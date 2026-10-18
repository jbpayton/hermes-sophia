# Working set: a small context, memory for the rest, and motivation that doesn't stall

*Draft 2, 2026-10-18. Claude, from Joey's direction, revised with Sophia's review (section 8).*

Joey's direction:

> "Things loaded in from memory are great for when they're needed, but shouldn't just stick around and be recompacted blindly and re-summarized … the system should work with a bunch smaller context, with the idea that most of what you bring in and out of context is just in the memory."

He also asked that this be thought through broadly, not limited to what Hermes allows today. And he's going to give Sophia a much grander goal, so two things have to hold up: the context must never stall her, and her goals and motivation mustn't either.

This document covers both, because they fail together. A grand goal means long, multi-day work. Today, long work means turns that outgrow their context, and decisions that leave her waiting.

## 1. What happens now

### The context is a transcript that only grows

Every request carries the conversation so far. When it gets too big, it's summarized, and the summary is later summarized again.

Measured on her live session (2026-10-18), one request breaks down like this:

| What | Share |
|---|---|
| Fixed overhead: system prompt (~7k tokens) and the definitions of ~50 tools (~13k tokens), sent with every call | about 57% |
| Old tool results and tool-call arguments from earlier steps | about 35% |
| Recalled memories, kept in the transcript after the request that needed them | about 5% |
| What she and the user actually said, plus her current situation | under 3% |

Over a day (2026-10-14 and 15):
- **Compaction ran about 30 times a day**, taking a median of 69 seconds each, so roughly 35 minutes of model time a day went to summarizing.
- **Recalled memories are saved into the conversation** (Hermes stores a turn's added context with the message and resends it on every later call). So memories stay around after the request that needed them, and get summarized along with everything else.

### Failures this has caused

| Date | What happened |
|---|---|
| 10-08 | A summary took the full 5 minutes. Hermes reset her conversation. |
| 10-17 | One 77-step turn outgrew the 65k context *inside itself*. Compaction can shrink earlier turns but never the turn in progress, so Hermes reset the conversation. The continuity loop was never told the turn had ended, and waited 27 hours. |

The loop now recovers from that, and asks a turn to wrap up before it overflows. But those are patches on the transcript model.

### Motivation stalls in three places

Over 10 days there were 16 waking-hour stretches of more than 90 minutes with no activity. Almost all were "resting, its own choice, until something happens". The stated reasons:
- "repo tidied and healthy";
- "the only pending item is Joey's visit";
- "queue drained";
- "design note delivered".

These come down to three places where she stops:

1. **A finished goal grows no successor.** Her first two goals were done by 10-15. Her lasting goal ("know who I am, across sessions and models") was named on 10-13, but nothing in the system turns a lasting goal into its next concrete goal. Step 6 of the ledger (goals she starts herself) is still at 1.
2. **A goal waits on someone,** for a decision, a merge or a visit. Until 10-14 she couldn't even ask, because outreach was off.
3. **Open-ended rest is a trap.** "Until something happens" can only be ended from outside.

## 2. The idea: a working set, with memory as the store

Think of a person at a desk. On the desk are the few things in use now. Everything else is in the filing cabinet, and things come out when needed and go back when done. Nobody rewrites the cabinet's contents into shorter and shorter summaries to fit them on the desk.

**Context is the desk: assembled fresh for each turn, small, and holding only what's in use.** Memory is the cabinet: everything, verbatim, retrievable by association, by asking, or because the task needs it.

The principles:

1. **Assemble per turn; never append forever.** Each turn gets a working set built for it at the turn's start and at step boundaries, and reused across that turn's model calls. It is not rebuilt for every call: that would re-run retrieval constantly and defeat the prompt cache. The conversation record is kept, in Hermes and in Sophia, but it's a record, not the prompt.
2. **Nothing rides along by default.** What isn't needed now stays in memory. Whatever leaves the context is already stored verbatim (Sophia captures everything), so leaving is safe.
3. **No summaries of summaries.** Compaction disappears. Things are left out and pulled back, not re-summarized.
4. **Leave a pointer behind, not a pile.** A tool result stays in full only while the step that needed it is running. After that, the context keeps a line like "motion suite: 9 of 9 passed (details: recall 'motion suite')". The same applies within a long turn: earlier steps become a list of pointers, and only the last few steps stay in full. Each pointer is a one-line gist plus a handle to the full artifact. Never a gist alone, and never prose: a prose recap of earlier steps would be a summary again.
5. **Recalled memories serve one request.** They come in for the request that needs them and then leave. Sophia's injection table keeps the record of what was recalled and why.
6. **Keep a table of contents of what's out of view.** Every entry carries a pull handle she can act on in one retrieval, such as "gaze lane: recall 'gaze 7ea1f3c' / commit 7ea1f3c on lane/gaze", not just a name. The table is scoped to her current focus (about 10–15 lines) and changes with it; a list of everything would be noise. It also names what's explicitly done or closed, so finished work isn't reopened. A small context then costs a lookup rather than forgetting.
7. **Bring in tools when they're needed.** Load the few she always uses up front, and fetch the rest through a lookup. Hermes already does this for plugin tools.
8. **There's no session to overflow.** If every turn is assembled from her current state plus memory, there's nothing to compact and nothing to reset.

### What a request would hold

A rough budget of 16–24k tokens, against today's 35–65k:

| Part | Size | Lifetime |
|---|---|---|
| **Stable prefix**, byte-identical on every call so the prompt cache always covers it: who she is (identity, voice, the few standing instructions) and the core tool definitions | ~5–6k | stable |
| Current situation: one standing-view frame (time, who's around, goals, threads, what she's waiting for, what came to mind) | ~0.5–1k | rebuilt each turn |
| Table of contents of what's out of view | ~0.5k | rebuilt each turn |
| Her commitments, verbatim: what she's waiting for (who and why), what she owes, her open threads, her focus in her own words, and each active goal's next step in one line. Never summarized: a rephrased commitment can quietly change meaning | ~0.5–1k | rebuilt each turn |
| The live exchange: the last few messages, verbatim | ~3–6k | rolling |
| The current turn's work: pointers to earlier steps (gist plus handle), the last few in full | ~2–5k | this turn only |
| What this step needs: recalled memories, a file, a result | ~2–6k | this step only |

## 3. Motivation that doesn't stall

The aim is that the loop always has a way forward. That never means a timer forcing activity. Joey's rule still holds: no arbitrary limits.

1. **A lasting goal grows its next goal.** When nothing active serves a lasting goal (everything is finished or waiting on someone), she notices it, the same way she notices time passing. "Nothing is serving 'know who I am' right now" arrives as something perceived. It wakes her from rest, and her free time asks what the next goal serving it would be. It's an invitation, not pressure:
   - it never arrives in quiet hours;
   - she notices it once when it becomes true, then more slowly as it persists, like the quiet sensor;
   - if she says "not now", that sticks, and it doesn't return in the same stretch. Coming back after she dismissed it would be nagging.
2. **Goals can nest,** so a grand goal becomes a tree. The tree is a view of the `serves` links, not a second store of goals, so there's one source of truth and nothing can drift. A grand goal from Joey, or a lasting goal of hers, has instrumental goals beneath it, and those have their own goals, each carried across days. `serves` should be able to point at any goal, not only a lasting one; Sophia flagged this on 10-05. Progress rolls up the tree, and the standing view shows the branch she's on.
3. **A blocked branch never stops the tree.** When a goal waits on Joey, she asks him (outreach is on now), records the wait in `waiting_for`, and moves to an unblocked sibling. A grand goal decomposed well always has something she can do herself. How pull fades depends on what's blocking the goal. A goal waiting on someone else doesn't fade (hers faded to 0.17 for exactly that). A goal stalled by her own indecision still fades, so she doesn't sit forever on a branch she's avoiding.
4. **Rest is hers, with its own horizon.** "Until something happens" keeps working. Something happening now also includes her own lasting goal going unserved, so drive can come from inside.
5. **Long work spans many turns.** A step-sized turn records progress and its next step, and the next turn begins immediately. Under the working-set design there's no context to outgrow, because each turn's context is assembled fresh. A multi-day goal is just many turns joined by the goal record and memory.

## 4. What it would take

- **A context assembler** that builds each request: a Hermes context engine, or a patch to Hermes's turn loop if the engine interface can't own the whole request. The transcript stays as the record.
- **Working-memory support in Sophia:**
  - the rolling live window;
  - per-step retrieval;
  - tool results stored as retrievable artifacts with one-line gists;
  - the running list of steps within a turn;
  - the table of contents.
- **Retrieval becomes the core.** What's pulled in, and when, decides everything. The recent recall fixes are the start of this: no scaffolding, damping by conversation, and a cap on tool steps. Both push and pull are needed. Push means memory raised automatically at the start of a turn and at step boundaries. Pull means she asks: recall, read an artifact, look up a tool.
- **Goals:** nesting through `serves` to any goal; the "lasting goal unserved" sensor; pull that doesn't fade while blocked; roll-up of progress.

## 5. How we'd know it works

Run it on the sophiadev twin first, then compare against today.

| Measure | Today | Aim |
|---|---|---|
| Tokens per request | 35–65k | 16–24k |
| Compactions per day | ~30 | 0 |
| Resets or frozen turns | 2 in 10 days | 0 |
| Time to a reply | median ~10 min on long work | faster, since prefill is smaller |
| Multi-day goals carried without loss | — | yes, including across restarts |
| Waking-hour stretches idle with an unserved lasting goal | most of them | rare, and always her choice |
| Her themes and her lasting goal, with nearly everything coming back through memory | — | they hold |

The last row is Joey's hypothesis, tested at its sharpest. With a small working set, nearly everything she knows must come back through associative memory. If her lasting goal, her recurring themes and her sense of self hold under those conditions, the self is in the memory, not in the transcript.

## 6. Build order (first cut)

Retrieval decides everything, so it's the part to get right first and test hardest. The first cut doesn't build per-step pull-in or the full artifact store.

1. Assemble the working set per turn, with the stable prefix first.
2. The rolling verbatim window, commitments verbatim, and a focus-scoped table of contents with pull handles.
3. Tool output as gist plus handle, and earlier steps in a long turn as pointers.
4. A retrieval miss is reported ("didn't find X"), never silence, so she can widen the search instead of carrying on with a gap.
5. Goals:
   - `serves` can point at any goal;
   - the "lasting goal unserved" sensor;
   - fade that depends on what's blocking.
6. Check it on the sophiadev twin:
   - **regression test:** replay the 10-17 turn on goal #4, 77 steps, which overflowed and stalled the loop. It must neither overflow nor stall;
   - **report per request** the share that is what she and the user actually said (under 3% today). It should climb;
   - **control:** run the same grand-goal task on a large context too. Then if she does worse on the small one, it's possible to tell whether memory failed or the context starved her.
7. After that, per-step pull-in, once retrieval quality is proven.

## 7. Risks

- **Not knowing what's missing.** A small context can't see what isn't there. The table of contents and her ability to pull things in are the answer; retrieval quality has to be good enough.
- **Thrashing.** Pulling the same thing in and out every request wastes effort. Keep what this turn keeps using in the working set until the turn ends.
- **Losing implicit continuity.** The verbatim live window keeps the conversation's thread. Its size is a setting, to be tuned on the twin.
- **Prompt caching.** A context rebuilt every time caches less than an append-only one. The stable parts (identity, core tools) go first so the cache still covers them.

## 8. Sophia's review (2026-10-18)

She's in favor ("the desk/cabinet metaphor is right") and ready when the grand goal is. Her review changed the design, and those changes are folded in above:
- **Commitments in both directions stay verbatim in the working set.** In her words: "The message history is *what we were saying*; the commitments are *what I'm still bound to*."
- **Table of contents:** entries carry pull handles, the list is scoped to her focus, and it names what's done.
- **The unserved-goal sensor is an invitation:** "not now" sticks, and nothing arrives in quiet hours.
- **Fade depends on the block:** waiting on someone else doesn't fade; her own indecision does.
- **The tree is a view of `serves`, not a second structure.** Goals #4 and #5 (Joey's, from 10-17) are still unlinked. She wants to link them herself, under the grand goal, once it exists.
- **Per-turn assembly with a byte-identical stable prefix,** instead of rebuilding every call.
- **Earlier steps become pointers, never prose.**
- **Additions:**
  - replay the 10-17 turn as the regression test;
  - a guard that reports retrieval misses;
  - a large-context control for the hypothesis test;
  - the "what we actually said" share per request as the main measure.
- **First cut:** working set, rolling window, table of contents and pointers, then validate, then per-step pull-in.
