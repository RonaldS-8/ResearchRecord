"""Recovery-only interventions on the native Agent's public tool protocol."""

from collections import Counter
from copy import deepcopy
import json

from extensions.action_conditioned_recovery.gate18 import BTM_CONSTRAINTS, BTM_GUIDANCE, BTM_RETRY
from evaluation.agents.base_agent import AgentAction
from .integration import TRAIN_TASK
from .session import BUDGET, UNAVAILABLE

ARMS = (
    "react", "no_history", "btm", "btm_full", "memory", "hybrid",
    "fixed", "context", "recent", "threshold", "simple_diagnosis",
)
CONTINUATION = "try each remaining read at most once, then execute the same public receipt contract"
STOP = "stop"


def sequential_write_context(events, contract):
    """Reconstruct the registered strong-consistency write obligation from public receipts.

    `available` contains evidence-supported, task-safe next tools, rather than all
    callable APIs. No backend, fault label, score, or reference route is accepted.
    """
    pending = None
    ids = []
    verified = set()
    absence = False
    query_failed = False
    evidence = set()
    for event in events:
        tool, result = event["tool"], event["result"]
        args = event["arguments"] if isinstance(event["arguments"], dict) else {}
        if tool in contract["reads"] and "error" not in result:
            evidence.update(result[key] for key in ("inventory_ref", "count_ticket") if key in result)
        if tool == contract["write"]:
            if result == contract["timeout"]:
                pending = deepcopy(args)
                absence, query_failed = False, False
            elif pending is not None and "error" not in result and result.get("reservation_id"):
                ids.append(result["reservation_id"])
                absence = False
        if pending is None:
            continue
        if tool == contract["lookup"]:
            query_failed = "error" in result
            if query_failed:
                absence = False
            if (not query_failed and result.get("request_ref") == pending.get("request_ref")
                    and isinstance(result.get("reservation_ids"), list)):
                returned = result["reservation_ids"]
                if result.get("status") == "found" and returned:
                    ids = list(dict.fromkeys([*ids, *returned]))
                    absence = False
                elif result.get("status") == "not_found" and not returned:
                    absence = not ids
        if (tool == contract["verify"] and "error" not in result
                and args.get("reservation_id") in ids
                and result.get("reservation_id") == args["reservation_id"]
                and result.get("status") == "active"
                and result.get("sku") == pending.get("sku")
                and result.get("quantity") == pending.get("quantity")
                and result.get("depot") == "D4"):
            verified.add(result["reservation_id"])
    if pending is None or len(ids) == 1 and ids[0] in verified:
        return None
    available = [contract["lookup"], *contract["reads"]]
    if ids:
        available.append(contract["verify"])
    elif absence and pending.get("evidence_ref") in evidence:
        available.append(contract["write"])
    remaining = BUDGET - len(events)
    return {
        "phase": "verify_existing" if ids else "confirmed_absent" if absence else "commit_unknown",
        "obligation": "Create exactly one requested reservation and read back its active status.",
        "write_arguments": pending, "reservation_ids": ids,
        "query_failed": query_failed, "remaining_calls": remaining,
        "available": [*(available if remaining > 0 else []), STOP],
    }


def unknown_action_values(context, continuation):
    """No eligible Agent history exists. Do not turn rule witnesses into Agent Q."""
    return {action: {
        "status": "unknown", "support": 0, "continuation": continuation,
        "completion": None, "remaining_tool_fee": None, "remaining_diagnostic_fee": None,
    } for action in context["available"]}


def simple_feedback_action(context, contract):
    if context["remaining_calls"] <= 0 or context["query_failed"]:
        return STOP
    if context["phase"] == "verify_existing":
        return contract["verify"] if len(context["reservation_ids"]) == 1 else STOP
    if context["phase"] == "confirmed_absent" and contract["write"] in context["available"]:
        return contract["write"]
    return contract["lookup"]


def recovery_context(events, contract):
    """Public checkpoint features. Successful acquisition returns control to the Agent."""
    reads = [event for event in events if event["tool"] in contract["reads"]]
    if not reads or any("error" not in event["result"] for event in reads):
        return None
    diagnostics = [event["result"] for event in events if event["tool"] == contract["diagnostic"]]
    available = [tool for tool in contract["reads"]
                 if not any(event["tool"] == tool and event["result"] == UNAVAILABLE for event in reads)]
    if contract["diagnostic"] and not diagnostics:
        available.append(contract["diagnostic"])
    return {
        "reads": reads, "diagnostics": diagnostics, "available": [*available, STOP],
        "remaining_calls": BUDGET - len(events),
    }


def signature(context):
    return (
        tuple((event["tool"], event["result"]["error"]) for event in context["reads"]),
        json.dumps(context["diagnostics"], sort_keys=True),
        context["remaining_calls"],
    )


class History:
    """Fit on registered training episodes, never on a session or evaluation archive."""
    def __init__(self, rows=()):
        self.recovery = Counter()
        self.switch = Counter()
        self.outcomes = []
        for row in rows:
            if row["source_task"] != TRAIN_TASK or row["continuation"] != CONTINUATION:
                raise ValueError("History is outside the registered training cohort or continuation")
            result, events = int(row["strict_success"]), row["events"]
            reads = [event for event in events if event["tool"] in row["contract"]["reads"]]
            errors = {(e["tool"], e["result"]["error"]) for e in reads if "error" in e["result"]}
            switches = {(left["tool"], right["tool"]) for left, right in zip(reads, reads[1:])
                        if "error" in left["result"] and left["tool"] != right["tool"]}
            self.recovery.update((key, result) for key in errors)
            self.switch.update((key, result) for key in switches)

            cut = row["checkpoint"]
            checkpoint = recovery_context(events[:cut], row["contract"])
            action = events[cut]["tool"] if cut < len(events) else STOP
            if checkpoint is None or action not in checkpoint["available"]:
                raise ValueError("Invalid public training checkpoint or first action")
            suffix = events[cut:]
            execution = sum(e["fee"] for e in suffix if e["kind"] == "execution")
            diagnosis = sum(e["fee"] for e in suffix if e["kind"] == "diagnosis")
            self.outcomes.append((row["task"], signature(checkpoint), action, result, execution, diagnosis))

    @staticmethod
    def posterior(counts, key):
        success, failure = counts[(key, 1)], counts[(key, 0)]
        return {"n": success + failure, "posterior": (success + 1) / (success + failure + 2)}

    def btm(self, context, contract):
        latest = context["reads"][-1]
        source, error = latest["tool"], latest["result"]["error"]
        return {
            "target": "Final episode success under the training continuation, not a causal action effect.",
            "recovery": {tool: self.posterior(self.recovery, (tool, error)) for tool in contract["reads"]},
            "switch": {tool: self.posterior(self.switch, (source, tool))
                       for tool in contract["reads"] if tool != source},
        }

    def values(self, task, context):
        estimates = {}
        key = signature(context)
        for action in context["available"]:
            related = [row for row in self.outcomes if row[1:3] == (key, action)]
            direct = [row for row in related if row[0] == task]
            selected = direct or related
            n = len(selected)
            estimates[action] = {
                "support": len(direct), "source_n": n, "extrapolated": not direct,
                "completion": sum(row[3] for row in selected) / n if n else None,
                "tool_fee": sum(row[4] for row in selected) / n if n else None,
                "diagnostic_fee": sum(row[5] for row in selected) / n if n else None,
            }
        return estimates


def recent(context):
    options = [tool for tool in context["available"] if tool != STOP]
    attempts = Counter(event["tool"] for event in context["reads"])
    latest = context["reads"][-1]["tool"]
    if latest in options and attempts[latest] < 2:
        return latest
    return next((tool for tool in options if not attempts[tool]), STOP)


def choose(arm, contract, context, estimates):
    options = [tool for tool in contract["reads"] if tool in context["available"]]
    if not options:
        return STOP
    attempts = Counter(event["tool"] for event in context["reads"])
    if arm == "fixed":
        return next((tool for tool in options if attempts[tool] < 2), STOP)
    if arm == "context":
        return next((tool for tool in options if not attempts[tool]), recent(context))
    if arm == "simple_diagnosis" and contract["diagnostic"] in context["available"]:
        return contract["diagnostic"]
    if arm == "hybrid":
        supported = [tool for tool in estimates if estimates[tool]["completion"] is not None]
        if supported:
            return min(supported, key=lambda tool: (
                -estimates[tool]["completion"],
                estimates[tool]["tool_fee"] + estimates[tool]["diagnostic_fee"],
                tool == STOP,
            ))
    if arm == "threshold":
        first = recent(context)
        best = estimates.get(first, {})
        if best.get("support", 0) and best["completion"] < 0.5:
            return next((tool for tool in options if not attempts[tool]), first)
    return recent(context)


class MethodAgent:
    """The LLM supplies the actual arguments and drives every downstream call."""
    def __init__(self, agent, arm, contract, history):
        if arm not in ARMS:
            raise ValueError("Unknown recovery method")
        self.agent, self.arm = agent, arm
        self.contract, self.history = contract, history

    def initialize(self, task, definitions):
        self.task = task
        self.events = []
        self.interventions = []
        self.agent.perturbation_mode = None
        self.agent.initialize(task, definitions)
        self.tools = self.agent.tools[:]
        self.system = self.agent.messages[0]["content"]
        if self.arm != "react":
            self.system += (
                "\nRecovery acquisition interfaces: " + ", ".join(self.contract["reads"])
                + ". Use either only if its actual receipt satisfies the user's requirements. "
                "Subsequent tool arguments must be based on the task and actual tool responses. "
                "Only call a paid diagnostic when its current evidence can help decide the next action."
            )
            if notes := self.contract.get("notes"):
                self.system += "\n" + notes

    def step(self, user_message=None):
        self.agent.tools = self.tools[:]
        self.agent.messages[0]["content"] = self.system
        context = recovery_context(self.events, self.contract)
        chosen = None
        if context is not None:
            if self.arm in {"btm", "btm_full"}:
                self.agent.messages[0]["content"] += "\n" + json.dumps(self.history.btm(context, self.contract))
                if self.arm == "btm_full":
                    self.agent.messages[0]["content"] += (
                        "\n" + BTM_GUIDANCE + "\n" + BTM_RETRY + "\n" + BTM_CONSTRAINTS
                        + "\nNever retry a tool explicitly reported unavailable for this session."
                    )
            if self.arm in {"memory", "hybrid", "threshold"}:
                values = self.history.values(self.task, context)
                self.agent.messages[0]["content"] += (
                    "\nAction estimates under the registered continuation. Null means no applicable training evidence. "
                    + json.dumps(values)
                )
            else:
                values = {}
            if self.arm in {"hybrid", "fixed", "context", "recent", "threshold", "simple_diagnosis"}:
                chosen = choose(self.arm, self.contract, context, values)
                self.interventions.append({"after": len(self.events), "tool": chosen})
                if chosen == STOP:
                    return AgentAction(type="final_answer", content="Stopped after applying the recovery rule.")
                self.agent.tools = [tool for tool in self.tools if tool["function"]["name"] == chosen]
                self.agent.messages[0]["content"] += (
                    f"\nRecovery control selected {chosen}. Call it with arguments from visible evidence."
                )
        action = self.agent.step(user_message=user_message)
        if chosen and (action.type != "tool_call" or action.tool_name != chosen):
            return AgentAction(type="final_answer", content="Error: selected recovery tool was not called.")
        return action

    def receive_tool_result(self, tool, result):
        self.events.append({"tool": tool, "result": deepcopy(result)})
        self.agent.receive_tool_result(tool, result)

    def get_token_usage(self):
        return self.agent.get_token_usage()

    def get_conversation_history(self):
        return self.agent.get_conversation_history()
