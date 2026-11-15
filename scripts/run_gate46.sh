#!/usr/bin/env bash
# Dedicated bounded Gate46 service. Existing vllm tmux sessions are untouched.
set -euo pipefail
cd /tmp/gate47-audit
agent_root=/home/ubuntu/Song/Agent
archive="$agent_root/results/046-service-01"
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
"$agent_root/.venv/bin/python" - <<'PY'
import socket
s=socket.socket()
try:
    s.bind(('127.0.0.1',8000))
finally:
    s.close()
PY
# Resolve the launcher in the original repo so its .venv path remains correct.
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
p=Path('/home/ubuntu/Song/Agent/results/046-service-01')
assert [x['id'] for x in json.loads((p/'models.json').read_text())['data']] == ['Qwen3-4B-Thinking-2507']
log=(p/'vllm.log').read_text()
assert 'enable_prefix_caching=False' in log or "'enable_prefix_caching': False" in log, 'Caching disable not observed in server config'
PY
timeout --signal=TERM 12h "$agent_root/.venv/bin/python" -m extensions.toolmaze_recovery.gate47 gate46 \
  --freeze "$agent_root/results/047-cpu-acceptance-02/freeze/freeze.json" \
  --output "$agent_root/results/046-real-agent-01" --model-path "$MODEL_PATH"
