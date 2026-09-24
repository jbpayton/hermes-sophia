"""Shared pieces of the Sophia benchmark harness: model calls, judges, a fresh memory per haystack, resumable results.

Every run records its exact setup (reader, judge, memory mode, config) next to its scores, because numbers from a
local reader and judge are not comparable with published numbers that use GPT-4o.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hermes_sophia.config import DEFAULTS  # noqa: E402
from hermes_sophia.engine import Engine  # noqa: E402
from hermes_sophia.lms import ModelServer  # noqa: E402
from hermes_sophia.sleep import SleepRunner  # noqa: E402

DATA = Path(os.environ.get("SOPHIA_BENCH_DATA", ROOT.parent / "bench-data"))
RESULTS = ROOT / "bench" / "results"

# The night's steps that build memory. Replay, rehearse and calibrate learn from live use, which a benchmark
# replay doesn't have; anticipate and tidy change nothing a question can see.
NIGHT_STEPS = ["settle", "sort", "contextualize", "relate", "integrate", "index", "promote", "views"]


def add_model_args(ap) -> None:
    ap.add_argument("--url", default="http://127.0.0.1:1234", help="model server for reader, judge and memory")
    ap.add_argument("--api", default="lmstudio", choices=["lmstudio", "openai"])
    ap.add_argument("--reader", default="qwen35-9b")
    ap.add_argument("--judge", default="qwen35-9b")
    ap.add_argument("--embed", default="nomic-embed")
    ap.add_argument("--decider", default="qwen35-9b")
    ap.add_argument("--night-model", default="qwen35-9b")
    ap.add_argument("--inject-chars", type=int, default=6000, help="size of Sophia's injected block")
    ap.add_argument("--graph-hops", type=int, default=1)
    ap.add_argument("--tag", default="", help="suffix for the results file")
    ap.add_argument("--yield-to", default="qwen/qwen3.8-27b",
                    help="pause while this LM Studio model is generating (someone's chat); '' to never pause")


class Models:
    def __init__(self, args):
        self.args = args
        self.server = ModelServer(args.url, os.path.expanduser(DEFAULTS["lms_cli"]), api=args.api)

    def wait_turn(self) -> None:
        """Benchmarks share the GPUs with real chat: wait while the guarded model is generating."""
        if not self.args.yield_to:
            return
        waited = 0
        while True:
            st = self.server.model_status() or {}
            if st.get(self.args.yield_to) != "generating":
                if waited:
                    print(f"  (resumed after yielding {waited}s to {self.args.yield_to})", flush=True)
                return
            time.sleep(2)
            waited += 2

    def read(self, prompt: str, max_tokens: int = 600) -> str:
        self.wait_turn()
        for attempt in range(3):
            try:
                return self.server.chat(self.args.reader, prompt, max_tokens=max_tokens, temperature=0.0, timeout=300)
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(5)
        return ""

    def judge(self, prompt: str, max_tokens: int = 10) -> str:
        self.wait_turn()
        for attempt in range(3):
            try:
                return self.server.chat(self.args.judge, prompt, max_tokens=max_tokens, temperature=0.0, timeout=120)
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(5)
        return ""


def memory_config(args, **identity) -> Dict[str, Any]:
    cfg = copy.deepcopy(DEFAULTS)
    cfg.update(lmstudio_url=args.url, embed_model=args.embed, embed_api=args.api, decider_model=args.decider,
               decider_api=args.api, sleep_model=args.night_model, sleep_api=args.api,
               inject_chars=args.inject_chars, graph_hops=args.graph_hops, embed_timeout=60.0, decider_timeout=60.0,
               sleep_call_timeout=600.0, **identity)
    cfg["sleep_guard_models"] = [args.night_model]
    cfg["lms_cli"] = os.path.expanduser(cfg["lms_cli"])
    return cfg


def fresh_engine(workdir: Path, name: str, cfg: Dict[str, Any]) -> Engine:
    db = workdir / f"{name}.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    return Engine(cfg, db)


def run_night(engine: Engine, args, now: float, log=lambda *_: None) -> Dict[str, Any]:
    r = SleepRunner(engine, model=args.night_model, max_wait_s=3600, steps=NIGHT_STEPS, log=log, now=now)
    return r.run()


class Results:
    """Append-only JSONL, so an interrupted run resumes where it stopped."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.rows: List[Dict[str, Any]] = []
        if path.exists():
            self.rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        self.done = {r["id"] for r in self.rows}

    def add(self, row: Dict[str, Any]) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.rows.append(row)
        self.done.add(row["id"])


def summarize(rows: Iterable[Dict[str, Any]], group_key: str) -> Dict[str, Any]:
    rows = list(rows)
    by = defaultdict(list)
    for r in rows:
        by[str(r[group_key])].append(r["correct"])
    groups = {k: {"n": len(v), "acc": round(sum(v) / len(v), 4)} for k, v in sorted(by.items())}
    n = len(rows)
    out = {"n": n, "accuracy": round(sum(r["correct"] for r in rows) / n, 4) if n else None, "by": groups}
    if groups:
        out["group_mean"] = round(sum(g["acc"] for g in groups.values()) / len(groups), 4)
    lat = [r.get("seconds", 0) for r in rows]
    out["mean_seconds_per_question"] = round(sum(lat) / n, 2) if n else None
    gates = [r["gate"] for r in rows if r.get("gate")]
    if gates:
        out["gate_passed_rate"] = round(sum(1 for r in rows if r.get("injected")) / n, 4)
    return out


def write_summary(path: Path, setup: Dict[str, Any], summary: Dict[str, Any]) -> None:
    path.write_text(json.dumps({"setup": setup, "summary": summary,
                                "written": dt.datetime.now().isoformat(timespec="seconds")}, indent=2))


def final_answer(text: str) -> str:
    m = re.search(r"(?im)^\s*answer\s*:\s*(.+)$", text or "")
    return (m.group(1) if m else (text or "")).strip()
