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


def row(cell, vote=False):
    v = ch.evaluate(cell, vote=vote)
    params = {k: (list(x) if isinstance(x, tuple) else x) for k, x in cell.__dict__.items()}
    extra = {}
    if vote:
        extra = {"fix_v": list(v["fix_v"]),
                 "fix_v_rule": {label: [r[0], r[1], list(r[2]), r[3]] for label, r in v["fix_v_rule"].items()},
                 "headroom_v_pp": (v["opt"][0] - v["fix_v"][0]) * PP}
    return {
        "cell": params,
        **{k: list(v[k]) for k in ("oracle", "opt", "opt_no_read", "fix_x", "fix",
                                   "retry_then_switch", "read_first")},
        "fix_x_seq": {label: [list(seq[0]), seq[1]] for label, seq in v["fix_x_seq"].items()},
        **extra,
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


def row_v(cell):
    return row(cell, vote=True)


def main(run_id, round_two=False):
    spec = ch.GRID2 if round_two else ch.GRID
    cells = list(ch.grid(spec))
    with ProcessPoolExecutor() as pool:
        rows = list(pool.map(row_v if round_two else row, cells, chunksize=16))
    out = ROOT / "results" / run_id
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "cells.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    primary = "headroom_v_pp" if round_two else "headroom_pp"
    headroom = [r[primary] for r in rows]
    margins = {}
    for key in spec:
        groups = defaultdict(list)
        for r in rows:
            groups[json.dumps(r["cell"][key])].append(r[primary])
        margins[key] = {k: {"max": max(v), "mean": statistics.mean(v),
                            "share_ge_10pp": sum(x >= 10 for x in v) / len(v)} for k, v in groups.items()}
    fee = [r["fee_gap_rel"] for r in rows if r["fee_gap_rel"] is not None]
    top = sorted(rows, key=lambda r: -r[primary])[:10]
    share10, worst = sum(h >= 10 for h in headroom) / len(headroom), max(headroom)
    verdict = ("headroom" if share10 >= 0.10 else "no_headroom" if worst < 5 else "local_headroom")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    summary = {
        "experiment": "047", "round": 2 if round_two else 1, "run_id": run_id, "commit": commit,
        "python": platform.python_version(), "cells": len(rows), "verdict": verdict,
        "verdict_on": "opt_minus_fix_v" if round_two else "opt_minus_fix_x",
        "headroom_pp_opt_minus_fix_x": describe([r["headroom_pp"] for r in rows]),
        **({"headroom_pp_opt_minus_fix_v": describe(headroom)} if round_two else {}),
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
    (evidence / ("summary-round2.json" if round_two else "summary.json")).write_text(text, encoding="utf-8")
    (out / "summary.json").write_text(text, encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("cells", "verdict", "verdict_on", "headroom_pp_opt_minus_fix_x",
                                              *(("headroom_pp_opt_minus_fix_v",) if round_two else ()),
                                              "oracle_minus_opt_pp", "opt_minus_retry_then_switch_pp",
                                              "opt_minus_read_first_pp", "read_back_value_pp",
                                              "fee_gap_rel_when_completion_tied")}, indent=1))


def vote_row(line):
    """Follow-up for competing explanation 3: per context, the better of the registered
    fixed order and a k-read vote rule; compared with the public optimum."""
    r = json.loads(line)
    params = {k: (tuple(x) if isinstance(x, list) else x) for k, x in r["cell"].items()}
    cell = ch.Cell(**params)
    total, chosen = [0.0, 0.0], {}
    for label, mass in cell.roots().items():
        actions, end = r["fix_x_seq"][label]
        fixed = ch.sequence_value(cell, mass, tuple(actions), end)
        vote = ch.best_vote(cell, mass)
        pick = vote if ch.better(vote[0], fixed) else (fixed, (0, 0, tuple(actions), end))
        total = [total[0] + pick[0][0], total[1] + pick[0][1]]
        chosen[label] = [pick[1][0], pick[1][1], list(pick[1][2]), pick[1][3]]
    return {"cell": r["cell"], "headroom_pp": r["headroom_pp"],
            "vote_headroom_pp": (r["opt"][0] - total[0]) * PP, "vote_rule": chosen}


def followup(run_id):
    out = ROOT / "results" / run_id
    lines = (out / "cells.jsonl").read_text(encoding="utf-8").splitlines()
    with ProcessPoolExecutor() as pool:
        rows = list(pool.map(vote_row, lines, chunksize=16))
    with open(out / "followup-vote.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    after = [r["vote_headroom_pp"] for r in rows]
    report = {"experiment": "047", "followup": "competing explanation 3: k-read vote rule",
              "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                       text=True).stdout.strip(),
              "cells": len(rows), "headroom_pp_opt_minus_best_simple": describe(after),
              "top_cells": sorted(rows, key=lambda r: -r["vote_headroom_pp"])[:5]}
    text = json.dumps(report, indent=1)
    (ROOT / "docs" / "evidence" / "047" / "followup-vote.json").write_text(text, encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("cells", "headroom_pp_opt_minus_best_simple")}, indent=1))


def reread_row(line):
    """Round-2 follow-up: per context, the better of FIX-V and a fixed order that
    repeats an erroring read-back; only cells where the optimum beats FIX-V."""
    r = json.loads(line)
    params = {k: (tuple(x) if isinstance(x, list) else x) for k, x in r["cell"].items()}
    cell = ch.Cell(**params)
    total, chosen = [0.0, 0.0], {}
    for label, mass in cell.roots().items():
        reads, need, actions, end = r["fix_v_rule"][label]
        actions = tuple(actions)
        fixed = (ch.vote_value(cell, mass, reads, need, actions, end) if reads
                 else ch.sequence_value(cell, mass, actions, end))
        reread = ch.best_reread(cell, mass)
        pick = reread if ch.better(reread[0], fixed) else (fixed, ("fix_v", reads, need, list(actions), end))
        total = [total[0] + pick[0][0], total[1] + pick[0][1]]
        chosen[label] = list(pick[1][:1]) + [list(x) if isinstance(x, tuple) else x for x in pick[1][1:]]
    fee_gap = ((total[1] - r["opt"][1]) / total[1]
               if abs(r["opt"][0] - total[0]) <= ch.TIE and total[1] > 0 else None)
    return {"cell": r["cell"], "headroom_v_pp": r["headroom_v_pp"],
            "headroom_vr_pp": (r["opt"][0] - total[0]) * PP, "fee_gap_rel": fee_gap, "rule": chosen}


def followup_round_two(run_id):
    out = ROOT / "results" / run_id
    rows = [json.loads(l) for l in (out / "cells.jsonl").read_text(encoding="utf-8").splitlines()]
    todo = [json.dumps(r) for r in rows if ch.better(tuple(r["opt"]), tuple(r["fix_v"]))]
    with ProcessPoolExecutor() as pool:
        done = list(pool.map(reread_row, todo, chunksize=8))
    with open(out / "followup-reread.jsonl", "w", encoding="utf-8") as f:
        for r in done:
            f.write(json.dumps(r) + "\n")
    # Cells where FIX-V already equals the optimum keep a zero gap on both dimensions.
    after = [r["headroom_vr_pp"] for r in done] + [0.0] * (len(rows) - len(done))
    fees = [r["fee_gap_rel"] for r in done if r["fee_gap_rel"] is not None]
    fees += [0.0] * (len(rows) - len(done))
    report = {"experiment": "047", "round": 2, "followup": "fixed order with erroring read-backs repeated",
              "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                       text=True).stdout.strip(),
              "cells": len(rows), "cells_where_opt_beat_fix_v": len(done),
              "headroom_pp_opt_minus_best_simple": describe(after),
              "fee_gap_rel_when_completion_tied": {"cells": len(fees), "median": statistics.median(fees),
                                                   "p90": sorted(fees)[int(0.9 * (len(fees) - 1))],
                                                   "max": max(fees), "share_ge_5pct": sum(g >= 0.05 for g in fees) / len(fees)},
              "top_cells": sorted(done, key=lambda r: -r["headroom_vr_pp"])[:5]}
    text = json.dumps(report, indent=1)
    (ROOT / "docs" / "evidence" / "047" / "followup-reread-round2.json").write_text(text, encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("cells", "cells_where_opt_beat_fix_v", "headroom_pp_opt_minus_best_simple",
                                             "fee_gap_rel_when_completion_tied")}, indent=1))


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[2] == "followup2":
        followup_round_two(sys.argv[1])
        sys.exit()
    if len(sys.argv) > 2 and sys.argv[2] == "followup":
        followup(sys.argv[1])
    elif len(sys.argv) > 2 and sys.argv[2] == "round2":
        main(sys.argv[1], round_two=True)
    else:
        main(sys.argv[1] if len(sys.argv) > 1 else "047-completion-headroom-01")
