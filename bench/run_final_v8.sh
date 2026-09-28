#!/usr/bin/env bash
# v8 as shipped (defaults: gate=choice, split off, whole-block "possible matches only" label), development then
# held out, against the dev_v8_decider / heldout_v8_decider arms run earlier on the same serving. 9B reader and judge.
set -u
cd "$(dirname "$0")"
export SOPHIA_BENCH_URL=http://127.0.0.1:8090 SOPHIA_BENCH_API=openai
W="$(pwd)/work/lme"; M="$(pwd)/work/lme_all"; R="$(pwd)/results"; A="${ALMANAC_PATH:-$HOME/almanac}"; SOPHIA="$(cd .. && pwd)"
HELD=conv-42,conv-43,conv-44,conv-47,conv-48,conv-49,conv-50
almanac() {  # lives, out
  (cd "$A" && PYTHONPATH="$SOPHIA:$A" python3 -m almanac.run --adapter sophia --lives "$1" --url "$SOPHIA_BENCH_URL" \
     --api openai --reader qwen35-9b --judge qwen35-9b --out "$2") || echo failed
}
echo "== dev"
python3 longmemeval.py --mode sophia --sample dev60 --memories "$W" --tag dev_v8_default || echo failed
python3 longmemeval.py --mode sophia --sample devpref --memories "$W" --tag dev_v8_default || echo failed
almanac data/dev "$R/almanac_dev_dev_v8_default.jsonl"
python3 locomo.py --mode sophia --convs conv-26,conv-30,conv-41 --tag dev_v8_default --reuse-from dev_v5 || echo failed
echo "== held out"
python3 longmemeval.py --mode sophia --sample gemmery60 --memories "$M" --tag heldout_v8_default || echo failed
almanac data/lives "$R/almanac_test_v8_default.jsonl"
python3 locomo.py --mode sophia-night --convs $HELD --tag heldout_v8_default --reuse-from heldout_split || echo failed
echo FINAL V8 DONE
