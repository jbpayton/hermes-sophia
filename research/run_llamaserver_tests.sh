#!/usr/bin/env bash
set -u
LMS=~/.cache/lm-studio/bin/lms
BK=~/.cache/lm-studio/extensions/backends/llama.cpp-linux-x86_64-nvidia-cuda12-avx2-2.33.0
M9=~/.cache/lm-studio/models/lmstudio-community/Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf
MD=~/.cache/lm-studio/models/unsloth/Qwen3.5-0.8B-GGUF/Qwen3.5-0.8B-Q8_0.gguf
export LD_LIBRARY_PATH=$BK:${LD_LIBRARY_PATH:-}
$LMS unload qwen35-9b 2>&1 | tail -1
run_cfg () {
  local label="$1"; shift
  echo; echo "=================== llama-server GPU1: $label ==================="
  "$BK/llama-server" -m "$M9" -dev CUDA1 -ngl 99 -c 8192 -np 4 -fa on --jinja --port 8081 --host 127.0.0.1 "$@" > "llamaserver_${label// /_}.log" 2>&1 &
  local pid=$!
  for i in $(seq 1 90); do sleep 1; curl -s -m 2 http://127.0.0.1:8081/health | grep -q '"ok"' && break; done
  if ! curl -s -m 2 http://127.0.0.1:8081/health | grep -q '"ok"'; then echo "server failed to start:"; tail -5 "llamaserver_${label// /_}.log"; kill $pid 2>/dev/null; wait $pid 2>/dev/null; return; fi
  nvidia-smi --query-gpu=index,memory.used --format=csv,noheader | tr '\n' ' '; echo
  LMS_BASE=http://127.0.0.1:8081 API=chat python3 speed_tests.py qwen35-9b compact 2>&1 | grep "^###" | sed 's/, sentence-id.*//'
  LMS_BASE=http://127.0.0.1:8081 API=chat python3 speed_tests.py qwen35-9b concurrency 2>&1 | grep -E "serial total|parallel total"
  kill $pid; wait $pid 2>/dev/null; sleep 2
}
run_cfg "plain"
run_cfg "ngram-mod" --spec-type ngram-mod
run_cfg "draft-simple 0.8B" --spec-type draft-simple -md "$MD" -devd CUDA1 -ngld 99 --spec-draft-n-max 8
echo; echo "--- restore LM Studio 9B ---"
$LMS load qwen/qwen3.5-9b --gpu max -c 8192 --identifier qwen35-9b -y 2>&1 | tr '\r' '\n' | grep -v Loading | tail -1
$LMS ps 2>&1 | tail -3
