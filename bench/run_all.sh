#!/usr/bin/env bash
# One queue, run in order, so no two runs share scratch memories or the night's lock.
set -u
cd "$(dirname "$0")"
OLD="--inject-top 10 --recall-k 20 --inject-chars 6000 --set facts_as=\"items\" --set graph_adjacent=0 --set fts_weight=0 --set inject_relative_floor=0.15"
HELD=conv-42,conv-43,conv-44,conv-47,conv-48,conv-49,conv-50
echo "== 1. LongMemEval dev, new defaults (diagnosis; cached memories)"
python3 longmemeval.py --mode sophia --sample dev60 --memories work/lme --tag dev_v3 || echo "failed"
echo "== 2. LongMemEval Gemmery-60, old recall settings (finish the 'before' pilot)"
eval python3 longmemeval.py --mode sophia --sample gemmery60 --tag pilot $OLD || echo "failed"
echo "== 3. held-out: LongMemEval Gemmery-60, new defaults"
python3 longmemeval.py --mode sophia --sample gemmery60 --tag heldout || echo "failed"
echo "== 4. held-out: LoCoMo 7 conversations"
python3 locomo.py --mode sophia --convs $HELD --tag heldout || echo "failed"
python3 locomo.py --mode full --convs $HELD --tag heldout || echo "failed"
python3 locomo.py --mode sophia-night --convs $HELD --tag heldout || echo "failed"
echo ALL DONE
