# hermes-sophia — design draft v0.5

**A passive, associative memory for Hermes Agent that organizes itself while you sleep.**
One memory provider, two layers (facts and judgment), two modes (awake and asleep). SophiaAMS's
associative memory and Gemmery's earned judgment, rebuilt as one plugin.

Status: draft v0.5, 2026-09-23. Targets Hermes Agent v0.21.4 (`~/.hermes/hermes-agent`).
**measured** = from runs on the development box, 2× RTX 3090 (scripts and results in [`research/`](../research/)). **verify** = assumption to
check in M1. **estimate** = not yet measured. Earlier versions are in [`archive/`](archive/). How the design got here: [STORY.md](STORY.md).
Implementation: this repository (prototype of M1–M3; §15 lists what is built, simplified, or missing).

Changes from v0.4: the blind-spot fixes; a representation built for the gaps extraction used to
paper over — contextual index text, typed spans, a three-clock time model, threads; the
self-organizing wiki as derived views; an explicit boundary between prescribed and emergent
structure, with promotion as the dial between them; evaluation that can see its own gaps.

---

## 0. What kind of memory this is

**Passive and associative.** Sophia never speaks, asks, or acts. Three things happen without
the agent asking: every turn is captured, associated memory is injected before each turn, and
the store reorganizes itself during sleep. Everything deliberate — deep recall, structured
queries, browsing the wiki, storing a note — is the agent's choice, through tools.

Two edges, both kept passive by default: sleep's *anticipate* step only warms caches, it never
surfaces anything unasked; the morning dream-journal line is off unless you turn it on.

---

## 1. Principles

1. **The raw record is the truth; everything else is an index.** Retrieval over raw text beat
   write-time summaries 0.917 vs 0.37–0.50 on LongMemEval (Gemmery's `FINDINGS.md`).
2. **Evidence stays verbatim; index text may be enriched.** What the chat model sees is always
   the original words. What the search engine sees can carry resolved references, time, and topic.
3. **Prescribe how to read values, not what the world contains.** A small fixed set of value
   types and time semantics is designed in; entities, relations, topics, and pages emerge (§4).
4. **Structure is earned** the way dossiers earn credit: an emergent pattern becomes schema when it
   recurs, gets used, and stays stable; unused structure decays back into plain clusters.
5. **Distill judgment, retrieve facts** (Gemmery). **Revise, don't accumulate.**
6. **Similarity ranks, the decider judges** (**measured**, §11).
7. **Credit orders what is shown; it never decides whether something may be shown.**
8. **Awake is cheap, asleep is thorough.** Nothing that generates text runs on the chat's critical path.
9. **Degrade loudly, never silently.**

---

## 2. Representation

Six layers over the raw record, each derived from the one before and rebuildable from it
(except credit and dossiers, which record history that cannot be re-derived).

| Layer | What | Built | Answers |
|---|---|---|---|
| **Windows** | 2–3 sentence spans of every turn, page, caption; verbatim `text` + enriched `index_text` | awake (heuristic header), rewritten asleep (model header) | "what was said about X" |
| **Typed spans** | values inside windows with a known type and a normalized value | awake (deterministic), completed asleep (model) | exact filters, counts, sums, date ranges |
| **Threads** | episodes within sessions; links: question→answer, assent→decision, correction→what it corrects | asleep | meaning that lives between messages |
| **Facts** | relations between entities or values, with modality and validity, linked to source windows | asleep | current state, history, relations |
| **Entities** | people, organizations, places, projects, with aliases | asleep | who and where |
| **Views** | wiki pages and indexes: entity pages, timeline, people, places, topics, sources, trust, changes | asleep | browsing, navigation |

### 2.1 Between messages: contextual index text, not extraction

Extraction used to paper over context loss by rewriting text into triples. Instead:
- **Awake, heuristic header (no model):** a window whose message is short, an assent, or starts
  with a pronoun gets the preceding question sentence, the session title, and the most recent
  named entities prepended to its `index_text`. "yes" becomes
  `[Joey · 2026-09-21 · answering: should I book Curry Village?] yes`.
- **Asleep, model header:** the 27B writes a one-line context per window, per session in one call
  — resolved references, speaker, topic, time — the technique behind Anthropic's
  [contextual retrieval](https://www.anthropic.com/engineering/contextual-retrieval), which cut
  top-20 retrieval failures 35% alone and 49% with keyword search. Windows are re-embedded;
  `text` never changes.
- **Threads** record the links explicitly, so an assent can be found as the decision it is.

### 2.2 Structure inside the unstructured: typed spans

A **fixed vocabulary of value types** (prescribed; modelled on NuExtract's type system):

| Type | Normalized as | Awake (deterministic) | Asleep (model) |
|---|---|---|---|
| `time` | ISO instant or interval, or recurrence rule | ISO dates, "today/tomorrow/yesterday", "next/last <weekday>" | vague and relative ("the week after the trip", "then") |
| `duration` | ISO 8601 duration | "3 days", "2h" | "a couple of weeks" |
| `quantity` | number + UCUM unit | numbers with units | implicit units |
| `money` | amount + ISO currency | "$12.40", "€5" | "twelve bucks" |
| `contact` | url / email / phone / handle | regex | — |
| `artifact` | path, command, code identifier, version, ticket id | backticks, paths, semver | prose references to code |
| `person`, `organization`, `place` | entity id | capitalized-name heuristic only as a hint | resolution to entities, aliases |

Spans point into windows by character offsets, so text stays verbatim while values become
queryable. Candidates for the night pass: the 27B, or NuExtract3 with a fixed typed template —
its verbatim and typed-value strengths fit this job even though it was weak at open triples
(**to test**).

### 2.3 Time: three clocks and a modality

| Clock | Meaning | Source |
|---|---|---|
| **said** | when the words were written | window timestamp |
| **happens** | when the thing it describes occurs or occurred | `time` spans, resolved against *said* |
| **believed** | when memory held it true | fact `valid_from` / `valid_to` |

Every fact also carries a **modality** (prescribed, because each changes behaviour):
`asserted`, `planned`, `habitual`, `preferred`, `hypothetical`, `negated`, `reported`.
- Relative times are pinned to absolute dates at the night typing pass — "next Tuesday" said on
  2026-09-21 becomes 2026-09-29 forever.
- **Plan lifecycle:** each night, `planned` facts whose *happens* time has passed become
  `unconfirmed` unless later evidence shows they happened ("we got back from Yosemite") or were
  cancelled. Recall shows unconfirmed plans as such.
- `hypothetical` and `negated` never become current state; `reported` keeps who said it.

---

## 3. Memory tiers

| Tier | Holds | Written | Read |
|---|---|---|---|
| Working | the context window | Hermes | always |
| **Short-term** | windows and spans since the last sleep, heuristic headers | every turn | every turn |
| **Long-term raw** | every past window with model headers and full spans | asleep (headers, spans) | every turn |
| **Long-term structure** | threads, facts, entities, views | asleep | every turn (facts), on request (views) |
| **Long-term judgment** | dossiers with earned credit (Gemmery) | asleep | once per session |
| Hermes built-ins | MEMORY.md, USER.md, skills, session search | Hermes | Hermes |

---

## 4. Emergent versus prescribed — the boundary and the dial

**Prescribed (designed once, small, domain-free):** the value types (§2.2), the three clocks and
modalities (§2.3), and six mechanical relation kinds the system itself needs — `same_as` (aliases),
`supersedes`, `part_of`, `mentions` (window→entity), `answers` (window→window), `follows`
(episode order). These are the physics; they say how to read and maintain memory, not what it contains.

**Emergent:** entities, relation predicates ("works at", "is bringing"), topics, page boundaries,
hierarchy, links between pages.

**Promotion is the dial.** Each night, emergent patterns are candidates for structure:
- **Predicates:** verb phrases are clustered; a cluster becomes a **canonical relation** once it has
  ≥ *N* instances across ≥ *M* sessions or sources and has been used in recall. Canonical relations
  unlock counts and lists (`sophia_query`) and learn **exclusivity** from data: if a subject's
  instances are usually sequential rather than concurrent ("lives in", "uses camera"), newer ones
  supersede older ones; otherwise they coexist. This replaces guessing at supersession.
- **Pages:** an entity gets a page at ≥ *N* facts or first use in recall; a topic cluster gets a
  page after it stays stable across *K* nights.
- **Demotion:** canonical relations and pages unused for *K* nights fall back to plain clusters.
  Nothing is deleted.

Low thresholds make the wiki structured early and feel prescribed; high thresholds keep it
emergent and slower to firm up. **Pins** are the escape hatch: you can declare a relation, a page,
or an importance class up front (e.g. "health facts never decay") — prescription on request,
not by default.

---

## 5. Awake

Rule: no generated text on the awake path. Model calls: embeddings (**measured** ~18 ms) and at
most one decider call per turn (**measured** ~0.3 s).

### 5.1 Capture — every turn, background (`sync_turn`)

1. **Window** user and assistant messages; add the heuristic context header (§2.1).
2. **Redact** secrets (Gemmery's patterns) before storage.
3. **Deterministic spans** (§2.2 awake column), with relative times resolved by a small
   rule-based resolver against the message time.
4. **Echo fencing:** assistant sentences that restate evidence injected this turn (high n-gram or
   embedding overlap) are flagged `echo` — stored, but excluded from retrieval and from credit.
5. **Embed** `index_text`; write windows, spans, FTS.
6. **Auto-capture of what was read** from the turn's tool results, by allowlist: `web_extract`
   and browser page text become external chunks keyed by URL (deduplicated by content hash).
   File reads become `artifact` events (path, hash) — the file is its own raw record. Credential
   and vault tools are never captured.
7. **Images:** image references are stored and queued for captioning at night (**verify** how
   Hermes stores attachments in messages).
8. **Events and outcomes:** tool calls as templated events; pytest summaries as real outcomes;
   dossier citations `[[knowledge/…]]` logged.
9. **Log the injection** that preceded this turn with the response reference.

Other inputs, same path: `sophia_ingest`, `sophia_remember` (flagged `explicit`), built-in memory
writes. `on_pre_compress`: the span is already indexed; the committed write is the checkpoint.

### 5.2 Recall — every turn (`prefetch`)

1. Hermes skips trivial prompts. Embed the query.
2. **Time scope:** the rule-based resolver reads time expressions in the query ("last Tuesday",
   "in March"); if present, candidates are filtered by the *said* or *happens* clock, and
   day-level questions ("what did we talk about Tuesday?") add that day's session titles from
   Hermes's session store.
3. **Type hint:** "when / how much / where / who" boosts windows with spans of the matching type.
4. **Candidates by rank:** raw windows (all time) top 20, active facts top 20, FTS over both.
   Junk floor 0.5 (to re-measure on windows, §11).
5. **Merge:** a fact and its source window collapse into one item. Order by rank, then credit.
6. **Gate:** skip at top-1 ≥ 0.82, otherwise one decider Noul over the top 10.
7. **Inject evidence or nothing:** verbatim windows, dates and numbers first, modality marked
   (`planned`, `unconfirmed`, `reported by Sam`), assistant-authored windows marked. ≤ 3,000 chars.
8. Log the injection.

**Degraded modes:** decider unavailable → inject only above the skip threshold; embeddings
unavailable → FTS only. Either state is recorded and shown in `status` and the journal.

### 5.3 Judgment — once per session

Dossiers ranked by credit, rendered into the system prompt via `system_prompt_block()`
(**verify** limits; fallback `register_system_prompt_section`, 4,000 chars). Numbers lead.

### 5.4 Tools — the deliberate side

| Tool | Purpose |
|---|---|
| `sophia_recall(query, history=false)` | deeper associative recall; past states with dates on request |
| `sophia_query(entity?, relation?, type?, from?, to?, aggregate?)` | structured questions over canonical relations and typed spans: counts, lists, sums, date ranges |
| `sophia_browse(view, key)` | the wiki: `entity`, `timeline`, `people`, `places`, `topics`, `sources`, `trust`, `changes` |
| `sophia_remember(fact)` / feedback | explicit memory; `helpful` / `wrong` on recalled items is real credit |
| `sophia_ingest(text, source_url)` | explicit learning from a document (reads are also captured automatically) |

---

## 6. Asleep — the nightly sequence

**Trigger:** Hermes cron at a set hour (default 03:00) running `hermes sophia sleep`, or idleness.
**Yields** to chat and resumes later. Every item is keyed by (night, step, item); reruns are safe;
a missed night is absorbed by the next. **Models:** the 27B through aux task `sophia_sleep`;
the 9B to replay gate decisions. **estimate:** 60–90 minutes for a busy day.

| Phase | # | Step | Does |
|---|---|---|---|
| **Settle** | 0 | Settle | lock, snapshot the day past the watermark, check models, record degraded modes |
| **Understand** | 1 | Sort | drop navigation/reference chunks and filler turns |
| | 2 | Caption | images → caption windows (the 27B is a vision model) |
| | 3 | Thread | segment sessions into episodes; link question→answer, assent→decision, correction→target |
| | 4 | Contextualize | model headers for every window, one call per session; re-embed `index_text` |
| | 5 | Type | model-typed spans where deterministic typing failed; resolve relative and vague times; modality per clause |
| **Consolidate** | 6 | Headroom | external chunks: ask the 27B the chunk's question cold; consolidate only where its answer disagrees or is missing |
| | 7 | Relate | relations from contextualized windows; objects point at typed spans where possible |
| | 8 | Integrate | entity resolution (merges logged, reversible); supersession only for exclusive relations or explicit change language; plan lifecycle; importance flag ("would forgetting this be harmful?") |
| | 9 | Index | embed facts and entities; span index |
| **Dream** | 10 | Real outcomes | tests, corrections, feedback → real credit (failures 2x) |
| | 11 | Replay | every real turn: judge what was injected and whether the gate was right (as it was); check tonight's memory can answer (as it is) |
| | 12 | Rehearse | questions about new facts **in every category** — lookup, temporal, count, chained, between-message, abstention — recall must answer; misses repaired; questions join the standing eval |
| | 13 | Librarian | Gemmery: 0–2 dossiers per session with replay verdicts as evidence |
| **Organize** | 14 | Calibrate | fit decider temperatures (≥ 50 labels per type); re-derive thresholds; apply only if the standing eval does not regress |
| | 15 | Promote / demote | canonical relations, learned exclusivity, pages (§4) |
| | 16 | Build views | entity pages, timeline, people, places, topics, sources, trust, changes |
| | 17 | Anticipate | warm caches for entities active recently and dated facts coming up |
| **Tidy** | 18 | Tidy | decay (§7), gc, vacuum, dream journal (including merges and supersessions, for undo); **advance the watermark last** |

**Why this order.** Images are part of the conversation, so captions come before threading.
Headers need threads; typing needs resolved references; relations need types; supersession needs
entities and learned exclusivity. The dream phase tests the finished memory, and real outcomes
fold before replay so replay never overrides them. Calibration and promotion consume the dream's
labels and credit. Views are built from promoted structure; anticipation from views. The
watermark moves last so an interrupted night simply reruns.

---

## 7. Credit and decay

| Class | Source | Used for |
|---|---|---|
| real | tests, corrections, feedback, dossier citations that led to passing work | ordering, first |
| replay | the 27B judging real turns against raw evidence | ordering when real is absent; decider labels |
| rehearsal | synthetic questions | index repair and the eval only |

- Append-only events, folded per class; failures debit 2x; pending ≠ 0.
- **Decay only on evidence of irrelevance:** an item sinks only after being injected and judged
  irrelevant repeatedly. Items never asked about do not decay.
- **Importance exemption:** items flagged as harmful to forget (health, safety, identity,
  obligations) and pinned classes never decay.
- **Credit orders, never gates:** new and uncredited items compete on similarity; credit breaks
  ties and orders the evidence.

---

## 8. Data model (SQLite, `$HERMES_HOME/plugin-data/sophia/sophia.db`, WAL)

```sql
windows(id TEXT PRIMARY KEY, ref TEXT, session_id TEXT, speaker TEXT, said REAL,
        text TEXT, index_text TEXT, header_source TEXT,           -- heuristic | model
        flags TEXT)                                                -- explicit|assistant|echo|trivial|caption
window_vectors(id TEXT, model TEXT, vec BLOB, PRIMARY KEY (id, model))
spans(window_id TEXT, start INT, end INT, type TEXT, value TEXT,  -- normalized value (ISO, UCUM, entity id…)
      source TEXT, confidence REAL)                                -- deterministic | model
threads(id TEXT PRIMARY KEY, session_id TEXT, title TEXT, start_window TEXT, end_window TEXT)
links(src TEXT, dst TEXT, kind TEXT, PRIMARY KEY (src, dst, kind))  -- answers|decides|corrects|follows|mentions|same_as|part_of|supersedes
chunks(ref TEXT PRIMARY KEY, url TEXT, title TEXT, text TEXT, fetched_at REAL, content_hash TEXT,
       headroom TEXT, dropped INT)                                 -- chunks are windowed like turns
facts(id TEXT PRIMARY KEY, subject TEXT, relation TEXT, object TEXT, object_span TEXT,
      modality TEXT, happens TEXT, valid_from REAL, valid_to REAL, superseded_by TEXT,
      status TEXT, importance INT, night_id TEXT)
fact_sources(fact_id TEXT, window_id TEXT, PRIMARY KEY (fact_id, window_id))
fact_vectors(id TEXT, model TEXT, vec BLOB, PRIMARY KEY (id, model))
entities(id TEXT PRIMARY KEY, name TEXT, type TEXT, aliases TEXT, page INT, vec BLOB)
relations(name TEXT PRIMARY KEY, cluster TEXT, canonical INT, exclusive INT, instances INT,
          promoted_night TEXT, pinned INT)
events(id TEXT PRIMARY KEY, session_id TEXT, kind TEXT, summary TEXT, said REAL)
outcomes(id TEXT PRIMARY KEY, session_id TEXT, kind TEXT, ok INT, summary TEXT, said REAL)
citations(session_id TEXT, message_id TEXT, dossier_path TEXT, said REAL)
injections(session_id TEXT, turn_id TEXT, items TEXT, gate TEXT, response_ref TEXT, said REAL)
credit_events(item_id TEXT, item_kind TEXT, class TEXT, kind TEXT, delta REAL, night_id TEXT, ts REAL)
decisions(id TEXT PRIMARY KEY, ts REAL, type TEXT, state_sha TEXT, options TEXT,
          probabilities TEXT, raw TEXT, flip INT, gold TEXT, gold_class TEXT)
views(key TEXT PRIMARY KEY, kind TEXT, body TEXT, built_night TEXT)
journal(night_id TEXT, step TEXT, kind TEXT, detail TEXT, undo TEXT)   -- merges, supersessions, promotions
jobs(night_id TEXT, step TEXT, item TEXT, status TEXT, attempts INT, updated_at REAL,
     PRIMARY KEY (night_id, step, item))
watermarks(key TEXT PRIMARY KEY, value TEXT)
eval_questions(id TEXT PRIMARY KEY, question TEXT, category TEXT, answer_refs TEXT, origin TEXT)
fts USING fts5(ref, text)                                          -- index_text of windows and facts
```

Dossiers live in the Gemmery git store (§14 question 1).

---

## 9. Evaluation that can see its own gaps

| Set | What | When |
|---|---|---|
| **LongMemEval** | the benchmark Gemmery already has a harness for (`experiments/lme`); five abilities — information extraction, multi-session reasoning, temporal reasoning, knowledge updates, abstention | each milestone and weekly; too heavy for nightly |
| **Hand set** | 50+ questions from your own history, tagged by category, including counts, chained questions, between-message decisions, images | each milestone |
| **Standing set** | replay and rehearsal questions, category-tagged | nightly regression gate for calibration |
| **Scale test** | recall@10 and gate precision with 100k+ windows (your history plus a LongMemEval haystack) | M1 and M3 |

Every deferral in this design is decided by these sets: rooms and the multi-room walk come back
only if chained questions lag; the fact layer shrinks if it does not beat raw windows on temporal,
knowledge-update, and count categories.

---

## 10. Models and VRAM

| When | Model | Job |
|---|---|---|
| Awake | Qwen3.8-27B (LM Studio) | Hermes chat |
| Awake | Qwen3.5-9B (LM Studio), reasoning off | the gate; a smaller decider may suffice (test a 4B in M2) |
| Awake | nomic-embed-text-v1.5 (LM Studio) | all embeddings |
| Asleep | Qwen3.8-27B (vision-capable) | caption, thread, contextualize, type, headroom, relate, integrate, replay, rehearse, librarian |
| Asleep | Qwen3.5-9B | replaying gate decisions |
| Candidate | NuExtract3 (on disk) | night typing pass, if it beats the 27B on typed spans |

The 27B at 16–32k context instead of 64k frees several GB per card.

---

## 11. Thresholds — **measured** on facts, to be re-measured on windows

76 triples from 13 texts (8 written as near-misses); 24 answerable and 10 unanswerable questions.
Prefixes required (recall@1 0.75 vs 0.62). Triple + source sentence: recall@10 1.00. Irrelevant
pairs median 0.49, relevant median 0.80. Unanswerable near-misses up to 0.78. SophiaAMS's
0.15 / 0.2 / 0.3 cutoffs keep 100% of pairs. Skip-gate at ≥ 0.82 covered 38% of answerable, 0% of
unanswerable. Decider gate over top 10: 32/34, no false "not found". Windows with heuristic and
model headers must be re-measured (M1), and at scale (§9).

---

## 12. CLI

```
hermes sophia status                  sizes, last sleep, watermark, degraded modes, calibration
hermes sophia sleep [--dry-run] [--phase NAME] [--night ID]
hermes sophia journal [--night ID]    learned, superseded, merged, promoted, missed; with undo ids
hermes sophia undo <journal-id>       revert a merge, supersession, or promotion
hermes sophia eval [--set lme|hand|standing|scale]
hermes sophia pin <relation|page|importance> …
hermes sophia reembed --model M
hermes sophia reconsolidate --since D
```

---

## 13. Milestones

**M1 — awake path and the yardstick.** Windows with heuristic headers, deterministic spans and
the time resolver, echo fencing, auto-capture of reads, prefetch with time scope and degraded
modes, injection log, `sophia_ingest`, `sophia_remember`, `status`. The LongMemEval adapter, the
hand set, the window threshold test, and the scale test. *Done when* a week of your sessions is
indexed and there is a raw-only LongMemEval number to beat.

**M2 — gate and first nights.** The decider gate; sleep phases Settle, Understand (sort, thread,
contextualize), Dream (real outcomes, replay), Organize (calibrate), Tidy. *Done when* LongMemEval
and the hand set improve over M1, and a night produces decider labels.

**M3 — structure and time.** Caption, type, consolidate, rehearse, promote/demote, views, plan
lifecycle, `sophia_query`, `sophia_browse`, `undo`. *Done when* temporal, knowledge-update, and
count categories improve over M2 — otherwise shrink the fact layer to what did improve.

**M4 — judgment.** Gemmery IO split, dossier injection, citations, outcome capture, librarian.

**M5 — Mindscape.** A UI over the views. Rooms and the multi-room walk only if chained questions lag.

**Dropped:** Sophia's goal table — Hermes kanban and `/goal` hold goals; memory holds facts about
them (**verify** kanban can hold a goal that never completes).

---

## 14. Open questions and risks

1. **Dossier store scope:** per project when the session cwd is a git repo, per profile otherwise?
2. **Promotion thresholds** *N*, *M*, *K*: start high (emergent) and lower with evidence, or the reverse?
3. **"Used" is not "helped."** If replay's helped/misled calls prove noisy, credit facts on use and contradictions only.
4. **Replay grades the 27B's own answers** — judged against raw evidence, kept as its own class.
5. **Night cost** grows with contextualizing every window; one call per session keeps it bounded — measure in M2.
6. **Sleep window** on a gateway that is never idle; the yield rule protects chat.
7. **Raw index growth:** float16 vectors and sqlite-vec past ~500k windows.
8. **Rule-based time resolver coverage** — measured by the temporal category; the night pass catches what it misses.
9. **Verify items:** `system_prompt_block()` limits; `PluginLlm(plugin_id="sophia")` from a provider;
   `reasoning_effort` passthrough on aux tasks; read-only session-store access; attachment storage;
   browser page-text tool names for auto-capture.
10. **Hook name trap:** provider `on_session_end` is a true session boundary; a general plugin's fires every turn.

---

## 15. Implementation status (prototype, 2026-09-23)

The code is this repository. It is tested on the `sophiadev` profile (a clone of the default profile) through the real Hermes loader and `hermes -p sophiadev chat`.

**Built and exercised in Hermes**
- The provider is discovered and loaded from `plugins/sophia`. It exposes 5 tools, a system block, and a recall status line.
- Awake path:
  - capture on a worker thread, 0.11 s per turn;
  - prefetch 260–460 ms including the gate;
  - off-topic queries blocked (for example "capital of Australia" scored 0.45);
  - a fresh session recalled the camera, Sam, and the dentist (gate 0.97).
- Auto-capture of `web_extract`:
  - Hermes's untrusted-content wrapper is unwrapped;
  - failed extractions are detected and dropped;
  - one chunk is made per URL;
  - injected source text carries an "(untrusted source text)" label.
- Night on the 9B (about 44 s for 14 windows): headers, links, facts, supersession (Fujifilm → Sony A7 IV, with the journal entry, `undo`, and restore round-tripped), the plan lifecycle, the importance exemption, replay labels, and entity views.
  - Fresh sessions afterward answer "Sony A7 IV"; one noted the original plan.
- When the prompt told the agent to use `sophia_browse` (view=entity for Dr. Patel), it called the tool correctly and cited where the fact came from. Unprompted tool use hasn't been tested yet.
- `ingest-history` reads the session store read-only and is idempotent: live and stored message shapes hash to the same identity.
- Per-job model servers. Embeddings, decider and night each have a model and an optional server, of type `lmstudio` or `openai` (llama-server, vLLM). Verified against LM Studio and a CPU llama-server: chat, logprob readout, routed recall, and the night's busy check.
- Hermes setup (`hermes memory setup`) and the dashboard expose all 48 settings. The basics are always shown; servers and tuning sit behind two gate questions.
- Graph expansion at recall: one hop from bridge entities, with hub damping, plus conversation links. Live, "Where does Sam's sister live?" reached `Lily | moved to | Denver` (similarity 0.57, below the cutoff) through Lily.
- Grounding check at capture. Live agent replies whose claims about the user are unsupported are kept out of recall. Found live: an invented answer was recalled as memory in the next session. The positive wording, read in both option orders, separated six hand-labelled cases (bad ≥ 0.59, good ≤ 0.34); the negative wording did not.
- Bare earlier questions are never injected passively.
- Unit tests: 38, all passing, run against a fake model server.

**Answers to §14 verify items**
- `ctx.llm` is not forwarded to memory providers (`_ProviderCollector`), so Sophia talks to LM Studio directly. `reasoning_effort: "none"` works on `/v1/chat/completions`, and `/v1/responses` returns first-token logprobs.
- `SessionDB(read_only=True)` works for history import. Stored rows carry `tool_name` and `tool_call_id: None`, while live messages carry `name`.
- The system block is short (under 700 characters). General plugins' `register_system_prompt_section` caps at 4,000.

**Simplified**
- Typing is deterministic only; there is no night typing pass.
- Threads are `links` rows with no segmentation table.
- Headroom is a Noul judgment, not the cold-answer test.
- Anticipate only builds an upcoming-7-days view; it warms no caches.
- The decider is uncalibrated: 3 labels so far, and `calibrate` needs 50.

**Not built yet**
- Image captions.
- The Gemmery layer, milestone M4. The outcomes step is a placeholder.
- The LongMemEval harness and the hand set (§9).
- The Mindscape UI.
- A scheduled nightly run. The README has a cron line; nothing is installed.
- The night has not been run on the 27B. It only ran on the 9B, so that the 27B instance in use elsewhere was never disturbed.

**Lessons that changed the code**
- Extraction must never read the model's context header as a source. The header once absorbed an assistant hallucination and extraction attributed it to the user. `relate` now sends verbatim `TEXT` with `CONTEXT` labelled, and never extracts from assistant lines.
- Supersession must be strictly older, negation-aware, and never within the same message.
- Injections need an assistant penalty and cap, exclusion of the live session unless compacted, and a floor relative to the top score. Without them, the agent's own restatements crowd out the user's words.

---

## Appendix — blind spots and where they are handled

| Blind spot | Handled by |
|---|---|
| What the agent reads but doesn't restate | auto-capture of reads, §5.1 step 6 |
| Images, files | captions at night; files as artifact events, §5.1 |
| Meaning between messages | heuristic and model headers, threads, §2.1 |
| Time questions, relative dates, stale plans | three clocks, modality, plan lifecycle, time-scoped recall, §2.3, §5.2 |
| Counts, lists | typed spans, canonical relations, `sophia_query`, §2.2, §4 |
| Chained questions | eval category; rooms return only if it lags, §9 |
| Scale | scale test, §9 |
| Memory echo | echo fencing, §5.1 step 4 |
| Wrong supersession, entity merges | learned exclusivity; logged, reversible merges; `undo`, §4, §6 |
| General-knowledge filter fooled by recency | cold-answer headroom test, §6 step 6 |
| Rare critical facts decaying | decay only on judged irrelevance; importance exemption, §7 |
| Rich get richer | credit orders, never gates, §7 |
| An eval blind to its own gaps | LongMemEval categories and hand set, §9 |
| Silent degradation | degraded modes recorded and shown, §5.2 |
