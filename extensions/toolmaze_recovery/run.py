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
from extensions.toolmaze_agent_recovery.methods import ARMS, STOP, History, MethodAgent
from extensions.toolmaze_agent_recovery.session import BUDGET
from evaluation.agents.base_agent import AgentAction
from evaluation.agents.vllm_agent import VLLMAgent

MODEL = "Qwen3-4B-Thinking-2507"
MODEL_REVISION = "768f209d9ea81521153ed38c47d515654e938aea"
REQUESTS = 12
OUTPUT_LIMIT = 6144
SEED = 2701
CHECKPOINT_REFERENCE = "8ad504c68b872be913cad640"


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


def run_episode(agent, session, *, max_turns=BUDGET, resume=False):
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
    for turn in range(max_turns):
        model_started = perf_counter()
        action = agent.step(user_message=prompt if turn == 0 and not resume else None)
        model_seconds += perf_counter() - model_started
        if action.type == "final_answer":
            answer = action.content
            break
        if action.type != "tool_call":
            break
        result = session.call(action.tool_name, action.arguments)
        agent.receive_tool_result(action.tool_name, result)
    return {
        **evaluate(session, answer), "answer": answer,
        "history": deepcopy(agent.get_conversation_history()),
        "tokens": agent.get_token_usage().to_dict(),
        "model_seconds": model_seconds, "wall_seconds": perf_counter() - started,
    }


def smoke(output, task, condition, endpoint, *, start_mode="full", seed=SEED, first_tool=None):
    if start_mode not in ("full", "write-checkpoint"):
        raise ValueError("Unknown start mode")
    if first_tool is not None and (
            start_mode != "write-checkpoint" or first_tool != "lookup_reservations_by_request"):
        raise ValueError("First-action assistance is restricted to the registered write checkpoint")
    output.mkdir()
    config = {
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "benchmark": "ToolMaze-Recovery MVP", "cohort": "development", "task": task, "fault": condition,
        "model": MODEL, "registered_model_revision": MODEL_REVISION, "endpoint": endpoint,
        "python": platform.python_version(), "vllm": version("vllm"), "openai": version("openai"),
        "seed": seed, "temperature": 0, "requests": REQUESTS, "max_tokens": OUTPUT_LIMIT,
        "call_budget": BUDGET, "arm": "react", "start_mode": start_mode,
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
        result = run_episode(agent, session, max_turns=REQUESTS, resume=resume)
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
    args = parser.parse_args()
    smoke(args.out, args.task, args.condition, args.endpoint, start_mode=args.start_mode,
          seed=args.seed, first_tool=args.first_tool)
