# hermes-sophia — design draft v0.3

A Hermes Agent memory provider that rebuilds SophiaAMS's associative semantic memory as a
plugin: triples with provenance, multi-channel recall, room-and-door navigation (Mindscape),
and goals — with a logprob-readout decider doing the navigation instead of LLM turns.

Status: draft v0.3 for review, 2026-09-22 (v0.2: embedding decision and thresholds, §6.1;
v0.3: Gemmery's findings folded in — raw record as fact store, supersession, earned credit §6.2;
Gemmery as sibling plugin, see `SUITE.md`). Targets Hermes Agent v0.21.4 (installed at
`~/.hermes/hermes-agent`). Numbers marked **measured** come from today's runs on this box
(`results/`, `*.py` in this folder). Items marked **verify** are assumptions to check in M1.

---

## 1. Goals and non-goals

**Goals**
- Learn continuously from three input streams without slowing the chat:
  1. **Conversation** — what comes in and what goes out, every turn.
  2. **External** — web pages and documents the agent reads (learned knowledge, with URLs).
  3. **Events** — things that happen: tool runs, delegations, scheduled jobs, dated facts.
- Recall fast enough to run before every turn, and navigate deeper only when needed.
- Every stored fact carries a verbatim source sentence and where it came from.
- Rebuildable offline: the whole graph can be re-extracted or re-embedded from Hermes's
  session store and the ingest log.
- Local-first: no cloud dependency, no torch in the Hermes venv.

**Principles carried over from Gemmery's experiments** (github.com/jbpayton/gemmery, `FINDINGS.md`)
- **Distill judgment, retrieve facts.** On LongMemEval, retrieval over the raw record scored 0.917;
  summarizing at write time scored 0.37–0.50. So triples are an **index and navigation layer** over
  the raw record, not the store of facts: recall returns verbatim source text, and a fact that
  extraction missed is still findable in the raw record.
- **Revise, don't accumulate.** A new fact about the same subject and relation supersedes the old
  one; history is kept, "is true" and "was true" stay distinguishable.
- **Credit is earned from outcomes,** not from repeat sightings; misleading costs twice what helping earns.
- **Memory helps only where the model is ignorant** — prefer private, recent, niche material.
- **Numbers lead, abstain honestly, never last-write-wins** between sources.

**Non-goals (v1)**
- Its own agent loop, event bus, web UI server, Telegram, scheduler, code runner, skill loader.
  Hermes provides all of these.
- Autonomous goal pursuit as a daemon inside the provider (see §8 — composed from Hermes cron and `/goal`).
- Migrating SophiaAMS data (the running instance holds 7 triples).
- Judgment memory (rules, decisions, track records). That is Gemmery's job as a sibling plugin;
  the boundary is in `SUITE.md`.

---

## 2. Shape

One pip package, `hermes-sophia`, exposing one memory provider named **`sophia`**.

```toml
[project.entry-points."hermes_agent.memory_providers"]
sophia = "hermes_sophia:register"
```

Activated with `memory.provider: sophia`. Built-in MEMORY.md / USER.md stay active beside it.

```
hermes_sophia/
├── __init__.py          register(ctx): provider + aux task + skills
├── plugin.yaml          name, version, hooks
├── provider.py          SophiaProvider(MemoryProvider) — lifecycle, tools, hook wiring
├── store.py             SQLite schema, upserts, FTS5, vector blobs, durable job queue
├── embed.py             embeddings via the OpenAI-compatible endpoint (LM Studio), prefixes applied here
├── extract.py           compact-format extraction + parser + validators
├── ingest.py            worker pool: queue -> chunk -> extract -> gate -> embed -> upsert
├── recall.py            tier-0 hybrid lookup, prefetch formatting
├── rooms.py             room assembly + doors (Mindscape core, no LLM narrative)
├── walk.py              decider-driven navigation (greedy + beam)
├── decider.py           = sophia_decider.py from this folder
├── goals.py             goal table + suggest_next
├── config_schema.py     dashboard config panel fields
├── cli.py               hermes sophia <status|ingest|reembed|calibrate|...>
└── skills/
    ├── memory-navigation/SKILL.md
    └── goal-pursuit/SKILL.md
```

---

## 3. Runtime picture

```
  Hermes process(es): CLI, gateway, cron  ── each loads SophiaProvider
        │   prefetch / sync_turn / hooks / tools
        ▼
  SophiaProvider ──► store: $HERMES_HOME/plugin-data/sophia/sophia.db  (SQLite, WAL)
        │                    shared safely by all Hermes processes of the profile
        │
        ├─ extraction ─► PluginLlm(task="sophia_extraction") ─► LM Studio: Qwen3.5-9B, reasoning off
        ├─ decisions ──► direct HTTP /v1/responses + top_logprobs ─► LM Studio: same 9B
        └─ embeddings ─► LM Studio /v1/embeddings (nomic-embed-text-v1.5)

  LM Studio: Qwen3.8-27B = Hermes main model (chat); Qwen3.5-9B = Sophia's worker model

  Sibling: Gemmery (general plugin) — judgment dossiers, own git store, librarian on the same 9B
           at lowest priority; shares decider/client/source-ref format via suite core (SUITE.md)
```

One loaded 9B serves both extraction and decisions (**measured**: correct on all room
decisions, ~250 ms per decision). The 27B never sits in the memory loop.

Why the decider bypasses Hermes's LLM facade: `PluginLlm` returns text only, and a decision
needs the first token's logprobs. Extraction goes through the facade so the model is a normal
`auxiliary.sophia_extraction` config choice.

---

## 4. Data model (SQLite)

```sql
triples(
  id TEXT PRIMARY KEY,              -- md5(lower(subject)|lower(verb)|lower(object)); upsert merges
  subject TEXT, verb TEXT, object TEXT,
  topics TEXT,                      -- JSON list
  event_time TEXT,                  -- ISO date if the fact is dated ("in March 1979"), else NULL
  valid_from REAL, valid_to REAL,   -- belief validity; valid_to NULL = currently believed
  superseded_by TEXT,               -- triple id that replaced this one
  created_at REAL, updated_at REAL, status TEXT DEFAULT 'active'   -- active | superseded | retracted
)
credit_events(                      -- append-only; credit = fold, misleading debits 2x (Gemmery rule)
  triple_id TEXT, kind TEXT,        -- injected | used | unused | contradicted | reaffirmed | feedback
  delta REAL, session_id TEXT, turn_id TEXT, ts REAL)
injections(session_id TEXT, turn_id TEXT, triple_ids TEXT, chunk_refs TEXT, ts REAL)  -- what prefetch showed
chunks(                             -- raw record for EXTERNAL input; conversation raw stays in Hermes's store
  ref TEXT PRIMARY KEY,             -- url:<url>#<n>
  title TEXT, text TEXT, fetched_at REAL, general_knowledge INT)   -- headroom flag (§5 step 2)
chunk_vectors(ref TEXT, model TEXT, vec BLOB, PRIMARY KEY (ref, model))
triple_sources(                     -- provenance is a LIST (fixes SophiaAMS plan item B3)
  triple_id TEXT, stream TEXT,      -- conversation | external | event | explicit | memory_write
  source_ref TEXT,                  -- suite source-ref format (SUITE.md §4): hermes:<sid>:<mid> | url:<url>#<n>
                                    --   the raw record lives behind this ref
  sentence TEXT,                    -- verbatim sentence the fact came from
  speaker TEXT, observed_at REAL,
  PRIMARY KEY (triple_id, source_ref, sentence)
)
vectors(triple_id TEXT, model TEXT, dim INT, vec BLOB,   -- float32; keyed by model => re-embed is safe
        PRIMARY KEY (triple_id, model))
entities(name TEXT PRIMARY KEY, triple_count INT, vec BLOB, model TEXT)  -- entry points for rooms
triples_fts USING fts5(subject, verb, object, sentence, content='')
events(id TEXT PRIMARY KEY, kind TEXT, summary TEXT, occurred_at REAL,  -- tool run, delegation,
       source_ref TEXT)                                                 -- cron job, session end
jobs(id TEXT PRIMARY KEY, kind TEXT, payload TEXT, status TEXT,        -- durable ingest queue
     attempts INT, claimed_by TEXT, created_at REAL, updated_at REAL)
watermarks(key TEXT PRIMARY KEY, value TEXT)      -- e.g. last ingested message id per session
goals(id TEXT PRIMARY KEY, description TEXT, status TEXT, priority INT, goal_type TEXT,
      parent_id TEXT, depends_on TEXT, journal TEXT, created_at REAL, updated_at REAL)
rooms(address TEXT PRIMARY KEY, seed TEXT, graph_version INT, body TEXT)  -- assembled-room cache
decisions(id TEXT PRIMARY KEY, ts REAL, model TEXT, type TEXT, state_sha TEXT, instructions TEXT,
          options TEXT, probabilities TEXT, raw TEXT, flip INT, latency_ms REAL, gold TEXT)
```

- Content-hash ids make every write idempotent, which the fail-closed pre-compress
  checkpoint (§5) requires.
- Jobs are claimed with a single `UPDATE … SET status='running', claimed_by=? WHERE id=(SELECT
  … WHERE status='pending' LIMIT 1) RETURNING *`, so the CLI, gateway and cron processes never
  double-process a job.
- Goals get their own table (SophiaAMS stored them as triples with metadata); each goal also
  writes a mirror triple `Sophia | has goal | <description>` so ordinary recall still sees it.

---

## 5. Write path — three streams in, one pipeline

### Where input comes from

| Hermes hook / surface | Stream | What is enqueued |
|---|---|---|
| `sync_turn(user, assistant, messages=…)` | conversation (+ events) | the turn text; tool calls/results become `events` rows with a one-line summary, tool *output* is not extracted by default |
| `on_pre_compress(messages)` — checkpoint API v2 | conversation | the about-to-be-compressed span, keyed by digest; returns only after the job row is committed |
| `on_session_end(messages)` | events | session-end event + flush of any unqueued tail |
| `on_memory_write(action, target, content)` | explicit | the built-in memory write, as a high-confidence fact |
| `on_delegation(task, result)` | events | delegation event + the result text |
| tool `sophia_ingest(text, source_url)` | external | page/document text the agent fetched with Hermes's own web tools, chunked |
| tool `sophia_remember(fact)` | explicit | one fact, extracted on the spot |
| `hermes sophia ingest --since …` | all | offline sweep of Hermes's session store past the watermark |

Policy from `initialize(agent_context=…)`: `primary` writes everything; `cron` and `subagent`
write **events only** (a summary of what ran), not full extraction. Error-looking assistant
text is skipped (SophiaAMS's poisoning filter).

### Pipeline (background worker pool, `spawn_context_thread`)

1. **Chunk.** Paragraph chunker from SophiaAMS (~2,000 chars). Conversation: one turn per job.
   External chunks are **stored raw** in `chunks` and embedded first — they are the fact store;
   everything after this step builds the index.
2. **Filter (external only).** Decider Nouls per chunk: "Is this explanatory content about the
   topic, not references or navigation?" (drop) and "Is this general knowledge a well-read
   assistant would already know?" (keep the raw chunk, **skip extraction** — the headroom rule;
   saves 9B time on encyclopedia pages). Replaces SophiaAMS's LLM KEEP/DISCARD call.
3. **Extract — compact format.** Sentences numbered `[s1] …`; model returns one line per fact:
   `subject | verb | object | sN | topic-indexes`, plus a single `TOPICS:` line per chunk and
   one worked example in the prompt. **Measured** on the 9B: ~2.8x fewer output tokens than
   JSON with the same triple count; source sentences exact by construction because they are
   looked up from `sN`, never generated. Optional sixth column `when` for dated facts (**verify**
   it doesn't cost quality).
4. **Validate.** Drop lines with empty object, unresolvable `sN`, verb containing the object, or
   placeholder objects such as `[implicit]`, `unknown`, `unspecified` (the 9B emitted `[implicit]`
   once in the embedding test corpus).
5. **Stated-fact gate (conversation only).** Decider Noul: "Is this fact explicitly stated in
   sentence sN?" Catches inferences like "Joey dislikes Sony" (**measured** failure of the 9B).
6. **Supersession.** For each new triple, find active triples with the same subject entity and a
   similar relation (entity match + verb embedding). Decider Noul: "Does the new fact replace the
   old one?" If yes, close the old triple (`valid_to`, `superseded_by`, `status='superseded'`) and
   log `contradicted` on it. "Joey is bringing the Fujifilm X-T5" retires "Joey uses the Sony".
7. **Advice skip (conversation).** Rules of thumb ("always fix it where the state is produced") are
   tagged and not extracted — judgment belongs to Gemmery's librarian (SUITE.md §1).
8. **Embed** in one batch: each triple as `search_document: {subject} {verb} {object}. {sentence}`
   (triple plus its source sentence — **measured** best recall, §6.1), and new entities.
9. **Upsert** triples, append `triple_sources`, bump `graph_version` for touched seeds.

Workers default to 2 so one of the 9B's 4 slots stays free for decisions (§9).

---

## 6. Read path — tiered access

Speed comes from visiting fewer rooms, not from faster decisions. Each tier runs only when the
one before it is not decisive.

| Tier | What | Cost | Used by |
|---|---|---|---|
| 0 | Hybrid lookup over **two channels**: the triple index (FTS5 + vector over triples and entities, predicate boost, 1-hop expansion) and the **raw record** (Hermes session-store full-text search + external chunk vectors). Top-k by rank, not by similarity floor; active triples only unless the query asks about the past | **measured** query embedding 18 ms median; search 3 ms at 100k triples, 31 ms at 1M (384-d; roughly double at 768-d) | every prefetch |
| 1 | One gate: Noul "does this set answer the query?" over the top 10; if the top seeds are near-tied, one Choice over the top 5 | **measured** ~0.3 s (1 order), ~0.6 s (2 orders) | prefetch, unless top-1 similarity ≥ 0.82 |
| 2 | Walk: per room, Noul `found_here` + Choice over doors ∪ {back, give_up}; hop budget 4 | **measured** 0.49 s/room (1 order), 0.93 s (2 orders) | recall tool; background after a tier-1 "door leads on" |
| 3 | Agent browsing: room + doors + decider suggestion returned to the 27B, which chooses | one 27B turn per hop | `sophia_browse` |

### `prefetch(query)` — before every turn

- Hermes already skips trivial prompts and caps external prefetch at 8 s (it blocks the reply).
  Target p95 under 400 ms.
- Tier 0 always. Tier 1 runs on most turns: embedding similarity ranks well but cannot tell an
  answer from a near-miss (§6.1). Skip it only when top-1 similarity ≥ 0.82.
- When the gate says *not found*, inject nothing rather than the nearest neighbours; a wrong
  "memory" in context is worse than none.
- If the gate says *not here, but a door leads on*, start a tier-2 walk in the background and
  surface it next turn via `queue_prefetch` / the room cache. The current reply never waits on a walk.
- Output is **evidence, not summaries**: each hit is the verbatim source sentence (or turn window /
  chunk excerpt) with its fact line and ref as a header, numbers first —
  `[used 5, helped 4] Joey | is bringing | Fujifilm X-T5 — "I'm bringing the Fujifilm X-T5 this time…" (hermes:…)`.
  Plus active goals. Goals go here, not in `system_prompt_block()`, because they change.
- Every injection is recorded in `injections` for the credit loop (§6.2).
- `recall_status()` reports the count for Hermes's recall indicator.

### 6.1 Embedding thresholds (nomic-embed-text-v1.5) — **measured**, provisional

Test: 76 triples extracted by the 9B from 13 texts, 8 of them written as near-misses (another
person's camera, another doctor, another telescope, sibling voicebanks); 24 answerable and 10
unanswerable questions. Script `embed_thresholds.py`, results in `results/`.

| Finding | Value |
|---|---|
| Prefixes (`search_query:` / `search_document:`) | recall@1 0.75 with, 0.62 without — **required** |
| Document text = triple + source sentence | recall@10 **1.00**, worst gold rank 8 (triple alone: worst rank 29) |
| Irrelevant pairs | median 0.49, p90 0.59, p99 0.78 |
| Relevant pairs | p5 0.62, median 0.80 |
| Top-1, answerable vs unanswerable | median 0.81 vs 0.66, but unanswerable reaches 0.78 ("When did Voyager 2 launch?" → "Voyager 1 was launched on…") |
| SophiaAMS cutoffs 0.15 / 0.2 / 0.3 | keep **100%** of all pairs — meaningless under nomic |
| SophiaAMS 0.65 / 0.8 (hop seed / hop similarity) | keep 93% / 52% of relevant pairs |
| Skip-gate at top-1 ≥ 0.82 | covers 38% of answerable, 0% of unanswerable |
| Decider gate (Noul over top-10, 9B) | 32/34 correct with 2 orders, 31/34 with 1; **no** false "not found"; misses: "What lens did Joey use on Half Dome?" (0.91) and "What car does Emma drive?" (0.56) |

Resulting rules:
- Retrieve by rank (top 10–20), with a junk floor of 0.5, never by the old absolute cutoffs.
- Hop expansion seeds by rank (top 3), not by a 0.65 similarity floor.
- Gate threshold 0.6 with 2 orders; 0.5 with 1 order is the cheap setting.
- Mindscape's 0.15 / 0.2 / 0.5 room and door cutoffs are replaced by rank limits.
- Recalibrate every threshold with `hermes sophia eval` once real data exists; 34 questions is a
  smoke test, not a calibration set.

### 6.2 Credit loop (from Gemmery)

- **After each turn** (background, from `sync_turn`): for every injected triple, decider Noul
  "Did the assistant's response rely on this fact?" → `used` / `unused`. One call per injected
  fact, batched on the shared 9B at low priority.
- **Contradiction:** supersession (§5 step 6), a user correction in the next turn, or feedback on
  `sophia_remember` → `contradicted`, debited 2x.
- **Ranking:** tier-0 results are ordered by similarity, then credit; facts injected often and
  never used sink.
- **Calibration labels for free:** a "found here" gate decision followed by `used` is a positive;
  followed by `unused` on every injected fact is a negative. This is the gold data `fit_temperature`
  needs, with no manual labelling.

### Rooms

`rooms.py` ports `MindscapeNavigator.assemble_room` with two changes:
- **No LLM narrative** in the recall path; narratives are generated lazily for the UI only.
- **Doors from SQL adjacency** (entities sharing triples with the room) instead of one vector
  search per entity.

Rooms are cached by content address and `graph_version`. Room budget stays at SophiaAMS's 768
display tokens; prompt cost for decisions is ~0.3 ms per input token (**measured**).

### Walk

Greedy with explicit back for `sophia_recall` (breadcrumb is the stack, visited set prevents
loops). Width-3 beam with geometric-mean path score for background walks. Low-confidence door
choice (below a fitted threshold) climbs to the parent directory node instead of guessing
(TypeSafe's confidence-fallback pattern). Order averaging is adaptive: one read, a second
reversed read only when the margin is under 0.5.

---

## 7. Tools (kept small — Hermes exposes these only with the `memory` toolset)

| Tool | Purpose |
|---|---|
| `sophia_recall(query, max_hops=4)` | tiered recall with walk; returns facts, sources, and the path taken |
| `sophia_browse(seed \| address, door?)` | Mindscape: one room, its doors, and the decider's suggestion |
| `sophia_remember(fact, source?)` | explicit store |
| `sophia_ingest(text, source_url, title?)` | learn from fetched external content |
| `sophia_goal(action, …)` | create / update / list / journal / suggest_next |

Feedback on a stored fact (`helpful` / `wrong`) is an action on `sophia_remember` rather than a
sixth tool.

---

## 8. Goals

- Port `create_goal`, `update_goal`, dependency and parent/child unblocking, and
  `suggest_next_goal` from `AssociativeSemanticMemory.py` onto the `goals` table.
- `suggest_next` stays deterministic (priority, dependencies, age); the decider only breaks ties.
- Autonomy is composed from Hermes, not reimplemented: a Hermes cron job fires hourly with
  "check your active goals", the agent calls `sophia_goal suggest_next`, then pursues it with
  `/goal` (judge-driven loop, quality gates). Journal entries are written back through the tool.
- Shipped as skill `sophia:goal-pursuit`. Phase 3.

---

## 9. Models and VRAM

| Role | Model | Where | Notes |
|---|---|---|---|
| Chat | Qwen3.8-27B Q6_K | LM Studio | unchanged; could drop to 16–32k ctx to free KV cache |
| Extraction | Qwen3.5-9B Q4_K_M, reasoning off | LM Studio | `reasoning_effort: "none"` honored on chat completions (**measured**); via aux-task `extra_body` (**verify**) |
| Decider | same 9B | LM Studio `/v1/responses`, `reasoning.effort: none`, `top_logprobs` | 210–640 ms cold, ~110–150 ms cached (**measured**) |
| Embeddings | nomic-embed-text-v1.5 (on disk, 84 MB, 768-d) | LM Studio `/v1/embeddings` | the only embedding model; prefixes required; 18 ms per query (**measured**). Hermes itself has no embedding model, so this follows LM Studio rather than bringing another in |

Contention: extraction workers capped at 2 of the 9B's 4 slots; decisions use a separate
client queue with priority. Throughput upgrade path if needed: pin the 9B to one GPU under
LM Studio's bundled llama-server (**measured** 1.35x single-stream, 201 vs 124 tok/s at 4-way).
Speculative decoding is off: it was slower in every configuration tried.

---

## 10. Dependencies

Required: `numpy`. That's it — SQLite, HTTP, and JSON are stdlib.
Optional extras: `scikit-learn` (directory clustering;
SophiaAMS used `hdbscan` with a DBSCAN fallback), `sqlite-vec` (beyond ~1M triples).
Dropped from SophiaAMS: torch, sentence-transformers, qdrant-client, networkx, matplotlib,
tinydb, spaCy, fastapi/uvicorn, trafilatura, bs4, tiktoken, telegram.

---

## 11. Offline CLI (`cli.py`, shown only when `memory.provider: sophia`)

```
hermes sophia status                       store size, queue depth, models, last ingest
hermes sophia ingest [--since DATE] [--session ID] [--dry-run]
hermes sophia reembed --model M            new vectors keyed by model; switch when complete
hermes sophia reextract [--since DATE]     rerun extraction from sources with a new prompt/model
hermes sophia rebuild-directory            clustering for Mindscape (optional extra)
hermes sophia calibrate [--teacher MODEL]  label a sample of logged decisions with the 27B, fit temperatures
hermes sophia eval QUERIES.jsonl           hops, success, latency on a labelled query set
```

Calibration labels come from the 27B acting as teacher on a sample of logged decisions (it
agreed with the 9B on every test decision today), plus explicit feedback. This follows
reflex's finding that frozen weights + fitted temperature beat fine-tuning for general use.

---

## 12. Config (`memory.sophia` in `config.yaml`, mirrored in `config_schema.py`)

```yaml
memory:
  provider: sophia
  sophia:
    embed: {backend: openai, base_url: http://127.0.0.1:1234/v1, model: text-embedding-nomic-embed-text-v1.5}
    decider: {base_url: http://127.0.0.1:1234, model: qwen35-9b, permutations: adaptive}
    ingest: {workers: 2, tool_output: summary, cron: events_only, subagent: events_only}
    recall: {prefetch_limit: 15, gate: auto, max_hops: 4, beam_width: 3}
auxiliary:
  sophia_extraction:
    base_url: http://127.0.0.1:1234/v1
    model: qwen35-9b
    extra_body: {reasoning_effort: none}
```

---

## 13. Milestones

**M1 — store, ingest, tier-0 recall (no decider).** Provider skeleton, schema (including
validity and credit tables), embeddings, compact extraction through the aux task, durable queue,
`sync_turn` + pre-compress checkpoint, raw-record channel, offline `ingest`. Done when: a week of
your real Hermes sessions ingests cleanly, 100% of stored sentences are verbatim, prefetch
p95 < 100 ms.

**M2 — decider, navigation, credit.** Tier-1 gate in prefetch, supersession, credit loop, rooms,
`sophia_recall` walk, `sophia_browse`, decision logging, `calibrate`, `eval`. Done when: a
50-query set built from your own history shows answer-found rate and hops/latency, versus tier 0
alone, and versus raw-record retrieval alone (the Gemmery baseline to beat).

**M3 — goals and external learning.** Goals table and tool, `sophia_ingest` with the chunk
filter, goal-pursuit skill, cron recipe.

**M4 — Mindscape UI.** Dashboard plugin (FastAPI router + UI bundle) for directory, rooms,
graph. Packaging for a memory-provider entry point is unverified (see §14).

**M5 — suite.** Gemmery Hermes adapter and the shared pieces, per `SUITE.md` §8.

---

## 14. Open questions and risks

1. **LLM facade from a provider (verify).** The memory-provider registration context forwards
   `register_*` calls but not `ctx.llm`. Plan: construct `agent.plugin_llm.PluginLlm(plugin_id="sophia")`
   directly; the aux task registered through the same context should be owned by `sophia`.
   Fallback: call LM Studio directly for extraction too.
2. **Reasoning off through the aux task (verify)** that `extra_body.reasoning_effort` reaches
   LM Studio unmodified; Hermes rewrites some `extra_body.reasoning` shapes.
3. **Session store access (verify)** for offline ingest: `hermes_state.SessionDB(read_only=True)`
   resolving to the active profile.
4. **Dashboard from a pip memory provider (verify)** — dashboard plugins use their own manifest;
   may need a second, general plugin in the same package.
5. **Embedding model — decided: nomic via LM Studio only.** Thresholds re-derived in §6.1.
   Open: a hard near-miss ("lens" vs "camera") still passes the gate; test a stricter wording
   ("states the exact answer") before M2.
6. **Events granularity.** Tool runs as one-line event summaries by default; full tool-output
   extraction is opt-in because file contents and command output poison the graph.
7. **Single worker model.** A long external ingest can crowd decisions; the 2-worker cap and
   priority queue are the mitigation, a dedicated decider model is the upgrade.
8. **Hook name trap.** The provider's `on_session_end(messages)` fires at real session boundaries;
   a *general plugin's* `on_session_end` hook fires at every turn's finalization. Anything
   session-scoped in the suite uses the provider method, `on_session_finalize`, or `on_session_reset`.
9. **Credit-loop cost.** One Noul per injected fact per turn; at ~15 injected facts that is ~15
   low-priority 9B calls per turn. If that crowds the 9B, judge only the top 5 or sample turns.
