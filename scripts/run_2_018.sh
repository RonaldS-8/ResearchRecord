#!/usr/bin/env bash
set -eu
root=/home/ubuntu/Song/Agent
out=$root/results/2_018-gpu-01
mkdir "$out"
exec >"$out/supervisor.log" 2>&1
git rev-parse HEAD >"$out/source-commit.txt"
export PATH="$root/.venv/bin:$PATH" PYTHONPATH="$PWD:$PWD/benchmarks/ToolMaze"
if curl -sf http://127.0.0.1:8010/v1/models >/dev/null; then exit 1; fi
vllm serve "$root/models/Qwen3-4B-Thinking-2507" --host 127.0.0.1 --port 8010 --served-model-name Qwen3-4B-Thinking-2507 --enable-auto-tool-choice --tool-call-parser hermes --reasoning-parser qwen3 --max-model-len 32768 --max-num-seqs 2 --gpu-memory-utilization 0.85 --enforce-eager --no-enable-prefix-caching >"$out/server.log" 2>&1 &
server=$!
trap 'kill "$server" 2>/dev/null || true' EXIT
for i in {1..90}; do curl -sf http://127.0.0.1:8010/v1/models >"$out/models.json" && break; kill -0 "$server"; sleep 2; done
python -m extensions.route_recovery.run_2018 "$out"
echo completed >"$out/status"
