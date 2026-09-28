"""Gate and per-line split in one readout, development only. One question with options "nothing", "about the user
but none fits", and "memory [i] bears on it most directly" for each of the top 10; the gate is P(nothing), the
split is the per-memory distribution. Compared with today's three-way gate followed by a separate pick readout
(bench/split_study.py). Gate cases as in gate_wording_choice.py (dev only); split scored on LongMemEval's answer turns.

  python bench/combo_study.py --url http://127.0.0.1:8090 --api openai --yield-to ""
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
from split_study import PICK_Q, is_evidence, norm

COMBO_Q = ("What does this message need from memory? A memory bears on it when it answers the message or states a "
           "fact the reply should take into account.")

# the three-way gate as measured here (question and options frozen, so reruns measure the same thing)
GATE_QUESTION = "What does this message need from memory?"
GATE_OPTIONS = {
    "general": "Nothing: a good reply would be the same for any user (general facts, explanations, writing, "
               "calculations, translation or code), so nothing about this user or earlier conversations is needed.",
    "none_fit": "It is about the user or earlier conversations, but none of these memories bears on it.",
    "relevant": "At least one of these memories is relevant: it answers the message or states a fact the reply "
                "should take into account.",
}


def combo_options(n):
    return {"general": GATE_OPTIONS["general"],
            "none_fit": "It is about the user or earlier conversations, but none of these memories bears on it.",
            **{f"m{i + 1}": f"Memory [{i + 1}] bears on it most directly." for i in range(n)}}


def read(e, state, n, method):
    """(P(general), P(none fits), per-memory probabilities, reads, ms) for one message."""
    recheck = lambda p: 0.05 <= p["general"] <= 0.95
    t = time.perf_counter()
    if method == "combo":
        a = e.decider.ask(state, Choice(COMBO_Q, combo_options(n)), permutations=1, recheck=recheck)
        p = a.probabilities
        mem, reads = [p[f"m{i + 1}"] for i in range(n)], len(a.raw)
        g, nf = p["general"], p["none_fit"]
    else:                                           # three-way gate, then (when it opens) a separate pick
        a = e.decider.ask(state, Choice(GATE_QUESTION, GATE_OPTIONS), permutations=1, recheck=recheck)
        g, nf, reads, mem = a.probabilities["general"], a.probabilities["none_fit"], len(a.raw), [0.0] * n
        if g < 0.5:
            keys = {f"memory [{i + 1}]": None for i in range(n)}
            b = e.decider.ask(state, Choice(PICK_Q, {**keys, "none of them": None}), permutations=1)
            mem, reads = [b.probabilities[f"memory [{i + 1}]"] for i in range(n)], reads + 1
    return g, nf, mem, reads, (time.perf_counter() - t) * 1000


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_model_args(ap)
    args = ap.parse_args()
    here, work, rng = Path(__file__).parent, RESULTS.parent / "work", random.Random(9)
    lme = {x["question_id"]: x for x in json.loads((DATA / "longmemeval_s_cleaned.json").read_text())}
    cases = []
    for s in ("dev60", "devpref"):
        for q in json.loads((here / f"lme_{s}.json").read_text())["ids"]:
            item = lme[q]
            answers = [norm(t["content"]) for sess in item["haystack_sessions"] for t in sess if t.get("has_answer")]
            cases.append((work / "lme" / f"day_{q}.db", item["question"], ts(item["question_date"]), "relevant", answers))
    convs = {c["sample_id"]: c for c in json.loads((DATA / "locomo10.json").read_text())}
    loc = [(work / f"locomo_sophia_dev_v5_{s}.db", qa["question"], None, "relevant", None)
           for s in ("conv-26", "conv-30", "conv-41") for qa in convs[s]["qa"] if qa.get("category") != 5]
    cases += rng.sample(loc, 150)
    dbs = [work / "lme" / f"day_{q}.db" for q in json.loads((here / "lme_dev20.json").read_text())["ids"][:6]] + \
          [work / f"locomo_sophia_dev_v5_{s}.db" for s in ("conv-26", "conv-30", "conv-41")]
    dev2 = json.loads((here / "gate_general_dev2.json").read_text())
    general = json.loads((here / "gate_offtopic.json").read_text())["prompts"] + dev2["general"]
    cases += [(dbs[i % len(dbs)], p, None, "general", None) for i, p in enumerate(general)]
    cases += [(dbs[i % len(dbs)], p, None, "personal", None) for i, p in enumerate(dev2["personal"])]
    engines, rows = {}, []
    for i, (db, q, now, kind, answers) in enumerate(cases):
        e = engines.get(db) or engines.setdefault(db, Engine(memory_config(args, user_name="User", agent_name="Assistant"), db))
        e.now_override = now
        items, _ = e.recall.candidates(q, e.cfg["recall_k"], session_id="combo", now=now)
        top = items[:e.cfg["gate_top"]]
        if not top or top[0]["sim"] >= e.cfg["skip_gate"]:
            continue
        state = {"message": q, "memories": [f"[{j + 1}] {e.recall.short(it)}" for j, it in enumerate(top)]}
        row = {"kind": kind, "query": q,
               "evidence": [is_evidence(it["text"], answers) for it in top] if answers else None}
        for method in (["combo", "gate+pick"] if i % 2 else ["gate+pick", "combo"]):   # alternate who goes first
            g, nf, mem, reads, ms = read(e, state, len(top), method)
            row[method] = {"general": g, "none_fit": nf, "mem": mem, "reads": reads, "ms": ms}
        rows.append(row)
    for e in engines.values():
        e.close()
    (RESULTS / "combo_study.json").write_text(json.dumps(rows, indent=1))
    for m in ("gate+pick", "combo"):
        parts = [f"{k} passed {sum(r[m]['general'] < .5 for r in rows if r['kind'] == k)}/{sum(r['kind'] == k for r in rows)}"
                 for k in ("relevant", "general", "personal")]
        print(f"{m:10} gate: " + "; ".join(parts) + f"; reads per message {statistics.mean(r[m]['reads'] for r in rows):.2f}; "
              f"median {statistics.median(r[m]['ms'] for r in rows):.0f} ms; relevant-only median "
              f"{statistics.median(r[m]['ms'] for r in rows if r['kind'] == 'relevant'):.0f} ms")
        ev_rows = [r for r in rows if r["evidence"] is not None and r[m]["general"] < .5]
        ev = sum(sum(r["evidence"]) for r in ev_rows)
        for th in (0.02, 0.05, 0.1):
            if m == "combo":                          # memory mass is shared with the gate options: renormalize
                rel = [[p / max(sum(r[m]["mem"]), 1e-9) >= th for p in r[m]["mem"]] for r in ev_rows]
            else:
                rel = [[p >= th for p in r[m]["mem"]] for r in ev_rows]
            n = sum(sum(x) for x in rel)
            tp = sum(a and b for x, r in zip(rel, ev_rows) for a, b in zip(x, r["evidence"]))
            lost = sum(any(r["evidence"]) and not any(a and b for a, b in zip(x, r["evidence"])) for x, r in zip(rel, ev_rows))
            print(f"{'':10} split >= {th}: Relevant lines {n}/{sum(len(x) for x in rel)}; precision {tp / max(n, 1):.2f}; "
                  f"evidence kept Relevant {tp}/{ev}; questions whose evidence all went to Possible {lost}")


if __name__ == "__main__":
    main()
