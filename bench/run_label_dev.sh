#!/usr/bin/env bash
# Development only: the choice gate with the softer label for less certain lines ("rely on one only if it clearly
# answers the message"), against dev_v8_decider and dev_v8_choice (the "verify before relying" label).
set -u
cd "$(dirname "$0")"
export SOPHIA_BENCH_URL=http://127.0.0.1:8090 SOPHIA_BENCH_API=openai
W="$(pwd)/work/lme"; R="$(pwd)/results"; A="${ALMANAC_PATH:-$HOME/almanac}"; SOPHIA="$(cd .. && pwd)"
tag=dev_v8_choice_label
python3 locomo.py --mode sophia --convs conv-26,conv-30,conv-41 --tag $tag --reuse-from dev_v5 --set gate=choice || echo failed
python3 longmemeval.py --mode sophia --sample dev60 --memories "$W" --tag $tag --set gate=choice || echo failed
python3 longmemeval.py --mode sophia --sample devpref --memories "$W" --tag $tag --set gate=choice || echo failed
(cd "$A" && PYTHONPATH="$SOPHIA:$A" python3 -m almanac.run --adapter sophia --lives data/dev --url "$SOPHIA_BENCH_URL" \
   --api openai --reader qwen35-9b --judge qwen35-9b --opt gate=choice --out "$R/almanac_dev_$tag.jsonl") || echo failed
echo LABEL DEV DONE
