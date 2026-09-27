"""Gate latency and decisions on different model servers: the same 20 real gate states (from development memories),
each made unique so nothing is cached, asked through Sophia's own decider client.

  python bench/decider_servers.py --label lmstudio --decider-url http://127.0.0.1:1234 --decider-api lmstudio
  python bench/decider_servers.py --label llama-server --decider-url http://127.0.0.1:8081 --decider-api openai --model qwen35-9b
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from common import DATA, RESULTS, add_model_args, memory_config
from hermes_sophia.decider import Decider
from hermes_sophia.engine import Engine
from hermes_sophia.lms import ModelServer
from hermes_sophia.recall import GATE_INSTRUCTIONS
from longmemeval import ts


def states(args):
    here, work = Path(__file__).parent, RESULTS.parent / "work" / "lme"
    lme = {x["question_id"]: x for x in json.loads((DATA / "longmemeval_s_cleaned.json").read_text())}
    out = []
    for qid in json.loads((here / "lme_dev20.json").read_text())["ids"]:
        e = Engine(memory_config(args, user_name="User", agent_name="Assistant"), work / f"day_{qid}.db")
        now = ts(lme[qid]["question_date"])
        items, _ = e.recall.candidates(lme[qid]["question"], e.cfg["recall_k"], session_id="s", now=now)
        out.append({"message": lme[qid]["question"], "memories": [e.recall.short(it) for it in items[:e.cfg["gate_top"]]]})
        e.close()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", required=True)
    ap.add_argument("--decider-url", required=True)
    ap.add_argument("--decider-api", default="lmstudio", choices=["lmstudio", "openai"])
    ap.add_argument("--model", default="qwen35-9b")
    ap.add_argument("--rounds", type=int, default=2)
    add_model_args(ap)
    args = ap.parse_args()
    cache = RESULTS / "decider_servers_states.json"
    if not cache.exists():
        cache.write_text(json.dumps(states(args), indent=1))
    sts = json.loads(cache.read_text())
    d = Decider(ModelServer(args.decider_url, api=args.decider_api), args.model, permutations=1, timeout=30)
    d.noul({"message": "warm up", "memories": []}, GATE_INSTRUCTIONS)
    rows = []
    for r in range(args.rounds):
        for i, st in enumerate(sts):
            fresh = dict(st, case=f"{i}-{r}")                # unique: nothing cached from an earlier call
            t = time.perf_counter()
            p = d.noul(fresh, GATE_INSTRUCTIONS).noul
            rows.append({"case": i, "round": r, "ms": (time.perf_counter() - t) * 1000, "p": p})
        for i, st in enumerate(sts[:5]):                      # the same state again: the server's prompt cache
            t = time.perf_counter()
            d.noul(dict(st, case=f"{i}-{r}"), GATE_INSTRUCTIONS)
            rows.append({"case": i, "round": r, "ms": (time.perf_counter() - t) * 1000, "cached": True})
    fresh = [x["ms"] for x in rows if not x.get("cached")]
    cached = [x["ms"] for x in rows if x.get("cached")]
    print(f"{args.label:14} fresh median {statistics.median(fresh):4.0f} ms p90 {sorted(fresh)[int(.9 * len(fresh))]:4.0f} | "
          f"repeated (cached) median {statistics.median(cached):4.0f} ms")
    (RESULTS / f"decider_servers_{args.label}.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
