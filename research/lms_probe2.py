import json, time, math, urllib.request
BASE="http://127.0.0.1:1234"
Q="STATE: The API has returned 503 for every request since the deploy.\nQUESTION: Which team should own this ticket? A) billing B) infra C) sales. Answer with the single letter only."
def post(path, body, timeout=180):
    t0=time.perf_counter()
    r=json.loads(urllib.request.urlopen(urllib.request.Request(BASE+path,data=json.dumps(body).encode(),headers={"Content-Type":"application/json"}),timeout=timeout).read())
    return (time.perf_counter()-t0)*1000, r
def show_resp(label, dt, r):
    kinds=[o["type"] for o in r.get("output",[])]
    msg=[o for o in r.get("output",[]) if o["type"]=="message"]
    reasoning=[o for o in r.get("output",[]) if o["type"]=="reasoning"]
    rtxt = "".join(c.get("text","") for o in reasoning for c in (o.get("content") or []))
    print(f"\n== {label}: {dt:.0f} ms, items={kinds}, reasoning_chars={len(rtxt)}, usage={r.get('usage',{}).get('output_tokens')}")
    if msg:
        c=msg[0]["content"][0]; lp=c.get("logprobs")
        print("   text:", repr(c.get("text"))[:60])
        first = lp[0] if isinstance(lp,list) and lp else None
        if first:
            for t in (first.get("top_logprobs") or [])[:6]: print(f"   {t.get('token')!r:8s} p={math.exp(t['logprob']):.3f}")
    else:
        print("   (no message item)")
# (i) reasoning effort none
try:
    dt,r=post("/v1/responses",{"model":"qwen/qwen3.8-27b","input":Q,"max_output_tokens":4,"temperature":0,"top_logprobs":6,"reasoning":{"effort":"none"},"include":["message.output_text.logprobs"]})
    show_resp("responses, reasoning effort=none, 4 tokens", dt, r)
except Exception as e: print("\n== effort=none failed:", str(e)[:200])
# (ii) reasoning low, 64 tokens: how long is the think block?
dt,r=post("/v1/responses",{"model":"qwen/qwen3.8-27b","input":Q+" /no_think","max_output_tokens":64,"temperature":0,"top_logprobs":6,"reasoning":{"effort":"low"},"include":["message.output_text.logprobs"]})
show_resp("responses, /no_think + effort=low, 64 tokens", dt, r)
# (iii) chat completions with chat_template_kwargs enable_thinking=false + logprobs
try:
    dt,r=post("/v1/chat/completions",{"model":"qwen/qwen3.8-27b","messages":[{"role":"user","content":Q}],"max_tokens":4,"temperature":0,"logprobs":True,"top_logprobs":6,"chat_template_kwargs":{"enable_thinking":False}})
    c=r["choices"][0]; print(f"\n== chat completions, enable_thinking=false: {dt:.0f} ms, content={c['message'].get('content')!r}, reasoning={str(c['message'].get('reasoning_content') or c['message'].get('reasoning'))[:40]!r}, logprobs={'present' if c.get('logprobs') else None}")
    if c.get("logprobs"): print("   ", json.dumps(c["logprobs"])[:400])
except Exception as e: print("\n== chat enable_thinking=false failed:", str(e)[:200])
# (iv) completions endpoint with raw prompt that closes the think block, logprobs
try:
    raw = "<|im_start|>user\n"+Q+"<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
    dt,r=post("/v1/completions",{"model":"qwen/qwen3.8-27b","prompt":raw,"max_tokens":2,"temperature":0,"logprobs":6})
    c=r["choices"][0]; print(f"\n== completions raw prompt w/ closed think: {dt:.0f} ms, text={c.get('text')!r}, logprobs={'present' if c.get('logprobs') else None}")
    if c.get("logprobs"): print("   ", json.dumps(c["logprobs"])[:400])
except Exception as e: print("\n== completions raw failed:", str(e)[:200])
