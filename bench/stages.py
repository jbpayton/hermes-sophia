"""Stage-by-stage view of the night's model work on LoCoMo: what each stage costs and what it buys.

For each conversation, memories are built from the cached day memory by running only some night steps:
  ctx    contextualize only (model headers, re-embedded index text)
  rel    relate + integrate + index only (facts, no headers)
  full   contextualize + relate + integrate + index
Each variant is stored as bench/work/retr_<variant>_<conv>.db, then scored with retrieval.py --db-suffix <variant>.
Per-stage diagnostics: seconds, model calls, and for facts the share of evidence turns that yielded one.

  python bench/stages.py --convs conv-26 --variants ctx,rel
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from pathlib import Path

from common import DATA, RESULTS, add_model_args, memory_config
from hermes_sophia.engine import Engine
from hermes_sophia.sleep import SleepRunner
from locomo import ingest, sessions
from retrieval import evidence_refs

VARIANTS = {"ctx": ["contextualize"], "rel": ["relate", "integrate", "index"],
            "full": ["contextualize", "relate", "integrate", "index"]}


def build(conv, variant: str, args, work: Path) -> dict:
    sid, spk = conv["sample_id"], conv["conversation"]
    day = work / f"retr_day_{sid}.db"
    cfg = memory_config(args, user_name=spk["speaker_a"], agent_name="Assistant")
    cfg["sleep_guard_models"] = [args.yield_to] if args.yield_to else []
    if not day.exists():
        e = Engine(cfg, day)
        ingest(e, conv)
        e.close()
    dst = work / f"retr_{variant}{args.suffix}_{sid}.db"
    for x in ("", "-wal", "-shm"):
        Path(str(dst) + x).unlink(missing_ok=True)
        if Path(str(day) + x).exists():
            shutil.copy(str(day) + x, str(dst) + x)
    e = Engine(cfg, dst)
    t = time.time()
    out = SleepRunner(e, steps=VARIANTS[variant], max_wait_s=3600, log=lambda *_: None,
                      now=sessions(conv)[-1][1] + 3600).run()
    secs = round(time.time() - t, 1)
    n_win = e.store.one("SELECT COUNT(*) AS n FROM windows")["n"]
    diag = {"variant": variant, "conv": sid, "status": out["status"], "seconds": secs,
            "seconds_per_window": round(secs / max(n_win, 1), 3), "windows": n_win,
            "steps": {k: v for k, v in out["stats"].items() if k in VARIANTS[variant]}}
    if "relate" in VARIANTS[variant]:
        refs = evidence_refs(conv)
        ev = {refs[d] for q in conv["qa"] if q.get("category") in (1, 2, 3, 4)
              for d in re.findall(r"D\d+:\d+", " ".join(q.get("evidence") or [])) if d in refs}
        with_fact = {r["ref"] for r in e.store.q("""SELECT DISTINCT w.ref FROM fact_sources fs JOIN windows w
                                                     ON w.id=fs.window_id""")}
        diag["facts"] = e.store.one("SELECT COUNT(*) AS n FROM facts")["n"]
        diag["facts_per_window"] = round(diag["facts"] / max(n_win, 1), 3)
        diag["evidence_turns_with_a_fact"] = round(len(ev & with_fact) / max(len(ev), 1), 3)
    e.close()
    return diag


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--convs", default="conv-26")
    ap.add_argument("--variants", default="ctx,rel")
    ap.add_argument("--suffix", default="", help="appended to the variant name (for prompt experiments)")
    add_model_args(ap)
    args = ap.parse_args()
    data = {c["sample_id"]: c for c in json.loads((DATA / "locomo10.json").read_text())}
    work = RESULTS.parent / "work"
    for sid in args.convs.split(","):
        for v in args.variants.split(","):
            d = build(data[sid], v, args, work)
            d["suffix"] = args.suffix
            with open(RESULTS / "stages_runs.jsonl", "a") as f:
                f.write(json.dumps(d) + "\n")
            print(json.dumps(d), flush=True)


if __name__ == "__main__":
    main()
