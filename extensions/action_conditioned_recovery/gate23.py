"""Paired Qwen recovery pilot on the frozen Gate 22 contract."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
from hashlib import sha256
from importlib.metadata import version
from itertools import product
from pathlib import Path
import platform
from statistics import mean
import subprocess
import time

from . import gate21, gate22
from .gate18 import BTM_CONSTRAINTS, BTM_GUIDANCE, BTM_RETRY, DecisionFailure, Requests, encode, spec
from .gate19 import (EXTRACT, EXTRACT_PROMPT, OUTCOMES, ROUTES, SELECT, SELECT_PROMPT, checkpoint,
                     expected_evidence, read, server_model)
from .run import require
from .workflow21 import ACQUIRE, Preparation, World, Workflow, binding, execute_action, tool_name

CONFIG = Path(__file__).with_suffix(".json")
ARMS = ("no_history", "btm", "memory", "hybrid", "btm_retry", "btm_full")
RULES = ("best_fixed", "recent_feedback", "full_history_threshold", "full_planning", "parser_control")
COMMON = """Recover the interrupted task. Prefer strict completion, then lower combined tool and
diagnostic fees among equally reliable paths. Use the current legal menu and actual receipts.
A is the primary acquisition interface, B is a backup on a potentially shared gateway, and C is
an independent external backup. Each acquisition interface has at most one recovery attempt.
A and B can issue a native credential. B can issue a short credential for a portable request,
which must be verified before native registration. C issues an external credential, which requires
external registration. The preparation receipt includes a noisy quality observation. A paid
diagnosis is separate and only supplies evidence, never a credential. Use the current menu after
each action. Check the credential scope and all fields against actual receipts before writing.
Registration commits the task. Stop when all acquisition routes have failed. The runtime binds
tool arguments from receipts. Do not provide arguments to environment tools."""
FORMAT = "Return the requested result."


def public_view(view):
    observations = []
    for action, success, credential in view["observations"]:
        outcome = ("positive" if success else "negative") if action in ("prepare", "diagnose") else (
            "success" if success else "failure")
        observations.append({"tool": tool_name(action), "outcome": outcome, "credential_kind": credential or None,
                             "extra_verification": credential == "short" if credential else None})
    return {"task": view["task"], "tool_history": view["history"], "observations": observations,
            "available_tools": {tool_name(a): view["quotes"][a] for a in view["actions"]},
            "execution_budget": view["progress"].budget, "diagnostic_accuracy": view["diagnostic_accuracy"]}


def btm_history(rows, error):
    counts = {tuple(row["key"]): row for row in rows}

    def entry(key):
        row = counts.get(key, {})
        return [row.get("n", 0), round(float(F(row.get("posterior", "1/2"))), 6)]
    return {
        "target": "Final strict task recovery after an observed key under the training policy",
        "fields": ["historical_episodes", "posterior_recovery"],
        "tool_error": {tool_name(a): {error: entry(("recovery", a))} for a in ACQUIRE},
        "switch": {tool_name(a): {tool_name(b): entry(("switch", a, b)) for b in ACQUIRE if a != b}
                   for a in ACQUIRE},
    }


def memory_history(view, group):
    progress, observations = view["progress"], view["observations"]
    values = group["values"](progress, observations)
    return {
        "target": "Strict task completion and expected fees after this action under the fixed local continuation",
        "fields": ["completion_probability", "tool_fee", "diagnostic_fee", "historical_attempts"],
        "actions": {tool_name(action): [*(round(float(x), 6) for x in value[:3]),
                                       group["contexts"][(*gate22.support_key(progress, observations), action)]]
                    for action, value in values.items()},
    }


def request_for(view, arm, settings, seed, turn, group, btm, count_tokens):
    public = public_view(view)
    base = COMMON + "\n" + (EXTRACT_PROMPT if arm == "hybrid" else SELECT_PROMPT)
    extra, stats = "", {}
    if arm in ("btm", "btm_retry", "btm_full"):
        stats = btm
    elif arm == "memory":
        stats = memory_history(view, group)
    if arm == "btm_retry":
        extra = BTM_RETRY
    if arm == "btm_full":
        extra = "\n".join((
            "<tool_reliability>", encode(stats), BTM_GUIDANCE,
            "Alternatives at acquisition: A to B or C, B to A or C, C to A or B. Native, short, and "
            "external credentials follow the different registration paths specified above.",
            BTM_RETRY, BTM_CONSTRAINTS, "</tool_reliability>",
        ))
    if arm == "hybrid":
        name = EXTRACT
        properties = {"observation_index": {"type": "integer", "minimum": -1},
                      "outcome": {"type": "string", "enum": list(OUTCOMES)},
                      "route": {"type": "string", "enum": list(ROUTES)}}
    else:
        name = SELECT
        properties = {"action": {"type": "string", "enum": list(public["available_tools"])}}
    tools = [spec(name, FORMAT, properties)]
    user = {"observation": public, "history": {} if arm == "btm_full" else stats}
    parts = {
        "common": count_tokens(COMMON),
        "arm_instructions": count_tokens(base.removeprefix(COMMON)),
        "additional_system": count_tokens(extra.replace(encode(stats), "", 1) if arm == "btm_full" else extra),
        "dynamic_history": count_tokens(encode(stats)) if stats else 0,
        "public_observation": count_tokens(encode(public)),
        "schema": count_tokens(encode(tools)),
    }
    request = {
        "model": settings["model"], "messages": [{"role": "system", "content": base + ("\n" + extra if extra else "")},
                                                {"role": "user", "content": encode(user)}],
        "tools": tools, "tool_choice": {"type": "function", "function": {"name": name}},
        "parallel_tool_calls": False, "temperature": settings["temperature"],
        "seed": 16 * seed + turn + settings["seed"], "max_tokens": settings["max_tokens"],
        "timeout": settings["timeout_seconds"],
    }
    return request, parts


def selected(view, call, arm, group):
    name, arguments = call
    if arm == "hybrid":
        if name != EXTRACT or encode(arguments) != encode(expected_evidence(public_view(view))):
            raise DecisionFailure("illegal", "Evidence extraction disagrees with public observation")
        history = view["observations"]
        last = history[-1]._replace(success=arguments["outcome"] in ("positive", "success"))
        return group["memory"](view["progress"], (*history[:-1], last))
    menu = {tool_name(a): a for a in view["actions"]}
    if name != SELECT or set(arguments) != {"action"} or not isinstance(arguments["action"], str):
        raise DecisionFailure("illegal", "Expected an action identifier with no arguments")
    if arguments["action"] not in menu:
        raise DecisionFailure("illegal", "Unavailable action")
    return menu[arguments["action"]]


def episode(session, arm, model, settings, config, seed, group, btm, tokenizer):
    started = time.perf_counter()
    requests, checks = [], []
    offsets = (len(session.ledger), len(session.diagnostics))
    failure = None
    while not session.state.terminal:
        view = session.view()
        check = {"view": public_view(view)}
        if len(requests) == config["max_turns"]:
            failure = {"kind": "budget", "detail": "Model turn limit"}
            break
        request, lengths = request_for(view, arm, settings, seed, len(requests), group, btm, tokenizer)
        record = {"turn": len(requests), "request": request, "prompt_components": lengths}
        requests.append(record)
        checks.append(check)
        try:
            call = model.call(request, record)
            action = selected(view, call, arm, group)
            check.update(action=action, binding=binding(view, action), parsed=call)
            execute_action(session, action)
        except DecisionFailure as error:
            failure = {"kind": error.kind, "detail": str(error)}
            break
    row = session.audit()
    require(not row["score"]["issues"], "Strict workflow audit failed")
    return {**row, "checkpoints": checks, "requests": requests, "offsets": offsets, "failure": failure,
            "wall_seconds": time.perf_counter() - started}


def matched_group(fit):
    base, preparation_accuracy = fit["model"]
    model = gate22.ContextLaw(gate21.Law(*map(F, base)), F(preparation_accuracy))
    contexts = Counter({(tuple(row["failed"]), (row["prepare_signal"], row["probe_signal"]), row["action"]): row["n"]
                        for row in fit["support"]["contexts"]})
    continuation = gate21.threshold(model, "full", True)
    memory, values = gate21.action_memory(model, continuation)
    return dict(model=model, continuation=continuation, memory=memory, values=values, contexts=contexts)


def frozen_inputs(config):
    root = Path(config["history_run"])
    archived = read(root / "config.json")
    frozen, inherited = map(read, (gate22.CONFIG, gate21.CONFIG))
    require(archived["commit"] == config["history_commit"] and archived["gate22"] == frozen
            and archived["gate21_rates"] == inherited["generating_rates"] and archived["grid"] == inherited["grid"],
            "Gate 22 archive differs from its frozen configuration")
    require(set(config["test_seeds"]).isdisjoint(seed for _, seeds, _ in frozen["splits"].values() for seed in seeds),
            "Pilot seed overlaps Gate 22")
    laws = gate22.mechanism_laws(frozen, inherited)
    history = read(root / "history.json")
    inputs = {"config.json", "history.json", "validation.json"}
    groups, stats, rules = {}, {}, {}
    for cell in config["cells"]:
        rows = read(root / f"btm-{cell}.json")
        stats[cell] = rows["btm"]
        inputs.add(f"btm-{cell}.json")
        validation = []
        for scope in frozen["scopes"]:
            filename = f"validation-orders-{cell}-{scope}.json"
            inputs.add(filename)
            validation.append(read(root / filename))
        scores = {order: gate22.validation_score([row for rows in validation for row in rows["".join(order)]])
                  for order in gate21.ORDERS}
        fixed = max(scores, key=scores.get)
        groups[cell] = {}
        rules[cell] = {}
        for scope in frozen["scopes"]:
            group = matched_group(history[cell][scope]["matched"])
            groups[cell][scope] = group
            rules[cell][scope] = {
                "best_fixed": gate21.ordered(fixed),
                "recent_feedback": gate21.threshold(group["model"], "recent", True),
                "full_history_threshold": group["continuation"],
                "full_planning": gate21.planning(group["model"])[0],
                "parser_control": group["memory"],
            }
    hashes = {name: sha256((root / name).read_bytes()).hexdigest() for name in sorted(inputs)}
    return frozen, laws, groups, stats, rules, hashes


def paired_cases(config, frozen, laws):
    for (family_index, family), (seed_index, seed) in product(enumerate(config["families"]),
                                                            enumerate(config["test_seeds"])):
        target = (family_index + seed_index) % 2 == 0
        split = {"splits": {"test": [[family], [seed], config["draw_limit"]]}}
        for identity, _, prep in gate22.dataset(split, "test", "standard", laws["full"]["standard"]):
            if prep.quality == target:
                break
        else:
            raise ValueError("No legal preparation stratum within the frozen draw cap")
        for cell, scope in product(config["cells"], frozen["scopes"]):
            law = laws[cell][scope]
            for case, world, preparation in gate22.dataset(split, "test", scope, law):
                if case == identity:
                    require(preparation.quality == target, "Paired preparation changed")
                    yield (cell, scope, *case), law, world, preparation
                    break


def smoke_session(fixture):
    if fixture == "verify":
        world, prefix = World((False, True, False), True, True), ("A", "C", "diagnose")
    else:
        world, prefix = World((False, False, False), False, False), ("A", "B", "C")
    session = Workflow("publish", world, F(4, 5), preparation=Preparation("portable", fixture == "verify", F(4, 5)))
    for action in prefix:
        execute_action(session, action)
    return session


def token_usage(row, config):
    totals = [0, 0]
    for request in row.get("requests", ()):
        usage = request.get("response", {}).get("usage")
        if not usage:
            return None, None
        prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
        require(type(prompt) is int and type(completion) is int and prompt > 0 and completion >= 0
                and prompt + completion == usage["total_tokens"] <= config["max_model_len"],
                "Invalid server token accounting")
        totals[0] += prompt
        totals[1] += completion
    return tuple(totals)


def metric(row, config):
    values = gate21.metrics(row)
    prompt, completion = token_usage(row, config)
    requests = row.get("requests", ())
    price = config["usd_per_million"]
    dollars = ((F(price["input"]) * prompt + F(price["output"]) * completion) / 1_000_000
               if prompt is not None else None)
    kind = (row.get("failure") or {}).get("kind")
    return {**values, "environment_fee": values["tool_fee"] + values["diagnostic_fee"],
            "requests": len(requests), "input_tokens": prompt, "output_tokens": completion,
            "total_tokens": prompt + completion if prompt is not None else None,
            "model_usd": dollars, "model_seconds": sum(r["latency_seconds"] for r in requests),
            "wall_seconds": row["wall_seconds"], "illegal": int(kind == "illegal"),
            "protocol": int(kind == "protocol"), "service": int(kind == "service"),
            "model_budget": int(kind == "budget"),
            **{f"prompt_component_{key}": sum(r["prompt_components"][key] for r in requests)
               for key in ("common", "arm_instructions", "additional_system", "dynamic_history",
                           "public_observation", "schema")}}


def disagreement(left, right):
    for turn, (a, b) in enumerate(zip(left["checkpoints"], right["checkpoints"])):
        require(a["view"] == b["view"], "Public state differs before first decision divergence")
        if a.get("action") != b.get("action"):
            return {"turn": turn, "view": a["view"], "btm": a.get("action"), "candidate": b.get("action"),
                    "both_legal": "action" in a and "action" in b}
    return None


def mean_metrics(rows):
    if not rows:
        return {"n": 0, "fields": {}}
    fields = {}
    for key in rows[0]:
        known = [row[key] for row in rows if row[key] is not None]
        fields[key] = {"n": len(known), "total": sum(known), "mean": mean(known) if known else None}
    return {"n": len(rows), "fields": fields}


def paired_summary(pairs, config):
    if not pairs:
        return {"n": 0}
    baseline, candidate, deltas, savings = {}, {}, {}, {}
    for key in pairs[0][0]:
        valid = [(a[key], b[key]) for a, b in pairs if a[key] is not None and b[key] is not None]
        if valid:
            baseline[key], candidate[key] = map(mean, zip(*valid))
            deltas[key] = {"n": len(valid), "mean": candidate[key] - baseline[key]}
            if baseline[key]:
                savings[key] = (baseline[key] - candidate[key]) / baseline[key]
    priced = [(b["model_usd"] - a["model_usd"], b["environment_fee"] - a["environment_fee"])
              for a, b in pairs if a["model_usd"] is not None and b["model_usd"] is not None]
    scenario = {"n": len(priced)}
    if priced:
        model, environment = map(mean, zip(*priced))
        root = -model / environment if environment else None
        scenario.update(delta_model_usd=model, delta_environment_units=environment,
                        positive_break_even_usd_per_unit=root if root is not None and root > 0 else None,
                        cheaper_side=("below" if environment > 0 else "above") if root is not None and root > 0
                        else None,
                        deltas_usd={k: model + F(k) * environment for k in config["tool_unit_usd"]})
    return {"n": len(pairs), "btm_means": baseline, "candidate_means": candidate, "deltas": deltas,
            "savings_fraction": savings, "usd_scenarios": scenario}


def summarize(cases, config):
    strata = defaultdict(list)
    for case in cases:
        cell, scope, family, seed, _ = case["identity"]
        for label in ("all", cell, scope, family, str(seed), f"preparation/{case['preparation'][1]}"):
            strata[label].append(case)
    summary = {}
    for label, batch in strata.items():
        arms, comparisons = {}, {}
        for arm in batch[0]["metrics"]:
            values = [case["metrics"][arm] for case in batch]
            denominator = sum(case["blocked"] for case in batch)
            arms[arm] = {"all": mean_metrics(values),
                         "successful": mean_metrics([row for row in values if row["complete"]]),
                         "failed": mean_metrics([row for row in values if not row["complete"]]),
                         "correct_stops": mean_metrics([row for row in values if row["correct_stop"]]),
                         "incorrect_failures": mean_metrics([row for row in values
                                                             if not row["complete"] and not row["correct_stop"]]),
                         "structurally_blocked": denominator,
                         "correct_stop_rate": (sum(row["correct_stop"] for row in values) / denominator
                                               if denominator else None)}
            if arm == "btm":
                continue
            pairs = [(case["metrics"]["btm"], case["metrics"][arm]) for case in batch]
            comparisons[arm] = {"all": paired_summary(pairs, config),
                                "joint_success": paired_summary([(a, b) for a, b in pairs
                                                                 if a["complete"] and b["complete"]], config),
                                "completion_wins": sum(b["complete"] > a["complete"] for a, b in pairs),
                                "completion_losses": sum(b["complete"] < a["complete"] for a, b in pairs)}
        summary[label] = {"arms": arms, "vs_btm": comparisons}
    return summary


def smoke(model, settings, config, group, btm, tokenize, out):
    outcomes = []
    for fixture in ("verify", "blocked"):
        for arm in ARMS:
            row = episode(smoke_session(fixture), arm, model, settings, config, config["smoke_seed"],
                          group, btm, tokenize)
            checkpoint(out / f"smoke-{fixture}-{arm}.json", row)
            expected = "complete" if fixture == "verify" else "blocked_stop"
            passed = (row["termination"] == expected and not row["failure"] and
                      all(value is not None and value > 0 for value in token_usage(row, config)))
            outcomes.append({"fixture": fixture, "arm": arm, "passed": passed})
            print(f"Acceptance {fixture}/{arm}: {passed}; requests {model.count}", flush=True)
    checkpoint(out / "smoke.json", outcomes)
    require(all(row["passed"] for row in outcomes), "Model acceptance failed; paired run halted")


def run(out):
    from transformers import AutoTokenizer
    from extensions.toolmaze_diagnostic_mvp.model_adapter import MODEL_CONFIG, VLLMAgent

    config = read(CONFIG)
    frozen, laws, groups, histories, rules, hashes = frozen_inputs(config)
    cases = list(paired_cases(config, frozen, laws))
    require(len(cases) == 16 and len(ARMS) * (len(cases) + 2) * config["max_turns"] == config["request_limit"],
            "Frozen trial size differs")
    require(version("vllm") == config["vllm"], "vLLM version differs")
    client = VLLMAgent(model=MODEL_CONFIG["model"], base_url=MODEL_CONFIG["base_url"]).client.with_options(max_retries=0)
    model = Requests(client, config["request_limit"])
    server = client.models.list().model_dump(mode="json")
    _, root_name, length = server_model(server, MODEL_CONFIG["model"])
    root = Path(root_name)
    expected_root = Path("models", MODEL_CONFIG["model"]).resolve()
    require(root.resolve() == expected_root and length == config["max_model_len"], "Unexpected served model")
    metadata = root / ".cache/huggingface/download"
    files = [*root.glob("*.safetensors"), root / "config.json", root / "tokenizer.json",
             root / "tokenizer_config.json"]
    require(len(files) > 3 and all(file.is_file() for file in files), "Served model snapshot incomplete")
    revisions = {file.name: (metadata / (file.name + ".metadata")).read_text().splitlines()[0] for file in files}
    require(set(revisions.values()) == {MODEL_CONFIG["model_revision"]}, "Snapshot revision mismatch")
    tokenizer = AutoTokenizer.from_pretrained(root, local_files_only=True)

    def tokenize(value):
        return len(tokenizer.encode(value, add_special_tokens=False))

    histories = {cell: btm_history(rows, smoke_session("verify").view()["history"][1]["output"]["error"])
                 for cell, rows in histories.items()}
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    checkpoint(out / "config.json", {"commit": commit, "gate23": config, "gate22": frozen, "model": MODEL_CONFIG,
                                     "vllm": version("vllm"), "openai": version("openai"),
                                     "transformers": version("transformers"), "python": platform.python_version(),
                                     "model_server": server, "snapshot_revisions": revisions,
                                     "history_sha256": hashes})
    checkpoint(out / "cases-plan.json", [{"identity": identity, "preparation": preparation}
                                         for identity, _, _, preparation in cases])
    smoke(model, MODEL_CONFIG, config, groups["full"]["portable"], histories["full"], tokenize, out)
    rows_path, pairs_path = out / "episodes", out / "cases"
    rows_path.mkdir()
    pairs_path.mkdir()
    all_cases = []
    for index, (identity, law, world, prep) in enumerate(cases):
        cell, scope, family, seed, instance = identity
        group, stats = groups[cell][scope], histories[cell]
        name = f"{cell}-{scope}-{family}-{seed}-{instance}"
        rows = {}
        # A preregistered rotation avoids always granting one arm first access to a warm server.
        rotation = index % len(ARMS)
        for arm in ARMS[rotation:] + ARMS[:rotation]:
            session = Workflow(family, world, law.accuracy, preparation=prep)
            row = episode(session, arm, model, MODEL_CONFIG, config, seed, group, stats, tokenize)
            rows[arm] = row
            checkpoint(rows_path / f"{name}-{arm}.json", row)
            print(f"Recorded {name}/{arm}; requests {model.count}", flush=True)
        for arm in RULES:
            session = Workflow(family, world, law.accuracy, preparation=prep)
            started = time.perf_counter()
            row = gate21.replay(session, rules[cell][scope][arm])
            row["wall_seconds"] = time.perf_counter() - started
            rows[arm] = row
        initial = public_view(Workflow(family, world, law.accuracy, preparation=prep).view())
        require(all((row["checkpoints"][0]["view"] if arm in ARMS else public_view(row["checkpoints"][0]["view"]))
                    == initial for arm, row in rows.items()), "Paired initial state differs")
        comparisons = {arm: disagreement(rows["btm"], rows[arm]) for arm in ARMS if arm != "btm"}
        values = {arm: metric(row, config) for arm, row in rows.items()}
        differences = {arm: {key: (values[arm][key] - value if value is not None and values[arm][key] is not None
                                   else None) for key, value in values["btm"].items()}
                       for arm in rows if arm != "btm"}
        case = {"identity": identity, "preparation": prep, "blocked": not any(world.available), "metrics": values}
        checkpoint(pairs_path / f"{name}.json",
                   {**case, "world": world, "rows": rows, "first_disagreements": comparisons,
                    "deltas_vs_btm": differences})
        all_cases.append(case)
    checkpoint(out / "evaluation.json", summarize(all_cases, config))
    print(f"Finished Gate 23: {len(all_cases)} pairs, {model.count} requests", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    out = parser.parse_args().out
    out.mkdir(parents=True, exist_ok=False)
    try:
        run(out)
    except Exception as error:
        checkpoint(out / "failure.json", {"error": repr(error)})
        raise


if __name__ == "__main__":
    main()
