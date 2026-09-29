# Benchmarks

Sophia on LongMemEval and LoCoMo, measured on one machine (2× RTX 3090, LM Studio). Readers are **Qwen3.5-9B** or **Qwen3.8-27B**, as labelled; the judge is the 9B with the official prompts (its agreement with the 27B judge is measured [below](#judge-agreement)). Published systems mostly use GPT-4o-class readers and judges, so these numbers show where Sophia stands with small local models. They are not a leaderboard entry.

## In short

**Where Sophia stands.** All results below use local models, on held-out data, with the official prompts. The judge is the 9B unless noted.

| Benchmark | Sophia | For comparison |
|---|---|---|
| LongMemEval-S, all 500 questions | **0.802** (Qwen3.5-9B reader, memory injected before each reply) | Full context with GPT-4o: 0.606 (the LongMemEval paper) |
| LongMemEval-S, 60 held-out questions | **0.867** (Qwen3.8-27B reader) | The same reader handed only the right sessions: 0.900 |
| LoCoMo, 7 held-out conversations | **0.869** with the agent also using the tools, **0.806** injection only (27B reader) | The same reader with the whole conversation: 0.853 |
| Almanac v0.1, 8 test lives (27B reader and judge for every system) | **0.990–1.000** | Full context 0.945; retrieval of the top 15 messages 0.899 |
| Almanac v0.2, 8 held-out lives | **0.957** (9B reader), **0.996** (27B reader) | Baselines not yet run |

**How to read that against published numbers.** Hermes's memory plugins publish LongMemEval scores between about 79 and 94, and LoCoMo between about 83 and 96 (see [the comparison](COMPARISON.md#published-benchmark-numbers)). Those numbers differ from Sophia's in three ways, so neither side's are directly comparable:
- **The answering model is much larger** (Gemini 3, GPT-5 class, Claude Haiku, gpt-oss-120b), and so is the judge. Sophia's reader and judge run on one desktop.
- **Each vendor runs its own harness,** on its own service rather than through its Hermes plugin. Some use easier variants, such as RetainDB's oracle split, which contains only the sessions that hold the evidence.
- **The judges differ,** and judges differ in how generous they are. Sophia's 9B judge is 2.5–4.5 points more generous on LoCoMo than a 27B judge (see [judge agreement](#judge-agreement)).

The closest like-for-like point is Hindsight's own paper. With gpt-oss-20b, a model near the 27B's size, as the answering model, Hindsight reports 83.6 on LongMemEval-S, against Sophia's 80.2 with a 9B reader and 86.7 with the 27B on the held-out 60.

**Sophia isn't tied to these models.** The reader is the agent's own chat model, whatever Hermes runs, local or cloud. Sophia's three models (embeddings, the check before each reply, and night work) are separate settings. Stronger models have helped at every step measured:
- **Reader:** LongMemEval held-out went 0.833 → 0.867 from the 9B to the 27B (same settings), against a ceiling of 0.900.
- **Night model:** on LoCoMo the 27B extracted about twice as many facts as the 9B, and scored +1.8 points.
- **Reader and tools together:** LoCoMo passive went 0.789 (9B) → 0.806 (27B), and with the tools 0.869.

A frontier reader should push these up further. We haven't measured one, so treat that as an expectation, not a result. A heavier judge cuts the other way: stricter judging would take a few points off LoCoMo.

**Time and cost matter too.**
- **Saving:** no model generates text when Sophia saves. The only model call is a quick one-token check of the agent's own replies.
- **Each message:** the check before a reply runs on your own model server, in about 0.6 s end to end (0.4 s for the check itself on llama-server), or 0.04 s with `gate: similarity`.
- **The agent's reading:** the agent reads from about 2,000–4,300 characters of recalled memory, against about 18,800 for the whole history (Almanac v0.1). At LongMemEval's 490,000 characters per question, the whole history isn't an option at all.
- **The night:** the heavy work waits for the night. It runs on your GPU while you're idle, about 20 minutes for a busy day on the 27B. It costs no API fees.
- **Other providers:** most of Hermes's other providers run an LLM on every turn or session, usually on a paid service. Before each reply they either wait on a network call (budgets of 3–8 s) or use a result fetched after the previous turn, one turn behind (see [the comparison](COMPARISON.md#time-and-cost-per-message)).

We haven't run a head-to-head latency or cost test yet.

**Why we wrote our own benchmark.** LongMemEval and LoCoMo ask questions about long chat histories. Every question needs memory, and the score is answer accuracy. An agent's memory runs on every message, so it has other jobs too:
- stay out of the way when nothing is needed;
- say "you never told me" when a plan's outcome was never told;
- tell a near-miss from an answer: a brother-in-law is not a brother;
- keep an old fact that's still true, and retire a "next weekend" from months ago;
- know who said something: you, the agent, or a web page;
- refuse instructions planted in a web page, and keep a pasted key out of memory;
- remember how a task was done.

The standard benchmarks score none of these. [Almanac](https://github.com/jbpayton/almanac) does, and gives every system the same reader and judge. It was written by Sophia's author, alongside Sophia, so read it as a published list of requirements with a harness, not as independent evidence. It's open so other memories can be run on it. Its lives are templated and short, so full context is near the ceiling there too.

## Protocol: improve without teaching to the test

- **Only general mechanisms.** No benchmark-specific prompts, category logic or answer formats. Every setting change has to make sense for Sophia's real use: a live agent with a local model.
- **Tune on development data, report on held-out data.**
  - **LoCoMo:** tuned on conversations 26, 30 and 41; reported on the other seven.
  - **LongMemEval:** tuned on 60 questions drawn with a different seed and the same per-type quotas, disjoint from the test sample; reported on Gemmery's fixed 60 questions (`bench/lme_gemmery60.json`) and on all 500.
- **Fixed harness.** The reader prompt, the judge prompts (verbatim from the official code) and the answer extraction were not changed during tuning.
- **The relevance check is tuned on both sides.** Every benchmark question is about memory, so tuning the check that decides whether to inject on benchmarks alone would teach it to always inject. Its development data therefore also has hand-written requests that need nothing about the user, generic-sounding personal requests, and follow-ups. It is reported on request sets written before the setting was chosen and not looked at while choosing ([the choice gate](#the-choice-gate-one-readout-that-gates-and-splits-the-lines)).

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
| Sophia v6: evidence listed by date, advice mode | 9B | passive | 0.700 | 0.750 | 4/8 |
| Sophia v6 code with those two off, same memories (control) | 9B | passive | 0.817 | 0.823 | 6/8 |
| Sophia v6 | 27B | passive | 0.867 | 0.854 | 6/8 |
| Sophia v6 | 27B | active | 0.833 | 0.848 | 3/8 |
| Evidence sessions only (the reader's ceiling) | 9B | | 0.917 | 0.854 | 6/8 |
| Evidence sessions only (the reader's ceiling) | 27B | | 0.900 | 0.875 | 6/8 |

- **v6 hurt the 9B on these 60 questions.** Listing the evidence by date (see [what changed](#what-changed-and-why)) won 1 question and lost 8 against the control on the same memories, mostly multi-session (0.69 → 0.44) and temporal (0.75 → 0.56). It had helped the same reader on the development set (6 won, 2 lost). With the 27B reader it made no difference. On all 500 questions it is neutral (below), so it stayed: it helps LoCoMo clearly. A small reader seems to rely on the best match coming first, and LongMemEval's injections are mostly noise around one or two passages.
- **The resolved-dates change** labels relative time words with the date they mean ("last Saturday" = 2023-05-20) and treats the agent's own lines as evidence when the user asks what the agent said. Development set: 0.733 → 0.750. Held-out: 0.750 → 0.833, mostly temporal (12/16 → 14/16) and single-session-assistant (5/7 → 7/7).
- **With the 27B reader,** passive Sophia is at 0.867 against a ceiling of 0.900: 96% of what the same reader does with only the right sessions in view.
- **Active did not beat passive here** (0.850 against 0.867, well within noise). It lost one abstention: when the agent searches and finds something nearby, it answers instead of saying it doesn't know.
- **Uncertainty:** with 60 questions, the 95% interval is roughly ±0.09–0.11. Differences of a few points between rows are not significant.
- **Memory mode:** day memory only (no night). A night per question costs several minutes of model time for about 2,000 windows.
- **The "pilot" run was interrupted.** Two runs collided on a shared scratch memory, so it was cut back to its first 24 verified questions and resumed with the same settings pinned by flags.

### All 500 questions

With `gate: similarity` (floor 0.60): 0.798 (4 won, 6 lost against v6; memory kept out of 7 of the 500 questions). On the 60 held-out questions: 0.683 (9B), 0.850 (27B passive), 0.850 (27B active).

Sophia with resolved dates, 9B reader and judge, passive, day memory: **0.804** (task-averaged 0.795; abstention 25/30). **v6: 0.802** (task-averaged 0.782; abstention 23/30): 29 questions won, 30 lost. Within that, the held-out 60 fall from 0.800 to 0.700 and the other 440 rise from about 0.805 to 0.816. Runs with the same settings agree question for question (temperature 0), so these differences are the change, not noise.

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
| Sophia v6: evidence listed by date, advice mode (same memories) | 9B | passive | 0.789 | 0.745 | 0.693 | 0.387 | 0.885 |
| Sophia v6 | 27B | passive | 0.806 | 0.769 | 0.740 | 0.493 | 0.878 |
| **Sophia v6** | 27B | **active** | **0.869** | 0.870 | 0.796 | 0.613 | 0.925 |
| Sophia v6 with `gate: similarity` (floor 0.60) | 9B | passive | 0.788 | 0.731 | 0.688 | 0.440 | 0.883 |
| Sophia v6 with `gate: similarity` | 27B | passive | 0.807 | 0.774 | 0.740 | 0.493 | 0.878 |
| Sophia v6 with `gate: similarity` | 27B | active | 0.867 | 0.865 | 0.796 | 0.627 | 0.920 |

- **Scale:** 1,155 questions over 7 conversations (roughly 700–950 windows each), scored with Mem0's J prompt; category 5 excluded, as is conventional.
- **v6 on the same memories:**
  - Passive with the 9B reader: 0.745 → 0.789 (102 won, 51 lost).
  - Passive with the 27B: 0.780 → 0.806 (66 won, 36 lost).
  - Active with the 27B: 0.858 → 0.869 (50 won, 37 lost).
  - Both passive gains are significant (sign test p < 0.005). They held from the development conversations (0.730 → 0.790, 42 won, 19 lost), and multi-hop, temporal and single-hop questions all gain.
  - Active recall is now 0.869 against 0.853 for the same reader with the whole conversation in context (better on 73 questions, worse on 54; p ≈ 0.09): on par, slightly ahead.
- **The similarity gate** gave the same held-out scores (within 2 questions of v6 in each setting), with lower time per question: passive recall itself takes 0.04 s instead of 0.65 s.
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
- **The similarity gate (`gate: similarity`, floor 0.60) did worse here:** passive by day scored 0.975. Four relevant questions got nothing because their best match scored under 0.60, and memory reached 12 of 16 off-topic questions. With a night it scored 0.990, and active 0.995. That's why the decider gate stays the default.
- **Its limits.** v0.1 lives are short, so a 27B with everything in context is near the ceiling too. See Almanac's README.

## Response time

Passive recall runs on every message, before the agent reads it, so it has to be fast. Active recall is a tool the agent chooses to call, so it can take longer. Measured on the development set's LongMemEval memories, about 2,000 windows each, with LM Studio on this machine (`bench/profile_prefetch.py`):

| Passive recall step | Median | p90 |
|---|---|---|
| Search: embed the message, vectors, text search, graph | 0.07 s | 0.08 s |
| The whole passive path, including the relevance gate | 0.65 s | 0.95 s |

- **The gate is the cost:** one decision call, asked on 50 of 60 messages; a very strong match (cosine ≥ 0.82) skips it. This was the yes/no gate, the default then. The choice gate, the default since v8, reads strong matches too; its time is [below](#the-choice-gate-one-readout-that-gates-and-splits-the-lines).
- **Most of that is LM Studio's fixed cost per uncached request.** The same call with no memories in it takes 0.38 s, with 3 memories 0.43 s, and with the usual 10 memories 0.57 s. Trimming what the gate sees would save little.
- **Every accuracy change in v6 is ranking or formatting.** No model calls were added, and passive time didn't change.

### The relevance gate: what it filters, and at what cost

The gate should let memory through when it bears on the message, and keep it out of small talk and general questions. Tested on development data (`bench/gate_variants.py`, `bench/gate_wording.py`; 60 plainly impersonal requests in `bench/gate_offtopic.json`):

- **In large memories (about 2,000 windows), the one-order gate filters almost nothing.** It passed 453 of 455 relevant questions and 29 of 30 off-topic ones: there is always something vaguely similar, and a single reading leans towards "yes".
- **In small memories it does filter.** On Almanac, the yes/no gate kept memory out of 11 of 16 off-topic questions and passed every relevant one.
- **A sharper wording read in both orders** separates better in large memories: 98.9% of relevant passed, 50 of 120 off-topic. But LM Studio runs the two long prompts one after the other, so passive time doubled (0.65 → 1.21 s), and it turned away 2% of real questions (LoCoMo development 0.790 → 0.771). Not adopted.
- **Similarity alone can't do it.** In large memories a floor of 0.60 keeps about 99% of relevant messages and turns away 20–33% of off-topic ones. In small memories, off-topic questions score as high as relevant ones: on Almanac's development lives, relevant questions went as low as 0.55 and off-topic ones were 0.59–0.66. On the Almanac test lives, 0.60 blocked 4 relevant questions ("Which city do I live in now?" went unanswered) and let 12 of 16 off-topic ones through.

**Settings:**
- **`gate: choice`** (the default since v8): one readout with an option per memory. See the next section.
- **`gate: decider`** (the default before v8, one order): it filters well in small memories and hardly at all in large ones.
- **`gate: similarity`** with `gate_floor: 0.50`: under 0.1 s; it lets memory through on nearly every message. On held-out data it scored the same as the yes/no gate, apart from the Almanac misses above at 0.60.

**Also tested and rejected:** the gate through the chat endpoint (top letter only), which was 0.2 s faster but turned away 17% of relevant messages.

### The choice gate: one readout that gates and splits the lines

The yes/no gate asks whether at least one memory is relevant. That is a low bar, and in a large memory it is nearly always met. Worse, once it is met every injected line reads as equally trustworthy. Sophia, the agent persona the maintainer runs on Hermes, reviewed this from the reader's side. One real match mixed in with nine lines that only look related is how a reader ends up asserting a near-miss as fact. The design below was worked out with her.

**One question, with one option per memory.** The decider sees the message, the previous user message when this one is a short follow-up, and the top 10 memories, numbered. It picks one answer:
- "nothing": a good reply would be the same for any user;
- "none fits": it is about the user or earlier conversations, but none of these memories bears on it;
- "memory [i] bears on it most directly", one option per memory.

From that single readout:
- **Gate:** memory is injected unless "nothing" reaches 0.8 (`gate_general`). A very strong match (cosine ≥ 0.82) is always injected, and so is one found while the decider is unreachable.
- **Whole-block label:** when "none fits" outweighs all the memories together, the block is headed *possible matches only: less certain; rely on one only if it clearly answers the message*.
- **Second reading:** if the first reading is unsure (0.05–0.95) and a second reading could still change the decision, the options are read again in reverse order and the two readings are averaged.
- **Split, off by default** (`gate_split`): lines holding at least 2% of the memories' probability (`split_min`) are listed under **Relevant**, and the rest under **Possible matches**. On held-out LoCoMo it cost answers, so it is opt-in. See below.

**How it was chosen** (development data only; `bench/gate_choice.py`, `bench/gate_wording_choice.py`, `bench/split_study.py`, `bench/combo_study.py`):
- **Two stages.** First tried as two stages: a message-only check (`bench/message_check.py`), then the relevance gate. It doubled passive time from 440 ms to 991 ms median (`results/stage1_check.json`, from a script removed along with the feature), so the stages were folded into one three-way question.
- **Wording.** The first wording listed kinds of general request ("a definition, fact, calculation…"). On a fresh held-out set it let 13 of 40 general requests through, against 7 of 60 on the tuning set: it had learned the list. That held-out set became development data, and a principle ("the same for any user") replaced the list. A new held-out set was written before the principle was tried.
- **Split readout.** A separate "which memory" readout after the gate added about 280 ms. The decider's recurrent layers keep llama.cpp from reusing a cached prompt that diverges partway through, so every call pays in full. Folding the split into the gate question costs one call. Its gate needed the higher cutoff (0.8) to keep every relevant question. Of the LongMemEval answer lines in the top 10, it kept 94 of 113 under Relevant; only 2 of 81 questions had all their evidence demoted. Precision was 0.42, a lower bound, since answer turns are labelled sparsely.

**Held out** (`bench/gate_check.py` and `bench/follow_up_check.py`; relevant questions from the large development memories, about 2,000 windows):

| Messages that got memory | Yes/no gate | Choice gate |
|---|---|---|
| Relevant questions (LongMemEval, LoCoMo) | 234 / 236 | 235 / 236 |
| General requests, held out | 26 / 40 | **6 / 40** |
| Personal requests, held out ("what should I cook tonight?") | 23 / 25 | 24 / 25 |
| Follow-ups to a general request ("and in Kelvin?") | 10 / 10 | **1 / 10** |
| Follow-ups about people in memory ("when did she apply to them?") | 10 / 10 | 10 / 10 |

- **Whole block marked possible:** 4 of 236 relevant questions.
- **Writing tasks:** writing about people in memory ("a short bio for Jon's dance studio website") opened the gate 9 times out of 10 on development memories. The miss was "a short birthday message for Melanie".
- **With the split on:** a median of 2 lines per relevant question were listed as Relevant, 577 of the 9,430 injected.

**Answers** (paired, same code and serving, 9B reader and judge; passive; `bench/run_final_v8.sh`, `bench/run_heldout_v8.sh`, `bench/run_choice_dev.sh`, `bench/run_label_dev.sh`). The default is the second column:

| | Yes/no gate | Choice gate | With the split, "verify before relying" label | With the split, "rely on one only if it clearly answers" label |
|---|---|---|---|---|
| LongMemEval development 60 | 0.800 | 0.750 | 0.767 | 0.850 |
| LongMemEval preference questions (development) | 0.385 | 0.308 | 0.462 | 0.500 |
| LoCoMo development | 0.784 | 0.805 | 0.784 | 0.779 |
| Almanac development lives | 0.960 | 0.920 | 0.973 | 0.947 |
| **LongMemEval, held-out 60** | 0.817 | **0.817** (no answer changed) | 0.783 | |
| **LoCoMo, held-out** | 0.798 | **0.797** (won 16, lost 17) | 0.772 (won 52, lost 82) | |
| **Almanac test lives, 199 scored** | 0.930 | **0.940** (won 3, lost 1) | 0.940 | |
| Almanac quiet questions with memory injected (held out) | 7 / 16 | **0 / 16** | 0 / 16 | |

- **The held-out rows are the comparison to read.** With the split off, the injected text is the same as the yes/no gate's whenever both open. Across the 1,960 questions above, the choice gate closed only 2 that the yes/no gate opened, and neither answer changed. The held-out answers are unchanged: LongMemEval identical, LoCoMo −1 of 1,155, Almanac +2 of 199. What changed is what reaches the reader when nothing is needed: 0 of 16 Almanac quiet questions with memory, against 7.
- **Development rows are noisier than they look.** The yes/no and "verify" columns ran before a one-character fix to the injected header (a stray parenthesis), and the other two after it. That fix alone, with the text otherwise identical, moved 7 of the 60 LongMemEval development answers: that is the run-to-run noise of these small sets. Every held-out arm ran after the fix.
- **Why the split is off.** On held-out LoCoMo the split lost 82 questions and won 52, nearly all of them simple lookups. The answer line was injected, the readout filed it under Possible matches, and the reader, told to verify it, answered "It was not mentioned": "How long have Mel and her husband been married?" went from "5 years" to "It wasn't mentioned". The same pattern was in the development data, hidden by gains elsewhere. A reader can't verify a line; it can only judge whether the line answers the question. The softer label asks for that, and recovered LongMemEval on development data but not LoCoMo or Almanac.
- **The cutoff doesn't fix it either.** The readout names the one memory that bears on the message most directly. A counting question needs several, and its second and third lines can fall under 2%. At 0.5%, all the evidence stayed under Relevant for 28 of 33 multi-line development questions, against 20 at 2%. But superseded lines then read as sure as the current one: "which city do I live in now?" failed on two Almanac lives. On development data it was a wash (LongMemEval +3 of 86, Almanac −2 of 75). Held out: LongMemEval 0.800, Almanac 0.915.
- **What the split is for.** Questions where a near-miss is dangerous: an absence question with a same-topic memory nearby, a topic match that doesn't answer, a stale value. The current benchmarks have few of those, so the split stays opt-in until a benchmark does.

**Time** (`bench/profile_prefetch.py`, LongMemEval development memories, llama-server): the whole passive path takes 607 ms median and 632 ms p90, against 514 ms and 538 ms with the yes/no gate. The prompt is longer, and strong matches now get a readout too.

### Almanac v0.2: near-misses and stale plans

[Almanac v0.2](https://github.com/jbpayton/almanac) adds the question types Sophia flagged as the ones where a near-miss is dangerous:
- **Near-miss:** "What's my brother's name?" when only a brother-in-law was mentioned; "Which dermatologist do I see?" when only the family doctor and the dentist were.
- **No answer:** "What's my cat's name?" when the cat came up twice and its name never did.
- **Stale:** a fact said once, five months earlier and still true. Also a follow-up in the same conversation, "Is it still happening next weekend, like I told you?", about a plan from months ago.

**Development** (`bench/run_almanac_v02_paired.sh`; 10 development lives, 319 scored questions). Each life's memory is built once, with a night, and every arm reuses it, so the arms differ only in recall. 9B reader and judge:

| | Yes/no gate | Choice gate | With the split |
|---|---|---|---|
| Overall | 0.934 | 0.931 | 0.931 |
| Near-miss (person / provider) | 10/10 · 7/10 | 10/10 · 7/10 | 10/10 · **10/10** |
| No answer | 19/20 | 19/20 | 20/20 |
| Stale: still true · follow-up | 20/20 · 6/10 | 20/20 · 7/10 | 20/20 · 7/10 |
| Change: current · previous · count | 10/10 · 19/20 · 3/10 | 10/10 · 17/20 · 3/10 | 9/10 · 15/20 · 4/10 |
| Plans: cancelled · outcome never told | 10/10 · 6/10 | 10/10 · 5/10 | **7/10** · 7/10 |
| Quiet questions with memory injected | 12/20 | **1/20** | 1/20 |

- **The split does what it was meant to, and costs as much.**
  - "Which dermatologist do I see?": without the split the reader named the family doctor 3 times in 10, because the gate judged that line relevant and nothing was labelled. With the split, it said it didn't know every time.
  - "Did I go to The Lumineers concert?" needs two lines, the tickets and the cancellation. In the 3 lives where the cancellation landed under Possible matches, the reader answered "yes".
  - The net is zero, so the split stays opt-in.
- **"Now Y (was X)" instead of "X → Y"** for superseded facts, as Sophia suggested so a small reader can't read the arrow backwards: 5 questions won and 5 lost on identical memories. On 20 LongMemEval development questions with night memories, the answers were identical. Not adopted.
- **Stale plans.** Without help, the reader confirmed a months-old "next weekend" as still ahead in 4 of 10 follow-ups ("Yes, the kitchen repaint is still planned for next weekend (October 26–28)"). The phrase's resolved date was on the line, but nothing said it was over.
  - Marking it "now past" fixed those. It also made the reader assume past appointments had happened: "Did I go to my dentist appointment?", whose right answer is "you never told me", fell from 4 to 1 of 10.
  - Saying what the line does and doesn't know fixed both: "now past; this line doesn't say if it happened". Follow-ups went 6 → 9 of 10, appointments 4 → 8 of 10, overall 0.922 → 0.947 (`mark_passed_dates`).
  - Two runs of the same setting on the same memories differ by about three questions: the 0.931 and 0.922 above are both without the mark.

**Held out** (`bench/run_almanac_v02_heldout.sh`; the 8 v0.2 test lives, 255 scored questions, same method; nothing was tuned afterwards). The passed-dates mark is on in every arm except the second:

| | Choice gate (default) | Without the passed-dates mark | Yes/no gate | Choice gate with the split |
|---|---|---|---|---|
| Overall | **0.957** | 0.933 (8 lost, 2 won) | 0.953 | 0.914 (14 lost, 3 won) |
| Stale follow-up | 8/8 | 5/8 | 8/8 | 7/8 |
| Plan whose outcome was never told | 7/8 | 4/8 | 7/8 | 7/8 |
| Near-miss (person / provider) | 8/8 · 6/8 | 8/8 · 6/8 | 8/8 · 6/8 | 8/8 · 6/8 |
| Plan cancelled | 8/8 | 8/8 | 8/8 | **3/8** |
| Quiet questions with memory injected | **1/16** | 1/16 | 9/16 | 1/16 |

- **The passed-dates mark holds up:** stale follow-ups 5 → 8 of 8, and plans whose outcome was never told 4 → 7 of 8.
- **The split's near-miss gain from development did not repeat**, and its two-line cost did: a cancelled concert was answered "yes" in 5 of 8 lives. It stays opt-in.
- **Near-miss providers are still the weak spot for the 9B:** 2 of 8 "which dermatologist do I see?" were answered with another doctor's name, under every setting.
- **With the 27B as reader** (`bench/run_almanac_v02_r27.sh`, same memories, 9B judge): 0.996. The near-miss provider was right 8 of 8, the cancelled plan 8 of 8, and the move count 8 of 8. The one miss was a stale follow-up where the reader didn't guess what "it" meant and said so. The split scored the same (0.996; 1 won, 1 lost), so it stays opt-in.

### Serving the decider faster

Most of the gate's time on LM Studio is the server, not the model: `/v1/responses`, the only LM Studio endpoint that returns logprobs, costs about 0.24 s even for a tiny cached prompt. The same 9B file served by llama.cpp's `llama-server`, on one GPU (`bench/decider_servers.py`, 20 real gate prompts, none cached):

| Decider server | Gate call, median | p90 | Repeated prompt | Same decisions |
|---|---|---|---|---|
| LM Studio (model split over two GPUs) | 594 ms | 864 ms | 430 ms | |
| llama-server, one GPU | **399 ms** | **421 ms** | 216 ms | 40 / 40 (p within 0.009) |

- **Whole passive path** (development memories of 2,000 windows): 651 ms median and 954 ms p90 on LM Studio, against 490 ms and 527 ms on llama-server.
- **Showing the gate 5 memories instead of 10** would bring it to 361 ms, but it turned away 3 more of 76 relevant LongMemEval questions and 2 more of 148 LoCoMo ones, so it stays at 10.
- **Two option orders** still cost double on llama-server (850 ms): processing the prompt, not the server, is the limit.
- **Other servers:** vLLM and SGLang need 8–9 GB for this model's 4-bit checkpoints (its embeddings stay 16-bit), and their prefix caching for its hybrid recurrent layers is still unreliable. Details and sources are in [CONFIGURATION.md](CONFIGURATION.md#serving-the-decider).
- **Active recall** averaged 10 s per LoCoMo question with the 27B reader. On the LongMemEval development set its 90th percentile was about 30 s, most of it the reader's own tool rounds.

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
| Plans whose date is over | A months-old "next weekend" plan, asked about as a follow-up, was confirmed as still ahead in 4 of 10 Almanac v0.2 development lives | A resolved date that pointed ahead and is now over adds "now past; this line doesn't say if it happened" (`mark_passed_dates`). Development: 0.922 → 0.947. See [Almanac v0.2](#almanac-v02-near-misses-and-stale-plans) |
| The agent's own words | "What did you recommend?" needs the agent's lines, which recall normally ranks down so the agent doesn't quote itself as fact | When the user asks about the agent's words, agent lines are evidence: no penalty, no cap |
| Who judges at night | Every night threshold was measured on the 9B's one-token readouts | The night model writes; its yes/no judgments go to the decider (`night_judge: decider`) |
| Two option orders | Read one after the other: two round trips per decision | Read in parallel; on LM Studio this helps short prompts most, since it runs long prompts for one model largely one at a time |
| Order of the injected evidence | Ranked best first, the reader had to put events in order and tell separate occasions apart itself | Still chosen best first, then listed by date under a heading per day (`inject_order: time`). Development: LongMemEval 0.717 → 0.783, LoCoMo 0.730 → 0.790. Held-out: LoCoMo up in all three settings, LongMemEval-500 flat (see above) |
| "Can you suggest…" | Present-tense "you suggest" matched the pattern for asking about the agent's own words, which switched off the assistant penalty on exactly the requests that need it | Only past forms ("you suggested", "did you recommend") count |
| Relevance gate | In a large memory the yes/no gate let memory into 26 of 40 held-out general requests and into every follow-up. Once it opened, every injected line read as equally sure | One readout with an option per memory (`gate: choice`) that closes the gate on general requests and marks blocks where nothing fits; short follow-ups are judged with the previous message. Splitting lines into Relevant and Possible matches is opt-in. See [the choice gate](#the-choice-gate-one-readout-that-gates-and-splits-the-lines) |
| Advice requests | Asked for suggestions, the top slots went to the assistant's earlier generic advice rather than what the user had said about themselves | Advice requests rank the agent's lines a further 0.06 lower and keep the user's own past questions (which describe them) at full rank (`advice_penalty`, `advice_keeps_questions`). On the 26 preference questions outside the held-out set: evidence injected 0.69 → 0.89, answers 0.42 → 0.50 |

**Tried and rejected** on development data:
- **An exhaustive recall option** (`sophia_recall` with `all: true`: every candidate checked by the decider, matches returned oldest first). Active recall went 0.883 → 0.867: the agent used it on most questions, over-counted, and twice ran out of tool rounds. The p90 time per question went from 30 s to 46 s. Removed.
- **A heading asking the reader to use the user's preferences:** preference questions 0.42 → 0.46 and dev60 0.72 → 0.73, 4 won and 3 lost each, which is noise. Removed.

## Reproducing

```bash
python bench/longmemeval.py --mode sophia --sample gemmery60 --tag mine     # also: oracle | none
python bench/locomo.py --mode sophia --convs conv-42,conv-43 --tag mine     # also: sophia-night | full | none
python bench/retrieval.py --convs conv-26 --set inject_top=30              # retrieval only, fast
```

The data goes in `../bench-data/` ([bench/README.md](../bench/README.md) lists the sources). Results and the exact setup of every run are written to `bench/results/*.summary.json`.
