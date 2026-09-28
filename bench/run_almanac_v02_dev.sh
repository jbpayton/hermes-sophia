#!/usr/bin/env bash
# Development only: Almanac v0.2 dev lives, a night before the questions (so superseded facts are labelled), 9B reader
# and judge. Four arms in parallel: the default, the "now Y (was X)" wording for superseded facts, the per-line split,
# and the yes/no gate. Then LongMemEval dev20 on night memories, both wordings.
# changed_style (the "now Y (was X)" wording) was tried here and removed: it changed nothing.
set -u
cd "$(dirname "$0")"
export SOPHIA_BENCH_URL=http://127.0.0.1:8090 SOPHIA_BENCH_API=openai
R="$(pwd)/results"; A="${ALMANAC_PATH:-$HOME/almanac}"; SOPHIA="$(cd .. && pwd)"
arm() {  # name, extra options
  local name=$1; shift
  (cd "$A" && PYTHONPATH="$SOPHIA:$A" python3 -m almanac.run --adapter sophia --lives data/v0.2/dev --url "$SOPHIA_BENCH_URL" \
     --api openai --reader qwen35-9b --judge qwen35-9b --opt night=end "$@" --out "$R/almanac02_dev_night_$name.jsonl") \
     > "$R/almanac02_dev_night_$name.log" 2>&1 || echo "failed $name"
}
arm default &
arm now_was --opt changed_style=now_was &
arm split --opt gate_split=true &
arm decider --opt gate=decider &
wait
python3 longmemeval.py --mode sophia --sample dev20 --memories "$(pwd)/work/lme" --memories-prefix night --tag dev20_night_arrow || echo failed
python3 longmemeval.py --mode sophia --sample dev20 --memories "$(pwd)/work/lme" --memories-prefix night --tag dev20_night_now_was --set changed_style=now_was || echo failed
echo ALMANAC02 DEV DONE
