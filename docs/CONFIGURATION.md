# Configuration

Sophia reads the `memory.sophia` section of the active profile's `config.yaml`, on top of the defaults in [`hermes_sophia/config.py`](../hermes_sophia/config.py).

There are three ways to set a value:

- **`hermes -p <profile> memory setup`**, then pick sophia. It always asks for the basics: names, the default server, and a model for each job. Then it asks two gate questions, whose answers are saved and only affect what setup shows:
  - `server_layout: shared | per-job` reveals the per-job server settings;
  - `show_advanced: no | yes` reveals every tuning setting below.
- **The Hermes dashboard**, which shows the same fields.
- **Directly:**

  ```bash
  hermes -p <profile> config set memory.sophia.<key> <value>
  ```

Values typed into setup arrive as text and are converted to the right type: numbers stay numbers, and lists are comma-separated. A value that can't be converted is ignored with a warning, and the default is used.

A typical profile:

```yaml
memory:
  provider: sophia
  memory_enabled: false          # optional: make Sophia the only memory
  user_profile_enabled: false
  sophia:
    embed_model: nomic-embed     # the identifiers your server shows (`lms ps`)
    decider_model: qwen35-9b
    sleep_model: qwen/qwen3.8-27b
    user_name: Joey
    agent_name: Hermes
```

## Models and servers

Sophia has three jobs. Each one has a model and, optionally, its own server:

| Job | Model key | Server keys | What it does |
|---|---|---|---|
| Embeddings | `embed_model` (default `text-embedding-nomic-embed-text-v1.5`) | `embed_url`, `embed_api` | Every embedding, day and night. Sophia adds the nomic `search_query:` / `search_document:` prefixes |
| Decider | `decider_model` (default `qwen/qwen3.5-9b`) | `decider_url`, `decider_api` | The per-turn check whether to inject. One prefill; only the first token's probabilities are read |
| Night | `sleep_model` (default `qwen/qwen3.8-27b`) | `sleep_url`, `sleep_api` | Context headers, fact extraction, and the night's judgments (sorting, supersession, replay, rehearsal) |

- **`lmstudio_url`** (default `http://127.0.0.1:1234`) is the default server. A job whose `*_url` is `default` or blank uses it.
- **`*_api`** is the server type:

  | Type | For | How Sophia talks to it |
  |---|---|---|
  | `lmstudio` (default) | LM Studio | Logprobs come from `/v1/responses`, because LM Studio's chat endpoint returns none. Reasoning is switched off with `reasoning_effort: none`. Busy status comes from `lms ps` |
  | `openai` | llama-server, vLLM, or any OpenAI-compatible server whose chat endpoint returns `logprobs` | Chat completions with `logprobs` / `top_logprobs`. Reasoning is switched off with `chat_template_kwargs: {enable_thinking: false}`. Busy status comes from llama-server's `/slots` |

- Jobs that share a server share one client. `hermes sophia status` shows where each job runs.

Example: the decider pinned to its own GPU under llama-server, which was about 1.35× faster in the speed tests, while everything else stays on LM Studio:

```yaml
    decider_url: http://127.0.0.1:8081
    decider_api: openai
    decider_model: qwen35-9b      # whatever --alias the server was started with
```

**Pick a capable decider.** The check is only as good as the model behind it. The Qwen3.5-9B blocked "What's the capital of Australia?" at 0.45. A Qwen3.5-0.8B passed it at 0.90, which would inject noise into every turn.

### The night's busy guard

| Key | Default | |
|---|---|---|
| `sleep_guard_models` | `[sleep_model]` | Before each call, the night waits until these LM Studio models are idle |
| `lms_cli` | `~/.cache/lm-studio/bin/lms` | Used to read LM Studio's model status |

When the night server is of type `openai`, the night also waits while that server reports a busy slot. A status that can't be read counts as idle.

To run one night on a different model or server:

```bash
hermes sophia sleep --model M [--url U --api openai]
```

## Identity

| Key | Default | |
|---|---|---|
| `user_name` | `user` | Speaker label for your lines; also the subject of extracted facts |
| `agent_name` | `assistant` | Speaker label for the agent's lines. These rank below yours and are never mined for facts |

## Awake: capture

| Key | Default | |
|---|---|---|
| `window_sentences` / `window_chars` | 3 / 480 | Window size for the raw record |
| `code_block_chars` | 800 | Long code blocks become one truncated `code` window |
| `capture_tools` | `web_extract`, `browser_snapshot`, `browser_navigate` | Tool results that are captured as external sources |
| `never_capture_substrings` | `vault`, `credential`, `secret`, `password` | A tool whose name contains any of these is never captured |
| `test_tools` | `terminal`, `shell`, `bash`, `run_command`, `execute_code` | Their output is scanned for pytest outcomes |
| `full_capture_contexts` | `primary` | Agent contexts captured in full. Other contexts (subagents, cron) record only a short event per task prompt: no conversation windows, no web reads |
| `echo_threshold` | 0.5 | Shingle containment above which a reply that just repeats injected memory is fenced off as an echo |

## Awake: recall and injection

| Key | Default | |
|---|---|---|
| `recall_k` | 20 | Number of candidates fetched |
| `gate_top` | 10 | Number of candidates the gate looks at |
| `skip_gate` | 0.82 | At or above this top-1 cosine, inject without asking the decider (measured; see `research/embed_thresholds.py`) |
| `gate_threshold` | 0.5 | Decider probability needed to inject |
| `gate_permutations` | 1 | Option orders averaged per gate decision. With 2, both orders are averaged, cancelling position bias at twice the cost |
| `junk_floor` | 0.5 | Candidates below this cosine are never shown to the gate |
| `inject_chars` | 3000 | Size cap for the injected block |
| `inject_relative_floor` | 0.15 | Only inject items within this similarity of the top item |
| `recency_bonus`, `fts_bonus`, `type_bonus` | 0.01, 0.03, 0.02 | Ranking nudges |
| `assistant_penalty`, `max_assistant_items` | 0.06, 2 | Keep the agent's own restatements from crowding out your words |
| `question_penalty` | 0.04 | A bare earlier question carries no facts |

## Asleep

| Key | Default | |
|---|---|---|
| `sleep_max_wait_s` | 900 | How long a night run waits for a busy guarded model before yielding |
| `sleep_poll_s` | 10 | How often it checks while waiting |
| `sleep_session_windows` | 40 | Windows per contextualize call |
| `promote_min_instances` / `promote_min_sessions` | 5 / 2 | Evidence needed before an emergent relation is promoted to canonical |
| `page_min_facts` | 3 | Minimum facts about an entity before it gets a wiki page |
| `calibration_min_labels` | 50 | Gold labels needed before decider temperatures are fitted |

## Timeouts (seconds)

`embed_timeout` 5, `decider_timeout` 8, `sleep_call_timeout` 300.

Hermes gives an external provider's prefetch 8 s in total, so keep `embed_timeout + decider_timeout` comfortably under that on slow hardware. When a model call fails or times out, Sophia records a degraded mode, which `sophia status` shows, and carries on without that model:

- with no embeddings, recall falls back to keyword search;
- with no decider, nothing is injected;
- capture stores windows without vectors, and the next night fills them in.
