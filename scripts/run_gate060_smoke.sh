#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
agent_root=/home/ubuntu/Song/Agent
archive="$agent_root/results/060-service-01"
mkdir "$archive"
exec > "$archive/supervisor.log" 2>&1
service_pid=''
cleanup() { if [[ -n "$service_pid" ]]; then kill -- -"$service_pid" 2>/dev/null || true; wait "$service_pid" 2>/dev/null || true; fi; nvidia-smi > "$archive/gpu-after.txt"; }
trap cleanup EXIT
[[ -z "$(git status --porcelain)" ]]
git rev-parse HEAD > "$archive/source-commit.txt"
nvidia-smi > "$archive/gpu-before.txt"
export PYTHONPATH=benchmarks/ToolMaze:.
"$agent_root/.venv/bin/python" -m unittest extensions.execution_memory_059.test_adapter extensions.execution_memory_059.test_smoke tests.test_no_leakage > "$archive/tests.log" 2>&1
"$agent_root/.venv/bin/python" - <<'PY'
import socket
s=socket.socket();s.bind(('127.0.0.1',8000));s.close()
PY
export MODEL_PATH="$agent_root/models/Qwen3-4B-Thinking-2507"
setsid bash "$agent_root/benchmarks/ToolMaze/evaluation/scripts/serve_local_vllm.sh" > "$archive/vllm.log" 2>&1 &
service_pid=$!
ready=0
for attempt in $(seq 1 180); do
 kill -0 "$service_pid"
 if curl -fsS http://127.0.0.1:8000/v1/models > "$archive/models.json"; then ready=1; break; fi
 sleep 5
done
[[ "$ready" == 1 ]]
timeout --signal=TERM 12h "$agent_root/.venv/bin/python" -m extensions.execution_memory_059.agent_smoke --root "$agent_root" --out "$agent_root/results/060-agent-route-smoke-01"
