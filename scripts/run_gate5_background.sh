#!/usr/bin/env bash
# Execute only on LabServer. Each stage preserves its files and stops on failure.
set -euo pipefail
run_root="$1"
mkdir "$run_root"
mark() { printf '%s\t%s\n' "$(date -u +%FT%TZ)" "$1" >> "$run_root/stages.log"; }
trap 'run_exit=$?; mark "exit_code=$run_exit"; exit "$run_exit"' EXIT
mark 'tests_started'
.venv/bin/python -m unittest discover -s tests -v > "$run_root/tests.log" 2>&1
mark 'tests_passed_smoke_started'
.venv/bin/python -u -m extensions.toolmaze_diagnostic_mvp.run_stability \
  --stage smoke --out "$run_root/smoke" > "$run_root/smoke.log" 2>&1
mark 'smoke_passed_determinism_started'
.venv/bin/python -u -m extensions.toolmaze_diagnostic_mvp.run_stability \
  --stage determinism --prerequisite "$run_root/smoke" --out "$run_root/determinism" > "$run_root/determinism.log" 2>&1
mark 'determinism_recorded_full_started'
.venv/bin/python -u -m extensions.toolmaze_diagnostic_mvp.run_stability \
  --stage full --prerequisite "$run_root/determinism" --out "$run_root/full" > "$run_root/full.log" 2>&1
mark 'full_completed'
