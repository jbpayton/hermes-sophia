"""Per-line split, development only: after the gate opens, which of the top memories should be listed as Relevant
and which as Possible matches? Two readouts on the gate's own (cached) prompt, scored against LongMemEval's answer
turns (a memory counts as evidence when its text holds a has_answer turn):
  pick   one first-token readout, "which memory is most relevant" (A..J = memory 1..10, K = none); a memory is
         Relevant when its probability reaches a threshold
  list   a short generation, "the numbers of all relevant memories" (multi-select, not calibrated)

  python bench/split_study.py --url http://127.0.0.1:8090 --api openai --yield-to ""
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from pathlib import Path

from common import DATA, RESULTS, add_model_args, memory_config
from hermes_sophia.decider import Choice
from hermes_sophia.engine import Engine
from longmemeval import ts

PICK_Q = ("Which memory bears most directly on the message: it answers it, or states a fact the reply should take "
          "into account?")
LIST_Q = ("Which memories bear on the message: they answer it, or state a fact the reply should take into account? "
          "Answer with their numbers only, comma-separated (for example: 2, 5), or 0 if none do.")
THRESHOLDS = (0.02, 0.05, 0.1, 0.2)

# the three-way gate as measured here (question and options frozen, so reruns measure the same thing)
GATE_QUESTION = "What does this message need from memory?"
GATE_OPTIONS = {
    "general": "Nothing: a good reply would be the same for any user (general facts, explanations, writing, "
               "calculations, translation or code), so nothing about this user or earlier conversations is needed.",
    "none_fit": "It is about the user or earlier conversations, but none of these memories bears on it.",
    "relevant": "At least one of these memories is relevant: it answers the message or states a fact the reply "
                "should take into account.",
}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def is_evidence(text: str, answers) -> bool:
    t = norm(text)
    return any(a[:80] in t or t[:80] in a for a in answers if a)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_model_args(ap)
    args = ap.parse_args()
    here, work = Path(__file__).parent, RESULTS.parent / "work"
    lme = {x["question_id"]: x for x in json.loads((DATA / "longmemeval_s_cleaned.json").read_text())}
    ids = [q for s in ("dev60", "devpref") for q in json.loads((here / f"lme_{s}.json").read_text())["ids"]]
    rows = []
    for qid in ids:
        item = lme[qid]
        answers = [norm(t["content"]) for sess in item["haystack_sessions"] for t in sess if t.get("has_answer")]
        now = ts(item["question_date"])
        e = Engine(memory_config(args, user_name="User", agent_name="Assistant"), work / "lme" / f"day_{qid}.db")
        try:
            e.now_override = now
            items, _ = e.recall.candidates(item["question"], e.cfg["recall_k"], session_id="split", now=now)
            top = items[:e.cfg["gate_top"]]
            if not top:
                continue
            state = {"message": item["question"],
                     "memories": [f"[{i + 1}] {e.recall.short(it)}" for i, it in enumerate(top)]}
            gate = e.decider.ask(state, Choice(GATE_QUESTION, GATE_OPTIONS), permutations=1).probabilities
            keys = {f"memory [{i + 1}]": None for i in range(len(top))}
            t = time.perf_counter()
            pick = e.decider.ask(state, Choice(PICK_Q, {**keys, "none of them": None}), permutations=1).probabilities
            ms_pick = (time.perf_counter() - t) * 1000
            state_text = json.dumps(state, ensure_ascii=False, indent=1)
            t = time.perf_counter()
            out = e.clients["decider"].chat(e.cfg["decider_model"], f"STATE:\n{state_text}\n\nQUESTION: {LIST_Q}", max_tokens=40,
                             timeout=60)
            ms_list = (time.perf_counter() - t) * 1000
            listed = {int(n) for n in re.findall(r"\d+", out) if 1 <= int(n) <= len(top)}
            rows.append({"id": qid, "type": item["question_type"], "gate": gate, "list_raw": out[:80],
                         "items": [{"evidence": is_evidence(it["text"], answers),
                                    "pick": pick[f"memory [{i + 1}]"], "listed": (i + 1) in listed}
                                   for i, it in enumerate(top)],
                         "none": pick["none of them"], "ms_pick": ms_pick, "ms_list": ms_list})
        finally:
            e.close()
    (RESULTS / "split_study.json").write_text(json.dumps(rows, indent=1))
    all_items = [it for r in rows for it in r["items"]]
    ev = sum(it["evidence"] for it in all_items)
    print(f"questions {len(rows)}; top-10 lines {len(all_items)}, of which evidence {ev}; "
          f"questions with evidence in the top 10: {sum(any(it['evidence'] for it in r['items']) for r in rows)}")

    def report(name, rel):
        n = sum(rel(it) for it in all_items)
        tp = sum(rel(it) and it["evidence"] for it in all_items)
        zero = sum(not any(rel(it) for it in r["items"]) for r in rows)
        lost = sum(any(it["evidence"] for it in r["items"]) and not any(rel(it) and it["evidence"] for it in r["items"])
                   for r in rows)
        print(f"{name:14} Relevant lines {n} ({n / len(all_items):.0%}); precision {tp / max(n, 1):.2f}; "
              f"evidence kept Relevant {tp}/{ev}; questions with no Relevant line {zero}; "
              f"questions whose evidence all went to Possible {lost}")
    for th in THRESHOLDS:
        report(f"pick >= {th}", lambda it, th=th: it["pick"] >= th)
    report("list", lambda it: it["listed"])
    print(f"time after the gate call: pick median {statistics.median(r['ms_pick'] for r in rows):.0f} ms, "
          f"list median {statistics.median(r['ms_list'] for r in rows):.0f} ms")


if __name__ == "__main__":
    main()
