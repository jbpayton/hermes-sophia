#!/usr/bin/env bash
# Development only: closest 3 matches first, then the rest by date (inject_order=lead), against the new defaults.
set -u
cd "$(dirname "$0")"
W="$(pwd)/work/lme"
echo "== LME dev60, lead (compare with dev_v7_gate)"
python3 longmemeval.py --mode sophia --sample dev60 --memories "$W" --tag dev_v7_lead --set inject_order=lead --yield-to "" || echo failed
echo "== LoCoMo dev, lead (compare with dev_v7_gate)"
python3 locomo.py --mode sophia --convs conv-26,conv-30,conv-41 --tag dev_v7_lead --reuse-from dev_v5 --set inject_order=lead --yield-to "" || echo failed
echo LEAD DEV DONE
