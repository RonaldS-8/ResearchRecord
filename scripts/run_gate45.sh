#!/usr/bin/env bash
# Dedicated, bounded Gate45 service and frozen Ready-arm batch. Run on LabServer.
set -euo pipefail
cd /home/ubuntu/Song/Agent
archive=results/045-service-01
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
.venv/bin/python - <<'PY'
import socket
s=socket.socket()
try:
    s.bind(('127.0.0.1',8000))
finally:
    s.close()
PY
setsid bash benchmarks/ToolMaze/evaluation/scripts/serve_local_vllm.sh > "$archive/vllm.log" 2>&1 &
service_pid=$!
printf '%s\n' "$service_pid" > "$archive/service.pid"
ready=0
for attempt in $(seq 1 180); do
  kill -0 "$service_pid"
  if curl -fsS http://127.0.0.1:8000/v1/models > "$archive/models.json"; then
    ready=1
    break
  fi
  sleep 5
done
[[ "$ready" == 1 ]]
.venv/bin/python - <<'PY'
import json
assert [x['id'] for x in json.load(open('results/045-service-01/models.json'))['data']] == ['Qwen3-4B-Thinking-2507']
PY
PYTHONPATH=benchmarks/ToolMaze:tests:. .venv/bin/python -m extensions.toolmaze_recovery.gate45 --output results/045-real-agent-01 --model-path models/Qwen3-4B-Thinking-2507
