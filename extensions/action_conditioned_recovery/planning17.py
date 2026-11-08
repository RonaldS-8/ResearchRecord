"""Calibrated two-state filtering and finite recovery action values."""
from fractions import Fraction as F
from functools import cache

from .gate14 import binary
from .gate16 import rank
from .workflow16 import Progress, actions
from .workflow17 import PRICES, advance

HALF = F(1, 2)
ZERO = (F(0), F(0), F(0))


def rate(p, accuracy):
    return p * accuracy + (1 - p) * (1 - accuracy)


def update(p, report, accuracy):
    sensitivity = accuracy if report else 1 - accuracy
    return p * sensitivity / rate(p, sensitivity)


class Planner:
    def __init__(self, q, stay, backup, accuracy, fee):
        self.q, self.stay, self.backup, self.accuracy, self.fee = map(F, (q, stay, backup, accuracy, fee))
        self.values = cache(self.values)
        self.solve = cache(self.solve)

    def belief(self, view, memory="full", marginal=HALF):
        if memory == "fixed":
            return marginal
        hints = [row["output"]["quality"] for row in view["history"] if "quality" in row["output"]]
        evidence = [("cue", report, accuracy) for report, accuracy in zip(hints, (F(4, 5), F(3, 5)))]
        evidence += [(d["action"], d["report"], self.accuracy if d["action"] == "diagnose"
                      else F(9, 10)) for d in view["decisions"]]
        p = HALF
        if memory == "last":
            evidence = evidence[-1:]
        for i, (action, report, accuracy) in enumerate(evidence):
            if action != "B":
                p = update(p, report, accuracy)
            if (action in PRICES and report) or (action == "cue" and i == 0 and len(hints) == 2
                                                and memory == "full"):
                p = rate(p, self.stay)
        return p

    def solve(self, state, p, target=2, fixed=False):
        if state.terminal or state.slot > target:
            complete = state.terminal == "complete" or state.slot > target
            return F(complete), F(0), F(0)
        options = self.values(state, p, target, fixed)
        if fixed:
            local = self.values(state, p, state.slot)
            return options[max(local, key=lambda a: rank(local[a]))]
        return max(options.values(), key=rank)

    def values(self, state, p, target=2, fixed=False):
        values = {}
        for action in actions(state):
            if action == "stop":
                values[action] = ZERO
                continue
            accuracy = self.accuracy if action == "diagnose" else F(9, 10)
            success = self.backup if action == "B" else rate(p, accuracy)
            result = [F(0), PRICES.get(action, F(0)), self.fee if action == "diagnose" else F(0)]
            for report, mass in binary(True, success):
                if not mass:
                    continue
                posterior = p if action == "B" else update(p, report, accuracy)
                if report and action in PRICES:
                    posterior = rate(posterior, self.stay)
                routes = binary(True, self.q) if state.slot == 1 and report and action in PRICES else ((None, F(1)),)
                for route, weight in routes:
                    if weight:
                        after = advance(state, action, report, route)
                        for i, value in enumerate(self.solve(after, posterior, target, fixed)):
                            result[i] += mass * weight * value
            values[action] = tuple(result)
        return values

    def closed(self, state, p):
        """Closed cost expression when all B calls can finish within budget."""
        if self.backup != 1 or state.tried or state.budget < 2 * (3 - state.slot):
            return self.values(state, p, 2, True)

        def route_cost(current, tail, probability):
            good = rate(current, F(9, 10))
            after_good = rate(update(current, True, F(9, 10)), self.stay)
            after_bad = rate(update(current, False, F(9, 10)), self.stay)
            a, b = PRICES["A"], PRICES["B"]
            return {"B": b + probability * tail(rate(current, self.stay)),
                    "A": a + (1 - good) * b + probability * (
                        good * tail(after_good) + (1 - good) * tail(after_bad))}

        def last(current):
            return min(PRICES["B"], PRICES["A"] + (1 - rate(current, F(9, 10))) * PRICES["B"])

        def middle(current):
            return min(route_cost(current, last, self.q).values())

        def cost(current):
            if state.slot == 2:
                return route_cost(current, last, 0)
            return route_cost(current, last, self.q) if state.slot == 1 else route_cost(current, middle, 1)

        options = {a: (F(1), v, F(0)) for a, v in cost(p).items()}
        if state.probe:
            future = sum(mass * min(cost(update(p, report, self.accuracy)).values())
                         for report, mass in binary(True, rate(p, self.accuracy)) if mass)
            options["diagnose"] = (F(1), future, self.fee)
        options["stop"] = ZERO
        return options


def choose(label, planner, view, marginal=HALF, tape=None):
    if label in ("fixed_retry", "fixed_switch"):
        order = ("A", "B", "stop") if label == "fixed_retry" else ("B", "A", "stop")
        return next(a for a in order if a in view["actions"])
    if label == "oracle":
        slot = view["slot"]
        return next((action for action, works in (("A", tape.a[slot]), ("B", tape.b[slot]))
                     if works and action in view["actions"]), "stop")
    state = Progress(view["slot"], tuple(view["tried"]), view["budget"], "diagnose" in view["actions"])
    memory = {"current_error": "last", "recent_plan": "last", "historical": "fixed"}.get(label, "full")
    p = planner.belief(view, memory, marginal)
    if label == "closed_three":
        options = planner.closed(state, p)
    else:
        target = state.slot if label in ("current_error", "local_full", "historical") else (
            min(2, state.slot + 1) if label == "two_slot" else 2)
        options = planner.values(state, p, target, label == "fixed_continuation")
    return max(options, key=lambda a: rank(options[a]))
