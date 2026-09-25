"""Judge agreement: a stronger model re-grades a random sample of answers the default judge graded.

Reports how often the two judges agree and in which direction they disagree, so a benchmark number from a small
local judge can be read with its likely bias. Uses exactly the same judge prompts as the benchmark runs.

  python bench/judge_agreement.py --files results/locomo_sophia-night_heldout.jsonl --n 200 --judge qwen/qwen3.8-27b
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter

from common import DATA, RESULTS, Models, add_model_args


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--files", required=True, help="comma-separated results/*.jsonl")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=5)
    add_model_args(ap)
    args = ap.parse_args()
    models = Models(args)
    rows = []
    for f in args.files.split(","):
        rows += [dict(json.loads(l), _file=f) for l in open(f)]
    random.Random(args.seed).shuffle(rows)
    rows = rows[:args.n]
    lme = None
    tally, out = Counter(), []
    for r in rows:
        if "category" in r:                                   # LoCoMo row
            import locomo
            new = int(locomo.judge(models, r["question"], r["gold"], r["answer"]))
        else:                                                 # LongMemEval row
            import longmemeval
            if lme is None:
                lme = {x["question_id"]: x for x in json.loads((DATA / "longmemeval_s_cleaned.json").read_text())}
            new = int(longmemeval.judge(models, lme[r["id"]], r["response"]))
        tally[(r["correct"], new)] += 1
        out.append({"id": r["id"], "file": r["_file"], "default": r["correct"], "strong": new})
    n = sum(tally.values())
    summary = {"judge": args.judge, "n": n, "agree": round((tally[(1, 1)] + tally[(0, 0)]) / n, 3),
               "default_yes_strong_no": tally[(1, 0)], "default_no_strong_yes": tally[(0, 1)],
               "default_accuracy": round(sum(r["default"] for r in out) / n, 3),
               "strong_accuracy": round(sum(r["strong"] for r in out) / n, 3), "files": args.files}
    stems = [f.split("/")[-1].rsplit(".", 1)[0] for f in args.files.split(",")]
    name = "judge_agreement_" + "+".join(stems)                  # one summary per graded file set
    (RESULTS / f"{name}.summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
