"""CPU audit of contextual recovery under the Gate 21 execution contract."""

import argparse
from fractions import Fraction as F
from itertools import product
import json
from pathlib import Path
import platform
import subprocess
from typing import NamedTuple

from . import gate21 as previous
from .run import require, write
from .workflow21 import (ACQUIRE, DIAGNOSTIC_FEE, Observation, Preparation, Progress, World,
                         Workflow, actions, event_occurs, execute_action, sample)

CONFIG = Path(__file__).with_suffix(".json")
ORDERS = previous.ORDERS
SIMPLE = ("best_fixed", "task_fixed", "current_threshold", "recent_feedback", "full_history_threshold",
          "fixed_continuation", "one_probe_rule")


class ContextLaw(NamedTuple):
    base: previous.Law
    prepare_accuracy: F

    @property
    def short(self):
        return self.base.short

    @property
    def accuracy(self):
        return self.base.accuracy

    def success(self, action, good):
        if action == "prepare":
            return self.prepare_accuracy if good else 1 - self.prepare_accuracy
        return self.base.success(action, good)


def mechanism_laws(config, inherited):
    return {
        cell: {
            scope: ContextLaw(previous.Law(**{key: F(value) for key, value in {
                **inherited["generating_rates"], "shared": settings["shared"], "accuracy": settings["accuracy"],
                "short": settings.get("short", short),
            }.items()}), F(settings["prepare_accuracy"]))
            for scope, short in config["scopes"].items()
        }
        for cell, settings in config["cells"].items()
    }


def support_key(state, history):
    failed, probe = previous.context_key(state, history)
    quality = history[0].success if history and history[0].action == "prepare" else None
    return failed, (quality, probe)


def dataset(config, split, scope, law):
    families, seeds, count = config["splits"][split]
    for family, seed, index in product(families, seeds, range(count)):
        key = ("gate22", split, family, seed, index)
        good = event_occurs(key, "gateway:A", previous.HALF)
        quality = good == event_occurs(key, "prepare:correct", law.prepare_accuracy)
        yield (family, seed, index), sample(law.base, key), Preparation(scope, quality, law.prepare_accuracy)


def training(config, scope, law, *, sparse=False):
    rows = []
    for identity, world, preparation in dataset(config, "train", scope, law):
        family, _, index = identity
        order = ORDERS[index - 6] if index >= 6 else ("A", "B", "C") if index % 2 == 0 else ("A", "C", "B")
        choose = previous.ordered(order)

        def logging(state, history):
            if index >= 6 and index % 2 == 0 and len(history) == 1:
                return "diagnose"
            selected = choose(state, history)
            if (sparse and selected == "B" and support_key(state, history) == (("A",), (True, None))
                    and "C" in actions(state)):
                return "C"
            return selected

        row = previous.replay(Workflow(family, world, law.accuracy, preparation=preparation), logging)
        rows.append({"identity": identity, **row})
    return rows


def fitted(rows, law, grid, order):
    augmented = [{**row, "observations": (row["checkpoints"][0]["view"]["observations"][0], *row["observations"])}
                 for row in rows]
    model, ties = previous.fit(augmented, law.accuracy, grid,
                               wrap=lambda base: ContextLaw(base, law.prepare_accuracy))
    btm, support, contexts = previous.historical(rows, order, support_key=support_key)
    continuation = previous.threshold(model, "full", True)
    memory, values = previous.action_memory(model, continuation)
    support["contexts"] = [{**{key: value for key, value in row.items() if key != "probe_signal"},
                            "prepare_signal": row["probe_signal"][0], "probe_signal": row["probe_signal"][1]}
                           for row in support["contexts"]]
    target = {str(signal): {action: contexts[("A",), (signal, None), action] for action in ("B", "C")}
              for signal in (True, False)}
    support["after_a_failure_no_probe"] = target
    support["target_coverage_sufficient"] = min(n for counts in target.values() for n in counts.values()) >= 3
    return dict(model=model, ties=ties, support=support, contexts=contexts, btm=btm,
                continuation=continuation, memory=memory, values=values)


def law_worlds(law):
    for good, a, b, c, short, signal, quality in product((True, False), repeat=7):
        weight = previous.HALF
        rates = [law.success(action, good) for action in ACQUIRE]
        chances = (*rates, law.short, law.success("diagnose", good), law.success("prepare", good))
        for outcome, chance in zip((a, b, c, short, signal, quality), chances):
            weight *= chance if outcome else 1 - chance
        if weight:
            yield weight, World((a, b, c), short, signal), quality


def run_policy(data, law, policy):
    return [{"identity": identity, "world": world, "preparation": prep,
             "row": previous.replay(Workflow(identity[0], world, law.accuracy, preparation=prep), policy)}
            for identity, world, prep in data]


def validation_score(rows):
    outcomes = [previous.outcomes(row["row"]) for row in rows]
    return (sum(row[0] for row in outcomes), sum(row[3] for row in outcomes),
            -sum(row[1] + row[2] for row in outcomes))


def exact(law, scope, policy, *, after_a_failure=None, oracle=False, probe=True):
    mass, result = F(0), list(previous.ZERO)
    for weight, world, quality in law_worlds(law):
        session = Workflow("publish", world, law.accuracy, probe=probe,
                           preparation=Preparation(scope, quality, law.prepare_accuracy))
        if after_a_failure is not None:
            if quality != after_a_failure or world.available[0]:
                continue
            execute_action(session, "A")
        prefix_fee = session.audit()["tool_fee"]
        selected = previous.oracle(world) if oracle else policy
        complete, tool, diag, stop = previous.outcomes(previous.replay(session, selected))
        for index, value in enumerate((complete, tool - prefix_fee, diag, stop)):
            result[index] += weight * value
        mass += weight
    return tuple(value / mass for value in result)


def witnesses(laws):
    winners = {
        "full": ("B", "C", "C", "C"),
        "no_dependency": ("B", "C", "B", "C"),
        "independent": ("B", "B", "C", "C"),
        "null_probe": ("B", "C", "C", "C"),
        "null_preparation": ("C", "C", "C", "C"),
    }
    result = {}
    checkpoint = Progress(4, failed=("A",))
    no_probe_checkpoint = checkpoint._replace(probe=False)
    for cell, scopes in laws.items():
        result[cell] = {}
        for (scope, signal), target in zip(product(scopes, (True, False)), winners[cell]):
            law = scopes[scope]
            history = (Observation("prepare", signal), Observation("A", False))
            select, values = previous.planning(law)
            comparison = {action: values(no_probe_checkpoint, history)[action] for action in ("B", "C")}
            require(select(no_probe_checkpoint, history) == target, "Registered action reversal was not reproduced")
            for order in (("B", "C"), ("C", "B")):
                replayed = exact(law, scope, previous.ordered(order), after_a_failure=signal, probe=False)
                require(replayed == comparison[order[0]], "Planning and the independent receipt replay disagree")
            chosen = select(checkpoint, history)
            replayed = exact(law, scope, select, after_a_failure=signal)
            require(replayed == values(checkpoint, history)[chosen], "Probe expectation differs from receipt replay")
            result[cell][f"{scope}/{signal}"] = {"B_C_without_probe": comparison, "choice": chosen,
                                                 "planned_value": replayed}
    paid, null = (result[cell]["portable/True"] for cell in ("full", "null_probe"))
    require(paid["choice"] == "diagnose" and paid["planned_value"][2] == DIAGNOSTIC_FEE
            and null["choice"] == "C", "Paid-probe witness was not reproduced")
    return result


def policies(group, fixed, task_fixed, btm):
    model = group["model"]

    def no_prepare(state, history):
        return group["memory"](state, tuple(o for o in history if o.action != "prepare"))

    return {
        "best_fixed": previous.ordered(fixed),
        "task_fixed": previous.ordered(task_fixed),
        "current_threshold": previous.threshold(model, "recent", False),
        "recent_feedback": previous.threshold(model, "recent", True),
        "full_history_threshold": group["continuation"],
        "fixed_continuation": previous.strongest_order(model),
        "one_probe_rule": previous.strongest_order(model, probe=True),
        "btm_proxy": btm,
        "btm_task_proxy": group["btm"],
        "task_only_memory": no_prepare,
        "memory_proxy": group["memory"],
        "full_planning": previous.planning(model)[0],
    }


def train_cells(config, laws, grid, out):
    models, heldout, orders = {}, {}, {}
    for cell, scopes in laws.items():
        rows, validation, scores = {}, {}, {}
        for scope, law in scopes.items():
            rows[scope] = training(config, scope, law)
            write(out / f"training-{cell}-{scope}.json", rows[scope])
            validation[scope] = list(dataset(config, "validation", scope, law))
            ordered_rows = {"".join(order): run_policy(validation[scope], law, previous.ordered(order))
                            for order in ORDERS}
            scores[scope] = {order: validation_score(ordered_rows["".join(order)]) for order in ORDERS}
            write(out / f"validation-orders-{cell}-{scope}.json", ordered_rows)
        pooled = {order: tuple(sum(scores[scope][order][i] for scope in scopes) for i in range(3)) for order in ORDERS}
        fixed = max(pooled, key=pooled.get)
        orders[cell] = {scope: max(scores[scope], key=scores[scope].get) for scope in scopes}
        models[cell] = {
            scope: {"matched": fitted(rows[scope], law, grid, orders[cell][scope])}
            for scope, law in scopes.items()
        }
        if cell == "full":
            for scope, law in scopes.items():
                sparse = training(config, scope, law, sparse=True)
                write(out / f"training-sparse-{scope}.json", sparse)
                models[cell][scope]["sparse"] = fitted(sparse, law, grid, orders[cell][scope])
        pooled_rows = [row for batch in rows.values() for row in batch]
        btm, btm_support, _ = previous.historical(pooled_rows, fixed)
        write(out / f"btm-{cell}.json", btm_support)
        heldout[cell] = {}
        for scope, law in scopes.items():
            strategies = policies(models[cell][scope]["matched"], fixed, orders[cell][scope], btm)
            results = {label: run_policy(validation[scope], law, strategies[label]) for label in SIMPLE}
            write(out / f"validation-rules-{cell}-{scope}.json", results)
            heldout[cell][scope] = (strategies, {label: validation_score(batch) for label, batch in results.items()})
    for scope in laws["full"]:
        models["full"][scope]["shifted"] = models["independent"][scope]["matched"]
    return models, heldout, orders


def differences(left, right):
    for index, (a, b) in enumerate(zip(left["checkpoints"], right["checkpoints"])):
        require(a["view"] == b["view"], "Policy views differ before their first action disagreement")
        if a["action"] != b["action"]:
            return {"turn": index, "view": a["view"], "left": a["action"], "right": b["action"]}
    require(len(left["checkpoints"]) == len(right["checkpoints"]), "Identical actions have different horizons")
    return None


def evaluate(config, laws, models, heldout, orders, out):
    cells, validations, expected = [], {}, {}
    for cell, scopes in laws.items():
        validation = {label: tuple(sum(heldout[cell][scope][1][label][i] for scope in scopes) for i in range(3))
                      for label in SIMPLE}
        strongest = max(validation, key=validation.get)
        validations[cell] = {"strongest_simple": strongest, "scores": validation,
                             "task_orders": orders[cell]}
    write(out / "validation.json", validations)
    for cell, scopes in laws.items():
        strongest = validations[cell]["strongest_simple"]
        expected[cell] = {}
        for scope, law in scopes.items():
            directory = out / cell / scope
            directory.mkdir(parents=True)
            strategies = dict(heldout[cell][scope][0])
            strategies["known_parameters"] = previous.planning(law)[0]
            for label, group in models[cell][scope].items():
                if label != "matched":
                    strategies[f"memory_{label}"] = group["memory"]
            expected[cell][scope] = {label: exact(law, scope, policy) for label, policy in strategies.items()}
            expected[cell][scope]["oracle"] = exact(law, scope, None, oracle=True)
            for identity, world, prep in dataset(config, "test", scope, law):
                family, seed, index = identity
                available = {**strategies, "oracle": previous.oracle(world)}
                rows = {label: previous.replay(Workflow(family, world, law.accuracy, preparation=prep), policy)
                        for label, policy in available.items()}
                forecasts = previous.forecasts(Workflow(family, world, law.accuracy, preparation=prep), law,
                                               models[cell][scope], orders[cell][scope], support_key=support_key)
                case = {"cell": cell, "identity": identity, "blocked": not any(world.available),
                        "metrics": {label: previous.metrics(row) for label, row in rows.items()},
                        "forecasts": forecasts}
                comparisons = {f"{left}/{right}": differences(rows[left], rows[right])
                               for left, right in (("btm_proxy", "memory_proxy"), ("full_planning", strongest),
                                                   ("full_planning", "task_fixed"), ("full_planning", "one_probe_rule"))}
                write(directory / f"{family}-{seed}-{index}.json",
                      {**case, "world": world, "preparation": prep, "rows": rows, "comparisons": comparisons})
                cells.append(case)
                cells.append({**case, "cell": f"{cell}/{scope}"})
        print(f"Recorded {cell}", flush=True)
    write(out / "expected.json", {"fields": ["complete", "tool_fee", "diagnostic_fee", "correct_stop"], "cells": expected})
    write(out / "evaluation.json", previous.summarize(cells))


def run(out):
    config = json.loads(CONFIG.read_text())
    inherited = json.loads(previous.CONFIG.read_text())
    laws = mechanism_laws(config, inherited)
    write(out / "config.json", {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                                "python": platform.python_version(), "execution": "CPU only",
                                "gate22": config, "gate21_rates": inherited["generating_rates"], "grid": inherited["grid"]})
    write(out / "witnesses.json", witnesses(laws))
    models, heldout, orders = train_cells(config, laws, inherited["grid"], out)
    write(out / "history.json", {
        cell: {scope: {label: {key: group[key] for key in ("model", "ties", "support")} for label, group in arms.items()}
               for scope, arms in scopes.items()} for cell, scopes in models.items()
    })
    evaluate(config, laws, models, heldout, orders, out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    try:
        run(args.out)
    except Exception as error:
        write(args.out / "failure.json", {"kind": type(error).__name__, "detail": str(error)})
        raise


if __name__ == "__main__":
    main()
