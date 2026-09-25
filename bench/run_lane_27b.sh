#!/usr/bin/env bash
# 27B lane: new held-out nights (27B writes, 9B decides), then the 27B as reader, passive and active.
set -u
cd "$(dirname "$0")"
HELD=conv-42,conv-43,conv-44,conv-47,conv-48,conv-49,conv-50
R27="--reader qwen/qwen3.8-27b"
echo "== N LoCoMo held-out nights: 27B writes, 9B decides (9B reader, comparable with 0.730 / 0.748)"
python3 locomo.py --mode sophia-night --convs $HELD --tag heldout_split --night-model qwen/qwen3.8-27b --set night_parallel=4 || echo failed
echo "== L1 LoCoMo held-out, passive, 27B reader (split-night memories)"
python3 locomo.py --mode sophia-night --convs $HELD --tag heldout_split_r27 --reuse-from heldout_split $R27 || echo failed
echo "== L2 LoCoMo held-out, active, 27B reader"
python3 locomo.py --mode sophia-night --recall active --convs $HELD --tag heldout_split_r27 --reuse-from heldout_split $R27 || echo failed
echo "== M1 LongMemEval held-out, passive, 27B reader"
python3 longmemeval.py --mode sophia --sample gemmery60 --memories work/lme_test --tag heldout_r27 $R27 || echo failed
echo "== M2 LongMemEval held-out, active, 27B reader"
python3 longmemeval.py --mode sophia --recall active --sample gemmery60 --memories work/lme_test --tag heldout_r27 $R27 || echo failed
echo "== M3 LongMemEval held-out, evidence sessions, 27B reader"
python3 longmemeval.py --mode oracle --sample gemmery60 --tag heldout_r27 $R27 || echo failed
echo "== L3 LoCoMo held-out, whole conversation, 27B reader"
python3 locomo.py --mode full --convs $HELD --tag heldout_r27 $R27 || echo failed
echo LANE 27B DONE
