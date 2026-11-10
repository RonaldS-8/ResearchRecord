"""Run the native ToolMaze Agent against one registered MVP development fixture."""

import argparse
from copy import deepcopy
from importlib.metadata import version
import json
from pathlib import Path
import platform
import subprocess
from time import perf_counter
from types import SimpleNamespace

from .environment import FAULTS, RecoverySession, evaluate
from .tasks import DEVELOPMENT
from extensions.toolmaze_agent_recovery.methods import ARMS, STOP, History, MethodAgent
from extensions.toolmaze_agent_recovery.session import BUDGET
from evaluation.agents.base_agent import AgentAction
from evaluation.agents.vllm_agent import VLLMAgent

MODEL = "Qwen3-4B-Thinking-2507"
MODEL_REVISION = "768f209d9ea81521153ed38c47d515654e938aea"
REQUESTS = 12
OUTPUT_LIMIT = 6144
SEED = 2701


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


def run_episode(agent, session, *, max_turns=BUDGET):
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
    answer = None
    model_seconds = 0.0
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
        **evaluate(session, answer), "answer": answer,
        "history": deepcopy(agent.get_conversation_history()),
        "tokens": agent.get_token_usage().to_dict(),
        "model_seconds": model_seconds, "wall_seconds": perf_counter() - started,
    }


def smoke(output, task, condition, endpoint):
    output.mkdir()
    config = {
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "benchmark": "ToolMaze-Recovery MVP", "cohort": "development", "task": task, "fault": condition,
        "model": MODEL, "registered_model_revision": MODEL_REVISION, "endpoint": endpoint,
        "python": platform.python_version(), "vllm": version("vllm"), "openai": version("openai"),
        "seed": SEED, "temperature": 0, "requests": REQUESTS, "max_tokens": OUTPUT_LIMIT,
        "call_budget": BUDGET, "arm": "react",
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
            kwargs["seed"] = SEED
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
        result = run_episode(agent, RecoverySession(task, condition), max_turns=REQUESTS)
    report = {**result, "model_requests": calls, "sdk_tokens": usage}
    (output / "episode.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--task", choices=DEVELOPMENT, required=True)
    parser.add_argument("--condition", choices=FAULTS, required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/v1")
    args = parser.parse_args()
    smoke(args.out, args.task, args.condition, args.endpoint)
