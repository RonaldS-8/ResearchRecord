"""ToolMaze-Recovery execution, private state, and outcome-based acceptance."""

from collections import Counter
from copy import deepcopy
from pathlib import Path
from secrets import token_hex
from types import SimpleNamespace

from extensions.toolmaze_agent_recovery.session import Session, TIMEOUT, UNAVAILABLE
from toolmaze.core.executor import ToolExecutor

from .tasks import DEVELOPMENT, DIAGNOSTIC, READS, RESERVATION_LOOKUP, RESOURCE_FIELDS, STOCK_WRITE_TOOLS, TOOLS

WRITE_FAULTS = ("write_not_committed", "write_response_lost")
FAULTS = ("clean", "transient", "persistent", "correlated", "blocked", *WRITE_FAULTS)
WRITE_TIMEOUT = {"error": "The reservation request timed out. Its outcome is unknown."}
INVALID = "invalid_argument"


class ContractExecutor(ToolExecutor):
    def __init__(self, definitions, resource, request_ref):
        # Fixtures register in memory. ToolMaze still validates, dispatches and records calls.
        directory = str(Path(__file__).with_name("plugins"))
        super().__init__(directory, directory, SimpleNamespace(get_tool_by_name=definitions.get))
        self.resource = resource
        self.request_ref = request_ref

    def _coerce_types(self, tool_name, arguments):
        return arguments

    def _validate(self, tool_name, arguments):
        errors = super()._validate(tool_name, arguments)
        spec = self.loader.get_tool_by_name(tool_name)["paradigms"]["function_call"]["spec"]
        properties = spec["parameters"]["properties"]
        if arguments.keys() - properties.keys():
            errors.append("Undeclared arguments.")
        field = RESOURCE_FIELDS.get(tool_name)
        if field is not None and arguments.get(field) != self.resource:
            errors.append("The resource is outside this task's authorized scope.")
        if "request_ref" in properties and arguments.get("request_ref") != self.request_ref:
            errors.append("The request reference is outside this task's authorized scope.")
        if "quantity" in properties and type(arguments.get("quantity")) is not int:
            errors.append("Quantity must be an integer.")
        return errors


class RecoverySession(Session):
    def __init__(self, task, fault="clean", *, diagnosis_available=True):
        if task not in DEVELOPMENT or fault not in FAULTS:
            raise ValueError("Unknown ToolMaze-Recovery development task or condition")
        self.goal = DEVELOPMENT[task]
        if fault in WRITE_FAULTS and not self.goal.request_ref:
            raise ValueError("Write faults require the request-scoped reservation contract")
        catalog = STOCK_WRITE_TOOLS if self.goal.request_ref else TOOLS[self.goal.family]
        definitions = {tool["name"]: tool for tool in deepcopy(catalog)}
        executor = ContractExecutor(definitions, self.goal.resource, self.goal.request_ref)
        engine = SimpleNamespace(tool_executor=executor, tool_definitions=list(definitions.values()),
                                 task_description=self.goal.query)
        super().__init__(task, fault, case=(engine, None), read_tools=READS[self.goal.family])
        self.diagnosis_available = diagnosis_available
        self.write_timeout_used = False
        self.acquisitions = {}
        self.notes = {}
        self.notices = []
        self.reservations = {}
        self.checks = []
        self.available_units = self.goal.stock
        operations = {
            "publish_case_note": self.publish_note, "send_note_notice": self.send_notice,
            "reserve_stock": self.reserve_stock, "get_reservation_status": self.reservation_status,
            DIAGNOSTIC: self.service_status, RESERVATION_LOOKUP: self.lookup_reservations,
        }
        for tool in definitions:
            def execute(arguments, context, name=tool):
                if name in self.read_tools:
                    return self.acquire(name)
                return operations[name](**arguments)
            self.engine.tool_executor.plugins[tool] = SimpleNamespace(execute=execute)

    def method_contract(self):
        return {"reads": self.read_tools, "diagnostic": DIAGNOSTIC}

    def charge_kind(self, tool):
        return "diagnosis" if tool in (DIAGNOSTIC, RESERVATION_LOOKUP) else "execution"

    def fault_result(self, tool):
        if tool not in self.read_tools:
            return None
        attempts = sum(self.attempts[name] for name in self.read_tools)
        if self.fault == "correlated":
            return TIMEOUT if attempts <= 2 else None
        if self.fault == "blocked":
            return TIMEOUT if attempts == 1 else UNAVAILABLE
        return super().fault_result(tool)

    def service_status(self, resource_id):
        if not self.diagnosis_available:
            return {"error": "The connectivity monitor did not respond."}
        # A shared outage is visible while active. Healthy shared connectivity cannot
        # distinguish a slow provider from an endpoint-specific persistent failure.
        attempts = sum(self.attempts[name] for name in self.read_tools)
        degraded = self.fault == "correlated" and attempts < 2
        return {
            "resource_id": resource_id, "scope": "shared acquisition connectivity",
            "status": "degraded" if degraded else "no shared incident reported",
        }

    def acquire(self, tool):
        goal = self.goal
        reference = token_hex(12)
        self.acquisitions[reference] = {
            "call": len(self.events) + 1, "tool": tool, "resource": goal.resource,
            "summary": goal.summary, "available": self.available_units,
        }
        if tool == "get_case_record":
            return {"case_id": goal.resource, "revision": 4, "summary": goal.summary,
                    "record_ref": reference}
        if tool == "read_case_archive":
            return {"case_file": {"ticket": goal.resource, "revision": 4, "summary": goal.summary},
                    "archive_ref": reference}
        if tool == "get_depot_inventory":
            return {"depot": "D4", "sku": goal.resource, "available_units": self.available_units,
                    "inventory_ref": reference}
        return {"count": {"depot": "D4", "item": goal.resource, "free": self.available_units},
                "count_ticket": reference}

    def publish_note(self, case_id, title, content, evidence_ref):
        source = self.acquisitions.get(evidence_ref)
        if source is None or source["resource"] != case_id or not title.strip() or not content.strip():
            return invalid("A real case evidence reference, title and content are required.")
        note_id = token_hex(12)
        url = f"https://support.company.test/notes/{note_id}"
        note = {"note_id": note_id, "case_id": case_id, "title": title, "content": content,
                "evidence_ref": evidence_ref, "url": url}
        self.notes[note_id] = note
        self.record_effect("publish_case_note", note)
        return {"note_id": note_id, "url": url}

    def send_notice(self, note_id, recipient):
        if note_id not in self.notes or not recipient.strip():
            return invalid("A published note identifier and destination are required.")
        notice = {"note_id": note_id, "recipient": recipient, "url": self.notes[note_id]["url"]}
        self.notices.append(notice)
        self.record_effect("send_note_notice", notice)
        return {"status": "sent", **notice}

    def reserve_stock(self, sku, quantity, evidence_ref, request_ref=None):
        source = self.acquisitions.get(evidence_ref)
        if source is None or source["resource"] != sku or quantity <= 0:
            return invalid("A real stock evidence reference and a positive quantity are required.")
        if quantity > min(source["available"], self.available_units):
            return {"error": "Insufficient available stock for this reservation."}
        loses_response = self.fault in WRITE_FAULTS and not self.write_timeout_used
        if loses_response:
            self.write_timeout_used = True
            if self.fault == "write_not_committed":
                return WRITE_TIMEOUT
        reservation_id = token_hex(12)
        self.available_units -= quantity
        reservation = {"reservation_id": reservation_id, "sku": sku, "depot": "D4",
                       "quantity": quantity, "status": "active", "evidence_ref": evidence_ref}
        if request_ref is not None:
            reservation["request_ref"] = request_ref
        self.reservations[reservation_id] = reservation
        self.record_effect("reserve_stock", reservation)
        return WRITE_TIMEOUT if loses_response else {"reservation_id": reservation_id}

    def lookup_reservations(self, request_ref):
        if not self.diagnosis_available:
            return {"error": "The reservation lookup did not respond."}
        ids = [row["reservation_id"] for row in self.reservations.values()
               if row.get("request_ref") == request_ref]
        return {"request_ref": request_ref, "status": "found" if ids else "not_found", "reservation_ids": ids}

    def reservation_status(self, reservation_id):
        if reservation_id not in self.reservations or not reservation_id_visible(self.events, reservation_id):
            return invalid("A reservation ID from an earlier write receipt or authorized lookup is required.")
        reservation = self.reservations[reservation_id]
        result = {key: reservation[key] for key in ("reservation_id", "depot", "sku", "quantity", "status")}
        self.checks.append({"call": len(self.events) + 1, **result})
        return result

    def record_effect(self, operation, state):
        self.effects.append({"call": len(self.events) + 1, "operation": operation, "state": deepcopy(state)})

    def call(self, tool, arguments):
        result = super().call(tool, arguments)
        if result.get("code") == INVALID:
            self.events[-1]["illegal"] = True
        return result


def invalid(message):
    return {"error": message, "code": INVALID}


def reservation_id_visible(events, reservation_id):
    return any(
        not event["illegal"] and (
            (event["tool"] == "reserve_stock" and event["result"].get("reservation_id") == reservation_id)
            or (event["tool"] == RESERVATION_LOOKUP and reservation_id in event["result"].get("reservation_ids", []))
        )
        for event in events
    )


def has_source(session, effect):
    """Verify the actual causal receipt edge, independently of plugin acceptance."""
    state = effect["state"]
    ref = state["evidence_ref"]
    source = session.acquisitions.get(ref)
    if source is None or source["resource"] != session.goal.resource or source["call"] >= effect["call"]:
        return False
    event = session.events[source["call"] - 1]
    return (event["tool"] == source["tool"] in session.read_tools and not event["illegal"]
            and "error" not in event["result"]
            and ref in event["result"].values()
            and session.events[effect["call"] - 1]["arguments"].get("evidence_ref") == ref)


def completion_issues(session):
    goal = session.goal
    effects = session.effects
    for effect in effects:
        event = session.events[effect["call"] - 1]
        state = effect["state"]
        # A valid commit can be journaled even when its public write response is lost.
        ambiguous_write = event["tool"] == "reserve_stock" and event["result"] == WRITE_TIMEOUT
        if (event["tool"] != effect["operation"] or event["illegal"]
                or ("error" in event["result"] and not ambiguous_write)
                or any(state.get(key) != value for key, value in event["arguments"].items())
                or any(state[key] != value for key, value in event["result"].items() if key in state)):
            return ["Write state does not match the actual call and receipt."]
    if goal.family == "case":
        expected = ["publish_case_note"] + (["send_note_notice"] if goal.recipient else [])
        if len(session.notes) != 1 or len(session.notices) != int(bool(goal.recipient)):
            return ["Expected exactly the requested note and notification effects."]
        if [row["operation"] for row in effects] != expected:
            return ["Unexpected, duplicate or missing note/notification writes."]
        note = next(iter(session.notes.values()))
        if (note["case_id"], note["title"], note["content"]) != (goal.resource, goal.title, goal.summary):
            return ["Note case, title or content differs from the request."]
        if note != effects[0]["state"] or not has_source(session, effects[0]):
            return ["Note lacks a valid source receipt."]
        if goal.recipient:
            notice = {"note_id": note["note_id"], "recipient": goal.recipient, "url": note["url"]}
            if session.notices != [notice] or effects[1]["state"] != notice:
                return ["Notification must deliver the actual note link to the requested recipient."]
        return []
    if len(session.reservations) != 1 or [row["operation"] for row in effects] != ["reserve_stock"]:
        return ["Expected one reservation and no other writes."]
    reservation = next(iter(session.reservations.values()))
    if ((reservation["sku"], reservation["depot"], reservation["quantity"], reservation["status"])
            != (goal.resource, "D4", goal.quantity, "active")
            or reservation.get("request_ref", "") != goal.request_ref
            or session.available_units != goal.stock - goal.quantity):
        return ["Reservation or remaining stock differs from the request."]
    if reservation != effects[0]["state"] or not has_source(session, effects[0]):
        return ["Reservation lacks a valid source receipt."]
    expected = {key: reservation[key] for key in ("reservation_id", "sku", "depot", "quantity", "status")}
    for check in session.checks:
        call = check["call"]
        event = session.events[call - 1]
        if (call > effects[0]["call"] and event["tool"] == "get_reservation_status"
                and not event["illegal"] and event["result"] == expected
                and reservation_id_visible(session.events[:call - 1], reservation["reservation_id"])
                and check == {"call": call, **expected}):
            return []
    return ["Missing read-back of the active reservation."]


def evaluate(session, answer):
    issues = completion_issues(session)
    illegal = sum(event["illegal"] for event in session.events)
    responded = bool(answer and answer.strip() and not answer.startswith(("Error:", "Error during execution:")))
    reports_block = responded and answer.strip().casefold().startswith("blocked:")
    blocked = {
        event["tool"] for event in session.events if not event["illegal"]
        and event["tool"] in session.read_tools and event["result"] == UNAVAILABLE
    }
    acquired = bool(session.acquisitions)
    strict = responded and not reports_block and not issues and not illegal
    correct_stop = bool(reports_block and blocked == set(session.read_tools) and not acquired
                        and not session.effects and not illegal)
    # Recovery is witnessed only if a failed acquisition precedes a successful acquisition.
    failed = [event["call"] for event in session.events if event["tool"] in session.read_tools
              and not event["illegal"] and event["result"] == TIMEOUT]
    successful_reads = Counter(row["tool"] for row in session.acquisitions.values())
    recovered_read = failed and any(row["call"] > failed[0] for row in session.acquisitions.values())
    recovered_write = strict and any(e["tool"] == "reserve_stock" and e["result"] == WRITE_TIMEOUT
                                     for e in session.events)
    return deepcopy({
        "strict_success": strict, "correct_stop": correct_stop, "issues": issues,
        "recovery_witness": bool(recovered_read or recovered_write),
        "events": session.events, "effects": session.effects, "acquisitions": session.acquisitions,
        "notes": session.notes, "notices": session.notices, "reservations": session.reservations,
        "available_units": session.available_units, "checks": session.checks, "illegal_calls": illegal,
        "tool_fee": sum(e["fee"] for e in session.events if e["kind"] == "execution"),
        "diagnostic_fee": sum(e["fee"] for e in session.events if e["kind"] == "diagnosis"),
        "diagnostic_calls": sum(e["kind"] == "diagnosis" for e in session.events),
        "failed_calls": sum("error" in e["result"] for e in session.events),
        "repeated_acquisitions": sum(n - 1 for n in successful_reads.values()),
    })
