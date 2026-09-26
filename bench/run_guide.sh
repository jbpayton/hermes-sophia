#!/usr/bin/env bash
# Development only: a heading that asks the reader to let the user's situation and preferences shape the reply.
set -u
cd "$(dirname "$0")"
W="$(pwd)/work/lme"
echo "== LME preference dev (26), heading off"
python3 longmemeval.py --mode sophia --sample devpref --memories "$W" --tag dev_guide_off --yield-to "" || echo failed
echo "== LME preference dev (26), heading on"
python3 longmemeval.py --mode sophia --sample devpref --memories "$W" --tag dev_guide_on --set inject_guide=true --yield-to "" || echo failed
echo "== LME dev60, heading on (compare with dev_v5_rank)"
python3 longmemeval.py --mode sophia --sample dev60 --memories "$W" --tag dev_v5_guide --set inject_guide=true --yield-to "" || echo failed
echo GUIDE DONE
