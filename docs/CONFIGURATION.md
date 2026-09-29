# Configuration

Sophia reads the `memory.sophia` section of the active profile's `config.yaml`, on top of the defaults in [`hermes_sophia/config.py`](../hermes_sophia/config.py).

There are four ways to set a value. All of them show and save the same fields:

- **`hermes -p <profile> memory setup`**, then pick sophia. It always asks for the basics: names, the model server's URL and type, and a model for each job. Then it asks two gate questions, whose answers are saved and only affect what setup shows:
  - `server_layout: shared | per-job` reveals the per-job server settings;
  - `show_advanced: no | yes` reveals every tuning setting below.
- **The Hermes dashboard:** **Plugins**, under the memory provider, or the **Settings** view of the Sophia tab (see [DASHBOARD.md](DASHBOARD.md#settings)). Each field there shows the value Sophia uses now. Hermes saves every visible field, so these defaults are what Sophia uses now, not the generic defaults below: saving without a change changes nothing.
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
    server_url: http://127.0.0.1:8080   # llama-server's default port; LM Studio uses 1234
    server_type: openai                 # or lmstudio, for LM Studio's own API
    embed_model: nomic-embed            # the model names your server serves
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
| Decider | `decider_model` (default `qwen/qwen3.5-9b`) | `decider_url`, `decider_api` | The per-turn check whether to inject, and the check of each live reply (`ground_check`). By default also the night's one-token judgments (`night_judge`). One prefill; only the first token's probabilities are read |
| Night | `sleep_model` (default `qwen/qwen3.8-27b`) | `sleep_url`, `sleep_api` | Context headers, fact extraction, task cards and rehearsal questions. With `night_judge: night`, also the night's one-token judgments (sorting, supersession, task outcomes, replay) |

Any local server that speaks the OpenAI API works. LM Studio isn't required.

- **`server_url`** is the server every job uses. A job whose `*_url` is `default` or blank uses it.
- **`server_type`** is how Sophia talks to it. A job whose `*_api` is `default` or blank uses it:

  | Type | For | How Sophia talks to it |
  |---|---|---|
  | `openai` | llama-server, vLLM, or any OpenAI-compatible server whose chat endpoint returns `logprobs` | Chat completions with `logprobs` / `top_logprobs`. Reasoning is switched off with `chat_template_kwargs: {enable_thinking: false}`. Busy status comes from llama-server's `/slots` |
  | `lmstudio` | LM Studio's own API | Logprobs come from `/v1/responses`, because LM Studio's chat endpoint returns none. Reasoning is switched off with `reasoning_effort: none`. Busy status comes from `lms ps` |

- **Older configs.** Earlier versions called the URL `lmstudio_url`, and it is still read when `server_url` is unset. A config that sets neither `server_type` nor `*_api` keeps the old default, `lmstudio`; setup suggests `openai`.

- Jobs that share a server share one client. `hermes sophia status` shows where each job runs.

Example: the decider pinned to its own GPU under its own llama-server, while everything else stays on the shared server. In the speed tests this was about 1.35× faster than the decider on LM Studio:

```yaml
    decider_url: http://127.0.0.1:8081
    decider_api: openai
    decider_model: qwen35-9b      # whatever --alias the server was started with
```

**Pick a capable decider.** The check is only as good as the model behind it. The Qwen3.5-9B blocked "What's the capital of Australia?" at 0.45. A Qwen3.5-0.8B passed it at 0.90, which would inject noise into every turn.

### The night's busy guard

| Key | Default | |
|---|---|---|
| `sleep_guard_models` | `[sleep_model]` | Before each call, the night waits until these models are idle |
| `lms_cli` | `~/.cache/lm-studio/bin/lms` | LM Studio only: used to read its model status. Set it to `''` on other servers |

When the night server is of type `openai`, the night also waits while that server reports a busy slot. A status that can't be read counts as idle.

To run one night on a different model or server:

```bash
hermes sophia sleep --model M [--url U --api openai]
```


## The dashboard's graph

These shape the Graph view of the Sophia tab. They don't affect recall: recall's own graph walk is `graph_hops`.

| Key | Default | |
|---|---|---|
| `dashboard_graph_view` | `neighborhood` | What the graph opens on: `neighborhood` (everything within a few hops of you) or `everything` (every person and thing, by cluster) |
| `dashboard_graph_hops` | 2 | How far a neighborhood reaches, 1 to 4 |
| `dashboard_graph_resolution` | 1.0 | Cluster size, for Louvain clustering: higher splits memory into more, smaller clusters |
| `dashboard_graph_mention_weight` | 0.5 | How strongly naming two people or things in the same line ties them, next to a fact between them (1.0) |

## Identity

| Key | Default | |
|---|---|---|
| `user_name` | `user` | Speaker label for your lines; also the subject of extracted facts |
| `agent_name` | `assistant` | Speaker label for the agent's lines. These rank below yours and are never mined for facts |
| `other_speakers` | none | Others who write in your conversations, such as another agent relaying through your channel (comma-separated in setup). A user-role message that opens with `Name:` or `**Name:**` for one of these names is stored as theirs, not yours |

Lines from other speakers are written to the agent, so at night a fact drawn from one must be grounded in the line. If the fact's subject or object is you, the agent or one of the other speakers, that person must be named in the line, or be the speaker writing in the first person ("I", "my"), or be the agent addressed as "you"/"your". Facts that fail are dropped, and the extraction prompt gets a one-line note about these lines whenever a batch contains any. On every line, a fact that only says one of these people *is* the assistant, the user or an agent is dropped as a role, not a fact. `hermes sophia audit-facts` lists stored facts that fail these checks, and `--apply` retracts them (journaled, undoable).

## Awake: capture

| Key | Default | |
|---|---|---|
| `window_sentences` / `window_chars` | 3 / 480 | Window size for the raw record |
| `code_block_chars` | 800 | Long code blocks become one truncated `code` window |
| `capture_tools` | `web_extract`, `browser_snapshot`, `browser_navigate` | Tool results that are captured as external sources |
| `never_capture_substrings` | `vault`, `credential`, `secret`, `password` | A tool whose name contains any of these is never captured |
| `test_tools` | `terminal`, `shell`, `bash`, `run_command`, `execute_code` | Their output is scanned for pytest outcomes |
| `full_capture_contexts` | `primary` | Agent contexts captured in full. Other contexts (subagents, cron) record a short event per task prompt and their tool calls (the action log, so they still get task cards), but no conversation windows and no web reads |
| `echo_threshold` | 0.5 | Shingle containment above which a reply that just repeats injected memory is fenced off as an echo |
| `ground_check` | on | Each live agent reply that names people, places or numbers is checked by the decider (both option orders). The question is whether every claim it makes about you is in your message, the memory it was given, or the turn's tool results. If not, the reply is kept out of recall. Imported history is not checked, because what was injected then is unknown |

## Awake: recall and injection

| Key | Default | |
|---|---|---|
| `recall_k` | 50 | Number of candidates fetched |
| `gate_top` | 10 | Number of candidates the gate looks at |
| `inject_top` | 50 | How deep in the ranking injection may draw from. It is still bounded by `inject_relative_floor` and `inject_chars` |
| `skip_gate` | 0.82 | At or above this top-1 cosine, always inject. `gate: decider` then skips the decider; `gate: choice` still asks it, for the whole-block label and, when on, the split (measured; see `research/embed_thresholds.py`) |
| `gate` | choice | How Sophia decides what to inject. `choice`: one decider readout with an option per memory, plus "nothing needed" and "about you, but none of these fits". It closes the gate on messages that need nothing about you, and heads the block "possible matches only" when "none fits" is at least as likely as all the memories together. `decider`: the older yes/no question, which in a large memory lets nearly everything through. `similarity`: no model call, just the best match's cosine. [Measured](BENCHMARKS.md#the-choice-gate-one-readout-that-gates-and-splits-the-lines) |
| `gate_general` | 0.8 | `gate: choice`: inject unless "nothing needed" gets at least this probability |
| `gate_recheck` | 0.05 | `gate: choice`: when "nothing needed" is between this and 1 minus this, and a second reading could still change the decision, read the options again in reverse order and average the two readings. 0 turns it off |
| `gate_split` | off | `gate: choice`: list the lines the gate vouched for under Relevant and the rest under "Possible matches (less certain; rely on one only if it clearly answers the message)". Off by default: on held-out LoCoMo the reader dropped answers the split had misfiled ([measured](BENCHMARKS.md#the-choice-gate-one-readout-that-gates-and-splits-the-lines)) |
| `split_min` | 0.02 | `gate_split`: the share of the memories' probability a line needs to be listed as Relevant. Lower lists more lines as Relevant, which helps counting questions that need every piece, and hurts questions whose older, superseded lines then look as sure as the current one ([measured](BENCHMARKS.md#the-choice-gate-one-readout-that-gates-and-splits-the-lines)) |
| `gate_threshold` | 0.5 | `gate: decider`: probability needed to inject |
| `gate_floor` | 0.50 | `gate: similarity`: the best match's cosine needed to inject |
| `gate_permutations` | 1 | Option orders averaged per gate decision. With 2, both orders are always averaged, cancelling position bias at twice the cost |
| `junk_floor` | 0.5 | Candidates below this cosine are dropped before ranking, unless they matched by keyword |
| `inject_chars` | 9000 | Size cap for the injected block: about 2,300 tokens at most, and typically 1,900 when memory is relevant. The check injects nothing on unrelated turns. If your model's context is small, lower this and `inject_top` |
| `inject_relative_floor` | 0.25 | Only inject items within this score of the top item |
| `inject_order` | time | `time`: still chosen best first, then listed by date under a heading per day. `rank`: best first |
| `recency_bonus`, `fts_bonus`, `type_bonus` | 0.01, 0.03, 0.02 | Ranking nudges. `fts_bonus` applies only when `fts_weight` is 0 |
| `fts_weight` | 0.05 | Graded keyword weight: a keyword match adds this × its bm25 score relative to the best match |
| `time_scope`, `time_scope_bonus` | boost, 0.05 | A date range in the question ("last week", "in March") ranks memories inside it higher. `filter` hides everything outside it instead, which misses facts told later about an earlier month |
| `show_resolved_dates` | on | Relative time words in injected lines are labelled with the date they meant when said ("last Saturday" = 2023-05-20) |
| `mark_passed_dates` | on | A resolved date that pointed ahead when it was said, and is now over, adds "now past; this line doesn't say if it happened" ([measured](BENCHMARKS.md#almanac-v02-near-misses-and-stale-plans)). Separately, and regardless of this setting, each night marks `planned` facts whose date is over as `unconfirmed`, and injected lines show that status |
| `facts_as` | keys | Extracted facts are extra search keys for the verbatim message they came from. The message ranks and is injected, labelled with its facts. `items` lets facts compete as their own entries, which pushed evidence down in testing |
| `assistant_penalty`, `max_assistant_items` | 0.06, 2 | Keep the agent's own restatements from crowding out your words |
| `advice_penalty`, `advice_keeps_questions` | 0.06, on | When you ask for suggestions or advice, the agent's earlier lines rank a further 0.06 lower, and your own earlier questions (which say a lot about you) are not ranked down |
| `question_penalty` | 0.04 | Ranking penalty for a bare earlier question in `sophia_recall`. Passive injection leaves bare questions out entirely |

## Awake: graph expansion

After the search, recall walks the memory graph from bridge entities: people and things in the best matches that the question itself doesn't name. Facts about them join the candidates, or raise candidates already found.

| Key | Default | |
|---|---|---|
| `graph_hops` | 1 | Hops from a matched entity to connected facts. 0 turns expansion off; 2 is untested |
| `graph_decay` | 0.9 | A connected fact scores its seed's score times this, or its own similarity if that is higher |
| `graph_hub_degree` | 8 | Entities with more facts than this spread less, damped by √(hub_degree / facts). You and the agent are never expanded |
| `graph_fanout` | 3 | Connected facts taken per entity, best-matching first |
| `graph_entities` | 6 | Entities expanded per hop |
| `graph_adjacent`, `graph_adjacent_decay` | 1, 0.9 | Turns immediately before and after a matched message (a question and its answer) join the candidates at the match's score × decay |

Conversation links are followed too: a matched message brings what corrects it, or what it answered.

## Asleep

| Key | Default | |
|---|---|---|
| `sleep_max_wait_s` | 900 | How long a night run waits for a busy guarded model before yielding |
| `sleep_poll_s` | 10 | How often it checks while waiting |
| `sleep_session_windows` | 40 | Windows per contextualize call |
| `promote_min_instances` / `promote_min_sessions` | 5 / 2 | Evidence needed before an emergent relation is promoted to canonical |
| `page_min_facts` | 3 | Minimum facts about an entity before it gets a wiki page |
| `calibration_min_labels` | 50 | Gold labels needed before decider temperatures are fitted |
| `supersede_threshold` | 0.85 | Decider probability needed before a newer fact retires an older one. It's high on purpose: a wrong retirement hides a true memory, while a missed one leaves both visible with their dates. Apart from negations ("not bringing the Fujifilm") and relations learned to hold one value at a time, only facts about an ongoing state (asked once per relation) can be retired. On one real memory the 9B retired set-valued states at 0.86–0.90 ("has reservations for" four places, each "replacing" the last); measured real changes score at least 0.92, so 0.92 is the safer setting until relations are also asked whether they hold several values at once |
| `supersede_prescreen` | 0.8 | Each possible change is read once first, in one option order; below this it is settled as no change. At or above it, it gets the careful reading in both orders, which `supersede_threshold` applies to |
| `night_judge` | decider | Which model makes the night's one-token judgments (sorting, headroom, supersession, whether a relation is a state, task outcomes, replay): `decider`, which is fast and on which every night threshold was measured, or `night`, the night model |
| `header_roles` | all | Whose lines get model-written context headers at night: `all`, or `user` for every line except the agent's (cheaper when the agent's replies are long; its lines still appear in the prompt as context) |
| `task_judge_chars` | 6000 | How much of a long task's action log the night's judge reads when deciding how it turned out: its first two actions and as many of its last as fit. A small decider context otherwise rejects long tasks |
| `night_parallel` | 2 | Night model calls in flight at once. Match the night model's parallel slots on its server |

## Timeouts (seconds)

`embed_timeout` 5, `decider_timeout` 8, `sleep_call_timeout` 300. `embed_max_chars` (3000): longer texts, such as task cards, are embedded from their start, so they fit the embedding server's context; the text itself is kept whole.

Hermes gives an external provider's prefetch 8 s in total, so keep `embed_timeout + decider_timeout` comfortably under that on slow hardware. When a model call fails or times out, Sophia records a degraded mode, which `sophia status` shows, and carries on without that model:

- with no embeddings, recall falls back to keyword search;
- with no decider, only a very strong match (top-1 cosine at or above `skip_gate`) is injected; `gate: similarity` doesn't use the decider at all;
- capture stores windows without vectors, and the next night fills them in.

## Serving the decider

The decider only ever reads one token's probabilities, so the server it runs on matters more than the model's speed. LM Studio works, but its only logprob endpoint (`/v1/responses`) adds about 0.2 s per call. llama.cpp's own server returns the same probabilities from its chat endpoint, faster: passive recall dropped from 651 to 490 ms median, and from 954 to 527 ms p90, with identical decisions (docs/BENCHMARKS.md, "Serving the decider faster").

```bash
# the same GGUF LM Studio uses, on one GPU (about 6 GB)
CUDA_VISIBLE_DEVICES=1 llama-server -m Qwen3.5-9B-Q4_K_M.gguf -ngl 99 -c 16384 -np 4 -fa on --jinja \
    --alias qwen35-9b --host 127.0.0.1 --port 8081
```

```yaml
# Sophia's config: only the decider moves; embeddings and the night can stay on LM Studio
decider_url: http://127.0.0.1:8081
decider_api: openai
```

- **Thinking.** Sophia turns thinking off per request (`chat_template_kwargs: {enable_thinking: false}`). Don't use `--reasoning-budget 0` instead: the first token is then likely to be a thinking tag, not the answer.
- **Memory.** llama-server needs its own copy of the model. On a machine that's already full, unload the model from LM Studio first.
- **Other servers** (surveyed in September 2026, not all tested here):
  - **vLLM** (`logprob_token_ids`, `/generative_scoring`) and **SGLang** (`/v1/score`, which scores candidate tokens in one pass) have the neatest APIs for this. But Qwen3.5-9B's 4-bit checkpoints for them take 8–9 GB. Prefix caching for its hybrid recurrent layers is still unreliable in both, and SGLang's kernels for them need newer GPUs than a 3090.
  - **TabbyAPI + ExLlamaV3** returns logprobs and has a 4-bit build that fits in 6–8 GB. Untested here.
  - **Ollama** returns logprobs natively since v0.12.11, but reportedly not through its OpenAI-compatible endpoint. Untested here.

### One endpoint for everything: llama-server's router mode

llama-server can serve several models on one port, routing by the request's `model` name, with per-model flags in an INI file. The chat model, the decider and the embedding model all move off LM Studio this way. Measured on 2× RTX 3090 with the same GGUF files (`bench/serving_bench.py`):

| | LM Studio | llama-server router |
|---|---|---|
| Qwen3.8-27B, fresh 6,100-token prompt: first token | 6.5 s | 6.0 s |
| Qwen3.8-27B, cached prompt: first token | 0.45 s | 0.50 s |
| Qwen3.8-27B generation | 43.6 tok/s | **75.5 tok/s** (tensor split + built-in MTP, one slot) |
| Decider gate call | 594 ms | **403 ms** |
| Embeddings, 64 texts | 571 ms | **89 ms** |

The same 27B with 4 slots and no MTP instead generates 50 tok/s, and 42 tok/s each for two requests at once, against LM Studio's 29.4. Choose that when requests often overlap.

```ini
version = 1
[*]
jinja = true
flash-attn = on
n-gpu-layers = 999

[qwen/qwen3.8-27b]
model = /models/Qwen3.8-27B-Q6_K.gguf
mmproj = /models/mmproj-Qwen3.8-27B-BF16.gguf
split-mode = tensor
ctx-size = 65536
parallel = 1
batch-size = 4096
ubatch-size = 1024
spec-type = draft-mtp
spec-draft-n-max = 2
load-on-startup = true

[qwen35-9b]
model = /models/Qwen3.5-9B-Q4_K_M.gguf
device = CUDA1
ctx-size = 16384
parallel = 4
load-on-startup = true

[nomic-embed]
model = /models/nomic-embed-text-v1.5.Q4_K_M.gguf
device = CUDA1
embedding = true
pooling = mean
ctx-size = 8192
batch-size = 8192
ubatch-size = 8192
load-on-startup = true
```

Start it with `llama-server --host 127.0.0.1 --port 8090 --models-preset models.ini --models-max 3`, for example from a systemd user service. Then:

- **Hermes:** `model.provider: local` and `model.base_url: http://127.0.0.1:8090/v1`. The model names stay the same.
- **Sophia:** `server_url: http://127.0.0.1:8090`, `server_type: openai`, and `lms_cli: ''`. The night guard then asks the router whether the chat model is busy (`/slots?model=…`), so nights still yield to a live conversation.
- **Only one 27B fits in memory.** Don't load models in LM Studio while the router holds the GPUs.
