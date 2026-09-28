"""The passive path end to end (prefetch) on development memories, under each gate: how many messages get memory,
and how long the path takes. Relevant questions come from LongMemEval dev60/devpref and LoCoMo dev; general requests
and generic-sounding personal requests (where memory should be let in) from the held-out list, gate_heldout.json.
The first run used what is now gate_general_dev2.json as its held-out list (results/gate_check_round1.log).

  python bench/gate_check.py --url http://127.0.0.1:8090 --api openai --yield-to ""

Modes take turns going first per message, so each is timed cold (the local server caches the shared STATE prefix);
reported times are cold ones only.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from pathlib import Path

from common import DATA, RESULTS, add_model_args, memory_config
from hermes_sophia.engine import Engine
from longmemeval import ts

MODES = {
    "decider": {"gate": "decider"},
    "choice-recheck": {"gate": "choice", "gate_recheck": 0.05},
}
SESSION = "gate-check"


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
    held = json.loads((here / "gate_heldout.json").read_text())
    for kind, prompts in (("general (held out)", held["general"]), ("personal (held out)", held["personal"])):
        cases += [(dbs[i % len(dbs)], p, None, kind) for i, p in enumerate(prompts)]
    names, engines, rows = list(MODES), {}, []
    try:
        for i, (db, q, now, kind) in enumerate(cases):
            e = engines.get(db) or engines.setdefault(db, Engine(memory_config(args, user_name="User", agent_name="Assistant"), db))
            e.now_override = now
            order = names[i % len(names):] + names[:i % len(names)]
            row = {"kind": kind, "query": q, "cold": order[0]}
            for m in order:
                e.cfg.update(MODES[m])
                t = time.perf_counter()
                text, info = e.recall.prefetch(q, SESSION, now=now)
                row[m] = {"injected": bool(text), "gate": info.get("gate"), "uncertain": info.get("uncertain", False),
                          "split": info.get("split"), "ms": (time.perf_counter() - t) * 1000}
            rows.append(row)
    finally:
        for e in engines.values():
            e.store.x("DELETE FROM injections WHERE session_id=?", (SESSION,))
            e.close()
    (RESULTS / "gate_check.json").write_text(json.dumps(rows, indent=1))
    kinds = list(dict.fromkeys(r["kind"] for r in rows))
    for m in names:
        cold = sorted(r[m]["ms"] for r in rows if r["cold"] == m)
        parts = []
        for k in kinds:
            rs = [r for r in rows if r["kind"] == k]
            parts.append(f"{k} {sum(r[m]['injected'] for r in rs)}/{len(rs)}"
                         + (f" (possible-matches {sum(r[m]['uncertain'] for r in rs)})" if m != "decider" else ""))
        print(f"{m:15} memory injected: " + "; ".join(parts))
        print(f"{'':15} cold time: median {statistics.median(cold):.0f} ms, p90 {cold[int(.9 * len(cold))]:.0f} ms "
              f"(n={len(cold)})")
        split = [r[m]["split"] for r in rows if r["kind"] == "relevant" and r[m].get("split")]
        if split:
            print(f"{'':15} relevant questions: lines under Relevant {sum(a for a, _ in split)} of {sum(b for _, b in split)} "
                  f"injected, median {statistics.median(a for a, _ in split):.0f} per question; "
                  f"whole block marked possible: {sum(r[m]['uncertain'] for r in rows if r['kind'] == 'relevant')}")
    for k in ("general (held out)", "personal (held out)"):
        for m in names:
            flip = [r["query"] for r in rows if r["kind"] == k and r[m]["injected"] == (k.startswith("general"))]
            print(f"{k} wrong under {m}: {flip}")


if __name__ == "__main__":
    main()
