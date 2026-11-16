#!/usr/bin/env bash
# Experiment 055 on LabServer: local Qwen3-4B ranks/proposes recovery routes (offline, no agent loop).
# Run from a clean checkout of the registered commit: bash scripts/run_route_judge.sh
# Needs ToolMaze data at benchmarks/ToolMaze/data (perturbed_tasks/c3). Existing vllm sessions are untouched.
set -euo pipefail
cd "$(dirname "$0")/.."
agent_root=/home/ubuntu/Song/Agent
run="$agent_root/results/055-route-judge-01"
archive="$agent_root/results/055-service-01"
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
"$agent_root/.venv/bin/python" -m unittest tests.test_route_judge tests.test_route_discovery > "$archive/cpu-tests.txt" 2>&1
"$agent_root/.venv/bin/python" - <<'PY'
import socket
s = socket.socket()
try:
    s.bind(('127.0.0.1', 8000))
finally:
    s.close()
PY
setsid bash "$agent_root/benchmarks/ToolMaze/evaluation/scripts/serve_local_vllm.sh" > "$archive/vllm.log" 2>&1 &
service_pid=$!
ready=0
for attempt in $(seq 1 180); do
  kill -0 "$service_pid"
  if curl -fsS http://127.0.0.1:8000/v1/models > "$archive/models.json"; then ready=1; break; fi
  sleep 5
done
[[ "$ready" == 1 ]]
timeout --signal=TERM 12h "$agent_root/.venv/bin/python" -m extensions.toolmaze_recovery.route_judge \
  --data "$agent_root/benchmarks/ToolMaze/data" --output "$run"
