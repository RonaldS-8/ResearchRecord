"""Bounded Gate 26 native Agent smoke on the existing LabServer service."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

from .integration import RecoverySession
from .methods import History, MethodAgent
from .session import TIMEOUT, run_episode
from evaluation.agents.vllm_agent import VLLMAgent

MODEL = "Qwen3-4B-Thinking-2507"
REQUESTS = 12
OUTPUT_LIMIT = 4096
SEED = 2601


def smoke(output, condition="persistent", *, common_contract=False):
    agent = VLLMAgent(
        MODEL, "http://127.0.0.1:8000/v1", temperature=0,
        max_tokens=6144 if common_contract else OUTPUT_LIMIT,
        request_timeout=120,
    )
    completions = agent.client.with_options(max_retries=0).chat.completions
    calls = 0
    usage = {"input_tokens": 0, "output_tokens": 0}
    with (output / "requests.jsonl").open("x") as records:
        def create(**kwargs):
            nonlocal calls
            if calls >= REQUESTS:
                raise RuntimeError("Gate 26 request cap reached.")
            calls += 1
            kwargs["seed"] = SEED
            entry = {"request": deepcopy(kwargs)}
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
                records.write(json.dumps(entry, ensure_ascii=False) + "\n")
                records.flush()

        agent.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        session = RecoverySession("002", condition)
        runner = MethodAgent(agent, "no_history", session.method_contract(), History()) if common_contract else agent
        result = run_episode(runner, session, max_turns=REQUESTS)
    timed_out = next((event["call"] for event in result["events"] if event["result"] == TIMEOUT), None)
    recovered = timed_out is not None and any(
        event["call"] > timed_out and event["tool"] in session.read_tools
        and "error" not in event["result"]
        for event in result["events"]
    )
    report = {**result, "model_requests": calls, "sdk_tokens": usage, "recovery_witness": recovered}
    (output / "episode.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--condition", choices=("persistent", "transient"), default="persistent")
    parser.add_argument("--common-contract", action="store_true")
    args = parser.parse_args()
    smoke(args.out, args.condition, common_contract=args.common_contract)
