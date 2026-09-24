#!/usr/bin/env bash
# Development split (LoCoMo conv-26): the tuned retrieval settings, by day and on the pilot's night memory.
set -u
cd "$(dirname "$0")"
V2="--inject-top 30 --set fts_weight=0.1 --set inject_relative_floor=0.25 --set graph_adjacent=1"
python3 locomo.py --mode sophia --convs conv-26 --tag dev_v2 $V2 || echo "day failed"
python3 locomo.py --mode sophia-night --convs conv-26 --tag dev_v2 --reuse-from pilot $V2 || echo "night failed"
echo DEV DONE
