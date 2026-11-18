#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
root=/home/ubuntu/Song/Agent
prefix="$root/results/2_009-agent-path-obligation"
service="${1:-$prefix-service-01}"
output="$prefix-01"
audit="$prefix-audit-01"
[[ ! -e "$output" && ! -e "$audit" ]]
mkdir "$service"
exec > "$service/supervisor.log" 2>&1
pid=''
cleanup() {
  code=$?
  if [[ -n "$pid" ]]; then
    kill -- -"$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  fi
  date --iso-8601=seconds > "$service/ended.txt"
  nvidia-smi > "$service/gpu-after.txt" || true
  printf '%s\n' "$code" > "$service/exit-code"
}
trap cleanup EXIT
date --iso-8601=seconds > "$service/started.txt"
[[ -z "$(git status --porcelain)" ]]
git rev-parse HEAD > "$service/source-commit.txt"
git hash-object AGENTS.md > "$service/rules-blob.txt"
nvidia-smi > "$service/gpu-before.txt"
export PYTHONPATH=benchmarks/ToolMaze:.
export PYTHONHASHSEED=0
python="$root/.venv/bin/python"
"$python" -m unittest extensions.route_recovery.test_2_009 tests.test_no_leakage \
  tests.test_route_discovery tests.test_route_judge > "$service/tests.log" 2>&1
"$python" - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 8000))
PY
if [[ -n "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader)" ]]; then
  echo "A GPU compute process is already active."
  exit 1
fi
export MODEL_PATH="$root/models/Qwen3-4B-Thinking-2507"
setsid bash benchmarks/ToolMaze/evaluation/scripts/serve_local_vllm.sh > "$service/vllm.log" 2>&1 &
pid=$!
date --iso-8601=seconds > "$service/gpu-started.txt"
ready=0
for attempt in $(seq 1 120); do
  kill -0 "$pid"
  if curl -fsS http://127.0.0.1:8000/v1/models > "$service/models.json" 2>/dev/null; then
    ready=1
    break
  fi
  sleep 5
done
[[ "$ready" == 1 ]]
set +e
timeout --signal=TERM 8h "$python" -m extensions.route_recovery.run_2_009 --root "$root" --out "$output"
code=$?
set -e
kill -- -"$pid" 2>/dev/null || true
wait "$pid" 2>/dev/null || true
pid=''
date --iso-8601=seconds > "$service/gpu-ended.txt"
if [[ -f "$output/freeze.json" ]]; then
  "$python" -m extensions.route_recovery.audit_2_009 --root "$root" --run "$output" --out "$audit"
fi
exit "$code"
