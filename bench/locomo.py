"""LoCoMo: 10 long two-person conversations, 1,540 scored questions (categories 1-4).

Modes:
  sophia        ingest every session into a fresh memory, answer from what Sophia injects (the passive path)
  sophia-night  the same, after a night (headers, facts, graph) built with --night-model
  full          the whole conversation in the reader's context (a strong baseline; about 18k tokens each)
  none          no memory at all (the floor)

Scoring is Mem0's LLM-as-judge "J" prompt (verbatim, mem0 commit aae5989) over categories 1-4, with a local judge.

  python bench/locomo.py --mode sophia --convs conv-26 --limit 40
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import time
from pathlib import Path

from common import (DATA, RESULTS, Models, Results, add_model_args, fresh_engine, final_answer, memory_config,
                    run_night, summarize, write_summary)

J_PROMPT = (  # verbatim from mem0 evaluation/metrics/llm_judge.py @ aae5989, trailing spaces kept
    '\n'
    'Your task is to label an answer to a question as ’CORRECT’ or ’WRONG’. You will be given the following data:\n'
    '    (1) a question (posed by one user to another user), \n'
    '    (2) a ’gold’ (ground truth) answer, \n'
    '    (3) a generated answer\n'
    'which you will score as CORRECT/WRONG.\n'
    '\n'
    'The point of the question is to ask about something one user should know about the other user based on their prior conversations.\n'
    'The gold answer will usually be a concise and short answer that includes the referenced topic, for example:\n'
    'Question: Do you remember what I got the last time I went to Hawaii?\n'
    'Gold answer: A shell necklace\n'
    'The generated answer might be much longer, but you should be generous with your grading - as long as it touches on the same topic as the gold answer, it should be counted as CORRECT. \n'
    '\n'
    'For time related questions, the gold answer will be a specific date, month, year, etc. The generated answer might be much longer or use relative time references (like "last Tuesday" or "next month"), but you should be generous with your grading - as long as it refers to the same date or time period as the gold answer, it should be counted as CORRECT. Even if the format differs (e.g., "May 7th" vs "7 May"), consider it CORRECT if it\'s the same date.\n'
    '\n'
    "Now it's time for the real question:\n"
    'Question: {question}\n'
    'Gold answer: {gold_answer}\n'
    'Generated answer: {generated_answer}\n'
    '\n'
    'First, provide a short (one sentence) explanation of your reasoning, then finish with CORRECT or WRONG. \n'
    'Do NOT include both CORRECT and WRONG in your response, or it will break the evaluation script.\n'
    '\n'
    'Just return the label CORRECT or WRONG in a json format with the key as "label".\n'
    '')

INSTRUCTIONS = ("Answer from the memories. Dates in the memories are when things were said; resolve words like "
                "\"yesterday\" or \"last week\" against them. If the memories don't contain the answer, say it "
                "wasn't mentioned.\nFirst note the relevant memories in one or two sentences, then give a short "
                "answer on a final line starting with \"Answer:\".")


def parse_date(s: str) -> float:
    s = re.sub(r"\s+", " ", s.strip())
    for fmt in ("%I:%M %p on %d %B, %Y", "%I:%M %p on %d %b, %Y", "%I:%M %p on %B %d, %Y"):
        try:
            return dt.datetime.strptime(s, fmt).timestamp()
        except ValueError:
            pass
    raise ValueError(f"unparsed LoCoMo date: {s!r}")


def sessions(conv):
    c = conv["conversation"]
    nums = sorted(int(m.group(1)) for k in c for m in [re.fullmatch(r"session_(\d+)", k)] if m)
    out = []
    for n in nums:
        t0 = parse_date(c[f"session_{n}_date_time"])
        turns = []
        for i, t in enumerate(c[f"session_{n}"]):
            text = t["text"]
            if t.get("blip_caption"):
                text += f" [shares a photo: {t['blip_caption']}]"
            turns.append({"speaker": t["speaker"], "text": text, "ts": t0 + i * 30})
        out.append((n, t0, turns))
    return out


def ingest(engine, conv) -> int:
    n = 0
    for num, t0, turns in sessions(conv):
        msgs = [{"role": "user", "name": t["speaker"], "content": t["text"], "timestamp": t["ts"]} for t in turns]
        n += engine.capture.process_messages(f"{conv['sample_id']}-s{num}", msgs, now=t0).get("windows", 0)
    return n


def transcript(conv) -> str:
    parts = []
    for num, t0, turns in sessions(conv):
        day = dt.datetime.fromtimestamp(t0).strftime("%Y-%m-%d %H:%M")
        parts.append(f"### Session {num} — {day}\n" + "\n".join(f"{t['speaker']}: {t['text']}" for t in turns))
    return "\n\n".join(parts)


def judge(models, q, gold, answer) -> bool:
    out = models.judge(J_PROMPT.format(question=q, gold_answer=gold, generated_answer=answer), max_tokens=120)
    m = re.search(r'"label"\s*:\s*"?(CORRECT|WRONG)', out, re.I)
    if m:
        return m.group(1).upper() == "CORRECT"
    return "CORRECT" in out.upper() and "WRONG" not in out.upper()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", required=True, choices=["sophia", "sophia-night", "full", "none"])
    ap.add_argument("--convs", default="", help="comma-separated sample ids (default: all 10)")
    ap.add_argument("--limit", type=int, default=0, help="questions per conversation (0 = all)")
    add_model_args(ap)
    args = ap.parse_args()

    data = json.loads((DATA / "locomo10.json").read_text())
    if args.convs:
        keep = set(args.convs.split(","))
        data = [c for c in data if c["sample_id"] in keep]
    name = f"locomo_{args.mode}" + (f"_{args.tag}" if args.tag else "")
    res = Results(RESULTS / f"{name}.jsonl")
    work = RESULTS.parent / "work"
    work.mkdir(parents=True, exist_ok=True)
    models = Models(args)

    for conv in data:
        sid, spk = conv["sample_id"], conv["conversation"]
        qa = [q for q in conv["qa"] if q.get("category") in (1, 2, 3, 4) and "answer" in q]
        if args.limit:
            qa = qa[:args.limit]
        todo = [(i, q) for i, q in enumerate(qa) if f"{sid}:{i}" not in res.done]
        if not todo:
            continue
        last = sessions(conv)[-1][1]
        asked_at = last + 86400
        engine, context = None, ""
        if args.mode.startswith("sophia"):
            # both speakers are people: neither is "the assistant", whose words the night treats as reported claims
            cfg = memory_config(args, user_name=spk["speaker_a"], agent_name="Assistant")
            engine = fresh_engine(work, f"{name}_{sid}", cfg)
            t = time.time()
            n = ingest(engine, conv)
            print(f"[{sid}] ingested {n} windows in {time.time() - t:.0f}s", flush=True)
            if args.mode == "sophia-night":
                t = time.time()
                out = run_night(engine, args, now=last + 3600)
                facts = engine.store.one("SELECT COUNT(*) AS n FROM facts")["n"]
                print(f"[{sid}] night {out['status']} in {time.time() - t:.0f}s: {facts} facts", flush=True)
        elif args.mode == "full":
            context = f"Conversation between {spk['speaker_a']} and {spk['speaker_b']}:\n\n{transcript(conv)}"

        for i, q in todo:
            t = time.time()
            gold = str(q["answer"])
            row = {"id": f"{sid}:{i}", "conv": sid, "category": q["category"], "question": q["question"], "gold": gold}
            date = dt.datetime.fromtimestamp(asked_at).strftime("%Y-%m-%d")
            if engine is not None:
                text, info = engine.recall.prefetch(q["question"], f"bench-{sid}", now=asked_at)
                row.update(gate=info.get("gate"), injected=info.get("n", 0), graph=info.get("graph"))
                memory = text or "(No memories were recalled for this question.)"
                prompt = f"{memory}\n\nThe question is asked on {date}.\nQuestion: {q['question']}\n{INSTRUCTIONS}"
            elif args.mode == "full":
                prompt = f"{context}\n\nThe question is asked on {date}.\nQuestion: {q['question']}\n{INSTRUCTIONS}"
            else:
                prompt = (f"(You have no memory of earlier conversations.)\n\nQuestion: {q['question']}\n"
                          "Give a short answer on a final line starting with \"Answer:\".")
            response = models.read(prompt)
            answer = final_answer(response)
            row.update(response=response, answer=answer, correct=int(judge(models, q["question"], gold, answer)),
                       seconds=round(time.time() - t, 2))
            res.add(row)
        if engine is not None:
            engine.close()
        s = summarize([r for r in res.rows if r["conv"] == sid], "category")
        print(f"[{sid}] J={s['accuracy']} over {s['n']}  {s['by']}", flush=True)

    summary = summarize(res.rows, "category")
    setup = {"benchmark": "LoCoMo (categories 1-4)", "mode": args.mode, "reader": args.reader, "judge": args.judge,
             "judge_prompt": "Mem0 J (aae5989)", "embed": args.embed, "decider": args.decider,
             "night_model": args.night_model if args.mode == "sophia-night" else None,
             "inject_chars": args.inject_chars, "graph_hops": args.graph_hops,
             "inject_top": args.inject_top, "recall_k": max(args.recall_k, args.inject_top),
             "convs": sorted({r["conv"] for r in res.rows}), "limit_per_conv": args.limit}
    write_summary(RESULTS / f"{name}.summary.json", setup, summary)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
