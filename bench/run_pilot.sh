#!/usr/bin/env bash
# Pilot: one LoCoMo conversation in three modes, then Gemmery's 60 LongMemEval questions in three modes.
set -u
cd "$(dirname "$0")"
for mode in full sophia sophia-night; do
  python3 locomo.py --mode "$mode" --convs conv-26 --tag pilot || echo "locomo $mode failed"
done
for mode in oracle none sophia; do
  python3 longmemeval.py --mode "$mode" --sample gemmery60 --tag pilot || echo "lme $mode failed"
done
echo PILOT DONE
