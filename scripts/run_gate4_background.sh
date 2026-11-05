#!/usr/bin/env bash
# Run once on LabServer from repository root. Stops on any failed stage.
set -euo pipefail
run_root="$1"
mkdir "$run_root"
mark() { printf '%s\t%s\n' "$(date -u +%FT%TZ)" "$1" >> "$run_root/stages.log"; }
trap 'run_exit=$?; mark "exit_code=$run_exit"; exit "$run_exit"' EXIT
mark 'tests_started'
.venv/bin/python -m unittest discover -s tests -v > "$run_root/tests.log" 2>&1
mark 'tests_passed_interface_started'
.venv/bin/python -u -m extensions.toolmaze_diagnostic_mvp.run_qwen \
  --stage interface --out "$run_root/interface" > "$run_root/interface.log" 2>&1
mark 'interface_passed_smoke_started'
.venv/bin/python -u -m extensions.toolmaze_diagnostic_mvp.run_qwen \
  --stage smoke --prerequisite "$run_root/interface" --out "$run_root/smoke" > "$run_root/smoke.log" 2>&1
mark 'smoke_passed_full_started'
.venv/bin/python -u -m extensions.toolmaze_diagnostic_mvp.run_qwen \
  --stage full --prerequisite "$run_root/smoke" --out "$run_root/full" > "$run_root/full.log" 2>&1
mark 'full_completed'
