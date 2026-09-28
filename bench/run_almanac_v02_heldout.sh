#!/usr/bin/env bash
# Held out: Almanac v0.2 test lives (data/v0.2/lives), each life's
# memory built once with a night (by the default arm) and reused by every arm, so the arms differ only in recall.
# Arms: the default (choice gate, passed dates marked), passed dates unmarked, the per-line split, the yes/no gate.
set -u
cd "$(dirname "$0")"
export SOPHIA_BENCH_URL=http://127.0.0.1:8090
D="$(pwd)/work/almanac02_test"; L="${ALMANAC_PATH:-$HOME/almanac}/data/v0.2/lives"; R="$(pwd)/results"; A="${ALMANAC_PATH:-$HOME/almanac}"; SOPHIA="$(cd .. && pwd)"
arm() {  # name, extra options
  local name=$1; shift
  (cd "$A" && PYTHONPATH="$SOPHIA:$A" python3 -m almanac.run --adapter sophia --lives "$L" --url "$SOPHIA_BENCH_URL" \
     --api openai --reader qwen35-9b --judge qwen35-9b --opt night=end --opt memories="$D/memories" "$@" \
     --out "$R/almanac02_test_$name.jsonl") >> "$R/almanac02_test_$name.log" 2>&1 || echo "failed $name"
}
arm default --only life-01,life-02,life-03 &
arm default --only life-04,life-05,life-06 &
arm default --only life-07,life-08 &
wait
arm unmarked --opt mark_passed_dates=false &
arm split --opt gate_split=true &
arm decider --opt gate=decider &
wait
echo ALMANAC02 HELDOUT DONE
