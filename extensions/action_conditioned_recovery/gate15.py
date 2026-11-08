"""Compare local and cross-slot recovery policies with exact paired replay."""
import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
from itertools import product
import json
from pathlib import Path
import platform
import subprocess
import time

from .mvp import rank, weighted
from .run import execute, require, score, write
from .workflow15 import BACKUPS, PRICE_A, PRICE_B, Workflow

CONFIG = Path(__file__).with_name("gate15.json")
RULES = ("fixed_switch", "fixed_retry", "local_threshold", "one_bit", "semantic",
         "local_action_value", "cross_slot_rule", "task_rate", "public_optimal", "oracle", "stop")


def support(cell):
    states = ((False, False), (True, True)) if cell["shared"] else tuple(product((False, True), repeat=2))
    accuracy = F(cell["accuracy"])
    return [(likelihood / len(states), health, report)
            for health in states
            for report, likelihood in ((health[0], accuracy), (not health[0], 1 - accuracy))]


def public_key(view):
    return tuple((d["slot"], d["action"], d["report"]) for d in view["decisions"])


def enumerate_policy(samples, cell):
    """Branch over legal actions and actual observations using rational weights."""
    plans = {}
    backups = BACKUPS[:cell["backups"]]

    def visit(group, slot, tried, history):
        if slot == 2:
            return F(1), F(0)
        mass = sum(weight for weight, _, _ in group)
        choices = {}
        for action in (*backups, "A", "diagnose", "stop"):
            if action == "stop":
                choices[action] = (F(0), F(0))
                continue
            if (action == "A" and tried) or (action == "diagnose" and history):
                continue
            observations = defaultdict(list)
            for sample in group:
                _, health, signal = sample
                report = signal if action == "diagnose" else health[slot] if action == "A" else True
                observations[report].append(sample)
            branches = []
            for report, subset in observations.items():
                next_slot = slot + int(action != "diagnose" and report)
                next_tried = action == "A" and not report
                path = history + ((slot, action, report),)
                probability = sum(weight for weight, _, _ in subset) / mass
                branches.append((probability, visit(subset, next_slot, next_tried, path)))
            price = F(cell["fee"]) if action == "diagnose" else PRICE_A if action == "A" else PRICE_B
            choices[action] = weighted(branches, price)
        best = max(choices.values(), key=rank)
        plans[history] = {"choices": choices, "optimal": [a for a, v in choices.items() if v == best]}
        return best

    value = visit(samples, 0, False, ())
    return value, plans


def best_current(p):
    retry = PRICE_A + (1 - p) * PRICE_B
    return min(retry, PRICE_B)


def two_slot_costs(p, shared):
    """Costs of choosing either route now, then acting on the resulting evidence."""
    later_switch = best_current(p if shared else F(1, 2))
    later_retry = p * PRICE_A + (1 - p) * PRICE_B if shared else best_current(F(1, 2))
    return {
        "B": PRICE_B + later_switch,
        "A": PRICE_A + (1 - p) * PRICE_B + later_retry,
    }


def rule(name, view):
    if name == "stop":
        return "stop"
    if name in ("fixed_switch", "task_rate") or "A" not in view["actions"]:
        return "B"
    if name == "fixed_retry":
        return "A"
    history = public_key(view)
    shared = view["calibration"]["shared_provider"]
    accuracy = F(view["calibration"]["accuracy"])
    probe = next((report for _, action, report in history if action == "diagnose"), None)
    p1 = F(1, 2) if probe is None else accuracy if probe else 1 - accuracy

    if view["slot"] == 1:
        p = p1 if shared else F(1, 2)
        first_result = next((report for slot, action, report in history if slot == 0 and action == "A"), None)
        if shared and first_result is not None:
            if name in ("semantic", "cross_slot_rule"):
                p = F(first_result)
            elif name == "one_bit" and not first_result:
                p = F(0)
        return "A" if PRICE_A + (1 - p) * PRICE_B < PRICE_B else "B"

    def costs(p):
        if name == "cross_slot_rule":
            return two_slot_costs(p, shared)
        return {"B": PRICE_B, "A": PRICE_A + (1 - p) * PRICE_B}

    current = costs(p1)
    action = min(current, key=current.__getitem__)
    if "diagnose" in view["actions"]:
        # A symmetric probe and the initial 1/2 prior give equally likely reports.
        with_probe = F(view["prices"]["diagnose"]) + (
            min(costs(accuracy).values()) + min(costs(1 - accuracy).values())
        ) / 2
        if with_probe < current[action]:
            return "diagnose"
    return action


def run_cell(cell, out):
    samples = support(cell)
    require(sum(w for w, _, _ in samples) == 1, "Invalid probability mass")
    value, plans = enumerate_policy(samples, cell)
    require(value == (F(1), F(cell["expected"])), "Preregistered optimum mismatch")
    write(out / "plans.json", [{"history": h, **p} for h, p in plans.items()])
    totals = defaultdict(Counter)
    views = {}
    for index, (weight, health, report) in enumerate(samples):
        rows = {}
        for name in RULES:
            if name == "public_optimal":
                choose = lambda view: plans[public_key(view)]["optimal"][0]
            elif name == "oracle":
                choose = lambda view: "A" if health[view["slot"]] else "B"
            else:
                choose = lambda view: rule(name, view)
            row = execute(Workflow(cell, health, report), choose)
            rows[name] = row
            require(not row["score"]["issues"], f"Invalid trace: {name}/{index}")
            require(row["score"]["legal_success"] == (name != "stop"), "Strict completion mismatch")
            for view in row["views"][:-1]:
                key = public_key(view)
                require(view == views.setdefault(key, view), "Public history leaks hidden state")
            metrics = totals[name]
            metrics["complete"] += weight * score(row)[0]
            metrics["tool_fee"] += weight * row["tool_fee"]
            metrics["diagnostic_fee"] += weight * row["diagnostic_fee"]
            metrics["calls"] += weight * row["recovery_calls"]
            metrics["redundant_calls"] += weight * max(0, row["recovery_calls"] - 2 - cell["checks"])
            metrics["premature_stop"] += weight * int(name == "stop")
            metrics[f"first_{row['decisions'][0]['action']}"] += weight
        write(out / f"{index:02}.json", {"weight": weight, "health": health, "probe": report, "rows": rows})
    observed = totals["public_optimal"]
    require((observed["complete"], observed["tool_fee"] + observed["diagnostic_fee"]) == value,
            "Public optimum disagrees with paired replay")
    return {"realizations": len(samples), "optimal_first": plans[()]["optimal"],
            "optimal_first_values": plans[()]["choices"], "policies": totals}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    out = parser.parse_args().out
    out.mkdir(parents=True, exist_ok=False)
    config = json.loads(CONFIG.read_text())
    write(out / "config.json", {**config, "commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True).strip(), "python": platform.python_version(),
        "seed": None, "model": None, "inference_framework": None, "complete_btm": "not run"})
    try:
        result = {}
        for name, cell in config["cells"].items():
            directory = out / name
            directory.mkdir()
            start = time.perf_counter()
            result[name] = run_cell(cell, directory)
            result[name]["elapsed_seconds"] = time.perf_counter() - start
        write(out / "evaluation.json", result)
    except Exception as error:
        write(out / "failure.json", {"error": repr(error)})
        raise


if __name__ == "__main__":
    main()
