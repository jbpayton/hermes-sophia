#!/usr/bin/env bash
# Development only: active recall on a baseline checkout (BASE=path/to/its/bench) against this one, 27B reader,
# same cached memories. Used to test (and reject) an exhaustive recall option: see docs/BENCHMARKS.md.
set -u
cd "$(dirname "$0")"
W="$(pwd)/work/lme"
BASE="${BASE:?set BASE to the bench folder of a checkout of the baseline code}"
echo "== LME dev60 active, before (committed code)"
( cd "$BASE" && SOPHIA_BENCH_DATA="$HOME/sophia-hermes-research/bench-data" python3 longmemeval.py --mode sophia --recall active --sample dev60 --memories "$W" --reader qwen/qwen3.8-27b --tag dev_ab_before --yield-to "" ) || echo failed
echo "== LME dev60 active, this checkout"
python3 longmemeval.py --mode sophia --recall active --sample dev60 --memories "$W" --reader qwen/qwen3.8-27b --tag dev_ab_after --yield-to "" || echo failed
echo AB DONE
