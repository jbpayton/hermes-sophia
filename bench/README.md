# Benchmark harness

Scripts for measuring Sophia on LoCoMo and LongMemEval, plus a task-memory smoke test. [docs/BENCHMARKS.md](../docs/BENCHMARKS.md) has the protocol and the results.

## Data

The data isn't in the repository. Put it in `../bench-data/`, or point `SOPHIA_BENCH_DATA` at another folder:

| File | Source |
|---|---|
| `locomo10.json` | https://github.com/snap-research/locomo (`data/locomo10.json`) |
| `longmemeval_s_cleaned.json`, `longmemeval_oracle.json` | https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned |

## Scripts

| Script | What it measures |
|---|---|
| `longmemeval.py` | End-to-end LongMemEval, scored with the official per-type judge prompts. Modes: `sophia`, `sophia-night`, `oracle`, `none`. `--memories` reuses cached per-question memories |
| `locomo.py` | End-to-end LoCoMo, scored with Mem0's J prompt over categories 1–4. Modes: `sophia`, `sophia-night`, `full`, `none`. `--reuse-from` starts from another run's memories |
| `retrieval.py`, `retrieval_lme.py` | Retrieval only, with no reader or judge: is the evidence ranked, and does it reach the agent? Takes seconds per variant on cached memories |
| `stages.py` | Builds memories from individual night stages (headers only, facts only, full) to see what each stage costs and adds |
| `tasks_eval.py` | Task memory on scripted agent sessions with known outcomes |
| `gate_check.py`, `follow_up_check.py`, `scoped_writing_check.py` | The passive path end to end, per gate: which messages get memory (relevant questions, general and personal requests, follow-ups, writing about people in memory), and how long it takes |
| `gate_wording_choice.py`, `split_study.py`, `combo_study.py` | Development studies behind `gate: choice`: the wording of "nothing needed", and how to split injected lines into Relevant and Possible matches |
| `profile_prefetch.py` | Where passive recall's time goes: search, gate, formatting |
| `compare_arms.py` | Paired comparison of two runs of the same questions: questions won and lost, and accuracy by what the choice gate said |

## Common flags

- `--set key=value` overrides any Sophia setting.
- `--reader` and `--judge` choose the models, and `--url` and `--api` the server.
- `--yield-to MODEL` pauses whenever that model is generating, so runs never compete with someone's chat.

Each run writes `results/<name>.jsonl` (per question, not committed) and `results/<name>.summary.json` (scores plus the exact configuration).

## Splits

- **Development (for tuning):** LoCoMo conversations 26, 30 and 41, and `lme_dev60.json`. For the gate: `gate_offtopic.json` and `gate_general_dev2.json` (general and personal requests).
- **Held-out (for reporting):** the other seven LoCoMo conversations, and `lme_gemmery60.json`. For the gate: `gate_heldout.json`.
