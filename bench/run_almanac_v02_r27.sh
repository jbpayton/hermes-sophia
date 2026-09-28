#!/usr/bin/env bash
# Held out, reader-side: Almanac v0.2 test lives on the memories run_almanac_v02_heldout.sh built, read by the 27B
# (the model Sophia herself runs on) instead of the 9B; judge unchanged (9B). The default, and the per-line split.
set -u
cd "$(dirname "$0")"
D="$(pwd)/work/almanac02_test"; L="${ALMANAC_PATH:-$HOME/almanac}/data/v0.2/lives"; R="$(pwd)/results"
A="${ALMANAC_PATH:-$HOME/almanac}"; SOPHIA="$(cd .. && pwd)"
for arm in "default:" "split:--opt gate_split=true"; do
  name=${arm%%:*}; extra=${arm#*:}
  (cd "$A" && PYTHONPATH="$SOPHIA:$A" python3 -m almanac.run --adapter sophia --lives "$L" --url http://127.0.0.1:8090 \
     --api openai --reader qwen/qwen3.8-27b --judge qwen35-9b --opt night=end --opt memories="$D/memories" $extra \
     --out "$R/almanac02_test_r27_$name.jsonl") > "$R/almanac02_test_r27_$name.log" 2>&1 || echo "failed $name"
done
echo ALMANAC02 R27 DONE
