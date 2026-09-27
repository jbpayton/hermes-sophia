"""Which gate wording separates relevant messages from off-topic ones? Both option orders per case (state first,
as the decider asks). Relevant: development questions whose answers are in memory. Off-topic: gate_offtopic.json.

  python bench/gate_wording.py
"""
from __future__ import annotations

import argparse
import json
import math
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import DATA, RESULTS, add_model_args, memory_config
from hermes_sophia.decider import LETTERS, Noul, _options, _prompt
from hermes_sophia.engine import Engine
from longmemeval import ts

WORDINGS = {
    "current": "At least one memory item is directly relevant to the message: it answers it, or states a fact the reply "
               "should take into account.",
    "reply-uses": "A good reply to this message would use at least one of these memories: one answers the message, or "
                  "says something about the user that should change the reply.",
    "about-user": "The message is about the user's own life, plans, preferences or past conversations, or one of these "
                  "memories says something about the user that should change the reply.",
    "not-just-topic": "At least one memory answers the message or is needed for a good reply to it. Memories that only "
                      "share a word or a topic with the message do not count.",
}


def p_true(client, model, prompt, order):
    _, tops = client.first_token_logprobs(model, prompt, 10, 30.0)
    lp = {}
    for tok, v in tops:
        t = tok.strip()
        if len(t) == 1 and t in LETTERS[:2]:
            lp[t] = max(lp.get(t, -1e9), v)
    if not lp:
        return 0.5
    floor = min(lp.values()) - 5
    a, b = lp.get("A", floor), lp.get("B", floor)
    m = max(a, b)
    pa, pb = math.exp(a - m), math.exp(b - m)
    return [pa, pb][order.index(1)] / (pa + pb)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_model_args(ap)
    args = ap.parse_args()
    here, work = Path(__file__).parent, RESULTS.parent / "work"
    rng = random.Random(7)
    lme = {x["question_id"]: x for x in json.loads((DATA / "longmemeval_s_cleaned.json").read_text())}
    off = json.loads((here / "gate_offtopic.json").read_text())["prompts"]
    cases = []
    for sample in ("dev60", "devpref"):
        for qid in json.loads((here / f"lme_{sample}.json").read_text())["ids"]:
            if (work / "lme" / f"day_{qid}.db").exists():
                cases.append((work / "lme" / f"day_{qid}.db", lme[qid]["question"], ts(lme[qid]["question_date"]), "relevant"))
    convs = {c["sample_id"]: c for c in json.loads((DATA / "locomo10.json").read_text())}
    loc = [(work / f"locomo_sophia_dev_v5_{sid}.db", qa["question"], None, "relevant")
           for sid in ("conv-26", "conv-30", "conv-41") for qa in convs[sid]["qa"] if qa.get("category") != 5]
    cases += rng.sample(loc, 100)
    dev20 = json.loads((here / "lme_dev20.json").read_text())["ids"][:6]
    for i, qid in enumerate(dev20):
        for q in off[i * 10:(i + 1) * 10]:
            cases.append((work / "lme" / f"day_{qid}.db", q, ts(lme[qid]["question_date"]), "off-topic"))
    for i, sid in enumerate(("conv-26", "conv-30", "conv-41")):
        for q in off[i * 20:(i + 1) * 20]:
            cases.append((work / f"locomo_sophia_dev_v5_{sid}.db", q, None, "off-topic"))
    keys, descs, qt = _options(Noul("x"))
    engines, jobs = {}, []
    for db, query, now, kind in cases:
        e = engines.get(db) or engines.setdefault(db, Engine(memory_config(args, user_name="User", agent_name="Assistant"), db))
        e.now_override = now
        items, _ = e.recall.candidates(query, e.cfg["recall_k"], session_id="v", now=now)
        top = items[:e.cfg["gate_top"]]
        if not top:
            jobs.append((None, kind, query, None, "no candidates"))
            continue
        if top[0]["sim"] >= e.cfg["skip_gate"]:
            jobs.append((None, kind, query, None, "skip"))
            continue
        st = json.dumps({"message": query, "memories": [e.recall.short(it) for it in top]}, ensure_ascii=False, indent=1)
        jobs.append((e, kind, query, st, "gate"))

    def run(job):
        e, kind, query, st, how = job
        out = {"kind": kind, "query": query, "how": how}
        if e is None:
            return out
        for name, w in WORDINGS.items():
            ps = [p_true(e.decider.client, e.cfg["decider_model"], _prompt(st, w, [descs[i] for i in o], qt), o)
                  for o in ([0, 1], [1, 0])]
            out[name] = sum(ps) / 2
        return out
    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(run, jobs))
    for e in engines.values():
        e.close()
    (RESULTS / "gate_wording.json").write_text(json.dumps(rows, indent=1))
    rel = [r for r in rows if r["kind"] == "relevant"]
    off_rows = [r for r in rows if r["kind"] == "off-topic"]
    print(f"relevant {len(rel)} (skip {sum(r['how'] == 'skip' for r in rel)}, none {sum(r['how'] == 'no candidates' for r in rel)}); "
          f"off-topic {len(off_rows)} (skip {sum(r['how'] == 'skip' for r in off_rows)}, none {sum(r['how'] == 'no candidates' for r in off_rows)})")
    for name in WORDINGS:
        rr = sorted(r[name] for r in rel if name in r)
        oo = [r[name] for r in off_rows if name in r]
        auc = sum((a > b) + 0.5 * (a == b) for a in rr for b in oo) / (len(rr) * len(oo))
        th97 = rr[int(0.03 * len(rr))]                 # keeps 97% of gated relevant messages
        line = f"{name:15} AUC {auc:.3f} | at 0.5: relevant {sum(x >= .5 for x in rr) / len(rr):.1%}, off-topic {sum(x >= .5 for x in oo)}/{len(oo)}"
        line += f" | cutoff keeping 97% relevant = {th97:.2f}: off-topic passed {sum(x >= th97 for x in oo)}/{len(oo)}"
        print(line)


if __name__ == "__main__":
    main()
