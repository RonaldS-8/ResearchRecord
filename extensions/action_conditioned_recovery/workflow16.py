"""Dynamic invoice workflow with an independently checked recovery ledger."""
from fractions import Fraction as F
from typing import NamedTuple

from extensions.toolmaze_diagnostic_mvp.environment import json_copy

from .workflow15 import CHECKS, INITIAL_ERROR, TASKS, initial_events

PRICES = {"A": F(9, 8), "B": F(2)}
ORDER = ("B", "A", "diagnose", "stop")


class Progress(NamedTuple):
    slot: int
    tried: tuple
    budget: int
    probe: bool
    terminal: str = ""


class World(NamedTuple):
    a: tuple
    b: tuple
    extra: bool
    cue: bool | None
    signal: bool


def actions(state):
    if state.terminal:
        return ()
    return tuple(action for action in ORDER if
                 (action == "stop" or
                  action == "diagnose" and state.probe or
                  action in PRICES and action not in state.tried and state.budget > 0))


def observation(world, state, action):
    if action == "diagnose":
        return world.signal, None
    if action == "stop":
        return None, None
    success = (world.a if action == "A" else world.b)[state.slot]
    return success, world.extra if success and state.slot == 0 else None


def advance(state, action, observed):
    if action == "stop":
        terminal = "blocked_stop" if len(state.tried) == 2 else "premature_stop"
        return state._replace(terminal=terminal)
    if action == "diagnose":
        return state._replace(probe=False)
    success, extra = observed
    left = state.budget - 1
    if success and (state.slot == 1 or not extra):
        return Progress(state.slot, (), left, False, "complete")
    slot, tried = (1, ()) if success else (state.slot, (*state.tried, action))
    return Progress(slot, tried, left, False, "exhausted" if not left else "")


class Workflow:
    def __init__(self, cell, world, instance="I29"):
        self.cell, self._world, self._instance = cell, world, instance
        self.state = Progress(0, (), cell["budget"], True)
        self.prefix = initial_events()
        for event in self.prefix:
            if "invoice" in event["arguments"]:
                event["arguments"]["invoice"] = instance
        if world.cue is not None:
            self.prefix[-2]["output"]["quality"] = world.cue
        self.events, self.decisions, self.ledger, self.diagnostics = [], [], [], []
        self.credential = None
        self.effect = None

    def view(self):
        return json_copy({"task": {**TASKS["invoice"], "input": {
            **TASKS["invoice"]["input"], "invoice": self.prefix[-1]["arguments"]["invoice"]}},
            "history": self.prefix + self.events, "decisions": self.decisions,
            "slot": self.state.slot, "tried": list(self.state.tried), "budget": self.state.budget,
            "actions": list(actions(self.state)), "done": bool(self.state.terminal),
            "prices": {**{k: str(v) for k, v in PRICES.items()}, "diagnose": self.cell["fee"]},
            "routing_probability": self.cell["q"],
            "diagnostic_accuracy": self.cell["accuracy"]})

    def _call(self, tool, args, output, fee):
        self.ledger.append({"index": len(self.events), "tool": tool, "fee": fee})
        self.events.append({"tool": tool, "arguments": args, "output": output})

    def act(self, action):
        state = self.state
        if action not in actions(state):
            raise ValueError("Unavailable recovery action")
        report, extra = observation(self._world, state, action)
        after = advance(state, action, (report, extra))
        if action == "diagnose":
            self.diagnostics.append({"report": report, "fee": F(self.cell["fee"])})
        elif action in PRICES:
            args = (self.prefix[-1]["arguments"] if state.slot == 0 else
                    {"credential": self.credential})
            tool = f"{action}_{'acquire' if state.slot == 0 else 'verify'}"
            output = {"error": INITIAL_ERROR}
            if report and state.slot == 0:
                self.credential = f"{args['invoice']}:{args['amount']}"
                output = {"credential": self.credential, "extra_verification": extra}
            elif report:
                output = {"verified": self.credential}
            self._call(tool, args, output, PRICES[action])
            if report and state.slot == 0:
                for check in CHECKS[:self.cell["checks"]]:
                    previous = self.credential
                    self.credential = f"{previous}:{check}"
                    self._call(check, {"credential": previous}, {"credential": self.credential}, F(0))
            if after.terminal == "complete":
                self.effect = {"registered": self.credential, "verified": bool(state.slot)}
        self.decisions.append({"slot": state.slot, "action": action, "report": report, "extra": extra})
        self.state = after
        return self.view()

    def audit(self):
        issues = verify(self)
        return {"score": {"legal_success": not issues and self.state.terminal == "complete",
                          "issues": issues}, "termination": self.state.terminal,
                "effect": self.effect, "events": self.events, "decisions": self.decisions,
                "ledger": self.ledger, "diagnostic_ledger": self.diagnostics,
                "tool_fee": sum(row["fee"] for row in self.ledger),
                "diagnostic_fee": sum(row["fee"] for row in self.diagnostics),
                "recovery_calls": len(self.events)}


def verify(run):
    """Reconstruct the required calls and effect from legal arguments and task outcomes."""
    world, cell = run._world, run.cell
    state = Progress(0, (), cell["budget"], True)
    prefix = initial_events()
    for event in prefix:
        if "invoice" in event["arguments"]:
            event["arguments"]["invoice"] = run._instance
    if world.cue is not None:
        prefix[-2]["output"]["quality"] = world.cue
    if prefix != run.prefix:
        return ["invalid initial provenance"]
    expected, bill, probes = [], [], []
    credential, effect = None, None

    def call(tool, args, output, fee):
        bill.append({"index": len(expected), "tool": tool, "fee": fee})
        expected.append({"tool": tool, "arguments": args, "output": output})

    for d in run.decisions:
        slot, action, report, extra = (d[key] for key in ("slot", "action", "report", "extra"))
        if slot != state.slot or action not in actions(state) or (report, extra) != observation(world, state, action):
            return ["illegal action or observation"]
        if action == "diagnose":
            probes.append({"report": report, "fee": F(cell["fee"])})
        if action in PRICES:
            if slot == 0:
                args = prefix[-1]["arguments"]
                token = f"{args['invoice']}:{args['amount']}"
                result = {"credential": token, "extra_verification": extra}
                call(f"{action}_acquire", args, result if report else {"error": INITIAL_ERROR}, PRICES[action])
                if report:
                    credential = token
                    for check in CHECKS[:cell["checks"]]:
                        next_token = f"{credential}:{check}"
                        call(check, {"credential": credential}, {"credential": next_token}, F(0))
                        credential = next_token
            else:
                call(f"{action}_verify", {"credential": credential},
                     {"verified": credential} if report else {"error": INITIAL_ERROR}, PRICES[action])
        state = advance(state, action, (report, extra))
        if state.terminal == "complete":
            effect = {"registered": credential, "verified": bool(slot)}
    issues = []
    if run.events != expected or run.effect != effect or run.state != state:
        issues.append("dependency, terminal effect or status mismatch")
    if run.ledger != bill or run.diagnostics != probes:
        issues.append("independent ledger mismatch")
    if state.terminal == "blocked_stop" and (world.a[state.slot] or world.b[state.slot]):
        issues.append("blocked stop with reachable route")
    if state.terminal == "exhausted" and state.budget != 0:
        issues.append("invalid budget exhaustion")
    return issues
