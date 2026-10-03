# Sophia

<p align="center"><img src="docs/img/hero.webp" width="100%" alt="hermes-sophia — memory for Hermes Agent: Sophia and the Hermes Agent mascot at a desk, working over a glowing graph of memories"></p>

**Memory for [Hermes Agent](https://github.com/NousResearch/hermes-agent) that brings up what's relevant before every reply, and tidies itself up while you sleep.** It runs on your own machine, with local models.

## What you get

Hermes already remembers. Its own memory is two short notes the agent keeps and a keyword search over every past conversation. It also ships eight memory plugins, and several are strong: Hindsight's time-aware entity graph, Honcho's model of the user, Supermemory's versioned facts, and OpenViking's file tree that records tool calls. [They're all compared here](docs/COMPARISON.md#hermess-memory-side-by-side).

Sophia takes a different path:

- **A graph that assembles itself.**
  - Each night, people, places and things are pulled from what was said, and facts are linked to the exact lines they came from.
  - Nobody declares a schema. Relations that recur become structure, and Sophia learns from its own history which ones hold one value at a time. A new home replaces the old one; a new friend doesn't replace an old one.
- **Semantic recall.**
  - Every line, fact and task card sits in vector indexes. Recall fuses them with keyword search, dates, and a hop through the graph, so a question about "Sam's sister" can reach where Lily lives.
  - At night, short replies are re-embedded with what they refer to, so a bare "yes" can be found by what it agreed to.
- **The actual words, not a rewrite.** What reaches the agent is what was said, with its date. Every other plugin injects text an LLM wrote.
- **It knows when to stay out of it.** A small model reads each message and decides whether memory bears on it, and "nothing" is a common answer. Other plugins use a similarity cut-off, or add something every turn.
- **Nothing generated when saving.** A message is stored as it was said, with one embedding (the agent's own replies also get a one-token check). The heavy model work happens at night on your GPU. The night also tests its own recall and repairs what it misses.
- **Time and change.** When something was said, when it happens, and what replaced what, all journaled and undoable. Plans whose date passed without word are marked as unconfirmed.
- **What the agent did.** Every tool call is logged, and each task gets a card: the steps that worked, the dead ends, and how it turned out.
- **See it all, and fix it.** The **Sophia** tab in the Hermes dashboard, on a desktop or a phone, shows:
  - the graph;
  - **Mindscape**, a page for each person, place and thing;
  - why each reply got the memory it got.

![The Sophia tab's graph: everything Silas has talked about, grouped into clusters, with a key to what the circles, lines and outlines mean](docs/img/dashboard/graph.webp)

<sub>Screenshots use the synthetic "Silas" life from the <a href="https://github.com/jbpayton/almanac">Almanac</a> benchmark.</sub>

### See it in a minute

<a href="docs/video/sophia-explainer.mp4"><img src="docs/video/sophia-explainer-preview.webp" width="100%" alt="An animated tour: a conversation saved word for word; a check before each reply that adds nothing to a general question and the dated original lines to a personal one; a night that builds a graph, marks what changed and which plans passed, and quizzes itself; the Sophia tab; and where it's headed"></a>

<sub>A silent one-minute tour, with the same synthetic data. [Full-quality MP4](docs/video/sophia-explainer.mp4).</sub>

### How it compares

A memory provider puts text into the agent's prompt before each reply, and saves each conversation as it goes. The table compares how each option does that, as Hermes runs it. Sources and details are in [the full comparison](docs/COMPARISON.md#hermess-memory-side-by-side).

| | What it adds before each reply | Leaves memory out when it isn't needed | AI work when saving a message | Tracks what changed | Remembers what the agent did | Where it runs |
|---|---|---|---|---|---|---|
| **Sophia** | The original lines, with dates | ● A model decides | Only an embedding; the rest overnight | ● | ● | Your machine |
| Hermes built-in | Both notes, every time | ○ | The agent writes notes when it chooses | ○ | ◐ Skills | Hermes |
| Holographic | Top 5 keyword matches | ◐ | None: the agent adds facts | ○ | ○ | Your machine |
| Mem0 | Top 10 extracted facts | ◐ Similarity cut-off | An LLM, every turn | ◐ | ○ | Cloud, or your machine |
| Honcho | Summaries and a model of you | ○ | An LLM, every turn | ◐ | ○ | Cloud, or your server |
| Supermemory | Up to 10 extracted memories | ◐ Similarity cut-off | An LLM, every turn | ● | ○ | Cloud, or your machine |
| Hindsight | Consolidated observations | ○ | An LLM, every turn | ● | ◐ | Cloud, or your machine |
| OpenViking | Your profile, then the top matches | ◐ Similarity cut-off | An LLM, each session | ◐ | ● | Your server, or hosted |
| ByteRover | An answer from its knowledge tree | ○ | An LLM, every turn | ◐ | ○ | Your machine, plus an LLM |
| RetainDB | Profile, matches and a written answer | ◐ | An LLM, on its server | ◐ | ○ | Cloud, or your server |

● yes · ◐ partly · ○ no

**Reading the table:**
- **What it adds before each reply:** the text that lands in the agent's prompt. "Extracted" and "summaries" mean an AI's rewording of what you said, not your words.
- **Leaves memory out when it isn't needed:** many messages need nothing about you ("what's the capital of Australia?"), and irrelevant memory in the prompt can mislead the agent.
  - ●: a model reads the message and decides whether memory applies.
  - ◐: memory is left out only when nothing is similar enough. Similarity can't tell an answer from a near-miss, so a near-miss still gets in.
  - ○: something is added every turn.
- **AI work when saving a message:** whether an AI model processes every message as it's saved. That takes time and, on a hosted service, money on every turn. Sophia saves the words with one embedding (a numeric fingerprint used for search), and does the rest overnight on your own GPU.
- **Tracks what changed:** whether it knows that a newer fact replaced an older one ("moved from Portland to Denver") and keeps the history.
- **Remembers what the agent did:** whether the agent's tool calls (commands run, pages read, files written) are kept, so it can reuse what worked.

Where others are ahead:
- **Honcho** models who you are.
- **Several plugins** share memory across users, teams and tools.
- **Every other plugin** has a hosted option, so there's nothing to run.
- **Sophia** is a v0.1 prototype that needs a GPU for good results.

### Benchmarks, briefly

On held-out data, with local models reading and judging:
- **LongMemEval-S:** 0.802 (Qwen3.5-9B).
- **LoCoMo:** 0.869 with the agent using Sophia's tools (Qwen3.8-27B), level with that model reading the whole conversation.
- **Almanac v0.2**, held-out lives: 0.957 (9B) and 0.996 (27B).

Other memories publish LongMemEval scores of about 79–94. They use answering models many times larger, their own harnesses and different judges, so the numbers don't line up directly. Stronger models have raised Sophia's scores at every step we measured; that and the time and cost side are in [BENCHMARKS.md](docs/BENCHMARKS.md#in-short).

[Almanac](https://github.com/jbpayton/almanac) is our own benchmark, for what the standard ones don't ask of an always-on memory: staying quiet when nothing's needed, "you never told me", telling a near-miss from an answer, and ignoring instructions planted in a web page. It was written alongside Sophia, so read it as a list of requirements, not independent proof.

## Quick start

**You need:**
- Hermes Agent;
- a local model server that speaks the OpenAI API: [llama-server](https://github.com/ggml-org/llama.cpp), [vLLM](https://github.com/vllm-project/vllm), [LM Studio](https://lmstudio.ai) or similar;
- three models on that server:

| Job | Recommended |
|---|---|
| Embeddings | `nomic-embed-text-v1.5` (about 80 MB) |
| The check before each reply | Qwen3.5-9B, Q4, reasoning off |
| Night work | Qwen3.8-27B, or the same 9B |

**1. Install** the plugin, and pick it as your memory:

```bash
git clone https://github.com/jbpayton/hermes-sophia
ln -s "$PWD/hermes-sophia/hermes_sophia" ~/.hermes/plugins/sophia
hermes memory setup        # pick "sophia"
```

Setup asks for:
- your name and the agent's;
- your server's URL and type (`openai` for llama-server, vLLM and most others);
- a model for each job.

For a named profile, link into `~/.hermes/profiles/<name>/plugins/` and add `-p <name>` to every command.

**2. Talk to your agent** as usual. Memory starts with the first message.

**3. Let it sleep.** Nothing is scheduled for you. Add a nightly run, for example at 3:30:

```cron
30 3 * * * hermes sophia sleep >> ~/.hermes/logs/sophia-sleep.log 2>&1
```

The night waits while you're chatting, and yields rather than competing with you.

**4. Watch it.** Enable the plugin's dashboard backend in `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - sophia
```

Then run `hermes dashboard` and open **Sophia**.

<p><img src="docs/img/dashboard/page.webp" width="49%" alt="A Mindscape page: what's believed about Spokane, each fact with the words it came from"> <img src="docs/img/dashboard/recall.webp" width="49%" alt="One recall: how the check read the message, and the lines that went into the prompt"></p>

## What it looks like

A plan that changes, across fresh chats:

```text
chat 1   You:     For the Yosemite trip I'm bringing my Fujifilm X-T5, and Sam is coming along.

chat 2   You:     Change of plans: I'm bringing the Sony A7 IV instead, the Fujifilm's sensor is acting up.

night    Sophia:  "Joey is bringing the Fujifilm X-T5" is replaced by "the Sony A7 IV"   (journaled; undoable)

chat 3   You:     Which camera am I taking on the Yosemite trip?
         Agent:   The Sony A7 IV. You'd planned on the Fujifilm, but switched because its sensor
                  was acting up.
```

Sophia was the only link between the chats. This is condensed; the verbatim run is in [How it works](docs/HOW-IT-WORKS.md#what-it-looks-like-across-sessions).

## Learn more

| Page | What's in it |
|---|---|
| [How it works](docs/HOW-IT-WORKS.md) | What the agent sees and how the check decides, the memory tools, task memory, the nightly run, and every command |
| [The Sophia tab](docs/DASHBOARD.md) | Starting it (including on a phone), every view, the graph and its clusters, correcting memory, settings, troubleshooting |
| [Configuration](docs/CONFIGURATION.md) | Every setting, and serving the models faster |
| [Benchmarks](docs/BENCHMARKS.md) | LongMemEval, LoCoMo and Almanac: protocol and results |
| [Comparison](docs/COMPARISON.md) | How Sophia compares with other agent memories |
| [Design](docs/DESIGN.md) | The reasoning behind it, and what's built so far |
| [Story](docs/STORY.md) | How it got here: the research, the dead ends, and the bugs only real use found |
| [Continuity](docs/CONTINUITY.md) | Where it's going: an agent that keeps going between messages, starts conversations, and sets its own goals |

## Status

A working prototype (v0.1), tested end to end inside Hermes v0.21.4. It has been a live agent's memory since 2026-09-28.

On benchmarks with local models:
- **LoCoMo:** when the agent also uses the memory tools, the 27B scores 0.869, on par with giving it the whole conversation (0.853).
- **LongMemEval-S:** 0.802 on all 500 questions, with the 9B and memory injection alone.

Details are in [BENCHMARKS.md](docs/BENCHMARKS.md).

## Development

```bash
pip install -e ".[test]"
pytest -q        # 127 tests against a fake model server; no GPU needed
```

The code is in `hermes_sophia/`, including the dashboard tab in `hermes_sophia/dashboard/` (plain JS, no build step). `hermes_continuity/` is the companion plugin that lets the agent keep going between messages (an early version; see [Continuity](docs/CONTINUITY.md)). The benchmark harness is in `bench/`, and the experiments behind the design are in `research/`. The animated tour is one HTML page, rendered to video by `scripts/explainer/build.py --video`.

## Lineage

Sophia is a clean-sheet redesign that combines two earlier projects:
- [SophiaAMS](https://github.com/jbpayton/SophiaAMS): associative triple memory, its memory-graph view, and the original Mindscape navigator.
- [Gemmery](https://github.com/jbpayton/gemmery): credit-earning memory, and the finding that retrieval over the raw record beats write-time summaries.

Not to be confused with [Sophia: A Persistent Agent Framework of Artificial Life](https://arxiv.org/abs/2512.18202) (Sun, Hong and Zhang, 2025), a separate project.

## License

MIT
