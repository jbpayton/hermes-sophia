# Research

These are the experiments behind the design, kept as they were run. They are prototypes, not library code: most talk to LM Studio at `127.0.0.1:1234` and print their findings.

All measurements come from the development box: 2× RTX 3090 (24 GB each), LM Studio on llama.cpp CUDA 12, Qwen3.8-27B Q6_K and Qwen3.5-9B Q4_K_M. [docs/STORY.md](../docs/STORY.md) tells the story around them.

## 1. Purpose-built decision models, zero-shot

"Decision models" read a situation and return a choice or a probability without generating text. The candidates in September 2026:

| System | What it is |
|---|---|
| **Jev** | TypeSafe's hosted "System One" model, with Choice, Score and Noul primitives. API only; no weights and no paper |
| **Laya** | Convai's 421M decision head on ModernBERT-large (`convaiinnovations/laya`), Apache 2.0 |
| **Von** | `wfzyx/von-1.0`, a 395M ModernBERT-Large encoder that speaks Jev's wire format |
| **jobe** | `MantisShrimpdev/jobe`, a logit readout on a frozen Qwen3.5-4B |

| Script | What it does |
|---|---|
| `laya_room_test.py` | A synthetic Mindscape room: a query about Joey's camera, 7 Yosemite triples, 5 doors plus `back` and `stop_here`. It runs once with the answer absent and once with it planted. Pass a checkpoint to test `laya-typed-decisions` |
| `jobe_room_test.py` | The same room with jobe |

Von was run with an inline script that isn't kept here. None of the scripts ships its model: install `laya` or `jobe` into a venv first, and use a torch build that matches your driver.

| System | "Found here?" (absent / present) | Door (absent / present) | Latency | Peak VRAM |
|---|---|---|---|---|
| Laya | 0.734 / 0.763 | photo gear 0.38 / photo gear 0.34 (wrong: should stop) | ~45 ms | 2.5 GB |
| Laya typed-decisions | 0.555 / 0.606 | photo gear 0.25 / 0.23 | ~44 ms | 2.5 GB |
| Von 1.0 | 0.9999 / 1.0 (saturated) | half_dome / half_dome (wrong) | ~126 ms | 0.9 GB |
| jobe (Qwen3.5-4B) | no 0.989 / yes 0.995 | photo gear 0.96 / stop_here 0.92 | ~340 ms per 3 decisions | 8.65 GB |
| Qwen3.8-27B, LM Studio logprob readout | no 0.957 / yes 0.988 | correct / correct (0.998) | ~1.1–1.3 s | none extra |

**Verdict.** The encoders were fast and wrong, and are only worth revisiting after fine-tuning on logged decisions. A logit readout on a real LLM got everything right. The one already loaded in LM Studio costs no extra VRAM, and at that point the 8.7 GB sidecar wouldn't have fit anyway.

## 2. Any chat model as a decider (logprob readout)

| Script | What it does |
|---|---|
| `lms_probe2.py` | Which LM Studio endpoints return logprobs: `/v1/completions` and `/v1/chat/completions` return `logprobs: null`. `/v1/responses` does return them, but only with `"reasoning": {"effort": "none"}`; otherwise the answer is swallowed by a reasoning block |
| `lms_readout_probe.py` | First-token readout on the room: pick a door, answer yes or no, score relevance |
| `lms_cache_probe.py` | Several questions over one state. Putting the state first lets the prefix cache serve the fan-out |
| `decider_latency.py` | Latency for short, room-sized and long states |
| `sophia_decider.py` | The standalone decider that became `hermes_sophia/decider.py`: `Choice` / `Noul` / `Score`, single-letter options, averaging over both option orders with a `flip` signal, a JSONL decision log, and `fit_temperature`. Its self-test log is `results/decisions.jsonl` |

On the 9B (Q4_K_M, reasoning off), one prompt in and one token read:

| State | Cold | Cached |
|---|---|---|
| Short, about 75 tokens | 210 ms | 110–135 ms |
| Room-sized, about 340 tokens | 280 ms | about 145 ms |
| Long, about 1,800 tokens | 640 ms | about 135 ms |

- A second question on the same room took 184 ms. With 8 in flight, throughput was 6.6 decisions/s.
- The 27B was 554 / 799 / 2,347 ms cold, at about 2 decisions/s, so the 9B does the per-turn gate.
- The 9B got 4/4 room decisions right, with probabilities of 0.94–0.99.

This became the awake-path gate.

## 3. Triple extraction bake-off

| Script | What it does |
|---|---|
| `extract_bakeoff.py` | SophiaAMS's extraction prompts and schema run against NuExtract3, Qwen3.5-9B and Qwen3.8-27B on 5 sample chunks: encyclopedia, conversation, procedure, web chunk with noise, and personal note. Needs a SophiaAMS clone: `SOPHIAAMS_DIR=/path/to/SophiaAMS` |

The results are in `results/bakeoff_*.json`:

| Config | Time per chunk | Triples | Null objects | Schema-valid chunks |
|---|---|---|---|---|
| Qwen3.8-27B Q6_K, SophiaAMS prompt, thinking off | 11–30 s | 50 | 0 | 5/5 |
| **Qwen3.5-9B Q4_K_M**, same prompt, thinking off | 7–12 s | 38 | 0 | 5/5 |
| NuExtract3 Q8_0, native template + 1 example | 3–6 s | 33 | 1 | 4/5 |
| NuExtract3, native, no example | 3–5 s | 31 | 6 | 2/5 |
| NuExtract3, example + reasoning | 8–15 s | 32 | 1 | 4/5 |

Every quote was verbatim in every config.

**Verdict:** "NuExtract3 is not the ticket." The stock 9B with reasoning off is.

NuExtract3's problems:
- null objects that no instruction suppresses;
- verbs that swallow their objects ("carries the Golden Record");
- fewer facts overall.

The 9B has its own flaw: it inferred "Joey dislikes Sony" from "the Sony was too heavy". That is a memory-poisoning risk, and it is why Sophia keeps facts as an index over verbatim evidence. LM Studio doesn't forward `chat_template_kwargs`, so NuExtract3 needs a self-rendered prompt on `/v1/completions`.

## 4. Extraction speed levers

| Script | What it does |
|---|---|
| `speed_tests.py` | A compact output format (numbered sentences in; `subject \| verb \| object \| sN` lines out), and concurrency |
| `run_llamaserver_tests.sh` | The 9B pinned to one GPU under LM Studio's bundled `llama-server`: plain, n-gram speculation, and a 0.8B draft model |

**Result.**
- **Baseline:** the 9B decoded at about 77 tok/s, spending about 90 output tokens per triple.
- **Compact format:** 2.8× faster on the 9B and 3.7× on the 27B. Sample 1 dropped from 899 to 327 output tokens and gained two triples, with quotes verbatim by construction. One worked example was needed; without it the 9B swapped columns.
- **Single-GPU llama-server:** 1.35× single-stream. Parallel scaling reached 1.66×: 23.2 s serial vs 14.0 s, 201 tok/s aggregate.
- **Speculative decoding:** a loss in every configuration.
  - LM Studio's MTP flag needs an MTP head the model doesn't have.
  - A 0.8B draft model dropped throughput from 78 to 51 tok/s.
  - n-gram speculation changed nothing.

Stacked, a five-chunk document went from about 45 s to about 11 s. The compact format is what the night's `relate` step uses.

## 5. Embedding thresholds with nomic ("when in Rome")

| Script | What it does |
|---|---|
| `embed_thresholds.py` | A 76-triple corpus from 13 texts, 8 of them written as near-misses, with 24 answerable and 10 unanswerable questions. It measures recall@k, relevant versus irrelevant scores, and what the gate decider adds |

The results are `results/embed_corpus.json`, `results/embed_thresholds.json` and `results/gate_decisions.jsonl`.

**Findings.**
- **Prefixes:** the `search_query:` / `search_document:` prefixes matter; recall@1 was 0.75 with them versus 0.62 without.
- **What to embed:** a triple together with its source sentence gave recall@10 of 1.00.
- **Score distribution:** irrelevant pairs had a median of about 0.48 and relevant pairs 0.80, but near-misses score like answers. "When did Voyager 2 launch?" scored 0.78 against the Voyager 1 launch fact. Similarity alone can't decide "found".
- **Old cutoffs:** SophiaAMS's MiniLM-era cutoffs of 0.15, 0.2 and 0.3 keep 100% of pairs, so they are meaningless under nomic.
- **The gate:** the decider over the top 10 got 32 of 34 right reading both option orders (31 of 34 with one order), with no false "not found". Its two misses: it accepted the camera fact for "What lens did Joey use?", and it said yes to "What car does Emma drive?" at 0.65. Skipping the gate at top-1 ≥ 0.82 covered 38% of answerable questions and 0% of unanswerable ones.

These became `skip_gate: 0.82` and the rule "similarity ranks, the decider judges".
