"""Gate 21 CPU mechanism checks, historical fit and paired replay."""

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from fractions import Fraction as F
from functools import cache
from itertools import combinations_with_replacement, permutations, product
import json
from pathlib import Path
import platform
from statistics import mean
import subprocess
from typing import NamedTuple

from .gate16 import rank
from .run import require, write
from .workflow21 import (ACQUIRE, DIAGNOSTIC_FEE, PRICES, Observation, Progress, World, Workflow,
                         actions, advance, execute_action, sample)

CONFIG = Path(__file__).with_suffix(".json")
HALF = F(1, 2)
ORDERS = tuple(permutations(ACQUIRE))
ZERO = (F(0),) * 4


class Law(NamedTuple):
    a_good: F
    a_bad: F
    b_good: F
    b_bad: F
    shared: F
    c: F
    short: F
    accuracy: F

    def success(self, action, good):
        if action == "A":
            return self.a_good if good else self.a_bad
        if action == "B":
            conditional = self.b_good if good else self.b_bad
            return self.shared * conditional + (1 - self.shared) * (self.b_good + self.b_bad) * HALF
        if action == "C":
            return self.c
        return self.accuracy if good else 1 - self.accuracy


def likelihood(law, observations, good):
    weight = F(1)
    for action, positive, _ in observations:
        if action in ("A", "B", "diagnose"):
            rate = law.success(action, good)
            weight *= rate if positive else 1 - rate
    return weight


@cache
def belief(law, observations):
    good, bad = (likelihood(law, observations, state) for state in (True, False))
    return good / (good + bad)


def rate(law, observations, action):
    good = belief(law, observations)
    return good * law.success(action, True) + (1 - good) * law.success(action, False)


def branches(law, history, action):
    if action in (*ACQUIRE, "diagnose"):
        success = rate(law, history, action)
        yield 1 - success, Observation(action, False)
        if action == "B":
            yield success * law.short, Observation(action, True, "short")
            yield success * (1 - law.short), Observation(action, True, "native")
        else:
            kind = {"A": "native", "C": "external"}.get(action, "")
            yield success, Observation(action, True, kind)
    else:
        yield F(1), Observation(action, action != "stop", "native" if action == "verify" else "")


def action_value(law, state, history, action, follow):
    value = [F(0), PRICES.get(action, F(0)), DIAGNOSTIC_FEE if action == "diagnose" else F(0), F(0)]
    for mass, observation in branches(law, history, action):
        if mass:
            after = advance(state, observation)
            tail = follow(after, (*history, observation))
            for i, item in enumerate(tail):
                value[i] += mass * item
    return tuple(value)


def expected(law, policy):
    @cache
    def follow(state, history):
        if state.terminal:
            return F(state.terminal == "complete"), F(0), F(0), F(state.terminal == "blocked_stop")
        return action_value(law, state, history, policy(state, history), follow)
    return follow


def choice(values):
    return max(values, key=lambda action: rank(values[action][:3]))


def ordered(order):
    def select(state, history):
        legal = actions(state)
        if state.phase != "acquire":
            return legal[0]
        return next((action for action in order if action in legal), "stop")
    return select


def strongest_order(law, probe=False):
    continuations = {order: expected(law, ordered(order)) for order in ORDERS}

    @cache
    def select(state, history):
        order = choice({order: value(state, history) for order, value in continuations.items()})
        selected = ordered(order)(state, history)
        if not probe or "diagnose" not in actions(state):
            return selected
        # The one-probe rule compares probing now against committing to an order now.
        def follow(after, evidence):
            return max((value(after, evidence) for value in continuations.values()),
                       key=lambda value: rank(value[:3]))
        probe_value = action_value(law, state, history, "diagnose", follow)
        return choice({selected: continuations[order](state, history), "diagnose": probe_value})
    return select


def threshold(law, memory, tails):
    def select(state, history):
        legal = actions(state)
        options = tuple(action for action in ACQUIRE if action in legal)
        if not options:
            return legal[0]
        evidence = history if memory == "full" else history[-1:] if memory == "recent" else ()

        def cost(action):
            chance = rate(law, evidence, action)
            suffix = law.short * PRICES["verify"] if tails and action == "B" else F(0)
            return PRICES[action] / chance + suffix
        return min(options, key=cost)
    return select


def planning(law, allow_probe=True):
    def select(state, history):
        return choice(options(state, history))

    @cache
    def options(state, history):
        return {action: action_value(law, state, history, action, follow)
                for action in actions(state) if allow_probe or action != "diagnose"}

    follow = expected(law, select)
    return select, options


def action_memory(law, continuation):
    follow = expected(law, continuation)

    @cache
    def values(state, history):
        return {action: action_value(law, state, history, action, follow) for action in actions(state)}
    return lambda state, history: choice(values(state, history)), values


def replay(session, policy):
    checkpoints = []
    while not session.state.terminal:
        view = session.view()
        action = policy(view["progress"], view["observations"])
        checkpoints.append({"view": view, "action": action})
        execute_action(session, action)
    row = session.audit()
    require(not row["score"]["issues"], "Independent audit failed")
    return {**row, "checkpoints": checkpoints}


def episodes(law, config, split):
    families, seeds, count = config["splits"][split]
    for family, seed, i in product(families, seeds, range(count)):
        identity = ("gate21", split, family, seed, i)
        yield (family, seed, i), sample(law, identity)


def training(law, config):
    rows = []
    for (family, seed, i), world in episodes(law, config, "train"):
        assigned = i >= len(ORDERS)
        order = ORDERS[i - len(ORDERS)] if assigned else ACQUIRE
        session = Workflow(family, world, law.accuracy)
        select = ordered(order)
        if assigned and i % 2 == 0:
            def logging(state, history):
                return "diagnose" if not history else select(state, history)
        else:
            logging = select
        row = replay(session, logging)
        rows.append({"family": family, "seed": seed, "instance": i, "assigned": assigned, **row})
    return rows


def historical(rows, order):
    counts, successes = Counter(), Counter()
    attempts, initial, receipts = Counter(), Counter(), Counter()
    contexts = Counter()
    for row in rows:
        failed = {"A"}
        keys = {("recovery", "A")}
        for checkpoint, observation in zip(row["checkpoints"], row["observations"]):
            action, positive, kind = observation
            contexts[(*context_key(checkpoint["view"]["progress"], checkpoint["view"]["observations"]), action)] += 1
            if action in ACQUIRE:
                attempts[action] += 1
                keys.update(("switch", source, action) for source in failed - {action})
                if not positive:
                    keys.add(("recovery", action))
                    failed.add(action)
                else:
                    receipts[action, kind] += 1
        if row["checkpoints"][0]["action"] in ACQUIRE:
            initial[row["checkpoints"][0]["action"]] += 1
        counts.update(keys)
        if row["score"]["legal_success"]:
            successes.update(keys)

    def select(state, history):
        legal = actions(state)
        candidates = [action for action in order if action in legal]
        if not candidates:
            return legal[0]
        last_error = state.failed[-1] if state.failed else "A"

        def posterior(action):
            key = ("recovery", last_error) if action == last_error else ("switch", last_error, action)
            return F(successes[key] + 1, counts[key] + 2)
        return max(candidates, key=posterior)

    stats = {"btm": [{"key": key, "n": n, "successes": successes[key],
                      "posterior": F(successes[key] + 1, n + 2)} for key, n in sorted(counts.items())],
             "attempts": dict(attempts), "first": {action: initial[action] for action in ACQUIRE},
             "receipts": [{"action": a, "kind": k, "n": n} for (a, k), n in sorted(receipts.items())]}
    stats["contexts"] = [{"failed": key[0], "probe_signal": key[1], "action": key[2], "n": n}
                         for key, n in sorted(contexts.items(), key=lambda item: str(item[0]))]
    return select, stats, contexts


def fit(rows, accuracy, grid):
    patterns = Counter(tuple(o for o in row["observations"] if o.action in ("A", "B", "diagnose"))
                       for row in rows)
    c = [o.success for row in rows for o in row["observations"] if o.action == "C"]
    short = [o.credential == "short" for row in rows for o in row["observations"]
             if o.action == "B" and o.success]
    marginals = F(sum(c) + 1, len(c) + 2), F(sum(short) + 1, len(short) + 2)
    pairs = tuple(combinations_with_replacement(map(F, grid["emissions"]), 2))
    candidates = (Law(ag, ab, bg, bb, F(shared), *marginals, accuracy)
                  for (ab, ag), (bb, bg), shared in product(pairs, pairs, grid["shared"]))
    candidates = sorted(candidates, key=lambda m: (m.shared, m.a_good - m.a_bad + m.b_good - m.b_bad, m))
    best, ties = F(-1), []
    for law in candidates:
        score = F(1)
        for observations, count in patterns.items():
            mass = (likelihood(law, observations, True) + likelihood(law, observations, False)) * HALF
            score *= mass**count
        if score > best:
            best, ties = score, [law]
        elif score == best:
            ties.append(law)
    return ties[0], ties


def validate_order(law, config):
    data = list(episodes(law, config, "validation"))
    metrics, archive = {}, {}
    for order in ORDERS:
        rows = [replay(Workflow(family, world, law.accuracy), ordered(order))
                for (family, _, _), world in data]
        archive["".join(order)] = [{"identity": identity, "world": world, "row": row}
                                  for (identity, world), row in zip(data, rows)]
        metrics[order] = (sum(row["score"]["legal_success"] for row in rows),
                          sum(row["termination"] == "blocked_stop" for row in rows),
                          -sum(row["tool_fee"] + row["diagnostic_fee"] for row in rows))
    return max(metrics, key=metrics.get), {"".join(order): value for order, value in metrics.items()}, archive


def tapes(law):
    for good, a, b, c, short, signal in product((True, False), repeat=6):
        mass = HALF
        rates = [law.success(action, good) for action in ACQUIRE]
        for outcome, probability in zip((a, b, c, short, signal), (*rates, law.short, law.success("diagnose", good))):
            mass *= probability if outcome else 1 - probability
        if mass:
            yield mass, World((a, b, c), short, signal)


def outcomes(row):
    return (int(row["score"]["legal_success"]), row["tool_fee"], row["diagnostic_fee"],
            int(row["termination"] == "blocked_stop"))


def exact_replay(law, policy, budget, prefix=(), signal=None):
    """Independent expectation from complete keyed outcomes and the receipt executor."""
    weight, totals = F(0), list(ZERO)
    for mass, world in tapes(law):
        if signal is not None and world.signal != signal:
            continue
        session = Workflow("publish", world, law.accuracy, budget)
        for action in prefix:
            execute_action(session, action)
        if any(o.action == "A" and o.success for o in session.observations):
            continue
        spent, diag = session.audit()["tool_fee"], session.audit()["diagnostic_fee"]
        result = outcomes(replay(session, policy))
        for i, item in enumerate((result[0], result[1] - spent, result[2] - diag, result[3])):
            totals[i] += mass * item
        weight += mass
    return tuple(total / weight for total in totals)


def witnesses(laws):
    independent = laws["control"]
    shared = independent._replace(shared=F(1))
    failures = Progress(4, failed=("A",))
    error = Observation("A", False)
    result = {}
    for name, law, target in (
        ("equal_receipts", independent, ("B", F("2.20"), F("2.36"))),
        ("different_receipts", independent._replace(short=HALF), ("C", F("2.70"), F("2.51"))),
        ("shared_gateway", shared, ("C", F(341, 135), F("2.36"))),
    ):
        select, values = planning(law)
        actual = values(failures, (error,))
        for action, other in (("B", "C"), ("C", "B")):
            direct = exact_replay(law, ordered((action, other)), 5, ("A",))
            require(actual[action] == direct, f"Exact witness differs from receipt replay: {name}")
        register = PRICES["register_native"] * actual["B"][0]
        comparison = (select(failures, (error,)), actual["B"][1] - register, actual["C"][1] - register)
        require(comparison == target and actual["B"][0] == actual["C"][0], f"Invalid witness: {name}")
        result[name] = actual

    informative = shared._replace(accuracy=F(4, 5))
    state = failures._replace(probe=False)
    select, values = planning(informative)
    for signal, order in ((True, ("B", "C")), (False, ("C", "B"))):
        action = order[0]
        history = (Observation("diagnose", signal), error)
        require(select(state, history) == action, "Early evidence did not reverse the action")
        direct = exact_replay(informative, ordered(order), 5, ("diagnose", "A"), signal)
        require(values(state, history)[action] == direct, "Earlier-evidence witness differs from replay")
        result["earlier_signal_" + str(signal)] = values(state, history)

    for name, law, winner, value in (
        ("paid_information", informative, "diagnose", (F(".72"), F("1.888"), DIAGNOSTIC_FEE)),
        ("null_information", shared, "C", (F(".70"), F("2.280"), F(0))),
        ("independent_information", informative._replace(shared=F(0)), "C",
         (F(".70"), F("2.280"), F(0))),
    ):
        select, values = planning(law)
        state = Progress(2)
        actual = values(state, ())
        require(select(state, ()) == winner and actual[winner][:3] == value, f"Invalid witness: {name}")
        require(actual[winner] == exact_replay(law, select, 2), f"Paid-probe replay differs: {name}")
        result[name] = actual
    return result


def context_key(state, history):
    signal = next((observation.success for observation in history if observation.action == "diagnose"), None)
    return tuple(sorted(state.failed)), signal


def model_group(rows, law, config, order):
    model, ties = fit(rows, law.accuracy, config["grid"])
    btm, support, contexts = historical(rows, order)
    continuation = threshold(model, "full", True)
    memory, values = action_memory(model, continuation)
    ranges = defaultdict(list)
    for alternative in ties:
        # Keep the continuation fixed while comparing likelihood-tied models.
        _, alternate = action_memory(alternative, continuation)
        for action, value in alternate(Progress(5), ()).items():
            ranges[action].append(value[:3])
    return {
        "model": model, "ties": ties, "support": support, "contexts": contexts, "btm": btm,
        "continuation": continuation, "memory": memory, "values": values,
        "initial_tied_range": {action: [(min(items), max(items)) for items in zip(*rows)]
                               for action, rows in ranges.items()},
    }


def policies(law, group, best_order):
    model = group["model"]
    return {
        "fixed_retry": ordered(ACQUIRE),
        "fixed_switch": ordered(("B", "C", "A")),
        "best_static_order": ordered(best_order),
        "current_threshold": threshold(model, "recent", False),
        "fixed_belief": threshold(model, "fixed", True),
        "recent_feedback": threshold(model, "recent", True),
        "full_history_threshold": group["continuation"],
        "fixed_continuation": strongest_order(model),
        "one_probe_rule": strongest_order(model, probe=True),
        "btm_proxy": group["btm"],
        "memory_proxy": group["memory"],
        "full_planning": planning(model)[0],
        "full_planning_no_probe": planning(model, allow_probe=False)[0],
        "known_parameters": planning(law)[0],
    }


def oracle(world):
    def select(state, history):
        legal = actions(state)
        options = [action for action in ACQUIRE if action in legal]
        if not options:
            return legal[0]
        possible = [action for action in options if world.available[ACQUIRE.index(action)]]
        return min(possible, key=lambda action: PRICES[action] + (PRICES["verify"]
                   if action == "B" and world.short else F(0))) if possible else options[0]
    return select


def metrics(row):
    complete, tools, diagnostic, correct_stop = outcomes(row)
    successful_path = sum(o.success and o.action != "diagnose" for o in row["observations"])
    return {"complete": complete, "correct_stop": correct_stop, "tool_fee": tools,
            "diagnostic_fee": diagnostic, "tool_calls": len(row["ledger"]),
            "diagnostic_calls": len(row["diagnostic_ledger"]),
            "redundant_tool_calls": len(row["ledger"]) - successful_path if complete else None,
            "premature_stop": int(row["termination"] == "premature_stop"),
            "exhausted": int(row["termination"] == "exhausted")}


def forecasts(session, law, groups, best_order):
    checkpoints = []
    expectations = {name: expected(law, group["continuation"]) for name, group in groups.items()}
    while not session.state.terminal:
        view = session.view()
        state, history = view["progress"], view["observations"]
        report = {}
        if state.phase == "acquire":
            for name, group in groups.items():
                values = group["values"](state, history)
                exact = {action: action_value(law, state, history, action, expectations[name])
                         for action in values}
                records = {}
                for action, predicted in values.items():
                    fork = deepcopy(session)
                    execute_action(fork, action)
                    row = replay(fork, group["continuation"])
                    complete, tools, diag, _ = outcomes(row)
                    actual = (complete, tools - sum(item["fee"] for item in session.ledger),
                              diag - sum(item["fee"] for item in session.diagnostics))
                    support = group["contexts"][(*context_key(state, history), action)]
                    records[action] = {"predicted": predicted[:3], "exact": exact[action][:3],
                                       "actual": actual, "training_attempts": support}
                report[name] = {"predicted_action": choice(values), "exact_action": choice(exact), "actions": records}
            checkpoints.append({"view": view, "forecast": report})
        execute_action(session, ordered(best_order)(state, history))
    return checkpoints


def summarize(cases):
    groups, errors, ranks, blocked = defaultdict(list), defaultdict(list), defaultdict(Counter), Counter()
    for case in cases:
        cell, (family, seed, _) = case["cell"], case["identity"]
        for label in (cell, f"{cell}/{family}", f"{cell}/{seed}"):
            blocked[label] += case["blocked"]
            for policy, row in case["metrics"].items():
                groups[label, policy].append(row)
        for checkpoint in case["forecasts"]:
            for fit_name, forecast in checkpoint["forecast"].items():
                ranks[cell, fit_name]["checkpoints"] += 1
                ranks[cell, fit_name]["rank_changes"] += forecast["predicted_action"] != forecast["exact_action"]
                for action, row in forecast["actions"].items():
                    support = "direct" if row["training_attempts"] else "extrapolated"
                    errors[cell, fit_name, action, support].append(row)
    evaluation = defaultdict(dict)
    for (label, policy), rows in groups.items():
        values = {key: [row[key] for row in rows if row[key] is not None] for key in rows[0]}
        evaluation[label][policy] = {
            "n": len(rows), "structurally_blocked": blocked[label],
            **{key: {"n": len(items), "total": sum(items), "mean": mean(items) if items else None}
               for key, items in values.items()},
        }
    error_summary = []
    for (cell, fit_name, action, support), rows in sorted(errors.items()):
        record = {"cell": cell, "fit": fit_name, "action": action, "support": support, "n": len(rows)}
        for i, metric in enumerate(("completion", "tool_fee", "diagnostic_fee")):
            predicted, exact, actual = (tuple(row[key][i] for row in rows) for key in ("predicted", "exact", "actual"))
            record[metric] = {
                "absolute_error": mean(abs(p - a) for p, a in zip(predicted, actual)),
                "bias": mean(p - a for p, a in zip(predicted, actual)),
                "fit_bias": mean(p - e for p, e in zip(predicted, exact)),
                "sampling_residual": mean(e - a for e, a in zip(exact, actual)),
            }
            if i == 0:
                record[metric]["brier"] = mean((p - a)**2 for p, a in zip(predicted, actual))
        error_summary.append(record)
    return {"metrics": evaluation, "forecast_errors": error_summary,
            "rank_errors": [{"cell": cell, "fit": fit_name, **counts}
                            for (cell, fit_name), counts in ranks.items()]}


def run(config, out):
    laws = {name: Law(**{key: F(value) for key, value in {**config["generating_rates"], **settings}.items()})
            for name, settings in config["cells"].items()}
    write(out / "config.json", {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                                "python": platform.python_version(), "execution": "CPU only", "config": config})
    write(out / "witnesses.json", witnesses(laws))
    groups, orders, history, selected, exact = {}, {}, {}, {}, {}
    for name, law in laws.items():
        rows = training(law, config)
        orders[name], validation, validation_rows = validate_order(law, config)
        groups[name] = {"matched": model_group(rows, law, config, orders[name])}
        if name == "full":
            groups[name].update({label: model_group([row for row in rows if row["assigned"] == assigned],
                                                    law, config, orders[name])
                                 for label, assigned in (("balanced", True), ("sparse", False))})
        write(out / f"training-{name}.json", rows)
        write(out / f"validation-{name}.json", validation_rows)
        history[name] = {"validation_orders": validation, "chosen_order": orders[name]}
        print(f"Fitted {name}", flush=True)
    groups["full"]["shifted"] = groups["independent"]["matched"]
    for name, law in laws.items():
        history[name]["fits"] = {
            label: {key: group[key] for key in ("model", "ties", "support", "initial_tied_range")}
            for label, group in groups[name].items()
        }
        selected[name] = policies(law, groups[name]["matched"], orders[name])
        for label, group in groups[name].items():
            if label != "matched":
                selected[name][f"memory_{label}"] = group["memory"]
        exact[name] = {label: expected(law, policy)(Progress(5), ()) for label, policy in selected[name].items()}
        require(exact[name]["fixed_continuation"] == exact[name]["full_planning_no_probe"],
                "Without probes, finite planning and exact ordering differ")
        for label in ("full_planning", "one_probe_rule", "known_parameters"):
            require(exact[name][label] == exact_replay(law, selected[name][label], 5),
                    f"Distribution and executor disagree: {name}/{label}")
        weighted = [(mass, outcomes(replay(Workflow("publish", world, law.accuracy), oracle(world))))
                    for mass, world in tapes(law)]
        exact[name]["oracle"] = tuple(sum(mass * result[i] for mass, result in weighted) for i in range(4))
    write(out / "history.json", history)
    write(out / "expected.json", {"fields": ["complete", "tool_fee", "diagnostic_fee", "correct_stop"], "cells": exact})
    cases = []
    for name, law in laws.items():
        directory = out / name
        directory.mkdir()
        for identity, world in episodes(law, config, "test"):
            family, seed, i = identity
            policies_here = {**selected[name], "oracle": oracle(world)}
            rows = {label: replay(Workflow(family, world, law.accuracy), policy)
                    for label, policy in policies_here.items()}
            require(len({str(row["checkpoints"][0]["view"]) for row in rows.values()}) == 1,
                    "Initial information differs across policies")
            case = {"cell": name, "identity": identity, "blocked": not any(world.available),
                    "metrics": {label: metrics(row) for label, row in rows.items()},
                    "forecasts": forecasts(Workflow(family, world, law.accuracy), law, groups[name], orders[name])}
            write(directory / f"{family}-{seed}-{i}.json", {**case, "world": world, "rows": rows})
            cases.append(case)
        print(f"Recorded {name}", flush=True)
    write(out / "evaluation.json", summarize(cases))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    try:
        run(json.loads(CONFIG.read_text()), args.out)
    except Exception as error:
        write(args.out / "failure.json", {"kind": type(error).__name__, "detail": str(error)})
        raise


if __name__ == "__main__":
    main()
