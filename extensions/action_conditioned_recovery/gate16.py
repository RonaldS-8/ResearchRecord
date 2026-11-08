"""Exact belief and planning comparisons on the dynamic recovery workflow."""
import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
from functools import cache
from itertools import product
import json
from pathlib import Path
import platform
from random import Random
import subprocess

from .gate14 import binary
from .run import execute, require, write
from .workflow16 import PRICES, Progress, Workflow, World, actions, advance, observation

CONFIG = Path(__file__).with_name("gate16.json")
DEFAULTS = {"accuracy": "4/5", "fee": "1", "backup": "1", "budget": 4, "checks": 0, "cue": False}
RULES = ("fixed_retry", "fixed_switch", "semantic", "local_full", "gate15", "q_rule",
         "fixed_continuation", "plan_marginal", "plan_last", "plan_full",
         "plan_independent", "known_mechanism", "oracle")
ZERO = (F(0), F(0), F(0))


def support(cell, w):
    groups = defaultdict(F)
    for z, z3 in product((False, True), repeat=2):
        mass = (1 - w) / 4 + (w / 2 if z == z3 else 0)
        first = binary(z, F(9, 10))
        second = binary(z3, F(9, 10))
        backup = binary(True, F(cell["backup"]))
        route = binary(True, F(cell["q"]))
        cues = binary(z, F(3, 4)) if cell["cue"] else ((None, F(1)),)
        probe = binary(z, F(cell["accuracy"]))
        for a, a3, b, b3, extra, cue, signal in product(first, second, backup, backup, route, cues, probe):
            weight = mass
            for _, likelihood in (a, a3, b, b3, extra, cue, signal):
                weight *= likelihood
            if weight:
                groups[World((a[0], a3[0]), (b[0], b3[0]), extra[0], cue[0], signal[0])] += weight
    return tuple(groups.items())


def rank(value):
    success, tools, diagnosis = value
    return success, -tools - diagnosis


class Planner:
    def __init__(self, cell, w):
        self.support = support(cell, w)
        self.initial = tuple(range(len(self.support)))
        self.cell = cell
        require(sum(m for _, m in self.support) == 1, "Invalid probability mass")
        self.solve = cache(self.solve)
        self.values = cache(self.values)

    def belief(self, view, evidence, known=None):
        cue = next((row["output"]["quality"] for row in view["history"]
                    if "quality" in row["output"]), None)
        facts = [(-1, "cue", cue)] if cue is not None else []
        facts += [(d["slot"], d["action"], d["report"]) for d in view["decisions"]]
        facts = facts if evidence == "full" else facts[-1:] if evidence == "last" else []

        def visible(world, slot, action):
            if action == "cue":
                return world.cue
            if action == "diagnose":
                return world.signal
            return (world.a if action == "A" else world.b)[slot]

        group = tuple(i for i, (world, _) in enumerate(self.support)
                      if (view["slot"] == 0 or world.extra)
                      and (known is None or (world.a, world.b) == known)
                      and all(visible(world, slot, action) == report for slot, action, report in facts))
        require(bool(group), "Observation outside calibrated support")
        return group

    def solve(self, state, group, target=-1, fixed=False):
        if state.terminal or target >= 0 and state.slot > target:
            success = state.terminal == "complete" or target >= 0 and state.slot > target
            return F(success), F(0), F(0)
        options = self.values(state, group, target, fixed)
        if fixed:
            local = self.values(state, group, state.slot, False)
            return options[max(local, key=lambda a: rank(local[a]))]
        return max(options.values(), key=rank)

    def values(self, state, group, target=-1, fixed=False):
        mass = sum(self.support[i][1] for i in group)
        options = {}
        for action in actions(state):
            outcomes = defaultdict(list)
            for i in group:
                outcomes[observation(self.support[i][0], state, action)].append(i)
            value = [F(0), PRICES.get(action, F(0)), F(self.cell["fee"]) if action == "diagnose" else F(0)]
            for observed, indices in outcomes.items():
                weight = sum(self.support[i][1] for i in indices) / mass
                after = advance(state, action, observed)
                for column, v in enumerate(self.solve(after, tuple(indices), target, fixed)):
                    value[column] += weight * v
            options[action] = tuple(value)
        return options

    def closed_form(self, state, group, q):
        """Gate 15's two-slot cost calculation, with optional third-stage routing."""
        if state.slot or state.tried or self.cell["backup"] != "1" or state.budget < 4:
            return self.values(state, group, state.slot if self.cell["backup"] == "1" else -1,
                               self.cell["backup"] != "1")

        def costs(indices):
            m = sum(self.support[i][1] for i in indices)
            p = sum(self.support[i][1] for i in indices if self.support[i][0].a[0]) / m

            def next_cost(subset):
                n = sum(self.support[i][1] for i in subset)
                if not n:
                    return F(0)
                good = sum(self.support[i][1] for i in subset if self.support[i][0].a[1]) / n
                return n / m * min(PRICES["B"], PRICES["A"] + (1 - good) * PRICES["B"])

            good = tuple(i for i in indices if self.support[i][0].a[0])
            bad = tuple(i for i in indices if not self.support[i][0].a[0])
            return {"B": PRICES["B"] + q * next_cost(indices),
                    "A": PRICES["A"] + (1 - p) * PRICES["B"] + q * (next_cost(good) + next_cost(bad))}

        options = {action: (F(1), fee, F(0)) for action, fee in costs(group).items()}
        if state.probe:
            positive = tuple(i for i in group if self.support[i][0].signal)
            negative = tuple(i for i in group if not self.support[i][0].signal)
            mass = sum(self.support[i][1] for i in group)
            expected = sum(sum(self.support[i][1] for i in part) / mass * min(costs(part).values())
                           for part in (positive, negative) if part)
            options["diagnose"] = (F(1), expected, F(self.cell["fee"]))
        options["stop"] = ZERO
        return options


def policy(name, model, view, world=None):
    if name in ("fixed_retry", "fixed_switch"):
        order = ("A", "B", "stop") if name == "fixed_retry" else ("B", "A", "stop")
        return next(a for a in order if a in view["actions"])
    state = Progress(view["slot"], tuple(view["tried"]), view["budget"], "diagnose" in view["actions"])
    evidence = "last" if name in ("semantic", "plan_last") else "marginal" if name == "plan_marginal" else "full"
    group = model.belief(view, evidence, (world.a, world.b) if name == "oracle" else None)
    if name in ("gate15", "q_rule"):
        options = model.closed_form(state, group, F(1) if name == "gate15" else F(view["routing_probability"]))
    else:
        target = state.slot if name in ("semantic", "local_full") else -1
        options = model.values(state, group, target, name == "fixed_continuation")
    return max(options, key=lambda a: rank(options[a]))


def train(config, path):
    rng = Random(config["history_seed"])
    cell = {**DEFAULTS, "q": "1"}
    pool = support(cell, F(3, 4))
    samples = rng.choices([w for w, _ in pool], [float(m) for _, m in pool],
                         k=config["history_size"])
    agreement, rows = 0, []
    for i, world in enumerate(samples):
        row = execute(Workflow(cell, world, instance=f"TRAIN-{i:03}"),
                      lambda view: policy("fixed_retry", None, view))
        require(not row["score"]["issues"] and row["score"]["legal_success"], "Invalid training trace")
        pair = [d["report"] for d in row["decisions"] if d["action"] == "A"]
        require(len(pair) == 2, "History missing a paired observation")
        agreement += pair[0] == pair[1]
        rows.append(row)
    estimate = min(F(1), max(F(0), (F(agreement, len(rows)) - F(1, 2)) / F(8, 25)))
    write(path, {"agreement": agreement, "n": len(rows), "w_estimate": estimate, "rows": rows})
    return estimate, agreement


def run_cell(name, cell, estimate, out):
    truth = F(cell["w"])
    fitted = estimate if name == "unknown_mix" else truth
    known, learned, independent = (Planner(cell, w) for w in (truth, fitted, F(0)))
    result = defaultdict(Counter)
    first_values, public_views = {}, {}
    for index, (world, weight) in enumerate(known.support):
        rows = {}
        start = Workflow(cell, world).view()
        if world.cue not in first_values:
            state = Progress(0, (), cell["budget"], True)
            options = known.values(state, known.belief(start, "full"))
            best = max(options.values(), key=rank)
            first_values[world.cue] = {"values": options,
                                       "optimal": [a for a, v in options.items() if rank(v) == rank(best)]}
        shortest = 1 + int(world.extra) + cell["checks"]
        for label in RULES:
            model = (known if label in ("known_mechanism", "oracle") else
                     independent if label == "plan_independent" else learned)
            choose = lambda view: policy(label, model, view, world if label == "oracle" else None)
            row = execute(Workflow(cell, world), choose)
            require(not row["score"]["issues"], f"Invalid replay {name}/{index}/{label}")
            for view in row["views"][:-1]:
                key = world.cue, tuple(tuple(d.values()) for d in view["decisions"])
                require(view == public_views.setdefault(key, view), "Hidden state leaked")
            term = row["termination"]
            m = result[label]
            for k in ("tool_fee", "diagnostic_fee", "recovery_calls"):
                m[k] += weight * row[k]
            m[term] += weight
            m["redundant_calls"] += weight * (row["recovery_calls"] - shortest if term == "complete" else 0)
            m[f"first_{row['decisions'][0]['action']}"] += weight
            rows[label] = row
        write(out / f"{index:03}.json", {"weight": weight, "world": world._asdict(), "rows": rows})
    expected = [F(0), F(0), F(0)]
    for world, weight in known.support:
        best = max(first_values[world.cue]["values"].values(), key=rank)
        for i, value in enumerate(best):
            expected[i] += weight * value
    require(tuple(expected) == tuple(result["known_mechanism"][key] for key in
                                     ("complete", "tool_fee", "diagnostic_fee")),
            "Known-mechanism plan and replay disagree")
    return {"realizations": len(known.support), "first_action_values": [
        {"cue": cue, **values} for cue, values in first_values.items()], "policies": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    out = parser.parse_args().out
    out.mkdir(parents=True, exist_ok=False)
    config = json.loads(CONFIG.read_text())
    write(out / "config.json", {**config, "defaults": DEFAULTS, "commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True).strip(), "python": platform.python_version(),
        "model": None, "inference_framework": None, "test_seed": None, "complete_btm": "not run"})
    try:
        estimate, agreement = train(config, out / "history.json")
        result = {}
        for name, overrides in config["cells"].items():
            path = out / name
            path.mkdir()
            result[name] = run_cell(name, {**DEFAULTS, **overrides}, estimate, path)
        write(out / "evaluation.json", {"history_agreement": agreement, "w_estimate": estimate, "cells": result})
    except Exception as error:
        write(out / "failure.json", {"error": repr(error)})
        raise


if __name__ == "__main__":
    main()
