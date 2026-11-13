"""Experiment 041 (Gate 41) cells and rounds. Registered in docs/experiments/041-*.md before each run.

All values are references inside the CPU environment model; none is an estimate of
what an LLM agent achieves.
"""
import argparse
from collections import defaultdict
from fractions import Fraction as Q
from hashlib import sha256
from itertools import combinations_with_replacement, permutations, product
import json
from math import sqrt
from pathlib import Path
import subprocess

from . import autoresearch as ar
from . import autoresearch_rounds as rounds40
from . import multipath as mp
from .multipath import DONE, PASS, START, Fault, Prices, Step

DEV_SEEDS, HELD_SEEDS, CONTROL_SEEDS = range(200), range(1000, 1200), range(2000, 2200)
SIZES = (30, 100, 300, 1000, 3000)
MARGIN = Q(1, 20)  # experiment 037's proposed materiality line: 5 points of completion, 5% of fee
TOLERANCES = {"0": Q(0), "0.005": Q(1, 200), "0.01": Q(1, 100), "0.02": Q(1, 50), "0.05": Q(1, 20), "0.1": Q(1, 10)}
INTERVALS = (1.0, 1.64, 1.96, 2.58)


def lift(cell):
    """An experiment 040 cell as a two-route multipath cell with the same names and tie order."""
    if cell.first_detail:
        raise ValueError("A detail on the first timeout is not carried over")
    graph = mp.parallel((((ar.SWITCH,), ar.BACKUP_PATH - 1), ((ar.RETRY,), ar.PRIMARY_PATH - 1)))
    faults = {state: Fault({ar.RETRY: f.retry, ar.SWITCH: f.backup},
                           {ar.RETRY: f.detail} if f.detail else {}, f.signal)
              for state, f in cell.faults.items()}
    roots = tuple((p, x, Prices(((ar.RETRY, quote.primary), (ar.SWITCH, quote.backup)), quote.diagnostic), prior)
                  for p, x, quote, prior in cell.roots)
    return mp.Cell(cell.name, graph, faults, roots, cell.left)


def lift_counts(counts):
    """Experiment 040 action-outcome counts in multipath labels (success of a one-call route is DONE)."""
    return {key: {DONE if seen is True else seen: n for seen, n in outcomes.items()}
            for key, outcomes in counts.items()}


# ---- Cells ----

def exclusive(prior, prices, tail):
    """K routes, each one call plus a shared certain tail; hidden state k means only route k works."""
    names = [f"r{i}" for i in range(len(prior))]
    graph = {START: tuple(Step(name, DONE, tail) for name in names)}
    faults = {name: Fault({other: Q(int(other == name)) for other in names}) for name in names}
    quote = Prices(tuple(zip(names, prices)))
    return mp.build("exclusive", graph, faults, {None: (Q(1), dict(zip(names, prior)))}, ((quote, Q(1)),),
                    left=len(names) + tail)


M3_CONTEXTS = {"X1": (Q(3, 5), Q(1, 5), Q(1, 10), Q(1, 10)), "X2": (Q(1, 10), Q(1, 2), Q(1, 5), Q(1, 5)),
               "X3": (Q(1, 10), Q(1, 10), Q(2, 5), Q(2, 5))}


def m3(left=8, contexts=None):
    """Three ways to obtain the evidence, sharing the write and read-back (ToolMaze C3 style):
    retry the primary read; the backup read followed by a check that fails when the backup
    copy is stale (failing again after the switch); or a dearer archive read that always works.
    The primary and the backup share a gateway, so an outage takes both down."""
    rest = (Step("archive", DONE, 3), Step("primary", DONE, 2))
    graph = {START: (Step("backup", "pending"), *rest), "pending": (Step("validate", DONE, 2), *rest)}

    def fault(primary, backup, validate):
        return Fault({"primary": Q(primary), "backup": Q(backup), "validate": Q(validate), "archive": Q(1)})
    faults = {"transient": fault(1, 1, 1), "persistent": fault(0, 1, 1), "stale": fault(0, 1, 0),
              "outage": fault(0, 0, 1)}
    contexts = contexts or M3_CONTEXTS
    return mp.build(f"M3-{left}", graph, faults,
                    {x: (Q(1, len(contexts)), dict(zip(faults, p))) for x, p in contexts.items()},
                    ((Prices((("archive", Q(3)),)), Q(1)),), left=left)


def m4():
    """Two slots (ToolMaze C4 style): obtain the evidence, then publish. Any evidence serves either
    writer. When the primary's provider is down for good, the writer on the same provider fails too,
    so the task can fail again in the second slot after a switch in the first."""
    graph = {START: (Step("backup", "evidence", 1), Step("primary", "evidence")),
             "evidence": (Step("writer", DONE, 1), Step("altwriter", DONE, 2))}

    def fault(primary, writer):
        return Fault({"primary": Q(primary), "backup": Q(1), "writer": Q(writer), "altwriter": Q(1)})
    faults = {"transient": fault(1, 1), "shared": fault(0, 0), "independent": fault(0, 1)}
    contexts = {"X1": (Q(3, 5), Q(1, 10), Q(3, 10)), "X2": (Q(1, 5), Q(3, 5), Q(1, 5)),
                "X3": (Q(1, 5), Q(1, 5), Q(3, 5))}
    return mp.build("M4", graph, faults,
                    {x: (Q(1, 3), dict(zip(faults, p))) for x, p in contexts.items()}, left=6)


def noisy(tool, clean, blocked, already, cap=2, budget=5):
    """Bench2Robust-style stochastic error of an unblocked tool (their Algorithm 1 as we read it):
    a call fails with probability 1 - clean, except once the tool has failed `cap` times since
    its last success or `budget` stochastic failures have been injected in the episode; then it
    returns clean. `already` counts this tool's stochastic failures before the checkpoint, and
    failures of `blocked` tools are scenario blocks, outside the budget."""
    def chance(events):
        streak = already
        for action, seen in events:
            if action == tool:
                streak = 0 if seen == PASS else streak + 1
        injected = (0 if "lookup" in blocked else 1) + sum(
            action not in blocked and action != ar.DIAGNOSE and seen != PASS for action, seen in events)
        return Q(1) if streak >= cap or injected >= budget else clean
    return chance


def b2r(mix, clean=Q(37, 50)):
    """One fallback-equivalence class under Bench2Robust's scenarios, as a loose reconstruction:
    S1 noise only, S2 one side blocked for the episode (either side with equal chance), S3 both
    blocked. Only explicit errors are modelled (0.26 per call); silent corruptions are not. The
    prior is the posterior over scenarios given that the first lookup call failed."""
    graph = {START: (Step("alt", DONE, 3), Step("lookup", DONE, 2))}
    states = {"S1": (), "S2_lookup_blocked": ("lookup",), "S2_alt_blocked": ("alt",), "S3": ("lookup", "alt")}
    faults = {name: Fault({tool: Q(0) if tool in blocked else noisy(tool, clean, blocked, int(tool == "lookup"))
                           for tool in ("lookup", "alt")}) for name, blocked in states.items()}
    s1, s2, s3 = mix
    weights = {"S1": s1 * (1 - clean), "S2_lookup_blocked": s2 / 2, "S2_alt_blocked": s2 / 2 * (1 - clean),
               "S3": s3}
    total = sum(weights.values())
    return mp.build("B2R-mini", graph, faults, {None: (Q(1), {k: w / total for k, w in weights.items() if w})},
                    left=6)


def dev_cells():
    """Cells already seen in experiment 040; used to choose the comparison rule."""
    old = rounds40.cells()
    return {"A": lift(old["A"]), "D": lift(old["D"]), "G": lift(old["G"]), "S4": lift(rounds40.composite()),
            "U_0.7": lift(rounds40.binary("U", rounds40.one(Q(9, 10)), backup=Q(7, 10))),
            "E": lift(old["E"]),
            "E_placebo": lift(rounds40.binary("E0", rounds40.one(Q(1, 2)),
                                              ((ar.Quote(diagnostic=Q(1, 10)), Q(1)),), Q(1, 2)))}


def held_cells():
    """Cells never run before the comparison rule is frozen."""
    composite = rounds40.composite()
    priors = ((Q(2, 5), Q(3, 10), Q(1, 5), Q(1, 10)), (Q(1, 5), Q(1, 5), Q(1, 5), Q(2, 5)),
              (Q(1, 10), Q(2, 5), Q(2, 5), Q(1, 10)))
    shifted = ar.build("S4b", composite.faults,
                       {f"X{i + 1}": (Q(1, 3), dict(zip(composite.faults, p))) for i, p in enumerate(priors)})
    blocked = ar.build("Gb", {"fast": ar.Fault(Q(1)), "persistent": ar.Fault(Q(0)), "blocked": ar.Fault(Q(0), Q(0))},
                       {None: (Q(1), {"fast": Q(3, 10), "persistent": Q(3, 10), "blocked": Q(2, 5)})})
    return {"M3-8": m3(8), "M3-6": m3(6), "M4": m4(), "B2R-mini": b2r((Q(2, 5), Q(1, 2), Q(1, 10))),
            "S4b": lift(shifted), "Gb": lift(blocked),
            "U_0.85": lift(rounds40.binary("Ub", rounds40.one(Q(7, 10)), backup=Q(17, 20)))}


# ---- Exact references and metrics ----

def show(pair):
    return [str(pair[0]), str(pair[1]), round(float(pair[1]), 4)]


def loss(pair, best):
    if pair[0] != best[0]:
        return f"completion {float(pair[0] - best[0]):+.4f}"
    return f"{float((pair[1] - best[1]) / best[1] * 100):.2f}%" if best[1] else "0.00%"


def material(a, b):
    """a is materially worse than b: 5 points less completion, or within 5 points and 5% dearer."""
    return b[0] - a[0] >= MARGIN or (abs(b[0] - a[0]) < MARGIN and a[1] >= b[1] * (1 + MARGIN))


def tools(cell):
    return list(dict.fromkeys(step.tool for steps in cell.graph.values() for step in steps))


def strongest_order(cell, limits=(0, 1, 2)):
    """Best fixed priority order by exact value: every permutation of the tools, every failure limit."""
    names, best = tools(cell), None
    for order in permutations(names):
        for caps in product(limits, repeat=len(names)):
            got = mp.value(cell, mp.priority(order, dict(zip(order, caps))))
            if best is None or ar.better(got, best[1]):
                best = ([f"{tool}x{cap}" for tool, cap in zip(order, caps) if cap], got)
    return best


def only(cell, x):
    roots = tuple(r for r in cell.roots if r[1] == x)
    total = sum(r[0] for r in roots)
    return mp.Cell(cell.name, cell.graph, cell.faults, tuple((r[0] / total, *r[1:]) for r in roots), cell.left)


def exact_table(cell, limits=(0, 1, 2)):
    best, blind, order = mp.value(cell), mp.value(cell, sees=()), strongest_order(cell, limits)
    contexts = list(dict.fromkeys(r[1] for r in cell.roots))
    per_context, plans = (Q(), Q()), {}
    for x in contexts:
        part = only(cell, x)
        weight = sum(r[0] for r in cell.roots if r[1] == x)
        plan, got = strongest_order(part, limits)
        plans[str(x)] = {"order": plan, "value": show(got), "optimum": show(mp.value(part)),
                         "first_actions": {a: show(v) for a, v in mp.first_values(part, x, part.roots[0][2]).items()}}
        per_context = (per_context[0] + weight * got[0], per_context[1] + weight * got[1])
    names = tools(cell)
    fallback = [t for t in names if t not in ("primary", "lookup", ar.RETRY)]
    primary = [t for t in names if t not in fallback]
    named = {"primary_once_then_fallbacks": mp.priority(primary + fallback),
             "primary_twice_then_fallbacks": mp.priority(primary + fallback, {t: 2 for t in primary}),
             "fallbacks_then_primary": mp.priority(fallback + primary)}
    return {"public_optimum": show(best), "oracle": show(mp.oracle(cell)),
            "blind_optimum_no_public_information": show(blind) + [loss(blind, best)],
            "strongest_fixed_order": {"order": order[0], "value": show(order[1]) + [loss(order[1], best)]},
            "context_rule_best_order_per_context": show(per_context) + [loss(per_context, best)],
            "per_context": plans,
            "named_rules": {k: show(mp.value(cell, r)) + [loss(mp.value(cell, r), best)] for k, r in named.items()}}


class Reference:
    """Exact values a learned policy is scored against at each public root."""

    def __init__(self, cell):
        self.cell, self.best, self.roots = cell, mp.value(cell), []
        for (x, quote), mass in mp.groups(cell, mp.PUBLIC).items():
            first = mp.first_values(cell, x, quote)
            top = max(first.values(), key=lambda v: (v[0], -v[1]))
            self.roots.append((x, quote, sum(mass.values(), Q()), {a for a, v in first.items() if v == top},
                               {a for a, v in first.items() if not material(v, top)}))

    def score(self, policy):
        got = {"completion": Q(), "fee": Q(), "wrong": Q(), "wrong_material": Q(), "supported": 0.0,
               "bias": 0.0, "error": 0.0, "covered": 0.0, "fee_bias": 0.0}
        for x, quote, weight, good, fine in self.roots:
            completion, fee = mp.at_root(self.cell, policy, x, quote)
            first = policy(mp.View(x, quote, (), self.cell.left, self.cell.graph))
            got["completion"] += weight * completion
            got["fee"] += weight * fee
            got["wrong"] += weight * (first not in good)
            got["wrong_material"] += weight * (first not in fine)
            if isinstance(policy, mp.Planner):
                _, estimate, values = policy.node(policy.key(x, quote), quote, (), self.cell.left)
                if len(values) > 1:
                    gap = float(estimate[0] - completion)
                    got["supported"] += float(weight)
                    got["bias"] += float(weight) * gap
                    got["error"] += float(weight) * abs(gap)
                    got["covered"] += float(weight) * (abs(gap) <= 1.96 * sqrt(estimate[2]) + 1e-12)
                    got["fee_bias"] += float(weight) * float(estimate[1] - fee)
        return got


def learn(train, test, logging, sizes, compare, seeds, insider=False, extra=None):
    """Fit once per history seed and size, then score every comparison rule exactly on the test cell.
    A smaller size is a prefix of the same seed's larger sample."""
    reference = Reference(test)
    names = list(compare) + list(extra or {})
    table = {n: {name: defaultdict(float) for name in names} for n in sizes}
    for seed in seeds:
        rows = mp.simulate(train, logging, max(sizes), seed, insider)
        for n in sizes:
            counts = mp.fit(rows[:n])
            for name in names:
                policy = (mp.Planner(counts, test, compare=compare[name]) if name in compare
                          else extra[name](counts, rows[:n]))
                got, cell = reference.score(policy), table[n][name]
                pair = (got["completion"], got["fee"])
                cell["optimal"] += pair == reference.best
                cell["material_regret"] += material(pair, reference.best)
                for key in ("completion", "fee", "wrong", "wrong_material", "supported", "bias", "error",
                            "covered", "fee_bias"):
                    cell[key] += float(got[key])
    count = len(seeds)

    def row(c):
        found = {"optimal_seeds": int(c["optimal"]), "material_regret_seeds": int(c["material_regret"]),
                 "mean_completion": round(c["completion"] / count, 5), "mean_fee": round(c["fee"] / count, 4),
                 "wrong_first_action": round(c["wrong"] / count, 4),
                 "materially_wrong_first_action": round(c["wrong_material"] / count, 4)}
        if c["supported"]:
            found.update({"supported_roots": round(c["supported"] / count, 4),
                          "completion_estimate_bias": round(c["bias"] / c["supported"], 5),
                          "completion_estimate_error": round(c["error"] / c["supported"], 5),
                          "interval_95_coverage": round(c["covered"] / c["supported"], 4),
                          "fee_estimate_bias": round(c["fee_bias"] / c["supported"], 4)})
        return found
    return {"public_optimum": show(reference.best), "seeds": count,
            "by_size": {n: {name: row(c) for name, c in by.items()} for n, by in table.items()}}


def rules():
    found = {f"tol_{k}": ("tolerance", d) for k, d in TOLERANCES.items()}
    for z in INTERVALS:
        found[f"ci_{z}_guard"] = ("interval", z, True)
        found[f"ci_{z}"] = ("interval", z, False)
    found["lcb_1.64"] = ("lcb", 1.64)
    return found


def learned_orders(cell, tolerance):
    """Fixed priority orders chosen on the planner's own estimates: one for all tasks, or one per x."""
    names = tools(cell)
    candidates = {f"{'>'.join(order)}x{cap}": mp.priority(order, {t: cap for t in order})
                  for size in range(1, len(names) + 1) for order in permutations(names, size) for cap in (1, 2)}

    def tasks(rows):
        return [(Q(1, len(rows)), r["x"], r["quote"]) for r in rows]

    def one(counts, rows):
        planner = mp.Planner(counts, cell, compare=("tolerance", tolerance))
        return candidates[planner.select(candidates, tasks(rows), cell.left)]

    def per_context(counts, rows):
        planner = mp.Planner(counts, cell, compare=("tolerance", tolerance))
        return mp.by_context({x: candidates[planner.select(candidates, [t for t in tasks(rows) if t[1] == x],
                                                            cell.left)] for x in {r["x"] for r in rows}})
    return {"learned_fixed_order": one, "learned_context_order": per_context}


# ---- Rounds ----

def round_a1():
    """Exclusive routes: blind search cost against its closed form, and the two-path cap."""
    rows, mismatches, above = [], 0, []
    shapes = {"uniform": lambda k: [Q(1, k)] * k,
              "halving": lambda k: [Q(1, 2 ** (i + 1)) for i in range(k - 1)] + [Q(1, 2 ** (k - 1))],
              "skewed": lambda k: [Q(7, 10)] + [Q(3, 10 * (k - 1))] * (k - 1)}
    for k, price, tail, (shape, make) in product((2, 3, 4), (Q(1), Q(2), Q(3)), (0, 2, 3), shapes.items()):
        prior = make(k)
        cell = exclusive(prior, [price] * k, tail)
        blind, best, top = mp.value(cell, sees=()), mp.value(cell), mp.oracle(cell)
        wasted = price * sum(i * p for i, p in enumerate(sorted(prior, reverse=True)))
        closed = (Q(1), wasted + price + tail)
        relative = (blind[1] - top[1]) / blind[1]
        cap = (k - 1) * price / (2 * (price + tail) + (k - 1) * price)
        mismatches += blind != closed or best != blind or top != (1, price + tail) or relative > cap
        record = {"routes": k, "price": str(price), "tail": tail, "prior": shape, "blind_optimum": show(blind),
                  "oracle": show(top), "relative_headroom": str(relative), "percent": round(float(relative) * 100, 2),
                  "uniform_cap": str(cap)}
        rows.append(record)
        if relative > Q(1, 4):
            above.append(record)
    mixed = exclusive([Q(1, 5), Q(3, 10), Q(1, 2)], [Q(1), Q(2), Q(3)], 2)
    return {"cells": len(rows), "closed_form_or_cap_mismatches": mismatches,
            "cells_above_the_two_path_cap_of_one_quarter": len(above), "above": above,
            "fixture_like_price_1_tail_2": [r for r in rows if r["price"] == "1" and r["tail"] == 2
                                            and r["prior"] == "uniform"],
            "largest": max(rows, key=lambda r: Q(r["relative_headroom"])),
            "unequal_prices_prior_0.2_0.3_0.5": {"blind_optimum": show(mp.value(mixed, sees=())),
                                                  "ratio_rule_prediction": "6", "oracle": show(mp.oracle(mixed))}}


def round_a2():
    out = {"M3-8": exact_table(m3(8)), "M3-6": exact_table(m3(6)), "M4": exact_table(m4())}
    for label, mix in (("phase4_40_50_10", (Q(2, 5), Q(1, 2), Q(1, 10))), ("phase1_100_0_0", (Q(1), Q(0), Q(0))),
                       ("solvable_50_50_0", (Q(1, 2), Q(1, 2), Q(0)))):
        cell = b2r(mix)
        out[f"B2R-mini/{label}"] = {
            "prior_after_first_failure": {state: str(p) for state, p in cell.roots[0][3]},
            **exact_table(cell, limits=(0, 1, 2, 3)),
            "pass_rate_only_if_fees_ignored": {
                name: str(mp.value(cell, rule)[0]) for name, rule in (
                    ("retry_until_exhausted_then_alt", mp.priority(("lookup", "alt"), {"lookup": 3, "alt": 3})),
                    ("alt_until_exhausted_then_retry", mp.priority(("alt", "lookup"), {"lookup": 3, "alt": 3})),
                    ("retry_once_then_alt_once", mp.priority(("lookup", "alt"))))}}
    return out


def round_a3():
    """How much context is worth in the M3 structure over a grid of two-context priors."""
    grid = [tuple(Q(n, 4) for n in parts) for parts in product(range(5), repeat=4) if sum(parts) == 4]
    out = {}
    for left in (8, 6):
        context, top, gaps, largest = [], [], 0, None
        for first, second in combinations_with_replacement(grid, 2):
            cell = m3(left, {"Xa": first, "Xb": second})
            best, blind, known = mp.value(cell), mp.value(cell, sees=()), mp.oracle(cell)
            if blind[0] != best[0]:
                gaps += 1
                continue
            saved = (blind[1] - best[1]) / blind[1] if blind[1] else Q(0)
            context.append(saved)
            top.append((blind[1] - known[1]) / blind[1] if blind[1] and known[0] == blind[0] else Q(0))
            if largest is None or saved > largest[0]:
                largest = (saved, [str(p) for p in first], [str(p) for p in second], show(best), show(blind))
        context.sort()
        top.sort()

        def quantiles(values):
            return {q: round(float(values[int(q * (len(values) - 1))]) * 100, 2) for q in (0.5, 0.75, 0.9, 0.99, 1.0)}
        out[f"calls_left_{left}"] = {
            "prior_pairs": len(context) + gaps, "pairs_where_blind_optimum_loses_completion": gaps,
            "context_headroom_percent_quantiles": quantiles(context),
            "pairs_with_context_headroom_at_least_5_percent": sum(v >= MARGIN for v in context),
            "oracle_headroom_percent_quantiles": quantiles(top),
            "largest_context_headroom": {"percent": round(float(largest[0]) * 100, 2), "first_prior": largest[1],
                                         "second_prior": largest[2], "public_optimum": largest[3],
                                         "blind_optimum": largest[4]}}
    return out


def round_b1():
    """Development ablation of the completion comparison rule on cells seen in experiment 040."""
    return {name: learn(cell, cell, mp.uniform, SIZES, rules(), DEV_SEEDS) for name, cell in dev_cells().items()}


def choose(developed):
    """Registered selection: lowest share of seeds with material regret over the development
    cells at N = 100, 300, 1000; then fewest materially wrong first actions; then the guard and
    the smaller z for intervals, the smaller tolerance for fixed tolerances."""
    def score(name):
        rows = [cell["by_size"][str(n)][name] for cell in developed.values() for n in (100, 300, 1000)]
        return (sum(r["material_regret_seeds"] for r in rows) / (len(rows) * 200),
                sum(r["materially_wrong_first_action"] for r in rows) / len(rows))
    intervals = [n for n in rules() if n.startswith("ci_")]
    fixed = [n for n in rules() if n.startswith("tol_") and n != "tol_0"]
    interval = min(intervals, key=lambda n: (*score(n), not n.endswith("guard"), float(n.split("_")[1])))
    tolerance = min(fixed, key=lambda n: (*score(n), float(n.split("_")[1])))
    return {"interval": interval, "tolerance": tolerance,
            "scores": {n: [round(v, 4) for v in score(n)] for n in rules()}}


def round_b2(out):
    """Held-out validation, run once with the comparison rules frozen by round b1."""
    chosen = choose(json.loads((out / "roundb1.json").read_text(encoding="utf-8"))["result"])
    all_rules = rules()
    compare = {name: all_rules[name] for name in dict.fromkeys(
        ("tol_0", "tol_0.05", chosen["tolerance"], chosen["interval"], "lcb_1.64"))}
    result = {"frozen_selection": chosen}
    for name, cell in held_cells().items():
        extra = learned_orders(cell, all_rules[chosen["tolerance"]][1])
        exact = {"blind_optimum_no_history": show(mp.value(cell, sees=())),
                 "context_optimum": show(mp.value(cell, sees=("x",)))}
        result[name] = {**exact, **learn(cell, cell, mp.uniform, (100, 300, 1000, 3000), compare, HELD_SEEDS,
                                         extra=extra)}
    return result


def insider(view, rng, state):
    """A logger that saw the hidden state; its log does not say so."""
    if not view.events:
        return ar.RETRY if rng.random() < (0.9 if state == "transient" else 0.1) else ar.SWITCH
    return ar.SWITCH if ar.SWITCH in view.legal() else ar.STOP


def round_b3(out):
    """Negative controls: no support, confounded logs and distribution shift, with the frozen rules."""
    chosen = choose(json.loads((out / "roundb1.json").read_text(encoding="utf-8"))["result"])
    all_rules = rules()
    compare = {name: all_rules[name] for name in dict.fromkeys(("tol_0", chosen["tolerance"], chosen["interval"]))}
    result = {"frozen_selection": {k: chosen[k] for k in ("interval", "tolerance")}, "no_support": {},
              "confounding": {}, "shift": {}}
    simple, three = lift(rounds40.cells()["A"]), m3(8)
    for name, cell, rule in (("A", simple, mp.priority((ar.SWITCH,))),
                             ("M3-8", three, mp.priority(("backup", "validate", "archive", "primary")))):
        result["no_support"][name] = {"logging_rule_value": show(mp.value(cell, rule)),
                                      **learn(cell, cell, mp.deterministic(rule), (1000,), compare, CONTROL_SEEDS)}
    hidden = lift(rounds40.binary("K", rounds40.one(Q(3, 10))))
    result["confounding"] = {"insider_log": learn(hidden, hidden, insider, (1000,), compare, CONTROL_SEEDS, True),
                             "uniform_log": learn(hidden, hidden, mp.uniform, (1000,), compare, CONTROL_SEEDS)}
    for p in (Q(9, 10), Q(3, 10), Q(1, 10)):
        test = lift(rounds40.binary("A", rounds40.one(p)))
        result["shift"][str(p)] = learn(simple, test, mp.uniform, (1000,), compare, CONTROL_SEEDS)
    return result


ROUNDS = {"a1": round_a1, "a2": round_a2, "a3": round_a3, "b1": round_b1, "b2": round_b2, "b3": round_b3}
NEEDS_OUT = ("b2", "b3")


def digest(path):
    """Hash of a result file's "result" field as stored, for comparing runs across machines."""
    result = json.loads(Path(path).read_text(encoding="utf-8"))["result"]
    return sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rounds", default=",".join(ROUNDS))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], text=True).strip())
    for name in args.rounds.split(","):
        # Exclusive creation: an earlier result, including a failed or negative one, is never overwritten.
        path = args.out / f"round{name}.json"
        with path.open("x", encoding="utf-8") as stream:
            result = ROUNDS[name](args.out) if name in NEEDS_OUT else ROUNDS[name]()
            json.dump({"commit": commit, "uncommitted_changes": dirty, "round": name, "result": result},
                      stream, indent=1, ensure_ascii=False)
        print(f"round {name} written, result sha256 {digest(path)}", flush=True)


if __name__ == "__main__":
    main()
