"""Exact finite-horizon enumeration for the registered C2-018 pilot."""
from fractions import Fraction as F
from functools import lru_cache
from itertools import product

DECISIONS = 8
STATES = ("T", "H", "P")


def after_failure(state, hazard):
    if state == "T":
        return (("T", 1 - hazard), ("H", hazard))
    return ((state, F(1)),)


def diagnostic_probability(state, recovered, accuracy):
    return accuracy if recovered == (state == "H") else 1 - accuracy


def rank(value):
    success, cost = value
    return success, -cost


def weighted(branches, charge):
    return (
        sum(p * value[0] for p, value in branches),
        charge + sum(p * value[1] for p, value in branches),
    )


class Pilot:
    def __init__(self, hazard, accuracy, diagnostic_cost, retry_cost, recovered_cost, switch_cost):
        self.hazard = hazard
        self.accuracy = accuracy
        self.diagnostic_cost = diagnostic_cost
        self.retry_cost = retry_cost
        self.recovered = (F(1), recovered_cost)
        self.switched = (F(1), switch_cost)
        self.stopped = (F(0), F(0))
        self.prior = ((1 - hazard) / 2, hazard / 2, F(1, 2))
        self.optimal = lru_cache(None)(self._optimal)

    def failed(self, belief):
        t, _, p = belief
        failure = t + p
        if not failure:
            return failure, None
        weights = dict(after_failure("T", self.hazard))
        return failure, (t * weights["T"] / failure, t * weights["H"] / failure, p / failure)

    def diagnosis(self, belief):
        for report in (False, True):
            mass = tuple(p * diagnostic_probability(s, report, self.accuracy)
                         for s, p in zip(STATES, belief))
            probability = sum(mass)
            if probability:
                yield report, probability, tuple(p / probability for p in mass)

    def retry(self, belief, remaining, continuation):
        failure, posterior = self.failed(belief)
        branches = [(belief[1], self.recovered)]
        if failure:
            branches.append((failure, continuation(posterior, remaining - 1)))
        return weighted(branches, self.retry_cost)

    def _optimal(self, belief, remaining, allow_diagnosis=True, oracle=False):
        if not remaining:
            return self.stopped, ("budget",)
        if oracle and 1 not in belief:
            branches = [(p, self.optimal(tuple(F(i == j) for i in range(3)), remaining,
                                         allow_diagnosis, True)[0])
                        for j, p in enumerate(belief) if p]
            return weighted(branches, F(0)), ("observe_state",)
        continuation = lambda b, n: self.optimal(b, n, allow_diagnosis, oracle)[0]
        actions = {"stop": self.stopped, "switch": self.switched,
                   "retry": self.retry(belief, remaining, continuation)}
        if allow_diagnosis and not oracle:
            actions["diagnose"] = weighted(
                [(p, continuation(b, remaining - 1)) for _, p, b in self.diagnosis(belief)],
                self.diagnostic_cost,
            )
        best = max(actions.values(), key=rank)
        return best, tuple(action for action, value in actions.items() if value == best)

    def baselines(self, allow_diagnosis=True):
        @lru_cache(None)
        def threshold(belief, remaining, retries):
            if not remaining:
                return self.stopped
            if not retries:
                return self.switched
            return self.retry(belief, remaining, lambda b, n: threshold(b, n, retries - 1))

        @lru_cache(None)
        def diagnose_rule(belief, remaining, before, samples, reports, limits):
            if not remaining:
                return self.stopped
            if before:
                return self.retry(belief, remaining, lambda b, n:
                                  diagnose_rule(b, n, before - 1, samples, reports, limits))
            if samples:
                return weighted([
                    (p, diagnose_rule(b, remaining - 1, 0, samples - 1, reports + signal, limits))
                    for signal, p, b in self.diagnosis(belief)
                ], self.diagnostic_cost)
            return threshold(belief, remaining, limits[reports])

        def memory_value(table):
            @lru_cache(None)
            def visit(belief, remaining, failed, report=None):
                if not remaining:
                    return self.stopped
                action = table[int(failed)] if report is None else table[2 + 2 * failed + report]
                if action == "switch":
                    return self.switched
                if action == "retry":
                    return self.retry(belief, remaining, lambda b, n: visit(b, n, True))
                return weighted([(p, visit(b, remaining - 1, failed, signal))
                                 for signal, p, b in self.diagnosis(belief)], self.diagnostic_cost)

            return visit(self.prior, DECISIONS, False)

        def best(candidates):
            value = max(candidates.values(), key=rank)
            return value, [key for key, result in candidates.items() if result == value]

        simple_actions = ("switch", "retry", "diagnose") if allow_diagnosis else ("switch", "retry")
        results = {
            "threshold": best({n: threshold(self.prior, DECISIONS, n) for n in range(DECISIONS + 1)}),
            "one_bit": best({table: memory_value(table)
                             for table in product(simple_actions, simple_actions,
                                                  *[("switch", "retry")] * 4)}),
        }
        if allow_diagnosis:
            candidates = {}
            for count in (1, 2):
                for before in range(DECISIONS - count):
                    limits = range(DECISIONS - count - before + 1)
                    for mapping in product(limits, repeat=count + 1):
                        key = (before, count, mapping)
                        candidates[key] = diagnose_rule(self.prior, DECISIONS, before, count, 0, mapping)
            results["diagnosis_rule"] = best(candidates)
        return results
