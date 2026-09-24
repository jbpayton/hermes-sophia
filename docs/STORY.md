# The story of Sophia

Sophia began on a Monday night with a question about porting an old project. By Wednesday afternoon it was a new memory provider running inside real Hermes Agent. On its first night, it filed a fact the agent had made up about a campground under the user's name. That bug, and the others only real use could find, shaped the final design.

This is how it got here: what was tried, what was measured, what was wrong, and what each lesson changed. All times are US Eastern and all dates are 2026. The numbers were measured on one machine with two RTX 3090s; the scripts and raw results are in [`research/`](../research/).

| When | What changed |
|---|---|
| Mon 21 Sep, 22:01 | "How well could I port SophiaAMS to Hermes?" The answer: very well |
| Tue 22 Sep, 09:03 | Not a port. A clean-sheet plugin |
| Tue 09:07–10:31 | Decision models: Jev, Laya, Von, jobe. Fast encoders were wrong; LLM readouts were right |
| Tue 12:28–14:06 | Extraction bake-off and speed levers. The stock 9B wins, about 6× faster with the right format |
| Tue 14:52 | "Are you doing a trick…?" Any LLM becomes a decider through its first-token logprobs |
| Tue 22:26 | Design v0.1 |
| Tue 22:40 | "When in Rome": nomic embeddings, and thresholds measured rather than inherited |
| Tue 22:51 | Gemmery joins. The raw record beats summaries; triples become an index |
| Wed 23 Sep, 08:03 | Awake and asleep: "sleep time" and a "dream sequence" |
| Wed 08:23–08:53 | Blind-spot review. Design v0.5: three clocks, typed spans, emergent over prescribed |
| Wed 14:19 | "Go ahead and try to implement this." |
| Wed 14:47 | The first night runs inside Hermes and finds the bugs no unit test could |

---

## 1. A port question

> "how well do you think I could port https://github.com/jbpayton/SophiaAMS to a Nous Hermes Agent plugin?"

[SophiaAMS](https://github.com/jbpayton/SophiaAMS) is an associative semantic memory. It extracts triples from conversation with an LLM, stores them in embedded Qdrant with sentence-transformer vectors, and has a goal engine and a graph browser called Mindscape.

Hermes Agent v0.21.4 has a `MemoryProvider` interface, and the two lined up almost one-to-one:

| SophiaAMS | Hermes |
|---|---|
| Stream monitor, before the model answers | `prefetch()` |
| Consolidation after the model answers | `sync_turn()` |
| Episode finalize | `on_session_end()` |
| Memory skills | `get_tool_schemas()` / `handle_tool_call()` |
| Web search and web reading | already in Hermes |

About half of SophiaAMS turned out to be scaffolding that Hermes already has. The biggest risk flagged was that embedded Qdrant takes a single-process lock, while Hermes runs its CLI, gateway and cron as separate processes.

## 2. Not a port: a clean sheet

> "So I think this doesn't become an in-place kind of fork. I think this becomes a completely new effort to recast this as a plugin like this."

**What memory can see.** Two facts shaped everything after this.

- **The old summary step hadn't earned its keep.** The author said it "didn't do much".
- **Hermes lets a memory provider watch everything.** It sees every turn through `sync_turn`, session boundaries, compression, and writes to the built-in memory, and it can read the session store afterwards. So memory can be built offline, off the chat's critical path.

**VRAM.** The machine has two 3090s. The author's everyday model, Qwen3.8-27B at Q6_K, filled about 29.6 GB across both cards and left roughly 9.5 GB free on each.

**Dependencies.** An audit found that only 3 of SophiaAMS's 18 dependencies carried its ideas. The novel core was about 2,500 of 11,500 lines. The new plugin could depend on numpy alone:

- SQLite instead of Qdrant;
- embeddings over HTTP from LM Studio;
- provenance built into the schema.

## 3. Models that decide instead of talk

> "These are a new kind of model that are blazingly fast. They're effectively LLMs, but they don't generate text."

**The idea.** The author wanted memory recall to navigate the data: walk Mindscape one room at a time, deciding at each door. TypeSafe's Jev had just launched as an API-only "System One" model with three primitives:

- **Choice:** pick one of several options;
- **Score:** place something on an ordered scale;
- **Noul:** the probability that a statement is true.

**The false start.** Hearing "J-E-V… Leia", the assistant went looking for JEPA until the author stopped it: "This is not Jepa keep researching- it's Jev". It then compressed Laya into a single table row until asked to "search that name literally", and ran a GPU test before being asked to. That last slip turned into a standing rule: say so before running local experiments.

**The candidates:**
- [Laya](https://github.com/NandhaKishorM/laya): a 421M decision head on ModernBERT-large.
- [Von](https://github.com/wfzyx/von): a 395M encoder that speaks Jev's wire format.
- [jobe](https://github.com/MantisShrimpdev/jobe): a logit readout on a frozen Qwen3.5-4B.

**The test.** One synthetic room: "What camera did Joey use for the Yosemite trip?", seven triples about the trip, five doors plus `back` and `stop_here`. It ran once with the answer absent and once with it planted.

| | Found here? | Door | Speed |
|---|---|---|---|
| Laya | 0.73 → 0.76, barely moved | wrong | ~45 ms |
| Von | 0.9999 → 1.0, saturated | wrong both times | ~126 ms |
| jobe (4B) | no 0.99 → yes 0.995 | right both times | ~110 ms per decision, 8.65 GB |
| The 27B already in LM Studio | no 0.96 → yes 0.99 | right both times (0.998) | ~1.1–1.3 s, no extra VRAM |

The encoders were "fast and wrong" zero-shot. The LLM readouts were right. Getting logprobs out of LM Studio at all took some digging:

- the completions and chat endpoints return `logprobs: null`;
- `/v1/responses` does return them, but only with reasoning switched off (`"reasoning": {"effort": "none"}`).

## 4. Hunting for a small extractor

> "Go ahead and start with nuextract… it might be the ticket here…"

**The bake-off.** Triple extraction needed a model smaller than the 27B. NuExtract3, a Qwen3.5-4B fine-tune built for extraction, went up against the stock 9B and the 27B. All three ran SophiaAMS's own prompts on five chunks: an encyclopedia entry, a conversation, a shell procedure, a noisy web page, and a personal note.

| | Time per chunk | Triples | Null objects |
|---|---|---|---|
| Qwen3.8-27B | 11–30 s | 50 | 0 |
| **Qwen3.5-9B**, reasoning off | 7–12 s | 38 | 0 |
| NuExtract3 + 1 example | 3–6 s | 33 | 1 (no instruction removed them) |

**Verdict:** "NuExtract3 is not the ticket." The stock 9B with thinking off is. NuExtract3's verbs swallowed their objects ("carries the Golden Record"). It also needed a hand-rendered prompt, because LM Studio doesn't pass template arguments through on chat.

**A warning sign.** The 9B inferred "Joey dislikes Sony" from "the Sony was too heavy". That is a small act of memory poisoning, and it foreshadowed Chapter 12.

## 5. "I wish this could go faster"

> "I mean, the plan is to just sit in, you know, what comes in and what comes out… And I do want to process things that come in from the outside as well, too, because that stuff is stuff that's learned. Also things about things that happen."

That aside became Sophia's three input streams: **conversation**, **external** (what the agent reads), and **events** (what happens).

**Speed levers:**

- **A compact output format** made extraction 2.8× faster on the 9B and 3.7× on the 27B. Sentences go in numbered; facts come out one per line as `subject | verb | object | sN`, and each quote is looked up from its sentence number, so it is verbatim by construction.
- **Pinning the 9B to one GPU** under llama-server added 1.35×, and 4-way parallel reached 201 tok/s in aggregate.
- **Speculative decoding** lost every time:
  - LM Studio's MTP flag needs a model with an MTP head, and this one has none;
  - a 0.8B draft model cut throughput from 78 to 51 tok/s;
  - n-gram speculation did nothing.

Stacked, a five-chunk document went from about 45 s to about 11 s.

## 6. The trick

> "Are you doing a trick where you're basically turning any LLM into a decider by just looking at the log probabilities of the responses, like the top responses it could give?"

That was exactly it:
1. Lay the options out as single letters.
2. Run the prompt through prefill only.
3. Read each letter's probability from the first token's top logprobs.
4. Renormalize over those letters.

**Result.** The 9B already loaded for extraction got 4 of 4 room decisions right, with probabilities of 0.94–0.99. Each decision took 210–640 ms cold depending on prompt length, and 110–150 ms when the state was cached. That cost no extra VRAM, which mattered: with the 27B and the 9B both loaded, the 8.7 GB jobe sidecar would no longer have fit.

> "Yeah, then let's do that. I don't think there's any reason not to. That's clever."

**The decider.** `sophia_decider.py` became Sophia's decider:
- Choice, Noul and Score, in Jev's shapes;
- state first in the prompt, so the prefix cache serves a fan-out of questions;
- both option orders averaged, with a flag when the two readings disagree;
- a log of every decision, so a temperature can be fitted once real outcomes arrive.

## 7. Rooms and budgets

> "how many rooms did it go through in this amount of time?"

**One room.** With the full question set, a room cost 1.76 s; a lean set in one option order cost 0.49 s. Brute-force cosine search over 100,000 vectors took 2.87 ms. Hermes gives a memory provider's prefetch 8 s in total.

**The access pattern:**
- **Every turn:** vector search plus at most one decider call.
- **The recall tool:** walks rooms only when asked.
- **Mindscape:** runs at human pace.

The classifier had no business picking the first room, because vector search is about 100× cheaper. The multi-room walk was deferred until an evaluation shows it's needed.

**Checking the Hermes assumptions.** Hermes doesn't give memory providers `ctx.llm`, so Sophia talks to LM Studio directly. Design v0.1 followed at 22:26.

## 8. When in Rome

> "I mean, when in Rome, lets do as it wants to do, no need to being in other embedding models... I think.... except you'll want to test with that, to make sure our thresholds or whatever arent screwed"

**The test set.** Nomic's embedding model is already in LM Studio, so it became the only embedder. The thresholds were measured on:
- 76 triples from 13 texts, some written as deliberate near-misses;
- 24 answerable and 10 unanswerable questions.

**Findings:**
- **The old thresholds were meaningless.** SophiaAMS's cutoffs of 0.15, 0.2 and 0.3 were tuned for a different embedding model. Under nomic they let through every single pair.
- **The prefixes matter.** Nomic expects `search_query:` and `search_document:` prefixes. Recall@1 was 0.75 with them and 0.62 without.
- **Embed the source sentence too.** Embedding each triple together with its source sentence put every answer in the top 10.
- **Similarity can't decide "found".** "When did Voyager 2 launch?" scored 0.78 against the Voyager 1 launch fact.

**What Sophia uses:**
- **A skip threshold.** At a top score of 0.82 or above, Sophia skips the check. That covered 38% of answerable questions and none of the unanswerable ones.
- **The decider for everything else.** The decider's check got 32 of 34 right and never missed an answer that was there.

**Similarity ranks; the decider judges.**

## 9. Gemmery joins

> "Now question- how about "gemmery" does that have any place here?" … "Gemmery is mine in my GitHub"

**What Gemmery brought.** [Gemmery](https://github.com/jbpayton/gemmery) is the author's versioned agent memory with earned credit. It brought one hard result from LongMemEval: retrieval over the raw record scored **0.917**, and write-time summaries scored **0.367–0.500**. Its rule is *distill judgment, retrieve facts*.

**What changed:**
- **Triples are an index.** The raw record is the memory; triples help find it.
- **Newer facts supersede older ones** instead of piling up.
- **Credit comes from outcomes.** Misleading memories cost more than helpful ones earn.

**From siblings to one provider.** The first plan was sibling plugins, a "suite": Sophia for what is the case, Gemmery for what to do and why. Three traps pushed it back into one provider:
- a general plugin's `on_session_end` fires on every turn;
- general plugins get no compression signal;
- the system-prompt section is capped at 4,000 characters.

> "I, I think it is also fine to improve upon what is there in total."

So the design became one provider with two layers, facts and judgment. SophiaAMS's goal system was dropped in favour of what Hermes already has.

## 10. Awake and asleep

> "maybe there is a "dream sequence"? … perhaps heavier operation for all of this in "sleep time""

**Why a night.** Real credit is sparse. Most turns never produce a signal saying whether a memory helped. The answer was to split the day from the night.

- **Awake, nothing generates text.** Each turn is embedded into verbatim windows, which takes milliseconds. Before each reply there is one decider call, and Sophia injects dated evidence or nothing.
- **Asleep, the big model is idle anyway.** It uses the night to:
  - extract facts and supersede stale ones;
  - replay the day's real questions to judge what was injected;
  - rehearse, writing its own questions about new facts and repairing whatever recall misses;
  - calibrate the decider.

**Credit classes.** Credit is ranked: real, then replay, then rehearsal. Rehearsal may repair the index but never ranks anything. The watermark advances last, so an interrupted night simply runs again.

## 11. Blind spots, and where structure comes from

> "So, where are potential memory blind spots?"

**The list:**
- pages the agent reads but never restates;
- meaning that lives between messages (a bare "yes");
- relative dates and plans that went stale;
- counting questions;
- scale (every threshold came from 76 facts);
- memory echoing itself;
- over-eager supersession;
- rare but critical facts decaying away;
- an evaluation that only asks what already works;
- failing silently.

The author confirmed the stance:

> "this memory system is completely passive and associative, right?"

> "I've up to this point decided that I wanted to make it more emergent than prescriptive, but I'm also interested to see if there's a kind of boundary there."

**Design v0.5 drew that boundary: prescribe how to read values, not what the world contains.**

**Prescribed** — fixed in the design:
- **Typed spans:** time, money, quantities, contacts, artifacts.
- **Three clocks:** when something was said, when it happens, and when it was believed.
- **Modalities:** planned, habitual, negated, hypothetical…
- **A plan lifecycle:** a plan whose date passes becomes "unconfirmed".

**Emergent** — left to the data:
- entities, relations, topics and pages.

**The dial between them** is promotion and demotion: structure that recurs gets promoted, and structure that goes unused decays. Pins are the escape hatch.

**Two texts per window.** Each window keeps its verbatim text plus an enriched index text. By day the index text gets a cheap header; by night the model writes one. The evidence the agent sees is always the original words.

## 12. Building it, and what only real use found

> "So if possible, go ahead and try to implement this. I don't know how we can test it without actually testing the plugin inside of the system, but if you can, I'd like you to try."

> "Also, take care not to disturb any real instances of something that might be using the larger model. Unless the larger model is just what we're going to do during nighttime."

**The setup.** The author's default Hermes profile runs the 27B, with a gateway up. So all testing happened in a cloned profile, `sophiadev`, with the plugin symlinked in and Hermes's built-in memory switched off. Every night ran on the 9B. Once the author asked, nothing Sophia ran loaded, unloaded, or called the 27B.

**First contact** through Hermes's real memory manager:
- Capture took 0.11 s.
- Prefetch took 260–460 ms.
- "What's the capital of Australia?" was blocked at a decider score of 0.45, so nothing was injected.
- "Second week of May", said in September, resolved to May 8–15 2027.
- A fresh session recalled the camera, Sam and the dentist (gate 0.97).

**The bugs.** At 14:47 the first night ran inside Hermes, in 44 seconds. The unit tests had passed; the real system found the rest.

1. **A failed page was stored as knowledge.** The test asked Hermes to read Curry Village's Wikipedia page. The web backend (SearXNG, search only) couldn't fetch it, so Sophia captured Hermes's `<untrusted_tool_result>` wrapper around an error as if it were the page. With nothing to read, the agent answered anyway: "Curry Village was founded in **1927**…".
   - *Fix:* unwrap Hermes's envelope, detect errors, and store one chunk per URL. The night's sort step drops error pages and flags pages that try to instruct the agent. Injected web text is labelled as untrusted.
2. **Header laundering.** The night's context header for Joey's question absorbed the agent's made-up answer. Extraction then stored `Curry Village | was founded in | 1927`, attributed to Joey.
   - *Fix:* extraction now sees the verbatim text, with the header only as labelled context, and never takes facts from it. The agent's own lines are never mined for facts. This is Gemmery's rule, learned the hard way.
3. **A message superseding itself.** "I'm bringing the Sony A7 IV instead of the Fujifilm" yielded both "bringing Sony" and "not bringing Fujifilm", and each retired the other.
   - *Fix:* only strictly older facts from other messages can be superseded, and negation is handled explicitly.
   - The first fix was too broad and broke the night test, so it was narrowed.
4. **The 9B's bad habits.** It produced questions as facts ("Joey | wants to know | …"), entities stuffed into relations, and the line's own date used as when something happens.
   - *Fix:* validation rules and prompt wording.
   - Along the way, the importance flag learned to recognise "Dr." and "dentist".
5. **The agent's own voice crowding out the user's.** One injection held 10 items, 5 of them the assistant restating things, including the current session's own reply.
   - *Fix:* assistant lines are penalized and capped at two, and the live session is excluded. Superseded evidence carries a "later changed" label, and only items near the top score are injected.
6. **Duplicates on history import.** Hermes stores `tool_call_id: None` where live messages have no key at all, so the same message hashed two ways.
   - *Fix:* one normalized message identity. A second import now adds nothing.

**After the fixes**, a fresh session asked "Which camera am I taking on the Yosemite trip?" and got:

> You're bringing the **Sony A7 IV** to your Yosemite trip 📷 Originally you had planned to bring your Fujifilm X-T5, but the camera's sensor has been acting up, so you've switched to the Sony A7 IV instead.

The supersession was journalled as undoable, and `sophia undo 61` round-tripped it.

## 13. Into a repository

> "Go ahead and put this in a git repo, get it ready with some docs, tell the story- etc"

Which brings us here.

---

## What went wrong along the way

- **Mishearing Jev as JEPA,** and not searching Laya literally until asked.
- **A GPU experiment run without asking.** It became a standing rule: give a one-line heads-up first.
- **Laya's venv pulled a CUDA 13 torch** that the driver (550, CUDA 12.4) couldn't run. A partial fix then broke cupti; a full cu126 reinstall worked.
- **"Choice can't say none of these" was wrong.** TypeSafe's own docs recommend a none option, and the room design now has `back` and `stop_here`.
- **The first design assumed providers get `ctx.llm`.** They don't.
- **An early check concluded Hermes's venv lacked numpy.** It had read the wrong interpreter; numpy was there all along.
- **The decider plan changed three times.** It went from a 4B sidecar, to the 27B readout, to the 9B readout that was already loaded.
- **The sibling-plugin plan was reversed** into one provider.
- **A progress report overstated a result.** It said the agent used `sophia_browse` "without being prompted"; the test prompt had told it to. Unprompted tool use is still untested.

## What's next

- **Run a night on the 27B,** at an hour the author picks.
- **Collect decider labels.** It has 3 of the 50 it needs to fit a calibrated temperature.
- **Build an evaluation:** a LongMemEval harness, a hand-written question set, and a scale test. Several thresholds were tuned on 76 facts and must be re-measured on real windows at scale.
- **Finish the parts that are simplified or missing:**
  - Gemmery's judgment layer, which is milestone M4;
  - image captions;
  - a night pass that types values the fixed rules miss;
  - the full cold-answer headroom test;
  - Mindscape as views over what the night builds.

[docs/DESIGN.md §15](DESIGN.md#15-implementation-status-prototype-2026-09-23) keeps the exact list.

---

*How this was made:* the research, design and code came out of a two-day conversation between the author and Claude Code, from 21 to 23 September 2026. The author set the direction, and the assistant researched, measured and built. The quotes above are the author's own words from that conversation.
