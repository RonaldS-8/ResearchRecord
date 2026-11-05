#!/usr/bin/env bash
# LabServer only. User-approved ADR-0006 capacity; original server script is intact.
set -euo pipefail
agent_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$agent_root/.venv/bin:$PATH"
exec "$agent_root/.venv/bin/vllm" serve "$agent_root/models/Qwen3-4B-Thinking-2507" \
  --host 127.0.0.1 --port 8000 \
  --served-model-name Qwen3-4B-Thinking-2507 \
  --enable-auto-tool-choice --tool-call-parser hermes --reasoning-parser qwen3 \
  --max-model-len 40960 --max-num-seqs 2 \
  --gpu-memory-utilization 0.90 --enforce-eager
