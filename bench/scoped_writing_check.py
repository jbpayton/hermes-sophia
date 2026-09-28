"""Writing requests scoped to the people in memory ("a birthday message for Melanie") should open the gate, even
though unscoped writing ("a slogan for a recycling campaign") closes it. Development memories (LoCoMo dev
conversations); prompts written before the check was run.

  python bench/scoped_writing_check.py --url http://127.0.0.1:8090 --api openai --yield-to ""
"""
from __future__ import annotations

import argparse

from common import RESULTS, add_model_args, memory_config
from hermes_sophia.engine import Engine

SCOPED = {
    "conv-26": ["Write a short birthday message for Melanie.",
                "Draft a thank-you note to Melanie for her support.",
                "Write a toast for Caroline's adoption celebration.",
                "Write a short poem about Melanie's pottery.",
                "Draft a message congratulating Caroline on her counseling career plans."],
    "conv-30": ["Write a slogan for Gina's online clothing store.",
                "Draft an announcement for the opening of Jon's dance studio.",
                "Write a short bio for Jon's dance studio website."],
    "conv-41": ["Draft a short speech for John's charity run for veterans.",
                "Write a get-well message for Maria after her car accident."],
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_model_args(ap)
    args = ap.parse_args()
    opened = 0
    for conv, prompts in SCOPED.items():
        db = RESULTS.parent / "work" / f"locomo_sophia_dev_v5_{conv}.db"
        e = Engine({**memory_config(args, user_name="User", agent_name="Assistant"), "gate": "choice"}, db)
        try:
            for p in prompts:
                text, info = e.recall.prefetch(p, "scoped-writing")
                opened += bool(text)
                print(f"{'open  ' if text else 'CLOSED'} {info['gate']:28} split {info.get('split')}  {p}")
        finally:
            e.store.x("DELETE FROM injections WHERE session_id='scoped-writing'")
            e.close()
    print(f"scoped writing requests that got memory: {opened}/{sum(len(v) for v in SCOPED.values())}")


if __name__ == "__main__":
    main()
