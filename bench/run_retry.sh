#!/usr/bin/env bash
# Rerun what the transient engine errors broke (now with retries and failure-tolerant nights).
set -u
cd "$(dirname "$0")"
HELD=conv-42,conv-43,conv-44,conv-47,conv-48,conv-49,conv-50
R27="--reader qwen/qwen3.8-27b"
echo "== N LoCoMo held-out nights: 27B writes, 9B decides (9B reader)"
python3 locomo.py --mode sophia-night --convs $HELD --tag heldout_split --night-model qwen/qwen3.8-27b --set night_parallel=4 || echo failed
echo "== L1 LoCoMo held-out, passive, 27B reader"
python3 locomo.py --mode sophia-night --convs $HELD --tag heldout_split_r27 --reuse-from heldout_split $R27 || echo failed
echo "== L2 LoCoMo held-out, active, 27B reader"
python3 locomo.py --mode sophia-night --recall active --convs $HELD --tag heldout_split_r27 --reuse-from heldout_split $R27 || echo failed
echo "== D3 LongMemEval dev: cheap night -> retrieval"
python3 lme_night.py --sample dev60 --yield-to "" || echo failed
python3 retrieval_lme.py --sample dev60 --db-suffix night --label "dev night-lite" --yield-to "" || echo failed
echo RETRY DONE
