#!/usr/bin/env bash
# Development only: Almanac v0.2 on 10 development lives (seed 2; lives 1-3 are the published dev set), each life's
# memory built once with a night (by the default arm) and reused by every arm, so the arms differ only in recall.
# Arms: the default, "now Y (was X)" wording for superseded facts (an option since removed), the per-line split,
# and the yes/no gate.
# changed_style (the "now Y (was X)" wording) was tried here and removed: it changed nothing.
set -u
cd "$(dirname "$0")"
export SOPHIA_BENCH_URL=http://127.0.0.1:8090
D="$(pwd)/work/almanac02_dev10"; R="$(pwd)/results"; A="${ALMANAC_PATH:-$HOME/almanac}"; SOPHIA="$(cd .. && pwd)"
arm() {  # name, extra options
  local name=$1; shift
  (cd "$A" && PYTHONPATH="$SOPHIA:$A" python3 -m almanac.run --adapter sophia --lives "$D/lives" --url "$SOPHIA_BENCH_URL" \
     --api openai --reader qwen35-9b --judge qwen35-9b --opt night=end --opt memories="$D/memories" "$@" \
     --out "$R/almanac02_dev10_$name.jsonl") >> "$R/almanac02_dev10_$name.log" 2>&1 || echo "failed $name"
}
arm default --only life-01,life-02,life-03,life-04 &
arm default --only life-05,life-06,life-07 &
arm default --only life-08,life-09,life-10 &
wait
arm now_was --opt changed_style=now_was &
arm split --opt gate_split=true &
arm decider --opt gate=decider &
wait
# Then the passed-dates mark, added after the arms above: today's wording ("now past; this line doesn't say if it
# happened", the default) and none. almanac02_dev10_marker_on was an earlier wording ("now past" alone).
arm marker2 &
arm marker_off --opt mark_passed_dates=false &
wait
echo ALMANAC02 PAIRED DONE
