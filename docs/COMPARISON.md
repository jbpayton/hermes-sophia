# How Sophia compares

This is a reality check, written in September 2026, against the best-known graph and agent memories. In short: Sophia's *representation* has converged with the state of the art. What distinguishes it is *behaviour*:
- when the model work happens;
- that it decides whether to inject anything at all;
- a night that tests and repairs its own recall.

Sophia has no benchmark number yet (see [Benchmarks](#benchmarks)), so none of this is a claim about accuracy.

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

1. **No model calls when something is saved.** Graphiti, Mem0 and Hindsight run LLM extraction as each message is saved. Sophia stores the words and their embeddings immediately and extracts at night on a local model. Letta shares the night idea, but for memory blocks rather than a fact graph.
2. **A check that can inject nothing.** The providers we checked rank memories and inject the top few. For example, Hermes's bundled Holographic provider injects its top 5 facts by trust score. Sophia measured that similarity can't separate an answer from a near-miss (unanswerable near-misses reached 0.78 against 0.80 for real answers). So a small model reads one token's probabilities to say yes or no before anything is injected. Rerankers and Self-RAG's "should I retrieve?" step are relatives.
3. **Its own words can't poison it.** The agent's replies are checked as they are captured. A reply that states facts about you that nothing in the turn supported is kept out of recall. This came from a real failure: in testing, an agent invented where someone's sister lived, and the next session recalled that as memory.
4. **A memory that tests itself.** Each night Sophia:
   - replays the day's injections to judge which ones were used;
   - writes its own questions about new facts, and repairs whatever recall misses;
   - uses those labels to calibrate the check.
   Hindsight's reflect step and Letta's consolidation reorganize memory, but we didn't find either grading its own recall.
5. **Emergent schema with learned exclusivity.** Graphiti's custom types are declared up front. Sophia promotes relations that recur, and learns from its own history whether a relation holds one value at a time (and so supersedes older values) or several.
6. **Footprint.** SQLite, numpy and a local model server. No graph database, no cloud. The night waits for your chat model to be idle.

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

The comparison that matters is accuracy on shared benchmarks: LongMemEval and LoCoMo. The harness is in [`bench/`](../bench/). Results will be added here with their exact setup: reader model, judge model, split and sample size. Numbers from a local 9B reader and judge are not directly comparable to published numbers that use GPT-4o, and are labelled as such.
