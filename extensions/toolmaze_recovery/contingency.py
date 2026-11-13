"""Contingency-program recovery: the Agent writes the whole recovery once, the executor runs it.

Every tool call goes through the unchanged RecoverySession, so argument validation, fault
injection, fees, side effects and the outcome scorer are the ones used by the stepwise Agent.
The program receives only tool results through call(). It never sees the session, the fault
condition, fees already charged, private acquisitions or the scorer.
"""

import argparse
import ast
import builtins
from copy import deepcopy
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
from time import perf_counter
from types import SimpleNamespace

from extensions.toolmaze_agent_recovery.session import BUDGET

from .environment import FAULTS, RecoverySession, evaluate

MAX_LINES = 20_000
HANDLED = ("Exception", "KeyError", "ValueError", "TypeError", "IndexError")
METHODS = {"get", "keys", "values", "items", "append", "startswith", "endswith",
           "strip", "lower", "casefold", "split", "join", "count"}
BUILTINS = {
    "len": len, "str": str, "int": int, "bool": bool, "range": range, "min": min, "max": max,
    "any": any, "all": all, "sorted": sorted, "list": list, "dict": dict, "isinstance": isinstance,
    **{name: getattr(builtins, name) for name in HANDLED},
}
NODES = (
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.If, ast.For, ast.While, ast.Break,
    ast.Continue, ast.Pass, ast.Return, ast.FunctionDef, ast.arguments, ast.arg, ast.Try,
    ast.ExceptHandler, ast.Raise, ast.Name, ast.Load, ast.Store, ast.Constant, ast.JoinedStr,
    ast.FormattedValue, ast.List, ast.Tuple, ast.Dict, ast.Subscript, ast.Slice, ast.Attribute,
    ast.Call, ast.keyword, ast.Compare, ast.BoolOp, ast.UnaryOp, ast.BinOp, ast.IfExp,
    ast.comprehension, ast.ListComp, ast.DictComp, ast.GeneratorExp, ast.And, ast.Or, ast.Not,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot,
    ast.Add, ast.Sub, ast.Mult, ast.Mod, ast.USub,
)
# The public program interface. The same text is given to the model in program mode.
API = """Functions available to the program:
- call(tool_name, **arguments) -> dict: run one advertised tool and return its JSON result.
  Tool failures are returned as a dict with an "error" key; they are never raised.
- finish(answer): end the program with your final reply to the user. Start the reply with
  'Blocked:' if the task cannot be completed.
- escalate(reason): end the program and continue the task yourself, step by step, with the
  full history of the calls the program made.
Builtins: len, str, int, bool, range, min, max, any, all, sorted, list, dict, isinstance.
No imports, no names or attributes starting with an underscore, no file or network access."""
PROGRAM_SYSTEM = (
    "You complete tasks by writing one Python program that an executor runs for you once. "
    "Reply with exactly one ```python code block and nothing after it. Use only the task text, "
    "the tool descriptions and tool results; bind arguments from earlier results by reference. "
    "Plan in the program for failures the tool descriptions say can happen. "
    "Call escalate(reason) for anything the program cannot handle.\n\n" + API
)
CODE_BLOCK = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.S)


class ProgramRejected(ValueError):
    pass


class Halt(BaseException):
    """Ends the program. A BaseException, so the program's own handlers cannot catch it."""

    def __init__(self, status, text=None):
        super().__init__(status)
        self.status, self.text = status, text


def check_program(source):
    """Parse and allow-list the program. Returns the parsed tree."""
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        raise ProgramRejected(f"Syntax error: {exc.msg} (line {exc.lineno})") from None
    for node in ast.walk(tree):
        if not isinstance(node, NODES):
            raise ProgramRejected(f"Construct not allowed: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ProgramRejected(f"Name not allowed: {node.id}")
        if isinstance(node, (ast.FunctionDef, ast.arg)):
            name = node.name if isinstance(node, ast.FunctionDef) else node.arg
            if name.startswith("_") or isinstance(node, ast.FunctionDef) and node.decorator_list:
                raise ProgramRejected(f"Definition not allowed: {name}")
        if isinstance(node, ast.Attribute) and node.attr not in METHODS:
            raise ProgramRejected(f"Attribute not allowed: {node.attr}")
        if isinstance(node, ast.ExceptHandler):
            names = node.type.elts if isinstance(node.type, ast.Tuple) else [node.type]
            if not all(isinstance(name, ast.Name) and name.id in HANDLED for name in names):
                raise ProgramRejected("Only named handlers for " + ", ".join(HANDLED) + " are allowed")
    return tree


def extract_program(text):
    """The last fenced code block of a reply, or None."""
    blocks = CODE_BLOCK.findall(text or "")
    return blocks[-1] if blocks else None


def run_program(session, source, *, max_lines=MAX_LINES):
    """Execute one program against the session. Scoring is left to the caller."""
    record = {"status": None, "answer": None, "reason": None, "error": None,
              "calls_before": len(session.events), "program_sha256": sha256(source.encode()).hexdigest()}
    try:
        code = compile(check_program(source), "<program>", "exec")
    except ProgramRejected as exc:
        record.update(status="rejected", error=str(exc))
        return record

    def call(tool_name, arguments=None, **keywords):
        if arguments is not None and keywords:
            raise TypeError("Pass arguments either as one dict or as keywords")
        if len(session.events) >= getattr(session, "call_budget", BUDGET):
            raise Halt("halted_budget")
        return session.call(tool_name, keywords if arguments is None else arguments)

    def finish(answer):
        raise Halt("finished", str(answer))

    def escalate(reason=""):
        raise Halt("escalated", str(reason))

    lines = 0

    def tracer(frame, event, arg):
        nonlocal lines
        if frame.f_code.co_filename != "<program>":
            return None
        if event == "line":
            lines += 1
            if lines > max_lines:
                raise Halt("halted_steps")
        return tracer

    namespace = {"__builtins__": dict(BUILTINS), "call": call, "finish": finish, "escalate": escalate}
    previous = sys.gettrace()
    sys.settrace(tracer)
    try:
        exec(code, namespace)
        record["status"] = "no_finish"
    except Halt as halt:
        record["status"] = halt.status
        if halt.status == "finished":
            record["answer"] = halt.text
        elif halt.status == "escalated":
            record["reason"] = halt.text
    except Exception as exc:  # A program error ends the program; it is not an executor failure.
        record.update(status="crashed", error=f"{type(exc).__name__}: {exc}")
    finally:
        sys.settrace(previous)
    record["calls"] = len(session.events) - record["calls_before"]
    record["lines"] = lines
    return record


def program_prompt(view):
    """Same task text, tool contracts and prices as the stepwise Agent receives."""
    specs = [tool["paradigms"]["function_call"]["spec"] for tool in view["tools"]]
    return (
        f'{view["task"]}\n\nTool prices: 1 engineering unit per advertised tool call, '
        "including diagnosis and failed calls. If unable to complete the task, "
        "start your final reply with 'Blocked:' and briefly explain.\n\n"
        "Tools (JSON function specifications):\n" + json.dumps(specs, indent=1)
    )


def program_episode(agent, session, *, max_requests, fallback=True):
    """One program request; on anything but finish, the native stepwise Agent continues.

    The continuation is the existing run.run_episode: the native system prompt, the same task
    message, and every call the program made replayed as the Agent's own prior calls.
    """
    from .run import run_episode

    started = perf_counter()
    view = session.public()
    agent.perturbation_mode = None
    agent.initialize(view["task"], view["tools"])
    agent.tools = []
    agent.messages[0]["content"] = PROGRAM_SYSTEM
    action = agent.step(user_message=program_prompt(view))
    reply = action.content if action.type == "final_answer" else None
    source = extract_program(reply)
    program = run_program(session, source) if source is not None else {
        "status": "no_program", "answer": None, "reason": None, "error": None,
        "calls_before": len(session.events), "calls": 0}
    program.update(reply=reply, source=source,
                   tokens=agent.get_token_usage().to_dict(), history=deepcopy(agent.get_conversation_history()))
    if program["status"] == "finished" or not fallback or max_requests <= 1:
        result = {**evaluate(session, program["answer"]), "answer": program["answer"], "continuation": None}
    else:
        result = run_episode(agent, session, max_turns=min(max_requests - 1, BUDGET),
                             resume=bool(session.events))
        result["continuation"] = {"tokens": result.pop("tokens"), "history": result.pop("history"),
                                  "checkpoints": result.pop("checkpoints")}
    return {**result, "program": program, "wall_seconds": perf_counter() - started}


def smoke(output, task, condition, endpoint):
    """Real model, program arm. Same model settings and request cap as run.smoke (stepwise arm)."""
    from evaluation.agents.vllm_agent import VLLMAgent

    from .run import MODEL, MODEL_REVISION, OUTPUT_LIMIT, REQUESTS, SEED
    from .tasks import LINEAGE

    output.mkdir()
    config = {
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "benchmark": "ToolMaze-Recovery MVP", "cohort": "development", "task": task, "fault": condition,
        "arm": "program", "model": MODEL, "registered_model_revision": MODEL_REVISION, "endpoint": endpoint,
        "python": platform.python_version(), "vllm": version("vllm"), "openai": version("openai"),
        "seed": SEED, "temperature": 0, "requests": REQUESTS, "max_tokens": OUTPUT_LIMIT,
        "call_budget": BUDGET, "program_system_sha256": sha256(PROGRAM_SYSTEM.encode()).hexdigest(),
        "lineage": {"base_task": LINEAGE[task][0], "shared_implementation": LINEAGE[task][1]},
    }
    (output / "config.json").write_text(json.dumps(config, indent=2))
    agent = VLLMAgent(MODEL, endpoint, temperature=0, max_tokens=OUTPUT_LIMIT, request_timeout=120)
    completions = agent.client.with_options(max_retries=0).chat.completions
    calls = 0
    usage = {"input_tokens": 0, "output_tokens": 0}
    with (output / "requests.jsonl").open("x", encoding="utf-8") as records:
        def create(**kwargs):
            nonlocal calls
            if calls >= REQUESTS:
                raise RuntimeError("Request cap reached.")
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
        session = RecoverySession(task, condition)
        try:
            result = program_episode(agent, session, max_requests=REQUESTS)
        except Exception as exc:
            (output / "failure.json").write_text(json.dumps({
                "error": repr(exc), "evaluation": evaluate(session, None), "model_requests": calls,
                "sdk_tokens": usage}, ensure_ascii=False, indent=2), encoding="utf-8")
            raise
    report = {**result, "model_requests": calls, "sdk_tokens": usage}
    (output / "episode.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    from .tasks import DEVELOPMENT

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--task", choices=DEVELOPMENT, required=True)
    parser.add_argument("--condition", choices=FAULTS, required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/v1")
    args = parser.parse_args()
    smoke(args.out, args.task, args.condition, args.endpoint)
