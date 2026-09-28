#!/usr/bin/env bash
# Development only: the three-way choice gate (re-reading the reverse order when unsure) against today's yes/no gate,
# both run now on the same code so the comparison is paired. Serving: the llama-server router; the 9B reads and judges.
set -u
cd "$(dirname "$0")"
export SOPHIA_BENCH_URL=http://127.0.0.1:8090 SOPHIA_BENCH_API=openai
W="$(pwd)/work/lme"
R="$(pwd)/results"
A="${ALMANAC_PATH:-$HOME/almanac}"
SOPHIA="$(cd .. && pwd)"
for arm in "decider:gate=decider" "choice:gate=choice gate_recheck=0.05"; do
  name="${arm%%:*}"; tag="dev_v8_$name"; set_args=""; opt_args=""
  for kv in ${arm#*:}; do set_args="$set_args --set $kv"; opt_args="$opt_args --opt $kv"; done
  echo "== LME dev60, $tag"
  python3 longmemeval.py --mode sophia --sample dev60 --memories "$W" --tag "$tag" $set_args || echo failed
  echo "== LME devpref, $tag"
  python3 longmemeval.py --mode sophia --sample devpref --memories "$W" --tag "$tag" $set_args || echo failed
  echo "== LoCoMo dev, $tag"
  python3 locomo.py --mode sophia --convs conv-26,conv-30,conv-41 --tag "$tag" --reuse-from dev_v5 $set_args || echo failed
  echo "== Almanac dev lives, $tag"
  (cd "$A" && PYTHONPATH="$SOPHIA:$A" python3 -m almanac.run \
     --adapter sophia --lives data/dev --url "$SOPHIA_BENCH_URL" --api openai --reader qwen35-9b --judge qwen35-9b \
     $opt_args --out "$R/almanac_dev_$tag.jsonl") || echo failed
done
echo CHOICE DEV DONE
