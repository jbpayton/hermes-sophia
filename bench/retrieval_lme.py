"""Retrieval-only evaluation on LongMemEval: are the evidence turns (has_answer) ranked and injected?

Each question's haystack is ingested into its own memory once (cached in bench/work/lme/), so variants take
seconds. Metrics as in retrieval.py; abstention questions are skipped (their "evidence" is related, not answering).

  python bench/retrieval_lme.py --sample dev60
  python bench/retrieval_lme.py --sample dev60 --set inject_top=30
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from collections import defaultdict
from pathlib import Path

from common import DATA, RESULTS, add_model_args, memory_config
from hermes_sophia.capture import message_hash
from hermes_sophia.engine import Engine
from longmemeval import ingest, ts

KS = (5, 10, 20, 30, 50)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", default="dev60", help="dev60 | gemmery60")
    ap.add_argument("--db-suffix", default="day")
    ap.add_argument("--label", default="")
    add_model_args(ap)
    args = ap.parse_args()
    ids = json.loads((Path(__file__).parent / f"lme_{args.sample}.json").read_text())["ids"]
    by_id = {x["question_id"]: x for x in json.loads((DATA / "longmemeval_s_cleaned.json").read_text())}
    work = RESULTS.parent / "work" / "lme"
    work.mkdir(parents=True, exist_ok=True)
    stats = defaultdict(lambda: defaultdict(list))
    t_all = time.time()
    for qid in ids:
        item = by_id[qid]
        if "_abs" in qid:
            continue
        cfg = memory_config(args, user_name="User", agent_name="Assistant")
        cfg["recall_k"] = max(cfg["recall_k"], max(KS))
        db = work / f"{args.db_suffix}_{qid}.db"
        fresh = not db.exists()
        e = Engine(cfg, db)
        if fresh:
            if args.db_suffix != "day":
                raise SystemExit(f"{db} missing")
            ingest(e, item)
        ev = set()
        for sid, turns in zip(item["haystack_session_ids"], item["haystack_sessions"]):
            for t in turns:
                if t.get("has_answer"):
                    ev.add(f"hermes:{sid}:{message_hash(sid, {'role': t['role'], 'content': t['content']})[:12]}")
        ref_of = {r["id"]: r["ref"] for r in e.store.q("SELECT id, ref FROM windows")}
        items, _ = e.recall.candidates(item["question"], k=max(KS), now=ts(item["question_date"]))
        ranked = [ref_of.get(it["id"] if it["kind"] == "window" else it.get("evidence_id")) for it in items]
        typ = item["question_type"]
        for k in KS:
            got = set(ranked[:k]) & ev
            stats[typ][f"hit@{k}"].append(bool(got))
            stats[typ][f"all@{k}"].append(got == ev)
        chosen = e.recall.select(items[:max(cfg["inject_top"], 1)])
        chosen = e.recall.fit(chosen, cfg["inject_chars"])            # only what reaches the agent
        inj = {ref_of.get(it["id"] if it["kind"] == "window" else it.get("evidence_id")) for it in chosen}
        stats[typ]["injected"].append(bool(inj & ev))
        stats[typ]["injected_all"].append(ev <= inj)
        stats[typ]["inject_chars"].append(len(e.recall.format(chosen, cfg["inject_chars"])))
        e.close()

    def mean(v):
        return round(sum(v) / len(v), 3) if v else None
    table = {t: {m: mean(v) for m, v in ms.items()} | {"n": len(ms["hit@5"])} for t, ms in sorted(stats.items())}
    allq = defaultdict(list)
    for ms in stats.values():
        for m, v in ms.items():
            allq[m].extend(v)
    table["all"] = {m: mean(v) for m, v in allq.items()} | {"n": len(allq["hit@5"])}
    out = {"label": args.label or " ".join(args.set) or "baseline", "sample": args.sample, "db": args.db_suffix,
           "set": args.set, "seconds": round(time.time() - t_all, 1), "table": table,
           "written": dt.datetime.now().isoformat(timespec="seconds")}
    with open(RESULTS / "retrieval_lme_runs.jsonl", "a") as f:
        f.write(json.dumps(out) + "\n")
    a = table["all"]
    print(f"{out['label']:40s} n={a['n']} " + " ".join(f"{m}={a[m]}" for m in
          ["hit@10", "hit@50", "all@30", "injected", "injected_all", "inject_chars"]))
    for t in sorted(k for k in table if k != "all"):
        c = table[t]
        print(f"   {t:26s} n={c['n']:3d} hit@10={c['hit@10']} hit@30={c['hit@30']} all@30={c['all@30']} injected={c['injected']}")


if __name__ == "__main__":
    main()
