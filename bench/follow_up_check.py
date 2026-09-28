"""Short follow-ups ("and in French?", "when did she read that one?") through the real passive path: the previous
turn is captured in the same session first, then the follow-up is recalled. Follow-ups to a general request should get
no memory; follow-ups about the people in memory should. Pairs were written by hand for LoCoMo conv-26 (a dev
conversation), on a scratch copy of its memory.

  python bench/follow_up_check.py --url http://127.0.0.1:8090 --api openai --yield-to ""
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import statistics
from pathlib import Path

from common import RESULTS, add_model_args, memory_config
from hermes_sophia.engine import Engine

GENERAL = [
    ("Write a haiku about autumn leaves.", "Now make it rhyme."),
    ("Convert 5 kilometres to miles.", "And 10?"),
    ("Translate 'thank you very much' into Spanish.", "What about in French?"),
    ("How do I reverse a list in Python?", "And in JavaScript?"),
    ("Tell me a short joke about penguins.", "Another one about them?"),
    ("Explain photosynthesis in one sentence.", "Can you make it simpler for a child?"),
    ("What's the boiling point of water in Fahrenheit?", "And in Kelvin?"),
    ("Write a limerick about a cat who loves boxes.", "Make it about a dog instead."),
    ("Draft a polite email declining a meeting invitation.", "Make it shorter."),
    ("What is the difference between TCP and UDP?", "Which of them is faster?"),
]
ABOUT_THEM = [
    ("When did Melanie sign up for a pottery class?", "And what did she make there?"),
    ("What did Caroline research?", "When did she apply to them?"),
    ("Where has Melanie camped?", "And when did she go in July?"),
    ("What is Caroline's relationship status?", "What about Melanie?"),
    ("What are Melanie's pets' names?", "Which of them is the oldest?"),
    ("When did Caroline go to the LGBTQ support group?", "And the conference?"),
    ("What kind of art does Caroline make?", "Has Melanie painted the same thing?"),
    ("What books has Melanie read?", "When did she read that one about the spider?"),
    ("Who supports Caroline when she has a negative experience?", "And what happened on that hike?"),
    ("When is Melanie planning on going camping?", "What do her kids like about it?"),
]
MODES = {"decider": {"gate": "decider"}, "choice": {"gate": "choice", "gate_recheck": 0.05}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_model_args(ap)
    args = ap.parse_args()
    work = RESULTS.parent / "work"
    clean, db = work / "follow_up_clean.db", work / "follow_up_check.db"
    with sqlite3.connect(work / "locomo_sophia_dev_v5_conv-26.db") as src, sqlite3.connect(clean) as dst:
        src.backup(dst)                                   # consistent even while the WAL is in use
    rows = []
    try:
        for kind, pairs in (("general", GENERAL), ("about them", ABOUT_THEM)):
            for i, (prev, q) in enumerate(pairs):
                row = {"kind": kind, "previous": prev, "query": q}
                for m, over in MODES.items():             # a fresh memory each time: no earlier capture to find
                    shutil.copy(clean, db)
                    e = Engine({**memory_config(args, user_name="Caroline", agent_name="Assistant"), **over}, db)
                    try:
                        e.capture_turn("follow", prev, "Sure, here you go.")
                        text, info = e.recall.prefetch(q, "follow")
                    finally:
                        e.close()
                    row[m] = {"injected": bool(text), "gate": info["gate"], "referential": info["referential"],
                              "uncertain": info.get("uncertain", False), "ms": info["ms"]}
                rows.append(row)
    finally:
        for f in (clean, db):
            for suffix in ("", "-wal", "-shm"):
                Path(str(f) + suffix).unlink(missing_ok=True)
    (RESULTS / "follow_up_check.json").write_text(json.dumps(rows, indent=1))
    for m in MODES:
        for kind in ("general", "about them"):
            rs = [r for r in rows if r["kind"] == kind]
            print(f"{m:8} {kind:10}: memory injected {sum(r[m]['injected'] for r in rs)}/{len(rs)}, "
                  f"seen as follow-ups {sum(r[m]['referential'] for r in rs)}/{len(rs)}, "
                  f"median {statistics.median(r[m]['ms'] for r in rs):.0f} ms; "
                  f"wrong: {[r['query'] for r in rs if r[m]['injected'] != (kind != 'general')]}")


if __name__ == "__main__":
    main()
