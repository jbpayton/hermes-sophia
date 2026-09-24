# hermes-sophia — design draft v0.4

**One Hermes memory provider, two layers (facts and judgment), two modes (awake and asleep).**
SophiaAMS's associative memory and Gemmery's earned judgment, rebuilt as one plugin. Awake, it
only embeds, retrieves, and makes one cheap decision per turn. Asleep, the large model does all
the heavy work: consolidation, dreaming, judgment, calibration.

Status: draft v0.4, 2026-09-23. Targets Hermes Agent v0.21.4 (`~/.hermes/hermes-agent`).
**measured** = from runs on this box (scripts and `results/` in this folder).
**verify** = assumption to check in the first milestone. **estimate** = not yet measured.

Changes from v0.3 (archived in `archive/`): one provider instead of sibling plugins; the day
path generates no text; all extraction, credit judgment, and the librarian move to sleep; the
triple layer shrinks to what raw retrieval can't do; rooms and the walk are deferred behind an
eval; Sophia's goal system is dropped in favour of Hermes kanban and `/goal`.

---

## 1. Principles

From Gemmery's experiments (`github.com/jbpayton/gemmery`, `FINDINGS.md`) and today's measurements:

1. **The raw record is the truth; everything else is an index.** Retrieval over raw text beat
   write-time distillation 0.917 vs 0.37–0.50 on LongMemEval. Recall returns verbatim evidence.
2. **Distill judgment, retrieve facts.** Facts come back as evidence; only judgment (rules,
   decisions, falsified assumptions) is distilled — into dossiers.
3. **Revise, don't accumulate.** A newer fact about the same thing supersedes the older one; history stays.
4. **Credit is earned from outcomes,** in three strengths kept apart: real > replay > rehearsal.
   Misleading costs twice what helping earns.
5. **Similarity ranks, the decider judges.** Nomic ranks the answer into the top 10 but cannot
   tell it from a near-miss; the logprob decider can (**measured**, §9).
6. **Memory helps only where the model is ignorant.** Don't consolidate general knowledge.
7. **Numbers lead, abstain honestly, never last-write-wins.**
8. **Awake is cheap, asleep is thorough.** Nothing that generates text runs on the chat's critical path.

---

## 2. Memory tiers

| Tier | What it holds | Stored | Written | Read |
|---|---|---|---|---|
| Working | the current context window | Hermes | Hermes | always |
| **Short-term** | everything since the last sleep: today's turns, pages read, notes, events — raw and embedded, not yet consolidated | raw index (`windows`, `chunks`) | every turn, while awake | every turn |
| **Long-term: raw** | every past turn and page, embedded | same raw index | nothing new at night (already there) | every turn |
| **Long-term: facts** | current state, entities, relationships, dated events — each linked to its source windows | `facts`, `entities` | asleep only | every turn |
| **Long-term: judgment** | dossiers with earned credit | Gemmery git store | asleep only (librarian) | once per session |
| Hermes built-ins | MEMORY.md, USER.md, skills, session search | Hermes | Hermes / agent | Hermes |

Short-term and long-term raw are one index; "short-term" just means *not yet consolidated*.
After a night, today's windows are still in the index — they have simply gained facts and credit.

---

## 3. Shape

- One pip package, `hermes-sophia`; entry point `hermes_agent.memory_providers: sophia`.
- Depends on the **Gemmery library** (store, valuation, dossier model, librarian prompt) — Gemmery
  keeps its standalone Claude Code front end; on Hermes it runs as this provider's judgment layer.
  Needs the IO split in Gemmery's `prod/hooks.py` (pure functions; Claude Code and Hermes front ends).
- Runtime dependencies: `numpy`, `pygit2` (via Gemmery). SQLite, HTTP, JSON are stdlib.
  Optional: `scikit-learn` (directory clustering, deferred), `sqlite-vec` (beyond ~500k windows).

```
hermes_sophia/
├── __init__.py      register(ctx): provider, aux tasks (sophia_sleep, sophia_decider), skills
├── provider.py      lifecycle hooks, tools, awake paths
├── store.py         SQLite: windows, chunks, facts, entities, credit, injections, jobs
├── embed.py         nomic via LM Studio /v1/embeddings, prefixes applied here
├── recall.py        candidate retrieval, merge, gate, evidence formatting
├── decider.py       logprob readout (sophia_decider.py in this folder)
├── judgment.py      Gemmery layer: dossier injection, citations, outcome capture
├── sleep/           one module per sleep step (§5), each idempotent
├── cli.py           hermes sophia <status|sleep|journal|eval|reembed|reconsolidate>
└── skills/memory/SKILL.md
```

---

## 4. Awake

Rule: **no generated text** on the awake path. The only model calls are embeddings (~18 ms,
**measured**) and at most one decider call per turn (~0.3 s, **measured**).

### 4.1 Short-term memory — writing, every turn (`sync_turn`, background thread)

1. **Window the turn.** Split user and assistant messages into windows of ~2–3 sentences, each
   with `hermes:<session_id>:<message_id>`, speaker, timestamp.
2. **Redact** secrets at the boundary (Gemmery's redaction patterns) before anything is stored.
3. **Embed** the windows in one call as `search_document: [<speaker>, <date>] <text>`; write to
   the raw index and FTS5. The day's memory is searchable within a second of the turn.
4. **Events, not tool output.** Tool calls become one templated event row each (tool, status,
   duration, key argument). Tool output is not embedded.
5. **Real outcomes, parsed not judged.** pytest summaries in tool results → outcome rows
   (Gemmery's parser). Dossier citations `[[knowledge/…]]` in assistant text → citation rows.
6. **Log the injection** made before this turn together with the response id, for sleep to judge.

Other short-term inputs, same treatment (store raw, embed, no extraction):
- `sophia_ingest(text, source_url)` — pages the agent read: chunked, stored in `chunks`, embedded.
- `sophia_remember(fact)` and built-in memory writes (`on_memory_write`) — a window flagged
  `explicit`, top priority for tonight's consolidation.
- `on_pre_compress` — the span is already indexed; the checkpoint is the committed index write
  (fail-closed checkpoint API v2 satisfied without extra work).

Cost per turn: one embedding call plus two SQLite writes, off the critical path.

### 4.2 Long-term memory — reading, every turn (`prefetch`)

1. Hermes skips trivial prompts. Embed the query (**measured** 18 ms).
2. **Candidates by rank, three channels:** raw windows (all time, including today) — top 20;
   active facts (triple + source sentence vectors) — top 20; FTS5 over both for exact names and
   commands. Junk floor 0.5 (§9).
3. **Merge:** a fact and its own source window collapse into one item (fact line as the header,
   window as the evidence). Order by rank, then credit (real, then replay). Short-term items carry
   a small recency lift.
4. **Gate:** skip if top-1 similarity ≥ 0.82; otherwise one decider Noul over the top 10,
   "at least one item directly answers the message" (threshold 0.6 with two orders, 0.5 with one).
5. **Inject evidence or nothing.** Verbatim windows with dates and numbers first:
   `[2026-09-21 · used 5, helped 4] Joey | is bringing | Fujifilm X-T5 — "I'm bringing the Fujifilm X-T5 this time…"`
   Assistant-authored windows are marked as such (weaker evidence than the user's own words).
   Target ≤ 3,000 characters.
6. Log what was injected (for sleep).

Budget: p95 under 400 ms, dominated by the gate.

### 4.3 Long-term judgment — once per session

- Dossiers ranked by earned credit, rendered once into the system prompt through the provider's
  `system_prompt_block()` (static per session, cache-safe) — **verify** its size limits; fallback
  `register_system_prompt_section` (4,000 chars). Numbers lead: version count, wins/losses, credit.
- The agent is asked to cite dossiers it uses as `[[knowledge/…]]` (Gemmery's convention).

### 4.4 Deeper recall on request — `sophia_recall(query)` tool

Same channels with k = 30, plus entity expansion (all active facts about the top entities) and a
history mode that includes superseded facts with their dates when the question is about the past.
Hermes's own `session_search` tool remains available to the agent for lexical search.

---

## 5. Asleep — the nightly sequence, in order

**Trigger:** a Hermes cron job at a configured hour (default 03:00) running `hermes sophia sleep`,
or Hermes-curator-style idleness (no turns for N hours). **Yields** when you start chatting:
finishes the current item, pauses, resumes at the next idle window. Every step is keyed by
(night, step, item) in `jobs`, so a crash or yield resumes cleanly. A missed night is absorbed by
the next one.

**Models:** the 27B (idle while you sleep) through aux task `sophia_sleep` for everything that
generates or judges; the 9B only to replay the day's gate decisions. **estimate** for a busy day
(~150 turns, ~10 pages): 45–60 minutes; the 27B produced compact extraction at ~5–8 s per chunk
(**measured**, incidentally, in the speed tests).

| # | Step | Does | Needs | Produces |
|---|---|---|---|---|
| 0 | **Settle** | take the lock, snapshot "the day" = everything past the watermark, check models | — | night id, work list |
| 1 | **Sort** | external chunks: drop navigation/references; flag general knowledge (kept raw, not consolidated). Conversation: skip filler, flag advice sentences for the librarian | decider | the day's consolidation queue |
| 2 | **Consolidate** | 27B compact extraction per session, in order, sentence-id grounded; validate (no empty/placeholder objects, ids resolve) | 27B | candidate facts |
| 3 | **Integrate** | entity resolution (aliases merged), dedup, **supersession** (newer replaces older: `valid_to`, `superseded_by`), conflicts that time can't resolve kept side by side and weighted by source credit | 27B for ambiguous cases | updated `facts`, `entities` |
| 4 | **Index** | embed new/changed facts and entities, FTS | nomic | searchable long-term facts |
| 5 | **Fold real outcomes** | tests, your corrections, explicit feedback → real credit on facts and dossiers (failures 2x) | — | real credit |
| 6 | **Replay (dream 1)** | for each of the day's real turns: (a) *as it was* — judge each injected item used / helped / misled, and whether the gate call was right; (b) *as it is now* — rerun recall against tonight's memory and check the answer is findable | 27B, 9B | replay credit, decider labels, recall-miss list |
| 7 | **Rehearse (dream 2)** | for each new fact, the 27B writes 1–2 questions a future you might ask; recall must find the fact; misses repaired (aliases, entity links, better index text) and retested once | 27B | index repairs, coverage stats — **never used for ranking** |
| 8 | **Librarian** | per session: transcript + real outcomes + replay verdicts + cited dossiers → 0–2 dossier captures or revisions, helped/misled verdicts (Gemmery) | 27B | dossiers, dossier credit |
| 9 | **Calibrate** | fit decider temperatures from replay + real labels (apply only with ≥ 50 labels per decision type); re-derive skip and gate thresholds; run the standing eval set and **apply new parameters only if nothing regresses** | 9B | calibration file, thresholds |
| 10 | **Anticipate** | sleep-time compute proper: entities active recently, dated facts in the next days ("appointment Oct 14"), open plans → pre-assemble and cache their evidence bundles; render tomorrow's dossier block | — | warm caches |
| 11 | **Tidy** | decay items repeatedly judged unused (raw is never deleted); `git gc` on the dossier store; SQLite vacuum; write the dream journal; **advance the watermark last** | — | journal, clean store |

Why this order: facts must exist (2–4) before replay can ask whether tonight's memory would
have answered (6b); real outcomes fold before replay so replay never overrides them (5 → 6);
the librarian needs replay verdicts as evidence (6 → 8); calibration needs the labels replay just
produced (6 → 9); anticipation works on the finished state (10); the watermark moves last so an
interrupted night reruns safely (11).

**Dream journal:** a short record of what the night learned, superseded, revised, and missed —
`hermes sophia journal`, and optionally one line surfaced in the first prefetch of the morning.

---

## 6. Credit

| Class | Source | Used for |
|---|---|---|
| **real** | tests, your corrections, explicit feedback, dossier citations that led to passing work | ranking first; never overridden |
| **replay** | the 27B judging real turns with raw evidence visible | ranking when real is absent; decider calibration |
| **rehearsal** | synthetic questions about new facts | index repair only |

Fold: append-only events; current credit is a fold per class; failures debit 2x; pending ≠ 0
(Gemmery's three-valued rule). Known bias: replay is partly the 27B grading its own answers —
mitigated by judging against raw evidence and by keeping replay separate from real.

---

## 7. Data model (SQLite, `$HERMES_HOME/plugin-data/sophia/sophia.db`, WAL)

```sql
windows(id TEXT PRIMARY KEY, ref TEXT, session_id TEXT, speaker TEXT, ts REAL, text TEXT,
        flags TEXT)                             -- explicit | advice | assistant | trivial
window_vectors(id TEXT, model TEXT, vec BLOB, PRIMARY KEY (id, model))   -- float16 at scale
chunks(ref TEXT PRIMARY KEY, url TEXT, title TEXT, text TEXT, fetched_at REAL,
       general_knowledge INT, dropped INT)
chunk_vectors(ref TEXT, model TEXT, vec BLOB, PRIMARY KEY (ref, model))
fts USING fts5(ref, text)                       -- windows, chunks, facts
facts(id TEXT PRIMARY KEY, subject TEXT, verb TEXT, object TEXT, topics TEXT, event_time TEXT,
      valid_from REAL, valid_to REAL, superseded_by TEXT, status TEXT, night_id TEXT)
fact_sources(fact_id TEXT, ref TEXT, sentence TEXT, PRIMARY KEY (fact_id, ref, sentence))
fact_vectors(id TEXT, model TEXT, vec BLOB, PRIMARY KEY (id, model))   -- triple + sentence text
entities(name TEXT PRIMARY KEY, aliases TEXT, fact_count INT, vec BLOB, model TEXT)
events(id TEXT PRIMARY KEY, session_id TEXT, kind TEXT, summary TEXT, ts REAL)
outcomes(id TEXT PRIMARY KEY, session_id TEXT, kind TEXT, ok INT, summary TEXT, ts REAL)
citations(session_id TEXT, message_id TEXT, dossier_path TEXT, ts REAL)
injections(session_id TEXT, turn_id TEXT, items TEXT, gate TEXT, response_ref TEXT, ts REAL)
credit_events(item_id TEXT, item_kind TEXT, class TEXT, kind TEXT, delta REAL, night_id TEXT, ts REAL)
decisions(id TEXT PRIMARY KEY, ts REAL, type TEXT, state_sha TEXT, options TEXT,
          probabilities TEXT, raw TEXT, flip INT, gold TEXT, gold_class TEXT)
jobs(night_id TEXT, step TEXT, item TEXT, status TEXT, attempts INT, updated_at REAL,
     PRIMARY KEY (night_id, step, item))
watermarks(key TEXT PRIMARY KEY, value TEXT)
eval_questions(id TEXT PRIMARY KEY, question TEXT, answer_refs TEXT, origin TEXT)  -- replay, rehearsal, hand
```

Dossiers live in the Gemmery git store (scope: §13 question 1). Everything in SQLite except
`credit_events`, `outcomes`, `citations`, and `decisions` can be rebuilt from the raw record.

---

## 8. Models and VRAM

| When | Model | Job |
|---|---|---|
| Awake | Qwen3.8-27B (LM Studio) | Hermes chat — unchanged |
| Awake | Qwen3.5-9B (LM Studio), reasoning off | the gate only — a smaller decider may suffice now that extraction moved to sleep (try a 4B GGUF in the M2 eval) |
| Awake | nomic-embed-text-v1.5 (LM Studio, 80 MB) | all embeddings |
| Asleep | Qwen3.8-27B | consolidation, integration, replay and rehearsal judging, librarian |
| Asleep | 9B | replaying gate decisions |

The 27B's 64k context and four slots hold KV cache a memory worker never needs by day; loading
it at 16–32k frees several GB per card.

---

## 9. Thresholds (nomic-embed-text-v1.5) — **measured**, provisional

76 triples extracted by the 9B from 13 texts, 8 of them written as near-misses; 24 answerable and
10 unanswerable questions (`embed_thresholds.py`).

| Finding | Value |
|---|---|
| Prefixes `search_query:` / `search_document:` | recall@1 0.75 with, 0.62 without — required |
| Index text = triple + source sentence | recall@10 1.00, worst gold rank 8 |
| Irrelevant pairs / relevant pairs | median 0.49 / median 0.80; relevant p5 0.62 |
| Unanswerable top-1 | up to 0.78 ("Voyager 2 launch" → "Voyager 1 was launched on…") |
| SophiaAMS cutoffs 0.15 / 0.2 / 0.3 | keep 100% of pairs — invalid |
| Skip-gate at top-1 ≥ 0.82 | 38% of answerable, 0% of unanswerable |
| Decider gate over top 10 | 32/34 (two orders), 31/34 (one); no false "not found" |

Raw-window thresholds are **not yet measured** — windows embed differently from triples. First
M1 task: rerun this test with raw windows as the documents. Nightly calibration (step 9) takes
over once real labels exist.

---

## 10. Tools

| Tool | Purpose |
|---|---|
| `sophia_recall(query, history=false)` | deeper recall: more candidates, entity expansion, past states with dates |
| `sophia_remember(fact)` / feedback | explicit memory; `helpful` / `wrong` feedback on a recalled item becomes real credit |
| `sophia_ingest(text, source_url)` | learn from a page or document the agent fetched |
| `sophia_browse(entity)` | everything currently believed about an entity, with sources — Mindscape's successor until rooms return |

---

## 11. CLI

```
hermes sophia status                  index sizes, last sleep, watermark, calibration state
hermes sophia sleep [--dry-run] [--steps 1-11] [--night ID]
hermes sophia journal [--night ID]    what the last night learned, superseded, revised, missed
hermes sophia eval [--set FILE]       recall and gate metrics on the standing eval set
hermes sophia reembed --model M       new vectors keyed by model; switch when complete
hermes sophia reconsolidate --since D rebuild facts from the raw record with the current prompt/model
```

---

## 12. Milestones

**M1 — awake path, raw only.** Provider, store, windowing, embeddings, prefetch over raw windows,
evidence injection, injection logging, `sophia_ingest`, `sophia_remember`. Rerun the threshold
test on raw windows. *Done when* a week of your real sessions is indexed and prefetch p95 < 100 ms
without the gate.

**M2 — gate and first sleep.** Decider gate; sleep steps 0, 5, 6a, 9, 11 (settle, real outcomes,
replay of injections, calibration, tidy). *Done when* a night produces decider labels and the eval
shows the gate's precision on your data. This milestone alone answers "is raw retrieval + gate enough?"

**M3 — consolidation.** Sleep steps 1–4, 6b, 7, 10: facts, supersession, rehearsal, anticipation.
*Done when* the eval shows facts beat raw-only on questions about current state and counts —
if they don't, keep the fact layer to supersession and entities only.

**M4 — judgment layer.** Gemmery IO split, dossier injection, citations, outcome capture, librarian
as sleep step 8.

**Deferred behind the eval:** rooms, doors, and the multi-room walk (only if M3's eval shows
questions that need more than one hop); the Mindscape UI; directory clustering.

**Dropped:** Sophia's goal table. Long-lived goals go to Hermes kanban (dependencies, durable cards,
recurring jobs) and `/goal`; memory keeps facts about goals, the judgment layer keeps what was
learned from how they went. **verify** kanban can hold a goal that never completes.

---

## 13. Open questions and risks

1. **Dossier store scope.** Per project when the session cwd is inside a git repo, per profile
   otherwise? Many Hermes chats have no project.
2. **"Used" is not "helped."** Replay judges both; if the distinction proves noisy, credit facts on
   "used" and contradictions only, and leave helped/misled to dossiers.
3. **Replay grades the 27B's own answers.** Judged against raw evidence, kept as a separate class.
4. **Sleep window.** A gateway that is never idle needs a configured hour; the yield rule protects chat.
5. **Raw index growth.** 768-d windows ≈ 3 KB each (float32); switch to float16 and sqlite-vec
   past ~500k windows. Brute force was 3 ms at 100k × 384-d (**measured**), ~2x at 768-d.
6. **Short-term staleness.** Today's changes don't supersede old facts until tonight; dated
   evidence lets the chat model see which is newer in the meantime.
7. **Verify items:** `system_prompt_block()` size limits; LLM facade from a provider
   (`PluginLlm(plugin_id="sophia")`); `reasoning_effort` passthrough on the aux task; read-only
   session-store access for replay.
8. **Hook name trap.** The provider's `on_session_end` is a true session boundary; a general
   plugin's `on_session_end` fires every turn. Everything here uses provider hooks.
