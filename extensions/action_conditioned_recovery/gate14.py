"""Exact paired recovery experiment under shift in historical applicability."""
import argparse
from collections import defaultdict
from fractions import Fraction as F
import json
from pathlib import Path
import platform
import subprocess
from typing import NamedTuple

from .multistep import REPORTS, Session
from .mvp import rank, weighted
from .run import execute, require, score, write

CONFIG = Path(__file__).with_name("gate14.json")
ACTIONS = ("switch", "retry", "diagnose", "stop")
BASELINES = ("fixed_switch", "fixed_retry", "no_history", "old_threshold", "old_action_value",
             "one_bit", "simple_feedback", "simple_probe", "public_optimal", "stop")


class Realization(NamedTuple):
    applies: bool
    first: bool
    second: bool
    cue: bool | None
    probe: bool
    report: str


def binary(truth, accuracy):
    return ((truth, accuracy), (not truth, 1 - accuracy))


def support(cell):
    for applies in (False, True):
        for first, p in binary(True, F(3, 4) if applies else F(1, 4)):
            for second in (False, True):
                cues = binary(applies, F(4, 5)) if cell["cue"] else ((None, F(1)),)
                for cue, c in cues:
                    for probe, d in binary(first, F(cell["accuracy"])):
                        for report, e in binary(second, F(4, 5) if cell["execution"] else F(1, 2)):
                            yield p * c * d * e / 4, Realization(
                                applies, first, second, cue, probe, REPORTS[0 if report else 1])


class Recovery:
    """Wrap the strictly verified workflow with a separately billed evidence channel."""

    def __init__(self, family, cell, sample):
        self._session = Session(family, "shared_error", (sample.first, sample.second, sample.report))
        self._prepared_index = len(self._session.view()["history"]) - 2
        self._cue = sample.cue
        self._probe = sample.probe
        self._accuracy = cell["accuracy"]
        self._execution = cell["execution"]
        self._fee = F(cell["fee"])
        self._diagnosis = []
        self._started = False

    def view(self):
        view = self._session.view()
        if self._cue is not None:
            view["history"][self._prepared_index]["output"]["compatibility"] = self._cue
        view["existing_compatibility"] = self._cue
        view["prices"]["diagnose"] = str(self._fee)
        view["calibration"] = {"accuracy": self._accuracy, "execution_informative": self._execution}
        if not view["done"] and not self._started and not self._diagnosis:
            view["actions"].append("diagnose")
            view["remaining_decisions"] += 1
        if self._diagnosis:
            view["decisions"] = [self._diagnosis[0]["observation"], *view["decisions"]]
        return view

    def act(self, action):
        if action not in self.view()["actions"]:
            raise ValueError("Action unavailable")
        if action == "diagnose":
            self._diagnosis.append({"observation": {"action": "diagnose", "report": self._probe},
                                    "fee": self._fee})
        else:
            self._started = True
            self._session.act(action)
        return self.view()

    def audit(self):
        row = self._session.audit()
        fee = sum(probe["fee"] for probe in self._diagnosis)
        expected = [{"observation": {"action": "diagnose", "report": self._probe},
                     "fee": self._fee}] if self._diagnosis else []
        if self._diagnosis != expected or row["tool_fee"] != row["recovery_calls"]:
            row["score"]["issues"].append("Independent recovery bill mismatch")
            row["score"]["legal_success"] = False
        return {**row, "diagnostic_fee": fee, "diagnostic_ledger": self._diagnosis,
                "existing_compatibility": self._cue}


def history_key(view):
    key = []
    errors = [e["output"]["error"] for e in view["history"]
              if e["tool"] == "commit_primary" and "error" in e["output"]]
    for decision in view["decisions"]:
        if decision["action"] == "diagnose":
            key.append(("diagnose", decision["report"]))
        elif decision["action"] == "retry":
            retries = sum(action == "retry" for action, _ in key)
            key.append(("retry", errors[1] if retries == 0 and not decision["recovered"] else None))
    return view["existing_compatibility"], tuple(key)


def exact_policy(samples, cell):
    """Enumerate legal plans by grouping on observations, without policy thresholds."""
    plans = {}

    def visit(group, cue, path):
        mass = sum(weight for weight, _ in group)
        choices = {"switch": (F(1), F(2))}
        retries = sum(action == "retry" for action, _ in path)
        if retries < 2:
            success = F(0)
            failed = defaultdict(list)
            for weight, sample in group:
                recovered = sample.second if retries else sample.first
                if recovered:
                    success += weight
                else:
                    failed[None if retries else sample.report].append((weight, sample))
            branches = [(success / mass, (F(1), F(0)))]
            for report, rows in failed.items():
                branches.append((sum(w for w, _ in rows) / mass,
                                 visit(rows, cue, path + (("retry", report),))))
            choices["retry"] = weighted(branches, F(1))
        if not path:
            by_probe = defaultdict(list)
            for weight, sample in group:
                by_probe[sample.probe].append((weight, sample))
            choices["diagnose"] = weighted(
                [(sum(w for w, _ in rows) / mass, visit(rows, cue, (("diagnose", report),)))
                 for report, rows in by_probe.items()], F(cell["fee"]))
        choices["stop"] = (F(0), F(0))
        best = max(choices, key=lambda action: rank(choices[action]))
        plans[cue, path] = best
        return choices[best]

    by_cue = defaultdict(list)
    for weight, sample in samples:
        by_cue[sample.cue].append((weight, sample))
    value = weighted([(sum(w for w, _ in rows), visit(rows, cue, ()))
                      for cue, rows in by_cue.items()], F(0))
    return value, lambda view: plans[history_key(view)]


def posterior(p, observation, accuracy):
    a = accuracy if observation else 1 - accuracy
    return p * a / (p * a + (1 - p) * (1 - a))


def simple_policy(name):
    def choose(view):
        cue, path = history_key(view)
        retries = sum(action == "retry" for action, _ in path)
        if name == "stop":
            return "stop"
        if name in ("fixed_switch", "no_history"):
            return "switch"
        if name == "fixed_retry":
            return "switch" if retries else "retry"

        uses_feedback = name in ("old_action_value", "simple_feedback", "simple_probe")
        informative = uses_feedback and view["calibration"]["execution_informative"]
        if retries:
            return "retry" if retries == 1 and informative and path[-1][1] == REPORTS[0] else "switch"

        p = F(3, 4) if name.startswith("old_") else {True: F(13, 20), False: F(7, 20), None: F(1, 2)}[cue]
        accuracy = F(view["calibration"]["accuracy"])
        if path:
            p = posterior(p, path[0][1], accuracy)
        failure_cost = F(17, 10) if informative else F(2)

        def retry_cost(probability):
            return 1 + (1 - probability) * failure_cost

        immediate = min(F(2), retry_cost(p))
        if name in ("old_action_value", "simple_probe") and "diagnose" in view["actions"]:
            positive = p * accuracy + (1 - p) * (1 - accuracy)
            after = positive * min(F(2), retry_cost(posterior(p, True, accuracy)))
            after += (1 - positive) * min(F(2), retry_cost(posterior(p, False, accuracy)))
            if F(view["prices"]["diagnose"]) + after < immediate:
                return "diagnose"
        return "retry" if retry_cost(p) < 2 else "switch"

    return choose


def run_cell(family, cell, directory):
    samples = list(support(cell))
    require(sum(weight for weight, _ in samples) == 1, "Invalid probability mass")
    theory, optimal = exact_policy(samples, cell)
    require(theory == (F(1), F(cell["expected"])), "Enumeration disagrees with preregistration")
    outcomes = defaultdict(list)
    same_view = {}
    differences = defaultdict(int)
    oracle = F(0)
    for i, (weight, sample) in enumerate(samples):
        rows = {}
        oracle += weight * (1 if sample.first else 2)
        for name in BASELINES:
            policy = optimal if name == "public_optimal" else simple_policy(name)
            row = execute(Recovery(family, cell, sample), policy)
            view = row["views"][0]
            require(view == same_view.setdefault(sample.cue, view), "Public view leaks hidden state")
            require(not row["score"]["issues"], "Execution or ledger check failed")
            require(row["score"]["legal_success"] == (name != "stop"), "Strict completion mismatch")
            rows[name] = row
            outcomes[name].append((weight, sample.applies, row))
        for key, left in (("probe_vs_feedback", "simple_probe"), ("old_vs_feedback", "old_action_value"),
                          ("optimal_vs_probe", "public_optimal")):
            right = "simple_probe" if left == "public_optimal" else "simple_feedback"
            if rows[left]["views"][1]["decisions"][0]["action"] != rows[right]["views"][1]["decisions"][0]["action"]:
                differences[key] += weight
        write(directory / f"{i:03}.json", {"weight": weight, "realization": sample._asdict(), "rows": rows})

    def summary(entries):
        mass = sum(w for w, _, _ in entries)
        return {
            "complete": sum(w * score(row)[0] for w, _, row in entries) / mass,
            "tool_fee": sum(w * row["tool_fee"] for w, _, row in entries) / mass,
            "diagnostic_fee": sum(w * row["diagnostic_fee"] for w, _, row in entries) / mass,
            "calls": sum(w * row["recovery_calls"] for w, _, row in entries) / mass,
        }

    results = {name: {"all": summary(entries),
                      "applicable": summary([e for e in entries if e[1]]),
                      "shifted": summary([e for e in entries if not e[1]])}
               for name, entries in outcomes.items()}
    require(weighted([(w, score(row)) for w, _, row in outcomes["public_optimal"]], F(0)) == theory,
            "Exact public policy disagrees with replay")
    return {"policies": results, "oracle_cost": oracle, "first_action_disagreements": differences,
            "realizations": len(samples)}


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
            result[name] = run_cell(config["family"], cell, directory)
        write(out / "evaluation.json", result)
    except Exception as error:
        write(out / "failure.json", {"error": repr(error)})
        raise


if __name__ == "__main__":
    main()
