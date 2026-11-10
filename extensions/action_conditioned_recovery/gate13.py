"""Pre-registered rule and first-action model feasibility comparison."""
import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
import json
from pathlib import Path
import platform
from random import Random
import subprocess

from .general import Session, facts
from .mvp import rank
from .run import require, write

CONFIG = Path(__file__).with_name("gate13.json")
BASELINES = ("fixed_retry", "fixed_switch", "price_threshold", "gate12_feedback",
             "one_bit", "simple_semantic", "no_history", "action_value")


def history(config):
    rng = Random(config["seed"])
    rows = []
    for family in config["history_families"]:
        for mode, clue, price in config["training"]:
            for arm in ("retry", "switch", mode):
                states = [i < (6 if clue == "hint" else 4)
                          for i in range(config["history_per_arm"])]
                rng.shuffle(states)
                for bad in states:
                    session = Session(family, mode, clue, price, bad)
                    view = session.view()
                    row = session.finish(arm)
                    require(not row["issues"], f"Invalid historical trace: {family}/{arm}")
                    rows.append({"family": family, "view": view, "first": arm,
                                 "assignment_probability": "1/3", **row})
    return rows


def fit(rows):
    groups = defaultdict(list)
    for row in rows:
        public = facts(row["view"])
        mode = next(role for role in public["roles"].values() if role in ("refresh", "verify"))
        for clue in (public["clue"], "pooled"):
            groups[mode, clue, row["first"]].append(row)
    return [
        {"mode": mode, "clue": clue, "action": action, "n": len(rows),
         "complete": F(sum(row["legal_success"] for row in rows), len(rows)),
         "calls": {role: F(n, len(rows)) for role, n in
                   Counter(role for row in rows for role in row["roles"]).items()}}
        for (mode, clue, action), rows in groups.items()
    ]


def estimate(view, public, fitted):
    roles = public["roles"]
    prices = {roles[a["id"]]: F(a["price"]) for a in view["actions"]}
    mode = next(role for role in prices if role in ("refresh", "verify"))
    options = {}
    fallback = []
    for arm in ("switch", "retry", mode):
        row = next((r for r in fitted if (r["mode"], r["clue"], r["action"]) ==
                    (mode, public["clue"], arm)), None)
        if row is None:
            row = next((r for r in fitted if (r["mode"], r["clue"], r["action"]) ==
                        (mode, "pooled", arm)), None)
            fallback.append(f"{arm}:{'pooled' if row is not None else 'default'}")
        if row is None:
            calls = {arm: F(1)}
            if arm == "retry" and mode == "refresh":
                calls["switch"] = F(1, 2)
            elif arm == mode:
                calls["retry"] = F(1) if mode == "refresh" else F(1, 2)
            row = {"complete": F(1, 2) if mode == "verify" and arm != mode else F(1),
                   "calls": calls}
        options[arm] = (row["complete"], sum(prices[k] * n for k, n in row["calls"].items()))
    return max(options, key=lambda arm: rank(options[arm])), fallback


def select(name, view, fitted):
    public = facts(view)
    prices = {public["roles"][a["id"]]: a["price"] for a in view["actions"]}
    if name.startswith("fixed_"):
        return name.removeprefix("fixed_"), []
    if name in ("no_history", "action_value"):
        return estimate(view, public, fitted if name == "action_value" else [])
    p = F(3, 4) if public["clue"] == "hint" and name in ("gate12_feedback", "simple_semantic") else F(1, 2)
    if name == "simple_semantic" and "verify" in prices:
        return "verify", []
    costs = {"switch": prices["switch"], "retry": prices["retry"] + p * prices["switch"]}
    if name == "simple_semantic":
        costs["refresh"] = prices["refresh"] + prices["retry"]
    return min(costs, key=costs.__getitem__), []


def run_rules(config, out):
    training = history(config)
    write(out / "history.json", training)
    fitted = fit(training)
    write(out / "estimates.json", fitted)
    seen = {tuple(row) for row in config["training"]}
    results = []
    for case in config["test"]:
        family, mode, clue, price, label, _ = case
        require(family not in config["history_families"], "Task family overlap")
        if label != "null":
            require(((mode, clue, price) in seen) == (label == "seen"), "Incorrect holdout label")
        initial = None
        comparisons = {}
        for bad in (False, True):
            session = Session(family, mode, clue, price, bad)
            view = session.view()
            require(initial is None or initial == view, "Hidden-state view differs")
            initial = view
            rows = {arm: Session(family, mode, clue, price, bad).finish(arm)
                    for arm in ("retry", "switch", mode, "stop")}
            require(all(not row["issues"] for row in rows.values()), "Execution/ledger mismatch")
            require(any(row["legal_success"] for row in rows.values()), "No valid completion")
            choices = {}
            for name in BASELINES:
                arm, fallback = select(name, view, fitted)
                require(name != "action_value" or not fallback, "Unsupported historical arm")
                choices[name] = {"action": arm, "fallback": fallback, "outcome": rows[arm]}
            comparisons[str(bad)] = {"arms": rows, "policies": choices}
        if label == "seen":
            good, bad = (comparisons[state]["arms"] for state in ("False", "True"))
            require(good["retry"]["legal_success"] and bad[mode]["legal_success"],
                    "Missing legal mechanism contrast")
            require((bad["retry"]["tool_fee"] > good["retry"]["tool_fee"]) if mode == "refresh"
                    else (not bad["retry"]["legal_success"] and bad["retry"]["duplicates"] == 1),
                    "Structural contrast absent")
        result = {"case": case, "view": initial, "comparisons": comparisons}
        write(out / f"{family}-{label}.json", result)
        results.append(result)
    require(len(results) == 6, "Unexpected rule matrix size")
    write(out / "evaluation.json", {"history_count": len(training), "paired_starts": 12,
                                    "model_gate": "pass", "complete_btm": "not run"})
    return results, fitted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    config = json.loads(CONFIG.read_text())
    write(args.out / "config.json", {**config, "commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True).strip(), "python": platform.python_version()})
    try:
        results, fitted = run_rules(config, args.out)
        if args.model:
            from .gate13_qwen import run_model
            run_model(config, args.out, results, fitted)
    except Exception as error:
        write(args.out / "failure.json", {"error": repr(error)})
        raise


if __name__ == "__main__":
    main()
