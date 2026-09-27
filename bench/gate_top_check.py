"""Does the gate decide the same when it sees 5 memories instead of 10? Development cases only: LongMemEval dev
questions, a LoCoMo dev sample, Almanac's development lives (relevant and quiet questions), and off-topic prompts.

  python bench/gate_top_check.py --set decider_url=http://127.0.0.1:8081 --set decider_api=openai --almanac-dbs DIR,DIR,DIR
"""
from __future__ import annotations

import argparse
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import DATA, RESULTS, add_model_args, memory_config
from hermes_sophia.engine import Engine
from hermes_sophia.recall import GATE_INSTRUCTIONS
from longmemeval import ts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--almanac-dbs", default="", help="memory folders for Almanac's dev lives, in life order (life-01 first)")
    add_model_args(ap)
    args = ap.parse_args()
    here, work, rng = Path(__file__).parent, RESULTS.parent / "work", random.Random(3)
    lme = {x["question_id"]: x for x in json.loads((DATA / "longmemeval_s_cleaned.json").read_text())}
    off = json.loads((here / "gate_offtopic.json").read_text())["prompts"]
    cases = []
    for sample in ("dev60", "devpref"):
        for qid in json.loads((here / f"lme_{sample}.json").read_text())["ids"]:
            cases.append((work / "lme" / f"day_{qid}.db", lme[qid]["question"], ts(lme[qid]["question_date"]), "relevant", "lme"))
    convs = {c["sample_id"]: c for c in json.loads((DATA / "locomo10.json").read_text())}
    loc = [(work / f"locomo_sophia_dev_v5_{s}.db", qa["question"], None, "relevant", "locomo")
           for s in ("conv-26", "conv-30", "conv-41") for qa in convs[s]["qa"] if qa.get("category") != 5]
    cases += rng.sample(loc, 150)
    for i, s in enumerate(("conv-26", "conv-30", "conv-41")):
        cases += [(work / f"locomo_sophia_dev_v5_{s}.db", q, None, "off-topic", "locomo") for q in off[i * 20:(i + 1) * 20]]
    alm_lives = sorted(Path.home().joinpath("almanac/data/dev").glob("life-*.json"))
    for d, f in zip([Path(x) for x in args.almanac_dbs.split(",") if x], alm_lives):
        life = json.loads(f.read_text())
        import datetime as dt
        now = dt.datetime.fromisoformat(life["asked_at"]).timestamp()
        for q in life["questions"]:
            cases.append((d / "sophia.db", q["question"], now, "off-topic" if q["kind"] == "quiet" else "relevant", "almanac"))
        cases += [(d / "sophia.db", q, now, "off-topic", "almanac") for q in rng.sample(off, 15)]
    engines, jobs = {}, []
    for db, q, now, kind, src in cases:
        e = engines.get(db) or engines.setdefault(db, Engine(memory_config(args, user_name="User", agent_name="Assistant"), db))
        e.now_override = now
        items, _ = e.recall.candidates(q, e.cfg["recall_k"], session_id="g", now=now)
        if not items or items[0]["sim"] >= e.cfg["skip_gate"]:
            continue
        jobs.append((e, kind, src, q, items))

    def run(job):
        e, kind, src, q, items = job
        out = {"kind": kind, "src": src, "query": q}
        for n in (10, 5):
            state = {"message": q, "memories": [e.recall.short(it) for it in items[:n]]}
            out[f"p{n}"] = e.decider.noul(state, GATE_INSTRUCTIONS).noul
        return out
    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(run, jobs))
    for e in engines.values():
        e.close()
    (RESULTS / "gate_top_check.json").write_text(json.dumps(rows, indent=1))
    for src in ("lme", "locomo", "almanac"):
        for kind in ("relevant", "off-topic"):
            rs = [r for r in rows if r["src"] == src and r["kind"] == kind]
            if rs:
                print(f"{src:8} {kind:9} n={len(rs):3}  passed with 10: {sum(r['p10'] >= .5 for r in rs):3}  with 5: {sum(r['p5'] >= .5 for r in rs):3}  "
                      f"same decision {sum((r['p10'] >= .5) == (r['p5'] >= .5) for r in rs)}/{len(rs)}")


if __name__ == "__main__":
    main()
