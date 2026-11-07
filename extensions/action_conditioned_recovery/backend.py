"""Thin adapter for C2 task loading, argument bindings and clean tool execution."""
import copy
from functools import lru_cache

from extensions.toolmaze_diagnostic_mvp.environment import ExecutionEngine, fresh_engine, load_case, resolve
from evaluation.core.judge import JudgeSystem
from evaluation.utils import TraceLogger

ERROR = {"error": "Operation unavailable"}
TOOL_LIMIT = 32


@lru_cache(maxsize=10)
def clean_base(task):
    return ExecutionEngine(load_case(task, "P1")["docs"]["P0"], None)


class Backend:
    def __init__(self, task):
        self.case = load_case(task, "P1")
        self.task = task
        self.engine = fresh_engine(clean_base(task))
        self.nodes = {n["id"]: n["tool_name"] for n in self.case["template"]["dag"]["nodes"]}
        self.outputs = {}
        self.events = []
        self.source = self.case["source"]["node_sequence"]
        self.target = self.case["target"]["node_sequence"]
        self.prefix = self.source[:self.case["position"] + 1]
        self.victim = self.prefix[-1]
        for node in self.prefix:
            self.call(node, blocked=node == self.victim)
        self.sunk = len(self.events)

    def arguments(self, node, outputs):
        bindings = self.case["template"]["parameter_bindings"][self.nodes[node]]
        return resolve(bindings, self.case["docs"]["P0"]["user_input"], outputs)

    def call(self, node, blocked=False):
        if len(self.events) >= TOOL_LIMIT:
            raise ValueError("Tool budget exhausted")
        tool = self.nodes[node]
        args = self.arguments(node, self.outputs)
        if blocked:
            output = ERROR.copy()
        else:
            output, status = self.engine._intercept_tool_call(tool, copy.deepcopy(args))
            if status != "clean" or "error" in output:
                raise ValueError(f"Unexpected failure during clean execution: {tool}")
            self.outputs[node] = copy.deepcopy(output)
        self.events.append({"call_id": len(self.events), "node": node, "tool": tool,
                            "arguments": args, "output": output, "blocked": blocked})

    def finish(self, path):
        for node in path:
            if node not in self.outputs:
                self.call(node)

    def verify(self, events, path, failed_retry):
        """Check exact workflow, dependency provenance and clean tool returns."""
        expected = [(node, node == self.victim) for node in self.prefix]
        if failed_retry:
            expected.append((self.victim, True))
        if path:
            expected.extend((node, False) for node in path if node not in self.prefix[:-1])
        if [(e["node"], e["blocked"]) for e in events] != expected:
            return {"legal_success": False, "issues": ["workflow or fault mismatch"]}
        engine = fresh_engine(clean_base(self.task))
        logger = TraceLogger(engine.task_id, "P0")
        outputs = {}
        for index, event in enumerate(events):
            node, tool = event["node"], event["tool"]
            if index != event["call_id"] or self.nodes[node] != tool:
                return {"legal_success": False, "issues": ["call identity"]}
            try:
                args = self.arguments(node, outputs)
            except (KeyError, ValueError, TypeError, IndexError):
                return {"legal_success": False, "issues": ["argument provenance"]}
            if args != event["arguments"]:
                return {"legal_success": False, "issues": ["argument binding"]}
            if event["blocked"]:
                if event["output"] != ERROR:
                    return {"legal_success": False, "issues": ["invalid failure"]}
                continue
            output, status = engine._intercept_tool_call(tool, copy.deepcopy(args))
            if output != event["output"] or status != "clean" or "error" in output:
                return {"legal_success": False, "issues": ["tool replay mismatch"]}
            outputs[node] = output
            logger.log_round(index + 1, {"type": "tool_call", "tool_name": tool,
                                        "arguments": args}, output, status)
        native = JudgeSystem().judge(self.case["docs"]["P0"], logger.to_dict())
        return {"legal_success": bool(path and native["pass"]), "native": native,
                "issues": ["native completion mismatch"] if path and not native["pass"] else []}
