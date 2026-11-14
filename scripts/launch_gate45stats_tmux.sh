#!/usr/bin/env bash
# Single bounded batch. Preserve the terminal and actual exit code for inspection.
set -euo pipefail
cd /home/ubuntu/Song/Agent
command -v tmux >/dev/null
test ! -e results/045-stat-01
test ! -e results/045-stat-dispatch-01
if tmux has-session -t gate45-stat 2>/dev/null; then
  echo 'gate45-stat session already exists' >&2
  exit 1
fi
mkdir results/045-stat-dispatch-01
tmux new-session -d -s gate45-stat "cd /home/ubuntu/Song/Agent; timeout --signal=TERM --kill-after=60s 20h bash scripts/run_gate45stats.sh > results/045-stat-dispatch-01/dispatch.log 2>&1; result=\$?; printf '%s\\n' \"\$result\" > results/045-stat-dispatch-01/exit-code.txt; exit \"\$result\""
tmux set-window-option -t gate45-stat remain-on-exit on
tmux display-message -p -t gate45-stat '#{session_name} #{pane_pid} #{pane_current_command}' > results/045-stat-dispatch-01/tmux.txt
