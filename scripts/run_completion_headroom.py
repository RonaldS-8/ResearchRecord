"""Experiment 047: evaluate the registered grid and write per-cell values and a summary.

Usage: python scripts/run_completion_headroom.py <run_id>
Writes results/<run_id>/cells.jsonl (not in Git) and docs/evidence/047/summary.json.
"""
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extensions.toolmaze_recovery import completion_headroom as ch  # noqa: E402

PP = 100.0


def row(cell):
    v = ch.evaluate(cell)
    params = {k: (list(x) if isinstance(x, tuple) else x) for k, x in cell.__dict__.items()}
    return {
        "cell": params,
        **{k: list(v[k]) for k in ("oracle", "opt", "opt_no_read", "fix_x", "fix",
                                   "retry_then_switch", "read_first")},
        "fix_x_seq": {label: [list(seq[0]), seq[1]] for label, seq in v["fix_x_seq"].items()},
        "headroom_pp": (v["opt"][0] - v["fix_x"][0]) * PP,
        "oracle_gap_pp": (v["oracle"][0] - v["opt"][0]) * PP,
        "naive_gap_pp": (v["opt"][0] - v["retry_then_switch"][0]) * PP,
        "read_first_gap_pp": (v["opt"][0] - v["read_first"][0]) * PP,
        "read_value_pp": (v["opt"][0] - v["opt_no_read"][0]) * PP,
        "fee_gap_rel": ((v["fix_x"][1] - v["opt"][1]) / v["fix_x"][1]
                        if abs(v["opt"][0] - v["fix_x"][0]) <= ch.TIE and v["fix_x"][1] > 0 else None),
    }


def describe(values):
    values = sorted(values)
    return {"min": values[0], "median": statistics.median(values), "p90": values[int(0.9 * (len(values) - 1))],
            "max": values[-1], "share_ge_5pp": sum(v >= 5 for v in values) / len(values),
            "share_ge_10pp": sum(v >= 10 for v in values) / len(values)}


def main(run_id):
    cells = list(ch.grid())
    with ProcessPoolExecutor() as pool:
        rows = list(pool.map(row, cells, chunksize=16))
    out = ROOT / "results" / run_id
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "cells.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    headroom = [r["headroom_pp"] for r in rows]
    margins = {}
    for key in ch.GRID:
        groups = defaultdict(list)
        for r in rows:
            groups[json.dumps(r["cell"][key])].append(r["headroom_pp"])
        margins[key] = {k: {"max": max(v), "mean": statistics.mean(v),
                            "share_ge_10pp": sum(x >= 10 for x in v) / len(v)} for k, v in groups.items()}
    fee = [r["fee_gap_rel"] for r in rows if r["fee_gap_rel"] is not None]
    top = sorted(rows, key=lambda r: -r["headroom_pp"])[:10]
    share10, worst = sum(h >= 10 for h in headroom) / len(headroom), max(headroom)
    verdict = ("headroom" if share10 >= 0.10 else "no_headroom" if worst < 5 else "local_headroom")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    summary = {
        "experiment": "047", "run_id": run_id, "commit": commit, "python": platform.python_version(),
        "cells": len(rows), "verdict": verdict,
        "headroom_pp_opt_minus_fix_x": describe(headroom),
        "oracle_minus_opt_pp": describe([r["oracle_gap_pp"] for r in rows]),
        "opt_minus_retry_then_switch_pp": describe([r["naive_gap_pp"] for r in rows]),
        "opt_minus_read_first_pp": describe([r["read_first_gap_pp"] for r in rows]),
        "read_back_value_pp": describe([r["read_value_pp"] for r in rows]),
        "fee_gap_rel_when_completion_tied": {"cells": len(fee), "median": statistics.median(fee) if fee else None,
                                             "max": max(fee) if fee else None},
        "margins_by_parameter": margins,
        "top_cells": top,
    }
    evidence = ROOT / "docs" / "evidence" / "047"
    evidence.mkdir(parents=True, exist_ok=True)
    text = json.dumps(summary, indent=1)
    (evidence / "summary.json").write_text(text, encoding="utf-8")
    (out / "summary.json").write_text(text, encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("cells", "verdict", "headroom_pp_opt_minus_fix_x",
                                              "oracle_minus_opt_pp", "opt_minus_retry_then_switch_pp",
                                              "opt_minus_read_first_pp", "read_back_value_pp",
                                              "fee_gap_rel_when_completion_tied")}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "047-completion-headroom-01")
