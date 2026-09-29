# How Sophia compares

This is a reality check, written in September 2026, against the best-known graph and agent memories. In short: Sophia's *representation* has converged with the state of the art. What distinguishes it is *behaviour*:
- when the model work happens;
- that it decides whether to inject anything at all;
- a night that tests and repairs its own recall.

Benchmark results, measured with a local 9B reader, are in [Benchmarks](#benchmarks).

## Hermes's memory, side by side

Hermes gives an agent memory out of the box, and ships eight memory plugins. Several are serious systems. This compares them with Sophia *as Hermes runs them*: we read each plugin's code in Hermes v0.21.4, and each project's own documentation, in September 2026. A plugin can do less than its service does, when the plugin doesn't use a feature; where that happens, the table says so.

● yes · ◐ partly · ○ no

| | Where it runs | Model work when saving | Added before each reply | Can add nothing | Keeps the words | Change over time | Agent's tool calls | Look and correct |
|---|---|---|---|---|---|---|---|---|
| **Sophia** | Your machine: SQLite in the Hermes process, plus your model server | None; facts, context and task cards are made at night | Matching lines word for word, with dates, and the facts that point at them | ● A model reads the message and decides | ● Every line; each fact links to its lines | ● When said, when it happens, when believed; replacements journaled and undoable; plans past their date marked | ● Every call, and a card per task | ● The Sophia tab: graph, pages, each recall's reasoning, undo |
| **Hermes built-in** | Hermes | The agent writes notes when it chooses, and is reminded every 10 turns | Both notes, always (up to 3,575 characters) | ○ Always there | ◐ Every past message, by keyword search when the agent asks (`session_search`) | ○ | ◐ Skills: procedures the agent writes, with an audit trail | ◐ `hermes journey`, or the files |
| **Holographic** | Local SQLite, no models | None: the agent adds facts | Top 5 keyword matches | ◐ When no keyword matches | ○ The agent's own wording | ○ Updates overwrite | ○ | ○ The agent's tools only |
| **Mem0** | Cloud, a server, or in-process with Ollama | An LLM extracts facts each turn (messages cut to 450 characters) | Top 10 facts, without dates | ◐ Weak score floor (0.1) | ◐ History keeps the cut input | ◐ Old and new kept; ranking decides | ○ | ● Dashboard: edit, delete, history |
| **Honcho** | Cloud, or self-hosted (Postgres, Redis, a worker) | An LLM derives conclusions about you; messages kept verbatim | Session summary, models of you and the agent, a reasoned answer; one turn behind | ○ | ● Messages, searchable by the agent | ◐ "Dreaming" rewrites outdated conclusions | ○ | ● Dashboard |
| **Supermemory** | Cloud, or a local binary | LLM extraction | Up to 10 memories, with age and similarity | ◐ Server threshold (0.5) | ◐ Kept on the server; the plugin shows only memories | ● Versions, event dates, expiry | ○ Left out on purpose | ● Console |
| **Hindsight** | Cloud, or local (a daemon with Postgres) | LLM extraction, entity resolution, consolidation | Consolidated observations, up to 4,096 tokens; one turn behind | ○ Fills its budget | ◐ Kept on the server; not injected | ● Event time and mention time; invalidate and revert | ◐ An "experience" network, inferred from replies | ● A control plane with a graph view and audit trail |
| **OpenViking** | Self-hosted server, or hosted | An LLM extracts when a session is committed | Your profile, then the top hits (up to 4,000 characters) | ◐ Score floor (0.15) | ◐ Session archives | ◐ A diff per commit; merges overwrite | ● Calls and results | ● Studio; memories are Markdown files |
| **ByteRover** | Local files, plus an LLM (hosted or yours) | An LLM curates each turn into a Markdown tree | An answer from the tree | ○ Only an output-length check | ○ Curated text only | ◐ Git-like history, decay, "dreaming" | ○ | ● Markdown on disk, web UI, review of changes |
| **RetainDB** | Cloud, or self-hosted (Postgres) | LLM extraction on the server | Profile, 5 results and a synthesised answer; one turn behind | ◐ On the server | Unknown | ◐ Versions upstream; not exposed by the plugin | ○ | ● Dashboard |

"One turn behind" means the plugin fetches recall after a turn, for the next one. It adds no wait before a reply, but it answers the previous message.

### What each does well

- **Hermes built-in:**
  - No setup at all.
  - Its notes are always in view.
  - Every past message, tool output included, can be searched by keyword.
  - Skills turn what worked into procedures, with a ledger and rollback.
- **Holographic:** private, free and model-free, fast and deterministic. Trust scores the agent can train. Small enough to audit.
- **Mem0:**
  - The simplest to run.
  - Hybrid retrieval: meaning, keywords and entities.
  - Explicit edit and delete, and a fully local mode.
  - A large ecosystem.
- **Honcho:**
  - Models you, and the agent, with an LLM that reasons over both conclusions and raw messages.
  - Verbatim search across sessions.
  - The best multi-user and multi-agent identity handling of the group.
- **Supermemory:**
  - Versioned facts with event dates and automatic expiry.
  - Documents and memories in one search, and connectors.
  - A local binary.
- **Hindsight:**
  - The richest model of time: when something happened, separate from when it was said.
  - Retrieval by meaning, keywords, graph and time, reranked.
  - Consolidated beliefs that keep their evidence, and reversible curation.
  - It can run fully local.
- **OpenViking:**
  - Records tool calls and their outcomes.
  - Three levels of detail to browse.
  - Ingests documents and repositories.
  - A relevance floor, and a diff for every commit.
- **ByteRover:**
  - Human-readable Markdown you can version and review.
  - Lossless archiving.
  - Fast paths that need no LLM.
- **RetainDB:**
  - Captures every turn with no wait before replies, through a queue that survives crashes.
  - Profiles, an agent self-model, file ingestion and team scopes.

### Where Sophia differs

- **The words, not a rewrite.** What reaches the agent is what was said, dated, with extracted facts pointing at it. Every other plugin injects text an LLM wrote. Honcho and Hermes's own `session_search` can find verbatim messages, but only when the agent goes looking.
- **A model decides whether memory is needed.** Before anything is injected, a small model reads the message and the best candidates. It answers one of three things:
  - nothing about you is needed;
  - it's about you, but none of these fits;
  - this one bears on it most directly.

  Three plugins use a similarity floor instead, and three have no gate. Sophia measured why a floor isn't enough: similarity can't separate an answer from a near-miss. Unanswerable near-misses scored up to 0.78, against 0.80 for real answers.
- **Nothing is generated when saving.** The night does the model work in batch, on your GPU, and then tests its own recall:
  - it replays the day's injections to see which helped;
  - it asks itself questions about new facts, and repairs what it misses.

  ByteRover and Honcho "dream", and Hindsight consolidates. None of them, as far as we found, grades its own recall.
- **A graph that assembles itself over the words.**
  - At night, facts are extracted, and entities are resolved by name with their aliases kept.
  - Nobody declares a schema. A relation becomes canonical once it recurs: 5 times, across 2 sessions.
  - Sophia learns from its own history which relations hold one value at a time, so a new home replaces the old one while a new friend doesn't replace an old one.
  - Lines that answer or correct each other are linked, and recall walks one hop through all of it.

  Hindsight also builds an entity graph, and Supermemory links facts that update one another. Both do it with an LLM at write time.
- **Semantic by design.** Every line, fact and task card is embedded and held in vector indexes. Recall fuses them with keyword search (FTS5), date ranges and the graph. At night, short lines are re-embedded with what they refer to, so a bare "yes" can be found by what it agreed to. Most plugins also search by meaning; Holographic and the built-in search are keyword-only.
- **What the agent did.** Every tool call is logged, and each task gets a card from the log: the steps that worked, the dead ends, and how it turned out. OpenViking is the only other plugin that records tool calls.
- **One file, no server.** Everything lives in one SQLite file inside the Hermes process, beside your model server. Holographic works the same way, and Mem0 can run in-process with a local vector store. Self-hosting Hindsight, Honcho, OpenViking or RetainDB means running a server with Postgres.
- **Why each reply got what it got.** The Sophia tab shows, for every message:
  - the gate's reading;
  - the lines that went in;
  - the candidates it weighed.

  Honcho can log what it injected, if asked. The other plugins' dashboards show what is stored, not why a reply got it.

### Where others are ahead

- **Modelling the user.** Honcho reasons about who you are; Sophia keeps evidence and facts, not a theory of you.
- **More than one user, and teams.** Honcho, Supermemory, RetainDB and ByteRover share memory across users, agents or tools. Sophia serves one user on one machine.
- **Nothing to run.** Every other plugin has a hosted option. Sophia needs a model server, and a GPU for good results.
- **Documents and repositories.** OpenViking, Supermemory and RetainDB ingest them as first-class memory. Sophia learns pages the agent reads, and documents it's given.
- **Maturity.** Sophia is a v0.1 prototype.
- **New facts wait for the night.** Sophia's verbatim lines are recallable at once, but facts and pages appear only after a night.

## Time and cost per message

The waits are each plugin's own budgets and timeouts, not measurements. Prices are from the vendors' pages in September 2026.

| | Before each reply | Model work per turn | What it costs |
|---|---|---|---|
| **Sophia** | A local check, about 0.6 s (0.04 s with `gate: similarity`) | None; the night batches it | Your own GPU time |
| **Hermes built-in** | None | None | Nothing |
| **Holographic** | A local keyword search | None | Nothing |
| **Mem0** | Waits up to 3 s | LLM extraction | Free up to 1,000 retrievals and 10,000 adds a month; Pro $249/month |
| **Honcho** | In the background (one turn behind); the first turn waits up to 5 s | LLM reasoning, plus a chat call | $2 per million tokens ingested; $0.001–0.50 per chat call |
| **Supermemory** | Waits up to 5 s | LLM extraction | $5 per million tokens, plus $5 per million queries |
| **Hindsight** | In the background (one turn behind) | LLM extraction | Cloud: $10 per million tokens retained, $0.75 per million recalled |
| **OpenViking** | Waits up to 4 s | LLM, when a session is committed | Self-hosted, or Volcengine's hosted plans |
| **ByteRover** | Waits up to 8 s: its fast paths take under 0.1 s, its LLM paths 5–15 s | LLM curation | Free, or Pro at $15/month; plus your LLM |
| **RetainDB** | In the background (one turn behind) | LLM extraction | Free up to 10,000 operations a month; paid plans from $20/month |

## Published benchmark numbers

Every number is published by its own project, run with its own harness on its own service, not through its Hermes plugin.

| System | LongMemEval | LoCoMo | Answering model (judge) | Source |
|---|---|---|---|---|
| **Sophia** | 80.2 (S, all 500); 86.7 (60 held out, 27B) | 86.9 with its tools, 80.6 injection only (27B) | Qwen3.5-9B or Qwen3.8-27B, local (9B judge) | [BENCHMARKS.md](BENCHMARKS.md), held-out data |
| **Mem0** | 94.4 | 92.5 | Not disclosed | [Mem0](https://mem0.ai/blog/mem0-the-token-efficient-memory-algorithm), April 2026 |
| **ByteRover** | 92.8 (S) | 96.1 | Gemini 3 Flash (also judging) | [paper](https://arxiv.org/html/2604.01599) |
| **Hindsight** | 83.6 / 89.0 / 91.4 (S) | 83.2 / 85.7 / 89.6 | gpt-oss-20b / gpt-oss-120b / Gemini-3 (gpt-oss-120b judge) | [paper](https://arxiv.org/pdf/2512.12818) |
| **Honcho** | 90.4 (S), 88.8 (M) | 89.9 | claude-haiku-4-5; gemini-2.5-flash-lite ingests | [Plastic Labs](https://plasticlabs.ai/blog/research/Benchmarking-Honcho), December 2025 |
| **Supermemory** | 81.6 / 84.6 / 85.2 (S) | | GPT-4o / GPT-5 / Gemini-3-Pro (GPT-4o judge) | Supermemory research page |
| **OpenViking** | | 82.9 (with Hermes) | Doubao models | [README](https://github.com/volcengine/OpenViking) |
| **RetainDB** | 79 (the easier oracle split) | | gpt-5.4 (gpt-5.4-mini judge) | [RetainDB](https://www.retaindb.com/benchmark), March 2026 |
| **Full context, GPT-4o** | 60.6 (S) | | GPT-4o | LongMemEval paper |

How to read it:
- **The answering models differ by an order of magnitude or more.** Sophia's reader runs on a desktop GPU. The closest like-for-like point is Hindsight with gpt-oss-20b, 83.6 on LongMemEval-S, against Sophia's 80.2 (9B) and 86.7 (27B, held-out 60).
- **The sets differ.** RetainDB's oracle split contains only the sessions with the evidence. Sophia reports on held-out questions it wasn't tuned on.
- **The judges differ,** and some are generous. Sophia's 9B judge is 2.5–4.5 points generous on LoCoMo.
- **Plugins can lose points the service would score.** Mem0's plugin cuts each message to 450 characters, Honcho's asks a generic question by default, and Supermemory's drops verbatim chunks. So a Hermes user may see less than the published score.
- **None of these benchmarks asks the things an always-on agent memory must get right.** It must stay out of the way when nothing is needed, and say "you never told me". It must not take a brother-in-law for a brother, or obey a web page. That's why [Almanac](https://github.com/jbpayton/almanac) exists; see [BENCHMARKS.md](BENCHMARKS.md#in-short).

## Where Sophia matches the field

| Sophia | Already done by |
|---|---|
| Three clocks (said / happens / believed). Superseded facts are invalidated, not deleted | [Graphiti / Zep](https://www.getzep.com/platform/graphiti/) is bi-temporal, with edge invalidation. [SodaMem](https://arxiv.org/pdf/2608.08055) tracks mention time, occurrence time and validity, with SUPERSEDES / CONTRADICTS / UPDATES edges |
| Verbatim record kept; every fact tied to its source | Graphiti keeps each episode verbatim as provenance. SodaMem uses "typed FactEvents with mandatory provenance spans" and returns citable evidence |
| Triples as an index over the passages they came from | [HippoRAG 2](https://arxiv.org/abs/2502.14802): passage nodes plus phrase nodes, with Personalized PageRank |
| Vector + keyword + time-bounded search, plus graph traversal | [Hindsight](https://arxiv.org/pdf/2512.12818) runs four strategies in parallel and fuses them |
| Heavy work off the chat's critical path | [Letta's sleep-time agents](https://www.letta.com/blog/sleep-time-compute/) |
| Entity pages | Hindsight's synthesized entity summaries |

SodaMem is the closest relative: its data model is nearly Sophia's. It reports 92.8% on LongMemEval-S, and Hindsight reports 91.4% on LongMemEval.

## Where Sophia plausibly differs

1. **No generated text when something is saved.** Graphiti, Mem0 and Hindsight run LLM extraction as each message is saved. Sophia stores the words and their embeddings immediately and extracts at night on a local model. The only other model call at capture is a one-token check of each live agent reply (point 3). Letta shares the night idea, but for memory blocks rather than a fact graph.
2. **A check that can inject nothing.** The providers we checked rank memories and inject the top few. For example, Hermes's bundled Holographic provider injects the 5 facts that best match the message, above a trust floor, on every turn. Sophia measured that similarity can't separate an answer from a near-miss (unanswerable near-misses reached 0.78 against 0.80 for real answers). So before anything is injected, a small model reads one token's probabilities over a few options: nothing about you is needed, it's about you but none of these memories fits, or which memory bears on it most directly. Memory stays out when "nothing needed" is clear, and the block is marked as possible matches only when "none fits" outweighs the memories. Rerankers and Self-RAG's "should I retrieve?" step are relatives.
3. **Its own words can't poison it.** The agent's replies are checked as they are captured. A reply that states facts about you that nothing in the turn supported is kept out of recall. This came from a real failure: in testing, an agent invented where someone's sister lived, and the next session recalled that as memory.
4. **A memory that tests itself.** Each night Sophia:
   - replays the day's injections to judge which ones were used;
   - writes its own questions about new facts, and repairs whatever recall misses;
   - uses those labels to calibrate the check (so far only its yes/no form; the default choice form isn't calibrated yet).
   Hindsight's reflect step and Letta's consolidation reorganize memory, but we didn't find either grading its own recall.
5. **Emergent schema with learned exclusivity.** Graphiti's custom types are declared up front. Sophia promotes relations that recur, and learns from its own history whether a relation holds one value at a time (and so supersedes older values) or several.
6. **Task memory from the action log.** Hindsight also keeps agent experiences as one of its memory networks. Sophia builds a task card from the tool-call log itself: outcome, working steps, dead ends with reasons, and the pages that informed them. The night model only points at logged actions, so a card can't contain a step that wasn't run. Hermes's own skills stay the general rulebook, and the cards are the evidence behind it.
7. **Footprint.** SQLite, numpy and a local model server. No graph database, no cloud. The night waits for your chat model to be idle.

## What "graph" means here

Sophia stores a temporal memory graph:
- **nodes:** entities, facts and verbatim windows;
- **fact edges:** subject → object, carrying modality and time;
- **provenance edges:** fact → the window it came from;
- **conversation edges:** a reply → what it answers or corrects.

Recall walks it, conservatively:

- **Bridge entities only.** Recall expands entities that appear in the top results but not in the question; similarity already covers the entities the question names. "Where does Sam's sister live?" matches `Sam | has a sister named | Lily`, and the hop through Lily reaches `Lily | moved to | Denver`. That fact scored only 0.57 on its own, below the injection cutoff.
- **Hub damping.** An entity with many facts spreads less, and you and the agent are never expanded, because everything connects to you.
- **Conversation links.** A matched message also brings what corrects it, or what it answered.

This is **one hop by default** (`graph_hops`), which is lighter than HippoRAG's Personalized PageRank or Graphiti's breadth-first traversal. Deeper chains need `graph_hops: 2` and haven't been evaluated.

## Benchmarks

The full protocol, results and caveats are in [BENCHMARKS.md](BENCHMARKS.md). Everything was tuned on development data and reported on held-out data, with a local 9B as reader and judge:

| Benchmark | Sophia | Same reader's reference |
|---|---|---|
| LongMemEval-S, 60 held-out questions | 0.750 (0.633 before tuning) | 0.917 with the evidence sessions handed over |
| LoCoMo, 7 held-out conversations (J) | 0.748 after a 27B night; 0.730 after a 9B night; 0.671 by day | 0.768 with the whole conversation in context |

These numbers are not directly comparable with published results that use GPT-4o-class readers and judges. For orientation: on LongMemEval-S, Zep scored 71.2 with GPT-4o and Hindsight 83.6 with gpt-oss-20b. On LoCoMo, Mem0 scored 66.9, Zep 75.1 and Hindsight 83.2.
