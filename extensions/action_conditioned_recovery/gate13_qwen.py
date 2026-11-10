"""Small recorded Qwen first-action and evidence extraction pilot."""
from importlib.metadata import version
import json
import time

from extensions.toolmaze_diagnostic_mvp.model_adapter import MODEL_CONFIG, ProtocolFailure, VLLMAgent

from .general import Session, facts
from .gate13 import estimate
from .run import require, write


def request(client, config, directory, view, arm, fitted):
    ids = [action["id"] for action in view["actions"]]
    extract = arm == "extract"
    function = "record_public_facts" if extract else "select_action"
    labels = {"type": "string", "enum": ["retry", "switch", "refresh", "verify", "stop", "unknown"]}
    properties = ({"clue": {"type": "string", "enum": ["hint", "none", "unknown"]},
                   "evidence": {"type": "string"},
                   "roles": {"type": "object", "properties": {k: labels for k in ids},
                             "required": ids, "additionalProperties": False}}
                  if extract else {"action": {"type": "string", "enum": ids}})
    system = (
        "Extract only visible facts. Classify the latest error as a hint if it specifically "
        "suggests a stale authorization or a lost write response, otherwise none. Quote the exact "
        "latest error as evidence. Classify each action by its described role. Use unknown when unclear."
        if extract else
        "Select one legal first recovery action. Maximize strict task completion, then minimize "
        "expected total recovery cost. The shared executor retries after a refresh or an empty receipt "
        "lookup, and switches after a rejected retry. A duplicate write fails strict completion. "
        "Use only public evidence and any provided history. Do not assume a hidden outcome."
    )
    user = {"view": view}
    if arm == "direct_history":
        user["training_statistics"] = fitted
    arguments = {
        "model": MODEL_CONFIG["model"], "temperature": config["temperature"], "seed": config["seed"],
        "max_tokens": config["max_tokens"], "timeout": config["timeout"],
        "parallel_tool_calls": False,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": json.dumps(user, default=str, ensure_ascii=False)}],
        "tools": [{"type": "function", "function": {"name": function, "parameters":
                   {"type": "object", "properties": properties, "required": list(properties),
                    "additionalProperties": False}}}],
        "tool_choice": {"type": "function", "function": {"name": function}},
    }
    write(directory / f"{arm}-request.json", arguments)
    start = time.perf_counter()
    try:
        payload = client.chat.completions.create(**arguments).model_dump(mode="json")
    except Exception as error:
        write(directory / f"{arm}-error.json", {"error": repr(error),
                                                "latency_seconds": time.perf_counter() - start})
        raise ProtocolFailure("Qwen request error") from error
    write(directory / f"{arm}-response.json", {"response": payload,
                                               "latency_seconds": time.perf_counter() - start})
    choices = payload.get("choices", [])
    require(len(choices) == 1 and choices[0]["finish_reason"] != "length", "Invalid Qwen choice")
    calls = choices[0]["message"].get("tool_calls") or []
    require(len(calls) == 1 and calls[0]["function"]["name"] == function, "Invalid Qwen tool call")
    parsed = json.loads(calls[0]["function"]["arguments"])
    require(isinstance(parsed, dict) and set(parsed) == set(properties), "Invalid Qwen fields")
    if extract:
        require(isinstance(parsed["roles"], dict) and set(parsed["roles"]) == set(ids)
                and all(role in labels["enum"] for role in parsed["roles"].values())
                and parsed["clue"] in properties["clue"]["enum"]
                and isinstance(parsed["evidence"], str), "Invalid extraction schema")
    else:
        require(parsed["action"] in ids, "Illegal Qwen action")
    return parsed


def run_model(config, out, results, fitted):
    settings = config["model"]
    require(3 * len(results) <= settings["request_limit"], "Model request budget exceeded")
    agent = VLLMAgent(model=MODEL_CONFIG["model"], base_url=MODEL_CONFIG["base_url"],
                      temperature=settings["temperature"], max_tokens=settings["max_tokens"],
                      request_timeout=settings["timeout"])
    client = agent.client.with_options(max_retries=0)
    root = out / "model"
    root.mkdir()
    write(root / "config.json", {"model": MODEL_CONFIG["model"],
                                 "configured_revision": MODEL_CONFIG["model_revision"],
                                 "inference_framework": "vLLM", "installed_version": version("vllm"),
                                 **settings})
    all_rows = []
    for result in results:
        family, mode, clue, price, label, bad = result["case"]
        view = result["view"]
        directory = root / f"{family}-{label}"
        directory.mkdir()
        public = facts(view)
        output = {}
        for arm in ("direct", "direct_history", "extract"):
            parsed = request(client, settings, directory, view, arm, fitted)
            if arm != "extract":
                role = public["roles"][parsed["action"]]
                output[arm] = Session(family, mode, clue, price, bad).finish(role)
                write(directory / f"{arm}-execution.json", output[arm])
                continue
            evidence = view["history"][-1]["output"]["error"]
            valid = (parsed["evidence"] == evidence and parsed["clue"] == public["clue"]
                     and parsed["roles"] == public["roles"])
            output["extraction"] = {"accepted": valid, "parsed": parsed}
            for name in ("hybrid", "hybrid_history"):
                representation = parsed if valid else public
                role, fallback = estimate(view, representation, fitted if valid and name == "hybrid_history" else [])
                output[name] = {"fallback": fallback,
                                **Session(family, mode, clue, price, bad).finish(role)}
        require(all(not row["issues"] for key, row in output.items() if key != "extraction"),
                "Model execution integrity failure")
        write(directory / "evaluation.json", output)
        all_rows.append({"case": result["case"], **output})
    write(root / "evaluation.json", all_rows)
