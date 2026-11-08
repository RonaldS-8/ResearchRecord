"""Frozen calibration, exact witnesses and seeded paired Gate 17 evaluation."""
import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
import gzip
from itertools import product
import json
from math import log, prod
from pathlib import Path
import platform
from statistics import mean, stdev
import subprocess

from .gate14 import binary
from .gate16 import rank
from .planning17 import HALF, Planner, choose, rate, update
from .run import execute, require, write
from .workflow16 import Progress
from .workflow17 import Tape, Workflow, sample

CONFIG = Path(__file__).with_name("gate17.json")
DEFAULTS = {"q": "1/2", "fee": "1", "accuracy": "4/5", "budget": 6, "checks": 0}
GRID = (F(1, 2), F(3, 4), F(9, 10))
RULES = ("fixed_retry", "fixed_switch", "historical", "current_error", "local_full",
         "recent_plan", "two_slot", "fixed_continuation", "closed_three", "full_plan",
         "known_mechanism", "oracle")
METRICS = ("complete", "blocked_stop", "premature_stop", "exhausted", "tool_fee",
           "diagnostic_fee", "recovery_calls", "redundant_calls")


def model(cell, stay, backup):
    return Planner(cell["q"], stay, backup, cell["accuracy"], cell["fee"])


def likelihood(sequence, stay, accuracy=F(9, 10)):
    p, total = HALF, F(1)
    for report in sequence:
        prob = rate(p, accuracy)
        total *= prob if report else 1 - prob
        p = rate(update(p, report, accuracy), stay)
    return total


def calibrate(config, out, *, emissions=None):
    calibrated = {}
    for cohort, truth in config["cohorts"].items():
        samples = {}
        for split in ("train", "validation"):
            histories, sequences, backups = [], [], []
            families = config["train_families"] if split == "train" else [config["validation_family"]]
            for seed in config[f"{split}_seeds"]:
                for arm in ("A", "B"):
                    cell = {**DEFAULTS, **truth, "q": "1", "backup": "1" if arm == "A" else truth["backup"]}
                    for i in range(config[f"{split}_per_arm"]):
                        family = families[i % len(families)]
                        tape = sample(cell, (split, family, seed, f"{cohort}:{arm}:{i}"))
                        label = "fixed_retry" if arm == "A" else "fixed_switch"
                        row = execute(Workflow(cell, tape), lambda view: choose(label, None, view))
                        require(not row["score"]["issues"], "Invalid calibration replay")
                        if arm == "A":
                            seq = [d["report"] for d in row["decisions"] if d["action"] == "A"]
                            require(len(seq) == 3 and row["score"]["legal_success"], "Incomplete A calibration")
                            sequences.append(seq)
                        else:
                            backups.append(row["decisions"][0]["report"])
                        histories.append({"identity": tape.identity, "row": row})
            samples[split] = (sequences, backups)
            write(out / f"{cohort}-{split}.json", histories)
        seq, b = samples["train"]
        if emissions is None:
            emission = F(9, 10)
            log_likelihoods = {str(s): sum(log(float(likelihood(row, s))) for row in seq) for s in GRID}
            stay = max(GRID, key=lambda s: log_likelihoods[str(s)])
        else:
            counts = Counter(map(tuple, seq))
            candidates = {
                (s, e): prod(likelihood(sequence, s, e) ** n for sequence, n in counts.items())
                for s, e in product(GRID, emissions)
            }
            stay, emission = max(candidates, key=candidates.get)
            log_likelihoods = {
                f"{s},{e}": log(value.numerator) - log(value.denominator)
                for (s, e), value in candidates.items()
            }
        backup = F(sum(b), len(b))
        a_mean = F(sum(sum(row) for row in seq), 3 * len(seq))
        marginal = (max(F(0), min(F(1), (a_mean - (1 - emission)) / (2 * emission - 1)))
                    if emission > HALF else HALF)
        valid_a, valid_b = samples["validation"]
        calibrated[cohort] = {
            "stay": stay, "backup": backup, "marginal": marginal,
            "train_A_sequences": len(seq), "train_B_attempts": len(b), "train_log_likelihoods": log_likelihoods,
            "validation_A_sequences": len(valid_a), "validation_B_attempts": len(valid_b),
            "validation_A_nll": -mean(log(float(likelihood(row, stay, emission))) for row in valid_a),
            "validation_B_frequency": F(sum(valid_b), len(valid_b)),
        }
        if emissions is not None:
            calibrated[cohort].update(
                emission=emission,
                tied_candidates=[list(key) for key, value in candidates.items()
                                 if value == candidates[stay, emission]],
            )
    write(out / "calibration.json", calibrated)
    return calibrated


def witnesses(out):
    report = {}
    for q, expected, best in (("0", F(4), "B"), ("1/2", F(24833, 5000), "A")):
        cell = {**DEFAULTS, "q": q}
        planner = model(cell, F(9, 10), F(1))
        options = planner.values(Progress(0, (), 6, True), HALF)
        require(max(options, key=lambda a: rank(options[a])) == best and options[best][1] == expected,
                "Exact routing witness differs from preregistration")
        replay = []
        weighted_cost = F(0)
        for z0, z1, z2, a0, a1, a2, extra in product((False, True), repeat=7):
            health = (z0, z1, z2)
            a = (a0, a1, a2)
            mass = HALF * (F(q) if extra else 1 - F(q))
            for i in (1, 2):
                mass *= F(9, 10) if health[i] == health[i - 1] else F(1, 10)
            for good, success in zip(health, a):
                mass *= F(9, 10) if good == success else F(1, 10)
            if not mass:
                continue
            tape = Tape(("witness", "invoice", 0, "routing"), a, (True,) * 3, extra, False)
            row = execute(Workflow(cell, tape), lambda view: choose("full_plan", planner, view))
            require(not row["score"]["issues"] and row["score"]["legal_success"]
                    and row["decisions"][0]["action"] == best, "Invalid routing replay")
            weighted_cost += mass * (row["tool_fee"] + row["diagnostic_fee"])
            replay.append({"weight": mass, "row": row})
        require(weighted_cost == expected, "Exact routing replay has wrong fee")
        report[q] = {"values": options, "replays": replay}
    cell = {**DEFAULTS}
    planner = model(cell, F(9, 10), F(1))
    tape = Tape(("witness", "invoice", 0, "quality"), (True,) * 3, (True,) * 3, True, True)
    quality = []
    for first, belief, best in ((True, F(111, 137), "A"), (False, F(39, 113), "B")):
        workflow = Workflow(cell, tape, hints=(first, True), slot=2)
        require(planner.belief(workflow.view()) == belief, "History posterior disagrees")
        row = execute(workflow, lambda view: choose("full_plan", planner, view))
        require(row["decisions"][0]["action"] == best and not row["score"]["issues"],
                "Invalid historical witness")
        quality.append({"posterior": belief, "row": row})
    high, low = (r["row"]["views"][0] for r in quality)
    require({k: v for k, v in high.items() if k != "history"} ==
            {k: v for k, v in low.items() if k != "history"}
            and high["history"][-3:] == low["history"][-3:], "Quality witness start differs")
    report["quality"] = quality
    dead = Tape(("witness", "invoice", 0, "blocked"), (False,) * 3, (False,) * 3, True, False)
    blocked = execute(Workflow(cell, dead), lambda view: choose("fixed_retry", None, view))
    require(blocked["termination"] == "blocked_stop" and not blocked["score"]["issues"], "Invalid stop witness")
    report["blocked"] = blocked
    write(out / "witnesses.json", report)


def test_cell(name, settings, config, calibrated, out):
    cohort = settings["cohort"]
    cell = {**DEFAULTS, **config["cohorts"][cohort], **settings}
    fit = calibrated[cohort]
    learned = model(cell, fit["stay"], fit["backup"])
    known = model(cell, cell["stay"], cell["backup"])
    groups = {}
    with gzip.open(out / f"{name}.jsonl.gz", "xt", encoding="utf-8") as stream:
        for family in config["test_families"]:
            for seed in config["test_seeds"]:
                totals = defaultdict(Counter)
                for i in range(config["test_per_family"]):
                    # Cells share external events when their public intervention changes.
                    identity = ("test", family, seed, i)
                    tape = sample(cell, identity)
                    initial, rows = Workflow(cell, tape).view(), {}
                    require(tape == sample(cell, identity),
                            "Random-key reproducibility failed")
                    for label in RULES:
                        planner = known if label == "known_mechanism" else learned
                        row = execute(Workflow(cell, tape), lambda view: choose(
                            label, planner, view, fit["marginal"], tape if label == "oracle" else None))
                        require(row["views"][0] == initial and not row["score"]["issues"],
                                f"Invalid paired replay: {name}/{seed}/{family}/{i}/{label}")
                        m = totals[label]
                        m[row["termination"]] += 1
                        for k in ("tool_fee", "diagnostic_fee", "recovery_calls"):
                            m[k] += row[k]
                        if row["score"]["legal_success"]:
                            m["redundant_calls"] += row["recovery_calls"] - 2 - int(tape.extra) - cell["checks"]
                        m["first_" + row["decisions"][0]["action"]] += 1
                        rows[label] = row
                    stream.write(json.dumps({"tape": tape._asdict(), "rows": rows},
                                            default=str, ensure_ascii=False) + "\n")
                groups.setdefault(family, {})[str(seed)] = totals
    summaries = {}
    n = config["test_per_family"]
    for family, seeds in groups.items():
        summary = {}
        for label in RULES:
            per_seed = [{k: float(totals[label][k] / n) for k in METRICS} for totals in seeds.values()]
            summary[label] = {k: {"mean": mean(row[k] for row in per_seed),
                                  "sd": stdev(row[k] for row in per_seed)} for k in METRICS}
        pairs = {}
        for other in ("current_error", "recent_plan", "local_full", "two_slot", "closed_three",
                      "fixed_continuation"):
            per_seed = []
            for seed, totals in seeds.items():
                a, b = totals["full_plan"], totals[other]
                gain = (b["tool_fee"] + b["diagnostic_fee"]) - (a["tool_fee"] + a["diagnostic_fee"])
                per_seed.append({"seed": seed, "completion_gain": F(a["complete"] - b["complete"], n),
                                 "cost_saving": gain / n})
            pairs[other] = per_seed
        summaries[family] = {"summary": summary, "paired": pairs}
    return {"n_per_family_seed": n, "groups": groups, "summaries": summaries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    out = parser.parse_args().out
    out.mkdir(parents=True, exist_ok=False)
    config = json.loads(CONFIG.read_text())
    write(out / "config.json", {**config, "defaults": DEFAULTS, "commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True).strip(), "python": platform.python_version(),
        "model": None, "inference_framework": None, "complete_btm": "not run"})
    try:
        witnesses(out)
        calibrated = calibrate(config, out)
        result = {}
        for name, settings in config["cells"].items():
            result[name] = test_cell(name, settings, config, calibrated, out)
        write(out / "evaluation.json", result)
    except Exception as error:
        write(out / "failure.json", {"error": repr(error)})
        raise


if __name__ == "__main__":
    main()
