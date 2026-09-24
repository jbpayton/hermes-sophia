"""Typed decisions from any chat model by reading first-token logprobs (Jev-style, prefill only).

Every option is a single-letter label; the probability of each letter at the first output position,
renormalized over the declared letters, is the answer. Reading twice with the options reversed and
averaging controls position bias; ``flip`` reports disagreement between the two readings.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from .lms import LMStudio, LMStudioError

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@dataclass(frozen=True)
class Choice:
    instructions: str
    criteria: Dict[str, Optional[str]]


@dataclass(frozen=True)
class Noul:
    instructions: str
    criteria: Optional[Dict[str, str]] = None


@dataclass(frozen=True)
class Score:
    instructions: str
    criteria: Sequence[str]


@dataclass
class Answer:
    type: str
    keys: List[str]
    probabilities: Dict[str, float]
    flip: bool
    latency_ms: float
    decision_id: str = ""
    raw: List[Dict[str, float]] = field(default_factory=list)

    @property
    def choice(self) -> str:
        return max(self.probabilities, key=self.probabilities.get)

    @property
    def noul(self) -> float:
        return self.probabilities.get("true", 0.0)

    @property
    def score(self) -> float:
        return sum(int(k) * p for k, p in self.probabilities.items()) if self.type == "score" else float("nan")

    @property
    def confidence(self) -> float:
        k = len(self.probabilities)
        p = max(self.probabilities.values())
        return (p - 1.0 / k) / (1.0 - 1.0 / k) if k > 1 else 1.0


class DeciderError(RuntimeError):
    pass


def _options(q):
    if isinstance(q, Choice):
        return list(q.criteria), [k if not v else f"{k}: {v}" for k, v in q.criteria.items()], "choice"
    if isinstance(q, Noul):
        c = q.criteria or {}
        return ["false", "true"], [f"false: {c.get('false', 'no, the statement does not hold')}",
                                   f"true: {c.get('true', 'yes, the statement holds')}"], "noul"
    if isinstance(q, Score):
        return [str(i) for i in range(len(q.criteria))], [f"level {i}: {d}" for i, d in enumerate(q.criteria)], "score"
    raise DeciderError(f"unknown question type {type(q).__name__}")


def _prompt(state_text: str, instructions: str, descs: List[str], qtype: str) -> str:
    opts = "\n".join(f"{LETTERS[i]}) {d}" for i, d in enumerate(descs))
    tail = {"choice": "Choose the single best option.", "noul": "Decide whether the statement is true of the STATE.",
            "score": "Rate the STATE on the ordered levels."}[qtype]
    return (f"STATE:\n{state_text}\n\nQUESTION: {instructions}\n{tail}\nOptions:\n{opts}\n"
            f"Answer with the single letter only.")


def _softmax(v: List[float]) -> List[float]:
    m = max(v)
    w = [math.exp(x - m) for x in v]
    s = sum(w)
    return [x / s for x in w]


class Decider:
    def __init__(self, client: LMStudio, model: str, *, permutations: int = 1, timeout: float = 8.0,
                 temperatures: Optional[Dict[str, float]] = None, top_logprobs: int = 10,
                 log: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.client, self.model = client, model
        self.permutations = max(1, min(2, permutations))
        self.timeout = timeout
        self.temperatures = {"choice": 1.0, "noul": 1.0, "score": 1.0, **(temperatures or {})}
        self.top_logprobs = top_logprobs
        self.log = log

    def ask(self, state: Any, q, permutations: Optional[int] = None) -> Answer:
        keys, descs, qtype = _options(q)
        k = len(keys)
        if not 2 <= k <= len(LETTERS):
            raise DeciderError(f"need 2..{len(LETTERS)} options, got {k}")
        perms = self.permutations if permutations is None else max(1, min(2, permutations))
        orders = [list(range(k))] + ([list(range(k))[::-1]] if perms == 2 else [])
        state_text = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False, indent=1)
        t0 = time.perf_counter()
        per_order, raws = [], []
        for order in orders:
            prompt = _prompt(state_text, q.instructions, [descs[i] for i in order], qtype)
            try:
                _, tops = self.client.first_token_logprobs(self.model, prompt, max(self.top_logprobs, k), self.timeout)
            except LMStudioError as e:
                raise DeciderError(str(e)) from e
            letter_lp: Dict[str, float] = {}
            for tok, lp in tops:
                t = tok.strip()
                if len(t) == 1 and t in LETTERS[:k]:
                    letter_lp[t] = max(letter_lp.get(t, -1e9), lp)
            if not letter_lp:
                raise DeciderError(f"no option letters among top tokens {[t for t, _ in tops][:5]}")
            raws.append(letter_lp)
            probs = _softmax([letter_lp.get(LETTERS[j], -30.0) / self.temperatures[qtype] for j in range(k)])
            declared = [0.0] * k
            for j, oi in enumerate(order):
                declared[oi] = probs[j]
            per_order.append(declared)
        probs = [sum(p[i] for p in per_order) / len(per_order) for i in range(k)]
        flip = len(per_order) > 1 and (max(range(k), key=lambda i: per_order[0][i]) !=
                                       max(range(k), key=lambda i: per_order[1][i]))
        ans = Answer(qtype, keys, {keys[i]: probs[i] for i in range(k)}, flip, (time.perf_counter() - t0) * 1000,
                     raw=raws)
        if self.log:
            rec = {"ts": time.time(), "model": self.model, "type": qtype,
                   "state_sha": hashlib.sha1(state_text.encode()).hexdigest()[:16],
                   "instructions": q.instructions, "options": keys, "probabilities": probs, "raw": raws,
                   "flip": int(flip)}
            rec["id"] = hashlib.sha1(json.dumps(rec, sort_keys=True, default=str).encode()).hexdigest()[:16]
            ans.decision_id = rec["id"]
            try:
                self.log(rec)
            except Exception:
                pass
        return ans

    def noul(self, state: Any, instructions: str, criteria: Optional[Dict[str, str]] = None, **kw) -> Answer:
        return self.ask(state, Noul(instructions, criteria), **kw)

    def choice(self, state: Any, instructions: str, criteria: Dict[str, Optional[str]], **kw) -> Answer:
        return self.ask(state, Choice(instructions, criteria), **kw)


def fit_temperature(pairs: List[tuple]) -> float:
    """Golden-section search for the temperature minimizing NLL. pairs = [(letter_logprobs_list, gold_index)]."""
    def nll(T):
        tot = 0.0
        for lps, g in pairs:
            p = _softmax([x / T for x in lps])
            tot -= math.log(max(p[g], 1e-12))
        return tot / len(pairs)
    lo, hi = 0.2, 5.0
    phi = (math.sqrt(5) - 1) / 2
    a, b = hi - phi * (hi - lo), lo + phi * (hi - lo)
    for _ in range(40):
        if nll(a) < nll(b):
            hi, b, a = b, a, hi - phi * (hi - lo)
        else:
            lo, a, b = a, b, lo + phi * (hi - lo)
    t = round((lo + hi) / 2, 3)
    return t, nll(1.0), nll(t)
