#!/usr/bin/env bash
set -euo pipefail
cd /tmp/gate47-audit
agent_root=/home/ubuntu/Song/Agent
archive="$agent_root/results/047-api-service-01"
mkdir "$archive"
exec > "$archive/supervisor.log" 2>&1
[[ -z "$(git status --porcelain)" ]]
git rev-parse HEAD > "$archive/source-commit.txt"
# No set -x, no environment dump, no credentials in result files.
set -a
source /tmp/gate47-model.env
set +a
export PYTHONPATH=benchmarks/ToolMaze:tests:.
timeout --signal=TERM 9h "$agent_root/.venv/bin/python" -m extensions.toolmaze_recovery.gate47 api \
  --output "$agent_root/results/047-api-01"
