"""Stage 1 of the relevance gate: can the decider, from the message alone, recognise requests that are self-contained
(need nothing about the user) without closing on anything that needs memory? Development data only.

  python bench/message_check.py --set decider_url=http://127.0.0.1:8090 --set decider_api=openai
"""
from __future__ import annotations

import argparse
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import DATA, RESULTS, add_model_args, memory_config
from hermes_sophia.decider import Decider
from hermes_sophia.lms import ModelServer

WORDINGS = {
    "self-contained": "The message is a self-contained general request (a definition, fact, calculation, conversion, "
                      "translation, joke, poem or code question) that needs nothing about the user or earlier "
                      "conversations.",
    "not-about-user": "The message is not about the user's own life, people, plans, preferences, projects or earlier "
                      "conversations; it could be answered the same way for anyone.",
}


def cases():
    here = Path(__file__).parent
    rng = random.Random(5)
    lme = {x["question_id"]: x for x in json.loads((DATA / "longmemeval_s_cleaned.json").read_text())}
    out = [(lme[q]["question"], "needs memory", "lme") for s in ("dev60", "devpref")
           for q in json.loads((here / f"lme_{s}.json").read_text())["ids"]]
    convs = {c["sample_id"]: c for c in json.loads((DATA / "locomo10.json").read_text())}
    loc = [(qa["question"], "needs memory", "locomo") for s in ("conv-26", "conv-30", "conv-41")
           for qa in convs[s]["qa"] if qa.get("category") != 5]
    out += rng.sample(loc, 150)
    for f in sorted(Path.home().joinpath("almanac/data/dev").glob("life-*.json")):
        for q in json.loads(f.read_text())["questions"]:
            out.append((q["question"], "self-contained" if q["kind"] == "quiet" else "needs memory", "almanac"))
    out += [(p, "self-contained", "offtopic") for p in json.loads((here / "gate_offtopic.json").read_text())["prompts"]]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_model_args(ap)
    args = ap.parse_args()
    cfg = memory_config(args)
    url = cfg.get("decider_url") if cfg.get("decider_url") not in (None, "", "default") else cfg["lmstudio_url"]
    d = Decider(ModelServer(url, api=cfg.get("decider_api", "lmstudio")), cfg["decider_model"], timeout=30)
    cs = cases()

    def run(c):
        msg, kind, src = c
        row = {"message": msg, "kind": kind, "src": src}
        for name, w in WORDINGS.items():
            a = d.noul({"message": msg}, w, permutations=2)
            fwd = a.raw[0] if a.raw else {}
            row[name] = a.noul
            row[name + "_flip"] = a.flip
        return row
    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(run, cs))
    (RESULTS / "message_check.json").write_text(json.dumps(rows, indent=1))
    need = [r for r in rows if r["kind"] == "needs memory"]
    selfc = [r for r in rows if r["kind"] == "self-contained"]
    print(f"needs memory {len(need)} (lme/locomo/almanac), self-contained {len(selfc)} (off-topic set + Almanac quiet)")
    for name in WORDINGS:
        for th in (0.5, 0.7, 0.8, 0.9, 0.95):
            closed_need = [r for r in need if r[name] >= th]
            print(f"{name:15} close at p>={th}: self-contained closed {sum(r[name] >= th for r in selfc)}/{len(selfc)} | "
                  f"needs-memory wrongly closed {len(closed_need)}/{len(need)}"
                  + (f"  e.g. {[r['message'][:50] for r in closed_need[:3]]}" if closed_need and th >= 0.8 else ""))


if __name__ == "__main__":
    main()
