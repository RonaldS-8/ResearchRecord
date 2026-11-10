"""Paired, full-trajectory Qwen recovery pilot on the frozen Gate 17 workflow."""

import argparse
from collections import Counter
from fractions import Fraction as F
from importlib.metadata import version
from itertools import combinations, product
import json
from pathlib import Path
import platform
from statistics import mean
import subprocess
import time

from .gate16 import rank
from .gate17 import CONFIG as GATE17_CONFIG, DEFAULTS, calibrate, witnesses
from .planning17 import HALF, Planner, choose
from .run import require, write
from .workflow16 import Progress
from .workflow17 import NODE, Tape, Workflow, sample

CONFIG = Path(__file__).with_name("gate18.json")
ARMS = ("react", "btm", "memory", "hybrid", "btm_no_retry", "btm_uniform")
STALE_ARMS = ("btm", "btm_no_retry", "memory", "hybrid")
RULES = ("fixed_retry", "fixed_switch", "historical", "current_error",
         "closed_three", "parser_control", "full_plan")
SYSTEM = """Resume the interrupted user task. Complete it when possible, otherwise stop
when there is no viable route. Among equally reliable routes prefer lower total recovery fees.
At each turn use one of the available tools with arguments grounded in actual tool responses.
The first action after the initial error on the primary interface is a recovery action.
Each node allows one recovery attempt per interface. A successful credential advances the task;
the register response states whether further verification is needed. The runtime commits the
task once all required nodes succeed. A diagnosis only supplies noisy evidence, never a credential.
Use only the given tool contracts, prices, task and observations. Respond with a single tool call."""
BTM_GUIDANCE = """Use the tool/error and source-to-target recovery beliefs to guide recovery.
A high recovery belief favors another try. A low one and a stronger alternative favor switching.
Check returned fields after switching. When both look poor, consider asking for help or transferring,
represented here by stop. Alternative tools are equivalent only at the same node and credential granularity."""
BTM_RETRY = "After a tool failure, try the same tool again at least once before other options, when available."
BTM_CONSTRAINTS = """Verify every required field and its granularity after switching.
Before an irreversible operation, confirm required fields from actual tool responses.
Use a calculation tool for price calculations if the domain has one. Here prices are quoted directly.
Inspect the result of every write for errors.
Escalate only after retry and alternative routes are exhausted."""
EXTRACT = """Instead of choosing an environment action, call record_public_facts.
For available tool names, give the role indicated by the tool description (primary, alternative,
diagnose, stop). Identify the index in observations of the last execution/diagnostic outcome,
using -1 before any recovery action. Use that outcome to report success, failure, positive,
negative, or none. Copy extra_verification if that observation contains it, else null.
For an available execution tool, identify the index of the prepare or most recent successful
credential receipt in tool_history and copy the whole output as arguments, excluding
extra_verification. Use -1 and empty arguments if no execution tool is available.
Indices are zero-based. Use only observed facts and never select an environment action yourself."""
ROLE = {"A": "primary", "B": "alternative", "diagnose": "diagnose", "stop": "stop"}
BTM_LABELS = {"A": "primary interface", "B": "alternative interface"}


class DecisionFailure(ValueError):
    def __init__(self, kind, detail):
        super().__init__(detail)
        self.kind = kind


def encode(data):
    return json.dumps(data, default=str, ensure_ascii=False, sort_keys=True)


def tool_name(action, slot):
    return f"{action}_{NODE[slot]}" if action in BTM_LABELS else action


def public_view(view):
    """Project public fields and replace the experiment's internal task identifier."""
    identity = next(iter(view["task"]["input"].values()))

    def mask(value):
        if isinstance(value, dict):
            return {key: mask(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [mask(item) for item in value]
        if isinstance(value, str) and (value == identity or value.startswith(identity + ":")):
            return "request" + value[len(identity):]
        return value

    slot = view["slot"]
    return mask({
        "task": view["task"],
        "tool_history": view["history"],
        "observations": [
            {"tool": tool_name(row["action"], row["slot"]),
             "outcome": ("positive" if row["report"] else "negative") if row["action"] == "diagnose"
             else ("success" if row["report"] else "failure"),
             "extra_verification": row["route"]}
            for row in view["decisions"] if row["action"] != "stop"
        ],
        "current_node": NODE[slot],
        "available_tools": {tool_name(a, slot): ROLE[a] for a in view["actions"]},
        "execution_budget": view["budget"],
        "quoted_fees": {tool_name(a, slot): view["prices"].get(a, "0") for a in view["actions"]},
        "additional_verification_probability": view["routing_probability"],
        "diagnostic_accuracy": view["diagnostic_accuracy"],
    })


def public_facts(public):
    roles = public["available_tools"]
    index, arguments = -1, {}
    if any(role in ("primary", "alternative") for role in roles.values()):
        for i, record in enumerate(public["tool_history"]):
            output = record["output"]
            if record["tool"] == "prepare" or "credential" in output:
                index = i
                arguments = {key: value for key, value in output.items() if key != "extra_verification"}
    observations = public["observations"]
    latest = observations[-1] if observations else {"outcome": "none", "extra_verification": None}
    return {"roles": roles, "receipt_index": index, "arguments": arguments,
            "observation_index": len(observations) - 1, "outcome": latest["outcome"],
            "extra_verification": latest["extra_verification"]}


def spec(name, description, properties):
    return {"type": "function", "function": {
        "name": name, "description": description, "parameters": {
            "type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False,
        },
    }}


def environment_tools(view, public, facts):
    tools = []
    for action in view["actions"]:
        name = tool_name(action, view["slot"])
        if action in BTM_LABELS:
            description = (
                f"Run the {BTM_LABELS[action]} for {public['current_node']}. Use the prepared input "
                "or current credential. Success returns a credential. Registration also reports "
                "whether verification is required."
            )
            properties = {key: {"type": "integer" if type(value) is int else "string"}
                          for key, value in facts["arguments"].items()}
        else:
            description = {"diagnose": "Buy a noisy signal about the current primary service.",
                           "stop": "End recovery and leave the unfinished task as is."}[action]
            properties = {}
        tools.append(spec(name, description, properties))
    return tools


def evidence_tool(facts):
    obj = lambda keys: {"type": "object", "properties": keys, "required": list(keys),
                        "additionalProperties": False}
    return spec("record_public_facts", "Record grounded recovery facts.", {
        "roles": obj({key: {"type": "string", "enum": list(ROLE.values())}
                      for key in facts["roles"]}),
        "receipt_index": {"type": "integer"},
        "arguments": obj({key: {"type": "integer" if type(value) is int else "string"}
                          for key, value in facts["arguments"].items()}),
        "observation_index": {"type": "integer"},
        "outcome": {"type": "string", "enum": ["success", "failure", "positive", "negative", "none"]},
        "extra_verification": {"type": ["boolean", "null"]},
    })


def recovery_keys(row):
    errors, transitions = set(), set()
    for event in row["views"][0]["history"] + row["events"]:
        name = event["tool"]
        if name[:2] not in ("A_", "B_"):
            continue
        if "error" in event["output"]:
            errors.add((name, event["output"]["error"]))
        other = ("B" if name[0] == "A" else "A") + name[1:]
        if any(source == other for source, _ in errors):
            transitions.add((other, name))
    return errors, transitions


def history_summary(rows):
    counts = {"recovery": Counter(), "switch": Counter()}
    successes = {"recovery": Counter(), "switch": Counter()}
    for row in rows:
        for field, keys in zip(counts, recovery_keys(row)):
            counts[field].update(keys)
            if row["score"]["legal_success"]:
                successes[field].update(keys)
    return {field: [{"key": key, "n": n, "successes": successes[field][key]}
                    for key, n in sorted(counter.items())] for field, counter in counts.items()}


def btm_prompt(arm, history, error):
    posterior = {
        field: {tuple(row["key"]): (row["successes"], row["n"]) for row in rows}
        for field, rows in history.items()
    }

    def probability(field, key):
        if arm == "btm_uniform":
            return "0.500"
        s, n = posterior[field].get(key, (0, 0))
        return f"{(s + 1) / (n + 2):.3f} (n={n}{'; no observations' if not n else ''})"

    beliefs, alternatives = [], []
    for node in NODE:
        for a, b in (("A", "B"), ("B", "A")):
            source, target = f"{a}_{node}", f"{b}_{node}"
            mapping = f"{source} -> {target}, same {node} credential and required fields"
            beliefs.append(f"{source}: episode recovery for {error}: {probability('recovery', (source, error))}; "
                           f"{mapping}, switch episode recovery: {probability('switch', (source, target))}")
            alternatives.append(mapping)
    return "\n".join(["<tool_reliability>", *beliefs, BTM_GUIDANCE, *alternatives,
                      *([BTM_RETRY] if arm != "btm_no_retry" else []),
                      BTM_CONSTRAINTS, "</tool_reliability>"])


def values(planner, view, memory="full"):
    state = Progress(view["slot"], tuple(view["tried"]), view["budget"], "diagnose" in view["actions"])
    belief = planner.belief(view, memory)
    return planner.values(state, belief, fixed=True)


def value_context(view, estimates, fit):
    return {
        "continuation": "Fixed local decision rule. Estimates are uncertain and include the chosen action.",
        "training_support": {key: fit[key] for key in ("train_A_sequences", "train_B_attempts")},
        "episode_evidence_indices": list(range(len(view["decisions"]))),
        "actions": {
            tool_name(action, view["slot"]): {
                "strict_completion_probability": round(float(v[0]), 6),
                "expected_tool_fee": round(float(v[1]), 6),
                "expected_diagnostic_fee": round(float(v[2]), 6),
            }
            for action, v in estimates.items()
        },
    }


def request_for(view, arm, settings, seed, turn, fit, history, estimates):
    public = public_view(view)
    facts = public_facts(public)
    tools = environment_tools(view, public, facts)
    system = SYSTEM
    context = {"observation": public}
    if arm.startswith("btm"):
        system += "\n" + btm_prompt(arm, history, view["history"][1]["output"]["error"])
    if arm == "memory":
        context["action_conditioned_memory"] = value_context(view, estimates, fit)
    if arm == "hybrid":
        system += "\n" + EXTRACT
        context["environment_tool_contracts"] = tools
        tools = [evidence_tool(facts)]
    return {
        "model": settings["model"], "messages": [{"role": "system", "content": system},
                                               {"role": "user", "content": encode(context)}],
        "tools": tools, "temperature": settings["temperature"],
        "max_tokens": settings["max_tokens"], "seed": (seed * 16 + turn + settings["seed"]),
        "parallel_tool_calls": False, "tool_choice": settings["tool_choice"],
        "timeout": settings["timeout_seconds"],
    }


def parse_call(response):
    choices = response.get("choices", [])
    if len(choices) != 1 or choices[0].get("finish_reason") == "length":
        raise DecisionFailure("protocol", "Missing or truncated model choice")
    calls = choices[0]["message"].get("tool_calls") or []
    if len(calls) != 1 or calls[0].get("type") != "function":
        raise DecisionFailure("protocol", "Expected one tool call")
    function = calls[0]["function"]
    try:
        arguments = json.loads(function["arguments"])
    except (ValueError, TypeError) as error:
        raise DecisionFailure("illegal", "Invalid JSON arguments") from error
    if not isinstance(arguments, dict):
        raise DecisionFailure("illegal", "Expected an argument object")
    return function["name"], arguments


def validate_action(view, call, facts):
    name, arguments = call
    menu = {tool_name(a, view["slot"]): a for a in view["actions"]}
    if name not in menu:
        raise DecisionFailure("illegal", "Tool unavailable")
    action = menu[name]
    required = facts["arguments"] if action in BTM_LABELS else {}
    if encode(arguments) != encode(required):
        raise DecisionFailure("illegal", "Arguments do not match the visible source receipt")
    return action


def infer_action(view, arm, call, estimates):
    expected = public_facts(public_view(view))
    if arm == "hybrid":
        name, arguments = call
        if name != "record_public_facts" or encode(arguments) != encode(expected):
            raise DecisionFailure("illegal", "Extraction disagrees with public evidence")
        action = max(estimates, key=lambda a: rank(estimates[a]))
        call = tool_name(action, view["slot"]), arguments["arguments"] if action in BTM_LABELS else {}
    return validate_action(view, call, expected)


class Requests:
    def __init__(self, client, limit):
        self.client, self.limit = client, limit
        self.count = 0

    def call(self, request, record):
        require(self.count < self.limit, "Model request budget exceeded")
        self.count += 1
        started = time.perf_counter()
        try:
            response = self.client.chat.completions.create(**request).model_dump(mode="json")
        except Exception as error:
            record.update(service_error=repr(error), latency_seconds=time.perf_counter() - started)
            raise DecisionFailure("service", "Model request failed") from error
        record.update(response=response, latency_seconds=time.perf_counter() - started)
        return parse_call(response)


def run_episode(session, arm, planner, fit, history, model, model_config, seed, max_turns):
    start = time.perf_counter()
    offset = len(session.decisions)
    views, checkpoints, requests = [session.view()], [], []
    failure = None
    while not views[-1]["done"]:
        view = views[-1]
        turn = len(checkpoints)
        require(turn < max_turns, "Recovery turn limit exceeded")
        estimates = values(planner, view) if arm in ("memory", "hybrid", "parser_control") else None
        checkpoint = {"view": public_view(view)}
        if arm in ("memory", "hybrid", "parser_control"):
            checkpoint["values"] = estimates
            checkpoint["frozen_values"] = values(planner, view, "fixed")
        checkpoints.append(checkpoint)
        try:
            if arm in ARMS:
                req = request_for(view, arm, model_config, seed, turn, fit, history, estimates)
                record = {"turn": turn, "request": req}
                requests.append(record)
                call = model.call(req, record)
                action = infer_action(view, arm, call, estimates)
            elif arm == "parser_control":
                action = infer_action(view, "hybrid", ("record_public_facts",
                                      public_facts(checkpoint["view"])), estimates)
            else:
                action = choose(arm, planner, view, fit["marginal"])
        except DecisionFailure as error:
            failure = {"kind": error.kind, "detail": str(error)}
            checkpoint["failure"] = failure
            break
        checkpoint["action"] = action
        views.append(session.act(action))
    audit = session.audit()
    require(not audit["score"]["issues"], "Independent workflow audit failed")
    return {**audit, "views": views, "checkpoints": checkpoints, "requests": requests,
            "failure": failure, "offset": offset, "wall_seconds": time.perf_counter() - start}


def metric_row(tape, row, arm):
    blocked_prefix = row["offset"] > 0
    required_nodes = 2 + int(tape.extra)
    blocked = blocked_prefix or any(not (tape.a[i] or tape.b[i]) for i in range(required_nodes))
    complete = row["score"]["legal_success"]
    failure = (row["failure"] or {}).get("kind")
    costs = row["ledger"][row["offset"]:]
    tools = len(costs)
    diagnostics = len(row["diagnostic_ledger"])
    responses = [rec.get("response", {}).get("usage") for rec in row["requests"]]
    counts_known = responses and all(u and u.get("prompt_tokens") is not None
                                     and u.get("completion_tokens") is not None for u in responses)
    return {
        "complete": int(complete), "structurally_blocked": int(blocked),
        "certified_block": int(blocked_prefix or any(len(view["tried"]) == 2 for view in row["views"])),
        "correct_stop": int(row["termination"] == "blocked_stop"),
        "premature_stop": int(row["termination"] == "premature_stop"),
        "exhausted": int(row["termination"] == "exhausted"),
        "tool_fee": float(sum(call["fee"] for call in costs)),
        "diagnostic_fee": float(row["diagnostic_fee"]),
        "tool_calls": tools, "diagnostic_calls": diagnostics,
        "redundant_tool_calls": tools - required_nodes if complete else None,
        "failed_episode_tool_fee": float(sum(call["fee"] for call in costs)) if not complete else None,
        "failed_episode_diagnostic_fee": float(row["diagnostic_fee"]) if not complete else None,
        "failed_episode_tool_calls": tools if not complete else None,
        "failed_episode_diagnostic_calls": diagnostics if not complete else None,
        "illegal": int(failure == "illegal"), "protocol": int(failure == "protocol"),
        "service": int(failure == "service"), "requests": len(row["requests"]),
        "input_tokens": sum(u["prompt_tokens"] for u in responses) if counts_known else None,
        "output_tokens": sum(u["completion_tokens"] for u in responses) if counts_known else None,
        "model_seconds": (sum(rec["latency_seconds"] for rec in row["requests"]) if arm in ARMS else None),
        "wall_seconds": row["wall_seconds"],
    }


def difference(left, right):
    """Only compare decisions at an identical checkpoint before the first divergence."""
    first = None
    for index, (a, b) in enumerate(zip(left["checkpoints"], right["checkpoints"])):
        if a["view"] != b["view"]:
            break
        if a.get("action") != b.get("action"):
            first = {"decision": index, "view": a["view"], "left": a.get("action"),
                     "right": b.get("action")}
            for key, entry in (("left", a), ("right", b)):
                if "values" in entry:
                    first[key + "_values"] = entry["values"]
                    first[key + "_frozen_values"] = entry["frozen_values"]
            break
    return first


def evaluate(tape, rows):
    metrics = {name: metric_row(tape, row, name) for name, row in rows.items()}
    comparisons = {}
    for a, b in combinations(rows, 2):
        x, y = metrics[a], metrics[b]
        comparisons[f"{a}/{b}"] = {
            "completion_delta": x["complete"] - y["complete"],
            "stop_delta": x["correct_stop"] - y["correct_stop"],
            "tool_fee_delta": x["tool_fee"] - y["tool_fee"],
            "diagnostic_fee_delta": x["diagnostic_fee"] - y["diagnostic_fee"],
            "first_disagreement": difference(rows[a], rows[b]),
        }
    return metrics, comparisons


def summarize(cases):
    groups = {}
    for cell, family, seed, metrics in cases:
        for group in (cell, cell + "/" + family, cell + "/" + family + "/" + str(seed)):
            arms = groups.setdefault(group, {})
            for arm, row in metrics.items():
                arms.setdefault(arm, []).append(row)
    report = {}
    for group, arms in groups.items():
        report[group] = {}
        for arm, rows in arms.items():
            numbers = {}
            for key in rows[0]:
                known = [row[key] for row in rows if row[key] is not None]
                numbers[key] = {"n": len(known), "total": sum(known),
                                "mean": mean(known) if known else None}
            denominator = sum(row["structurally_blocked"] for row in rows)
            numbers["correct_stop_rate"] = (sum(row["correct_stop"] for row in rows) / denominator
                                             if denominator else None)
            report[group][arm] = numbers
    return report


def condition(gate17, name):
    settings = gate17["cells"][name]
    cohort = settings["cohort"]
    return {**DEFAULTS, **gate17["cohorts"][cohort], **settings}, cohort


def planner_for(cell, fit):
    return Planner(cell["q"], fit["stay"], fit["backup"], cell["accuracy"], cell["fee"],
                   emission=fit["emission"])


def observational_history(config, gate17, model, model_config, out):
    histories = {}
    for cohort, name in config["history_cells"].items():
        cell, _ = condition(gate17, name)
        directory = out / cohort
        directory.mkdir(parents=True)
        rows = []
        for family, seed, index in product(gate17["train_families"], config["history_seeds"],
                                           range(config["history_per_family"])):
            tape = sample(cell, ("gate18-history", family, seed, index))
            row = run_episode(Workflow(cell, tape), "react", None, {}, {}, model, model_config,
                              seed, config["max_turns"])
            write(directory / f"{family}-{seed}-{index}.json", row)
            rows.append(row)
        histories[cohort] = history_summary(rows)
        print(f"Frozen {cohort} observational history ({len(rows)} episodes)", flush=True)
    return histories


def test_cases(config, gate17):
    for name in (*config["primary_cells"], "independent_stale", "blocked"):
        physical = {"independent_stale": "independent", "blocked": "unreliable_backup"}.get(name, name)
        cell, cohort = condition(gate17, physical)
        if name == "independent_stale":
            cohort = "cohort_a"
        for family, seed in product(gate17["test_families"], config["test_seeds"]):
            identity = ("gate18-blocked" if name == "blocked" else "gate18-test", family, seed, 0)
            tape = (Tape(identity, (False,) * 3, (False,) * 3, True, False)
                    if name == "blocked" else sample(cell, identity))
            yield name, cell, cohort, family, seed, tape


def evaluate_cases(config, gate17, fits, histories, model, model_config, out):
    recorded = []
    independent = {}
    out.mkdir()
    for name, cell, cohort, family, seed, tape in test_cases(config, gate17):
        fit, history = fits[cohort], histories[cohort]
        planner = planner_for(cell, fit)
        initial, rows = None, {}
        for arm in (*ARMS, *RULES):
            if name == "independent_stale" and arm in ("react", "btm_uniform", "fixed_retry", "fixed_switch"):
                rows[arm] = independent[family, seed][arm]
                continue
            session = Workflow(cell, tape)
            if name == "blocked":
                session.act("A")
                session.act("B")
                require(session.view()["actions"] == ["stop"], "Common block not certified")
            if initial is None:
                initial = session.view()
            require(initial == session.view(), "Unpaired initial view")
            rows[arm] = run_episode(session, arm, planner, fit, history, model, model_config,
                                    seed, config["max_turns"])
        require(all(row["views"][0] == initial for row in rows.values()), "Paired view mismatch")
        metrics, comparisons = evaluate(tape, rows)
        if name == "independent":
            independent[family, seed] = rows
        cross_history = {}
        if name == "independent_stale":
            for arm in (*STALE_ARMS, *RULES[2:]):
                matched = independent[family, seed][arm]
                matched_metric = metric_row(tape, matched, arm)
                cross_history[arm] = {"matched": matched_metric, "stale": metrics[arm],
                                      "first_disagreement": difference(rows[arm], matched)}
        write(out / f"{name}-{family}-{seed}.json",
              {"history": cohort, "tape": tape._asdict(), "rows": rows, "metrics": metrics,
               "comparisons": comparisons, "cross_history": cross_history})
        recorded.append((name, family, seed, metrics))
        print(f"Recorded {name}/{family}/{seed}; {model.count} model requests", flush=True)
    return recorded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    from extensions.toolmaze_diagnostic_mvp.model_adapter import MODEL_CONFIG, VLLMAgent

    config = json.loads(CONFIG.read_text())
    gate17 = json.loads(GATE17_CONFIG.read_text())
    out = args.out
    out.mkdir(parents=True, exist_ok=False)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    client = VLLMAgent(model=MODEL_CONFIG["model"], base_url=MODEL_CONFIG["base_url"])
    model = Requests(client.client.with_options(max_retries=0), config["request_limit"])
    server = model.client.models.list().model_dump(mode="json")
    write(out / "config.json", {"commit": commit, "gate18": config, "gate17": gate17,
                               "model_config": MODEL_CONFIG, "model_server": server,
                               "inference_framework": "vLLM", "vllm": version("vllm"),
                               "openai": version("openai"), "python": platform.python_version(),
                               "btm": "paper prompt reproduction, frozen posteriors"})
    try:
        witnesses(out)
        calibration = out / "calibration"
        calibration.mkdir()
        fits = calibrate(gate17, calibration, emissions=tuple(map(F, config["emissions"])))
        histories = observational_history(config, gate17, model, MODEL_CONFIG, out / "history")
        write(out / "history_summary.json", histories)
        cases = evaluate_cases(config, gate17, fits, histories, model, MODEL_CONFIG, out / "cases")
        write(out / "evaluation.json", summarize(cases))
        print(f"Finished Gate 18 with {len(cases)} paired cases and {model.count} model requests", flush=True)
    except Exception as error:
        write(out / "failure.json", {"error": repr(error), "model_requests": model.count})
        raise


if __name__ == "__main__":
    main()
