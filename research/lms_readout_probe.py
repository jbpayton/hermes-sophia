import json, time, urllib.request
import os
URL = "http://127.0.0.1:1234/v1/responses"
state = json.dumps({
  "query": "What camera did Joey use for the Yosemite trip?",
  "current_room": "Yosemite trip",
  "triples_in_room": ["Joey visited Yosemite in May 2025","Joey hiked Half Dome with Sam","Yosemite trip lasted four days",
                      "Joey stayed at Curry Village","Sam brought a drone to Yosemite","Joey prefers hiking in spring","Joey drove from San Jose to Yosemite"],
  "doors": {"A":"joey_photography_gear: 9 triples about Joey's cameras, lenses and photo habits","B":"sam: 6 triples about Sam, Joey's hiking partner",
            "C":"half_dome: 4 triples about the Half Dome hike","D":"curry_village: 3 triples about the lodging","E":"san_jose: 12 triples about Joey's home city",
            "F":"back: none of these doors lead toward the query; return to the previous room","G":"stop_here: this room already contains the answer"}})
def ask(extra_triple=None, q="Which door (A-G) best advances answering the query from this room? Answer with the single letter only."):
    st = json.loads(state)
    if extra_triple: st["triples_in_room"].append(extra_triple)
    body = {"model":os.environ.get("DECIDER_MODEL","qwen/qwen3.8-27b"),"input":"STATE:\n"+json.dumps(st,indent=1)+"\n\nQUESTION: "+q+"",
            "max_output_tokens":2,"temperature":0,"top_logprobs":10,"reasoning":{"effort":"none"},"include":["message.output_text.logprobs"]}
    t0=time.perf_counter()
    r = json.loads(urllib.request.urlopen(urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type":"application/json"}), timeout=180).read())
    dt=(time.perf_counter()-t0)*1000
    msg=[o for o in r["output"] if o["type"]=="message"]
    if not msg: return dt, None, None, [o["type"] for o in r["output"]]
    c=msg[0]["content"][0]; lp=c.get("logprobs")
    first = lp[0] if isinstance(lp,list) and lp else lp
    return dt, c.get("text"), first, r.get("usage")
for label, extra in [("answer NOT in room", None), ("answer IS in room", "Joey used a Fujifilm X-T5 at Yosemite")]:
    dt, text, first, usage = ask(extra)
    print(f"\n== {label}: {dt:.0f} ms, text={text!r}, usage={usage}")
    if isinstance(first, dict):
        tops = first.get("top_logprobs") or []
        import math
        for t in tops[:10]:
            print(f"   {t.get('token')!r:10s} logprob={t.get('logprob'):.3f}  p={math.exp(t.get('logprob')):.3f}")
    else:
        print("   raw:", json.dumps(first)[:400])
dt, text, first, usage = ask(None, "Does any triple in triples_in_room directly answer the query? Answer yes or no only.")
print(f"\n== noul-style, answer NOT in room: {dt:.0f} ms, text={text!r}")
if isinstance(first, dict):
    import math
    for t in (first.get("top_logprobs") or [])[:6]: print(f"   {t.get('token')!r:10s} p={math.exp(t.get('logprob')):.3f}")
dt, text, first, usage = ask("Joey used a Fujifilm X-T5 at Yosemite", "Does any triple in triples_in_room directly answer the query? Answer yes or no only.")
print(f"== noul-style, answer IS in room: {dt:.0f} ms, text={text!r}")
if isinstance(first, dict):
    import math
    for t in (first.get("top_logprobs") or [])[:6]: print(f"   {t.get('token')!r:10s} p={math.exp(t.get('logprob')):.3f}")
