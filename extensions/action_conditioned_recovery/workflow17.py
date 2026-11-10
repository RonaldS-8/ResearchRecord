"""Keyed stochastic workflow tape and audited three-node execution."""
from fractions import Fraction as F
from hashlib import sha256
import json
from typing import NamedTuple

from extensions.toolmaze_diagnostic_mvp.environment import json_copy

from .general import TASKS
from .workflow15 import CHECKS, INITIAL_ERROR
from .workflow16 import Progress, actions

PRICES = {"A": F(6, 5), "B": F(2)}
FAMILIES = {**TASKS, "archive": ("archive a credential", "credential_id", "C55", "retention", " 90d ")}
NODE = ("acquire", "register", "verify")


class Tape(NamedTuple):
    identity: tuple
    a: tuple
    b: tuple
    extra: bool
    signal: bool


def sample(cell, identity):
    def flip(event, chance):
        key = json.dumps((*identity, event), separators=(",", ":")).encode()
        u = int.from_bytes(sha256(key).digest()[:8], "big")
        return F(u, 2**64) < F(chance)

    health = [flip("state:0", F(1, 2))]
    for i in (1, 2):
        previous = health[-1]
        health.append(previous if flip(f"transition:{i}", cell["stay"]) else not previous)
    a = tuple(flip(f"A:{i}", F(9, 10) if good else F(1, 10)) for i, good in enumerate(health))
    b = tuple(flip(f"B:{i}", cell["backup"]) for i in range(3))
    return Tape(identity, a, b, flip("route:1", cell["q"]),
                health[0] == flip("probe:0", cell["accuracy"]))


def advance(state, action, success, route):
    if action == "stop":
        return state._replace(terminal="blocked_stop" if len(state.tried) == 2 else "premature_stop")
    if action == "diagnose":
        return state._replace(probe=False)
    left = state.budget - 1
    if success and (state.slot == 2 or state.slot == 1 and not route):
        return Progress(state.slot, (), left, False, "complete")
    node, tried = (state.slot + 1, ()) if success else (state.slot, (*state.tried, action))
    return Progress(node, tried, left, False, "exhausted" if left == 0 else "")


def task(family, instance):
    goal, id_key, _, key, value = FAMILIES[family]
    return {"goal": goal, "input": {id_key: instance, key: value}}


def prefix(public_task, hints, slot):
    ready = {k: v.strip() if isinstance(v, str) else v for k, v in public_task["input"].items()}
    events = [{"tool": "prepare", "arguments": public_task["input"], "output": ready}]
    for i, report in enumerate(hints):
        events.append({"tool": f"prepare_quality_{i}", "arguments": ready, "output": {"quality": report}})
    if slot:
        receipt = {"credential": f"{next(iter(ready.values()))}:0"}
        events.append({"tool": "prepared_credential", "arguments": ready, "output": receipt})
        ready = receipt
    events.append({"tool": f"A_{NODE[slot]}", "arguments": ready, "output": {"error": INITIAL_ERROR}})
    return events


class Workflow:
    def __init__(self, cell, tape, *, hints=(), slot=0):
        self.cell, self._tape, self._hints, self._start_slot = cell, tape, hints, slot
        self.task = task(tape.identity[1], f"{tape.identity[0]}-{tape.identity[2]}-{tape.identity[3]}")
        self.prefix = prefix(self.task, hints, slot)
        self.state = Progress(slot, (), cell["budget"], slot == 0)
        self.events, self.decisions, self.ledger, self.diagnostics = [], [], [], []
        self._payload = self.prefix[-1]["arguments"]
        self.effect = None

    def view(self):
        return json_copy({"task": self.task, "history": self.prefix + self.events, "decisions": self.decisions,
                          "slot": self.state.slot, "tried": self.state.tried, "budget": self.state.budget,
                          "actions": actions(self.state), "done": bool(self.state.terminal),
                          "routing_probability": self.cell["q"], "diagnostic_accuracy": self.cell["accuracy"],
                          "prices": {**{a: str(v) for a, v in PRICES.items()}, "diagnose": self.cell["fee"]}})

    def _call(self, tool, args, result, fee):
        self.ledger.append({"index": len(self.events), "tool": tool, "fee": fee})
        self.events.append({"tool": tool, "arguments": args, "output": result})

    def act(self, action):
        state = self.state
        if action not in actions(state):
            raise ValueError("Unavailable recovery action")
        success, route = None, None
        if action == "diagnose":
            success = self._tape.signal
            self.diagnostics.append({"event": "probe:0", "report": success, "fee": F(self.cell["fee"])})
        elif action in PRICES:
            success = (self._tape.a if action == "A" else self._tape.b)[state.slot]
            route = self._tape.extra if success and state.slot == 1 else None
            token = f"{next(iter(self.task['input'].values()))}:{state.slot}"
            result = {"credential": token} if success else {"error": INITIAL_ERROR}
            if route is not None:
                result["extra_verification"] = route
            self._call(f"{action}_{NODE[state.slot]}", self._payload, result, PRICES[action])
            if success:
                self._payload = {"credential": token}
                if state.slot == 0:
                    for check in CHECKS[:self.cell["checks"]]:
                        next_payload = {"credential": self._payload["credential"] + ":" + check}
                        self._call(check, self._payload, next_payload, F(0))
                        self._payload = next_payload
        self.state = advance(state, action, success, route)
        self.decisions.append({"slot": state.slot, "action": action, "report": success, "route": route})
        if self.state.terminal == "complete":
            self.effect = {"goal": self.task["goal"], "credential": self._payload["credential"]}
        return self.view()

    def audit(self):
        issues = verify(self)
        keys = []
        for row in self.decisions:
            slot, action, report = row["slot"], row["action"], row["report"]
            if action in PRICES:
                keys.append(f"{action}:{slot}")
                if report and slot == 1:
                    keys.append("route:1")
                if report and (slot == 0 or slot == 1 and row["route"]):
                    keys.append(f"transition:{slot + 1}")
            elif action == "diagnose":
                keys.append("probe:0")
        return {"score": {"legal_success": not issues and self.state.terminal == "complete", "issues": issues},
                "termination": self.state.terminal, "decisions": self.decisions, "events": self.events,
                "ledger": self.ledger, "diagnostic_ledger": self.diagnostics, "effect": self.effect,
                "tool_fee": sum(row["fee"] for row in self.ledger),
                "diagnostic_fee": sum(row["fee"] for row in self.diagnostics),
                "recovery_calls": len(self.events), "used_random_keys": keys}


def verify(run):
    tape = run._tape
    initial = prefix(task(tape.identity[1], f"{tape.identity[0]}-{tape.identity[2]}-{tape.identity[3]}"),
                     run._hints, run._start_slot)
    if initial != run.prefix:
        return ["prefix or parameter provenance mismatch"]
    state = Progress(run._start_slot, (), run.cell["budget"], run._start_slot == 0)
    inputs = initial[-1]["arguments"]
    events, bill, probes = [], [], []

    def expected_call(tool, args, output, fee):
        bill.append({"index": len(events), "tool": tool, "fee": fee})
        events.append({"tool": tool, "arguments": args, "output": output})

    for row in run.decisions:
        action, slot = row["action"], row["slot"]
        if action not in actions(state) or slot != state.slot:
            return ["illegal action sequence"]
        report, route = None, None
        if action == "diagnose":
            report = tape.signal
            probes.append({"event": "probe:0", "report": report, "fee": F(run.cell["fee"])})
        elif action in PRICES:
            report = tape.a[slot] if action == "A" else tape.b[slot]
            expected_output = {"error": INITIAL_ERROR}
            if report:
                identifier = next(iter(run.task["input"].values()))
                expected_output = {"credential": f"{identifier}:{slot}"}
                if slot == 1:
                    route = tape.extra
                    expected_output["extra_verification"] = route
            expected_call(f"{action}_{NODE[slot]}", inputs, expected_output, PRICES[action])
            if report:
                inputs = {"credential": expected_output["credential"]}
                if slot == 0:
                    for check in CHECKS[:run.cell["checks"]]:
                        checked = {"credential": inputs["credential"] + ":" + check}
                        expected_call(check, inputs, checked, F(0))
                        inputs = checked
        if (report, route) != (row["report"], row["route"]):
            return ["incorrect observation"]
        state = advance(state, action, report, route)
    effect = {"goal": run.task["goal"], "credential": inputs["credential"]} if state.terminal == "complete" else None
    issues = []
    if (events, effect, state) != (run.events, run.effect, run.state):
        issues.append("dependency or terminal effect mismatch")
    if (bill, probes) != (run.ledger, run.diagnostics):
        issues.append("independent ledger mismatch")
    if state.terminal == "blocked_stop" and (tape.a[state.slot] or tape.b[state.slot]):
        issues.append("blocked stop with viable route")
    return issues
