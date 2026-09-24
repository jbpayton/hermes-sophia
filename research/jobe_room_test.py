"""Same Sophia-style room decision via jobe (frozen Qwen3.5-4B logit readout)."""
import json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("HF_HOME", os.path.join(HERE, "hf_home"))
import torch
from jobe import Decision, Option, load, score

query = "What camera did Joey use for the Yosemite trip?"
room_triples = [
    "Joey visited Yosemite in May 2025",
    "Joey hiked Half Dome with Sam",
    "Yosemite trip lasted four days",
    "Joey stayed at Curry Village",
    "Sam brought a drone to Yosemite",
    "Joey prefers hiking in spring",
    "Joey drove from San Jose to Yosemite",
]
doors = [
    Option("joey_photography_gear", "extends: 9 triples about Joey's cameras, lenses and photo habits"),
    Option("sam", "related-to: 6 triples about Sam, Joey's hiking partner"),
    Option("half_dome", "instantiates: 4 triples about the Half Dome hike itself"),
    Option("curry_village", "related-to: 3 triples about the lodging"),
    Option("san_jose", "related-to: 12 triples about Joey's home city"),
    Option("back", "None of these doors lead toward the query; return to the previous room"),
    Option("stop_here", "This room already contains the answer to the query"),
]
def evidence(triples):
    return json.dumps({
        "query": query,
        "current_room": "Yosemite trip",
        "breadcrumb": ["Joey", "Travel", "Yosemite trip"],
        "triples_in_room": triples,
        "doors": {o.id if hasattr(o, 'id') else o[0]: (o.description if hasattr(o, 'description') else o[1])
                  for o in doors if (o.id if hasattr(o, 'id') else o[0]) not in ("back", "stop_here")},
    }, indent=1)

ev_absent = evidence(room_triples)
ev_present = evidence(room_triples + ["Joey used a Fujifilm X-T5 at Yosemite"])
YESNO = (Option("no", "No, the statement does not hold"), Option("yes", "Yes, the statement holds"))

def decisions(ev):
    return [
        Decision(id="found_here", evidence=ev,
                 criterion="At least one triple in triples_in_room directly answers the query.", options=YESNO),
        Decision(id="any_door_leads_on", evidence=ev,
                 criterion="At least one door in doors leads to a room likely to contain the answer to the query.", options=YESNO),
        Decision(id="next_action", evidence=ev,
                 criterion="Which action best advances answering the query from this room?", options=tuple(doors)),
    ]

def run(backbone, ev, label):
    t0 = time.perf_counter()
    out = [score(backbone.model, backbone.tokenizer, d) for d in decisions(ev)]
    dt = (time.perf_counter() - t0) * 1000
    print(f"\n== {label} ({dt:.1f} ms for 3 decisions) ==")
    for d, r in zip(decisions(ev), out):
        scores = getattr(r, "scores", None) or {}
        top = getattr(r, "choice", None)
        conf = getattr(r, "confidence", None)
        conf_s = f"{conf:.3f}" if isinstance(conf, (int, float)) else str(conf)
        print(f"{d.id:18s} choice={top} conf={conf_s}")
        for k, p in sorted(scores.items(), key=lambda kv: -kv[1]):
            print(f"    {k:24s} {p:.3f}")
    return dt

if torch.cuda.is_available():
    torch.cuda.reset_peak_memory_stats()
t0 = time.perf_counter()
backbone = load("Qwen/Qwen3.5-4B", revision="851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a")
print(f"loaded Qwen3.5-4B in {time.perf_counter()-t0:.1f}s; model device: {next(backbone.model.parameters()).device}, dtype: {next(backbone.model.parameters()).dtype}")
run(backbone, ev_absent, "warm-up")
lat = [run(backbone, ev_absent, "answer NOT in room (should prefer joey_photography_gear or back)"),
       run(backbone, ev_present, "answer IS in room (should prefer stop_here / found_here=yes)")]
for _ in range(3):
    t0 = time.perf_counter(); [score(backbone.model, backbone.tokenizer, d) for d in decisions(ev_absent)]; lat.append((time.perf_counter()-t0)*1000)
print(f"\nlatency ms per 3-decision room over {len(lat)} runs: min={min(lat):.1f} median={sorted(lat)[len(lat)//2]:.1f} max={max(lat):.1f}")
if torch.cuda.is_available():
    print(f"peak GPU mem: {torch.cuda.max_memory_allocated()/1e9:.2f} GB allocated, {torch.cuda.max_memory_reserved()/1e9:.2f} GB reserved")
