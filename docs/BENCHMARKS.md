# Benchmarks

Sophia on LongMemEval and LoCoMo, measured on one machine (2× RTX 3090, LM Studio). The reader and the judge are both **Qwen3.5-9B**, and the judges use the official prompts. Published systems mostly use GPT-4o-class readers and judges, so these numbers show where Sophia stands with a small local model. They are not a leaderboard entry.

## Protocol: improve without teaching to the test

- **Only general mechanisms.** No benchmark-specific prompts, category logic or answer formats. Every setting change has to make sense for Sophia's real use: a live agent with a local model.
- **Tune on development data, report on held-out data.**
  - **LoCoMo:** tuned on conversations 26, 30 and 41; reported on the other seven.
  - **LongMemEval:** tuned on 60 questions drawn with a different seed and the same per-type quotas, disjoint from the test sample; reported on Gemmery's fixed 60 questions (`bench/lme_gemmery60.json`).
- **Fixed harness.** The reader prompt, the judge prompts (verbatim from the official code) and the answer extraction were not changed during tuning.
- **One thing deliberately not tuned:** the relevance check that decides whether to inject anything. Every benchmark question is about memory, so tuning that check on benchmarks would teach it to always inject, which is the wrong behaviour in real chat.

## LongMemEval (S, cleaned; Gemmery's 60 held-out questions)

| Memory | Accuracy | Task-averaged | Abstention |
|---|---|---|---|
| None | 0.183 | 0.176 | 7/8 |
| Sophia, before (pilot settings) | 0.633 | 0.644 | 6/8 |
| **Sophia, after (development-tuned defaults)** | **0.750** | **0.723** | 6/8 |
| Evidence sessions only (this reader's ceiling) | 0.917 | 0.854 | 6/8 |

- **After, by question type:** knowledge-update 9/9, single-session-user 8/8, temporal 12/16, multi-session 10/16, single-session-assistant 5/7, preference 1/4.
- **Development set** with the same defaults: 0.733.
- **The "before" run was interrupted.** Two runs collided on a shared scratch memory, so it was cut back to its first 24 verified questions and resumed with the same settings pinned by flags.
- **Uncertainty:** with 60 questions, the 95% interval on 0.75 is roughly ±0.11.
- **Memory mode:** day memory only (no night). A night per question costs several minutes of model time for about 2,000 windows.

**Published numbers**, for orientation only (different readers, judges and sample sizes):

| System | Score | Reader / judge | Setting |
|---|---|---|---|
| Full-context GPT-4o | 60.6 | GPT-4o / GPT-4o | LongMemEval paper, S |
| Full-context Llama-3.1-8B | 45.4 | Llama-3.1-8B / GPT-4o | LongMemEval paper, S |
| Zep | 71.2 | GPT-4o | S |
| Hindsight | 83.6 / 89.0 / 91.4 | gpt-oss-20b / gpt-oss-120b / Gemini-3 | S |
| SodaMem | 92.8 | deepseek-v4-flash, grading itself | S |
| Gemmery | 0.917 | Claude / Claude, non-official judge | these 60 questions |

## LoCoMo (categories 1–4; the seven held-out conversations)

| Memory | J | Multi-hop (1) | Temporal (2) | Open-domain (3) | Single-hop (4) |
|---|---|---|---|---|---|
| Sophia, day memory | 0.671 | 0.663 | 0.476 | 0.373 | 0.778 |
| **Sophia, after one night (9B night model)** | **0.730** | 0.740 | 0.567 | 0.387 | 0.825 |
| **Sophia, after one night (27B night model)** | **0.748** | 0.755 | 0.593 | 0.387 | 0.844 |
| The whole conversation in the reader's context | 0.768 | 0.788 | 0.619 | 0.480 | 0.849 |

- **Scale:** 1,155 questions over 7 conversations (roughly 700–950 windows each), scored with Mem0's J prompt; category 5 excluded, as is conventional.
- **Against full context:** after one night, Sophia reaches **95% (9B night) to 97% (27B night) of the same reader's full-context score** while injecting at most 9,000 characters instead of the whole ~70,000-character conversation. Full context stops being an option at LongMemEval scale (about 490,000 characters per question).
- **27B night against 9B night:** same memories and the same 9B reader and judge, so the difference is the night model alone. The 27B wrote headers, facts and judgments. It extracted about twice as many facts (median 679 per conversation against 359) and scored +1.8 points. Question by question it won 104 and lost 83 (sign test p ≈ 0.14), so the gain is real but not significant. Its nights took a median of 28 minutes against 15. Most of that went to integration (1,120 s), which is a stage of one-token yes/no checks; the 9B is well suited to those, and every threshold was measured on it. **Next step:** the 27B writes, the 9B decides.
- **Before, for reference:** with the pilot settings, the development conversation 26 scored 0.566 by day and 0.605 after its night.
- **Night cost** on the 9B with 2 parallel slots: 12–21 minutes per conversation.
  - Headers: about 0.3 s per window.
  - Facts: about 0.25 s per window.
  - Integration: 4–13 minutes, spent mostly on supersession checks that found only 0–2 changes.
  - **Since these runs,** supersession questions are batched, read once first, read in both orders only near the bar, and run in parallel. On conversation 26, integration went from 754 s to 270 s with the same outcome, and fact extraction from 226 s to 134 s. A night for a conversation like this is now about 9 minutes instead of 21.
- **Weakest categories:** temporal (0.57) and open-domain inference (0.39). They are also the reader's weakest with the whole conversation in view (0.62 and 0.48).

**Published numbers** (J), for orientation only (different readers and judges):

| System | J | Reader |
|---|---|---|
| Mem0 / Mem0g | 66.88 / 68.44 | gpt-4o-mini |
| Full context, Mem0 paper | 72.90 | gpt-4o-mini |
| Letta | 74.0 | gpt-4o-mini |
| Zep | 75.14 | gpt-4o-mini |
| Hindsight | 83.18 / 85.67 / 89.61 | gpt-oss-20b / gpt-oss-120b / Gemini-3 |

## What changed, and why

Each change was found stage by stage on the development data (`bench/stages.py`, `bench/retrieval.py`, `bench/retrieval_lme.py`). It was kept only if it improved both development sets or fixed a clear bug.

| Stage | Finding | Change |
|---|---|---|
| Fact extraction | The 9B put whole facts into the relation, with an empty object, and validation discarded them: 1 fact survived from 44 windows | The prompt says what to extract, with worked examples, and objects left inside relations are split back out. 267 facts instead of 130; rejections dropped from 159 to 31 and are logged by reason |
| Supersession | All 17 supersessions in one night were false (a shared photo "replacing" another shared photo) | A high bar (0.85), both option orders, and only for ongoing states. Whether a relation is a state is asked once per relation |
| How recall uses facts | As separate candidates, facts pushed the evidence down | Facts are search keys for the message they came from (`facts_as: keys`). Full night: evidence in the top 10 went from 0.77 (day) to 0.88 |
| Date ranges | A parsed range ("in January and March") hid everything said outside it | The range boosts instead of filtering (`time_scope: boost`) |
| Injection depth | Only 10 items could be injected, and counting questions need every piece | 50 items within 9,000 characters (about 1,900 tokens when memory is relevant). All evidence injected: 0.81 → 0.88 (LongMemEval development), 0.74 → 0.80 (LoCoMo development) |
| Context headers | They carry most of the night's gain for LoCoMo (evidence in the top 10: 0.78 → 0.87) | Batches now run in parallel (`night_parallel`) |

## Reproducing

```bash
python bench/longmemeval.py --mode sophia --sample gemmery60 --tag mine     # also: oracle | none
python bench/locomo.py --mode sophia --convs conv-42,conv-43 --tag mine     # also: sophia-night | full | none
python bench/retrieval.py --convs conv-26 --set inject_top=30              # retrieval only, fast
```

The data goes in `../bench-data/` ([bench/README.md](../bench/README.md) lists the sources). Results and the exact setup of every run are written to `bench/results/*.summary.json`.
