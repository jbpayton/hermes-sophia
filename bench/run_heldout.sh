#!/usr/bin/env bash
# Held-out evaluation with the development-tuned defaults. Nothing here was used for tuning:
# LoCoMo conv-42..50 (7 conversations) and Gemmery's 60 LongMemEval questions.
set -u
cd "$(dirname "$0")"
HELD=conv-42,conv-43,conv-44,conv-47,conv-48,conv-49,conv-50
python3 longmemeval.py --mode sophia --sample gemmery60 --tag heldout || echo "lme sophia failed"
python3 locomo.py --mode sophia --convs $HELD --tag heldout || echo "locomo day failed"
python3 locomo.py --mode full --convs $HELD --tag heldout || echo "locomo full failed"
python3 locomo.py --mode sophia-night --convs $HELD --tag heldout || echo "locomo night failed"
echo HELDOUT DONE
