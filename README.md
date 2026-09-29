# Sophia

<p align="center"><img src="docs/img/hero.webp" width="100%" alt="hermes-sophia — memory for Hermes Agent: Sophia and the Hermes Agent mascot at a desk, working over a glowing graph of memories"></p>

**Memory for [Hermes Agent](https://github.com/NousResearch/hermes-agent) that brings up what's relevant before every reply, and tidies itself up while you sleep.** It runs on your own machine, with local models.

## What it does

- **Remembers the actual words.** Conversations are kept verbatim, not summarized. Before each reply, Sophia checks whether anything it remembers bears on your message. If something does, the agent sees the exact past lines, with their dates. If nothing does, it adds nothing. You never have to say "remember this".
- **Sleeps on it.** Each night it works out who and what you talk about. It notes what changed ("moved from Portland to Denver") and which plans have passed their date. It also writes up what the agent did, and whether it worked.
- **Lets the agent look things up.** Tools let the agent dig deeper, count and list things, and read a page about any person, place or thing.
- **Shows you everything, and lets you fix it.** The **Mindscape** tab in the Hermes dashboard shows what memory is doing, what the night changed, and what went into each reply. It works on your phone too.

![Mindscape's Overview: what memory is doing right now, what last night did, and how recall behaved this week](docs/img/mindscape/overview.webp)

<sub>Screenshots use the synthetic "Silas" life from the <a href="https://github.com/jbpayton/almanac">Almanac</a> benchmark.</sub>

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

Then run `hermes dashboard` and open **Mindscape**.

<p><img src="docs/img/mindscape/graph.webp" width="49%" alt="The graph, with one person's facts spread out around them"> <img src="docs/img/mindscape/recall.webp" width="49%" alt="One recall: how the check read the message, and the lines that went into the prompt"></p>

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
| [The Mindscape tab](docs/MINDSCAPE.md) | Starting it (including on a phone), every view, correcting memory, troubleshooting |
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
pytest -q        # 88 tests against a fake model server; no GPU needed
```

The code is in `hermes_sophia/`, including the dashboard tab in `hermes_sophia/dashboard/` (plain JS, no build step). The benchmark harness is in `bench/`, and the experiments behind the design are in `research/`.

## Lineage

Sophia is a clean-sheet redesign that combines two earlier projects:
- [SophiaAMS](https://github.com/jbpayton/SophiaAMS): associative triple memory, its memory-graph view, and the original Mindscape navigator.
- [Gemmery](https://github.com/jbpayton/gemmery): credit-earning memory, and the finding that retrieval over the raw record beats write-time summaries.

## License

MIT
