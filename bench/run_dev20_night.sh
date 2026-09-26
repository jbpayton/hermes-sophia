#!/usr/bin/env bash
# Does a night help LongMemEval retrieval? A stratified 20-question development slice (a full night per question
# takes ~20 min on the 9B, so all 60 would hold the GPUs for about 20 hours). Nights resume where they stopped.
set -u
cd "$(dirname "$0")"
echo "== nights on dev20 (9B writes and decides, 4 parallel slots)"
python3 lme_night.py --sample dev20 --yield-to "" --set night_parallel=4 || echo failed
echo "== retrieval: day memories"
python3 retrieval_lme.py --sample dev20 --db-suffix day --label "dev20 day" --yield-to "" || echo failed
echo "== retrieval: after the night"
python3 retrieval_lme.py --sample dev20 --db-suffix night --label "dev20 night-lite" --yield-to "" || echo failed
echo DEV20 DONE
