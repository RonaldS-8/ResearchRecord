"""Experiment 040 cells and rounds. Registered in docs/experiments/040-*.md before each run."""
import argparse
from fractions import Fraction as Q
from itertools import combinations, product
import json
from pathlib import Path
import subprocess

from . import autoresearch as ar
from .autoresearch import (DIAGNOSE, HINTS, PUBLIC, RETRY, STOP, SWITCH, Fault, Planner, Quote, View,
                           build, fixed, value)

SEEDS = range(200)
SIZES = (30, 100, 300, 1000, 3000)
FACTORS = ("x", "quote", "detail", "signal")


def hint(gamma, transient):
    """Diagnostic signal law with accuracy gamma, in the fixture's public labels."""
    right, wrong = (HINTS[0], HINTS[1]) if transient else (HINTS[1], HINTS[0])
    return ((right, gamma), (wrong, 1 - gamma))


def binary(name, contexts, quotes=((Quote(), Q(1)),), gamma=None, backup=Q(1), left=ar.CALLS_LEFT):
    """Fast transient or persistent: contexts is {x: (P(x), P(transient | x))}."""
    faults = {"transient": Fault(Q(1), backup, signal=hint(gamma, True) if gamma else ()),
              "persistent": Fault(Q(0), backup, signal=hint(gamma, False) if gamma else ())}
    return build(name, faults, {x: (px, {"transient": p, "persistent": 1 - p})
                                for x, (px, p) in contexts.items()}, quotes, left=left)


def gate34(distribution, context=None):
    """The registered Gate 34 cells A, B and E as macro cells."""
    if distribution.cell == "B":
        names = (context,) if context else ("X1", "X2")
        contexts = {x: (Q(1, len(names)), distribution.transient_probability(x)) for x in names}
        return binary("B", contexts)
    contexts = {None: (Q(1), distribution.transient_probability())}
    if distribution.cell == "A":
        return binary("A", contexts)
    return binary("E", contexts, ((Quote(diagnostic=distribution.diagnostic_fee), Q(1)),), distribution.gamma)


def one(p):
    return {None: (Q(1), p)}


def cells():
    """Registered cells in fixture prices; C, D, F, G, H follow the experiment 037 lineage drafts."""
    two = {"X1": (Q(1, 2), Q(4, 5)), "X2": (Q(1, 2), Q(1, 5))}
    half = {"fast": Q(1, 2)}
    return {
        "A": binary("A", one(Q(9, 10))),
        "B": binary("B", two),
        "C": binary("C", one(Q(3, 5)), ((Quote(), Q(1, 2)), (Quote(primary=Q(2)), Q(1, 2)))),
        "D": binary("D", one(Q(4, 5)), left=4),
        "E": binary("E", one(Q(1, 2)), ((Quote(diagnostic=Q(1, 10)), Q(1)),), Q(9, 10)),
        "F": build("F", {"fast": Fault(Q(1)),
                         "slow": Fault((Q(0), Q(1)), detail=(("a", Q(4, 5)), ("b", Q(1, 5)))),
                         "persistent": Fault(Q(0), detail=(("a", Q(1, 5)), ("b", Q(4, 5))))},
                   {None: (Q(1), {"fast": Q(1, 2), "slow": Q(1, 4), "persistent": Q(1, 4)})}),
        "G": build("G", {"fast": Fault(Q(1)), "blocked": Fault(Q(0), Q(0))},
                   {None: (Q(1), {**half, "blocked": Q(1, 2)})}),
        "H": build("H", {"fast": Fault(Q(1)), "shared": Fault((Q(0), Q(1)), (Q(0), Q(1)))},
                   {None: (Q(1), {**half, "shared": Q(1, 2)})}),
        "CX": binary("CX", two, tuple((Quote(b), Q(1, 3)) for b in (Q(1, 5), Q(1), Q(5)))),
        "V": binary("V", {f"p{n}": (Q(1, 5), Q(n, 10)) for n in (1, 3, 5, 7, 9)},
                    ((Quote(diagnostic=Q(1, 10)), Q(1, 2)), (Quote(diagnostic=Q(3, 10)), Q(1, 2))), Q(9, 10)),
    }


def show(pair):
    return [str(pair[0]), str(pair[1]), round(float(pair[1]), 4)]


def loss(pair, best):
    """Fee excess over the optimum in percent when completion is equal, else the completion gap."""
    if pair[0] != best[0]:
        return f"completion {float(pair[0] - best[0]):+.4f}"
    return f"{float((pair[1] - best[1]) / best[1] * 100):.2f}%" if best[1] else "0.00%"


def root(cell, policy):
    """First action per (x, quote) root."""
    return {f"{x}|{quote.backup}|{quote.diagnostic}|{quote.primary}": policy(View(x, quote, (), cell.left))
            for _, x, quote, _ in cell.roots}


def optimal_policy(cell, **kwargs):
    table = {}
    value(cell, table=table, **kwargs)
    return lambda view: table[view.x, view.quote, view.events]


def named_rules(cell, history):
    statistics = ar.btm_statistics(history)
    return {"fixed_switch": fixed(0), "fixed_retry": fixed(1), "fixed_retry_twice": fixed(2),
            "fixed_retry_unguarded": fixed(1, guard=False), "retry_then_one_switch": fixed(1, backups=1),
            "simple_feedback_frozen": ar.simple_feedback,
            "btm_style_retry_once": ar.btm_style(statistics),
            "btm_style_compare_switch": ar.btm_style(statistics, None)}, statistics


def learn(train, test, logging, sizes, variants, insider=False, probe=None):
    """For each history seed and size, fit every variant and evaluate it exactly on the test cell.
    A smaller size is a prefix of the same seed's larger sample."""
    best = value(test)
    table = {n: {name: {"optimal": 0, "completion": Q(), "fee": Q(), "worst": None, "probe": 0}
                 for name in variants} for n in sizes}
    for seed in SEEDS:
        rows = ar.simulate(train, logging, max(sizes), seed, insider)
        for n in sizes:
            for name, make in variants.items():
                policy = make(rows[:n])
                got = value(test, policy)
                cell = table[n][name]
                cell["optimal"] += got == best
                cell["completion"] += got[0]
                cell["fee"] += got[1]
                cell["worst"] = got if cell["worst"] is None or ar.better(cell["worst"], got) else cell["worst"]
                if probe:
                    cell["probe"] += probe(policy)
    count = len(SEEDS)
    return {"public_optimum": show(best), "seeds": count, "by_size": {
        n: {name: {"optimal_seeds": c["optimal"], "mean_completion": round(float(c["completion"] / count), 5),
                   "mean_fee": round(float(c["fee"] / count), 4), "worst_seed": show(c["worst"]),
                   **({"probe_seeds": c["probe"]} if probe else {})}
            for name, c in row.items()} for n, row in table.items()}}


def acv(cell, **options):
    return lambda rows: Planner(ar.fit(rows, options.get("key", lambda x, quote: x)), cell.alphabet(), **options)


def round0():
    from .gate34a import Distribution
    out = {}
    cases = {"A": gate34(Distribution("A")), "B": gate34(Distribution("B")),
             "B/X1": gate34(Distribution("B"), "X1"), "B/X2": gate34(Distribution("B"), "X2")}
    for gamma, fee in product((Q(9, 10), Q(4, 5), Q(1, 2)), (Q(1, 10), Q(1, 2))):
        cases[f"E/gamma={gamma}/d={fee}"] = gate34(Distribution("E", gamma, fee))
    for name, cell in cases.items():
        best = value(cell)
        row = {"public_optimum": show(best), "oracle": show(ar.oracle(cell))}
        statistics = {}
        for label, logging in (("uniform", ar.uniform), ("always_switch", ar.deterministic(fixed(0))),
                               ("retry_first", ar.deterministic(fixed(1)))):
            found = ar.btm_statistics(ar.simulate(cell, logging, 3000, 0))
            statistics[label] = {"recovery": {str(k): str(v) for k, v in found["recovery"].items()},
                                 "switch": str(found["switch"])}
        rules, _ = named_rules(cell, ar.simulate(cell, ar.uniform, 3000, 0))
        row["rules"] = {label: show(value(cell, rule)) for label, rule in rules.items()}
        row["btm_statistics_by_logging_policy"] = statistics
        out[name] = row
    return out


def grid():
    """The registered R1 grid: (parameters, quote, optimum fee, cheaper fixed rule's fee)."""
    for p1, p2, gamma, fee, primary, backup in product(
            (Q(1, 10), Q(3, 10), Q(1, 2), Q(7, 10), Q(9, 10)), (Q(1, 10), Q(3, 10), Q(1, 2), Q(7, 10), Q(9, 10)),
            (Q(1, 2), Q(4, 5), Q(9, 10), Q(1)), (Q(0), Q(1, 10), Q(3, 10)), (Q(1), Q(2), Q(3)),
            (Q(1, 5), Q(1), Q(3), Q(5), Q(17))):
        quote = Quote(backup, fee, primary)
        cell = binary("grid", {"X1": (Q(1, 2), p1), "X2": (Q(1, 2), p2)}, ((quote, Q(1)),), gamma)
        best, switch, retry = value(cell), value(cell, fixed(0)), value(cell, fixed(1))
        assert best[0] == switch[0] == retry[0] == 1
        yield (p1, p2, gamma, fee, primary, backup), quote, best[1], min(switch[1], retry[1])


def round1():
    point, top, unit_top, material, violations, count = None, None, None, 0, [], 0
    quantiles = []
    for (p1, p2, gamma, fee, primary, backup), quote, best_fee, simple in grid():
        saving, mean = simple - best_fee, (p1 + p2) / 2
        wasted, premium = primary, max(quote.fee(SWITCH, True) - quote.fee(RETRY, True), Q(0))
        bound = min(mean * premium, (1 - mean) * wasted)
        ceiling = wasted * premium / (wasted + premium)
        count += 1
        if saving > bound or bound > ceiling:
            violations.append([str(v) for v in (p1, p2, gamma, fee, primary, backup, saving, bound, ceiling)])
        relative = saving / simple
        quantiles.append(relative)
        material += relative >= Q(1, 20)
        record = {"relative_headroom": str(relative), "percent": round(float(relative) * 100, 3), "saving": str(saving),
                  "bound": str(bound), "p": [str(p1), str(p2)], "gamma": str(gamma), "diagnostic_fee": str(fee),
                  "primary_price": str(primary), "backup_price": str(backup)}
        if top is None or relative > Q(top["relative_headroom"]):
            top = record
        if primary == backup == 1 and (unit_top is None or relative > Q(unit_top["relative_headroom"])):
            unit_top = record
        if p1 == p2 == Q(1, 2) and gamma == Q(9, 10) and fee == Q(1, 10) and primary == backup == 1:
            point = record
    quantiles.sort()
    return {"grid_cells": count, "bound_violations": violations, "largest_relative_headroom": top,
            "largest_at_unit_prices": unit_top, "gate34_E_like_point": point,
            "cells_with_at_least_5_percent_headroom": material,
            "relative_headroom_quantiles_percent": {q: round(float(quantiles[int(q * (count - 1))]) * 100, 3)
                                                    for q in (0.5, 0.75, 0.9, 0.99, 1.0)}}


def round2():
    out = {}
    for name, cell in cells().items():
        values = {frozenset(s): value(cell, sees=s) for n in range(5) for s in combinations(FACTORS, n)}
        best = values[PUBLIC]
        enough = [s for s, v in values.items() if v == best]
        minimal = sorted(sorted(s) for s in enough if not any(o < s for o in enough))
        rules, statistics = named_rules(cell, ar.simulate(cell, ar.uniform, 3000, 0))
        families = {"no_public_information": values[frozenset()],
                    **{f"only_{f}": values[frozenset((f,))] for f in FACTORS},
                    "btm_information_bound_details_no_diagnostic": value(cell, sees=("detail",), ban=(DIAGNOSE,)),
                    "no_diagnostic": value(cell, ban=(DIAGNOSE,))}
        out[name] = {
            "public_optimum": show(best), "oracle": show(ar.oracle(cell)), "minimal_sufficient_information": minimal,
            "optimal_first_action": root(cell, optimal_policy(cell)),
            "best_rule_reading": {k: show(v) + [loss(v, best)] for k, v in families.items()},
            "named_rules": {k: show(value(cell, r)) + [loss(value(cell, r), best)] for k, r in rules.items()},
            "btm_statistics_uniform_3000": {"recovery": {str(k): str(v) for k, v in statistics["recovery"].items()},
                                            "switch": str(statistics["switch"])}}
    return out


def round3():
    band = []
    for step, gamma, fee in product(range(1, 20), (Q(1, 2), Q(4, 5), Q(9, 10)), (Q(1, 10), Q(3, 10))):
        p = Q(step, 20)
        cell = binary("band", one(p), ((Quote(diagnostic=fee), Q(1)),), gamma)
        best = value(cell)
        buys = root(cell, optimal_policy(cell))[f"None|1|{fee}|1"] == DIAGNOSE
        low = (fee + (1 - gamma)) / (gamma + (1 - gamma))
        high = (gamma - fee) / (gamma + (1 - gamma))
        frozen = value(cell, ar.simple_feedback)
        band.append({"p": str(p), "gamma": str(gamma), "fee": str(fee), "optimum_buys": buys,
                     "closed_form_buys": low < p < high, "optimum": show(best),
                     "simple_feedback": show(frozen), "simple_feedback_loss": loss(frozen, best),
                     "never_buy_loss": loss(value(cell, ban=(DIAGNOSE,)), best)})
    learned = {}
    for label, p, gamma in (("informative", Q(1, 2), Q(9, 10)), ("placebo", Q(1, 2), Q(1, 2)),
                            ("outside_band", Q(9, 10), Q(9, 10))):
        cell = binary(f"R3-{label}", one(p), ((Quote(diagnostic=Q(1, 10)), Q(1)),), gamma)
        learned[label] = {
            "simple_feedback_frozen": show(value(cell, ar.simple_feedback)),
            "best_without_diagnostic": show(value(cell, ban=(DIAGNOSE,))),
            **learn(cell, cell, ar.uniform, SIZES, {"acv": acv(cell), "acv_tolerance_0.05": acv(cell, tolerance=Q(1, 20))},
                    probe=lambda policy, c=cell: policy(View(None, c.roots[0][2], (), c.left)) == DIAGNOSE)}
    return {"band": band, "band_mismatches": sum(r["optimum_buys"] != r["closed_form_buys"] for r in band),
            "learned": learned}


def round4():
    out = {"flaky_backup": {}, "stop": {}, "estimated": {}}
    for beta in (Q(99, 100), Q(9, 10), Q(7, 10)):
        cell = binary("U", one(Q(9, 10)), backup=beta)
        strict, loose = value(cell), value(cell, tolerance=Q(1, 20))
        out["flaky_backup"][str(beta)] = {
            "strict_optimum": show(strict), "strict_first_action": root(cell, optimal_policy(cell)),
            "tolerance_0.05_optimum": show(loose),
            "tolerance_0.05_first_action": root(cell, optimal_policy(cell, tolerance=Q(1, 20))),
            "fixed_retry": show(value(cell, fixed(1))), "fixed_switch": show(value(cell, fixed(0))),
            "predicted_completion_gain_of_switch_first": str(Q(1, 10) * (1 - beta) ** 2 * beta)}
    blocked = build("GD", {"persistent": Fault(Q(0), Q(1), signal=hint(Q(9, 10), True)),
                           "blocked": Fault(Q(0), Q(0), signal=hint(Q(9, 10), False))},
                    {None: (Q(1), {"persistent": Q(1, 2), "blocked": Q(1, 2)})},
                    ((Quote(diagnostic=Q(1, 10)), Q(1)),))

    def buy_and_stop(view):
        if DIAGNOSE in view.legal():
            return DIAGNOSE
        return SWITCH if view.last(DIAGNOSE) == HINTS[0] and not view.count(SWITCH) and SWITCH in view.legal() else STOP
    out["stop"]["GD"] = {"strict_optimum": show(value(blocked)), "strict_first_action": root(blocked, optimal_policy(blocked)),
                         "buy_then_stop_on_blocked_hint": show(value(blocked, buy_and_stop)),
                         "tolerance_0.05_optimum": show(value(blocked, tolerance=Q(1, 20))),
                         "tolerance_0.05_first_action": root(blocked, optimal_policy(blocked, tolerance=Q(1, 20))),
                         "oracle": show(ar.oracle(blocked))}
    for name, cell in {**cells(), "GD": blocked, "U": binary("U", one(Q(9, 10)), backup=Q(9, 10))}.items():
        table = {}
        value(cell, table=table)
        out["stop"].setdefault("stop_nodes_on_optimal_tables", {})[name] = sorted(
            repr(events) for (_, _, events), action in table.items() if action == STOP and len(events) <= 2)
    variants = {"mle_strict": {}, "smoothed_strict": {"smooth": Q(1)},
                "mle_tolerance_0.05": {"tolerance": Q(1, 20)},
                "smoothed_tolerance_0.05": {"smooth": Q(1), "tolerance": Q(1, 20)}}
    for name, cell in (("A", binary("A", one(Q(9, 10)))), ("U_beta_0.9", binary("U", one(Q(9, 10)), backup=Q(9, 10)))):
        out["estimated"][name] = {
            "fixed_retry": show(value(cell, fixed(1))), "fixed_switch": show(value(cell, fixed(0))),
            "tolerance_0.05_optimum": show(value(cell, tolerance=Q(1, 20))),
            **learn(cell, cell, ar.uniform, (100, 300, 1000), {k: acv(cell, **o) for k, o in variants.items()},
                    probe=lambda policy, c=cell: policy(View(None, Quote(), (), c.left)) == RETRY)}
    return out


def mixed(share):
    return lambda view, rng: ar.uniform(view, rng) if rng.random() < share else fixed(0)(view)


def insider(view, rng, state):
    """A logger that saw the hidden state; its log does not say so."""
    if not view.events:
        return RETRY if rng.random() < (0.9 if state == "transient" else 0.1) else SWITCH
    return SWITCH if SWITCH in view.legal() else STOP


def round5():
    out = {"coverage": {}, "confounding": {}, "shift": {}}
    for name in ("A", "B"):
        cell = cells()[name]
        out["coverage"][name] = {str(share): learn(cell, cell, mixed(share), (300,), {"acv": acv(cell)})
                                 for share in (0, 0.1, 0.3, 1)}
    hidden = binary("K", one(Q(3, 10)))
    retries = lambda policy: policy(View(None, Quote(), (), hidden.left)) == RETRY
    for label, logging, inside in (("insider_log", insider, True), ("uniform_log", ar.uniform, False)):
        rows = ar.simulate(hidden, logging, 1000, 0, inside)
        first = ar.fit(rows)[None, (), RETRY]
        found = ar.btm_statistics(rows)
        out["confounding"][label] = {
            "seed0_retry_success_rate": round(first[True] / sum(first.values()), 4), "seed0_retries": sum(first.values()),
            "seed0_btm_recovery": str(found["recovery"][None]), "seed0_btm_switch": str(found["switch"]),
            **learn(hidden, hidden, logging, (1000,), {"acv": acv(hidden)}, insider=inside, probe=retries)}
    out["confounding"]["fixed_retry"] = show(value(hidden, fixed(1)))
    train = cells()["A"]
    for p in (Q(9, 10), Q(7, 10), Q(1, 2), Q(3, 10), Q(1, 10)):
        test = binary("A", one(p))
        best = value(test)
        out["shift"][str(p)] = {
            "fixed_retry": show(value(test, fixed(1))) + [loss(value(test, fixed(1)), best)],
            "fixed_switch": show(value(test, fixed(0))) + [loss(value(test, fixed(0)), best)],
            **learn(train, test, ar.uniform, (1000,), {"acv_trained_on_A": acv(train)})}
    return out


def learned_rules(cell):
    """Simple rules chosen on the same counts and estimator that ACV plans with."""
    orders = {k: (lambda x, k=k: fixed(k)) for k in (0, 1, 2)}
    rates = {f"rate>{n}/10": (lambda x, n=n: ar.cost_threshold(Q(n, 10))) for n in range(1, 10)}

    def tasks(rows):
        return [(Q(1, len(rows)), r["x"], r["quote"]) for r in rows]

    def global_order(rows):
        planner = Planner(ar.fit(rows), cell.alphabet())
        return orders[planner.select(orders, tasks(rows), cell.left)](None)

    def context_rule(rows):
        planner = Planner(ar.fit(rows), cell.alphabet())
        chosen = {x: orders[planner.select(orders, [t for t in tasks(rows) if t[1] == x], cell.left)](x)
                  for x in {r["x"] for r in rows}}
        return lambda view: chosen.get(view.x, fixed(0))(view)

    def threshold(rows):
        planner = Planner(ar.fit(rows), cell.alphabet())
        return rates[planner.select(rates, tasks(rows), cell.left)](None)

    return {"learned_fixed_order": global_order, "learned_context_rule": context_rule,
            "learned_cost_threshold": threshold, "simple_feedback_frozen": lambda rows: ar.simple_feedback,
            "acv": acv(cell), "acv_per_context_and_quote": acv(cell, key=lambda x, quote: (x, quote))}


def round6():
    out, sizes = {}, (100, 300, 1000, 3000)
    for name in ("B", "CX", "F", "V"):
        cell = cells()[name]
        out[name] = learn(cell, cell, ar.uniform, sizes, learned_rules(cell))
    full = cells()["CX"]
    train = binary("CX", {"X1": (Q(1, 2), Q(4, 5)), "X2": (Q(1, 2), Q(1, 5))},
                   tuple((Quote(b), Q(1, 2)) for b in (Q(1, 5), Q(1))))
    test = binary("CX", {"X1": (Q(1, 2), Q(4, 5)), "X2": (Q(1, 2), Q(1, 5))}, ((Quote(Q(5)), Q(1)),))
    out["CX_unseen_backup_price_5"] = learn(train, test, ar.uniform, sizes, learned_rules(full))
    return out


def composite():
    """S4: the four fault types of cells A, G and H together, with context-dependent priors."""
    faults = {"fast": Fault(Q(1)), "shared": Fault((Q(0), Q(1)), (Q(0), Q(1))),
              "persistent": Fault(Q(0)), "blocked": Fault(Q(0), Q(0))}

    def mix(*p):
        return dict(zip(faults, p))
    return build("S4", faults, {"X1": (Q(1, 3), mix(Q(3, 5), Q(1, 5), Q(1, 10), Q(1, 10))),
                                "X2": (Q(1, 3), mix(Q(1, 10), Q(1, 10), Q(2, 5), Q(2, 5))),
                                "X3": (Q(1, 3), mix(Q(3, 10), Q(3, 5), Q(1, 20), Q(1, 20)))})


def order_learners(cell, tolerance=Q()):
    """Fixed attempt orders chosen on the planner's own estimates: one for all tasks, or one per x."""
    orders = {"".join(a[0] for a in seq): ar.order(*seq)
              for n in (1, 2, 3) for seq in product((RETRY, SWITCH), repeat=n)}
    pick = {k: (lambda x, r=r: r) for k, r in orders.items()}

    def tasks(rows):
        return [(Q(1, len(rows)), r["x"], r["quote"]) for r in rows]

    def global_order(rows):
        planner = Planner(ar.fit(rows), cell.alphabet(), tolerance=tolerance)
        return orders[planner.select(pick, tasks(rows), cell.left)]

    def context_order(rows):
        planner = Planner(ar.fit(rows), cell.alphabet(), tolerance=tolerance)
        chosen = {x: orders[planner.select(pick, [t for t in tasks(rows) if t[1] == x], cell.left)]
                  for x in {r["x"] for r in rows}}
        return lambda view: chosen[view.x](view) if view.x in chosen else STOP
    return orders, global_order, context_order


def round7():
    bound = {"violations": 0, "largest_cap": Q(0), "largest_relative": Q(0)}
    for _, quote, best_fee, simple in grid():
        wasted, success = quote.primary, quote.fee(RETRY, True)
        premium = max(quote.fee(SWITCH, True) - success, Q(0))
        cap = wasted * premium / ((wasted + premium) * (success + premium))
        relative = (simple - best_fee) / simple
        bound["violations"] += relative > cap or cap > Q(1, 4)
        bound["largest_cap"] = max(bound["largest_cap"], cap)
        bound["largest_relative"] = max(bound["largest_relative"], relative)
    out = {"relative_bound": {k: str(v) for k, v in bound.items()}}
    cell = composite()
    best = value(cell)
    orders, global_order, context_order = order_learners(cell)
    rules, _ = named_rules(cell, ar.simulate(cell, ar.uniform, 3000, 0))
    table = {}
    value(cell, table=table)
    nothing, context = value(cell, sees=()), value(cell, sees=("x",))
    out["S4"] = {
        "public_optimum": show(best), "oracle": show(ar.oracle(cell)),
        "optimal_plan": {x: [[repr(events), action] for (cx, _, events), action in sorted(table.items(), key=repr)
                             if cx == x and len(events) <= 2] for x in ("X1", "X2", "X3")},
        "best_rule_reading": {"no_public_information": show(nothing) + [loss(nothing, best)],
                              "only_x": show(context) + [loss(context, best)]},
        "fixed_orders": {k: show(value(cell, r)) + [loss(value(cell, r), best)] for k, r in orders.items()},
        "named_rules": {k: show(value(cell, r)) + [loss(value(cell, r), best)] for k, r in rules.items()},
        "learned": learn(cell, cell, ar.uniform, (100, 300, 1000, 3000),
                         {"learned_fixed_order": global_order, "learned_context_order": context_order,
                          "acv": acv(cell)})}
    out["btm_style_variants"] = {}
    for name, target in {**cells(), "S4": cell}.items():
        found = ar.btm_statistics(ar.simulate(target, ar.uniform, 3000, 0))
        top = value(target)
        variants = {"retry_once": ar.btm_style(found), "compare_switch": ar.btm_style(found, None),
                    "bar_4/5": ar.btm_style(found, Q(4, 5)),
                    "retry_once_stop_below_1/2": ar.btm_style(found, poor=Q(1, 2)),
                    "retry_once_stop_below_3/5": ar.btm_style(found, poor=Q(3, 5))}
        out["btm_style_variants"][name] = {
            "public_optimum": show(top),
            "statistics": {"recovery": {str(k): round(float(v), 4) for k, v in found["recovery"].items()},
                           "switch": round(float(found["switch"]), 4)},
            **{k: show(value(target, r)) + [loss(value(target, r), top)] for k, r in variants.items()}}
    return out


def round8():
    """Completion ties within a tolerance, where completion itself has to be estimated."""
    out, sizes = {}, (100, 300, 1000, 3000)
    tolerances = {"0": Q(0), "0.01": Q(1, 100), "0.02": Q(1, 50), "0.05": Q(1, 20), "0.1": Q(1, 10), "0.3": Q(3, 10)}
    targets = {"S4": composite(), "G": cells()["G"], "D": cells()["D"],
               "U_beta_0.7": binary("U", one(Q(9, 10)), backup=Q(7, 10))}
    for name, cell in targets.items():
        variants = {f"acv_tolerance_{k}": acv(cell, tolerance=t) for k, t in tolerances.items()}
        if name == "S4":
            for k in ("0", "0.05"):
                _, global_order, context_order = order_learners(cell, tolerances[k])
                variants[f"learned_fixed_order_tolerance_{k}"] = global_order
                variants[f"learned_context_order_tolerance_{k}"] = context_order
        out[name] = {"strict_optimum": show(value(cell)),
                     "tolerance_0.05_optimum": show(value(cell, tolerance=Q(1, 20))),
                     **learn(cell, cell, ar.uniform, sizes, variants)}
    return out


ROUNDS = {"0": round0, "1": round1, "2": round2, "3": round3, "4": round4, "5": round5, "6": round6,
          "7": round7, "8": round8}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rounds", default="".join(ROUNDS))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], text=True).strip())
    for number in args.rounds:
        # Exclusive creation: an earlier result, including a failed or negative one, is never overwritten.
        with (args.out / f"round{number}.json").open("x", encoding="utf-8") as stream:
            json.dump({"commit": commit, "uncommitted_changes": dirty, "round": number,
                       "result": ROUNDS[number]()}, stream, indent=1, ensure_ascii=False)
        print(f"round {number} written")


if __name__ == "__main__":
    main()
