"""Gate 13 workflow simulation and independent strict trace validation."""
from extensions.toolmaze_diagnostic_mvp.environment import json_copy

TASKS = {
    "parcel": ("dispatch a parcel", "parcel", "P17", "postal_code", " 238801 "),
    "invoice": ("register an invoice", "invoice", "I29", "amount", 360),
    "publish": ("publish the requested artifact version", "artifact", "build-17", "version", " v3 "),
    "appointment": ("register exactly one appointment", "request_key", "A29", "slot", " 09:00 "),
}
INTERFACES = {
    "parcel": ("dispatch", "dispatch_alternate", "renew_dispatch", "find_dispatch"),
    "invoice": ("register_invoice", "post_invoice_alternate", "renew_invoice", "find_invoice"),
    "publish": ("release_artifact", "mirror_release", "renew_release_permit", "lookup_release"),
    "appointment": ("reserve_slot", "reserve_partner_slot", "renew_booking", "lookup_reservation"),
}
DESCRIPTIONS = {
    "retry": "Repeat the original write using the currently prepared input. May duplicate an unconfirmed write.",
    "switch": "Write via the independent alternate interface. Does not check for an existing write.",
    "refresh": "Refresh the authorization required by the original write and return a new usable permit.",
    "verify": "Read the authoritative receipt by request identity. Does not issue another write.",
    "stop": "End recovery without further calls.",
}
HINTS = {
    "parcel": ("Dispatch lease may be stale", "Reply was lost after dispatch submission"),
    "invoice": ("Invoice authorization cache may be expired", "Reply was lost after posting the invoice"),
    "publish": ("Release permit may have expired", "Publish response ended after submission"),
    "appointment": ("Booking lease may be stale", "Connection closed after the reservation was submitted"),
}
NEUTRAL = "Operation unavailable"


def facts(view):
    """Checked representation derived from the public error and tool descriptions."""
    error = view["history"][-1]["output"]["error"]
    descriptions = {description: role for role, description in DESCRIPTIONS.items()}
    return {"clue": "none" if error == NEUTRAL else "hint",
            "roles": {a["id"]: descriptions[a["description"]] for a in view["actions"]}}


class Session:
    def __init__(self, family, mode, clue, price, bad):
        goal, id_field, identity, key, value = TASKS[family]
        self.task = {"goal": goal, "input": {id_field: identity, key: value}}
        prepared = value.strip() if isinstance(value, str) else value
        self.payload = {id_field: identity, key: prepared}
        primary, fallback, refresh, verify = INTERFACES[family]
        self.catalog = {"retry": primary, "switch": fallback,
                        mode: refresh if mode == "refresh" else verify, "stop": "stop"}
        self.prices = {"retry": 1, "switch": 4, mode: price, "stop": 0}
        self.mode, self.bad = mode, bad
        self.receipts = [dict(self.payload)] if mode == "verify" and bad else []
        self.initial = [
            {"tool": "prepare_" + id_field, "arguments": self.task["input"], "output": self.payload},
            {"tool": primary, "arguments": self.payload, "output": {"error":
                HINTS[family][mode == "verify"] if clue == "hint" else NEUTRAL}},
        ]
        self.events, self.ledger, self.roles = [], [], []
        self.permit, self.confirmed = False, False

    def view(self):
        return json_copy({
            "task": self.task, "history": self.initial + self.events,
            "actions": [{"id": tool, "description": DESCRIPTIONS[role], "price": self.prices[role]}
                        for role, tool in self.catalog.items()],
            "remaining_decisions": 2 - len(self.roles),
        })

    def step(self, role):
        if role not in self.catalog or self.confirmed or len(self.roles) >= 2 or "stop" in self.roles:
            raise ValueError("Unavailable recovery action")
        self.roles.append(role)
        if role == "stop":
            return
        if role == "refresh":
            self.permit = True
            args, output = self.payload, {"permit": "renewed"}
        elif role == "verify":
            args = {next(iter(self.payload)): next(iter(self.payload.values()))}
            self.confirmed = bool(self.receipts)
            output = {"receipt": self.receipts[0] if self.confirmed else None}
        else:
            args = self.payload | ({"permit": "renewed"} if role == "retry" and self.permit else {})
            if role == "retry" and self.mode == "refresh" and self.bad and not self.permit:
                output = {"error": "Authorization rejected"}
            else:
                self.receipts.append(dict(self.payload))
                self.confirmed = True
                output = {"receipt": self.payload}
        self.events.append({"tool": self.catalog[role], "arguments": args, "output": output})
        self.ledger.append({"index": len(self.events) - 1, "tool": self.catalog[role],
                            "fee": self.prices[role]})

    def finish(self, role):
        self.step(role)
        if not self.confirmed and role != "stop":
            self.step("switch" if role == "retry" else "retry")
        return self.audit()

    def audit(self):
        # Derive the expected effect and charges independently from recorded public calls.
        user = self.task["input"]
        expected = {k: v.strip() if isinstance(v, str) else v for k, v in user.items()}
        expected_receipts = int(self.mode == "verify" and self.bad)
        authorized = self.mode != "refresh" or not self.bad
        confirmed = False
        issues = []
        tools = {tool: role for role, tool in self.catalog.items()}
        expected_bill = []
        for i, event in enumerate(self.events):
            role = tools[event["tool"]]
            args, result = event["arguments"], event["output"]
            expected_bill.append({"index": i, "tool": event["tool"], "fee": self.prices[role]})
            if role == "refresh":
                valid = args == expected and result == {"permit": "renewed"}
                authorized = True
            elif role == "verify":
                key = next(iter(expected))
                valid = args == {key: expected[key]} and result == {
                    "receipt": expected if expected_receipts else None}
                confirmed = bool(expected_receipts)
            else:
                allowed = role == "switch" or authorized
                required = expected | ({"permit": "renewed"} if role == "retry" and i and
                                       tools[self.events[i - 1]["tool"]] == "refresh" else {})
                valid = args == required and result == (
                    {"receipt": expected} if allowed else {"error": "Authorization rejected"})
                if allowed:
                    expected_receipts += 1
                    confirmed = True
            if not valid:
                issues.append("binding or tool response mismatch")
        if self.receipts != [expected] * expected_receipts:
            issues.append("effect mismatch")
        if expected_bill != self.ledger:
            issues.append("ledger mismatch")
        if len(self.events) > 2 or len(self.roles) > 2:
            issues.append("budget exceeded")
        return {"legal_success": not issues and confirmed and expected_receipts == 1,
                "issues": issues, "duplicates": max(expected_receipts - 1, 0),
                "tool_fee": sum(row["fee"] for row in self.ledger if tools[row["tool"]] != "verify"),
                "diagnostic_fee": sum(row["fee"] for row in self.ledger if tools[row["tool"]] == "verify"),
                "recovery_calls": len(self.events), "roles": self.roles, "events": self.events,
                "ledger": self.ledger, "receipts": self.receipts}
