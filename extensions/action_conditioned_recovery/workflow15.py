"""Two dependent invoice recovery slots with an independent trace verifier."""
from fractions import Fraction as F

from extensions.toolmaze_diagnostic_mvp.environment import json_copy

from .multistep import INITIAL_ERROR, TASKS, preparation

PRICE_A = F(5, 4)
PRICE_B = F(2)
BACKUPS = ("B", "B2")
CHECKS = ("check_credential_scope", "normalize_credential")
TOOL_LIMIT = 6
DECISION_LIMIT = 5


def initial_events():
    events = [{"tool": tool, "arguments": args, "output": output}
              for tool, args, output in preparation(TASKS["invoice"])]
    user = TASKS["invoice"]["input"]
    events.append({"tool": "A_acquire", "arguments": {
        "invoice": user["invoice"], "amount": events[-1]["output"]["approved_total"]},
        "output": {"error": INITIAL_ERROR}})
    return events


class Workflow:
    def __init__(self, cell, health, report):
        self.cell = cell
        self._health = health
        self._report = report
        self.prefix = initial_events()
        self.events, self.decisions, self.ledger, self.diagnostics = [], [], [], []
        self.slot = 0
        self.tried = False
        self.done = False
        self.credential = None
        self.effect = None

    def view(self):
        actions = [] if self.done else [*BACKUPS[:self.cell["backups"]], "stop"]
        if not self.done and not self.tried:
            actions.append("A")
        if not self.decisions:
            actions.append("diagnose")
        return json_copy({
            "task": TASKS["invoice"],
            "slot": self.slot,
            "history": self.prefix + self.events,
            "decisions": self.decisions,
            "actions": actions,
            "prices": {"A": str(PRICE_A), "B": str(PRICE_B), "diagnose": self.cell["fee"]},
            "calibration": {"shared_provider": self.cell["shared"], "accuracy": self.cell["accuracy"]},
            "required_checks": list(CHECKS[:self.cell["checks"]]),
            "remaining_decisions": DECISION_LIMIT - len(self.decisions),
            "remaining_calls": TOOL_LIMIT - len(self.events),
            "done": self.done,
        })

    def _call(self, tool, arguments, output, fee):
        if len(self.events) >= TOOL_LIMIT:
            raise ValueError("Tool budget exhausted")
        self.ledger.append({"index": len(self.events), "tool": tool, "fee": fee})
        self.events.append({"tool": tool, "arguments": arguments, "output": output})

    def act(self, action):
        if action not in self.view()["actions"] or len(self.decisions) >= DECISION_LIMIT:
            raise ValueError("Action unavailable")
        decision = {"slot": self.slot, "action": action, "report": None}
        if action == "diagnose":
            decision["report"] = self._report
            self.diagnostics.append({"report": self._report, "fee": F(self.cell["fee"])})
        elif action == "stop":
            self.done = True
        else:
            recovered = action != "A" or self._health[self.slot]
            decision["report"] = recovered
            suffix = "acquire" if self.slot == 0 else "register"
            args = (self.prefix[-1]["arguments"] if self.slot == 0 else
                    {"credential": self.credential})
            if not recovered:
                self.tried = True
                output = {"error": INITIAL_ERROR}
            elif self.slot == 0:
                self.credential = f"{args['invoice']}:{args['amount']}"
                output = {"credential": self.credential}
            else:
                self.effect = {"registered": args["credential"]}
                output = self.effect
            self._call(f"{action}_{suffix}", args, output, PRICE_A if action == "A" else PRICE_B)
            if recovered and self.slot == 0:
                for tool in CHECKS[:self.cell["checks"]]:
                    source = self.credential
                    self.credential = f"{source}:{tool}"
                    self._call(tool, {"credential": source}, {"credential": self.credential}, F(0))
                self.slot = 1
                self.tried = False
            elif recovered:
                self.done = True
        self.decisions.append(decision)
        return self.view()

    def audit(self):
        legal, issues = verify(self)
        return {
            "score": {"legal_success": legal, "issues": issues},
            "events": self.events, "decisions": self.decisions, "effect": self.effect,
            "ledger": self.ledger, "diagnostic_ledger": self.diagnostics,
            "tool_fee": sum(row["fee"] for row in self.ledger),
            "diagnostic_fee": sum(row["fee"] for row in self.diagnostics),
            "recovery_calls": len(self.events),
        }


def verify(workflow):
    """Check exact call sequence, legal inputs, public reports, terminal effect and charges."""
    if workflow.prefix != initial_events():
        return False, ["initial prefix mismatch"]
    config = workflow.cell
    expected, bill, diagnostics = [], [], []
    effect, credential = None, None
    slot, tried = 0, False

    def call(tool, arguments, output, fee):
        bill.append({"index": len(expected), "tool": tool, "fee": fee})
        expected.append({"tool": tool, "arguments": arguments, "output": output})

    for i, row in enumerate(workflow.decisions):
        action, report = row["action"], row["report"]
        if effect is not None or row["slot"] != slot or i >= DECISION_LIMIT:
            return False, ["invalid slot or decision after completion"]
        if action == "diagnose" and i == 0 and report == workflow._report:
            diagnostics.append({"report": report, "fee": F(config["fee"])})
            continue
        if action == "stop" and i == len(workflow.decisions) - 1 and report is None:
            break
        if action not in ("A", *BACKUPS[:config["backups"]]) or (tried and action == "A"):
            return False, ["unavailable route"]
        success = action != "A" or workflow._health[slot]
        if report is not success:
            return False, ["unverified recovery observation"]
        args = workflow.prefix[-1]["arguments"] if slot == 0 else {"credential": credential}
        tool = f"{action}_{'acquire' if slot == 0 else 'register'}"
        fee = PRICE_A if action == "A" else PRICE_B
        if not success:
            call(tool, args, {"error": INITIAL_ERROR}, fee)
            tried = True
        elif slot == 0:
            credential = f"{args['invoice']}:{args['amount']}"
            call(tool, args, {"credential": credential}, fee)
            for check in CHECKS[:config["checks"]]:
                source = credential
                credential += f":{check}"
                call(check, {"credential": source}, {"credential": credential}, F(0))
            slot, tried = 1, False
        else:
            effect = {"registered": credential}
            call(tool, args, effect, fee)
    issues = []
    if expected != workflow.events or effect != workflow.effect or len(expected) > TOOL_LIMIT:
        issues.append("call sequence, credential or terminal effect mismatch")
    if bill != workflow.ledger or diagnostics != workflow.diagnostics:
        issues.append("independent ledger mismatch")
    return effect is not None and not issues, issues
