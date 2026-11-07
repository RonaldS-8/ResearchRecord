"""Run the preregistered exact comparisons and paired cloud replay."""
import argparse
import json
from fractions import Fraction as F
import platform
from pathlib import Path
import subprocess

from .mvp import DIAGNOSIS, POLICIES, PRIORS, STATES, Session, best_policy, diagnostic_value, signal_outcomes, values, diagnostic_probability, rank, weighted


def write(path, data):
    with path.open("x") as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False, default=str)


def execute(session, choose):
    views = [session.view()]
    while not views[-1]["done"]:
        views.append(session.act(choose(session.view())))
    return {"views": views, **session.audit()}


def fixed(policy):
    return lambda view: POLICIES[policy][len(view["decisions"])]


def feedback_policy(view):
    decisions = view["decisions"]
    if not decisions:
        return "diagnose"
    if len(decisions) > 1:
        return "switch"
    report = decisions[0]["report"]
    accuracy = F(view["diagnostic_accuracy"])
    return POLICIES[best_policy(accuracy if report else 1 - accuracy)][0]


def score(row):
    return F(row["score"]["legal_success"]), row["tool_fee"] + row["diagnostic_fee"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def run(out):
    summary = {}
    for context in ("A", "B"):
        prior = PRIORS[context]
        initial_views = []
        estimates = {}
        for policy in POLICIES:
            branches = []
            for state, mass in zip(STATES, (prior, 1 - prior)):
                session = Session(context, state)
                initial = session.view()
                row = execute(session, fixed(policy))
                write(out / f"{context}-{state}-{policy}.json", row)
                initial_views.append(initial)
                require(not row["score"]["issues"], f"Invalid trace: {context}/{state}/{policy}")
                branches.append((mass, score(row)))
            estimates[policy] = weighted(branches, F(0))
        require(all(view == initial_views[0] for view in initial_views), "Initial view mismatch")
        require(estimates == values(prior), f"Exact value mismatch: {context}")
        summary[context] = {"values": estimates, "best": best_policy(prior)}

    prior = PRIORS["feedback"]
    for accuracy in (F(4, 5), F(1, 2)):
        branches = []
        initial_views = []
        for state in STATES:
            for report, _, _ in signal_outcomes(prior, accuracy):
                probability = diagnostic_probability(state, report, accuracy)
                # With these registered accuracies, 0 and 9/10 produce either report.
                session = Session("feedback", state, accuracy, F(0) if report else F(9, 10))
                initial_views.append(session.view())
                row = execute(session, feedback_policy)
                write(out / f"feedback-{accuracy.numerator}-{state}-{report}.json", row)
                require(row["views"][1]["decisions"][-1]["report"] == report
                        and not row["score"]["issues"], "Invalid feedback trace")
                branches.append((F(1, 2) * probability, score(row)))
        require(all(view == initial_views[0] for view in initial_views), "Feedback view mismatch")
        diagnosis = weighted(branches, F(0))
        require(diagnosis == diagnostic_value(prior, accuracy), "Diagnostic value mismatch")
        no_diagnosis = values(prior)[best_policy(prior)]
        summary[str(accuracy)] = {"diagnose": diagnosis, "no_diagnosis": no_diagnosis,
                                  "best": max((diagnosis, no_diagnosis), key=rank)}
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    out = parser.parse_args().out
    out.mkdir(parents=True, exist_ok=False)
    write(out / "config.json", {
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "python": platform.python_version(), "model": None, "inference_framework": None,
        "seed": None, "task": "C2-018", "priors": PRIORS,
        "policies": POLICIES, "diagnostic_cost": DIAGNOSIS,
        "feedback_accuracy": ["4/5", "1/2"], "initial": Session("A", "H").view(),
    })
    try:
        write(out / "evaluation.json", run(out))
    except Exception as error:
        write(out / "failure.json", {"error": repr(error)})
        raise


if __name__ == "__main__":
    main()
