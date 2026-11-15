#!/usr/bin/env bash
# Experiment 050 local Qwen run on a dedicated vLLM service. Existing vllm tmux sessions are untouched.
# Run from a clean checkout of the registered commit: bash scripts/run_gate50.sh
set -euo pipefail
cd "$(dirname "$0")/.."
agent_root=/home/ubuntu/Song/Agent
archive="$agent_root/results/050-service-01"
mkdir "$archive"
exec > "$archive/supervisor.log" 2>&1
service_pid=''
cleanup() {
  if [[ -n "$service_pid" ]]; then
    kill -- -"$service_pid" 2>/dev/null || true
    wait "$service_pid" 2>/dev/null || true
  fi
  nvidia-smi > "$archive/gpu-after.txt"
}
trap cleanup EXIT
trap 'exit 143' TERM INT
[[ -z "$(git status --porcelain)" ]]
git rev-parse HEAD > "$archive/source-commit.txt"
nvidia-smi > "$archive/gpu-before.txt"
export MODEL_PATH="$agent_root/models/Qwen3-4B-Thinking-2507"
export PYTHONPATH=benchmarks/ToolMaze:tests:.
"$agent_root/.venv/bin/python" -m unittest discover -s tests -p 'test_toolmaze_gate50.py' > "$archive/cpu-tests.txt" 2>&1
"$agent_root/.venv/bin/python" - <<'PY'
import socket
s=socket.socket()
try:
    s.bind(('127.0.0.1',8000))
finally:
    s.close()
PY
printf '%s\n' 'serve_local_vllm.sh --no-enable-prefix-caching' > "$archive/launch-args.txt"
setsid bash "$agent_root/benchmarks/ToolMaze/evaluation/scripts/serve_local_vllm.sh" --no-enable-prefix-caching > "$archive/vllm.log" 2>&1 &
service_pid=$!
printf '%s\n' "$service_pid" > "$archive/service.pid"
ready=0
for attempt in $(seq 1 180); do
  kill -0 "$service_pid"
  if curl -fsS http://127.0.0.1:8000/v1/models > "$archive/models.json"; then ready=1; break; fi
  sleep 5
done
[[ "$ready" == 1 ]]
"$agent_root/.venv/bin/python" - <<'PY'
import json
from pathlib import Path
p=Path('/home/ubuntu/Song/Agent/results/050-service-01')
assert [x['id'] for x in json.loads((p/'models.json').read_text())['data']] == ['Qwen3-4B-Thinking-2507']
PY
timeout --signal=TERM 12h "$agent_root/.venv/bin/python" -m extensions.toolmaze_recovery.gate50 \
  --output "$agent_root/results/050-lost-receipt-01" --model-path "$MODEL_PATH"
"$agent_root/.venv/bin/python" scripts/analyze_gate50.py "$agent_root/results/050-lost-receipt-01"
