"""Bounded Gate 26 native Agent smoke on the existing LabServer service."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

from .integration import RecoverySession
from .session import run_episode
from evaluation.agents.vllm_agent import VLLMAgent

MODEL = "Qwen3-4B-Thinking-2507"
REQUESTS = 12
OUTPUT_LIMIT = 4096
SEED = 2601


def smoke(output):
    agent = VLLMAgent(
        MODEL, "http://127.0.0.1:8000/v1", temperature=0, max_tokens=OUTPUT_LIMIT,
        request_timeout=120,
    )
    completions = agent.client.with_options(max_retries=0).chat.completions
    calls = 0
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
                return response
            except Exception as exc:
                entry["error"] = str(exc)
                raise
            finally:
                records.write(json.dumps(entry, ensure_ascii=False) + "\n")
                records.flush()

        agent.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        result = run_episode(agent, RecoverySession("002", "persistent"), max_turns=REQUESTS)
    (output / "episode.json").write_text(json.dumps({**result, "model_requests": calls}, indent=2))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    smoke(parser.parse_args().out)
