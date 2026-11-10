"""Private execution boundary for the two Gate 25 engineering fixtures."""

from collections import Counter
from copy import copy, deepcopy
from functools import lru_cache
from time import perf_counter
from types import FunctionType, SimpleNamespace

from extensions.toolmaze_diagnostic_mvp.environment import (
    ROOT, ExecutionEngine, fresh_engine, load_json,
)

DATA = ROOT / "benchmarks/ToolMaze/data"
READS = {
    "001": ("get_aviationstack_gate_board_native", "get_flightaware_trip_timeline_native"),
    "002": ("get_bank_balance_sheet_native", "get_broker_balance_ledger_native"),
}
BUDGET = 16
TIMEOUT = {"error": "Upstream request timed out."}
UNAVAILABLE = {"error": "This endpoint is unavailable for the remainder of this session."}

# Follow the native calls to the simulated write boundary. Each binding is local
# to this executor. Native modules and other concurrent sessions are untouched.
WRITE_LEAVES = {"create_document", "push_alert", "send_email", "schedule_meeting", "snapshot_workspace"}
DELEGATES = {
    "create_document_and_alert": {"cd": "create_document", "pa": "push_alert"},
    "create_document_and_alert_from_data": {"cdaa": "create_document_and_alert"},
    "archive_aviationstack_gate_board_native": {"cdaafd": "create_document_and_alert_from_data"},
    "archive_flightaware_trip_timeline_native": {"cdaafd": "create_document_and_alert_from_data"},
    "archive_bank_balance_sheet_native": {"cdaafd": "create_document_and_alert_from_data"},
    "archive_broker_balance_ledger_native": {"cdaafd": "create_document_and_alert_from_data"},
    "publish_google_slot_ticket_native": {"pa": "push_alert"},
    "email_contact_by_name": {"se": "send_email"},
    "archive_light_mesh_snapshot_native": {"cdaafd": "create_document_and_alert_from_data"},
    "archive_light_bridge_payload_native": {"cdaafd": "create_document_and_alert_from_data"},
    "publish_bank_balance_sheet_native": {"pa": "push_alert"},
    "publish_broker_balance_ledger_native": {"pa": "push_alert"},
}


@lru_cache(maxsize=2)
def fixture(task):
    if task not in READS:
        raise ValueError("Task is outside the Gate 25 engineering fixtures")
    task_doc = load_json(DATA / "perturbed_tasks/c3" / f"C3_task_{task}_P0.json")
    template = load_json(DATA / "templates/c3" / f"{task_doc['template_id']}.json")
    return ExecutionEngine(task_doc, None), template


def recorded_plugins(plugins, effects):
    @lru_cache(maxsize=None)
    def wrap(name):
        execute = plugins[name].execute
        if name in WRITE_LEAVES:
            def commit(arguments, context):
                result = execute(arguments, context)
                if "error" not in result:
                    effects.append({
                        "call": len(context.history) + 1, "operation": name,
                        "arguments": deepcopy(arguments), "receipt": deepcopy(result),
                    })
                return result
            return SimpleNamespace(execute=commit)
        if name not in DELEGATES:
            return plugins[name]
        bindings = dict(execute.__globals__)
        for alias, dependency in DELEGATES[name].items():
            if bindings[alias].TOOL_NAME != dependency:
                raise ValueError(f"Native delegate changed: {name}.{alias}")
            bindings[alias] = wrap(dependency)
        return SimpleNamespace(execute=FunctionType(
            execute.__code__, bindings, execute.__name__, execute.__defaults__, execute.__closure__,
        ))

    return {name: wrap(name) for name in plugins}


class Session:
    def __init__(self, task, fault="clean", *, case=None, read_tools=None):
        if fault not in {"clean", "transient", "persistent", "blocked"} and case is None:
            raise ValueError("Unknown engineering fault fixture")
        base, self.template = case if case is not None else fixture(task)
        self.engine = fresh_engine(base)
        self.engine.tool_executor = copy(base.tool_executor)
        self.task = task
        self.fault = fault
        self.read_tools = read_tools if read_tools is not None else READS[task]
        self.events = []
        self.effects = []
        self.attempts = Counter()
        self.engine.tool_executor.plugins = recorded_plugins(base.tool_executor.plugins, self.effects)
        self.tools = {definition["name"] for definition in self.engine.tool_definitions}

    def fault_result(self, tool):
        if self.fault == "blocked" and tool in self.read_tools:
            return UNAVAILABLE
        if tool == self.read_tools[0] and (
            self.fault == "persistent" or (self.fault == "transient" and self.attempts[tool] == 1)
        ):
            return TIMEOUT
        return None

    def charge_kind(self, tool):
        return "execution"

    def valid_arguments(self, tool, arguments):
        return not self.engine.tool_executor._validate(tool, arguments)

    def public(self):
        definitions = sorted(self.engine.tool_definitions, key=lambda definition: definition["name"])
        return {
            "task": self.engine.task_description,
            "tools": deepcopy(definitions),
            "prices": {tool: 1 for tool in sorted(self.tools)},
        }

    def call(self, tool, arguments):
        if len(self.events) >= BUDGET:
            raise ValueError("Call budget exhausted")
        executor = self.engine.tool_executor
        step = len(self.events) + 1
        advertised = isinstance(tool, str) and tool in self.tools and isinstance(arguments, dict)
        kind = self.charge_kind(tool)
        if not advertised:
            result = {"error": "Invalid or unavailable tool call."}
            self.engine.context.record(step, tool, arguments, result, "error")
        else:
            coerced = executor._coerce_types(tool, deepcopy(arguments))
            valid = self.valid_arguments(tool, coerced)
            if valid:
                self.attempts[tool] += 1
            result = self.fault_result(tool) if valid else None
            if result is None:
                result = executor.execute(tool, deepcopy(arguments), self.engine.context, step)
                coerced = self.engine.context.history[-1].arguments
                valid = valid and tool in executor.plugins
                self.events.append({
                    "call": step, "tool": tool, "arguments": deepcopy(coerced), "result": deepcopy(result),
                    "fee": 1, "illegal": not valid, "kind": kind,
                })
                return deepcopy(result)
            self.engine.context.record(step, tool, coerced, result, "error")
            arguments = coerced
        self.events.append({
            "call": step, "tool": tool, "arguments": deepcopy(arguments), "result": deepcopy(result),
            "fee": int(advertised), "illegal": not advertised, "kind": kind,
        })
        return deepcopy(result)


def run_episode(agent, session, *, max_turns=BUDGET):
    """Run the native agent protocol. Only the selected call can advance state."""
    from .verification import evaluate

    started = perf_counter()
    public = session.public()
    if hasattr(agent, "perturbation_mode"):
        agent.perturbation_mode = None  # Same prompt in every fault condition.
    agent.initialize(public["task"], public["tools"])
    prompt = f'{public["task"]}\n\nTool prices (engineering units): 1 per tool call.'
    answer = None
    model_seconds = 0.0
    if not 0 < max_turns <= BUDGET:
        raise ValueError("Invalid Agent turn budget")
    for turn in range(max_turns):
        model_started = perf_counter()
        action = agent.step(user_message=prompt if turn == 0 else None)
        model_seconds += perf_counter() - model_started
        if action.type == "final_answer":
            answer = action.content
            break
        if action.type != "tool_call":
            break
        result = session.call(action.tool_name, action.arguments)
        agent.receive_tool_result(action.tool_name, result)

    return {
        **evaluate(session, answer),
        "answer": answer,
        "history": deepcopy(agent.get_conversation_history()),
        "tokens": agent.get_token_usage().to_dict(),
        "model_seconds": model_seconds,
        "wall_seconds": perf_counter() - started,
    }
