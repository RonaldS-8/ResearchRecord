#!/usr/bin/env bash
# LabServer only. Registered exit-wording control: CPU acceptance / four development episodes (experiment 036).
# The vLLM service is started and stopped outside this script, as in Gate 33.
set -euo pipefail
cd /home/ubuntu/Song/Agent
export PYTHONPATH="$PWD/benchmarks/ToolMaze:$PWD/tests:$PWD"
export PYTHONDONTWRITEBYTECODE=1
cpu_dir="${EXIT_WORDING_CPU_DIR:-results/036-exit-wording-cpu-01}"
agent_dir=results/036-exit-wording-agent-01
if [[ "${1:-}" == cpu ]]; then
  mkdir "$cpu_dir"
  git rev-parse HEAD > "$cpu_dir/commit.txt"
  .venv/bin/python -B -m unittest discover -s tests -p 'test_toolmaze*.py' -v > "$cpu_dir/toolmaze-tests-01.log" 2>&1
  .venv/bin/python -B -m unittest discover -s tests -p test_no_leakage.py -v > "$cpu_dir/no-leakage-01.log" 2>&1
  cp "$cpu_dir/commit.txt" "$cpu_dir/passed-commit.txt"
elif [[ "${1:-}" == agent ]]; then
  test "$(cat "$cpu_dir/passed-commit.txt")" = "$(git rev-parse HEAD)"
  mkdir "$agent_dir"
  git rev-parse HEAD > "$agent_dir/commit.txt"
  .venv/bin/python -B -m pip freeze > "$agent_dir/packages.txt"
  nvidia-smi > "$agent_dir/gpu.txt"
  ps -eo pid,args > "$agent_dir/processes.txt"
  .venv/bin/python -B - "$agent_dir/model-revision.json" <<'PY'
import json
from pathlib import Path
import sys
directory = Path('models/Qwen3-4B-Thinking-2507/.cache/huggingface/download')
names = ['config.json', 'tokenizer.json', *[f'model-{i:05d}-of-00003.safetensors' for i in range(1, 4)]]
revisions = {name: (directory / (name + '.metadata')).read_text().splitlines()[0] for name in names}
assert set(revisions.values()) == {'768f209d9ea81521153ed38c47d515654e938aea'}, revisions
Path(sys.argv[1]).write_text(json.dumps(revisions, indent=2))
PY
  # A failed episode keeps its archive and is listed; the remaining registered episodes still run.
  for wording in original removed; do
    for condition in write_not_committed write_response_lost; do
      name="$wording-$condition"
      .venv/bin/python -B -m extensions.toolmaze_recovery.run \
        --task stock-write-recovery --condition "$condition" \
        --start-mode write-checkpoint --seed 3301 --arm react \
        --first-tool lookup_reservations_by_request --exit-wording "$wording" \
        --out "$agent_dir/$name" > "$agent_dir/$name.log" 2>&1 || echo "$name" >> "$agent_dir/failed.txt"
    done
  done
  date -u +%FT%TZ > "$agent_dir/completed.txt"
else
  echo 'Usage: bash scripts/run_exit_wording.sh cpu|agent' >&2
  exit 2
fi
