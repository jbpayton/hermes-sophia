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
- **It knows when to stay out of it.** A small model reads each message and decides whether memory bears on it, and "nothing" is a common answer. Other plugins use a similarity floor or no gate at all.
- **Nothing generated when saving.** A message is stored as it was said, with one embedding (the agent's own replies also get a one-token check). The heavy model work happens at night on your GPU. The night also tests its own recall and repairs what it misses.
- **Time and change.** When something was said, when it happens, and what replaced what, all journaled and undoable. Plans whose date passed without word are marked as unconfirmed.
- **What the agent did.** Every tool call is logged, and each task gets a card: the steps that worked, the dead ends, and how it turned out.
- **See it all, and fix it.** The **Sophia** tab in the Hermes dashboard, on a desktop or a phone, shows:
  - the graph;
  - **Mindscape**, a page for each person, place and thing;
  - why each reply got the memory it got.

![The Sophia tab's graph: everything Silas has talked about, grouped into clusters, with a key to what the circles, lines and outlines mean](docs/img/dashboard/graph.webp)

<sub>Screenshots use the synthetic "Silas" life from the <a href="https://github.com/jbpayton/almanac">Almanac</a> benchmark.</sub>

### How it compares

● yes · ◐ partly · ○ no. Each plugin is described as Hermes runs it, in [the full comparison](docs/COMPARISON.md#hermess-memory-side-by-side) with sources.

| | Added before each reply | Can add nothing | Model work when saving | Change over time | Agent's tool calls | Runs on |
|---|---|---|---|---|---|---|
| **Sophia** | The original lines, dated | ● A model decides | An embedding; the rest at night | ● | ● | Your machine |
| Hermes built-in | Both notes, always | ○ | The agent writes notes | ○ | ◐ Skills | Hermes |
| Holographic | Top 5 keyword matches | ◐ | The agent adds facts | ○ | ○ | Your machine |
| Mem0 | Top 10 extracted facts | ◐ Score floor | LLM, each turn | ◐ | ○ | Cloud, or your machine |
| Honcho | Summaries and a model of you | ○ | LLM, each turn | ◐ | ○ | Cloud, or your server |
| Supermemory | Up to 10 extracted memories | ◐ Score floor | LLM, each turn | ● | ○ | Cloud, or your machine |
| Hindsight | Consolidated observations | ○ | LLM, each turn | ● | ◐ | Cloud, or your machine |
| OpenViking | Your profile, then top hits | ◐ Score floor | LLM, each session | ◐ | ● | Your server, or hosted |
| ByteRover | An answer from its tree | ○ | LLM, each turn | ◐ | ○ | Your machine, plus an LLM |
| RetainDB | Profile, results and an answer | ◐ | LLM, on the server | ◐ | ○ | Cloud, or your server |

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

## Status

A working prototype (v0.1), tested end to end inside Hermes v0.21.4. It has been a live agent's memory since 2026-09-28.

On benchmarks with local models:
- **LoCoMo:** when the agent also uses the memory tools, the 27B scores 0.869, on par with giving it the whole conversation (0.853).
- **LongMemEval-S:** 0.802 on all 500 questions, with the 9B and memory injection alone.

Details are in [BENCHMARKS.md](docs/BENCHMARKS.md).

## Development

```bash
pip install -e ".[test]"
pytest -q        # 91 tests against a fake model server; no GPU needed
```

The code is in `hermes_sophia/`, including the dashboard tab in `hermes_sophia/dashboard/` (plain JS, no build step). The benchmark harness is in `bench/`, and the experiments behind the design are in `research/`.

## Lineage

Sophia is a clean-sheet redesign that combines two earlier projects:
- [SophiaAMS](https://github.com/jbpayton/SophiaAMS): associative triple memory, its memory-graph view, and the original Mindscape navigator.
- [Gemmery](https://github.com/jbpayton/gemmery): credit-earning memory, and the finding that retrieval over the raw record beats write-time summaries.

## License

MIT
