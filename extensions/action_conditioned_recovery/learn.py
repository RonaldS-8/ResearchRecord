"""Small held-out experiment using only observable training outcomes."""
import argparse
from collections import defaultdict
from fractions import Fraction as F
import json
from pathlib import Path
import platform
from random import Random
import subprocess

from extensions.toolmaze_diagnostic_mvp.environment import load_case

from .mvp import Session, rank
from .run import execute, fixed, require, score, write

CONFIG = Path(__file__).with_name("gate10.json")
ARMS = ("switch", "retry_then_switch")
BASELINES = ("retry_only", *ARMS, "task_rate", "cost_only", "pooled", "context",
             "context_one_bit", "action_values")


def fit(rows):
    retry = [r for r in rows if r["arm"] == "retry_then_switch"]
    by_context = defaultdict(list)
    by_action = defaultdict(list)
    task_outcomes = defaultdict(list)
    switches = defaultdict(list)
    for row in rows:
        context = row["views"][0]["context"]
        by_action[context, row["arm"]].append(score(row))
        fault = row["views"][0]["history"][-1]
        key = fault["tool"], fault["output"]["error"]
        task_outcomes[key].append(score(row)[0])
        if row["arm"] == "retry_then_switch":
            by_context[context].append(row)
        for decision, bill in zip(row["decisions"], row["ledger"]):
            if decision["action"] == "switch":
                target = row["events"][bill["calls"][0]]["tool"]
                switches[key[0], target].append(score(row)[0])

    def posterior(records):
        return F(1 + sum(r["decisions"][0]["recovered"] for r in records), 2 + len(records))

    def beta(records):
        return {"n": len(records), "mean": F(1 + sum(records), 2 + len(records))}

    return {
        "pooled": posterior(retry),
        "context": {x: posterior(records) for x, records in by_context.items()},
        "action": {x: {a: tuple(sum(column) / len(records) for column in
                               zip(*records))
                       for (ctx, a), records in by_action.items() if ctx == x}
                   for x in by_context},
        "task": {key: beta(records) for key, records in task_outcomes.items()},
        "switch": {key: beta(records) for key, records in switches.items()},
    }


def threshold(view, p):
    r, f, s = (F(view["prices"][k]) for k in ("retry_success", "retry_failure", "switch"))
    return "retry_then_switch" if p * r + (1 - p) * (f + s) < s else "switch"


def select(name, view, fitted):
    context = view["context"]
    if name in (*ARMS, "retry_only"):
        return name
    if name == "action_values":
        estimates = fitted["action"][context]
        return max(ARMS, key=lambda arm: rank(estimates[arm]))
    # Task-rate statistics supply no retry-specific probability. Use the same
    # public-cost fallback as the no-history control.
    p = {"pooled": fitted["pooled"], "context": fitted["context"][context],
         "context_one_bit": fitted["context"][context]}.get(name, F(1, 2))
    return threshold(view, p)


def tasks(groups):
    return [(family, task) for family, members in groups.items() for task in members]


def run(config, out):
    history_tasks = tasks(config["history"])
    test_tasks = tasks(config["test"])
    require(not set(config["history"]) & set(config["test"]), "Family overlap")
    ids = [task for _, task in history_tasks + test_tasks] + config["development"]
    require(len(ids) == len(set(ids)), "Task overlap")
    probabilities = {x: F(p) for x, p in config["probabilities"].items()}

    history = []
    rng = Random(config["history_seed"])
    for family, task in history_tasks:
        for context, p in probabilities.items():
            assignments = list(ARMS) * config["history_per_action"]
            rng.shuffle(assignments)
            for arm in assignments:
                state = "H" if rng.random() < p else "P"
                row = execute(Session(context, state, task=task, per_call=True), fixed(arm))
                row.update(family=family, task_id=task, arm=arm, assignment_probability="1/2")
                write(out / f"history-{len(history):04d}.json", row)
                require(not row["score"]["issues"], f"Invalid historical trace: {task}")
                history.append(row)
    fitted = fit(history)
    write(out / "input_hashes.json", {task: load_case(task, "P1")["hashes"]
                                       for _, task in history_tasks + test_tasks})
    write(out / "estimates.json", {**fitted, **{
        k: [{"key": key, **stat} for key, stat in fitted[k].items()] for k in ("task", "switch")
    }})
    result = defaultdict(lambda: defaultdict(lambda: {"n": 0, "completed": 0, "tool_fee": 0,
                                                       "diagnostic_fee": 0, "calls": 0}))
    rng = Random(config["test_seed"])
    pair = 0
    for family, task in test_tasks:
        for context, p in probabilities.items():
            for _ in range(config["test_per_context"]):
                state = "H" if rng.random() < p else "P"
                sessions = {arm: Session(context, state, task=task, per_call=True)
                            for arm in (*ARMS, "retry_only")}
                initial = sessions["switch"].view()
                selected = {name: select(name, initial, fitted) for name in BASELINES}
                rows = {}
                for arm, session in sessions.items():
                    row = execute(session, fixed(arm))
                    write(out / f"test-{pair:04d}-{arm}.json", row)
                    require(not row["score"]["issues"], f"Invalid paired trace: {pair}/{arm}")
                    require(row["views"][0] == initial, f"Pair prefix mismatch: {pair}")
                    rows[arm] = row
                write(out / f"test-{pair:04d}-selection.json",
                      {"family": family, "task": task, "context": context, "selection": selected})
                for name, arm in selected.items():
                    row = rows[arm]
                    for group in (family, f"{family}/{context}"):
                        metrics = result[group][name]
                        metrics["n"] += 1
                        metrics["completed"] += row["score"]["legal_success"]
                        metrics["tool_fee"] += row["tool_fee"]
                        metrics["diagnostic_fee"] += row["diagnostic_fee"]
                        metrics["calls"] += row["recovery_calls"]
                pair += 1
    return {"history": len(history), "test_pairs": pair, "groups": result,
            "complete_btm": "not run"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    out = parser.parse_args().out
    out.mkdir(parents=True, exist_ok=False)
    config = json.loads(CONFIG.read_text())
    write(out / "config.json", {**config, "commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True).strip(), "python": platform.python_version(),
        "model": None, "inference_framework": None})
    try:
        write(out / "evaluation.json", run(config, out))
    except Exception as error:
        write(out / "failure.json", {"error": repr(error)})
        raise


if __name__ == "__main__":
    main()
