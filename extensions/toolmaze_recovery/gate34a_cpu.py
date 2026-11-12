"""Offline exact finite-state reference, independently checked by real contracts.

This is a CPU acceptance calculation of ideal rule continuations, not an Agent
predictor. Registered laws and latent worlds stay here/on the evaluator side.
"""
from collections import defaultdict, deque
from dataclasses import dataclass, replace, asdict
from fractions import Fraction as Q
from functools import lru_cache
import argparse
import json
from pathlib import Path
import subprocess

from .gate34a import (BACKUP, CALL_BUDGET, DIAGNOSE, MAIN, RESOURCE, VALIDATE, VERIFY,
                      WRITE, Distribution, MechanismSession, evaluate)

STOP = "final_answer"


@dataclass(frozen=True)
class State:
    remaining: int = CALL_BUDGET - 1
    primary: bool = False
    backup: bool = False
    certified: bool = False
    written: bool = False
    verified: bool = False
    diagnosed: bool = False


@dataclass(frozen=True)
class Value:
    success: Q
    cost: Q

    def json(self):
        return {"strict_completion_probability": str(self.success), "expected_suffix_fee": str(self.cost)}


def worlds(distribution, context=None):
    p = distribution.transient_probability(context)
    if distribution.cell != "E":
        return ((True, True, p), (False, True, 1 - p))
    g = distribution.gamma
    return ((True, True, p * g), (True, False, p * (1 - g)),
            (False, True, (1 - p) * (1 - g)), (False, False, (1 - p) * g))


def actions(state, diagnostic):
    """All productive/legal tool classes, including redundant reads and checks.

    References of a given provenance are interchangeable for this one-content
    fixture. Invalid bindings cannot improve success or cost and are dominated
    by stopping. Duplicate writes are forbidden by contract, not a plan option.
    """
    if state.remaining == 0:
        return (STOP,)
    result = [BACKUP, MAIN]
    if state.backup:
        result.append(VALIDATE)
    if (state.primary or state.certified) and not state.written:
        result.append(WRITE)
    if state.written:
        result.append(VERIFY)
    if diagnostic and not state.diagnosed:
        result.append(DIAGNOSE)
    return (*result, STOP)


def transition(state, action, world):
    """Independent finite kernel: no executor imports/state inspection here."""
    transient, hint = world
    following = replace(state, remaining=state.remaining - 1)
    if action == MAIN:
        return replace(following, primary=state.primary or transient), "primary" if transient else "timeout"
    if action == BACKUP:
        return replace(following, backup=True), "backup"
    if action == VALIDATE:
        return replace(following, certified=True), "certificate"
    if action == WRITE:
        return replace(following, written=True), "publication"
    if action == VERIFY:
        return replace(following, verified=True), "verified"
    if action == DIAGNOSE:
        return replace(following, diagnosed=True), "transient_hint" if hint else "persistent_hint"
    raise ValueError("Non-call action")


class ExactReference:
    def __init__(self, distribution, context=None, *, allow_diagnostic=True):
        self.distribution = distribution
        self.context = context
        self.initial = worlds(distribution, context)
        self.diagnostic = distribution.cell == "E" and allow_diagnostic
        self.nodes = {}
        # Cache lifetime is one reference, not all runs retained by a class method.
        self.solve = lru_cache(maxsize=None)(self._solve)
        self.attainable = lru_cache(maxsize=None)(self._attainable)

    def branches(self, state, belief, action):
        groups = defaultdict(list)
        for transient, hint, weight in belief:
            following, observation = transition(state, action, (transient, hint))
            groups[following, observation].append((transient, hint, weight))
        for (following, observation), rows in groups.items():
            probability = sum((r[2] for r in rows), Q())
            yield probability, following, observation, tuple((t, h, w / probability) for t, h, w in rows)

    def action_value(self, state, belief, action):
        if action == STOP:
            return Value(Q(int(state.verified)), Q())
        fee = self.distribution.diagnostic_fee if action == DIAGNOSE else Q(1)
        success, cost = Q(), fee
        for probability, following, _, posterior in self.branches(state, belief, action):
            value, _ = self.solve(following, posterior)
            success += probability * value.success
            cost += probability * value.cost
        return Value(success, cost)

    def _solve(self, state, belief):
        values = {a: self.action_value(state, belief, a) for a in actions(state, self.diagnostic)}
        selected = max(values, key=lambda a: (values[a].success, -values[a].cost))
        self.nodes[state, belief] = (selected, values)
        return values[selected], selected

    def update(self, state, belief, action, observation):
        return next((following, posterior) for _, following, obs, posterior in self.branches(state, belief, action)
                    if obs == observation)

    def _attainable(self, state, belief):
        """All distinct (completion, unconditional cost) pairs of finite plans.

        Identical pairs from different policies are coalesced, not discarded as
        dominated. Branch Cartesian products include every feedback-contingent
        continuation in the finite public-state contract abstraction.
        """
        values = set()
        for action in actions(state, self.diagnostic):
            if action == STOP:
                values.add(Value(Q(int(state.verified)), Q()))
                continue
            fee = self.distribution.diagnostic_fee if action == DIAGNOSE else Q(1)
            partial = {Value(Q(), fee)}
            for probability, following, _, posterior in self.branches(state, belief, action):
                suffixes = self.attainable(following, posterior)
                partial = {Value(a.success + probability * b.success, a.cost + probability * b.cost)
                           for a in partial for b in suffixes}
            values.update(partial)
        return frozenset(values)

    def table(self):
        return [{"public_state": asdict(s), "offline_belief": [(t, h, str(w)) for t, h, w in b],
                 "selected_tool": selected, "values": {a: v.json() for a, v in values.items()}}
                for (s, b), (selected, values) in self.nodes.items()]


def bind_from_view(view, action):
    """CPU rule binding, explicitly separate from the real/model executor.

    Uses only actually observed receipts. This helper is not an Agent runner.
    """
    events = view["history"]
    if action in (MAIN, BACKUP, DIAGNOSE):
        return {"record_id": RESOURCE}
    if action == VALIDATE:
        receipt = next(e["result"] for e in reversed(events) if e["tool"] == BACKUP and "error" not in e["result"])
        return {"record_id": RESOURCE, "pending_ref": receipt["pending_ref"]}
    if action == WRITE:
        evidence = next(e["result"] for e in reversed(events) if "evidence_ref" in e["result"])
        content = next(e["result"]["content"] for e in reversed(events) if "content" in e["result"])
        return {"record_id": RESOURCE, "content": content, "evidence_ref": evidence["evidence_ref"]}
    if action == VERIFY:
        receipt = next(e["result"] for e in reversed(events) if e["tool"] == WRITE and "publication_id" in e["result"])
        return {"publication_id": receipt["publication_id"]}
    raise ValueError("No binding for final answer")


def observation(action, result):
    if result.get("error") == "Upstream request timed out.":
        return "timeout"
    if "error" in result:
        raise AssertionError(result)
    if action == DIAGNOSE:
        return result["signal"]
    return {MAIN: "primary", BACKUP: "backup", VALIDATE: "certificate", WRITE: "publication", VERIFY: "verified"}[action]


def new_world(distribution, context, world):
    transient, hint = world
    session = MechanismSession(transient, signal="transient_hint" if hint else "persistent_hint",
                               context=context, diagnostic_fee=distribution.diagnostic_fee if distribution.cell == "E" else None,
                               _namespace="cpu-counterfactual-receipt-namespace")
    result = session.call(MAIN, {"record_id": RESOURCE})
    assert result == {"error": "Upstream request timed out."}
    return session


def real_replay(distribution, context, world, trace):
    session = new_world(distribution, context, world)
    for action in trace:
        session.call(action, bind_from_view(session.view(), action))
    return session


def check_all_transitions(distribution, context=None):
    """Every reachable abstract state/action checked against native dispatch.

    One representative per provenance-equivalent state is sufficient: the
    fixture has one immutable content, so replacing a valid receipt of a source
    class with another of that same class leaves permissions/results unchanged.
    """
    checked = 0
    for t, h, _ in worlds(distribution, context):
        queue = deque([(State(), ())])
        visited = set()
        while queue:
            state, trace = queue.popleft()
            if state in visited:
                continue
            visited.add(state)
            for action in actions(state, distribution.cell == "E"):
                if action == STOP:
                    session = real_replay(distribution, context, (t, h), trace)
                    assert evaluate(session, "Published and verified.")["strict_success"] == state.verified
                    continue
                expected_state, expected_observation = transition(state, action, (t, h))
                session = real_replay(distribution, context, (t, h), trace)
                result = session.call(action, bind_from_view(session.view(), action))
                assert observation(action, result) == expected_observation, (state, action, result)
                event = session.events[-1]
                assert not event["illegal"]
                assert Q(event["fee"]) == (distribution.diagnostic_fee if action == DIAGNOSE else 1)
                assert (evaluate(session, "Published and verified.")["strict_success"] == expected_state.verified)
                checked += 1
                queue.append((expected_state, (*trace, action)))
    return checked


def plan_action(name, state, reference, belief):
    if state.verified or state.remaining == 0:
        return STOP
    if state.written:
        return VERIFY
    if state.primary or state.certified:
        return WRITE
    if state.backup:
        return VALIDATE
    if name == "stop":
        return STOP
    if name == "switch":
        return BACKUP
    if name == "retry_only":
        return MAIN if state.remaining == CALL_BUDGET - 1 else STOP
    if name == "retry_then_switch":
        return MAIN if state.remaining == CALL_BUDGET - 1 else BACKUP
    if name == "buy_diagnostic" and not state.diagnosed:
        return DIAGNOSE
    return reference.solve(state, belief)[1]


def replay_plan(distribution, context, name, *, oracle=False):
    reference = ExactReference(distribution, context)
    success, cost = Q(), Q()
    witnesses = []
    for t, h, weight in reference.initial:
        belief = reference.initial
        if oracle:
            mass = sum((w for wt, _, w in belief if wt == t), Q())
            belief = tuple((wt, wh, w / mass) for wt, wh, w in belief if wt == t)
        state, trace = State(), []
        session = new_world(distribution, context, (t, h))
        while True:
            # No latent arguments are passed to the selection/binding functions.
            action = plan_action(name, state, reference, belief)
            assert action in actions(state, reference.diagnostic)
            if action == STOP:
                break
            result = session.call(action, bind_from_view(session.view(), action))
            obs = observation(action, result)
            state, belief = reference.update(state, belief, action, obs)
            trace.append(action)
        row = evaluate(session, "Published and verified." if state.verified else "Blocked: incomplete.")
        success += weight * int(row["strict_success"])
        cost += weight * Q(row["suffix_fee"])
        witnesses.append({"private_world": {"transient": t, "signal_transient": h},
                          "weight": str(weight), "continuation": f"cpu_{name}",
                          "oracle": oracle, "trace": trace, "outcome": row})
    return Value(success, cost), witnesses


def calculate(distribution, context=None, *, check_transitions=True):
    reference = ExactReference(distribution, context)
    best, _ = reference.solve(State(), reference.initial)
    plans = ["stop", "retry_only", "retry_then_switch", "switch", "bayes"]
    if distribution.cell == "E":
        plans.append("buy_diagnostic")
    results, witnesses = {}, {}
    for name in plans:
        value, rows = replay_plan(distribution, context, name)
        results[name] = value.json()
        witnesses[name] = rows
        if name == "bayes":
            assert value == best
        if name in ("switch", "retry_then_switch"):
            root_action = BACKUP if name == "switch" else MAIN
            # Each forced root is followed by the optimal rule, which should
            # equal these complete named plans at the registered probabilities.
            assert value == reference.action_value(State(), reference.initial, root_action)
        if name == "buy_diagnostic":
            assert value == reference.action_value(State(), reference.initial, DIAGNOSE)
    oracle, rows = replay_plan(distribution, context, "oracle", oracle=True)
    results["oracle"] = oracle.json()
    witnesses["oracle"] = rows
    if distribution.cell == "E":
        no_diag = ExactReference(distribution, context, allow_diagnostic=False).solve(State(), reference.initial)[0]
        bought = Q(results["buy_diagnostic"]["expected_suffix_fee"])
        results["no_diagnostic"] = no_diag.json()
        results["diagnostic_net_saving_if_bought"] = str(no_diag.cost - bought)
        results["optimal_net_saving"] = str(no_diag.cost - best.cost)
    attainable = reference.attainable(State(), reference.initial)
    assert best == max(attainable, key=lambda v: (v.success, -v.cost))
    return {"cell": distribution.cell, "context": context, "gamma": str(distribution.gamma) if distribution.cell == "E" else None,
            "diagnostic_fee": str(distribution.diagnostic_fee) if distribution.cell == "E" else None, "plans": results,
            "finite_public_decision_nodes": len(reference.nodes),
            "real_contract_transitions_checked": check_all_transitions(distribution, context) if check_transitions else None,
            "all_distinct_finite_plan_values": [v.json() for v in sorted(attainable, key=lambda v: (v.success, v.cost))],
            "state_action_values": reference.table(), "witnesses": witnesses}


def registered_cases():
    yield Distribution("A"), None
    for context in ("X1", "X2"):
        yield Distribution("B"), context
    for gamma in (Q(4, 5), Q(9, 10), Q(1, 2)):
        for fee in (Q(1, 10), Q(1, 2)):
            yield Distribution("E", gamma, fee), None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "commit.txt").write_text(subprocess.check_output(["git", "rev-parse", "HEAD"], text=True))
    # Individual exclusive files retain all prior cases if a later check fails.
    results = []
    for index, (distribution, context) in enumerate(registered_cases()):
        result = calculate(distribution, context)
        results.append(result)
        with (args.out / f"case-{index:02d}.json").open("x") as stream:
            json.dump(result, stream, indent=2)
        print(json.dumps({k: result[k] for k in ("cell", "context", "gamma", "diagnostic_fee", "plans",
                                               "finite_public_decision_nodes", "real_contract_transitions_checked")}))
    b = [r for r in results if r["cell"] == "B"]
    summary = {"B_equal_context_average": {
        name: {"strict_completion_probability": str(sum(Q(r["plans"][name]["strict_completion_probability"]) for r in b) / 2),
               "expected_suffix_fee": str(sum(Q(r["plans"][name]["expected_suffix_fee"]) for r in b) / 2)}
        for name in ("retry_then_switch", "switch", "bayes", "oracle")},
        "registered_cases": len(results),
        "real_contract_transitions_checked": sum(r["real_contract_transitions_checked"] for r in results),
        "public_decision_nodes": sum(r["finite_public_decision_nodes"] for r in results),
        "distinct_plan_value_pairs_per_case": [len(r["all_distinct_finite_plan_values"]) for r in results]}
    with (args.out / "summary.json").open("x") as stream:
        json.dump(summary, stream, indent=2)
    (args.out / "passed.txt").write_text("All registered exact references and real-contract witnesses agree.\n")


if __name__ == "__main__":
    main()
