"""Serving benchmark for the whole stack, over the plain OpenAI API, so any server can be compared:
- chat model: time to first token and generation speed for an agent-sized prompt (a ~3,000-token system prompt of
  instructions and tool schemas + a question), fresh vs with the system prompt already seen, and two at once;
- embeddings: a batch of 64 short texts, and one query.

  python bench/serving_bench.py --label lmstudio --url http://127.0.0.1:1234 --chat-model qwen/qwen3.8-27b --embed-model nomic-embed
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TOOLS = [{"type": "function", "function": {"name": f"tool_{i}", "description": (
    f"Tool number {i}. It reads, searches, edits or runs things for the user; arguments are validated, errors are "
    f"returned as text, and long outputs are truncated. Use it when the task needs capability {i}.") * 2,
    "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "A file path or URL."},
                                                    "query": {"type": "string", "description": "What to look for."},
                                                    "limit": {"type": "integer", "description": "Max results."}},
                   "required": ["query"]}}} for i in range(24)]
SYSTEM = ("You are a capable personal agent. Follow the user's instructions, use tools when they help, keep answers "
          "concise, and explain what you did. Never invent tool results. " * 40)
QUESTIONS = ["Explain, in about 150 words, how a heat pump works in winter.",
             "Give me a short plan, about 150 words, for learning to bake sourdough bread.",
             "In about 150 words, what should I check before buying a used car?",
             "Describe, in about 150 words, how the internet routes a packet from my laptop to a website."]


def post_stream(url, body, timeout=300):
    req = urllib.request.Request(url + "/v1/chat/completions", data=json.dumps({**body, "stream": True,
                                 "stream_options": {"include_usage": True}}).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter(); first = None; last = None; chunks = 0; usage = {}
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for line in r:
            line = line.strip()
            if not line.startswith(b"data:") or line.endswith(b"[DONE]"):
                continue
            d = json.loads(line[5:])
            if d.get("usage"):
                usage = d["usage"]
            for ch in d.get("choices") or []:
                delta = ch.get("delta") or {}
                if delta.get("content") or delta.get("reasoning_content") or delta.get("tool_calls"):
                    now = time.perf_counter()
                    first = first or now
                    last = now
                    chunks += 1
    total = time.perf_counter() - t0
    n = usage.get("completion_tokens") or chunks
    gen = (n - 1) / (last - first) if first and last and last > first else None
    return {"ttft_ms": (first - t0) * 1000 if first else None, "total_s": total, "tokens": n, "gen_tps": gen,
            "prompt_tokens": usage.get("prompt_tokens")}


def chat_body(model, system, question, think_off=True):
    b = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": question}],
         "tools": TOOLS, "max_tokens": 256, "temperature": 0}
    if think_off:
        b["reasoning_effort"] = "none"
        b["chat_template_kwargs"] = {"enable_thinking": False}
    return b


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:1234")
    ap.add_argument("--embed-url", default="")
    ap.add_argument("--chat-model", default="qwen/qwen3.8-27b")
    ap.add_argument("--embed-model", default="nomic-embed")
    ap.add_argument("--skip-embed", action="store_true")
    args = ap.parse_args()
    out = {"label": args.label}
    m = args.chat_model
    post_stream(args.url, chat_body(m, "warm up " + SYSTEM, "Say hi."))
    fresh = [post_stream(args.url, chat_body(m, f"[session {uuid.uuid4().hex}] " + SYSTEM, q)) for q in QUESTIONS[:3]]
    base = f"[session {uuid.uuid4().hex}] " + SYSTEM
    post_stream(args.url, chat_body(m, base, "Say hi."))                  # the system prompt is now in the cache
    warm = [post_stream(args.url, chat_body(m, base, q)) for q in QUESTIONS[:3]]
    t = time.perf_counter()
    with ThreadPoolExecutor(2) as ex:
        pair = list(ex.map(lambda q: post_stream(args.url, chat_body(m, f"[pair {uuid.uuid4().hex}] " + SYSTEM, q)), QUESTIONS[:2]))
    pair_wall = time.perf_counter() - t
    med = lambda xs: round(statistics.median([x for x in xs if x is not None]), 1)
    out["chat"] = {"prompt_tokens": fresh[0]["prompt_tokens"],
                   "fresh_ttft_ms": med([r["ttft_ms"] for r in fresh]), "fresh_gen_tps": med([r["gen_tps"] for r in fresh]),
                   "cached_ttft_ms": med([r["ttft_ms"] for r in warm]), "cached_gen_tps": med([r["gen_tps"] for r in warm]),
                   "two_at_once_gen_tps_each": med([r["gen_tps"] for r in pair]),
                   "two_at_once_total_tps": round(sum(r["tokens"] for r in pair) / pair_wall, 1)}
    if not args.skip_embed:
        eu = args.embed_url or args.url
        texts = [f"search_document: Note {i}: the user mentioned a trip, a recipe or a bill on day {i}." for i in range(64)]
        def emb(inp):
            t = time.perf_counter()
            urllib.request.urlopen(urllib.request.Request(eu + "/v1/embeddings", data=json.dumps(
                {"model": args.embed_model, "input": inp}).encode(), headers={"Content-Type": "application/json"}), timeout=60).read()
            return (time.perf_counter() - t) * 1000
        emb(texts[:2])
        out["embed"] = {"batch64_ms": med([emb(texts) for _ in range(3)]),
                        "one_query_ms": med([emb(["search_query: where did I park?"]) for _ in range(10)])}
    print(json.dumps(out, indent=1))
    Path(__file__).parent.joinpath("results", f"serving_{args.label}.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
