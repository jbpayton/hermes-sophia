"""Which relevance gate separates relevant from off-topic messages? For each development case, four readouts:
{state first, instructions first} x {options in order, reversed}; each variant's P(relevant) is computed from them.

  python bench/gate_variants.py
"""
from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import RESULTS, add_model_args, memory_config
from hermes_sophia.decider import LETTERS, Noul, _options, _prompt
from hermes_sophia.engine import Engine

# the gate question as it was when this was measured (the one-order gate that passed nearly everything)
GATE_INSTRUCTIONS = ("At least one memory item is directly relevant to the message: it answers it, or states a fact "
                     "the reply should take into account.")
QUIET = ["What's a good synonym for 'quick'?", "Write me a two-line poem about rain.", "How many ounces are in a cup?"]


def _prompt_first(state_text, instructions, descs, qtype):
    """Instructions first, state last (tested as a way to let the server's prompt cache reuse the fixed part)."""
    opts = "\n".join(f"{LETTERS[i]}) {d}" for i, d in enumerate(descs))
    return (f"QUESTION: {instructions}\nDecide whether the statement is true of the STATE.\nOptions:\n{opts}\n"
            f"Answer with the single letter only.\n\nSTATE:\n{state_text}\n\nAnswer:")


def p_true(client, model, prompt, order):
    _, tops = client.first_token_logprobs(model, prompt, 10, 30.0)
    lp = {}
    for tok, v in tops:
        t = tok.strip()
        if len(t) == 1 and t in LETTERS[:2]:
            lp[t] = max(lp.get(t, -1e9), v)
    if not lp:
        return None
    floor = min(lp.values()) - 5
    a, b = lp.get("A", floor), lp.get("B", floor)
    m = max(a, b); pa, pb = math.exp(a - m), math.exp(b - m)
    probs = [pa / (pa + pb), pb / (pa + pb)]           # letters as shown
    shown_true = order.index(1)                       # where "true" was shown
    return probs[shown_true]


def main():
    ap = argparse.ArgumentParser(); add_model_args(ap); args = ap.parse_args()
    keys, descs, qt = _options(Noul(GATE_INSTRUCTIONS))      # ["false", "true"]
    # rebuild the same cases (db, query, now, kind) and their gate states
    import sys
    sys.argv = [sys.argv[0], "--yield-to", ""]
    cases = []
    here = Path(__file__).parent
    for db, query, now, kind in V_cases():
        cases.append((db, query, now, kind))
    engines, jobs = {}, []
    for db, query, now, kind in cases:
        e = engines.get(db) or engines.setdefault(db, Engine(memory_config(args, user_name="User", agent_name="Assistant"), db))
        e.now_override = now
        items, _ = e.recall.candidates(query, e.cfg["recall_k"], session_id="v", now=now)
        top = items[:e.cfg["gate_top"]]
        if not top or top[0]["sim"] >= e.cfg["skip_gate"]:
            continue
        st = json.dumps({"message": query, "memories": [e.recall.short(it) for it in top]}, ensure_ascii=False, indent=1)
        jobs.append((e, kind, query, st))
    def run(job):
        e, kind, query, st = job
        out = {"kind": kind, "query": query}
        for layout, build in (("state", _prompt), ("instr", _prompt_first)):
            for oname, order in (("fwd", [0, 1]), ("rev", [1, 0])):
                out[f"{layout}_{oname}"] = p_true(e.client if hasattr(e, "client") else e.decider.client, e.cfg["decider_model"],
                                                  build(st, GATE_INSTRUCTIONS, [descs[i] for i in order], qt), order)
        return out
    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(run, jobs))
    for e in engines.values():
        e.close()
    (RESULTS / "gate_variants.json").write_text(json.dumps(rows, indent=1))
    variants = {"state, one order (current)": lambda r: r["state_fwd"],
                "state, both orders": lambda r: (r["state_fwd"] + r["state_rev"]) / 2,
                "instructions first, one order": lambda r: r["instr_fwd"],
                "instructions first, both orders": lambda r: (r["instr_fwd"] + r["instr_rev"]) / 2}
    rel = [r for r in rows if r["kind"] != "quiet"]; quiet = [r for r in rows if r["kind"] == "quiet"]
    for name, f in variants.items():
        ok = [r for r in rows if all(r[k] is not None for k in ("state_fwd", "state_rev", "instr_fwd", "instr_rev"))]
        rr = [f(r) for r in ok if r["kind"] != "quiet"]; qq = [f(r) for r in ok if r["kind"] == "quiet"]
        auc = sum((a > b) + 0.5 * (a == b) for a in rr for b in qq) / (len(rr) * len(qq))
        line = f"{name:34} AUC {auc:.3f} |"
        for th in (0.5, 0.7, 0.9):
            line += f" t={th}: pass {sum(x >= th for x in rr)}/{len(rr)} relevant, {sum(x >= th for x in qq)}/{len(qq)} off-topic |"
        print(line)


def V_cases():
    import json as _j
    from common import DATA
    from longmemeval import ts
    here = Path(__file__).parent
    lme = {x["question_id"]: x for x in _j.loads((DATA / "longmemeval_s_cleaned.json").read_text())}
    work = RESULTS.parent / "work"
    for sample in ("dev60", "devpref"):
        for qid in _j.loads((here / f"lme_{sample}.json").read_text())["ids"]:
            db = work / "lme" / f"day_{qid}.db"
            if db.exists():
                yield db, lme[qid]["question"], ts(lme[qid]["question_date"]), "lme"
    for qid in _j.loads((here / "lme_dev20.json").read_text())["ids"][:10]:
        for q in QUIET:
            yield work / "lme" / f"day_{qid}.db", q, ts(lme[qid]["question_date"]), "quiet"
    convs = {c["sample_id"]: c for c in _j.loads((DATA / "locomo10.json").read_text())}
    for sid in ("conv-26", "conv-30", "conv-41"):
        for qa in convs[sid]["qa"]:
            if qa.get("category") != 5:
                yield work / f"locomo_sophia_dev_v5_{sid}.db", qa["question"], None, "locomo"


if __name__ == "__main__":
    main()
