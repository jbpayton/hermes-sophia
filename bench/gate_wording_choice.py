"""Second round of wording for the choice gate's "general" option, on development data only: relevant questions from
LongMemEval dev60/devpref and LoCoMo dev, general requests from gate_offtopic.json and gate_general_dev2.json, and
the personal requests in gate_general_dev2.json. Each wording is read the way the gate reads it (one order, the
reverse order too when "general" is between 0.05 and 0.95).

  python bench/gate_wording_choice.py --url http://127.0.0.1:8090 --api openai --yield-to ""
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
from longmemeval import ts

GENERAL = {
    "current": GATE_OPTIONS["general"],
    "same-for-anyone": "Nothing: a good reply would be the same for any user (general facts, explanations, writing, "
                       "calculations, translation or code), so nothing about this user or earlier conversations is "
                       "needed.",
    "longer-list": "Nothing: it is a self-contained general request (a definition, fact, explanation, calculation, "
                   "conversion, translation, joke, poem, piece of writing, list of ideas, how-to or code question) "
                   "that needs nothing about the user.",
    "principle": "Nothing: the message is a general request that any user could send, and a good reply needs nothing "
                 "about this user or earlier conversations.",
}

# the three-way gate as measured here (question and options frozen, so reruns measure the same thing)
GATE_QUESTION = "What does this message need from memory?"
GATE_OPTIONS = {
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
    dev2 = json.loads((here / "gate_general_dev2.json").read_text())
    general = json.loads((here / "gate_offtopic.json").read_text())["prompts"] + dev2["general"]
    cases += [(dbs[i % len(dbs)], p, None, "general") for i, p in enumerate(general)]
    cases += [(dbs[i % len(dbs)], p, None, "personal") for i, p in enumerate(dev2["personal"])]
    engines, states = {}, []
    for db, q, now, kind in cases:
        e = engines.get(db) or engines.setdefault(db, Engine(memory_config(args, user_name="User", agent_name="Assistant"), db))
        e.now_override = now
        items, _ = e.recall.candidates(q, e.cfg["recall_k"], session_id="w", now=now)
        top = items[:e.cfg["gate_top"]]
        if top and top[0]["sim"] < e.cfg["skip_gate"]:
            states.append((e, kind, q, {"message": q, "memories": [e.recall.short(it) for it in top]}))
    rows = []
    for name, text in GENERAL.items():
        options = {**GATE_OPTIONS, "general": text}
        for e, kind, q, state in states:
            t = time.perf_counter()
            a = e.decider.ask(state, Choice(GATE_QUESTION, options), permutations=1,
                              recheck=lambda p: 0.05 <= p["general"] <= 0.95)
            rows.append({"wording": name, "kind": kind, "query": q, "p": a.probabilities, "reads": len(a.raw),
                         "ms": (time.perf_counter() - t) * 1000})
    for e in engines.values():
        e.close()
    (RESULTS / "gate_wording_choice.json").write_text(json.dumps(rows, indent=1))
    kinds = ("relevant", "general", "personal")
    print("gated cases:", {k: sum(s[1] == k for s in states) for k in kinds}, "(strong matches skip the gate)")
    for name in GENERAL:
        rs = [r for r in rows if r["wording"] == name]
        parts = [f"{k} passed {sum(r['p']['general'] < .5 for r in rs if r['kind'] == k)}/{sum(r['kind'] == k for r in rs)}"
                 for k in kinds]
        print(f"{name:16} " + "; ".join(parts) + f"; second reading {sum(r['reads'] == 2 for r in rs)}/{len(rs)}; "
              f"median {statistics.median(r['ms'] for r in rs):.0f} ms")
        print(f"{'':16} relevant turned away: {[r['query'][:60] for r in rs if r['kind'] == 'relevant' and r['p']['general'] >= .5]}")
        print(f"{'':16} personal turned away: {[r['query'][:60] for r in rs if r['kind'] == 'personal' and r['p']['general'] >= .5]}")


if __name__ == "__main__":
    main()
