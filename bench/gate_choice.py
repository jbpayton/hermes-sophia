"""One-call gate with a three-way choice (self-contained / about the user but no memory fits / a memory is relevant):
does it separate relevant from off-topic messages as well as two stages, at the cost of one request?
Development cases only; the same states the gate sees today (message + top 10 memories).

  python bench/gate_choice.py --url http://127.0.0.1:8090 --api openai --yield-to ""
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from pathlib import Path

from common import DATA, RESULTS, add_model_args, memory_config
from hermes_sophia.decider import Choice
from hermes_sophia.engine import Engine
from hermes_sophia.recall import GATE_INSTRUCTIONS
from longmemeval import ts

QUESTION = "What does this message need from memory?"
OPTIONS = {
    "general": "Nothing: it is a self-contained general request (a definition, fact, calculation, conversion, "
               "translation, joke, poem or code question) that needs nothing about the user.",
    "none_fit": "It is about the user or earlier conversations, but none of these memories bears on it.",
    "relevant": "At least one of these memories is relevant: it answers the message or states a fact the reply "
                "should take into account.",
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_model_args(ap)
    args = ap.parse_args()
    here, work, rng = Path(__file__).parent, RESULTS.parent / "work", random.Random(9)
    lme = {x["question_id"]: x for x in json.loads((DATA / "longmemeval_s_cleaned.json").read_text())}
    off = json.loads((here / "gate_offtopic.json").read_text())["prompts"]
    cases = []
    for s in ("dev60", "devpref"):
        for q in json.loads((here / f"lme_{s}.json").read_text())["ids"]:
            cases.append((work / "lme" / f"day_{q}.db", lme[q]["question"], ts(lme[q]["question_date"]), "relevant"))
    convs = {c["sample_id"]: c for c in json.loads((DATA / "locomo10.json").read_text())}
    loc = [(work / f"locomo_sophia_dev_v5_{s}.db", qa["question"], None, "relevant")
           for s in ("conv-26", "conv-30", "conv-41") for qa in convs[s]["qa"] if qa.get("category") != 5]
    cases += rng.sample(loc, 150)
    dbs = [work / "lme" / f"day_{q}.db" for q in json.loads((here / "lme_dev20.json").read_text())["ids"][:6]] + \
          [work / f"locomo_sophia_dev_v5_{s}.db" for s in ("conv-26", "conv-30", "conv-41")]
    cases += [(dbs[i % len(dbs)], p, None, "off-topic") for i, p in enumerate(off)]
    rows, engines = [], {}
    for db, q, now, kind in cases:
        e = engines.get(db) or engines.setdefault(db, Engine(memory_config(args, user_name="User", agent_name="Assistant"), db))
        e.now_override = now
        items, _ = e.recall.candidates(q, e.cfg["recall_k"], session_id="g", now=now)
        top = items[:e.cfg["gate_top"]]
        if not top or top[0]["sim"] >= e.cfg["skip_gate"]:
            rows.append({"kind": kind, "skip": True})
            continue
        state = {"message": q, "memories": [e.recall.short(it) for it in top]}
        row = {"kind": kind, "query": q, "skip": False}
        t = time.perf_counter(); row["yesno"] = e.decider.noul(state, GATE_INSTRUCTIONS).noul; row["ms_yesno"] = (time.perf_counter() - t) * 1000
        for perms in (1, 2):
            t = time.perf_counter()
            a = e.decider.ask(state, Choice(QUESTION, OPTIONS), permutations=perms)
            row[f"c{perms}"] = a.probabilities
            row[f"ms_c{perms}"] = (time.perf_counter() - t) * 1000
        rows.append(row)
    for e in engines.values():
        e.close()
    (RESULTS / "gate_choice.json").write_text(json.dumps(rows, indent=1))
    rel = [r for r in rows if r["kind"] == "relevant" and not r["skip"]]
    offr = [r for r in rows if r["kind"] == "off-topic" and not r["skip"]]
    print(f"gated cases: relevant {len(rel)}, off-topic {len(offr)} (strong matches skip the gate)")
    print(f"today (yes/no, 1 order, p>=0.5): relevant passed {sum(r['yesno'] >= .5 for r in rel)}, off-topic passed {sum(r['yesno'] >= .5 for r in offr)}; "
          f"median {statistics.median(r['ms_yesno'] for r in rel):.0f} ms")
    for perms in (1, 2):
        k = f"c{perms}"
        rules = {"relevant is the top choice": lambda p: max(p, key=p.get) == "relevant",
                 "relevant >= 0.3": lambda p: p["relevant"] >= 0.3,
                 "general < 0.5": lambda p: p["general"] < 0.5,
                 "general < 0.7": lambda p: p["general"] < 0.7}
        for name, f in rules.items():
            print(f"3-way, {perms} order(s), inject if {name:26}: relevant passed {sum(f(r[k]) for r in rel)}/{len(rel)}, "
                  f"off-topic passed {sum(f(r[k]) for r in offr)}/{len(offr)}")
        print(f"   median {statistics.median(r[f'ms_{k}'] for r in rel):.0f} ms")


if __name__ == "__main__":
    main()
