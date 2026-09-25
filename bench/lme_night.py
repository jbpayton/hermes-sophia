"""A cheap night for LongMemEval memories: model headers for the user's lines only, facts, integration on the decider.

Copies each cached day memory (bench/work/lme/day_<qid>.db) to night_<qid>.db and runs contextualize + relate +
integrate + index as of the question's date. The agent's replies (87% of LongMemEval's text) keep their cheap
daytime headers, which is what makes a night per question affordable.

  python bench/lme_night.py --sample dev60
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from common import DATA, RESULTS, add_model_args, memory_config
from hermes_sophia.engine import Engine
from hermes_sophia.sleep import SleepRunner
from longmemeval import ts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", default="dev60")
    add_model_args(ap)
    args = ap.parse_args()
    ids = json.loads((Path(__file__).parent / f"lme_{args.sample}.json").read_text())["ids"]
    by_id = {x["question_id"]: x for x in json.loads((DATA / "longmemeval_s_cleaned.json").read_text())}
    work = RESULTS.parent / "work" / "lme"
    log = []
    for qid in ids:
        src, dst = work / f"day_{qid}.db", work / f"night_{qid}.db"
        if not src.exists() or dst.exists():
            continue
        for x in ("", "-wal", "-shm"):
            if Path(str(src) + x).exists():
                shutil.copy(str(src) + x, str(dst) + x)
        cfg = memory_config(args, user_name="User", agent_name="Assistant")
        cfg.update(header_roles="user", night_judge="decider")
        cfg["sleep_guard_models"] = [args.yield_to] if args.yield_to else []
        e = Engine(cfg, dst)
        t = time.time()
        out = SleepRunner(e, steps=["contextualize", "relate", "integrate", "index"], max_wait_s=3600,
                          log=lambda *_: None, now=ts(by_id[qid]["question_date"])).run()
        rec = {"id": qid, "status": out["status"], "seconds": round(time.time() - t, 1),
               "facts": e.store.one("SELECT COUNT(*) AS n FROM facts")["n"]}
        e.close()
        log.append(rec)
        print(json.dumps(rec), flush=True)
    secs = [r["seconds"] for r in log]
    if secs:
        print(json.dumps({"nights": len(secs), "median_seconds": sorted(secs)[len(secs) // 2], "total_minutes": round(sum(secs) / 60, 1)}))


if __name__ == "__main__":
    main()
