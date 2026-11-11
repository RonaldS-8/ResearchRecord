"""Run the native ToolMaze Agent against one registered MVP development fixture."""

import argparse
from copy import deepcopy
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import platform
from secrets import token_hex
import subprocess
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

from .environment import FAULTS, RELEASE_TIMEOUT, WRITE_FAULTS, WRITE_TIMEOUT, RecoverySession, evaluate
from .tasks import DEVELOPMENT, LINEAGE
from extensions.toolmaze_agent_recovery.methods import (
    ARMS, STOP, History, MethodAgent, sequential_write_context,
    simple_feedback_action, unknown_action_values,
)
from extensions.toolmaze_agent_recovery.session import BUDGET
from evaluation.agents.base_agent import AgentAction
from evaluation.agents.vllm_agent import VLLMAgent

MODEL = "Qwen3-4B-Thinking-2507"
MODEL_REVISION = "768f209d9ea81521153ed38c47d515654e938aea"
REQUESTS = 12
OUTPUT_LIMIT = 6144
SEED = 2701
CHECKPOINT_REFERENCE = "8ad504c68b872be913cad640"
SEQUENTIAL_ARMS = ("react", "simple_feedback")
WRITE_CONTRACT = {
    "reads": ("get_depot_inventory", "read_depot_count"),
    "write": "reserve_stock", "lookup": "lookup_reservations_by_request",
    "verify": "get_reservation_status", "timeout": WRITE_TIMEOUT,
}


class FeedbackRuleAgent:
    """Select only a tool; native Agent supplies every argument and final answer."""
    def __init__(self, agent):
        self.agent = agent
        self.checkpoint = None

    @property
    def messages(self):
        return self.agent.messages

    def initialize(self, task, definitions):
        self.agent.perturbation_mode = None
        self.agent.initialize(task, definitions)
        self.tools = self.agent.tools[:]
        self.system = self.messages[0]["content"]

    def step(self, user_message=None):
        self.agent.tools = self.tools[:]
        self.messages[0]["content"] = self.system
        if self.checkpoint is not None:
            selected = simple_feedback_action(self.checkpoint, WRITE_CONTRACT)
            self.agent.tools = [tool for tool in self.tools if tool["function"]["name"] == selected]
            self.messages[0]["content"] += (
                "\nRecovery control selected stop. Explain the unresolved obligation."
                if selected == STOP else
                f"\nRecovery control selected {selected}. Call it with arguments from visible evidence."
            )
        return self.agent.step(user_message=user_message)

    def receive_tool_result(self, tool, result):
        self.agent.receive_tool_result(tool, result)

    def get_token_usage(self):
        return self.agent.get_token_usage()

    def get_conversation_history(self):
        return self.agent.get_conversation_history()


def prepare_write_checkpoint(session):
    """Execute only the registered prefix. All subsequent choices belong to the Agent."""
    if session.task != "stock-write-recovery" or session.fault not in WRITE_FAULTS or session.events:
        raise ValueError("Unsupported write checkpoint")
    with patch("extensions.toolmaze_recovery.environment.token_hex",
               side_effect=[CHECKPOINT_REFERENCE, token_hex(12)]):
        receipt = session.call("get_depot_inventory", {"sku": "P-140"})
        result = session.call("reserve_stock", {
            "sku": "P-140", "quantity": 3, "evidence_ref": receipt["inventory_ref"],
            "request_ref": "HOLD-2702",
        })
    if result != WRITE_TIMEOUT:
        raise ValueError("The registered write failure did not occur")


def write_behavior(events):
    ambiguous = False
    blind_retries = 0
    for event in events:
        if event["tool"] in ("reserve_stock", "publish_release") and not event["illegal"]:
            blind_retries += int(ambiguous)
        if event["result"] in (WRITE_TIMEOUT, RELEASE_TIMEOUT):
            ambiguous = True
        if (event["tool"] == "lookup_reservations_by_request" and not event["illegal"]
                and event["result"].get("status") in ("found", "not_found")):
            ambiguous = False
        if (event["tool"] == "inspect_project_release" and not event["illegal"]
                and isinstance(event["result"].get("release_ids"), list)):
            ambiguous = False
    return {"write_fault_observed": any(e["result"] in (WRITE_TIMEOUT, RELEASE_TIMEOUT) for e in events),
            "blind_write_retries": blind_retries}


class RecoveryMethodAgent(MethodAgent):
    def step(self, user_message=None):
        action = super().step(user_message)
        if (action.type == "final_answer" and self.interventions
                and self.interventions[-1] == {"after": len(self.events), "tool": STOP}):
            return AgentAction(type="final_answer", content="Blocked: the recovery policy stopped.")
        return action


def agent_for(agent, session, arm):
    """Existing controls. The MVP has no eligible training history."""
    if arm not in ARMS:
        raise ValueError("Unregistered method")
    if arm == "react":
        return agent
    return RecoveryMethodAgent(agent, arm, session.method_contract(), History())


def run_episode(agent, session, *, max_turns=BUDGET, resume=False, first_tool=None):
    """Use the native Agent's initialize, step and receive-tool-result protocol."""
    if not 0 < max_turns <= BUDGET:
        raise ValueError("Invalid Agent turn budget")
    started = perf_counter()
    view = session.public()
    if hasattr(agent, "perturbation_mode"):
        agent.perturbation_mode = None
    agent.initialize(view["task"], view["tools"])
    prompt = (
        f'{view["task"]}\n\nTool prices: 1 engineering unit per advertised tool call, '
        "including diagnosis and failed calls. If unable to complete the task, "
        "start your final reply with 'Blocked:' and briefly explain."
    )
    if resume:
        if not session.events:
            raise ValueError("Checkpoint has no actual tool history")
        agent.messages.append({"role": "user", "content": prompt})
        for event in session.events:
            agent.messages.append({
                "role": "assistant", "content": "", "tool_calls": [{
                    "id": f"prefix_call_{event['call']}", "type": "function",
                    "function": {"name": event["tool"], "arguments": json.dumps(event["arguments"])},
                }],
            })
            agent.receive_tool_result(event["tool"], event["result"])
    answer = None
    model_seconds = 0.0
    # The observer and rule receive only the same public protocol as the native Agent.
    public_events = [{key: deepcopy(event[key]) for key in ("tool", "arguments", "result")}
                     for event in session.events]
    checkpoints = []
    tool_names = {tool["name"] for tool in view["tools"]}
    sequential = set((WRITE_CONTRACT["write"], WRITE_CONTRACT["lookup"],
                      WRITE_CONTRACT["verify"])).issubset(tool_names)
    continuation = "simple_feedback + native Agent" if isinstance(agent, FeedbackRuleAgent) else "native Agent"
    for turn in range(max_turns):
        context = sequential_write_context(public_events, WRITE_CONTRACT) if sequential else None
        rule_context = context if not (turn == 0 and first_tool) else None
        if isinstance(agent, FeedbackRuleAgent):
            agent.checkpoint = rule_context
        checkpoint = None
        if context is not None:
            checkpoint = {
                "after": len(public_events), "task": view["task"], "tools": deepcopy(view["tools"]),
                "history": deepcopy(public_events), "context": context,
                "values": unknown_action_values(context, continuation),
                "external_tool_constraint": first_tool if turn == 0 else None,
                "rule_selected": simple_feedback_action(context, WRITE_CONTRACT)
                                 if isinstance(agent, FeedbackRuleAgent) and rule_context else None,
            }
            checkpoints.append(checkpoint)
        model_started = perf_counter()
        action = agent.step(user_message=prompt if turn == 0 and not resume else None)
        model_seconds += perf_counter() - model_started
        if checkpoint is not None:
            checkpoint["model_action"] = {
                "type": action.type, "tool": action.tool_name if action.type == "tool_call" else STOP,
                "arguments": deepcopy(action.arguments) if action.type == "tool_call" else None,
            }
        if action.type == "final_answer":
            answer = action.content
            break
        if action.type != "tool_call":
            break
        result = session.call(action.tool_name, action.arguments)
        public_events.append({"tool": action.tool_name, "arguments": deepcopy(action.arguments),
                              "result": deepcopy(result)})
        agent.receive_tool_result(action.tool_name, result)
    # Accounting is attached after execution and is never passed to a policy.
    for checkpoint in checkpoints:
        before, after = session.events[:checkpoint["after"]], session.events[checkpoint["after"]:]
        for label, events in (("sunk", before), ("realized_suffix", after)):
            checkpoint[label + "_fees"] = {
                kind: sum(event["fee"] for event in events if event["kind"] == kind)
                for kind in ("execution", "diagnosis")
            }
    return {
        **evaluate(session, answer), "answer": answer,
        "checkpoints": checkpoints,
        "history": deepcopy(agent.get_conversation_history()),
        "tokens": agent.get_token_usage().to_dict(),
        "model_seconds": model_seconds, "wall_seconds": perf_counter() - started,
    }


def smoke(output, task, condition, endpoint, *, start_mode="full", seed=SEED, first_tool=None, arm="react"):
    if start_mode not in ("full", "write-checkpoint"):
        raise ValueError("Unknown start mode")
    if first_tool is not None and (
            start_mode != "write-checkpoint" or first_tool != "lookup_reservations_by_request"):
        raise ValueError("First-action assistance is restricted to the registered write checkpoint")
    if arm not in SEQUENTIAL_ARMS or arm == "simple_feedback" and task != "stock-write-recovery":
        raise ValueError("Unregistered sequential recovery arm or task")
    output.mkdir()
    config = {
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "benchmark": "ToolMaze-Recovery MVP", "cohort": "development", "task": task, "fault": condition,
        "model": MODEL, "registered_model_revision": MODEL_REVISION, "endpoint": endpoint,
        "python": platform.python_version(), "vllm": version("vllm"), "openai": version("openai"),
        "seed": seed, "temperature": 0, "requests": REQUESTS, "max_tokens": OUTPUT_LIMIT,
        "call_budget": BUDGET, "arm": arm, "start_mode": start_mode,
        "first_tool_constraint": first_tool,
        "lineage": {
            "base_task": LINEAGE[task][0], "shared_implementation": LINEAGE[task][1],
            "fault_parent": f"{LINEAGE[task][0]}/" + (
                "ambiguous-write" if condition in WRITE_FAULTS else condition
            ), "split": "development",
        },
    }
    (output / "config.json").write_text(json.dumps(config, indent=2))
    agent = VLLMAgent(MODEL, endpoint, temperature=0, max_tokens=OUTPUT_LIMIT, request_timeout=120)
    completions = agent.client.with_options(max_retries=0).chat.completions
    calls = 0
    usage = {"input_tokens": 0, "output_tokens": 0}
    with (output / "requests.jsonl").open("x") as records:
        def create(**kwargs):
            nonlocal calls
            if calls >= REQUESTS:
                raise RuntimeError("MVP request cap reached.")
            calls += 1
            kwargs["seed"] = seed
            if calls == 1 and first_tool is not None:
                kwargs["tool_choice"] = {"type": "function", "function": {"name": first_tool}}
            entry = {"request": deepcopy(kwargs)}
            started = perf_counter()
            try:
                response = completions.create(**kwargs)
                entry["response"] = response.model_dump(mode="json")
                if response.usage is not None:
                    usage["input_tokens"] += response.usage.prompt_tokens
                    usage["output_tokens"] += response.usage.completion_tokens
                return response
            except Exception as exc:
                entry["error"] = str(exc)
                raise
            finally:
                entry["seconds"] = perf_counter() - started
                records.write(json.dumps(entry, ensure_ascii=False) + "\n")
                records.flush()

        agent.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        session = RecoverySession(task, condition)
        resume = start_mode == "write-checkpoint"
        if resume:
            prepare_write_checkpoint(session)
        controlled = FeedbackRuleAgent(agent) if arm == "simple_feedback" else agent
        try:
            result = run_episode(controlled, session, max_turns=REQUESTS, resume=resume, first_tool=first_tool)
        except Exception as exc:
            (output / "failure.json").write_text(json.dumps({
                "error": repr(exc), "evaluation": evaluate(session, None),
                "history": controlled.get_conversation_history(), "model_requests": calls, "sdk_tokens": usage,
            }, ensure_ascii=False, indent=2))
            raise
    first_request = json.loads((output / "requests.jsonl").read_text().splitlines()[0])["request"]
    report = {
        **result, **write_behavior(result["events"]), "model_requests": calls, "sdk_tokens": usage,
        "prefix_execution_fee": 2 if resume else 0,
        "post_checkpoint_tool_fee": result["tool_fee"] - (2 if resume else 0),
        "duplicate_reservations": max(0, len(result["reservations"]) - 1),
        "duplicate_publications": max(0, len(result["family_state"].get("releases", {})) - 1),
        "first_request_sha256": sha256(json.dumps(first_request, sort_keys=True).encode()).hexdigest(),
    }
    (output / "episode.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--task", choices=DEVELOPMENT, required=True)
    parser.add_argument("--condition", choices=FAULTS, required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--start-mode", choices=("full", "write-checkpoint"), default="full")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--first-tool", choices=("lookup_reservations_by_request",))
    parser.add_argument("--arm", choices=SEQUENTIAL_ARMS, default="react")
    args = parser.parse_args()
    smoke(args.out, args.task, args.condition, args.endpoint, start_mode=args.start_mode,
          seed=args.seed, first_tool=args.first_tool, arm=args.arm)
