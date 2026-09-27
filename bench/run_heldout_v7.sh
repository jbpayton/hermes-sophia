#!/usr/bin/env bash
# Held-out evaluation of v7 (v6 plus the similarity gate and parallel option orders; the agent-words
# pattern fix). Same memories and settings as the earlier rows otherwise, so each compares with its predecessor.
set -u
cd "$(dirname "$0")"
M="$(pwd)/work/lme_all"
R27="--reader qwen/qwen3.8-27b"
HELD=conv-42,conv-43,conv-44,conv-47,conv-48,conv-49,conv-50
echo "== 1. LME held-out 60, passive, 9B reader"
python3 longmemeval.py --mode sophia --sample gemmery60 --memories "$M" --tag heldout_v7 --yield-to "" || echo failed
echo "== 2. LME held-out 60, passive, 27B reader"
python3 longmemeval.py --mode sophia --sample gemmery60 --memories "$M" --tag heldout_v7_r27 $R27 --yield-to "" || echo failed
echo "== 3. LME held-out 60, active, 27B reader"
python3 longmemeval.py --mode sophia --recall active --sample gemmery60 --memories "$M" --tag heldout_v7_r27 $R27 --yield-to "" || echo failed
echo "== 4. LME all 500, passive, 9B reader"
python3 longmemeval.py --mode sophia --sample all --memories "$M" --tag all_v7 --yield-to "" || echo failed
echo "== 5. LoCoMo held-out, passive, 27B reader (split-night memories)"
python3 locomo.py --mode sophia-night --convs $HELD --tag heldout_v7_r27 --reuse-from heldout_split $R27 --yield-to "" || echo failed
echo "== 6. LoCoMo held-out, passive, 9B reader"
python3 locomo.py --mode sophia-night --convs $HELD --tag heldout_v7 --reuse-from heldout_split --yield-to "" || echo failed
echo "== 7. LoCoMo held-out, active, 27B reader"
python3 locomo.py --mode sophia-night --recall active --convs $HELD --tag heldout_v7_r27 --reuse-from heldout_split $R27 --yield-to "" || echo failed
echo HELDOUT V7 DONE
echo "== 8. Almanac test lives, Sophia (passive day, passive night, active night)"
( cd ~/almanac && export PYTHONPATH="$HOME/sophia-hermes-research/hermes-sophia:$HOME/almanac" && \
  python3 -m almanac.run --adapter sophia --out results/v7/sophia_passive_day.jsonl && \
  python3 -m almanac.run --adapter sophia --opt night=end --out results/v7/sophia_passive_night.jsonl && \
  python3 -m almanac.run --adapter sophia --opt night=end --opt recall=active --out results/v7/sophia_active_night.jsonl ) || echo failed
echo ALL V7 DONE
