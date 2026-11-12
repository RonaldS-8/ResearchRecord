"""One Gate 34-A development fixture; never pass its private session to a policy.

Only public()/view() JSON may cross the policy boundary. No Agent/model runner is
added here. Sampling and assignment metadata are evaluator-side records.
"""
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import random
from secrets import token_hex
from types import SimpleNamespace

from extensions.toolmaze_agent_recovery.session import Session
from .environment import ContractExecutor, INVALID, invalid
from .tasks import definition

MAIN = "read_primary_record"
BACKUP = "read_backup_record"
VALIDATE = "validate_record_granularity"
WRITE = "publish_verified_record"
VERIFY = "read_published_record"
DIAGNOSE = "inspect_read_channel"
CALL_BUDGET = 7
RESOURCE = "REC-3401"
CONTENT = "Valve A: 12 units; Valve B: 8 units."
ITEMS = ({"item": "Valve A", "units": 12}, {"item": "Valve B", "units": 8})
TOOLS = (
    definition(MAIN, "Read the current item-level record. Returns content and evidence_ref "
               "accepted by publish_verified_record. Read-only; retry is permitted after timeout.",
               "Source", record_id="Record authorized in the task."),
    definition(BACKUP, "Read the authorized backup of the same record. Returns content and "
               "pending_ref and item rows. Its granularity has not been verified; pending_ref is not a write "
               "reference. validate_record_granularity checks its actual item-level coverage.",
               "Source", record_id="Record authorized in the task."),
    definition(VALIDATE, "Check a pending_ref actually issued by read_backup_record in this task. "
               "Returns evidence_ref only after verifying item-level coverage and record scope.",
               record_id="Record authorized in the task.", pending_ref="Actual backup receipt."),
    definition(WRITE, "Publish exactly the current record content using a primary evidence_ref "
               "or an evidence_ref issued by validate_record_granularity. Raw backup pending_ref "
               "is not accepted. Creates one non-idempotent publication; duplicate writes are forbidden. "
               "Returns publication_id. The caller must read it back to verify publication.",
               record_id="Record authorized in the task.", content="Exact current content.",
               evidence_ref="Actual authorized evidence receipt."),
    definition(VERIFY, "Read an actual publication_id returned by a previous publication in this "
               "task. Returns its record_id, content and active status.",
               publication_id="ID from the actual write receipt."),
)
DIAGNOSTIC = definition(
    DIAGNOSE, "Read a noisy channel signal: transient_hint or persistent_hint. Neither signal "
    "guarantees the failure state. Read-only and does not change channel state. At most one "
    "call is permitted per task, including a rejected call; further calls are forbidden.",
    "Diagnostic", record_id="Record authorized in the task.",
)


@dataclass(frozen=True)
class Distribution:
    """Private registration, not a policy feature table."""
    cell: str
    gamma: Fraction = Fraction(9, 10)
    diagnostic_fee: Fraction = Fraction(1, 10)

    def __post_init__(self):
        if self.cell not in ("A", "B", "E"):
            raise ValueError("Unregistered cell")
        if self.gamma not in (Fraction(4, 5), Fraction(9, 10), Fraction(1, 2)):
            raise ValueError("Unregistered diagnostic accuracy")
        if self.diagnostic_fee not in (Fraction(1, 10), Fraction(1, 2)):
            raise ValueError("Unregistered diagnostic fee")

    def transient_probability(self, context=None):
        if self.cell == "B":
            if context not in ("X1", "X2"):
                raise ValueError("B requires registered context")
            return Fraction(4, 5) if context == "X1" else Fraction(1, 5)
        return Fraction(9, 10) if self.cell == "A" else Fraction(1, 2)


def stream(seed, domain):
    return random.Random(int.from_bytes(hashlib.sha256(f"{domain}:{seed}".encode()).digest(), "big"))


def bernoulli(rng, probability):
    return rng.randrange(probability.denominator) < probability.numerator


def sample(distribution, seed):
    """Sample Z once, then an independent noise coin, with separate RNG domains."""
    context = ("X1" if stream(seed, "context").randrange(2) == 0 else "X2") if distribution.cell == "B" else None
    transient = bernoulli(stream(seed, "fault"), distribution.transient_probability(context))
    correct = bernoulli(stream(seed, "diagnostic-noise"), distribution.gamma)
    signal = "transient_hint" if transient == correct else "persistent_hint"
    namespace = f"{stream(seed, 'receipts').getrandbits(256):064x}"
    session = MechanismSession(transient, signal=signal, context=context,
                               diagnostic_fee=distribution.diagnostic_fee if distribution.cell == "E" else None,
                               _namespace=namespace)
    return session


class MechanismSession(Session):
    def __init__(self, transient, *, signal="transient_hint", context=None,
                 diagnostic_fee=None, _namespace=None):
        if type(transient) is not bool or signal not in ("transient_hint", "persistent_hint"):
            raise ValueError("Invalid private world")
        if context not in (None, "X1", "X2"):
            raise ValueError("Invalid public context")
        if diagnostic_fee is not None and diagnostic_fee not in (Fraction(1, 10), Fraction(1, 2)):
            raise ValueError("Invalid diagnostic price")
        self.call_budget = CALL_BUDGET
        self._signal, self._diagnostic_fee = signal, diagnostic_fee
        self._context, self._namespace = context, _namespace or token_hex(32)
        self._issued = 0
        self.acquisitions, self.certificates, self.publications, self.checks = {}, {}, {}, []
        self._diagnostic_used = False
        catalog = TOOLS + ((DIAGNOSTIC,) if diagnostic_fee is not None else ())
        definitions = {t["name"]: deepcopy(t) for t in catalog}
        executor = ContractExecutor(definitions, RESOURCE, "", {"record_id": RESOURCE})
        task = (f"For record {RESOURCE}, publish exactly one copy of its current item-level content. "
                "Use an actual primary evidence receipt, or an authorized backup receipt after "
                "its granularity has been verified. Read back the actual publication and check "
                "that its record, content and active status match. Give a final response.")
        engine = SimpleNamespace(tool_executor=executor, tool_definitions=list(definitions.values()),
                                 task_description=task)
        super().__init__("gate34a-record", "transient" if transient else "persistent",
                         case=(engine, None), read_tools=(MAIN, BACKUP))
        for name in definitions:
            def execute(arguments, context, tool=name):
                return self._execute(tool, arguments)
            self.engine.tool_executor.plugins[name] = SimpleNamespace(execute=execute)

    def call_fee(self, tool):
        return self._diagnostic_fee if tool == DIAGNOSE and self._diagnostic_fee is not None else Fraction(1)

    def charge_kind(self, tool):
        return "diagnosis" if tool == DIAGNOSE else "execution"

    def public(self):
        public = super().public()
        public["prices"] = {tool: str(fee) for tool, fee in public["prices"].items()}
        public.update({"call_budget": self.call_budget, "context": self._context})
        return public

    def view(self):
        return {**self.public(), "history": deepcopy(self.events),
                "remaining_calls": self.call_budget - len(self.events)}

    def _reference(self):
        self._issued += 1
        return hashlib.sha256(f"{self._namespace}:{self._issued}".encode()).hexdigest()[:24]

    def _execute(self, tool, args):
        call = len(self.events) + 1
        if tool in (MAIN, BACKUP):
            reference = self._reference()
            self.acquisitions[reference] = {"call": call, "tool": tool, "record_id": RESOURCE,
                                             "content": CONTENT, "granularity": "item", "items": deepcopy(list(ITEMS))}
            result = {"record_id": RESOURCE, "content": CONTENT,
                      "evidence_ref" if tool == MAIN else "pending_ref": reference}
            if tool == BACKUP:
                result["items"] = deepcopy(self.acquisitions[reference]["items"])
            return result
        if tool == VALIDATE:
            source = self.acquisitions.get(args["pending_ref"])
            if (source is None or source["tool"] != BACKUP or source["record_id"] != args["record_id"]
                    or source["granularity"] != "item" or source["items"] != list(ITEMS)
                    or source["content"] != CONTENT):
                return invalid("A real item-level backup receipt from this task is required.")
            reference = self._reference()
            self.certificates[reference] = {"call": call, "pending_ref": args["pending_ref"],
                                             "record_id": RESOURCE}
            return {"record_id": RESOURCE, "evidence_ref": reference, "granularity": "item"}
        if tool == WRITE:
            if self.publications:
                return invalid("This task already has a publication; duplicate writes are forbidden.")
            source = self.acquisitions.get(args["evidence_ref"])
            certificate = self.certificates.get(args["evidence_ref"])
            if certificate is not None:
                source = self.acquisitions.get(certificate["pending_ref"])
            if (source is None or source["record_id"] != args["record_id"] or args["content"] != source["content"]
                    or source["tool"] == BACKUP and certificate is None):
                return invalid("An actual primary or granularity-verified backup evidence_ref is required.")
            identifier = self._reference()
            state = {"publication_id": identifier, "record_id": RESOURCE, "content": args["content"],
                     "status": "active", "evidence_ref": args["evidence_ref"]}
            self.publications[identifier] = state
            self.effects.append({"call": call, "operation": WRITE, "state": deepcopy(state)})
            return {"publication_id": identifier}
        if tool == VERIFY:
            state = self.publications.get(args["publication_id"])
            if state is None:
                return invalid("A publication_id from an actual write receipt in this task is required.")
            result = {k: state[k] for k in ("publication_id", "record_id", "content", "status")}
            self.checks.append({"call": call, **result})
            return result
        return {"signal": self._signal}

    def call(self, tool, arguments):
        # Consume the permission even on a malformed first diagnostic call. The
        # ordinary Session/executor still validates, records and charges that call.
        if tool == DIAGNOSE and tool in self.tools and len(self.events) < self.call_budget:
            used = self._diagnostic_used
            self._diagnostic_used = True
            if used:
                result = invalid("The one permitted diagnostic call has already been used.")
                step = len(self.events) + 1
                self.engine.context.record(step, tool, deepcopy(arguments), result, "error")
                self.events.append({"call": step, "tool": tool, "arguments": deepcopy(arguments),
                                    "result": result, "fee": str(self.call_fee(tool)), "illegal": True,
                                    "kind": "diagnosis"})
                return deepcopy(result)
        result = super().call(tool, arguments)
        if result.get("code") == INVALID:
            self.events[-1]["illegal"] = True
        # Public JSON carries exact rational fee strings, not binary float sums.
        self.events[-1]["fee"] = str(self.events[-1]["fee"])
        return result


def evaluate(session, answer):
    """Independent receipt-graph acceptance for this fixture only."""
    events = session.events
    issues = []
    if len(session.publications) != 1 or len(session.effects) != 1:
        issues.append("Expected exactly one publication.")
    else:
        effect = session.effects[0]
        state = effect["state"]
        write = events[effect["call"] - 1]
        ref = state["evidence_ref"]
        certificate = session.certificates.get(ref)
        source = session.acquisitions.get(certificate["pending_ref"] if certificate else ref)
        if (write["tool"] != WRITE or write["illegal"] or write["result"] != {"publication_id": state["publication_id"]}
                or write["arguments"] != {"record_id": RESOURCE, "content": CONTENT, "evidence_ref": ref}
                or session.publications != {state["publication_id"]: state}
                or state != {"publication_id": state["publication_id"], "record_id": RESOURCE,
                             "content": CONTENT, "status": "active", "evidence_ref": ref}):
            issues.append("Publication state and write ledger disagree.")
        if source is None:
            issues.append("Missing real source.")
        else:
            read = events[source["call"] - 1]
            key = "evidence_ref" if source["tool"] == MAIN else "pending_ref"
            actual_ref = certificate["pending_ref"] if certificate else ref
            if (source["record_id"] != RESOURCE or source["content"] != CONTENT or source["granularity"] != "item"
                    or source["call"] >= effect["call"] or read["illegal"] or read["tool"] != source["tool"]
                    or source["items"] != list(ITEMS)
                    or read["result"] != {"record_id": RESOURCE, "content": CONTENT, key: actual_ref,
                                          **({"items": list(ITEMS)} if source["tool"] == BACKUP else {})}
                    or read["arguments"] != {"record_id": RESOURCE}):
                issues.append("Invalid source receipt edge.")
            if source["tool"] == BACKUP:
                if certificate is None:
                    issues.append("Backup requires real granularity verification.")
                else:
                    check = events[certificate["call"] - 1]
                    if (certificate["record_id"] != RESOURCE or not source["call"] < certificate["call"] < effect["call"] or check["illegal"]
                            or check["tool"] != VALIDATE or check["arguments"] != {"record_id": RESOURCE, "pending_ref": actual_ref}
                            or check["result"] != {"record_id": RESOURCE, "evidence_ref": ref, "granularity": "item"}):
                        issues.append("Invalid granularity certificate edge.")
        expected = {k: state[k] for k in ("publication_id", "record_id", "content", "status")}
        if not any(c["call"] > effect["call"] and events[c["call"] - 1]["tool"] == VERIFY
                   and not events[c["call"] - 1]["illegal"] and events[c["call"] - 1]["result"] == expected
                   and events[c["call"] - 1]["arguments"] == {"publication_id": state["publication_id"]}
                   and c == {"call": c["call"], **expected} for c in session.checks):
            issues.append("Missing valid read-back.")
    illegal = sum(e["illegal"] for e in events)
    ledger = session.engine.context.history
    if len(ledger) != len(events) or any(
        e["call"] != i + 1 or h.tool_name != e["tool"] or h.arguments != e["arguments"] or h.output != e["result"]
        for i, (e, h) in enumerate(zip(events, ledger))
    ):
        issues.append("Native execution ledger mismatch.")
    if any(Fraction(e["fee"]) != (session.call_fee(e["tool"]) if e["tool"] in session.tools else 0) for e in events):
        issues.append("Per-call fee mismatch.")
    valid_answer = bool(isinstance(answer, str) and answer.strip()
                        and not answer.lstrip().startswith(("Error:", "Error during execution:"))
                        and not answer.strip().casefold().startswith("blocked:"))
    execution = sum((Fraction(e["fee"]) for e in events if e["kind"] == "execution"), Fraction())
    diagnosis = sum((Fraction(e["fee"]) for e in events if e["kind"] == "diagnosis"), Fraction())
    # The checkpoint is an actual first valid primary timeout, never an assumed fee.
    sunk = Fraction(events[0]["fee"]) if events and events[0]["tool"] == MAIN and events[0]["result"] == {"error": "Upstream request timed out."} else Fraction()
    return {"strict_success": not issues and not illegal and valid_answer,
            "obligations_complete": not issues, "valid_answer": valid_answer,
            "issues": issues, "illegal_calls": illegal, "execution_fee": str(execution),
            "diagnostic_fee": str(diagnosis), "sunk_fee": str(sunk),
            "suffix_fee": str(execution + diagnosis - sunk), "events": deepcopy(events)}


def assign_tool(view, seed):
    """Evaluator-only randomized first-checkpoint assignment; no argument filling."""
    if (len(view["history"]) != 1 or view["history"][0]["tool"] != MAIN
            or "error" not in view["history"][0]["result"]):
        raise ValueError("Assignment requires the first-timeout checkpoint")
    tools = (MAIN, BACKUP) + ((DIAGNOSE,) if any(t["name"] == DIAGNOSE for t in view["tools"]) else ())
    selected = tools[stream(seed, "assignment").randrange(len(tools))]
    return {"assigned_tool": selected, "probability": str(Fraction(1, len(tools)))}


def execution_record(assignment, event, continuation):
    return {**assignment, "continuation": continuation, "executed_tool": event["tool"],
            "arguments": deepcopy(event["arguments"]), "legal": not event["illegal"],
            "assignment_followed": event["tool"] == assignment["assigned_tool"],
            "usable_result": not event["illegal"] and "error" not in event["result"]}
