"""Paired comparison of two runs of the same questions: accuracy, questions won and lost, and (for a choice-gate run)
accuracy split by what the gate said: closed, whole block marked possible, or lines vouched for.

  python bench/compare_arms.py results/lme_sophia_dev60_dev_v8_decider.jsonl results/lme_sophia_dev60_dev_v8_choice.jsonl
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def load(path):
    rows = {}
    for line in Path(path).read_text().splitlines():
        r = json.loads(line)
        rows[r["id"]] = r
    return rows


def ok(r) -> bool:
    return bool(int(r.get("correct") or 0))


def verdict(gate: str) -> str:
    m = re.match(r"choice:g([\d.]+),n([\d.]+),m([\d.]+)", gate or "")
    if not m:
        return "other"
    g, n, mem = map(float, m.groups())
    return "possible (whole block)" if n >= mem else "vouched lines"


def main():
    a, b = load(sys.argv[1]), load(sys.argv[2])
    ids = [i for i in a if i in b]
    won = [i for i in ids if ok(b[i]) and not ok(a[i])]
    lost = [i for i in ids if ok(a[i]) and not ok(b[i])]
    print(f"{len(ids)} questions: A {sum(ok(a[i]) for i in ids) / len(ids):.3f}, B {sum(ok(b[i]) for i in ids) / len(ids):.3f}; "
          f"B won {len(won)}, lost {len(lost)}")
    groups = {}
    for i in ids:
        g = b[i].get("gate") or ""
        key = "closed (no memory)" if str(b[i].get("injected")) in ("0", "") and g.startswith("choice") else verdict(g)
        groups.setdefault(key, []).append(i)
    for key, gi in sorted(groups.items()):
        print(f"  B's gate said {key:24}: {len(gi):3} questions; A {sum(ok(a[i]) for i in gi)}/{len(gi)}, "
              f"B {sum(ok(b[i]) for i in gi)}/{len(gi)}")
    for name, lst in (("won", won), ("lost", lost)):
        for i in lst:
            print(f"  {name}: {i} [{b[i].get('gate')}] {str(b[i].get('question'))[:90]}")


if __name__ == "__main__":
    main()
