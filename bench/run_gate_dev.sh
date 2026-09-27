#!/usr/bin/env bash
# Development only: the new relevance gate (both option orders, in parallel; wording about the user's own world).
set -u
cd "$(dirname "$0")"
W="$(pwd)/work/lme"
echo "== LME dev60, new gate (compare with dev_v5_time)"
python3 longmemeval.py --mode sophia --sample dev60 --memories "$W" --tag dev_v7_gate --yield-to "" || echo failed
echo "== LoCoMo dev, new gate (compare with dev_v5_time)"
python3 locomo.py --mode sophia --convs conv-26,conv-30,conv-41 --tag dev_v7_gate --reuse-from dev_v5 --yield-to "" || echo failed
echo "== passive time"
python3 profile_prefetch.py --sample dev60 --yield-to "" || echo failed
echo GATE DEV DONE
