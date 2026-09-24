import json, time, urllib.request
BASE="http://127.0.0.1:1234/v1/responses"
st = json.load(open("/dev/stdin")) if False else None
state = {"query":"What camera did Joey use for the Yosemite trip?","current_room":"Yosemite trip",
 "triples_in_room":["Joey visited Yosemite in May 2025","Joey hiked Half Dome with Sam","Yosemite trip lasted four days","Joey stayed at Curry Village","Sam brought a drone to Yosemite","Joey prefers hiking in spring","Joey drove from San Jose to Yosemite"],
 "doors":{"A":"joey_photography_gear: 9 triples about Joey's cameras, lenses and photo habits","B":"sam: 6 triples about Sam","C":"half_dome: 4 triples about the hike","D":"curry_village: 3 triples about the lodging","E":"san_jose: 12 triples about Joey's home city","F":"back: none of these doors lead toward the query","G":"stop_here: this room already contains the answer"}}
prefix = "STATE:\n"+json.dumps(state,indent=1)+"\n\nQUESTION: "
qs = ["Which door (A-G) best advances answering the query? Answer with the single letter only.",
      "Does any triple in triples_in_room directly answer the query? Answer yes or no only.",
      "Does any door lead to a room likely to contain the answer? Answer yes or no only.",
      "Rate this room's relevance to the query: 0 unrelated, 1 tangential, 2 related, 3 directly answers. Answer with the single digit only."]
for i,q in enumerate(qs):
    body={"model":"qwen/qwen3.8-27b","input":prefix+q,"max_output_tokens":2,"temperature":0,"top_logprobs":3,"reasoning":{"effort":"none"},"include":["message.output_text.logprobs"]}
    t0=time.perf_counter()
    r=json.loads(urllib.request.urlopen(urllib.request.Request(BASE,data=json.dumps(body).encode(),headers={"Content-Type":"application/json"}),timeout=180).read())
    dt=(time.perf_counter()-t0)*1000
    msg=[o for o in r["output"] if o["type"]=="message"][0]["content"][0]
    u=r.get("usage",{}); cached=u.get("input_tokens_details",{}).get("cached_tokens")
    print(f"q{i+1}: {dt:.0f} ms  input={u.get('input_tokens')} cached={cached}  answer={msg.get('text')!r}")
