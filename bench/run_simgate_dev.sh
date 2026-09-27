#!/usr/bin/env bash
# Development only: the similarity gate (no model call) against the old one-order decider gate.
set -u
cd "$(dirname "$0")"
W="$(pwd)/work/lme"
OLD="--set gate=decider --set gate_permutations=1"
echo "== LME dev60, similarity gate (compare with dev_v5_time)"
python3 longmemeval.py --mode sophia --sample dev60 --memories "$W" --tag dev_v7_simgate --set gate=similarity --yield-to "" || echo failed
echo "== LoCoMo dev, similarity gate (compare with dev_v5_time)"
python3 locomo.py --mode sophia --convs conv-26,conv-30,conv-41 --tag dev_v7_simgate --reuse-from dev_v5 --set gate=similarity --yield-to "" || echo failed
echo "== passive time, similarity gate"
python3 profile_prefetch.py --sample dev60 --set gate=similarity --yield-to "" || echo failed
echo SIMGATE DEV DONE
