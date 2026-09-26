#!/usr/bin/env bash
# Development only: does listing injected evidence by date (inject_order=time) beat best-first (rank)?
set -u
cd "$(dirname "$0")"
W="$(pwd)/work/lme"
echo "== LME dev60, rank"
python3 longmemeval.py --mode sophia --sample dev60 --memories "$W" --tag dev_v5_rank --yield-to "" || echo failed
echo "== LME dev60, time"
python3 longmemeval.py --mode sophia --sample dev60 --memories "$W" --tag dev_v5_time --set inject_order=time --yield-to "" || echo failed
echo "== LoCoMo dev, rank (builds the day memories)"
python3 locomo.py --mode sophia --convs conv-26,conv-30,conv-41 --tag dev_v5 --yield-to "" || echo failed
echo "== LoCoMo dev, time"
python3 locomo.py --mode sophia --convs conv-26,conv-30,conv-41 --tag dev_v5_time --reuse-from dev_v5 --set inject_order=time --yield-to "" || echo failed
echo ORDER DONE
