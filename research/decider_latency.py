import json, time, statistics, urllib.request, sys, concurrent.futures as cf
BASE="http://127.0.0.1:1234/v1/responses"
MODEL=sys.argv[1] if len(sys.argv)>1 else "qwen35-9b"
def ask(state, q, max_tokens=2):
    body={"model":MODEL,"input":f"STATE:\n{state}\n\nQUESTION: {q} Answer with the single letter only.","max_output_tokens":max_tokens,
          "temperature":0,"top_logprobs":5,"reasoning":{"effort":"none"},"include":["message.output_text.logprobs"]}
    t0=time.perf_counter()
    r=json.loads(urllib.request.urlopen(urllib.request.Request(BASE,data=json.dumps(body).encode(),headers={"Content-Type":"application/json"}),timeout=120).read())
    dt=(time.perf_counter()-t0)*1000
    msg=[o for o in r["output"] if o["type"]=="message"]
    txt=msg[0]["content"][0]["text"] if msg else None
    return dt, txt, r.get("usage",{}).get("input_tokens")
short = "The API has returned 503 for every request since the deploy."
room = "\n".join(f"- fact {i}: Joey visited Yosemite in May 2025 and hiked Half Dome with Sam, staying at Curry Village." for i in range(8))
long = "\n".join(f"- note {i}: The nightly report job on host web-{i%4} exceeded fifteen minutes because the archive step ran before the index rebuild finished." for i in range(45))
Q="Which team should own this: A) billing B) infra C) sales?"
def bench(label, state, n=8):
    lat=[]; toks=None
    for _ in range(n):
        dt,txt,toks=ask(state,Q); lat.append(dt)
    lat.sort()
    print(f"{label:28s} input≈{toks:>5} tok | median {statistics.median(lat):6.0f} ms | min {lat[0]:6.0f} | p95 {lat[int(0.95*(n-1))]:6.0f} | answer={txt!r}")
print(f"=== decision latency on {MODEL} (sequential, cold-ish, n=8 each) ===")
bench("short (1 sentence)", short)
bench("room-sized (~8 facts)", room)
bench("long (~45 notes)", long)
print("=== same state, second question (prefix cache) ===")
ask(room, Q)
dt2,_,_ = ask(room, "Is this state about hiking: A) yes B) no?")
print(f"room-sized, 2nd question on same state: {dt2:.0f} ms")
print("=== throughput: 8 decisions in flight (room-sized) ===")
t0=time.perf_counter()
with cf.ThreadPoolExecutor(8) as ex:
    res=list(ex.map(lambda i: ask(room+f"\n- extra {i}", Q), range(8)))
tot=time.perf_counter()-t0
print(f"8 concurrent room decisions: {tot*1000:.0f} ms total → {8/tot:.1f} decisions/s; per-request median {statistics.median([r[0] for r in res]):.0f} ms")
