"""Two development-only real receipt chains for experiment 042; no model runner or learner.

Only public()/view() may be passed to a policy. Constructors/sampling/checkpoint
prefixes and the receipt-graph scorer belong to the private execution boundary.
"""
from copy import deepcopy
from fractions import Fraction as F
from types import SimpleNamespace

from .environment import ContractExecutor, invalid
from .gate34a import (BACKUP, CONTENT, ITEMS, MAIN, RESOURCE, VALIDATE, VERIFY, WRITE,
                      MechanismSession, stream)
from .tasks import definition

ARCHIVE = "read_archive_record"
ALTWRITE = "prepare_alternate_publication"
CONFIRM = "confirm_alternate_publication"
ITEM_SCOPE = tuple(item["item"] for item in ITEMS)
PRIORS = {
    "M3": {"X1": (6, 2, 1, 1), "X2": (1, 5, 2, 2), "X3": (1, 1, 4, 4)},
    "M4": {"X1": (6, 1, 3), "X2": (2, 6, 2), "X3": (2, 2, 6)},
}
STATES = {"M3": ("transient", "persistent", "stale", "outage"),
          "M4": ("transient", "shared", "independent")}


class MultipathSession(MechanismSession):
    def __init__(self, mechanism, state, *, context="X1", recovery_calls=None, _namespace=None):
        if mechanism not in STATES or state not in STATES[mechanism] or context not in PRIORS[mechanism]:
            raise ValueError("Unregistered development world")
        recovery_calls = recovery_calls if recovery_calls is not None else (8 if mechanism == "M3" else 6)
        if recovery_calls not in ((6, 8) if mechanism == "M3" else (6,)):
            raise ValueError("Unregistered recovery budget")
        self._mechanism, self._state = mechanism, state
        self._coverage, self.pending_publications = {}, {}
        super().__init__(state == "transient", _namespace=_namespace)
        self._context, self.call_budget = context, recovery_calls + 1
        definitions = {d["name"]: deepcopy(d) for d in self.engine.tool_definitions}
        definitions[VALIDATE] = definition(
            VALIDATE, "Check the record, item-level coverage and current authority of an actual "
            "pending_ref issued by an authorized backup or archive read in this task. A read returns "
            "unverified data, not writing permission. Returns evidence_ref only after successful "
            "verification. A verification failure issues no writable reference.",
            record_id="Record authorized in the task.", pending_ref="Actual pending read receipt.")
        if mechanism == "M3":
            definitions[ARCHIVE] = definition(
                ARCHIVE, "Read the independent authorized archive of this record. Returns content, "
                "item rows and pending_ref. Current item-level authority must be checked by "
                "validate_record_granularity before this pending receipt can authorize publication.",
                "Source", record_id="Record authorized in the task.")
        else:
            definitions[WRITE]["paradigms"]["function_call"]["spec"]["description"] += (
                " This endpoint shares a provider with read_primary_record. An unavailable-endpoint "
                "failure confirms that this call committed no publication.")
            definitions[ALTWRITE] = definition(
                ALTWRITE, "Prepare publication through an independent writer using exact source "
                "content and an actual authorized evidence_ref. Returns pending_publication_ref. "
                "Preparation does not publish; confirm_alternate_publication must receive this "
                "actual reference to commit. All writers share the one-publication limit.",
                record_id="Record authorized in the task.", content="Exact current source content.",
                evidence_ref="Actual authorized evidence receipt.")
            definitions[CONFIRM] = definition(
                CONFIRM, "Confirm and commit an actual pending_publication_ref from "
                "prepare_alternate_publication in this task. Returns publication_id only after "
                "the actual publication. Duplicate publication is forbidden. Read back that ID.",
                record_id="Record authorized in the task.",
                pending_publication_ref="Actual uncommitted preparation receipt.")
        self.engine.tool_definitions = list(definitions.values())
        self.engine.tool_executor = ContractExecutor(definitions, RESOURCE, "", {"record_id": RESOURCE})
        self.tools = set(definitions)
        for name in definitions:
            def execute(arguments, context, tool=name):
                return self._execute(tool, arguments)
            self.engine.tool_executor.plugins[name] = SimpleNamespace(execute=execute)

    def call_fee(self, tool):
        return F(3) if tool == ARCHIVE else F(1)

    def fault_result(self, tool):
        if tool == MAIN and (self.attempts[MAIN] == 1 or self._state != "transient"):
            return {"error": "Upstream request timed out."}
        if tool == BACKUP and self._mechanism == "M3" and self._state == "outage":
            return {"error": "Upstream request timed out."}
        return None

    def _source(self, reference):
        certificate = self.certificates.get(reference)
        source = self.acquisitions.get(certificate["pending_ref"] if certificate else reference)
        if source and source["tool"] in (BACKUP, ARCHIVE):
            if certificate is None or self._coverage.get(certificate["pending_ref"]) != ITEM_SCOPE:
                return None
        return source

    def _writable(self, args):
        source = self._source(args["evidence_ref"])
        return (source is not None and source["record_id"] == args["record_id"] == RESOURCE
                and source["content"] == args["content"] == CONTENT)

    def _execute(self, tool, args):
        if tool == BACKUP:
            result = super()._execute(tool, args)
            self._coverage[result["pending_ref"]] = (ITEM_SCOPE[:1] if self._mechanism == "M3"
                                                       and self._state == "stale" else ITEM_SCOPE)
            return result
        if tool == ARCHIVE:
            ref = self._reference()
            self.acquisitions[ref] = {"call": len(self.events) + 1, "tool": ARCHIVE, "record_id": RESOURCE,
                                     "content": CONTENT, "granularity": "item", "items": deepcopy(list(ITEMS))}
            self._coverage[ref] = ITEM_SCOPE
            return {"record_id": RESOURCE, "content": CONTENT, "pending_ref": ref, "items": deepcopy(list(ITEMS))}
        if tool == VALIDATE:
            source = self.acquisitions.get(args["pending_ref"])
            if (source is None or source["tool"] not in (BACKUP, ARCHIVE)
                    or source["record_id"] != args["record_id"]):
                return invalid("An actual pending read receipt from this task is required.")
            if (self._coverage.get(args["pending_ref"]) != ITEM_SCOPE or source["granularity"] != "item"
                    or source["items"] != list(ITEMS) or source["content"] != CONTENT):
                return {"error": "Current item-level authority could not be established for this receipt.",
                        "code": "verification_failed"}
            ref = self._reference()
            self.certificates[ref] = {"call": len(self.events) + 1, "pending_ref": args["pending_ref"],
                                      "record_id": RESOURCE}
            return {"record_id": RESOURCE, "evidence_ref": ref, "granularity": "item"}
        if tool in (WRITE, ALTWRITE):
            # Real argument/provenance validation precedes service availability.
            if not self._writable(args):
                return invalid("An actual primary or granularity-verified backup evidence_ref is required.")
            if self.publications:
                return invalid("This task already has a publication; duplicate writes are forbidden.")
            if tool == WRITE and self._mechanism == "M4" and self._state == "shared":
                return {"error": "Publication endpoint unavailable; no publication was committed."}
            if tool == ALTWRITE:
                ref = self._reference()
                self.pending_publications[ref] = {"call": len(self.events) + 1, **deepcopy(args)}
                return {"pending_publication_ref": ref}
        if tool == CONFIRM:
            job = self.pending_publications.get(args["pending_publication_ref"])
            if job is None or job["record_id"] != args["record_id"] or not self._writable(job):
                return invalid("An actual authorized publication preparation from this task is required.")
            payload = {key: job[key] for key in ("record_id", "content", "evidence_ref")}
            result = super()._execute(WRITE, payload)
            if "error" not in result:
                self.effects[-1]["operation"] = CONFIRM
            return result
        return super()._execute(tool, args)


def sample(mechanism, seed, *, recovery_calls=None):
    """Private generator; neither this table nor seed is a policy feature."""
    if mechanism not in STATES:
        raise ValueError("Unregistered mechanism")
    context = ("X1", "X2", "X3")[stream(seed, f"042:{mechanism}:context").randrange(3)]
    point = stream(seed, f"042:{mechanism}:fault").randrange(10)
    for state, weight in zip(STATES[mechanism], PRIORS[mechanism][context]):
        point -= weight
        if point < 0:
            namespace = f"{stream(seed, f'042:{mechanism}:receipts').getrandbits(256):064x}"
            return MultipathSession(mechanism, state, context=context, recovery_calls=recovery_calls,
                                    _namespace=namespace)
    raise AssertionError("Probability mass was not conserved")


def checkpoint(mechanism, *, _namespace=None):
    """Registered exogenous prefix only, never an Agent action or automatic continuation."""
    state = "stale" if mechanism == "M3" else "shared"
    session = MultipathSession(mechanism, state, _namespace=_namespace)
    session.call(MAIN, {"record_id": RESOURCE})
    pending = session.call(BACKUP, {"record_id": RESOURCE})
    verified = session.call(VALIDATE, {"record_id": RESOURCE, "pending_ref": pending["pending_ref"]})
    if mechanism == "M4":
        session.call(WRITE, {"record_id": RESOURCE, "content": pending["content"],
                             "evidence_ref": verified["evidence_ref"]})
    return session


def evaluate(session, answer):
    """Independent acceptance from actual receipt edges, ledger and committed effects.

    Does not ask the CPU model for a path/value or trust a tool's success flag alone.
    """
    events, issues = session.events, []
    if len(session.publications) != 1 or len(session.effects) != 1:
        issues.append("Expected exactly one committed publication.")
    else:
        effect = session.effects[0]
        state, call = effect["state"], effect["call"]
        commit = events[call - 1]
        ref = state["evidence_ref"]
        certificate = session.certificates.get(ref)
        source_ref = certificate["pending_ref"] if certificate else ref
        source = session.acquisitions.get(source_ref)
        payload = {"record_id": RESOURCE, "content": CONTENT, "evidence_ref": ref}
        anchor = call
        if effect["operation"] == CONFIRM:
            job_ref = commit["arguments"].get("pending_publication_ref")
            job = session.pending_publications.get(job_ref)
            if job is None:
                issues.append("Missing real preparation.")
            else:
                prepared = events[job["call"] - 1]
                anchor = job["call"]
                if (job != {"call": anchor, **payload} or not anchor < call or prepared["tool"] != ALTWRITE
                        or prepared["arguments"] != payload or prepared["illegal"]
                        or prepared["result"] != {"pending_publication_ref": job_ref}
                        or commit["arguments"] != {"record_id": RESOURCE, "pending_publication_ref": job_ref}):
                    issues.append("Invalid preparation/confirmation edge.")
        elif effect["operation"] != WRITE or commit["arguments"] != payload:
            issues.append("Invalid writer arguments.")
        if (commit["tool"] != effect["operation"] or commit["illegal"]
                or commit["result"] != {"publication_id": state["publication_id"]}
                or state != {"publication_id": state["publication_id"], **payload, "status": "active"}
                or session.publications != {state["publication_id"]: state}):
            issues.append("Invalid commit or publication state.")
        if source is None:
            issues.append("Missing actual source.")
        else:
            read = events[source["call"] - 1]
            pending = source["tool"] in (BACKUP, ARCHIVE)
            expected = {"record_id": RESOURCE, "content": CONTENT,
                        "pending_ref" if pending else "evidence_ref": source_ref}
            if pending:
                expected["items"] = list(ITEMS)
            if (source != {"call": source["call"], "tool": source["tool"], "record_id": RESOURCE,
                           "content": CONTENT, "granularity": "item", "items": list(ITEMS)}
                    or source["tool"] not in (MAIN, BACKUP, ARCHIVE) or not source["call"] < anchor
                    or read["tool"] != source["tool"] or read["illegal"] or read["result"] != expected
                    or read["arguments"] != {"record_id": RESOURCE}):
                issues.append("Invalid source edge.")
            if pending:
                if certificate is None or session._coverage.get(source_ref) != ITEM_SCOPE:
                    issues.append("Source lacks current item-level authority.")
                else:
                    verification = events[certificate["call"] - 1]
                    if (certificate != {"call": certificate["call"], "pending_ref": source_ref, "record_id": RESOURCE}
                            or not source["call"] < certificate["call"] < anchor
                            or verification["tool"] != VALIDATE or verification["illegal"]
                            or verification["arguments"] != {"record_id": RESOURCE, "pending_ref": source_ref}
                            or verification["result"] != {"record_id": RESOURCE, "evidence_ref": ref, "granularity": "item"}):
                        issues.append("Invalid verification edge.")
        expected = {k: state[k] for k in ("publication_id", "record_id", "content", "status")}
        if not any(check == {"call": check["call"], **expected} and check["call"] > call
                   and events[check["call"] - 1]["tool"] == VERIFY and not events[check["call"] - 1]["illegal"]
                   and events[check["call"] - 1]["arguments"] == {"publication_id": state["publication_id"]}
                   and events[check["call"] - 1]["result"] == expected for check in session.checks):
            issues.append("Missing actual post-commit readback.")
    ledger = session.engine.context.history
    if len(events) > session.call_budget or len(ledger) != len(events) or any(
        event["call"] != i + 1 or entry.tool_name != event["tool"] or entry.arguments != event["arguments"]
        or entry.output != event["result"] for i, (event, entry) in enumerate(zip(events, ledger))):
        issues.append("Budget or native ledger mismatch.")
    if any(e["kind"] != session.charge_kind(e["tool"])
           or F(e["fee"]) != (session.call_fee(e["tool"]) if session.billable_call(e["tool"], e["arguments"]) else 0)
           for e in events):
        issues.append("Per-call fee or category mismatch.")
    valid = bool(isinstance(answer, str) and answer.strip()
                 and not answer.lstrip().startswith(("Error:", "Error during execution:"))
                 and not answer.strip().casefold().startswith("blocked:"))
    illegal = sum(e["illegal"] for e in events)
    execution = sum((F(e["fee"]) for e in events if e["kind"] == "execution"), F())
    diagnosis = sum((F(e["fee"]) for e in events if e["kind"] == "diagnosis"), F())
    sunk = F(events[0]["fee"]) if events and events[0]["tool"] == MAIN and events[0]["result"] == {"error": "Upstream request timed out."} else F()
    return {"strict_success": not issues and not illegal and valid, "obligations_complete": not issues,
            "valid_answer": valid, "issues": issues, "illegal_calls": illegal, "execution_fee": str(execution),
            "diagnostic_fee": str(diagnosis), "sunk_fee": str(sunk), "suffix_fee": str(execution + diagnosis - sunk),
            "events": deepcopy(events)}
