#!/usr/bin/env bash
# Terminal 1: bash evaluation/scripts/serve_local_vllm.sh
# Terminal 2: run evaluation/scripts/run_eval.py from the ToolMaze root.
set -euo pipefail

AGENT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
MODEL_PATH="${MODEL_PATH:-$AGENT_ROOT/models/Qwen3-4B-Thinking-2507}"
MODEL_NAME="${MODEL_NAME:-Qwen3-4B-Thinking-2507}"
export PATH="$AGENT_ROOT/.venv/bin:$PATH"

# MODEL_PATH selects weights on disk; MODEL_NAME must match agent.model in YAML.
# Qwen3 Thinking requires reasoning parsing; Hermes parses its tool calls.
exec "$AGENT_ROOT/.venv/bin/vllm" serve "$MODEL_PATH" \
  --host 127.0.0.1 \
  --port 8000 \
  --served-model-name "$MODEL_NAME" \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  --reasoning-parser qwen3 \
  --max-model-len 32768 \
  --max-num-seqs 2 \
  --gpu-memory-utilization 0.85 \
  --enforce-eager \
  "$@"
