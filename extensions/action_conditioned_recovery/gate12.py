"""Fit recovery rules on one workflow and execute weighted pairs on another."""
import argparse
from collections import defaultdict
from fractions import Fraction as F
import json
from pathlib import Path
import platform
from random import Random
import subprocess

from .multistep import REPORTS, Session
from .mvp import rank, weighted
from .run import execute, require, score, write

CONFIG = Path(__file__).with_name("gate12.json")
POLICIES = ("switch", "retry_then_switch", "task_rate", "context_threshold",
            "one_bit", "feedback_threshold", "action_value", "known_feedback")


def support(p, accuracy):
    yield p, (True, False, REPORTS[0])
    for recovered in (True, False):
        for i, report in enumerate(REPORTS):
            likelihood = accuracy if recovered == (i == 0) else 1 - accuracy
            yield (1 - p) * likelihood / 2, (False, recovered, report)


def fit(rows):
    first, second, reports, completion = (defaultdict(list) for _ in range(4))
    for row in rows:
        context = row["views"][0]["context"]
        initial = row["decisions"][0]
        finished = row["score"]["legal_success"]
        completion["episode"].append(finished)
        if any(d["action"] == "switch" for d in row["decisions"]):
            completion["switch_transition"].append(finished)
        if initial["action"] == "switch":
            completion["direct_switch"].append(finished)
            continue
        first[context].append(initial["recovered"])
        if initial["recovered"]:
            completion["first_success"].append(finished)
            continue
        view = row["views"][1]
        report = view["history"][-1]["output"]["error"]
        reports["high"].append(report == REPORTS[0])
        followup = row["decisions"][1]
        if followup["action"] == "switch":
            completion["after_failure_switch"].append(finished)
            continue
        recovered = followup["recovered"]
        second[report].append(recovered)
        second["pooled"].append(recovered)
        completion["second_success" if recovered else "after_second_failure_switch"].append(finished)

    def summarize(groups, prior):
        return {key: {"p": F(sum(obs) + prior, len(obs) + 2 * prior), "n": len(obs)}
                for key, obs in groups.items()}

    return {"first": summarize(first, 1), "second": summarize(second, 1),
            "reports": summarize(reports, 1), "completion": summarize(completion, 0)}


def recovery_policy(name, fitted, informative):
    def choose(view):
        r, s = (F(view["prices"][k]) for k in ("retry", "switch"))
        retry_count = len(view["decisions"])
        if "retry" not in view["actions"] or name == "switch":
            return "switch"
        if name == "retry_then_switch":
            return "retry" if retry_count == 0 else "switch"
        if name == "known_feedback":
            if retry_count:
                return "retry" if informative and last_error(view) == REPORTS[0] else "switch"
            return "retry" if view["context"] == "A" or informative and view["context"] == "M" else "switch"

        def rate(group, key, default):
            return fitted[group].get(key, {}).get("p", default)

        def completion(key):
            if name == "task_rate":
                return rate("completion", "episode", F(1))
            return rate("completion", key, F(1)) if name == "action_value" else F(1)

        def late(report):
            p = F(1, 2)
            if name in ("one_bit", "feedback_threshold", "action_value"):
                p = rate("second", "pooled", p)
            if name in ("feedback_threshold", "action_value"):
                p = rate("second", report, p)
            return {
                "switch": (completion("after_failure_switch"), s),
                "retry": (p * completion("second_success")
                          + (1 - p) * completion("after_second_failure_switch"), r + (1 - p) * s),
            }

        if retry_count:
            options = late(last_error(view))
        else:
            high = rate("reports", "high", F(1, 2))
            after_failure = weighted(
                [(mass, max(late(report).values(), key=rank))
                 for mass, report in zip((high, 1 - high), REPORTS)], F(0))
            # Episode completion does not identify a retry rate. This arm uses the frozen
            # public-cost fallback, even though the shared episode key has history coverage.
            p = F(1, 2) if name == "task_rate" else rate("first", view["context"], F(1, 2))
            options = {"switch": (completion("direct_switch"), s),
                       "retry": weighted([(p, (completion("first_success"), F(0))),
                                          (1 - p, after_failure)], r)}
        return max(options, key=lambda action: rank(options[action]))

    return choose


def last_error(view):
    return view["history"][-1]["output"]["error"]


def train(config, accuracy, probabilities):
    rng = Random(config["seed"])
    rows = []
    for context, p in probabilities.items():
        arms = ["retry", "switch"] * config["history_per_arm"]
        rng.shuffle(arms)
        followup = []
        for arm in arms:
            first = rng.random() < p
            second = rng.random() < F(1, 2)
            high = second == (rng.random() < accuracy)
            report = REPORTS[0 if high else 1]
            if arm == "retry" and not first and not followup:
                followup = ["retry", "switch"]
                rng.shuffle(followup)
            next_action = followup.pop() if arm == "retry" and not first else "switch"
            actions = (arm, next_action, "switch")
            row = execute(Session(config["history_family"], context, (first, second, report)),
                          lambda view: actions[len(view["decisions"])])
            row["assignment"] = {"first": arm, "first_probability": "1/2",
                                 "on_failure": next_action if arm == "retry" and not first else None,
                                 "failure_block": 2}
            rows.append(row)
    return rows


def run(config, out):
    require(config["history_family"] != config["test_family"], "Task family overlap")
    probabilities = {x: F(p) for x, p in config["first_retry_probabilities"].items()}
    results = {}
    for panel, raw_accuracy in config["accuracy"].items():
        accuracy = F(raw_accuracy)
        directory = out / panel
        directory.mkdir()
        training = train(config, accuracy, probabilities)
        write(directory / "history.json", training)
        require(all(not row["score"]["issues"] for row in training), "Invalid training trace")
        fitted = fit(training)
        write(directory / "estimates.json", fitted)
        metrics = {}
        for context, p in probabilities.items():
            totals, actions = defaultdict(list), defaultdict(lambda: defaultdict(F))
            forced = defaultdict(list)
            for i, (mass, fault) in enumerate(support(p, accuracy)):
                initial = None
                rows = {}
                for name in POLICIES:
                    policy = recovery_policy(name, fitted, panel == "informative")
                    row = execute(Session(config["test_family"], context, fault), policy)
                    rows[name] = row
                    require(not row["score"]["issues"] and row["score"]["legal_success"],
                            f"Invalid test trace: {panel}/{context}/{i}/{name}")
                    view = row["views"][0]
                    if initial is None:
                        initial = view
                    require(view == initial, "Initial paired view mismatch")
                    totals[name].append((mass, score(row)))
                    for step, decision in enumerate(row["decisions"]):
                        actions[name][f"{step + 1}:{decision['action']}"] += mass

                # Compare second actions from the identical observed failure checkpoint.
                if context == "M" and not fault[0]:
                    paired = {}
                    for action in ("retry", "switch"):
                        plan = ("retry", action, "switch")
                        paired[action] = execute(Session(config["test_family"], context, fault),
                                                 lambda view: plan[len(view["decisions"])])
                        row = paired[action]
                        require(not row["score"]["issues"] and row["score"]["legal_success"],
                                "Invalid forced continuation")
                        forced[fault[2], action].append((mass, F(row["tool_fee"] - 1)))
                    require(paired["retry"]["views"][1] == paired["switch"]["views"][1],
                            "Second-stage paired view mismatch")
                    rows["forced"] = paired
                write(directory / f"{context}-{i}.json", {"weight": mass, "rows": rows})
            metrics[context] = {"outcomes": {name: weighted(rows, F(0)) for name, rows in totals.items()},
                                "actions": actions, "forced_after_failure": [
                                    {"feedback": report, "action": action,
                                     "cost": sum(m * fee for m, fee in rows) / sum(m for m, _ in rows)}
                                    for (report, action), rows in forced.items()]}
        expect = F(37, 20) if panel == "informative" else F(2)
        require(metrics["M"]["outcomes"]["known_feedback"] == (F(1), expect),
                "Known feedback reference disagrees with theory")
        results[panel] = {"history": len(training), "test_cells": 5 * len(probabilities),
                          "metrics": metrics}
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    out = parser.parse_args().out
    out.mkdir(parents=True, exist_ok=False)
    config = json.loads(CONFIG.read_text())
    write(out / "config.json", {**config, "commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True).strip(), "python": platform.python_version(),
        "model": None, "inference_framework": None, "test_seed": None, "complete_btm": "not run"})
    try:
        write(out / "evaluation.json", run(config, out))
    except Exception as error:
        write(out / "failure.json", {"error": repr(error)})
        raise


if __name__ == "__main__":
    main()
