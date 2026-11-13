"""Short-lived experiment 038 adapter; the fixture, Agent and scorer are unchanged."""
import argparse
from copy import deepcopy
from fractions import Fraction as F
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import platform
import subprocess
from time import perf_counter
from types import SimpleNamespace

from .gate34a import (BACKUP, DIAGNOSE, MAIN, RESOURCE, VALIDATE, VERIFY, WRITE,
                      Distribution, evaluate, execution_record, sample)
from .run import MODEL, MODEL_REVISION, OUTPUT_LIMIT, REQUESTS, VLLMAgent, required_tool

MODEL_SEED = 3301
SMOKE = (
    ("S01", "A", 34001, None, None, None),
    ("S02", "A", 34002, None, None, None),
    ("S03", "A", 34003, None, None, MAIN),
    ("S04", "A", 34004, None, None, MAIN),
    ("S05", "B", 34005, None, None, BACKUP),
    ("S06", "B", 34006, None, None, BACKUP),
    ("S07", "E", 34007, "9/10", "1/10", DIAGNOSE),
    ("S08", "E", 34008, "4/5", "1/2", DIAGNOSE),
)
PAIRS = (
    ("P01", "A", 35001, None, None, None),
    ("P02", "B", 35002, None, None, None),
    ("P03", "B", 35003, None, None, None),
    ("P04", "E", 35004, "4/5", "1/10", None),
    ("P05", "E", 35005, "9/10", "1/10", None),
    ("P06", "E", 35006, "1/2", "1/10", None),
)


def feedback_tool(view):
    """Frozen public feedback rule; never receives a Session or latent config."""
    events = view["history"]
    successful = {e["tool"] for e in events if "error" not in e["result"]}
    if view["remaining_calls"] == 0 or VERIFY in successful:
        return None
    if WRITE in successful:
        return VERIFY
    if MAIN in successful or VALIDATE in successful:
        return WRITE
    if BACKUP in successful:
        return VALIDATE
    if sum(e["tool"] == MAIN and "error" in e["result"] for e in events) >= 2:
        return BACKUP
    diagnostics = [e for e in events if e["tool"] == DIAGNOSE]
    if not diagnostics and DIAGNOSE in view["prices"] and F(view["prices"][DIAGNOSE]) <= F(1, 10):
        return DIAGNOSE
    if diagnostics and diagnostics[-1]["result"].get("signal") == "persistent_hint":
        return BACKUP
    return MAIN


def initialize(agent, session):
    """Original system/exit wording; only task/contract/public facts are new."""
    view = session.public()
    agent.perturbation_mode = None
    agent.initialize(view["task"], view["tools"])
    prompt = (f'{view["task"]}\n\nTool prices (engineering units per advertised call, including '
              f'failed calls): {json.dumps(view["prices"], sort_keys=True)}. '
              f'Public context: {json.dumps(view["context"])}. '
              f'Tool call budget: {view["call_budget"]} total, including the observed prefix. '
              "If unable to complete the task, start your final reply with 'Blocked:' and briefly explain.")
    agent.messages.append({"role": "user", "content": prompt})
    for event in session.events:
        agent.messages.append({"role": "assistant", "content": "", "tool_calls": [{
            "id": f"prefix_call_{event['call']}", "type": "function",
            "function": {"name": event["tool"], "arguments": json.dumps(event["arguments"])},
        }]})
        agent.receive_tool_result(event["tool"], event["result"])


def run_episode(agent, session, *, arm="react", first_tool=None,
                initial_messages=None, request_limit=REQUESTS, scorer=evaluate):
    if arm not in ("react", "simple_feedback") or first_tool and arm != "react":
        raise ValueError("Unregistered control combination")
    initialize(agent, session)
    if initial_messages is not None:
        if initial_messages[:2] != agent.messages[:2]:
            raise ValueError("Checkpoint prompt differs from the original Agent prompt")
        agent.messages = deepcopy(initial_messages)
    answer, checkpoints, model_seconds = None, [], 0.0
    for turn in range(request_limit):
        view = session.view()
        selected = first_tool if turn == 0 and first_tool else feedback_tool(view) if arm == "simple_feedback" else None
        checkpoint = {"after": len(session.events), "public_view": view,
                      "constraint_source": "first_action" if turn == 0 and first_tool else "feedback_rule" if selected else None,
                      "assigned_tool": selected, "assignment_probability": "1" if selected else None,
                      "continuation": "original_native_suffix" if arm == "react" else "frozen_feedback_tool_control_with_LLM_arguments"}
        checkpoints.append(checkpoint)
        started = perf_counter()
        with required_tool(agent, selected):
            action = agent.step()
        model_seconds += perf_counter() - started
        checkpoint["model_action"] = {"type": action.type, "tool": action.tool_name if action.type == "tool_call" else None,
                                       "arguments": deepcopy(action.arguments) if action.type == "tool_call" else None}
        if action.type == "final_answer":
            checkpoint["assignment_followed"] = False if selected else None
            answer = action.content
            break
        if action.type != "tool_call":
            break
        try:
            result = session.call(action.tool_name, action.arguments)
        except ValueError as exc:
            checkpoint["execution"] = {"accepted": False, "rejection": str(exc), "tool": action.tool_name,
                                       "arguments": deepcopy(action.arguments)}
            break
        checkpoint["execution"] = execution_record(
            {"assigned_tool": selected, "probability": "1" if selected else None}, session.events[-1], checkpoint["continuation"])
        if selected is None:
            checkpoint["execution"]["assignment_followed"] = None
        agent.receive_tool_result(action.tool_name, result)
    for checkpoint in checkpoints:
        suffix = session.events[checkpoint["after"]:]
        checkpoint["realized_suffix_fees"] = {
            kind: str(sum((F(e["fee"]) for e in suffix if e["kind"] == kind), F()))
            for kind in ("execution", "diagnosis")}
    return {**scorer(session, answer), "answer": answer, "checkpoints": checkpoints,
            "history": deepcopy(agent.get_conversation_history()), "tokens": agent.get_token_usage().to_dict(),
            "model_seconds": model_seconds}


def p05_checkpoint(source, write_feedback):
    """Replay actual calls, retain actual SDK history; alter only rejection five."""
    config = json.loads((source / "config.json").read_text())
    if (config["case"], config["arm"], config["cell"], config["env_seed"],
            config["gamma"], config["diagnostic_fee"]) != (
            "P05", "simple_feedback", "E", 35005, "9/10", "1/10"):
        raise ValueError("Expected frozen experiment 038 P05 source")
    archived = json.loads((source / "result.json").read_text())
    requests = [json.loads(line)["request"] for line in (source / "requests.jsonl").read_text().splitlines()]
    expected = deepcopy(requests[4])  # Request after the first four real model actions.
    session = sample(Distribution("E", F(9, 10), F(1, 10)), 35005)
    prefix = archived["events"][:5]
    if len(prefix) != 5 or prefix[-1]["tool"] != WRITE or not prefix[-1]["illegal"]:
        raise ValueError("Expected first rejected write at call five")
    for event in prefix:
        if session.call(event["tool"], event["arguments"]) != event["result"]:
            raise ValueError("Archived receipt differs from real executor")
    if session.events != prefix:
        raise ValueError("Prefix ledger changed")
    if json.loads(expected["messages"][-1]["content"]) != prefix[-1]["result"]:
        raise ValueError("SDK history does not end at the rejected write")
    if write_feedback == "specific":
        # Regenerate the same prefix via the registered condition, never edit the ledger.
        session = sample(Distribution("E", F(9, 10), F(1, 10)), 35005)
        for event in prefix:
            session._write_feedback = "specific" if event["call"] == 5 else "original"
            session.call(event["tool"], event["arguments"])
        changed = deepcopy(session.events)
        changed[-1]["result"]["error"] = prefix[-1]["result"]["error"]
        if changed != prefix:
            raise ValueError("Feedback condition changed more than rejection text")
        expected["messages"][-1]["content"] = json.dumps(session.events[-1]["result"])
        session._write_feedback = "original"  # All future receipts are equal between arms.
    elif write_feedback != "original":
        raise ValueError("Unregistered feedback condition")
    expected.pop("tool_choice")  # Native continuation, identical removal in both arms.
    provenance = {name: sha256((source / name).read_bytes()).hexdigest()
                  for name in ("config.json", "result.json", "requests.jsonl")}
    return session, expected, {"source": str(source), "sha256": provenance,
                               "prefix_calls": 5, "prior_model_requests": 4}


def episode(output, spec, arm, endpoint, *, write_feedback="original", resume_source=None):
    output.mkdir()  # Never overwrite any existing evidence, including failed runs.
    name, cell, env_seed, gamma, fee, first_tool = spec
    distribution = Distribution(cell, F(gamma or "9/10"), F(fee or "1/10"))
    session = sample(distribution, env_seed, write_feedback=write_feedback)
    expected, provenance = None, None
    if resume_source is not None:
        if spec != PAIRS[4] or arm != "react":
            raise ValueError("Only registered P05 native checkpoint continuation is supported")
        session, expected, provenance = p05_checkpoint(resume_source, write_feedback)
    request_limit = REQUESTS - provenance["prior_model_requests"] if provenance else REQUESTS
    config = {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "case": name, "cell": cell, "env_seed": env_seed, "gamma": gamma, "diagnostic_fee": fee,
              "arm": arm, "first_tool": first_tool, "model": MODEL, "revision": MODEL_REVISION,
              "model_seed": MODEL_SEED, "temperature": 0, "max_tokens": OUTPUT_LIMIT, "request_cap": REQUESTS,
              "call_budget": session.call_budget, "exit_wording": "original", "endpoint": endpoint,
              "write_feedback": write_feedback, "feedback_scope": "checkpoint_rejection_only" if provenance else "episode",
              "checkpoint_source": provenance, "continuation_request_cap": request_limit,
              "python": platform.python_version(), "vllm": version("vllm"), "openai": version("openai")}
    (output / "config.json").write_text(json.dumps(config, indent=2))
    (output / "private-world.json").write_text(json.dumps({"fault": session.fault, "signal": session._signal,
                                                           "context": session.public()["context"]}, indent=2))
    if provenance is None:
        session.call(MAIN, {"record_id": RESOURCE})  # Registered exogenous prefix, not a model action.
    else:
        (output / "checkpoint.json").write_text(json.dumps({"provenance": provenance, "events": session.events,
                  "remaining_calls": session.view()["remaining_calls"], "expected_first_request": expected}, indent=2))
    agent = VLLMAgent(MODEL, endpoint, temperature=0, max_tokens=OUTPUT_LIMIT, request_timeout=120)
    completions = agent.client.with_options(max_retries=0).chat.completions
    calls, usage, sdk_error = 0, {"input_tokens": 0, "output_tokens": 0}, False
    started = perf_counter()
    with (output / "requests.jsonl").open("x") as records:
        def create(**kwargs):
            nonlocal calls, sdk_error
            if calls >= request_limit:
                raise RuntimeError("Registered request cap reached.")
            calls += 1
            kwargs["seed"] = MODEL_SEED
            entry = {"request": deepcopy(kwargs)}
            call_started = perf_counter()
            try:
                if calls == 1 and expected is not None and kwargs != expected:
                    raise ValueError("First SDK request changed beyond registered feedback/tool_choice control")
                response = completions.create(**kwargs)
                entry["response"] = response.model_dump(mode="json")
                if response.usage:
                    usage["input_tokens"] += response.usage.prompt_tokens
                    usage["output_tokens"] += response.usage.completion_tokens
                return response
            except Exception as exc:
                sdk_error = True
                entry["error"] = repr(exc)
                raise
            finally:
                entry["seconds"] = perf_counter() - call_started
                records.write(json.dumps(entry, ensure_ascii=False) + "\n")
                records.flush()
        agent.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        try:
            result = run_episode(agent, session, arm=arm, first_tool=first_tool,
                                 initial_messages=expected["messages"] if expected else None,
                                 request_limit=request_limit)
        except Exception as exc:
            (output / "failure.json").write_text(json.dumps({"error": repr(exc), "evaluation": evaluate(session, None),
                                                            "history": agent.get_conversation_history()}, indent=2))
            raise
    result.update({"case": name, "arm": arm, "first_tool": first_tool, "model_requests": calls,
                   "sdk_tokens": usage, "sdk_error": sdk_error, "wall_seconds": perf_counter() - started})
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    (output / "original-system-sha256.txt").write_text(sha256(agent.messages[0]["content"].encode()).hexdigest() + "\n")
    return result


def smoke_gate(directory):
    results = [json.loads((directory / f"{spec[0]}-react/result.json").read_text()) for spec in SMOKE]
    private = [json.loads((directory / f"{spec[0]}-react/private-world.json").read_text()) for spec in SMOKE]
    complete = [r for r in results if r["strict_success"]]
    def used(row, tool):
        return any(e["tool"] == tool and "error" not in e["result"] for e in row["events"])
    checks = {"both_faults": {p["fault"] for p in private} == {"transient", "persistent"},
              "primary_completion": any(used(r, MAIN) for r in complete),
              "backup_completion": any(used(r, BACKUP) and used(r, VALIDATE) for r in complete),
              "diagnosed_completion": any(used(r, DIAGNOSE) for r in complete),
              "no_sdk_error": not any(r["sdk_error"] for r in results)}
    return {"go": all(checks.values()), "checks": checks}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("smoke", "pairs"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--smoke-dir", type=Path)
    parser.add_argument("--write-feedback", choices=("original", "specific"), default="original")
    args = parser.parse_args()
    if args.stage == "pairs":
        if args.smoke_dir is None or not smoke_gate(args.smoke_dir)["go"]:
            raise ValueError("Registered smoke Go required")
    args.out.mkdir(parents=True, exist_ok=False)
    specs = SMOKE if args.stage == "smoke" else PAIRS
    failures = []
    for spec in specs:
        for arm in (("react",) if args.stage == "smoke" else ("react", "simple_feedback")):
            name = f"{spec[0]}-{arm}"
            try:
                result = episode(args.out / name, spec, arm, "http://127.0.0.1:8000/v1",
                                 write_feedback=args.write_feedback)
                print(name, result["strict_success"], result["suffix_fee"], flush=True)
            except Exception as exc:
                failures.append({"case": name, "error": repr(exc)})
                with (args.out / "failures.jsonl").open("a") as stream:
                    stream.write(json.dumps(failures[-1]) + "\n")
    if args.stage == "smoke":
        gate = {"go": False, "infrastructure_failures": failures} if failures else smoke_gate(args.out)
        (args.out / "smoke-gate.json").write_text(json.dumps(gate, indent=2))
        print("smoke_gate", gate, flush=True)
    (args.out / "completed.json").write_text(json.dumps({"stage": args.stage, "failures": failures}, indent=2))


if __name__ == "__main__":
    main()
