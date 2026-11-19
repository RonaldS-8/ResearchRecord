#!/usr/bin/env bash
set -eu
root=/home/ubuntu/Song/Agent
out=$root/results/2_021-gpu-01
mkdir "$out"
exec >"$out/supervisor.log" 2>&1
git rev-parse HEAD >"$out/source-commit.txt"
export PATH="$root/.venv/bin:$PATH" PYTHONPATH="$PWD:$PWD/benchmarks/ToolMaze"
cp "$root/models/Qwen3-8B-AWQ/SHA256SUMS" "$out/model-sha256.txt"
python -c 'import importlib.metadata; print(importlib.metadata.version("vllm"))' >"$out/vllm-version.txt"
if curl -sf http://127.0.0.1:8010/v1/models >/dev/null; then exit 1; fi
vllm serve "$root/models/Qwen3-8B-AWQ" --host 127.0.0.1 --port 8010 --served-model-name Qwen3-8B-AWQ --enable-auto-tool-choice --tool-call-parser hermes --reasoning-parser qwen3 --max-model-len 32768 --max-num-seqs 2 --gpu-memory-utilization 0.85 --enforce-eager --no-enable-prefix-caching >"$out/server.log" 2>&1 &
server=$!
trap 'kill "$server" 2>/dev/null || true' EXIT
for i in {1..90}; do curl -sf http://127.0.0.1:8010/v1/models >"$out/models.json" && break; kill -0 "$server"; sleep 2; done
python -m extensions.route_recovery.run_2021 "$out"
echo completed >"$out/status"
