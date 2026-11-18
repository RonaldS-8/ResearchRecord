"""Run the frozen 2_009 protocol using the native Agent and ToolMaze executor."""

import argparse
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter
from types import SimpleNamespace
from urllib.request import Request, urlopen

from evaluation.agents.vllm_agent import VLLMAgent
from evaluation.core.sandbox import ExecutionEngine

from . import gate_2_009 as protocol


BASE_URL = "http://127.0.0.1:8000"
POLICY = ContextVar("public_policy", default=False)
TERMINAL_BATCH_ERRORS = {"service_error", "usage_mismatch", "request_drift"}


def guard(event, args):
    if event == "open" and POLICY.get() and isinstance(args[0], (str, bytes)):
        name = str(args[0]).lower()
        if any(mark in name for mark in ("alternatives.yaml", "perturbed_tasks", "/tools/plugins/")):
            raise PermissionError("Policy attempted to access simulator-only material")


@contextmanager
def public_scope():
    token = POLICY.set(True)
    try:
        yield
    finally:
        POLICY.reset(token)


def json_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False).encode()


def digest(value):
    return sha256(json_bytes(value)).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def append(path, value):
    with path.open("a") as file:
        file.write(json.dumps(value, ensure_ascii=False) + "\n")


class ToolSession:
    def __init__(self, task, task_path, record_to=None):
        start = perf_counter()
        self.events = []
        self.task = task
        self.record_to = record_to
        self.engine = ExecutionEngine(json.loads(task_path.read_bytes()), None)
        self.reset_seconds = perf_counter() - start
        self.initial = self.call(task.failed_tool, task.failed_arguments, initial=True)
        if self.initial["perturbation"] != "perturbed" or self.initial["output"] != {"error": task.error}:
            raise ValueError(f"Frozen first-touch receipt differs for {task.identifier}")
        if self.initial["plugins"]:
            raise ValueError("Injected failure unexpectedly entered a plugin")

    def call(self, tool, arguments, *, initial=False):
        start = perf_counter()
        arguments = deepcopy(arguments)
        plugins = []
        stack = {}
        coerced = False

        def profile(frame, event, result):
            if event == "call" and frame.f_code.co_name == "execute" and "/tools/plugins/" in frame.f_code.co_filename:
                stack[frame] = len(plugins)
                plugins.append({
                    "tool": frame.f_globals["TOOL_NAME"],
                    "arguments": deepcopy(frame.f_locals.get("arguments", {})),
                })
            if event == "return" and frame in stack:
                plugins[stack.pop(frame)]["output"] = deepcopy(result) if isinstance(result, dict) else {}

        if tool not in protocol.TOOLS or not isinstance(arguments, dict):
            out, perturbation = {"error": "Tool not allowed"}, "rejected"
        else:
            schema = self.engine.tool_executor
            coerced = schema._coerce_types(tool, deepcopy(arguments)) != arguments
            scope = POLICY.set(False)
            previous_profile = sys.getprofile()
            sys.setprofile(profile)
            try:
                out, perturbation = self.engine._intercept_tool_call(tool, arguments)
            finally:
                sys.setprofile(previous_profile)
                POLICY.reset(scope)

        entry = {"tool": tool, "arguments": arguments, "output": deepcopy(out), "plugins": plugins,
                 "perturbation": perturbation, "coerced": coerced, "seconds": perf_counter() - start}
        if not initial:
            self.events.append(entry)
        if self.record_to is not None:
            append(self.record_to / ("initial.jsonl" if initial else "events.jsonl"), entry)
        return entry if initial else out


def make_agent(prompt, cards):
    agent = VLLMAgent(
        protocol.MODEL, BASE_URL + "/v1", temperature=0,
        max_tokens=protocol.MAX_OUTPUT, request_timeout=180,
    )
    agent.initialize(prompt, cards)
    agent.messages.append({"role": "user", "content": prompt})
    return agent


def count_tokens(messages, tools):
    payload = {"model": protocol.MODEL, "messages": messages, "tools": tools}
    req = Request(BASE_URL + "/tokenize", data=json_bytes(payload),
                  headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=20) as response:
        info = json.load(response)
    if info["max_model_len"] != protocol.CONTEXT or info["count"] != len(info["tokens"]):
        raise ValueError("Server tokenization contract differs")
    return info["count"]


class RequestLog:
    def __init__(self, folder, create, seed, expected_input):
        self.folder = folder
        self.create = create
        self.seed = seed
        self.expected_input = expected_input
        self.count = 0
        self.status = None
        self.final_reasoning = None

    def stop(self, status):
        self.status = status
        # The native Agent catches this exception. It deliberately lacks transient-error keywords.
        raise RuntimeError("Frozen episode ended")

    def __call__(self, **payload):
        if self.status:
            self.stop(self.status)
        if self.count >= protocol.MAX_REQUESTS:
            self.stop("request_budget")
        start = perf_counter()
        try:
            count = count_tokens(payload["messages"], payload["tools"])
        except Exception as error:
            append(self.folder / "protocol.jsonl", {"tokenizer_failure": repr(error)})
            self.stop("service_error")
        elapsed = perf_counter() - start
        if count + protocol.MAX_OUTPUT > protocol.CONTEXT:
            append(self.folder / "protocol.jsonl", {"context_budget": count})
            self.stop("context_budget")
        if self.count == 0 and (
            digest({"messages": payload["messages"], "tools": payload["tools"]}) != self.expected_input[0]
            or count != self.expected_input[1]
        ):
            self.stop("request_drift")
        payload["seed"] = self.seed
        row = {"request": deepcopy(payload), "prompt_tokens_precheck": count, "tokenizer_seconds": elapsed}
        self.count += 1
        start = perf_counter()
        try:
            result = self.create(**payload)
            row["response"] = result.model_dump(mode="json")
        except Exception as error:
            row["error"] = repr(error)
            self.status = "service_error"
        finally:
            row["seconds"] = perf_counter() - start
            append(self.folder / "requests.jsonl", row)
        if self.status:
            self.stop(self.status)
        usage = row["response"].get("usage") or {}
        if usage.get("prompt_tokens") != count:
            self.stop("usage_mismatch")
        if not result.choices or result.choices[0].message is None:
            self.stop("empty")
        choice = result.choices[0]
        if choice.finish_reason == "length":
            self.stop("length")
        message = row["response"]["choices"][0]["message"]
        calls = message.get("tool_calls") or []
        if len(calls) > 1:
            self.stop("multiple_tool_calls")
        if calls:
            try:
                arguments = json.loads(calls[0]["function"].get("arguments") or "{}")
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be an object")
            except (ValueError, TypeError, KeyError):
                self.stop("response_parse")
        elif not str(message.get("content") or "").strip():
            self.stop("empty")
        if not calls and not message.get("function_call"):
            self.final_reasoning = message.get("reasoning_content") or message.get("reasoning")
        return result


def run_agent(agent, session, requests):
    agent.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=requests)))
    for _ in range(protocol.MAX_REQUESTS):
        with public_scope():
            action = agent.step()
        if requests.status is not None:
            return None, requests.status
        if action.type != "tool_call":
            return action.content, "answered"
        if len(session.events) >= protocol.MAX_CALLS:
            return None, "tool_budget"
        reply = session.call(action.tool_name, action.arguments)
        agent.receive_tool_result(action.tool_name, reply)
    return None, "request_budget"


def sha_file(path):
    stream = sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            stream.update(block)
    return stream.hexdigest()


def model_manifest(root):
    directory = root / "models" / protocol.MODEL
    manifest = {}
    for path in sorted(directory.glob("*.safetensors")):
        metadata = directory / ".cache/huggingface/download" / f"{path.name}.metadata"
        revision, expected, *_ = metadata.read_text().splitlines()
        actual = sha_file(path)
        if revision != protocol.REVISION or expected != actual:
            raise ValueError(f"Model revision or checksum differs for {path.name}")
        manifest[path.name] = actual
    if len(manifest) != 3:
        raise ValueError("Expected three frozen model weights")
    return {"revision": protocol.REVISION, "weights": manifest,
            "tokenizer_config": sha_file(directory / "tokenizer_config.json"),
            "tokenizer": sha_file(directory / "tokenizer.json")}


def prepare(root, output):
    start = perf_counter()
    with public_scope():
        cards = protocol.public_contracts()
    task_root = root / "benchmarks/ToolMaze/data/perturbed_tasks/c3"
    tasks = []
    for position, task in enumerate(protocol.TASKS):
        path = task_root / (task.identifier + ".json")
        session = ToolSession(task, path)
        tick = perf_counter()
        with public_scope():
            routes = protocol.candidates(task, cards)
        search_seconds = perf_counter() - tick
        prompts = {}
        for arm in protocol.ARMS:
            prompt = protocol.message(task, session.initial["output"], arm, routes)
            agent = make_agent(prompt, cards)
            input_hash = digest({"messages": agent.messages, "tools": agent.tools})
            count = count_tokens(agent.messages, agent.tools)
            if count + protocol.MAX_OUTPUT > protocol.CONTEXT:
                raise ValueError(f"Initial context exceeds budget for {task.identifier}:{arm}")
            prompts[arm] = {"user": prompt, "sha256": input_hash, "tokens": count}
        if position == 0:
            if count_tokens(agent.messages, None) >= prompts[arm]["tokens"]:
                raise ValueError("Server tokenization does not account for serialized tool cards")
        tasks.append({"public": asdict(task), "task_sha256": sha_file(path),
                      "order": protocol.ORDERS[position], "seed": 200901 + position,
                      "initial_receipt": session.initial, "routes": routes, "search_seconds": search_seconds,
                      "prompts": prompts, "reset_seconds": session.reset_seconds})
    manifest = {
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "model": model_manifest(root),
        "versions": {name: version(name) for name in ("vllm", "openai", "torch", "transformers")},
        "python": platform.python_version(), "contracts": cards, "contracts_sha256": digest(cards),
        "limits": {"max_requests": 8, "max_calls": 12, "max_output": 6144, "context": 32768,
                   "timeout_secs": 180, "temperature": 0, "wall_seconds": 28800},
        "tasks": tasks, "preparation_seconds": perf_counter() - start,
    }
    write_json(output / "freeze.json", manifest)
    return task_root, manifest


def comparable(event):
    return {key: value for key, value in event.items() if key != "seconds"}


def run(root, output):
    output.mkdir(parents=True, exist_ok=False)
    sys.addaudithook(guard)
    task_root, manifest = prepare(root, output)
    cards = manifest["contracts"]
    print("Frozen 16 initial SDK prompts and four rules", flush=True)
    completed = []
    for task, frozen in zip(protocol.TASKS, manifest["tasks"]):
        for arm in (*frozen["order"], "D"):
            folder = output / f"{task.number:03d}-{arm}"
            folder.mkdir()
            print(f"Start {folder.name}", flush=True)
            begin = perf_counter()
            path = task_root / (task.identifier + ".json")
            if sha_file(path) != frozen["task_sha256"]:
                raise RuntimeError("Task changed after freeze")
            session = ToolSession(task, path, folder)
            if comparable(session.initial) != comparable(frozen["initial_receipt"]):
                raise RuntimeError("Shared initial state changed after freeze")
            if arm == "D":
                with public_scope():
                    answer, status = protocol.deterministic(task, cards, frozen["routes"], session.call)
                requests, final_reasoning = 0, None
            else:
                prompt = frozen["prompts"][arm]
                agent = make_agent(prompt["user"], cards)
                backend = agent.client.with_options(max_retries=0).chat.completions.create
                log = RequestLog(folder, backend, frozen["seed"], (prompt["sha256"], prompt["tokens"]))
                answer, status = run_agent(agent, session, log)
                requests, final_reasoning = log.count, log.final_reasoning
            episode = {
                "task": task.identifier, "arm": arm, "requests": requests,
                "answer": answer, "status": status, "events": session.events,
                "final_reasoning": final_reasoning, "reset_seconds": session.reset_seconds,
                "initial": session.initial, "seconds": perf_counter() - begin,
            }
            write_json(folder / "episode.json", episode)
            completed.append({"episode": folder.name, "status": status, "requests": requests})
            write_json(output / "progress.json", completed)
            print(f"Finish {folder.name}: {status} ({requests} SDK requests)", flush=True)
            if status in TERMINAL_BATCH_ERRORS:
                raise RuntimeError(f"Batch stopped: {status}")
    write_json(output / "completed.json", {"episodes": 20, "requests": sum(x["requests"] for x in completed)})


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--root", type=Path, required=True)
    args.add_argument("--out", type=Path, required=True)
    opts = args.parse_args()
    run(opts.root, opts.out)


if __name__ == "__main__":
    main()
