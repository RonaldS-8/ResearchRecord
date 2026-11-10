"""C2-018 execution and independent trace checks for the synthetic fault."""
import copy
from fractions import Fraction as F

from extensions.toolmaze_diagnostic_mvp.environment import (
    ExecutionEngine, json_copy, load_case, resolve,
)
from evaluation.core.judge import JudgeSystem
from evaluation.utils import TraceLogger

from .enumeration import DECISIONS, after_failure, diagnostic_probability

ERROR = {"error": "Operation unavailable"}
TOOL_LIMIT = 32


class Replay:
    def __init__(self, state, hazard, accuracy, diagnostic_cost, prices, transition_draw, diagnostic_draw):
        self.case = load_case("018", "P1")
        self.engine = ExecutionEngine(self.case["docs"]["P0"], None)
        self.state = state
        self.hazard, self.accuracy = hazard, accuracy
        self.diagnostic_cost, self.prices = diagnostic_cost, prices
        self.transition_draw, self.diagnostic_draw = transition_draw, diagnostic_draw
        self.events, self.decisions, self.outputs = [], [], {}
        self.done = False
        self.nodes = {n["id"]: n["tool_name"] for n in self.case["template"]["dag"]["nodes"]}
        prefix = self.case["source"]["node_sequence"][:self.case["position"] + 1]
        self.victim = prefix[-1]
        for node in prefix[:-1]:
            self.call(node)
        self.call(self.victim, blocked=True)
        self.advance()
        self.sunk = len(self.events)

    def advance(self):
        transitions = after_failure(self.state, self.hazard)
        if len(transitions) > 1 and self.transition_draw() < transitions[1][1]:
            self.state = transitions[1][0]

    def call(self, node, blocked=False):
        if len(self.events) >= TOOL_LIMIT:
            raise ValueError("Tool budget exhausted")
        tool = self.nodes[node]
        args = resolve(self.case["template"]["parameter_bindings"][tool],
                       self.case["docs"]["P0"]["user_input"], self.outputs)
        if blocked:
            output = ERROR.copy()
        else:
            output, status = self.engine._intercept_tool_call(tool, copy.deepcopy(args))
            if status != "clean" or "error" in output:
                raise ValueError(f"Unexpected native failure: {tool}, {status}, {output}")
            self.outputs[node] = copy.deepcopy(output)
        self.events.append({"call_id": len(self.events), "node": node, "tool": tool,
                            "arguments": args, "output": output, "blocked": blocked,
                            "charge": self.prices.get(tool, F(1))})

    def finish(self, path):
        for node in path["node_sequence"]:
            if node not in self.outputs:
                self.call(node)
        self.done = True

    def act(self, action):
        if self.done or len(self.decisions) >= DECISIONS:
            raise ValueError("No recovery decision available")
        decision = {"action": action, "charge": F(0)}
        if action == "retry":
            blocked = self.state != "H"
            self.call(self.victim, blocked)
            if blocked:
                self.advance()
            else:
                self.finish(self.case["source"])
        elif action == "switch":
            self.finish(self.case["target"])
        elif action == "diagnose":
            decision["report"] = self.diagnostic_draw() < diagnostic_probability(
                self.state, True, self.accuracy)
            decision["charge"] = self.diagnostic_cost
        elif action == "stop":
            self.done = True
        else:
            raise ValueError(action)
        self.decisions.append(decision)
        return self.view()

    def view(self):
        return json_copy({
            "task": self.case["base"].task_description,
            "tools": [d["paradigms"]["function_call"]["spec"]
                      for d in self.case["base"].tool_definitions],
            "actions": ["retry", "switch", "diagnose", "stop"],
            "remaining": DECISIONS - len(self.decisions),
            "remaining_tools": TOOL_LIMIT - len(self.events),
            "prior_transient": "1/2", "hazard": str(self.hazard), "accuracy": str(self.accuracy),
            "default_tool_price": "1", "prices": {k: str(v) for k, v in self.prices.items()},
            "diagnostic_cost": str(self.diagnostic_cost),
            "history": [{key: event[key] for key in ("call_id", "tool", "arguments", "output")}
                        for event in self.events],
            "decisions": [{k: v for k, v in decision.items() if k != "charge"}
                          for decision in self.decisions],
        })


def verify(session, events):
    """Validate real value provenance and replay clean calls on a fresh backend."""
    case = session.case
    engine = ExecutionEngine(case["docs"]["P0"], None)
    native = TraceLogger(engine.task_id, "P0")
    outputs = {}
    issues = []
    expected_prefix = case["source"]["node_sequence"][:case["position"] + 1]
    if [e["node"] for e in events[:len(expected_prefix)]] != expected_prefix:
        issues.append("prefix")
    for index, event in enumerate(events):
        node, tool = event["node"], event["tool"]
        if event["call_id"] != index or session.nodes.get(node) != tool:
            issues.append("call identity")
            continue
        try:
            arguments = resolve(case["template"]["parameter_bindings"][tool],
                                case["docs"]["P0"]["user_input"], outputs)
        except (KeyError, IndexError, TypeError, ValueError):
            issues.append("missing source")
            continue
        if arguments != event["arguments"]:
            issues.append("parameter binding")
            continue
        if event["charge"] != session.prices.get(tool, F(1)):
            issues.append("cost")
        if event["blocked"]:
            if node != session.victim or event["output"] != ERROR:
                issues.append("invalid failure")
            continue
        output, status = engine._intercept_tool_call(tool, copy.deepcopy(arguments))
        if output != event["output"] or status != "clean" or "error" in output:
            issues.append("native replay")
            continue
        outputs[node] = output
        native.log_round(index + 1, {"type": "tool_call", "tool_name": tool,
                                     "arguments": arguments}, output, status)
    matched = [p["path_id"] for p in (case["source"], case["target"])
               if all(node in outputs for node in p["node_sequence"])]
    judgement = JudgeSystem().judge(case["docs"]["P0"], native.to_dict())
    return {"native": judgement, "matched": matched, "issues": issues,
            "legal_success": bool(judgement["pass"] and matched and not issues)}
