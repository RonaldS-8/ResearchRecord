"""Two synthetic task families sharing a commit API and recovery contract."""
from extensions.toolmaze_diagnostic_mvp.environment import json_copy

INITIAL_ERROR = "Operation unavailable"
REPORTS = ("Reconnect suggested", "Alternate route suggested")
FALLBACK = "reserve_fallback"

# Each workflow starts from different user data and writes a different effect.
TASKS = {
    "parcel": {"goal": "dispatch parcel", "input": {"parcel": "P17", "postal_code": " 238801 "}},
    "invoice": {"goal": "register invoice", "input": {"invoice": "I29", "quantity": 3, "unit_price": 120}},
}


def preparation(task):
    if task["goal"] == "dispatch parcel":
        user = task["input"]
        return [("normalize_address", {"postal_code": user["postal_code"]},
                 {"postal_code": user["postal_code"].strip()})]
    user = task["input"]
    subtotal = user["quantity"] * user["unit_price"]
    return [
        ("calculate_subtotal", {"quantity": user["quantity"], "unit_price": user["unit_price"]},
         {"subtotal": subtotal}),
        ("validate_invoice", {"invoice": user["invoice"], "subtotal": subtotal},
         {"approved_total": subtotal}),
    ]


class Session:
    def __init__(self, family, context, fault):
        self._task = TASKS[family]
        self._context = context
        self._first, self._second, self._report = fault
        self._events, self._decisions, self._ledger = [], [], []
        self._effect = None
        self._done = False
        for tool, args, output in preparation(self._task):
            self._record(tool, args, output)
        user = self._task["input"]
        final = self._events[-1]["output"]
        if family == "parcel":
            self._payload = {"parcel": user["parcel"], "postal_code": final["postal_code"]}
        else:
            self._payload = {"invoice": user["invoice"], "amount": final["approved_total"]}
        self._record("commit_primary", self._payload, {"error": INITIAL_ERROR})
        self._sunk = len(self._events)

    def _record(self, tool, args, output):
        self._events.append({"call_id": len(self._events), "tool": tool,
                             "arguments": args, "output": output})

    def _commit(self, tool, args):
        self._effect = {"goal": self._task["goal"], "payload": dict(self._payload)}
        self._record(tool, args, {"committed": self._effect})
        self._done = True

    def view(self):
        retries = sum(d["action"] == "retry" for d in self._decisions)
        actions = [] if self._done else ["switch", "stop"]
        if not self._done and retries < 2:
            actions.append("retry")
        return json_copy({"task": self._task, "context": self._context, "actions": actions,
                          "history": self._events, "decisions": self._decisions,
                          "prices": {"retry": 1, "switch": 2}, "done": self._done,
                          "remaining_decisions": 0 if self._done else 3 - retries})

    def act(self, action):
        if action not in self.view()["actions"]:
            raise ValueError("Action unavailable")
        start = len(self._events)
        decision = {"action": action}
        if action == "retry":
            first_attempt = not self._decisions
            recovered = self._first if first_attempt else self._second
            decision["recovered"] = recovered
            if recovered:
                self._commit("commit_primary", self._payload)
            else:
                error = self._report if first_attempt else INITIAL_ERROR
                self._record("commit_primary", self._payload, {"error": error})
        elif action == "switch":
            identity = self._payload.get("parcel", self._payload.get("invoice"))
            reservation = "fallback:" + identity
            self._record(FALLBACK, self._payload, {"reservation": reservation})
            self._commit("commit_fallback", {"reservation": self._events[-1]["output"]["reservation"]})
        else:
            self._done = True
        self._decisions.append(decision)
        calls = list(range(start, len(self._events)))
        self._ledger.append({"action": action, "calls": calls, "tool_fee": len(calls)})
        return self.view()

    def audit(self):
        success, issues = verify(self._task, self._events, self._decisions, self._ledger,
                                 self._effect, (self._first, self._second, self._report))
        return {"events": self._events, "decisions": self._decisions, "ledger": self._ledger,
                "effect": self._effect, "score": {"legal_success": success, "issues": issues},
                "recovery_calls": len(self._events) - self._sunk,
                "tool_fee": sum(row["tool_fee"] for row in self._ledger), "diagnostic_fee": 0}


def verify(task, events, decisions, ledger, effect, fault):
    """Independently derive valid dependencies, effects and bill from the record."""
    user = task["input"]
    if "parcel" in user:
        address = user["postal_code"].strip()
        expected = [("normalize_address", {"postal_code": user["postal_code"]}, {"postal_code": address})]
        payload = {"parcel": user["parcel"], "postal_code": address}
        identity = user["parcel"]
    else:
        amount = user["quantity"] * user["unit_price"]
        expected = [("calculate_subtotal", {k: user[k] for k in ("quantity", "unit_price")},
                     {"subtotal": amount}),
                    ("validate_invoice", {"invoice": user["invoice"], "subtotal": amount},
                     {"approved_total": amount})]
        payload = {"invoice": user["invoice"], "amount": amount}
        identity = user["invoice"]
    expected.append(("commit_primary", payload, {"error": INITIAL_ERROR}))
    bill = []
    final = None
    for index, decision in enumerate(decisions):
        if final is not None or index >= 3:
            return False, ["action after completion or budget"]
        action = decision["action"]
        start = len(expected)
        if action == "retry" and index < 2:
            recovered = fault[index]
            if decision.get("recovered") != recovered:
                return False, ["retry observation"]
            if recovered:
                final = {"goal": task["goal"], "payload": payload}
            output = {"committed": final} if recovered else {"error": fault[2] if index == 0 else INITIAL_ERROR}
            expected.append(("commit_primary", payload, output))
        elif action == "switch":
            token = "fallback:" + identity
            final = {"goal": task["goal"], "payload": payload}
            expected.extend([(FALLBACK, payload, {"reservation": token}),
                             ("commit_fallback", {"reservation": token}, {"committed": final})])
        elif action != "stop" or index != len(decisions) - 1:
            return False, ["invalid action"]
        calls = list(range(start, len(expected)))
        bill.append({"action": action, "calls": calls, "tool_fee": len(calls)})
    trace = [{"call_id": i, "tool": tool, "arguments": args, "output": output}
             for i, (tool, args, output) in enumerate(expected)]
    issues = []
    if trace != events or final != effect:
        issues.append("workflow, binding, return or final effect")
    if ledger != bill:
        issues.append("recovery ledger mismatch")
    return final is not None and not issues, issues
