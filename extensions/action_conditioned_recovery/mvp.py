"""Exact values and a restricted C2-018 recovery session for Gate 9."""
from fractions import Fraction as F

from extensions.toolmaze_diagnostic_mvp.environment import json_copy

from .backend import Backend, TOOL_LIMIT

PRIORS = {"A": F(3, 4), "B": F(1, 4), "feedback": F(1, 2)}
STATES = ("H", "P")
RETRY, SWITCH, DIAGNOSIS = F(1), F(2), F(1, 10)
POLICIES = {
    "switch": ("switch",),
    "retry_then_switch": ("retry", "switch"),
    "retry_only": ("retry", "stop"),
    "stop": ("stop",),
}


def rank(value):
    return value[0], -value[1]


def weighted(branches, charge):
    return (sum(p * value[0] for p, value in branches),
            charge + sum(p * value[1] for p, value in branches))


def diagnostic_probability(state, report, accuracy):
    return accuracy if report == (state == "H") else 1 - accuracy


def values(p):
    return {
        "switch": (F(1), SWITCH),
        "retry_then_switch": (F(1), RETRY + (1 - p) * SWITCH),
        "retry_only": (p, RETRY),
        "stop": (F(0), F(0)),
    }


def best_policy(p):
    options = values(p)
    return max(options, key=lambda policy: rank(options[policy]))


def signal_outcomes(p, accuracy):
    for report in (False, True):
        healthy = p * diagnostic_probability("H", report, accuracy)
        blocked = (1 - p) * diagnostic_probability("P", report, accuracy)
        if healthy + blocked:
            yield report, healthy + blocked, healthy / (healthy + blocked)


def diagnostic_value(p, accuracy):
    return weighted(
        [(mass, values(posterior)[best_policy(posterior)])
         for _, mass, posterior in signal_outcomes(p, accuracy)],
        DIAGNOSIS,
    )


class Session:
    def __init__(self, context, state, accuracy=None, draw=F(1, 2), *,
                 task="018", per_call=False):
        if context not in (*PRIORS, "control") or state not in STATES:
            raise ValueError("Unknown context or fault state")
        if (context == "feedback") != (accuracy is not None):
            raise ValueError("Diagnostic calibration is limited to the feedback cell")
        self._context, self._state = context, state
        self._accuracy, self._draw = accuracy, draw
        self._backend = Backend(task)
        self._per_call = per_call
        self._decisions, self._ledger = [], []
        self._done = False

    def view(self):
        backend = self._backend
        actions = []
        retried = any(d["action"] == "retry" for d in self._decisions)
        if not self._done:
            actions = ["switch", "stop"]
            if not retried:
                actions.append("retry")
            if self._accuracy is not None and not self._decisions:
                actions.append("diagnose")
        prices = {"retry": str(RETRY), "switch": str(SWITCH)}
        if self._per_call:
            prices = {
                "retry_success": len(backend.source) - backend.sunk + 1,
                "retry_failure": 1,
                "switch": len(set(backend.target) - set(backend.prefix[:-1])),
            }
        public = {
            "task": backend.case["base"].task_description,
            "tools": [d["paradigms"]["function_call"]["spec"]
                      for d in backend.case["base"].tool_definitions],
            "history": [{k: e[k] for k in ("call_id", "tool", "arguments", "output")}
                        for e in backend.events],
            "context": self._context, "actions": actions, "done": self._done,
            "remaining_tools": TOOL_LIMIT - len(backend.events),
            "remaining_decisions": 0 if self._done else 1 if retried else 2 + int("diagnose" in actions),
            "prices": prices, "decisions": self._decisions,
        }
        if self._accuracy is not None:
            prices["diagnose"] = str(DIAGNOSIS)
            public["diagnostic_accuracy"] = str(self._accuracy)
        return json_copy(public)

    def act(self, action):
        if action not in self.view()["actions"]:
            raise ValueError("Action unavailable")
        backend = self._backend
        start = len(backend.events)
        decision = {"action": action}
        if action == "retry":
            recovered = self._state == "H"
            decision["recovered"] = recovered
            backend.call(backend.victim, blocked=not recovered)
            if recovered:
                backend.finish(backend.source)
                self._done = True
        elif action == "switch":
            backend.finish(backend.target)
            self._done = True
        elif action == "diagnose":
            decision["report"] = self._draw < diagnostic_probability(self._state, True, self._accuracy)
        else:
            self._done = True
        self._decisions.append(decision)
        self._ledger.append({
            "action": action, "calls": list(range(start, len(backend.events))),
            "tool_fee": len(backend.events) - start if self._per_call else
                        {"retry": RETRY, "switch": SWITCH}.get(action, F(0)),
            "diagnostic_fee": DIAGNOSIS if action == "diagnose" else F(0),
        })
        return self.view()

    def audit(self):
        backend = self._backend
        actions = [d["action"] for d in self._decisions]
        retry = "retry" in actions
        switched = "switch" in actions
        failed = retry and self._state != "H"
        path = backend.target if switched else backend.source if retry and not failed else None
        score = backend.verify(backend.events, path, failed)
        recovery_calls = len(backend.events) - backend.sunk
        tool_fee = sum(row["tool_fee"] for row in self._ledger)
        diagnostic_fee = sum(row["diagnostic_fee"] for row in self._ledger)
        calls = [call for row in self._ledger for call in row["calls"]]
        expected_tool = recovery_calls if self._per_call else int(retry) + 2 * int(switched)
        if (calls != list(range(backend.sunk, len(backend.events)))
                or [row["action"] for row in self._ledger] != actions
                or tool_fee != expected_tool
                or diagnostic_fee != actions.count("diagnose") * DIAGNOSIS):
            score["issues"].append("recovery ledger mismatch")
            score["legal_success"] = False
        return {"events": backend.events, "decisions": self._decisions,
                "ledger": self._ledger, "score": score, "recovery_calls": recovery_calls,
                "tool_fee": tool_fee, "diagnostic_fee": diagnostic_fee}
