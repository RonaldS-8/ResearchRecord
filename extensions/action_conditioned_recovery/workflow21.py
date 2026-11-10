"""Receipt-dependent recovery with a public action menu and separate ledgers."""

from fractions import Fraction as F
from hashlib import sha256
import json
from typing import NamedTuple

from extensions.toolmaze_diagnostic_mvp.environment import json_copy

from .workflow17 import INITIAL_ERROR, prefix, task

ACQUIRE = ("A", "B", "C")
PRICES = dict(A=F("0.40"), B=F("1.20"), C=F("2.00"),
              verify=F("2.00"), register_native=F("0.40"), register_external=F("0.40"))
DIAGNOSTIC_FEE = F("0.05")
REGISTER = {"native": "register_native", "external": "register_external", "short": "verify"}


class Progress(NamedTuple):
    budget: int
    phase: str = "acquire"
    failed: tuple = ()
    probe: bool = True
    terminal: str = ""


class Observation(NamedTuple):
    action: str
    success: bool
    credential: str = ""


class World(NamedTuple):
    available: tuple
    short: bool
    signal: bool


class Preparation(NamedTuple):
    scope: str
    quality: bool
    accuracy: F


def tool_name(action):
    return action + "_acquire" if action in ACQUIRE else action


def actions(state):
    if state.terminal:
        return ()
    if state.phase != "acquire":
        return REGISTER[state.phase], "stop"
    candidates = tuple(action for action in ACQUIRE if action not in state.failed)
    return (*candidates, "diagnose", "stop") if candidates and state.probe else (*candidates, "stop")


def advance(state, observation):
    action, success, credential = observation
    if action == "stop":
        return state._replace(terminal="blocked_stop" if len(state.failed) == 3 else "premature_stop")
    if action == "diagnose":
        return state._replace(probe=False)
    budget = state.budget - 1
    if action.startswith("register_"):
        return state._replace(budget=budget, terminal="complete")
    if action == "verify":
        return state._replace(budget=budget, phase="native")
    if success:
        needed = 2 if credential == "short" else 1
        return state._replace(budget=budget, phase=credential, probe=False,
                              terminal="exhausted" if budget < needed else "")
    failed = (*state.failed, action)
    return state._replace(budget=budget, failed=failed,
                          terminal="exhausted" if len(failed) < 3 and budget < 2 else "")


def event_occurs(identity, event, probability):
    key = json.dumps((*identity, event), separators=(",", ":")).encode()
    return F(int.from_bytes(sha256(key).digest()[:8], "big"), 2**64) < probability


def sample(law, identity):
    def flip(event, probability):
        return event_occurs(identity, event, probability)

    good = flip("gateway:A", F(1, 2))
    b_good = good if flip("gateway:shared", law.shared) else flip("gateway:B", F(1, 2))
    return World((flip("acquire:A", law.a_good if good else law.a_bad),
                  flip("acquire:B", law.b_good if b_good else law.b_bad),
                  flip("acquire:C", law.c)),
                 flip("credential:B", law.short), good == flip("probe:correct", law.accuracy))


def binding(view, action):
    if action not in view["actions"]:
        raise ValueError("Unavailable recovery action")
    if action not in PRICES:
        return {"source": None, "arguments": {}}
    for index in reversed(range(len(view["history"]))):
        event = view["history"][index]
        output = event["output"]
        if event["tool"] == "prepare":
            return {"source": index, "arguments": output}
        if "credential" in output:
            return {"source": index, "arguments": {"credential": output["credential"]}}
    raise ValueError("Missing source receipt")


class Workflow:
    def __init__(self, family, world, accuracy, budget=5, *, preparation=None, probe=True):
        self.task = task(family, "request")
        self.preparation = preparation
        if preparation is not None:
            self.task["input"]["scope"] = preparation.scope
        self.prefix = self._prefix()
        self.initial = self.state = Progress(budget, probe=probe)
        self.accuracy, self._world = accuracy, world
        self.observations, self.events, self.ledger, self.diagnostics = [], [], [], []
        self.effect = None

    def _prefix(self):
        events = prefix(self.task, (), 0)
        if self.preparation is not None:
            events[0]["receipt_metadata"] = {"quality": self.preparation.quality,
                                             "accuracy": str(self.preparation.accuracy)}
        return events

    def view(self):
        history = tuple(self.observations)
        if self.preparation is not None:
            history = (Observation("prepare", self.preparation.quality), *history)
        return {"task": json_copy(self.task), "history": json_copy(self.prefix + self.events),
                "observations": history, "progress": self.state,
                "diagnostic_accuracy": str(self.accuracy), "actions": actions(self.state),
                "quotes": {action: str(PRICES.get(action, DIAGNOSTIC_FEE if action == "diagnose" else 0))
                           for action in actions(self.state)}}

    def act(self, action, bound):
        if bound != binding(self.view(), action):
            raise ValueError("Arguments or source do not match the current receipt")
        observed = Observation(action, False)
        if action in ACQUIRE:
            works = self._world.available[ACQUIRE.index(action)]
            kind = "external" if action == "C" else "short" if action == "B" and self._world.short else "native"
            observed = Observation(action, works, kind if works else "")
            output = {"credential": "request:" + kind, "kind": kind} if works else {"error": INITIAL_ERROR}
        elif action == "diagnose":
            observed = Observation(action, self._world.signal)
            self.diagnostics.append({"turn": len(self.observations), "signal": observed.success,
                                     "fee": DIAGNOSTIC_FEE})
        elif action == "verify":
            observed = Observation(action, True, "native")
            output = {"credential": "request:native", "kind": "native"}
        elif action in PRICES:
            observed = Observation(action, True)
            self.effect = {"goal": self.task["goal"], **bound["arguments"]}
            if self.preparation is not None:
                self.effect["scope"] = self.preparation.scope
            output = {"effect": self.effect}
        if action in PRICES:
            self.ledger.append({"index": len(self.events), "tool": tool_name(action), "fee": PRICES[action]})
            self.events.append({"tool": tool_name(action), **bound, "output": output})
        self.observations.append(observed)
        self.state = advance(self.state, observed)
        return self.view()

    def audit(self):
        """Recheck the receipt chain, final effect and billing independently of advance."""
        issues = []
        if self.prefix != self._prefix():
            issues.append("incorrect preparation or fault checkpoint")
        source = 0
        arguments = self.prefix[0]["output"]
        required = ""
        seen = set()
        entries, diagnostics = [], []
        effect = None
        ended = ""
        for turn, (action, success, credential) in enumerate(self.observations):
            if ended:
                issues.append("decision after termination")
                break
            if action == "diagnose":
                if (not self.initial.probe or diagnostics or required or len(seen) == 3
                        or success != self._world.signal or credential):
                    issues.append("invalid diagnostic evidence")
                diagnostics.append({"turn": turn, "signal": success, "fee": DIAGNOSTIC_FEE})
                continue
            if action == "stop":
                ended = "blocked_stop" if len(seen) == 3 and not required else "premature_stop"
                continue
            if action in ACQUIRE:
                works = self._world.available[ACQUIRE.index(action)]
                kind = "external" if action == "C" else "short" if action == "B" and self._world.short else "native"
                if required or action in seen or (success, credential) != (works, kind if works else ""):
                    issues.append("invalid acquisition")
                seen.add(action)
                output = {"credential": "request:" + kind, "kind": kind} if works else {"error": INITIAL_ERROR}
                required = REGISTER[kind] if works else ""
            elif action == required and action == "verify":
                if not success or credential != "native":
                    issues.append("invalid verification result")
                output = {"credential": "request:native", "kind": "native"}
                required = "register_native"
            elif action == required and action.startswith("register_"):
                if not success or credential:
                    issues.append("invalid registration result")
                effect = {"goal": self.task["goal"], **arguments}
                if "scope" in self.task["input"]:
                    effect["scope"] = self.task["input"]["scope"]
                output = {"effect": effect}
                ended = "complete"
            else:
                issues.append("incorrect credential or missing verification")
                break
            index = len(entries)
            entries.append({"tool": tool_name(action), "source": source, "arguments": arguments, "output": output})
            if "credential" in output:
                source, arguments = len(self.prefix) + index, {"credential": output["credential"]}
            left = self.initial.budget - len(entries)
            if left < 0:
                issues.append("execution exceeds budget")
            if not ended and not (len(seen) == 3 and not required):
                minimum = 1 if required.startswith("register_") else 2
                if left < minimum:
                    ended = "exhausted"
        bill = [{"index": i, "tool": event["tool"],
                 "fee": PRICES[event["tool"].removesuffix("_acquire")]} for i, event in enumerate(entries)]
        if entries != self.events or effect != self.effect or ended != self.state.terminal:
            issues.append("receipt chain or terminal mismatch")
        if (bill, diagnostics) != (self.ledger, self.diagnostics):
            issues.append("independent ledger mismatch")
        return {"score": {"legal_success": ended == "complete" and not issues, "issues": issues},
                "termination": ended, "effect": effect, "prefix": self.prefix,
                "events": self.events, "observations": self.observations,
                "ledger": self.ledger, "diagnostic_ledger": self.diagnostics,
                "tool_fee": sum(item["fee"] for item in self.ledger),
                "diagnostic_fee": sum(item["fee"] for item in self.diagnostics)}


def execute_action(workflow, action):
    return workflow.act(action, binding(workflow.view(), action))
