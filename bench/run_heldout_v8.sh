#!/usr/bin/env bash
# Held-out confirmation of v8: the choice gate (one readout that gates and splits lines into Relevant and Possible
# matches) against the yes/no gate, both run now on the same code and serving (llama-server router), 9B reader
# and judge. Passive recall only: the gate decides what is injected. Arms alternate per benchmark so partial
# results are already paired.
set -u
cd "$(dirname "$0")"
export SOPHIA_BENCH_URL=http://127.0.0.1:8090 SOPHIA_BENCH_API=openai
M="$(pwd)/work/lme_all"
R="$(pwd)/results"
A="${ALMANAC_PATH:-$HOME/almanac}"
SOPHIA="$(cd .. && pwd)"
HELD=conv-42,conv-43,conv-44,conv-47,conv-48,conv-49,conv-50
for arm in decider choice; do
  echo "== LME held-out 60, passive, 9B reader, gate=$arm"
  python3 longmemeval.py --mode sophia --sample gemmery60 --memories "$M" --tag "heldout_v8_$arm" --set gate=$arm || echo failed
done
for arm in decider choice; do
  echo "== Almanac test lives, passive by day, 9B reader and judge, gate=$arm"
  (cd "$A" && PYTHONPATH="$SOPHIA:$A" python3 -m almanac.run --adapter sophia --url "$SOPHIA_BENCH_URL" --api openai \
     --reader qwen35-9b --judge qwen35-9b --opt gate=$arm --out "$R/almanac_test_v8_$arm.jsonl") || echo failed
done
for arm in decider choice; do
  echo "== LoCoMo held-out, passive, 9B reader (split-night memories), gate=$arm"
  python3 locomo.py --mode sophia-night --convs $HELD --tag "heldout_v8_$arm" --reuse-from heldout_split --set gate=$arm || echo failed
done
echo HELDOUT V8 DONE
