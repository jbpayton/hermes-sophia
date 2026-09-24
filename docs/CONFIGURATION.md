# Configuration

Sophia reads the `memory.sophia` section of the active profile's `config.yaml`, on top of the defaults in [`hermes_sophia/config.py`](../hermes_sophia/config.py). You can set any key with:

```bash
hermes -p <profile> config set memory.sophia.<key> <value>
```

A typical profile:

```yaml
memory:
  provider: sophia
  memory_enabled: false          # optional: make Sophia the only memory
  user_profile_enabled: false
  sophia:
    embed_model: nomic-embed     # the identifiers `lms ps` shows
    decider_model: qwen35-9b
    sleep_model: qwen/qwen3.8-27b
    user_name: Joey
    agent_name: Hermes
```

## Models

| Key | Default | What it is |
|---|---|---|
| `lmstudio_url` | `http://127.0.0.1:1234` | LM Studio's OpenAI-compatible server |
| `lms_cli` | `~/.cache/lm-studio/bin/lms` | Used only by the sleep guard, through `lms ps --json` |
| `embed_model` | `text-embedding-nomic-embed-text-v1.5` | Embeddings. Sophia adds the nomic `search_query:` / `search_document:` prefixes |
| `decider_model` | `qwen/qwen3.5-9b` | Per-turn gate and night judgments. Runs with reasoning off, one prefill; Sophia reads only the first-token logprobs |
| `sleep_model` | `qwen/qwen3.8-27b` | Night work: context headers and fact extraction |
| `sleep_guard_models` | `[sleep_model]` | Before each call, the night run waits until these models are idle |

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
| `full_capture_contexts` | `primary`, `""` | Agent contexts captured in full. Other contexts (subagents, cron) record only a short event per task prompt: no conversation windows, no web reads |
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
