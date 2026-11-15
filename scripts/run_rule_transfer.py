"""Experiment 048 round 3: simple-rule tables chosen on validation cells, frozen, and
scored on test cells whose hidden parameters differ (registered in section 9).

Usage: python scripts/run_rule_transfer.py <run_id> [round2|round1]
Writes docs/evidence/048/rule-transfer[-round1].json and results/<run_id>/rule-transfer.json.
"""
from array import array
from concurrent.futures import ProcessPoolExecutor
import json
from operator import add
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extensions.toolmaze_recovery import completion_headroom as ch  # noqa: E402

PP = 100.0
LABELS = ("timeout", "error")
HIDDEN = {"round2": ("q_commit", "split", "p_retry", "c_lost", "p_switch", "accuracy",
                     "read_noise", "read_fail", "detail"),
          "round1": ("q_commit", "split", "p_retry", "c_lost", "accuracy", "detail")}
PUBLIC = {"round2": ("left", "backup_calls"), "round1": ("left", "read_fee")}


def compute(cell):
    values, opt = ch.candidate_values(cell)
    return {label: (array("d", c), array("d", f)) for label, (c, f) in values.items()}, opt


def describe(values):
    values = sorted(values)
    return {"cells": len(values), "median": statistics.median(values),
            "p90": values[int(0.9 * (len(values) - 1))], "max": values[-1],
            "share_ge_5pp": sum(v >= 5 for v in values) / len(values),
            "share_ge_10pp": sum(v >= 10 for v in values) / len(values)}


def verdict(d):
    return "headroom" if d["share_ge_10pp"] >= 0.10 else "no_headroom" if d["max"] < 5 else "local_headroom"


class Table:
    """Per-cell candidate values; rule keys use public features only."""

    def __init__(self, cells, rows, public):
        self.cells, self.rows, self.public = cells, rows, public

    def key(self, i, label):
        return tuple(getattr(self.cells[i], k) for k in self.public) + (label,)

    def choose(self, members):
        sums, counts = {}, {}
        for i in members:
            for label in LABELS:
                k = self.key(i, label)
                c, f = self.rows[i][0][label]
                if k in sums:
                    sums[k] = (list(map(add, sums[k][0], c)), list(map(add, sums[k][1], f)))
                else:
                    sums[k] = (list(c), list(f))
                counts[k] = counts.get(k, 0) + 1
        return {k: ch.select(v, counts[k]) for k, v in sums.items()}

    def gaps(self, rules, members):
        """[(OPT - rule completion in pp, relative fee gap when completion ties or None)]."""
        out = []
        for i in members:
            picks = [(self.rows[i][0][label], rules[self.key(i, label)]) for label in LABELS]
            c = sum(v[0][j] for v, j in picks)
            f = sum(v[1][j] for v, j in picks)
            opt = self.rows[i][1]
            fee_gap = (f - opt[1]) / f if abs(opt[0] - c) <= ch.TIE and f > 0 else None
            out.append(((opt[0] - c) * PP, fee_gap))
        return out


def splits(cells, hidden, spec):
    """Registered transfer splits: choose on cells with one value, test on the others."""
    for name in hidden:
        for v in spec[name]:
            val = [i for i, c in enumerate(cells) if getattr(c, name) == v]
            test = [i for i, c in enumerate(cells) if getattr(c, name) != v]
            yield f"{name}={v}", val, test


def main(run_id, which):
    spec = ch.GRID2 if which == "round2" else ch.GRID
    cells = list(ch.grid(spec))
    with ProcessPoolExecutor() as pool:
        rows = list(pool.map(compute, cells, chunksize=8))
    table = Table(cells, rows, PUBLIC[which])
    report = {"experiment": "048", "round": 3, "grid": which, "run_id": run_id,
              "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                       text=True).stdout.strip(),
              "python": platform.python_version(), "cells": len(cells),
              "rule_key": list(PUBLIC[which]) + ["first_detail_label"],
              "candidate_rules_max": max(len(r[0]["timeout"][0]) for r in rows), "splits": {}}
    pooled, pooled_fee = [], []
    for name, val, test in splits(cells, HIDDEN[which], spec):
        g = table.gaps(table.choose(val), test)
        gaps = [x for x, _ in g]
        pooled += gaps
        pooled_fee += [y for _, y in g if y is not None]
        d = describe(gaps)
        report["splits"][name] = {"validation_cells": len(val), **d, "verdict": verdict(d)}
    d = describe(pooled)
    report["transfer_pooled"] = {**d, "verdict": verdict(d),
                                 "fee_gap_rel_when_tied": {"cells": len(pooled_fee),
                                                           "median": statistics.median(pooled_fee),
                                                           "p90": sorted(pooled_fee)[int(0.9 * (len(pooled_fee) - 1))],
                                                           "max": max(pooled_fee)}}
    order = list(range(len(cells)))
    random.Random(4801).shuffle(order)
    half = len(order) // 2
    d = describe([x for x, _ in table.gaps(table.choose(order[:half]), order[half:])])
    report["iid_half"] = {**d, "verdict": verdict(d)}
    every = list(range(len(cells)))
    d = describe([x for x, _ in table.gaps(table.choose(every), every)])
    report["single_table_in_sample"] = {**d, "verdict": verdict(d)}
    d = describe([table.gaps(table.choose([i]), [i])[0][0] for i in every])
    report["per_cell_best_rounds_1_2"] = {**d, "verdict": verdict(d)}
    out = ROOT / "results" / run_id
    out.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=1)
    (out / "rule-transfer.json").write_text(text, encoding="utf-8")
    name = "rule-transfer.json" if which == "round2" else "rule-transfer-round1.json"
    (ROOT / "docs" / "evidence" / "048" / name).write_text(text, encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "splits"}, indent=1))
    for k, v in report["splits"].items():
        print(k, v["validation_cells"], round(v["median"], 2), round(v["p90"], 2), round(v["max"], 2),
              f"{v['share_ge_10pp'] * 100:.1f}%", v["verdict"])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "048-rule-transfer-01",
         sys.argv[2] if len(sys.argv) > 2 else "round2")
