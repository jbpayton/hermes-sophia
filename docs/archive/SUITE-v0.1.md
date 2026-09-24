# Sophia + Gemmery on Hermes — suite plan v0.1

Two sibling plugins that each work alone and are better together. This document fixes the
boundary between them so neither duplicates the other, and lists the few things they share.
Companion to `DESIGN.md` (Sophia) and the Gemmery repository (`github.com/jbpayton/gemmery`).

Status: draft, 2026-09-22. Hermes facts below were checked against the installed v0.21.4.

---

## 1. Division of labour

| | Sophia | Gemmery |
|---|---|---|
| Keeps | **what is the case** — facts about people, projects, the world, and events, each tied to the raw record it came from | **what to do and why** — rules, decisions, falsified assumptions, track records, each with earned credit |
| Volume | high, automatic: every turn, every page read | low, selective: 0–2 dossiers per session; the decision to record is signal |
| Hermes slot | the one **memory provider** (`memory.provider: sophia`) | a **general plugin** (hooks + a system-prompt section); takes no memory-provider slot |
| Storage | SQLite in `$HERMES_HOME/plugin-data/sophia/` | git store (see §6 for scope) |
| Injection | per turn, dynamic, via `prefetch()` | once per session, cache-safe, via `register_system_prompt_section` |
| Model work | extraction + decisions on the local 9B | one librarian call per session/chapter on the local 9B |

Hermes itself keeps a third kind of memory the suite leaves alone: **skills** — how to do a task,
step by step, created by the agent and maintained by Hermes's curator.

**The boundary rule, one sentence each:**
- Sophia never stores advice as fact: rules of thumb found in conversation are left to the librarian.
- Gemmery never restates facts: dossiers cite Sophia source refs or project files instead
  (its own "distill judgment, retrieve facts" rule).
- Neither writes Hermes skills; Gemmery may *value* them later (§7).

---

## 2. Packaging

One monorepo is not required. Three distributions:

| Distribution | Contents | Depends on |
|---|---|---|
| suite core (working name) | decider (logprob readout), LM Studio client (chat, responses, embeddings), credit fold, source-ref format, in-process signal registry | numpy |
| `hermes-sophia` | memory provider (DESIGN.md) | suite core |
| `gemmery[hermes]` | the existing Gemmery library **plus** a Hermes adapter module, entry point `hermes_agent.plugins` | pygit2, numpy; suite core optional |

Gemmery stays one codebase with two front ends: the Claude Code wiring it has today, and the
Hermes adapter. Nothing moves out of the Gemmery repo.

---

## 3. Gemmery on Hermes — hook mapping

| Gemmery today (Claude Code) | Hermes surface | Notes |
|---|---|---|
| `SessionStart` → `gemmery inject` | `ctx.register_system_prompt_section("gemmery.dossiers", fn)` | renders once per new session, frozen across compression and resume; **4,000-char cap** per plugin (today's `INJECT_CAP` is 6,000 — trim) and 8,000 across all plugins |
| `PostToolUse` (Bash, pytest) → `outcome-hook` | `post_tool_call` hook, `tool_name == "terminal"` | same parse of pytest summaries from the result text |
| `SessionEnd` → `librarian` | `on_session_finalize` / `on_session_reset` | **not** `on_session_end`: for general plugins that fires at every turn's finalization |
| `PreCompact` → `librarian` (chapter) | suite signal from Sophia's `on_pre_compress` | general plugins get no pre-compression hook; without Sophia, chapters fall back to session boundaries only |
| transcript file (`transcript_path`) | Hermes session store by `session_id`, or history cached from `post_llm_call` | assistant-only text for citation counting, as today |
| `claude -p … --model haiku` | `ctx.llm.complete(..., task="gemmery_librarian")` | general plugins have `ctx.llm`; register the aux task so the librarian runs on the local 9B |

Required refactor in Gemmery: split `prod/hooks.py` into pure functions
(`inject_text(store)`, `record_outcome(cmd, text)`, `run_librarian(store, tail, assistant_text, complete)`)
and thin front ends for Claude Code (stdin JSON, subprocess) and Hermes (hook kwargs, `ctx.llm`).

---

## 4. What the suite shares

1. **Source-ref format.** One string format for "where this came from", used by Sophia's
   `triple_sources` and by Gemmery's dossier citations:
   `hermes:<session_id>:<message_id>` · `url:<url>#<chunk>` · `file:<path>@<commit>` · `sophia:<triple_id>`.
   This is the only cross-plugin data contract.
2. **Signals, in process.** A tiny registry in suite core: Sophia emits `chapter_boundary(session_id, messages)`
   from `on_pre_compress` and `session_boundary(session_id)` from `on_session_end`; Gemmery subscribes.
   No-op when either plugin is absent.
3. **Model access.** One client, one priority queue on the shared 9B:
   decisions (highest) → extraction → librarian (lowest). The librarian is the least latency-sensitive
   work in the suite and yields to everything else.
4. **Credit semantics.** Same fold for both: append-only outcome events, current credit is a fold,
   failures debit 2x, pending ≠ 0. Sophia credits facts; Gemmery credits dossiers. Each keeps its own ledger.
5. **Presentation rules.** Numbers lead ("used 5, helped 4, credit +0.7"), abstain when silent,
   never last-write-wins between sources.
6. **One embedding model** — nomic via LM Studio. Gemmery's embedder interface accepts the suite
   client; its hashing embedder stays the no-server default.

---

## 5. Context budget per turn

| Source | When | Budget |
|---|---|---|
| Hermes MEMORY.md / USER.md | always | Hermes-managed (2,200 / 1,375 chars in your config) |
| Gemmery dossiers | system prompt, once per session | ≤ 4,000 chars |
| Sophia recall | appended to the user message each turn | target ≤ 3,000 chars; empty when the gate says "not found" |

---

## 6. Open questions

1. **Gemmery store scope on Hermes.** Today: `<project>/.gemmery-store`. On Hermes, many sessions
   have no project (gateway chats). Proposal: project store when the session `cwd` is inside a
   git repo, otherwise a profile store under `$HERMES_HOME/plugin-data/gemmery/`.
2. **Where rules found in conversation go.** Sophia's extraction will meet sentences like "always
   fix it where the state is produced". Proposal: Sophia tags them `advice` and skips extraction;
   the librarian sees them in the transcript anyway.
3. **Chapter signal payload.** Does the librarian want the about-to-be-compressed span (what
   Sophia receives) or the whole transcript tail? Today it reads the tail.
4. **Names.** Suite and core package names are placeholders.

---

## 7. Later

- **Credit for Hermes skills.** Hermes emits `on_skill_lifecycle` (use counts, reuse after patch).
  Gemmery could attach test outcomes to skill use, giving skills the win/loss record the curator
  lacks. Valuation only — the curator still owns the skills.
- **Goals as predictions.** Sophia's goal journal could emit outcome events that Gemmery credits
  (did the plan that the dossier recommended work?).

---

## 8. Order of work

1. Sophia M1–M2 (DESIGN.md). Suite core is extracted from Sophia as it is built: decider, client,
   credit fold, source refs, signals.
2. Gemmery refactor: IO split in `prod/hooks.py`, no behaviour change, Claude Code path still green.
3. Gemmery Hermes adapter on the mapping in §3, with `gemmery[hermes]` extra.
4. Cross-links: librarian cites Sophia source refs; chapter signal wired.
