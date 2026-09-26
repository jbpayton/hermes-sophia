# Benchmarks

Sophia on LongMemEval and LoCoMo, measured on one machine (2× RTX 3090, LM Studio). Readers are **Qwen3.5-9B** or **Qwen3.8-27B**, as labelled; the judge is the 9B with the official prompts (its agreement with the 27B judge is measured [below](#judge-agreement)). Published systems mostly use GPT-4o-class readers and judges, so these numbers show where Sophia stands with small local models. They are not a leaderboard entry.

## Protocol: improve without teaching to the test

- **Only general mechanisms.** No benchmark-specific prompts, category logic or answer formats. Every setting change has to make sense for Sophia's real use: a live agent with a local model.
- **Tune on development data, report on held-out data.**
  - **LoCoMo:** tuned on conversations 26, 30 and 41; reported on the other seven.
  - **LongMemEval:** tuned on 60 questions drawn with a different seed and the same per-type quotas, disjoint from the test sample; reported on Gemmery's fixed 60 questions (`bench/lme_gemmery60.json`) and on all 500.
- **Fixed harness.** The reader prompt, the judge prompts (verbatim from the official code) and the answer extraction were not changed during tuning.
- **One thing deliberately not tuned:** the relevance check that decides whether to inject anything. Every benchmark question is about memory, so tuning that check on benchmarks would teach it to always inject, which is the wrong behaviour in real chat.

## Passive and active recall

Sophia is measured two ways, and each is compared only with its own kind:
- **Passive:** Sophia injects what it recalls before the agent reads the message, and the agent answers from that. The agent does nothing to remember. This is the setting of most published memory numbers (retrieve, then answer), so passive scores are the ones to put next to Mem0, Zep or Hindsight.
- **Active:** the same injection, plus Sophia's tools (`sophia_recall`, `sophia_query`, `sophia_browse`) with its system note and memory skill, for up to four rounds. This is how Hermes actually runs Sophia. It belongs next to agentic memories, where the model searches on its own.

Passive is allowed to be the weaker of the two: it is the floor the agent gets for free.

## LongMemEval (S, cleaned; Gemmery's 60 held-out questions)

| Memory | Reader | Recall | Accuracy | Task-averaged | Abstention |
|---|---|---|---|---|---|
| None | 9B | | 0.183 | 0.176 | 7/8 |
| Sophia, pilot settings | 9B | passive | 0.633 | 0.644 | 6/8 |
| Sophia, development-tuned | 9B | passive | 0.750 | 0.723 | 6/8 |
| **Sophia, + resolved dates and agent-words recall** | 9B | passive | **0.833** | 0.802 | 6/8 |
| **Sophia, same** | 27B | passive | **0.867** | 0.885 | 5/8 |
| Sophia, same | 27B | active | 0.850 | 0.836 | 4/8 |
| Evidence sessions only (the reader's ceiling) | 9B | | 0.917 | 0.854 | 6/8 |
| Evidence sessions only (the reader's ceiling) | 27B | | 0.900 | 0.875 | 6/8 |

- **The last Sophia change** labels relative time words with the date they mean ("last Saturday" = 2023-05-20) and treats the agent's own lines as evidence when the user asks what the agent said. Development set: 0.733 → 0.750. Held-out: 0.750 → 0.833, mostly temporal (12/16 → 14/16) and single-session-assistant (5/7 → 7/7).
- **With the 27B reader,** passive Sophia is at 0.867 against a ceiling of 0.900: 96% of what the same reader does with only the right sessions in view.
- **Active did not beat passive here** (0.850 against 0.867, well within noise). It lost one abstention: when the agent searches and finds something nearby, it answers instead of saying it doesn't know.
- **Uncertainty:** with 60 questions, the 95% interval is roughly ±0.09–0.11. Differences of a few points between rows are not significant.
- **Memory mode:** day memory only (no night). A night per question costs several minutes of model time for about 2,000 windows.
- **The "pilot" run was interrupted.** Two runs collided on a shared scratch memory, so it was cut back to its first 24 verified questions and resumed with the same settings pinned by flags.

### All 500 questions

Sophia with resolved dates, 9B reader and judge, passive, day memory: **0.804** (task-averaged 0.795; abstention 25/30).

| Type | n | Accuracy |
|---|---|---|
| knowledge-update | 78 | 0.936 |
| single-session-user | 70 | 0.914 |
| single-session-assistant | 56 | 0.804 |
| temporal-reasoning | 133 | 0.782 |
| multi-session | 133 | 0.737 |
| single-session-preference | 30 | 0.600 |

The whole run, including building each question's memory from about 50 sessions, averaged 44 seconds per question.

### Does a night help on LongMemEval?

Each LongMemEval question has its own haystack of about 50 sessions, so the rows above use day memory only. To see what a night adds, a stratified 20-question slice of the development set (`bench/lme_dev20.json`) got one night per question. The 9B wrote and decided, with model-written headers only for the user's lines. A night took a median of 14 minutes, about 2,000 windows each on 4 parallel slots.

| Memory | All evidence in the top 30 | All evidence injected | Characters injected | Answer accuracy (9B reader) |
|---|---|---|---|---|
| Day | 16/20 | 15/20 | 5,184 | 0.65 |
| After a night | 17/20 | **18/20** | 6,747 | **0.75** |

- **The direction is right, but the sample is small.** Paired, the night won 2 questions and lost none: a preference question and an event-ordering question. That isn't significant with 20 questions.
- **The retrieval gain is in multi-session questions** (all evidence injected: 3/5 → 5/5) and one temporal question (4/6 → 5/6). The 9B reader still counted wrong on the multi-session questions, so those answers didn't improve. That's a reader limit, not a memory one.
- **In real use, a night runs once over everything new, not once per question.** The cost that makes this benchmark expensive (a fresh night per haystack) doesn't arise.

`bench/run_dev20_night.sh` reproduces it, and a resumed run skips nights that are already built.

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

| Memory | Reader | Recall | J | Multi-hop (1) | Temporal (2) | Open-domain (3) | Single-hop (4) |
|---|---|---|---|---|---|---|---|
| Sophia, day memory | 9B | passive | 0.671 | 0.663 | 0.476 | 0.373 | 0.778 |
| Sophia, after one night (9B night model) | 9B | passive | 0.730 | 0.740 | 0.567 | 0.387 | 0.825 |
| Sophia, after one night (27B night model) | 9B | passive | 0.748 | 0.755 | 0.593 | 0.387 | 0.844 |
| Sophia, after one night (27B writes, 9B decides) | 9B | passive | 0.745 | 0.721 | 0.636 | 0.413 | 0.830 |
| The whole conversation in the reader's context | 9B | | 0.768 | 0.788 | 0.619 | 0.480 | 0.849 |
| Sophia, after one night (27B writes, 9B decides) | 27B | passive | 0.780 | 0.755 | 0.706 | 0.507 | 0.847 |
| **Sophia, same memories** | 27B | **active** | **0.858** | 0.817 | 0.805 | 0.640 | 0.916 |
| The whole conversation in the reader's context | 27B | | 0.853 | 0.803 | 0.805 | 0.547 | 0.922 |

- **Scale:** 1,155 questions over 7 conversations (roughly 700–950 windows each), scored with Mem0's J prompt; category 5 excluded, as is conventional.
- **Active recall matches full context.** With the 27B reader and Sophia's tools, J is 0.858 against 0.853 with the whole conversation in context, a tie within noise. It gets there from recalled passages, not the whole ~70,000-character conversation.
  - Against passive on the same memories: 114 questions won and 24 lost.
  - The agent used a tool on a third of the questions (589 `sophia_recall`, 196 `sophia_browse` and 27 `sophia_query` calls), at 15 s per question against 8 s for passive.
  - The largest gain is open-domain inference: 0.507 → 0.640, above full context's 0.547.
- **Passive against full context:** 95–97% of the same reader's full-context score with the 9B reader, and 91% with the 27B. A stronger reader gets more out of seeing everything, which is why active recall matters more as the reader improves. Full context stops being an option at LongMemEval scale (about 490,000 characters per question).
- **All LoCoMo rows share one judge,** the 9B, which is 2.5–4.5 points generous on LoCoMo against the 27B (see [judge agreement](#judge-agreement)). The rows compare fairly with each other. Against published numbers, active recall is about 0.83 under the stricter judge.
- **27B writes, 9B decides:** scored 0.745 against 0.748 for the all-27B night, on the same 9B reader. This run also had resolved dates, which helps temporal questions (0.593 → 0.636) but not multi-hop ones (0.755 → 0.721), so it isn't a clean comparison of night models. Its nights shared the GPUs with other runs, so their times aren't comparable either.
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

## Almanac (time, plans, provenance, absence, tasks, hygiene)

[Almanac](https://github.com/jbpayton/almanac) is a separate benchmark, written alongside Sophia, of the things LoCoMo and LongMemEval don't ask: when something was said, whether a plan happened, where a belief came from, what was never mentioned, how a task was done, and whether memory can be tricked. Its v0.1 test set is 8 generated lives. The same reader and judge (Qwen3.8-27B) were used for every system:

| System | Recall | Overall | Hygiene | Secret kept | Quiet: memory injected | Context (chars) |
|---|---|---|---|---|---|---|
| Full context | | 0.945 | 0.62 | 8/8 | 0/16 | 18,789 |
| RAG, top 15 | | 0.899 | 0.33 | 8/8 | 16/16 | 1,728 |
| Sophia, by day | passive | **1.000** | 1.00 | 0/8 | 5/16 | 1,951 |
| Sophia, after a night | passive | 0.990 | 1.00 | 0/8 | 9/16 | 2,950 |
| Sophia, after a night | active | 0.995 | 1.00 | 0/8 | 9/16 | 4,349 |

- **It found a real bug.** A pasted key was redacted in its own message but survived in the next reply's context header and in the injection log (14 of 19 databases). Fixed, and existing databases are scrubbed on first open. The rows above are from the fixed code.
- **It found a real weakness.** Memory reaches some questions that need none (5 of 16 by day, 9 of 16 after a night), usually through a word they share with old small talk. It is not tuned here, because tuning on the test lives would be teaching to the test.
- **Its limits.** v0.1 lives are short, so a 27B with everything in context is near the ceiling too. See Almanac's README.

## Judge agreement

The 9B judges every run above. To check it, `bench/judge_agreement.py` re-grades a sample with the 27B, using the same official prompts:

| Benchmark | Sample | Agreement | 9B says right, 27B wrong | 9B says wrong, 27B right | Accuracy, 9B → 27B judge |
|---|---|---|---|---|---|
| LongMemEval | 60 (held-out) | 96.7% | 1 | 1 | 0.750 → 0.750 |
| LoCoMo | 200 (held-out, after a night) | 91.5% | 13 | 4 | 0.750 → 0.705 |
| LoCoMo, active recall, 27B reader | 200 (held-out) | 94.5% | 8 | 3 | 0.835 → 0.810 |

- **LongMemEval scores stand as they are.**
- **LoCoMo J from the 9B judge is 2.5–4.5 points generous** against a stricter judge, mostly partial answers it accepts. Comparisons inside the LoCoMo table are fair, because every row has the same judge. Against published numbers, subtract a few points: active recall's 0.858 is about 0.83 under the 27B judge.

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
| Relative dates | The reader had to work out which date "last Saturday" meant from the line's date, and often got it wrong | Injected lines label relative time words with the date they mean (`show_resolved_dates`). LoCoMo development conversation: 0.645 → 0.684, temporal 0.51 → 0.70 |
| The agent's own words | "What did you recommend?" needs the agent's lines, which recall normally ranks down so the agent doesn't quote itself as fact | When the user asks about the agent's words, agent lines are evidence: no penalty, no cap |
| Who judges at night | Every night threshold was measured on the 9B's one-token readouts | The night model writes; its yes/no judgments go to the decider (`night_judge: decider`) |

## Reproducing

```bash
python bench/longmemeval.py --mode sophia --sample gemmery60 --tag mine     # also: oracle | none
python bench/locomo.py --mode sophia --convs conv-42,conv-43 --tag mine     # also: sophia-night | full | none
python bench/retrieval.py --convs conv-26 --set inject_top=30              # retrieval only, fast
```

The data goes in `../bench-data/` ([bench/README.md](../bench/README.md) lists the sources). Results and the exact setup of every run are written to `bench/results/*.summary.json`.
