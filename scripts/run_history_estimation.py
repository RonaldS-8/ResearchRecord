"""Experiment 051: history-estimated planning (M) versus the frozen rule table (FR),
the empirical first action (EMP) and the history-selected rule (HR, hybrid).

Usage: python scripts/run_history_estimation.py <run_id>
Writes docs/evidence/051/summary.json and results/<run_id>/cells.jsonl.
"""
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from extensions.toolmaze_recovery import completion_headroom as ch  # noqa: E402
from extensions.toolmaze_recovery import history_estimation as he  # noqa: E402
import run_rule_transfer as rt  # noqa: E402

PP = 100.0
NS = (10, 50, 200)
REPS = 3
PRIMARY_N = 50
CELLS = list(ch.grid(ch.GRID2))
GROUPS = {}
for _i, _c in enumerate(CELLS):
    GROUPS.setdefault((_c.left, _c.backup_calls), []).append(_i)
_DISTS = None
_CACHES = {}


def _init(dists):
    global _DISTS
    _DISTS = dists


def posterior_map(i, counts, exclude_true=False):
    """Index of the most likely hypothesis with the same public key (uniform prior)."""
    best, arg = None, None
    for h in GROUPS[(CELLS[i].left, CELLS[i].backup_calls)]:
        if exclude_true and h == i:
            continue
        ll = he.log_likelihood(_DISTS[h], counts)
        if best is None or ll > best:
            best, arg = ll, h
    return arg


def plan_value(i, h):
    return he.plug_in(CELLS[i], CELLS[h], _CACHES.setdefault(h, {}))


def method_cell(i):
    out = {}
    for n in NS:
        reps = []
        for rep in range(REPS):
            counts = he.sample(_DISTS[i], n, f"050:{i}:{rep}:{n}")
            h, hx = posterior_map(i, counts), posterior_map(i, counts, exclude_true=True)
            emp, choice = he.empirical_first(CELLS[i], counts)
            reps.append({"map": h, "map_excl_true": hx, "m": plan_value(i, h), "m_excl": plan_value(i, hx),
                         "emp": emp, "emp_first": choice})
        out[n] = reps
    if len(_CACHES) > 400:
        _CACHES.clear()
    return out


def describe(values):
    values = sorted(values)
    return {"cells": len(values), "mean": statistics.fmean(values), "median": statistics.median(values),
            "p10": values[int(0.1 * (len(values) - 1))], "p90": values[int(0.9 * (len(values) - 1))],
            "min": values[0], "max": values[-1],
            "share_ge_5pp": sum(v >= 5 for v in values) / len(values),
            "share_ge_10pp": sum(v >= 10 for v in values) / len(values),
            "share_le_minus_5pp": sum(v <= -5 for v in values) / len(values)}


def main(run_id):
    with ProcessPoolExecutor() as pool:
        rows = list(pool.map(rt.compute, CELLS, chunksize=8))
        dists = list(pool.map(he.trajectories, CELLS, chunksize=32))
    table = rt.Table(CELLS, rows, ("left", "backup_calls"))
    best_rule = [{label: ch.select(rows[h][0][label], 1) for label in rt.LABELS} for h in range(len(CELLS))]

    def rule_c(i, picks):
        return sum(rows[i][0][label][0][picks[label]] for label in rt.LABELS)

    with ProcessPoolExecutor(initializer=_init, initargs=(dists,)) as pool:
        method = list(pool.map(method_cell, range(len(CELLS)), chunksize=4))
    out = ROOT / "results" / run_id
    out.mkdir(parents=True, exist_ok=True)
    per_cell = []
    for i, m in enumerate(method):
        row = {"cell": i, "opt": list(rows[i][1])}
        for n, reps in m.items():
            row[str(n)] = {"m": statistics.fmean(r["m"][0] for r in reps),
                           "m_excl": statistics.fmean(r["m_excl"][0] for r in reps),
                           "emp": statistics.fmean(r["emp"][0] for r in reps),
                           "hr": statistics.fmean(rule_c(i, best_rule[r["map"]]) for r in reps),
                           "map_is_true": sum(r["map"] == i for r in reps) / len(reps),
                           "fee_m": statistics.fmean(r["m"][1] for r in reps)}
        per_cell.append(row)
    with open(out / "cells.jsonl", "w", encoding="utf-8") as f:
        for r in per_cell:
            f.write(json.dumps(r) + "\n")

    report = {"experiment": "051", "run_id": run_id,
              "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                       text=True).stdout.strip(),
              "python": platform.python_version(), "cells": len(CELLS), "reps": REPS, "by_n": {}}
    splits = [(name, table.choose(val), test) for name, val, test in rt.splits(CELLS, rt.HIDDEN["round2"], ch.GRID2)]
    for n in NS:
        key = str(n)
        diffs = {k: [] for k in ("opt_fr", "m_fr", "m_excl_fr", "emp_fr", "hr_fr", "m_emp", "m_hr", "opt_m")}
        per_split = {}
        for name, rules, test in splits:
            local = []
            for i in test:
                fr = sum(rows[i][0][label][0][rules[table.key(i, label)]] for label in rt.LABELS)
                r, opt = per_cell[i][key], rows[i][1][0]
                vals = {"opt_fr": opt - fr, "m_fr": r["m"] - fr, "m_excl_fr": r["m_excl"] - fr,
                        "emp_fr": r["emp"] - fr, "hr_fr": r["hr"] - fr, "m_emp": r["m"] - r["emp"],
                        "m_hr": r["m"] - r["hr"], "opt_m": opt - r["m"]}
                for k, v in vals.items():
                    diffs[k].append(v * PP)
                local.append((r["m"] - fr) * PP)
            per_split[name] = {"mean_m_minus_fr": statistics.fmean(local),
                               "share_ge_10pp": sum(v >= 10 for v in local) / len(local)}
        summary = {k: describe(v) for k, v in diffs.items()}
        mean_m_fr, share = summary["m_fr"]["mean"], summary["m_fr"]["share_ge_10pp"]
        verdict = "go" if mean_m_fr >= 5 and share >= 0.10 else "no_go" if mean_m_fr < 2 else "uncertain"
        report["by_n"][key] = {
            "pooled_transfer_test_cells_pp": summary,
            "captured_share_of_headroom": mean_m_fr / summary["opt_fr"]["mean"] if summary["opt_fr"]["mean"] else None,
            "map_is_true_rate": statistics.fmean(r[key]["map_is_true"] for r in per_cell),
            "per_split": per_split,
            "verdict" + (" (primary)" if n == PRIMARY_N else ""): verdict}
    text = json.dumps(report, indent=1)
    evidence = ROOT / "docs" / "evidence" / "051"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "summary.json").write_text(text, encoding="utf-8")
    (out / "summary.json").write_text(text, encoding="utf-8")
    for n in NS:
        b = report["by_n"][str(n)]
        s = b["pooled_transfer_test_cells_pp"]
        print(f"N={n}", {k: (round(v["mean"], 2), round(v["share_ge_10pp"] * 100, 1)) for k, v in s.items()},
              "captured", round(b["captured_share_of_headroom"], 3), "map_true", round(b["map_is_true_rate"], 3),
              [v for k, v in b.items() if k.startswith("verdict")])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "050-history-estimation-01")
