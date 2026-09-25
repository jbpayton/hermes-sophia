#!/usr/bin/env bash
# 9B lane: development checks first, then held-out 9B-reader runs, the cheap LongMemEval night, the full 500.
set -u
cd "$(dirname "$0")"
YT=(--yield-to "")      # the 27B lane keeps the 27B busy; this lane must not wait on it
echo "== D1 LongMemEval dev, passive, 9B reader (resolved dates + agent-words recall)"
python3 longmemeval.py --mode sophia --sample dev60 --memories work/lme --tag dev_v4 "${YT[@]}" || echo failed
echo "== D2 LoCoMo dev conv-26, day, passive, 9B reader: with and without resolved dates"
python3 locomo.py --mode sophia --convs conv-26 --tag dev_v4 "${YT[@]}" || echo failed
python3 locomo.py --mode sophia --convs conv-26 --tag dev_v4_nodates --set show_resolved_dates=false "${YT[@]}" || echo failed
echo "== H1 LongMemEval held-out, passive, 9B reader"
python3 longmemeval.py --mode sophia --sample gemmery60 --memories work/lme_test --tag heldout_v4 "${YT[@]}" || echo failed
echo "== D3 LongMemEval dev: cheap night (user-line headers, 9B decides) -> retrieval"
python3 lme_night.py --sample dev60 "${YT[@]}" || echo failed
python3 retrieval_lme.py --sample dev60 --db-suffix night --label "dev night-lite" "${YT[@]}" || echo failed
echo "== J judge agreement (27B re-grades 200 LoCoMo and 60 LongMemEval answers)"
python3 judge_agreement.py --files results/locomo_sophia-night_heldout.jsonl --n 200 --judge qwen/qwen3.8-27b "${YT[@]}" || echo failed
python3 judge_agreement.py --files results/lme_sophia_gemmery60_heldout.jsonl --n 60 --judge qwen/qwen3.8-27b "${YT[@]}" || echo failed
echo "== F LongMemEval all 500, passive, 9B reader (memories cached for other readers)"
python3 longmemeval.py --mode sophia --sample all --memories work/lme_all --tag full500 "${YT[@]}" || echo failed
echo LANE 9B DONE
