"""Retrieval-only evaluation on LoCoMo: are the evidence turns in what Sophia ranks, and in what it injects?

No reader, no judge: each question's evidence dia_ids map to the windows captured from those turns, and we measure
  hit@k      some evidence window is in the top k candidates (a fact counts through its source window)
  all@k      every evidence window is in the top k (what multi-hop questions need)
  injected   some evidence window is in what prefetch would actually inject (gate skipped)
Memories are built once per conversation and cached in bench/work, so variants take seconds.

  python bench/retrieval.py                          # all 10 conversations, current settings
  python bench/retrieval.py --set inject_top=30 --set inject_chars=12000
  python bench/retrieval.py --db-suffix night        # reuse memories that already had a night
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import time
from collections import defaultdict

from common import DATA, RESULTS, add_model_args, memory_config
from hermes_sophia.capture import message_hash
from hermes_sophia.engine import Engine
from locomo import ingest, sessions

KS = (5, 10, 20, 30, 50)


def evidence_refs(conv):
    """dia_id -> the window ref its turn was captured under."""
    out = {}
    for num, t0, turns in sessions(conv):
        sid = f"{conv['sample_id']}-s{num}"
        raw = conv["conversation"][f"session_{num}"]
        for t, r in zip(turns, raw):
            m = {"role": "user", "name": t["speaker"], "content": t["text"], "timestamp": t["ts"]}
            out[r["dia_id"]] = f"hermes:{sid}:{message_hash(sid, m)[:12]}"
    return out


def parse_set(pairs):
    out = {}
    for p in pairs or []:
        k, v = p.split("=", 1)
        try:
            out[k] = json.loads(v)
        except ValueError:
            out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--convs", default="")
    ap.add_argument("--db-suffix", default="day", help="which cached memories to use: day | night | …")
    ap.add_argument("--label", default="")
    add_model_args(ap)
    args = ap.parse_args()
    overrides = parse_set(args.set)
    data = json.loads((DATA / "locomo10.json").read_text())
    if args.convs:
        data = [c for c in data if c["sample_id"] in set(args.convs.split(","))]
    work = RESULTS.parent / "work"
    work.mkdir(parents=True, exist_ok=True)
    stats = defaultdict(lambda: defaultdict(list))
    t_all = time.time()
    for conv in data:
        sid, spk = conv["sample_id"], conv["conversation"]
        cfg = memory_config(args, user_name=spk["speaker_a"], agent_name="Assistant")
        cfg.update(overrides)
        cfg["recall_k"] = max(cfg["recall_k"], max(KS))
        db = work / f"retr_{args.db_suffix}_{sid}.db"
        fresh = not db.exists()
        e = Engine(cfg, db)
        if fresh:
            if args.db_suffix != "day":
                raise SystemExit(f"{db} missing: build '{args.db_suffix}' memories first")
            ingest(e, conv)
        refs = evidence_refs(conv)
        ref_of = {r["id"]: r["ref"] for r in e.store.q("SELECT id, ref FROM windows")}
        asked_at = sessions(conv)[-1][1] + 86400
        for q in conv["qa"]:
            if q.get("category") not in (1, 2, 3, 4) or not q.get("evidence"):
                continue
            ev = {refs[d] for d in re.findall(r"D\d+:\d+", " ".join(q["evidence"])) if d in refs}
            if not ev:
                continue
            items, _info = e.recall.candidates(q["question"], k=max(KS), now=asked_at)
            ranked = []
            for it in items:
                wid = it["id"] if it["kind"] == "window" else it.get("evidence_id")
                ranked.append(ref_of.get(wid))
            cat = str(q["category"])
            for k in KS:
                got = set(ranked[:k]) & ev
                stats[cat][f"hit@{k}"].append(bool(got))
                stats[cat][f"all@{k}"].append(got == ev)
            chosen = e.recall.select(items[:max(cfg["inject_top"], 1)], agent_asked=_info.get("asks_agent", False))
            chosen = e.recall.fit(chosen, cfg["inject_chars"])        # only what reaches the agent
            inj = {ref_of.get(it["id"] if it["kind"] == "window" else it.get("evidence_id")) for it in chosen}
            text = e.recall.format(chosen, cfg["inject_chars"])
            stats[cat]["injected"].append(bool(inj & ev))
            stats[cat]["injected_all"].append(ev <= inj)
            stats[cat]["inject_chars"].append(len(text))
        e.close()
    def mean(v):
        return round(sum(v) / len(v), 3) if v else None
    table = {cat: {m: mean(v) for m, v in ms.items()} | {"n": len(ms["hit@5"])} for cat, ms in sorted(stats.items())}
    allq = defaultdict(list)
    for ms in stats.values():
        for m, v in ms.items():
            allq[m].extend(v)
    table["all"] = {m: mean(v) for m, v in allq.items()} | {"n": len(allq["hit@5"])}
    out = {"label": args.label or " ".join(args.set or []) or "baseline", "db": args.db_suffix,
           "overrides": overrides, "seconds": round(time.time() - t_all, 1), "table": table,
           "written": dt.datetime.now().isoformat(timespec="seconds")}
    with open(RESULTS / "retrieval_runs.jsonl", "a") as f:
        f.write(json.dumps(out) + "\n")
    a = table["all"]
    print(f"{out['label']:40s} n={a['n']} " + " ".join(f"{m}={a[m]}" for m in
          ["hit@10", "hit@50", "all@30", "injected", "injected_all", "inject_chars"]))
    for cat in sorted(k for k in table if k != "all"):
        c = table[cat]
        print(f"   cat {cat} n={c['n']:3d} hit@10={c['hit@10']} hit@30={c['hit@30']} all@30={c['all@30']} injected={c['injected']}")


if __name__ == "__main__":
    main()
