#!/usr/bin/bash
# Round c4 of experiment 042: 25 parts, 13 at a time, longest first.
cd "D:/users/018574/Research" || exit 1
W=$(cygpath -w "$PWD")
export PYTHONUTF8=1 PYTHONPATH="$W\\benchmarks\\ToolMaze;$W\\tests;$W"
export PY="D:/users/018574/.venvs/researchrecord/Scripts/python.exe"
export OUT=results/043a-r-02-corrected
mkdir -p "$OUT"
run() {
    cell=$1; seeds=$2
    if [ "$seeds" = "-" ]; then
        "$PY" -B -m extensions.toolmaze_recovery.belief_rounds --out "$OUT" --round d1 --cell "$cell" \
            > "$OUT/d1-$cell.log" 2>&1
    else
        "$PY" -B -m extensions.toolmaze_recovery.belief_rounds --out "$OUT" --round d1 --cell "$cell" --seeds "$seeds" \
            > "$OUT/d1-$cell-${seeds/:/-}.log" 2>&1
    fi
}
export -f run
xargs -P 8 -L 1 bash -c 'run "$0" "$1"' <<'JOBS'
M3-8 6000:6010
M3-8 6010:6020
M3-8 6020:6030
M3-8 6030:6040
M3-8 6040:6050
M3-8 6050:6060
thin-M3-8 6000:6015
thin-M3-8 6015:6030
thin-M3-8 6030:6045
thin-M3-8 6045:6060
M5 6000:6015
M5 6015:6030
M5 6030:6045
M5 6045:6060
thin-M5 6000:6020
thin-M5 6020:6040
thin-M5 6040:6060
S4b 6000:6030
S4b 6030:6060
B2R-mini 6000:6030
B2R-mini 6030:6060
E -
E_placebo -
A -
controls -
JOBS
echo "all parts finished: $(cat "$OUT"/*.log | grep -c written) written"
grep -L written "$OUT"/*.log
