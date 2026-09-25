"""LongMemEval (S split, cleaned): 500 questions, each with its own ~48-session haystack.

Modes:
  sophia        ingest the haystack into a fresh memory, answer from what Sophia injects (the passive path)
  sophia-night  the same, after a night built with --night-model
  oracle        only the evidence sessions, in the official history format (the ceiling for this reader)
  none          no memory at all (the floor)

Scoring uses the official judge prompts verbatim (evaluate_qa.py, per type, abstention first) with a local judge.
The default sample is Gemmery's fixed 60 questions, so results sit beside its 0.917.

  python bench/longmemeval.py --mode sophia --sample gemmery60
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time

from common import (active_read, DATA, RESULTS, Models, Results, add_model_args, fresh_engine, memory_config, run_night,
                    summarize, write_summary)

_STD = ("I will give you a question, a correct answer, and a response from a model. Please answer yes if the response "
        "contains the correct answer. Otherwise, answer no. If the response is equivalent to the correct answer or "
        "contains all the intermediate steps to get the correct answer, you should also answer yes. If the response "
        "only contains a subset of the information required by the answer, answer no. ")
JUDGE = {
    "standard": _STD + "\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\n"
                       "Is the model response correct? Answer yes or no only.",
    "temporal-reasoning": _STD + "In addition, do not penalize off-by-one errors for the number of days. If the "
                                 "question asks for the number of days/weeks/months, etc., and the model makes "
                                 "off-by-one errors (e.g., predicting 19 days when the answer is 18), the model's "
                                 "response is still correct. \n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: "
                                 "{}\n\nIs the model response correct? Answer yes or no only.",
    "knowledge-update": ("I will give you a question, a correct answer, and a response from a model. Please answer yes "
                         "if the response contains the correct answer. Otherwise, answer no. If the response contains "
                         "some previous information along with an updated answer, the response should be considered "
                         "as correct as long as the updated answer is the required answer.\n\nQuestion: {}\n\nCorrect "
                         "Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."),
    "single-session-preference": ("I will give you a question, a rubric for desired personalized response, and a "
                                  "response from a model. Please answer yes if the response satisfies the desired "
                                  "response. Otherwise, answer no. The model does not need to reflect all the points "
                                  "in the rubric. The response is correct as long as it recalls and utilizes the "
                                  "user's personal information correctly.\n\nQuestion: {}\n\nRubric: {}\n\nModel "
                                  "Response: {}\n\nIs the model response correct? Answer yes or no only."),
    "abstention": ("I will give you an unanswerable question, an explanation, and a response from a model. Please "
                   "answer yes if the model correctly identifies the question as unanswerable. The model could say "
                   "that the information is incomplete, or some other information is given but the asked "
                   "information is not.\n\nQuestion: {}\n\nExplanation: {}\n\nModel Response: {}\n\nDoes the model "
                   "correctly identify the question as unanswerable? Answer yes or no only."),
}

READ_MEMORY = ("I will give you memories recalled from several history chats between you and a user. Please answer the "
               "question based on the relevant memories. Answer the question step by step: first extract all the "
               "relevant information, and then reason over the information to get the answer.\n\n\nMemories:\n\n{}\n\n"
               "Current Date: {}\nQuestion: {}\nAnswer (step by step):")
ACTIVE_QUESTION = ("Answer the question based on the memories above; if they are not enough, use the memory tools to "
                   "search further. Answer step by step: first extract all the relevant information, and then reason "
                   "over it to get the answer.\n\nCurrent Date: {}\nQuestion: {}")
READ_HISTORY = ("I will give you several history chats between you and a user. Please answer the question based on the "
                "relevant chat history. Answer the question step by step: first extract all the relevant information, "
                "and then reason over the information to get the answer.\n\n\nHistory Chats:\n\n{}\n\nCurrent Date: "
                "{}\nQuestion: {}\nAnswer (step by step):")


def ts(s: str) -> float:
    return dt.datetime.strptime(s, "%Y/%m/%d (%a) %H:%M").timestamp()


def haystack(item):
    """Sessions sorted by full timestamp (the S file is out of order within a day), without has_answer."""
    rows = sorted(zip(item["haystack_dates"], item["haystack_session_ids"], item["haystack_sessions"]),
                  key=lambda r: ts(r[0]))
    return [(date, sid, [{"role": t["role"], "content": t["content"]} for t in turns]) for date, sid, turns in rows]


def ingest(engine, item) -> int:
    n = 0
    for date, sid, turns in haystack(item):
        t0 = ts(date)
        msgs = [dict(t, timestamp=t0 + i * 30) for i, t in enumerate(turns)]
        n += engine.capture.process_messages(sid, msgs, now=t0).get("windows", 0)
    return n


def oracle_history(item) -> str:
    keep = set(item["answer_session_ids"])
    blocks = [f"\n### Session {i + 1}:\nSession Date: {date}\nSession Content:\n{json.dumps(turns)}\n"
              for i, (date, sid, turns) in enumerate(r for r in haystack(item) if r[1] in keep)]
    return "".join(blocks)


def judge(models, item, response) -> bool:
    kind = "abstention" if "_abs" in item["question_id"] else (
        item["question_type"] if item["question_type"] in JUDGE else "standard")
    out = models.judge(JUDGE[kind].format(item["question"], item["answer"], response), max_tokens=10)
    return "yes" in out.lower()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", required=True, choices=["sophia", "sophia-night", "oracle", "none"])
    ap.add_argument("--sample", default="gemmery60", help="gemmery60 | all | N (first N of gemmery60)")
    ap.add_argument("--split", default="longmemeval_s_cleaned.json")
    ap.add_argument("--limit", type=int, default=0, help="only the first N questions of the sample")
    ap.add_argument("--only-type", default="", help="only this question_type (development diagnosis)")
    ap.add_argument("--recall", default="passive", choices=["passive", "active"],
                    help="passive: the reader sees only what Sophia injects; active: it may also call Sophia's tools")
    ap.add_argument("--memories", default="", help="reuse per-question memories from this folder "
                    "(e.g. bench/work/lme, built by retrieval_lme.py) instead of ingesting each haystack")
    add_model_args(ap)
    args = ap.parse_args()

    from pathlib import Path
    sample_file = Path(__file__).parent / f"lme_{args.sample}.json"
    ids = json.loads((sample_file if sample_file.exists() else Path(__file__).parent / "lme_gemmery60.json").read_text())["ids"]
    if args.sample.isdigit():
        ids = ids[:int(args.sample)]
    data = json.loads((DATA / args.split).read_text())
    if args.sample != "all":
        by_id = {x["question_id"]: x for x in data}
        data = [by_id[i] for i in ids]
    if args.only_type:
        data = [x for x in data if x["question_type"] == args.only_type]
    if args.limit:
        data = data[:args.limit]
    name = f"lme_{args.mode}" + ("_active" if args.recall == "active" else "") + f"_{args.sample}" + \
        (f"_{args.tag}" if args.tag else "")
    res = Results(RESULTS / f"{name}.jsonl")
    work = RESULTS.parent / "work"
    work.mkdir(parents=True, exist_ok=True)
    models = Models(args)

    for item in data:
        qid = item["question_id"]
        if qid in res.done:
            continue
        t = time.time()
        row = {"id": qid, "type": item["question_type"], "abstention": "_abs" in qid, "question": item["question"],
               "gold": str(item["answer"])}
        asked_at = ts(item["question_date"])
        if args.mode.startswith("sophia"):
            cfg = memory_config(args, user_name="User", agent_name="Assistant")
            cached = Path(args.memories) / f"day_{qid}.db" if args.memories else None
            if cached:                                   # reuse, or build once and keep (for other readers)
                from hermes_sophia.engine import Engine
                cached.parent.mkdir(parents=True, exist_ok=True)
                fresh_db = not cached.exists()
                engine = Engine(cfg, cached)
                row["windows"] = ingest(engine, item) if fresh_db else \
                    engine.store.one("SELECT COUNT(*) AS n FROM windows")["n"]
            else:
                engine = fresh_engine(work, f"{name}_current", cfg)          # one scratch memory per run
                row["windows"] = ingest(engine, item)
            if args.mode == "sophia-night":
                row["night"] = run_night(engine, args, now=asked_at)["status"]
            engine.now_override = asked_at
            text, info = engine.recall.prefetch(item["question"], "bench", now=asked_at)
            row.update(gate=info.get("gate"), injected=info.get("n", 0), graph=info.get("graph"))
            prompt = READ_MEMORY.format(text or "(No memories were recalled for this question.)",
                                        item["question_date"], item["question"])
            if args.recall == "active":
                act = active_read(models, engine, text or "(No memories were recalled for this question.)",
                                  ACTIVE_QUESTION.format(item["question_date"], item["question"]))
                engine.close()
                row["tool_calls"] = act["tool_calls"]
                response = act["response"]
                row.update(response=response, correct=int(judge(models, item, response)),
                           seconds=round(time.time() - t, 2))
                res.add(row)
                print(f"{len(res.rows):3d} {qid:18s} {row['type']:26s} {'OK ' if row['correct'] else 'MISS'} "
                      f"{row.get('gate', '')} tools={len(act['tool_calls'])} {row['seconds']}s", flush=True)
                continue
            engine.close()
        elif args.mode == "oracle":
            prompt = READ_HISTORY.format(oracle_history(item), item["question_date"], item["question"])
        else:
            prompt = (f"Current Date: {item['question_date']}\nQuestion: {item['question']}\n"
                      "Answer (step by step):")
        response = models.read(prompt, max_tokens=800)
        row.update(response=response, correct=int(judge(models, item, response)), seconds=round(time.time() - t, 2))
        res.add(row)
        print(f"{len(res.rows):3d} {qid:18s} {row['type']:26s} {'OK ' if row['correct'] else 'MISS'} "
              f"{row.get('gate', '')} {row['seconds']}s", flush=True)

    rows = res.rows
    summary = summarize(rows, "type")
    summary["task_averaged"] = summary.pop("group_mean", None)
    ab = [r for r in rows if r["abstention"]]
    summary["abstention"] = {"n": len(ab), "acc": round(sum(r["correct"] for r in ab) / len(ab), 4) if ab else None}
    setup = {"benchmark": f"LongMemEval ({args.split})", "sample": args.sample, "mode": args.mode, "recall": args.recall,
             "reader": args.reader, "judge": args.judge, "judge_prompts": "official evaluate_qa.py (9e0b455)",
             "embed": args.embed, "decider": args.decider,
             "night_model": args.night_model if args.mode == "sophia-night" else None,
             "sophia_config": {k: memory_config(args)[k] for k in (
                 "inject_chars", "inject_top", "recall_k", "inject_relative_floor", "graph_hops", "graph_adjacent",
                 "fts_weight", "facts_as", "skip_gate", "gate_threshold")}}
    write_summary(RESULTS / f"{name}.summary.json", setup, summary)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
