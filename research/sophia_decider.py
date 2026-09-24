"""sophia_decider — typed decisions from any chat model via a one-token logprob readout.

Works against LM Studio's OpenAI-compatible server (``/v1/responses`` with reasoning off and
``top_logprobs``). Same idea as Jev / SemIf / jobe / reflex: prefill only, read the probability
of each option's letter at the first output position, renormalize over the declared letters.

Primitives (same shapes as TypeSafe's wire format so a Jev or reflex backend can swap in later):
    choice(state, instructions, criteria={key: description|None}) -> ChoiceAnswer
    noul(state, instructions, criteria={"true": ..., "false": ...} | None) -> NoulAnswer
    score(state, instructions, criteria=[level0, level1, ...]) -> ScoreAnswer
    system_one(state, questions={qid: Choice|Noul|Score}) -> {qid: answer}   (fan-out, concurrent)

Design notes:
  * STATE goes first and QUESTION last so LM Studio's prefix cache serves fan-out questions.
  * Every option is a single-token letter; yes/no is rendered as letters too so probability
    mass doesn't split across "yes"/"Yes"/" yes".
  * Each question is read twice with the option order reversed and the two distributions are
    averaged (position-bias control, as in reflex/jobe). ``flip`` tells you if the two readings
    disagreed — a cheap "escalate this one" signal.
  * Probabilities are UNCALIBRATED until you fit a temperature: log decisions with ``log_path``,
    record outcomes with ``record_outcome``, then ``fit_temperature`` and pass ``temperatures``.
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import math
import os
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


# --------------------------------------------------------------------------- question types
@dataclass(frozen=True)
class Choice:
    instructions: str
    criteria: Dict[str, Optional[str]]  # key -> description (None = key only)

@dataclass(frozen=True)
class Noul:
    instructions: str
    criteria: Optional[Dict[str, str]] = None  # {"true": "...", "false": "..."}

@dataclass(frozen=True)
class Score:
    instructions: str
    criteria: Sequence[str]  # ordered level descriptions, index 0 = lowest


# --------------------------------------------------------------------------- answers
@dataclass
class ChoiceAnswer:
    type: str
    choice: str
    probabilities: Dict[str, float]
    confidence: float          # chance-corrected: (p_max - 1/K) / (1 - 1/K)
    margin: float              # p_top - p_second
    flip: bool                 # did the reversed-order reading pick a different option?
    latency_ms: float
    raw: List[Dict[str, float]] = field(default_factory=list)  # per-order letter logprobs

@dataclass
class NoulAnswer:
    type: str
    noul: float                # P(true)
    flip: bool
    latency_ms: float
    raw: List[Dict[str, float]] = field(default_factory=list)

@dataclass
class ScoreAnswer:
    type: str
    score: float               # probability-weighted level index
    probabilities: Dict[str, float]
    legend: Dict[str, str]
    confidence: float
    flip: bool
    latency_ms: float
    raw: List[Dict[str, float]] = field(default_factory=list)


class DeciderError(RuntimeError):
    pass


# --------------------------------------------------------------------------- the decider
class Decider:
    def __init__(self, base_url: str = "http://127.0.0.1:1234", model: str = "qwen35-9b", *,
                 top_logprobs: int = 10, permutations: int = 2, timeout: float = 60.0,
                 temperatures: Optional[Dict[str, float]] = None, log_path: Optional[str] = None,
                 max_workers: int = 4):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.top_logprobs = top_logprobs
        self.permutations = max(1, min(2, permutations))
        self.timeout = timeout
        self.temperatures = {"choice": 1.0, "noul": 1.0, "score": 1.0, **(temperatures or {})}
        self.log_path = log_path
        self.max_workers = max_workers

    # ---- public primitives ------------------------------------------------
    def choice(self, state: Any, instructions: str, criteria: Dict[str, Optional[str]]) -> ChoiceAnswer:
        return self._decide(state, Choice(instructions, criteria))

    def noul(self, state: Any, instructions: str, criteria: Optional[Dict[str, str]] = None) -> NoulAnswer:
        return self._decide(state, Noul(instructions, criteria))

    def score(self, state: Any, instructions: str, criteria: Sequence[str]) -> ScoreAnswer:
        return self._decide(state, Score(instructions, list(criteria)))

    def system_one(self, state: Any, questions: Dict[str, Any]) -> Dict[str, Any]:
        """Answer several questions about one state concurrently (prefix cache makes this cheap)."""
        with cf.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futs = {qid: ex.submit(self._decide, state, q) for qid, q in questions.items()}
            return {qid: f.result() for qid, f in futs.items()}

    # ---- core -------------------------------------------------------------
    def _decide(self, state: Any, q: Any):
        keys, descs, qtype = self._options(q)
        k = len(keys)
        if not 2 <= k <= len(LETTERS):
            raise DeciderError(f"need 2..{len(LETTERS)} options, got {k}")
        orders = [list(range(k))] + ([list(range(k))[::-1]] if self.permutations == 2 and k > 1 else [])
        t0 = time.perf_counter()
        per_order_probs: List[List[float]] = []
        raws: List[Dict[str, float]] = []
        state_text = self._render_state(state)
        for order in orders:
            prompt = self._render_prompt(state_text, q.instructions, [descs[i] for i in order], qtype)
            letter_lp = self._readout(prompt, k)                        # letter -> logprob (declared order of letters)
            raws.append(letter_lp)
            # map back: letter j in this order corresponds to option order[j]
            lps = [letter_lp.get(LETTERS[j], -30.0) for j in range(k)]
            probs_this = self._softmax([lp / self.temperatures[qtype] for lp in lps])
            probs_declared = [0.0] * k
            for j, opt_idx in enumerate(order):
                probs_declared[opt_idx] = probs_this[j]
            per_order_probs.append(probs_declared)
        probs = [sum(p[i] for p in per_order_probs) / len(per_order_probs) for i in range(k)]
        flip = len(per_order_probs) > 1 and (max(range(k), key=lambda i: per_order_probs[0][i]) !=
                                               max(range(k), key=lambda i: per_order_probs[1][i]))
        latency = (time.perf_counter() - t0) * 1000
        ans = self._package(q, qtype, keys, probs, flip, latency, raws)
        self._log(state_text, q, qtype, keys, probs, ans, raws)
        return ans

    @staticmethod
    def _options(q) -> Tuple[List[str], List[str], str]:
        if isinstance(q, Choice):
            keys = list(q.criteria.keys())
            descs = [k if (v is None or v == "") else f"{k}: {v}" for k, v in q.criteria.items()]
            return keys, descs, "choice"
        if isinstance(q, Noul):
            c = q.criteria or {}
            return ["false", "true"], [f"false: {c.get('false', 'no, the statement does not hold')}",
                                       f"true: {c.get('true', 'yes, the statement holds')}"], "noul"
        if isinstance(q, Score):
            keys = [str(i) for i in range(len(q.criteria))]
            return keys, [f"level {i}: {d}" for i, d in enumerate(q.criteria)], "score"
        raise DeciderError(f"unknown question type {type(q).__name__}")

    @staticmethod
    def _render_state(state: Any) -> str:
        return state if isinstance(state, str) else json.dumps(state, ensure_ascii=False, indent=1)

    @staticmethod
    def _render_prompt(state_text: str, instructions: str, descs: List[str], qtype: str) -> str:
        opts = "\n".join(f"{LETTERS[i]}) {d}" for i, d in enumerate(descs))
        tail = {"choice": "Choose the single best option.",
                "noul": "Decide whether the statement is true of the STATE.",
                "score": "Rate the STATE on the ordered levels."}[qtype]
        return (f"STATE:\n{state_text}\n\nQUESTION: {instructions}\n{tail}\nOptions:\n{opts}\n"
                f"Answer with the single letter only.")

    def _readout(self, prompt: str, k: int) -> Dict[str, float]:
        body = {"model": self.model, "input": prompt, "max_output_tokens": 2, "temperature": 0,
                "top_logprobs": max(self.top_logprobs, k), "reasoning": {"effort": "none"},
                "include": ["message.output_text.logprobs"]}
        req = urllib.request.Request(self.base_url + "/v1/responses", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            resp = json.loads(r.read())
        msgs = [o for o in resp.get("output", []) if o.get("type") == "message"]
        if not msgs:
            kinds = [o.get("type") for o in resp.get("output", [])]
            raise DeciderError(f"no message in response (got {kinds}); is reasoning disabled for {self.model}?")
        content = msgs[0]["content"][0]
        lp = content.get("logprobs") or []
        if not lp:
            raise DeciderError("no logprobs returned; the endpoint must support top_logprobs")
        first = lp[0]
        out: Dict[str, float] = {}
        for t in first.get("top_logprobs", []):
            tok = (t.get("token") or "").strip()
            if len(tok) == 1 and tok in LETTERS[:k]:
                # keep the max over variants like "A" and " A"
                out[tok] = max(out.get(tok, -1e9), float(t["logprob"]))
        if not out:
            raise DeciderError(f"no option letters in top_logprobs; first token was {first.get('token')!r}")
        return out

    @staticmethod
    def _softmax(vals: List[float]) -> List[float]:
        m = max(vals); w = [math.exp(v - m) for v in vals]; s = sum(w)
        return [x / s for x in w]

    @staticmethod
    def _package(q, qtype, keys, probs, flip, latency, raws):
        k = len(keys)
        order = sorted(range(k), key=lambda i: -probs[i])
        p1, p2 = probs[order[0]], (probs[order[1]] if k > 1 else 0.0)
        conf = (p1 - 1.0 / k) / (1.0 - 1.0 / k)
        if qtype == "noul":
            return NoulAnswer("noul", probs[1], flip, latency, raws)
        if qtype == "score":
            score = sum(i * p for i, p in enumerate(probs))
            return ScoreAnswer("score", score, {keys[i]: probs[i] for i in range(k)},
                               {str(i): d for i, d in enumerate(q.criteria)}, conf, flip, latency, raws)
        return ChoiceAnswer("choice", keys[order[0]], {keys[i]: probs[i] for i in range(k)}, conf, p1 - p2, flip, latency, raws)

    # ---- logging & calibration ------------------------------------------
    def _log(self, state_text, q, qtype, keys, probs, ans, raws):
        if not self.log_path:
            return
        rec = {"ts": time.time(), "model": self.model, "type": qtype,
               "state_sha": hashlib.sha256(state_text.encode()).hexdigest()[:16],
               "instructions": q.instructions, "options": keys, "probabilities": probs,
               "raw_letter_logprobs": raws, "flip": getattr(ans, "flip", False),
               "latency_ms": round(ans.latency_ms, 1), "gold": None}
        rec["id"] = hashlib.sha256(json.dumps(rec, sort_keys=True, default=str).encode()).hexdigest()[:16]
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec["id"]

    @staticmethod
    def record_outcome(log_path: str, decision_id: str, gold: str) -> None:
        """Append a gold label for a logged decision (what the LLM / user later confirmed)."""
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"outcome_for": decision_id, "gold": gold, "ts": time.time()}) + "\n")

    @staticmethod
    def fit_temperature(log_path: str, qtype: str) -> float:
        """Golden-section search for the temperature minimizing NLL on logged decisions with outcomes."""
        recs, golds = {}, {}
        for line in open(log_path, encoding="utf-8"):
            r = json.loads(line)
            if "outcome_for" in r:
                golds[r["outcome_for"]] = r["gold"]
            elif r.get("type") == qtype:
                recs[r["id"]] = r
        pairs = []
        for rid, gold in golds.items():
            r = recs.get(rid)
            if r and gold in r["options"] and r["raw_letter_logprobs"]:
                lps = [r["raw_letter_logprobs"][0].get(LETTERS[j], -30.0) for j in range(len(r["options"]))]
                pairs.append((lps, r["options"].index(gold)))
        if len(pairs) < 10:
            raise DeciderError(f"need at least 10 labelled {qtype} decisions, have {len(pairs)}")
        def nll(T):
            tot = 0.0
            for lps, g in pairs:
                p = Decider._softmax([x / T for x in lps]); tot -= math.log(max(p[g], 1e-12))
            return tot / len(pairs)
        lo, hi = 0.2, 5.0; phi = (math.sqrt(5) - 1) / 2
        a, b = hi - phi * (hi - lo), lo + phi * (hi - lo)
        for _ in range(40):
            if nll(a) < nll(b): hi, b, a = b, a, hi - phi * (hi - lo)
            else: lo, a, b = a, b, lo + phi * (hi - lo)
        return round((lo + hi) / 2, 3)


# --------------------------------------------------------------------------- self-test
if __name__ == "__main__":
    import sys
    model = sys.argv[1] if len(sys.argv) > 1 else "qwen35-9b"
    d = Decider(model=model, log_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "decisions.jsonl"))
    query = "What camera did Joey use for the Yosemite trip?"
    triples = ["Joey visited Yosemite in May 2025", "Joey hiked Half Dome with Sam", "Yosemite trip lasted four days",
               "Joey stayed at Curry Village", "Sam brought a drone to Yosemite", "Joey prefers hiking in spring",
               "Joey drove from San Jose to Yosemite"]
    doors = {"joey_photography_gear": "9 triples about Joey's cameras, lenses and photo habits",
             "sam": "6 triples about Sam, Joey's hiking partner", "half_dome": "4 triples about the Half Dome hike",
             "curry_village": "3 triples about the lodging", "san_jose": "12 triples about Joey's home city",
             "back": "none of these doors lead toward the query; return to the previous room",
             "stop_here": "this room already contains the answer to the query"}
    def room(extra=None):
        return {"query": query, "current_room": "Yosemite trip", "breadcrumb": ["Joey", "Travel", "Yosemite trip"],
                "triples_in_room": triples + ([extra] if extra else []),
                "doors": {k: v for k, v in doors.items() if k not in ("back", "stop_here")}}
    questions = {
        "found_here": Noul("At least one triple in triples_in_room directly answers the query."),
        "any_door_leads_on": Noul("At least one door in doors leads to a room likely to contain the answer."),
        "next_action": Choice("Which action best advances answering the query from this room?", doors),
        "room_relevance": Score("How relevant is this room's content to the query?",
                                ["unrelated", "tangential", "related", "directly answers"]),
    }
    for label, extra in [("answer NOT in room", None), ("answer IS in room", "Joey used a Fujifilm X-T5 at Yosemite")]:
        t0 = time.perf_counter(); ans = d.system_one(room(extra), questions); wall = (time.perf_counter() - t0) * 1000
        print(f"\n== {label}  (4 questions x 2 orders, wall {wall:.0f} ms) ==")
        print(f"  found_here        P(true)={ans['found_here'].noul:.3f} flip={ans['found_here'].flip}")
        print(f"  any_door_leads_on P(true)={ans['any_door_leads_on'].noul:.3f}")
        na = ans["next_action"]
        print(f"  next_action       {na.choice}  conf={na.confidence:.2f} margin={na.margin:.2f} flip={na.flip}  "
              + ", ".join(f"{k}={v:.2f}" for k, v in sorted(na.probabilities.items(), key=lambda kv: -kv[1])[:3]))
        rr = ans["room_relevance"]
        print(f"  room_relevance    score={rr.score:.2f} ({rr.legend[str(round(rr.score))]}) conf={rr.confidence:.2f}")
    print(f"\ndecisions logged to {d.log_path}")
