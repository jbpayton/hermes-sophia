---
name: memory
description: How to use Sophia's long-term memory tools — deep recall, structured queries, the memory wiki, notes and feedback.
---

# Sophia memory

Sophia is passive and associative. Before each of your replies it injects verbatim, dated evidence it
judged relevant — or nothing. It never asks, speaks or acts on its own. Everything below is deliberate.

## When to call which tool

- **sophia_recall** — the injected memories aren't enough: you need older detail, everything about a
  topic, or how something used to be (`history: true` shows superseded facts with the dates they held).
- **sophia_query** — counts, lists and date ranges: "how many times…", "list every…", "what happened
  between X and Y". `spans_type` aggregates typed values (e.g. money spent, with `text` as a filter).
- **sophia_browse** — Mindscape, the memory wiki the night builds: `entity` pages, `timeline` for a date phrase, `recent` (not yet
  consolidated), `sources` (pages learned from), `changes` (what last night learned or superseded).
- **sophia_remember** — keep a note the user asks you to remember; or, with `item_id` + `verdict`,
  tell memory a recalled item was `helpful` or `wrong`. Feedback is the strongest signal memory gets.
- **sophia_ingest** — learn a document you obtained outside the web tools (web pages are captured
  automatically).

## Reading injected memory

- Dates are when something was said. Facts may carry `planned`, `unconfirmed` (a plan whose date has
  passed without evidence it happened), `habitual`, `hypothetical`, `negated`, or `reported`.
- Lines marked "assistant said" are your own earlier words — weaker evidence than the user's.
- If memory is silent, say you don't know rather than guessing.
