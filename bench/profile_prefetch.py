"""Where passive recall's time goes: candidates (embed + search + graph) vs the gate vs formatting.

  python bench/profile_prefetch.py --sample dev60 [--db-suffix day] [--set key=value]
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from common import DATA, RESULTS, add_model_args, memory_config
from hermes_sophia.engine import Engine
from longmemeval import ts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", default="dev60")
    ap.add_argument("--db-suffix", default="day")
    add_model_args(ap)
    args = ap.parse_args()
    ids = json.loads((Path(__file__).parent / f"lme_{args.sample}.json").read_text())["ids"]
    by_id = {x["question_id"]: x for x in json.loads((DATA / "longmemeval_s_cleaned.json").read_text())}
    work = RESULTS.parent / "work" / "lme"
    rows = []
    for qid in ids:
        db = work / f"{args.db_suffix}_{qid}.db"
        if not db.exists():
            continue
        item = by_id[qid]
        e = Engine(memory_config(args, user_name="User", agent_name="Assistant"), db)
        now = ts(item["question_date"])
        e.now_override = now
        r = e.recall
        t0 = time.perf_counter()
        items, info = r.candidates(item["question"], e.cfg["recall_k"], session_id="profile", now=now)
        t1 = time.perf_counter()
        text, pinfo = r.prefetch(item["question"], "profile", now=now)     # the whole passive path, as Hermes runs it
        t2 = time.perf_counter()
        rows.append({"id": qid, "windows": e.store.one("SELECT COUNT(*) AS n FROM windows")["n"],
                     "candidates_ms": (t1 - t0) * 1000, "prefetch_ms": (t2 - t1) * 1000, "gate": pinfo.get("gate", ""),
                     "chars": len(text or "")})
        e.close()
    def q(xs, p):
        xs = sorted(xs); return xs[min(len(xs) - 1, int(p * len(xs)))]
    for key in ("candidates_ms", "prefetch_ms"):
        xs = [r[key] for r in rows]
        print(f"{key:14} median {statistics.median(xs):6.0f}  p90 {q(xs, .9):6.0f}  max {max(xs):6.0f}")
    gated = [r["prefetch_ms"] - r["candidates_ms"] for r in rows if r["gate"].startswith("decider")]
    skipped = [r for r in rows if r["gate"].startswith("skip")]
    print(f"gate asked the decider on {len(gated)}/{len(rows)}; skipped (strong match) on {len(skipped)}; "
          f"median gate+format time when asked {statistics.median(gated) if gated else 0:.0f} ms")
    print(f"windows per memory: median {statistics.median(r['windows'] for r in rows):.0f}; injected chars median "
          f"{statistics.median(r['chars'] for r in rows):.0f}")
    (RESULTS / f"profile_prefetch_{args.sample}_{args.db_suffix}.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
