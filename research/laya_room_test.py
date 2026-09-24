"""Zero-shot Laya test on a Sophia-style room navigation decision, timed on the local GPU."""
import json, os, sys, time
os.environ.setdefault("HF_HOME", os.path.join(os.path.dirname(__file__), "hf_home"))
import torch
import laya

CKPT = sys.argv[1] if len(sys.argv) > 1 else "convaiinnovations/laya"
if os.environ.get("LAYA_DEVICE"):
    DEVICE = os.environ["LAYA_DEVICE"]
elif torch.cuda.is_available():
    DEVICE = "cuda:1" if torch.cuda.device_count() > 1 else "cuda"
else:
    DEVICE = "cpu"
USE_CUDA = DEVICE.startswith("cuda")

# --- A synthetic Mindscape room: query + packed triples + doors ---------------------
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
doors = {
    "joey_photography_gear": "extends: 9 triples about Joey's cameras, lenses and photo habits",
    "sam": "related-to: 6 triples about Sam, Joey's hiking partner",
    "half_dome": "instantiates: 4 triples about the Half Dome hike itself",
    "curry_village": "related-to: 3 triples about the lodging",
    "san_jose": "related-to: 12 triples about Joey's home city",
    "back": "None of these doors lead toward the query; return to the previous room",
    "stop_here": "This room already contains the answer to the query",
}
state = {
    "query": query,
    "current_room": "Yosemite trip",
    "breadcrumb": ["Joey", "Travel", "Yosemite trip"],
    "triples_in_room": room_triples,
    "doors": {k: v for k, v in doors.items() if k not in ("back", "stop_here")},
}
questions = {
    "found_here": {
        "type": "noul",
        "instructions": "At least one triple in triples_in_room directly answers the query.",
    },
    "any_door_leads_on": {
        "type": "noul",
        "instructions": "At least one door in doors leads to a room likely to contain the answer to the query.",
    },
    "next_action": {
        "type": "choice",
        "instructions": "Which action best advances answering the query from this room?",
        "criteria": doors,
    },
    "room_relevance": {
        "type": "score",
        "instructions": "How relevant is this room's content to the query?",
        "criteria": ["unrelated", "tangential", "related", "directly answers"],
    },
}

# --- A second state where the answer IS in the room ---------------------------------
state2 = dict(state)
state2["triples_in_room"] = room_triples + ["Joey used a Fujifilm X-T5 at Yosemite"]

def run(agent, st, label):
    t0 = time.perf_counter()
    r = agent.predict(st, questions)
    dt = (time.perf_counter() - t0) * 1000
    a = r["answers"]
    print(f"\n== {label} ({dt:.1f} ms) ==")
    print(f"found_here        noul={a['found_here']['noul']:.3f}")
    print(f"any_door_leads_on noul={a['any_door_leads_on']['noul']:.3f}")
    na = a["next_action"]
    probs = sorted(na["probabilities"].items(), key=lambda kv: -kv[1])
    print(f"next_action       choice={na['choice']} conf={na['confidence']:.3f}")
    for k, p in probs:
        print(f"    {k:24s} {p:.3f}")
    rr = a["room_relevance"]
    print(f"room_relevance    score={rr['score']:.2f} conf={rr['confidence']:.3f}")
    return dt

if USE_CUDA:
    torch.cuda.reset_peak_memory_stats()
t0 = time.perf_counter()
agent = laya.load(CKPT, device=DEVICE)
print(f"loaded {CKPT} on {DEVICE} in {time.perf_counter()-t0:.1f}s")

# warm-up
agent.predict(state, questions)
lat = []
lat.append(run(agent, state, "answer NOT in room (should prefer joey_photography_gear or back)"))
lat.append(run(agent, state2, "answer IS in room (should prefer stop_here / found_here high)"))
for _ in range(5):
    t0 = time.perf_counter(); agent.predict(state, questions); lat.append((time.perf_counter()-t0)*1000)
print(f"\nlatency ms over {len(lat)} calls: min={min(lat):.1f} median={sorted(lat)[len(lat)//2]:.1f} max={max(lat):.1f}")
if USE_CUDA:
    dev_idx = int(DEVICE.split(':')[1]) if ':' in DEVICE else 0
    print(f"peak GPU mem: {torch.cuda.max_memory_allocated(dev_idx)/1e9:.2f} GB allocated, {torch.cuda.max_memory_reserved(dev_idx)/1e9:.2f} GB reserved")
else:
    print("ran on CPU (no CUDA in this torch build)")
