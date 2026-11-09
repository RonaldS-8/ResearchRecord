"""Controlled action-only agent comparison on the frozen Gate 18 assets."""

import argparse
from collections import Counter
from copy import deepcopy
from fractions import Fraction as F
from hashlib import sha256
from importlib.metadata import version
from itertools import product
import json
from pathlib import Path
import platform
from statistics import mean
import subprocess
import time

from .gate16 import rank
from .gate17 import CONFIG as GATE17_CONFIG, GRID
from .gate18 import (
    BTM_RETRY, CONFIG as GATE18_CONFIG, DecisionFailure, Requests, condition, encode, evaluate,
    history_summary, planner_for, public_facts, public_view, recovery_keys, spec, summarize,
    test_cases, tool_name, values,
)
from .planning17 import HALF, choose, rate, update
from .run import require, write
from .workflow17 import NODE, PRICES, Tape, Workflow

CONFIG = Path(__file__).with_name("gate19.json")
CORE = ("btm", "memory", "hybrid")
ARMS = (*CORE, "no_history", "btm_retry")
RULES = ("fixed_switch", "closed_three", "parser_control")
SELECT = "select_recovery_action"
EXTRACT = "record_recovery_evidence"
OUTCOMES = ("none", "success", "failure", "positive", "negative")
ROUTES = ("not_reported", "required", "not_required")
COMMON = """Recover the interrupted task. Prefer strict completion, then lower combined tool and
diagnostic fees among equally reliable paths. Use the current menu and actual tool returns.
At each node the primary and alternative interfaces can supply the same credential for that node.
Their credentials do not substitute for other nodes' credentials. Each interface can be attempted
once per recovery node. When a tool fails, inspect the error and consider other legal options.
A paid diagnosis yields noisy evidence only. A successful acquisition yields the credential for
registration. Registration supplies a credential and may require an additional verification node.
Check each returned credential and write result. Completion requires all revealed nodes and the
runtime's final commit. End recovery if no viable path remains. The executor binds arguments
from actual receipts and handles the final commit. Never supply tool arguments yourself."""
SELECT_PROMPT = """Use the supplied history, if any, and visible observations.
Call select_recovery_action with a single available tool name as action."""
EXTRACT_PROMPT = """Extract the latest record from the observations list. This is an evidence
request. Call record_recovery_evidence only. Use a zero-based observation_index and copy the
record's outcome. For extra_verification, map true to required, false to not_required, and null
to not_reported. If observations is empty, use -1, none, and not_reported.
Do not choose an action or supply any arguments for an environment tool."""


def read(path):
    return json.loads(path.read_text())


def expected_evidence(public):
    observations = public["observations"]
    if not observations:
        return {"observation_index": -1, "outcome": "none", "route": "not_reported"}
    latest = observations[-1]
    route = {None: "not_reported", True: "required", False: "not_required"}
    return {"observation_index": len(observations) - 1, "outcome": latest["outcome"],
            "route": route[latest["extra_verification"]]}


def verified_view(view, call):
    name, evidence = call
    if name != EXTRACT or encode(evidence) != encode(expected_evidence(public_view(view))):
        raise DecisionFailure("illegal", "Extraction disagrees with the latest public observation")
    if evidence["observation_index"] == -1:
        return view
    route = {"not_reported": None, "required": True, "not_required": False}
    decisions = view["decisions"]
    last = {**decisions[-1], "report": evidence["outcome"] in ("success", "positive"),
            "route": route[evidence["route"]]}
    return {**view, "decisions": [*decisions[:-1], last]}


def available(view):
    return {tool_name(a, view["slot"]): a for a in view["actions"]}


def selected_action(view, call):
    name, arguments = call
    if (name != SELECT or set(arguments) != {"action"} or not isinstance(arguments["action"], str)
            or arguments["action"] not in available(view)):
        raise DecisionFailure("illegal", "Expected one available action and no tool arguments")
    return available(view)[arguments["action"]]


def bind_and_execute(session, view, action):
    if action not in view["actions"] or view != session.view():
        raise DecisionFailure("illegal", "Unavailable action or stale checkpoint")
    receipt_index = public_facts(public_view(view))["receipt_index"] if action in PRICES else -1
    event_index = len(session.events)
    binding = {"action": action, "receipt_index": receipt_index}
    if action in PRICES:
        require(receipt_index >= 0, "Execution lacks a visible source receipt")
        receipt = view["history"][receipt_index]["output"]
        binding["arguments"] = {key: value for key, value in receipt.items() if key != "extra_verification"}
    next_view = session.act(action)
    if action in PRICES:
        require(session.events[event_index]["arguments"] == binding["arguments"],
                "Independent receipt binding mismatch")
    return next_view, binding


def btm_statistics(history, error):
    index = {kind: {tuple(row["key"]): row for row in rows} for kind, rows in history.items()}
    result = {"recovery": [], "switch": []}
    for node in NODE:
        for source, target in ((f"A_{node}", f"B_{node}"), (f"B_{node}", f"A_{node}")):
            for kind, key in (("recovery", (source, error)), ("switch", (source, target))):
                row = index[kind].get(key, {"successes": 0, "n": 0})
                result[kind].append({"key": key, "n": row["n"], "posterior": (row["successes"] + 1) / (row["n"] + 2)})
    return {"target": "Final strict episode completion after an observed key under the training policy",
            **result}


def action_statistics(view, planner, fit):
    return {
        "target": "Strict completion probability and expected future fees under the fixed local continuation",
        "actions": {
            tool_name(action, view["slot"]): {
                "completion_probability": round(float(prob), 6), "tool_fee": round(float(tools), 6),
                "diagnostic_fee": round(float(diag), 6),
                "same_node_training_attempts": fit["support"].get(f"{view['slot']}:{action}", 0),
            }
            for action, (prob, tools, diag) in values(planner, view).items()
        },
    }


def request_for(view, arm, settings, seed, turn, planner, fit, history):
    public = public_view(view)
    context = {"observation": public, "history": {}}
    if arm == "hybrid":
        system = COMMON + "\n" + EXTRACT_PROMPT
        function = EXTRACT
        properties = {
            "observation_index": {"type": "integer", "minimum": -1},
            "outcome": {"type": "string", "enum": list(OUTCOMES)},
            "route": {"type": "string", "enum": list(ROUTES)},
        }
    else:
        system = COMMON + "\n" + SELECT_PROMPT
        function = SELECT
        properties = {"action": {"type": "string", "enum": list(available(view))}}
        if arm in ("btm", "btm_retry"):
            context["history"] = btm_statistics(history, view["history"][1]["output"]["error"])
        if arm == "btm_retry":
            system += "\n" + BTM_RETRY
        if arm == "memory":
            context["history"] = action_statistics(view, planner, fit)
    return {
        "model": settings["model"], "messages": [{"role": "system", "content": system},
                                               {"role": "user", "content": encode(context)}],
        "tools": [spec(function, "Return the requested result.", properties)],
        "tool_choice": {"type": "function", "function": {"name": function}},
        "parallel_tool_calls": False, "temperature": settings["temperature"],
        "seed": seed * 16 + turn + settings["seed"],
        "max_tokens": settings["max_tokens"], "timeout": settings["timeout_seconds"],
    }


def replay(session, arm, planner, fit, history, model=None, settings=None, seed=0, max_turns=8):
    start = time.perf_counter()
    offset = len(session.decisions)
    views, checkpoints, requests = [session.view()], [], []
    failure = None
    while not views[-1]["done"]:
        view = views[-1]
        turn = len(checkpoints)
        require(turn < max_turns, "Recovery turn limit exceeded")
        public = public_view(view)
        checkpoint = {"view": public}
        checkpoints.append(checkpoint)
        try:
            if arm in ARMS:
                request = request_for(view, arm, settings, seed, turn, planner, fit, history)
                record = {"turn": turn, "request": request}
                requests.append(record)
                call = model.call(request, record)
                if arm != "hybrid":
                    action = selected_action(view, call)
            if arm in ("hybrid", "parser_control"):
                evidence = call if arm == "hybrid" else (EXTRACT, expected_evidence(public))
                estimates = values(planner, verified_view(view, evidence))
                checkpoint.update(evidence=evidence[1], decision_engine=True, values=estimates)
                action = max(estimates, key=lambda a: rank(estimates[a]))
            elif arm not in ARMS:
                action = choose(arm, planner, view)
            if arm == "memory":
                checkpoint["values"] = values(planner, view)
            next_view, binding = bind_and_execute(session, view, action)
            checkpoint.update(action=action, binding=binding)
            views.append(next_view)
        except DecisionFailure as error:
            failure = {"kind": error.kind, "detail": str(error)}
            checkpoint["failure"] = failure
            break
    audit = session.audit()
    require(not audit["score"]["issues"], "Independent workflow audit failed")
    return {**audit, "views": views, "checkpoints": checkpoints, "requests": requests,
            "failure": failure, "offset": offset, "wall_seconds": time.perf_counter() - start}


def conditional_likelihood(rows, stay, emission):
    likelihood = F(1)
    for row in rows:
        p = HALF
        for d in row["decisions"]:
            action, report = d["action"], d["report"]
            if action in ("A", "diagnose"):
                accuracy = emission if action == "A" else F(row["views"][0]["diagnostic_accuracy"])
                chance = rate(p, accuracy)
                likelihood *= chance if report else 1 - chance
                p = update(p, report, accuracy)
            if action in PRICES and report:
                p = rate(p, stay)
    return likelihood


def fit_history(root, gate18, gate17):
    fits, histories, sources = {}, {}, {}
    for cohort in gate18["history_cells"]:
        paths = [root / "history" / cohort / f"{family}-{seed}-{i}.json"
                 for family, seed, i in product(gate17["train_families"], gate18["history_seeds"],
                                                range(gate18["history_per_family"]))]
        rows = []
        for path in paths:
            raw = path.read_bytes()
            sources[str(path)] = sha256(raw).hexdigest()
            row = json.loads(raw)
            require(not row["score"]["issues"], "Invalid archived training trajectory")
            rows.append(row)
        support = Counter(f"{d['slot']}:{d['action']}" for row in rows for d in row["decisions"])
        backups = [d["report"] for row in rows for d in row["decisions"] if d["action"] == "B"]
        require(backups, "No observed backup outcomes in shared history")
        candidates = {pair: conditional_likelihood(rows, *pair)
                      for pair in product(GRID, map(F, gate18["emissions"]))}
        stay, emission = max(candidates, key=candidates.get)
        fits[cohort] = {
            "stay": stay, "emission": emission, "backup": F(sum(backups), len(backups)),
            "support": dict(support), "n_episodes": len(rows),
            "tied_candidates": [pair for pair, score in candidates.items()
                                if score == candidates[stay, emission]],
        }
        histories[cohort] = history_summary(rows)
    return fits, histories, sources


def validation_predictions(root, fits):
    report = {}
    for cohort, fit in fits.items():
        cases = read(root / "calibration" / f"{cohort}-validation.json")
        predictions = {"A": [], "B": []}
        for case in cases:
            arm = case["identity"][3].split(":")[1]
            if arm == "B":
                predictions["B"].append((fit["backup"], case["row"]["decisions"][0]["report"]))
                continue
            p = HALF
            for d in case["row"]["decisions"]:
                if d["action"] == "A":
                    predictions["A"].append((rate(p, fit["emission"]), d["report"]))
                    p = update(p, d["report"], fit["emission"])
                if d["action"] in PRICES and d["report"]:
                    p = rate(p, fit["stay"])
        report[cohort] = {a: {"n": len(rows), "brier": mean((float(p) - y) ** 2 for p, y in rows)}
                          for a, rows in predictions.items()}
    return report


def initial_session(cell, tape, blocked=False):
    session = Workflow(cell, tape)
    if blocked:
        session.act("A")
        session.act("B")
        require(session.view()["actions"] == ["stop"], "Common block not certified")
    return session


def binding_audit(root, cases):
    replayed = []
    for name, cell, _, family, seed, tape in cases:
        if family != "archive" or name in ("independent_stale", "blocked"):
            continue
        case = read(root / "cases" / f"{name}-{family}-{seed}.json")
        for arm, row in case["rows"].items():
            if (row["failure"] or {}).get("detail") != "Arguments do not match the visible source receipt":
                continue
            session = initial_session(cell, tape)
            view = session.view()
            require(row["views"] == [view], "Original rejection did not occur at the common first step")
            function = row["requests"][-1]["response"]["choices"][0]["message"]["tool_calls"][0]["function"]
            attempted = json.loads(function["arguments"])
            require(attempted.get("retention") == " 90d ", "Archived retention rejection differs from audit")
            action = selected_action(view, (SELECT, {"action": function["name"]}))
            _, binding = bind_and_execute(session, view, action)
            require(binding["arguments"]["retention"] == "90d", "Archive binding did not use prepared value")
            audit = session.audit()
            require(not audit["score"]["issues"], "Invalid first-step replay")
            replayed.append({"case": [name, family, seed], "arm": arm, "original_call": function,
                             "binding": binding, "first_step": audit})
    require(len(replayed) == 24, "Archived Gate 18 rejection count differs from preregistration")
    return replayed


def forecast_replays(session, planner, fit):
    rows = []
    while not session.view()["done"]:
        view = session.view()
        estimates = values(planner, view)
        for action, predicted in estimates.items():
            fork = deepcopy(session)
            tools_before, diag_before = len(fork.ledger), len(fork.diagnostics)
            bind_and_execute(fork, view, action)
            while not fork.view()["done"]:
                after = fork.view()
                bind_and_execute(fork, after, choose("local_full", planner, after))
            audit = fork.audit()
            require(not audit["score"]["issues"], "Forecast replay audit failed")
            actual = (int(audit["score"]["legal_success"]),
                      sum(row["fee"] for row in audit["ledger"][tools_before:]),
                      sum(row["fee"] for row in audit["diagnostic_ledger"][diag_before:]))
            rows.append({"view": public_view(view), "action": action,
                         "training_attempts": fit["support"].get(f"{view['slot']}:{action}", 0),
                         "predicted": predicted, "actual": actual})
        bind_and_execute(session, view, choose("fixed_switch", planner, view))
    return rows


def forecast_report(cases):
    groups = {}
    for identity, rows in cases.items():
        for row in rows:
            action = row["action"]
            coverage = ("rule" if action == "stop" else "observed" if row["training_attempts"]
                        else "public_calibration" if action == "diagnose" else "extrapolated")
            key = f"{action}/{coverage}"
            group = groups.setdefault(key, {"cases": set(), "errors": []})
            group["cases"].add(identity)
            group["errors"].append([float(p - a) for p, a in zip(row["predicted"], row["actual"])])
    return {key: {"n_cases": len(group["cases"]), "n_predictions": len(group["errors"]),
                  "brier": mean(e[0] ** 2 for e in group["errors"]),
                  "tool_mae": mean(abs(e[1]) for e in group["errors"]),
                  "diagnostic_mae": mean(abs(e[2]) for e in group["errors"]),
                  "tool_bias": mean(e[1] for e in group["errors"]),
                  "diagnostic_bias": mean(e[2] for e in group["errors"])}
            for key, group in groups.items()}


def btm_calibration(row, history):
    posterior = {kind: {tuple(item["key"]): item for item in rows} for kind, rows in history.items()}
    recovered = int(row["score"]["legal_success"])
    result = []
    for kind, keys in zip(("recovery", "switch"), recovery_keys(row)):
        for key in sorted(keys):
            item = posterior[kind].get(key, {"n": 0, "successes": 0})
            result.append({"kind": kind, "key": key, "n": item["n"], "actual": recovered,
                           "prediction": (item["successes"] + 1) / (item["n"] + 2)})
    return result


def calibration_report(rows):
    result = {}
    for kind in ("recovery", "switch"):
        matches = [row for row in rows if row["kind"] == kind]
        supported = [row for row in matches if row["n"]]
        result[kind] = {"encounters": len(matches), "supported": len(supported),
                        "supported_brier": (mean((row["prediction"] - row["actual"]) ** 2
                                                 for row in supported) if supported else None)}
    return result


def retry_adherence(row):
    eligible = []
    for i, checkpoint in enumerate(row["checkpoints"]):
        view = row["views"][i]
        last = view["history"][-1]
        if "error" not in last["output"] or last["tool"] not in available(view):
            continue
        retry = available(view)[last["tool"]]
        eligible.append({"turn": i, "retry": retry, "selected": checkpoint.get("action")})
    return eligible


def check_smoke(gate17, gate18, fits, histories, model, settings, seed, out):
    family = gate17["validation_family"]
    outcomes = []
    for blocked in (False, True):
        cell, cohort = condition(gate17, "unreliable_backup" if blocked else "dynamic")
        works = not blocked
        tape = Tape(("gate19-smoke", family, seed, int(blocked)), (works,) * 3, (works,) * 3, True, False)
        fit = fits[cohort]
        row = replay(initial_session(cell, tape, blocked), "hybrid", planner_for(cell, fit), fit,
                     histories[cohort], model, settings, seed, gate18["max_turns"])
        name = "blocked" if blocked else "multi_step"
        write(out / f"smoke-{name}.json", row)
        visited = all(step.get("decision_engine") for step in row["checkpoints"])
        passed = row["failure"] is None and visited and (
            row["termination"] == "blocked_stop" if blocked else row["score"]["legal_success"]
            and len(row["checkpoints"]) >= 2 and any(d["route"] is True for d in row["decisions"])
            and row["decisions"][-1]["slot"] == 2)
        outcomes.append({"fixture": name, "passed": passed})
        print(f"Gate 19 model acceptance {name}: {passed}", flush=True)
    write(out / "smoke.json", outcomes)
    require(all(row["passed"] for row in outcomes), "Model acceptance failed; paired evaluation not started")


def paired_run(cases, gate18, fits, histories, model, settings, out):
    recorded, matched, forecasts, btm_rows = [], {}, {}, []
    out.mkdir()
    for name, cell, cohort, family, seed, tape in cases:
        fit, history = fits[cohort], histories[cohort]
        planner = planner_for(cell, fit)
        rows = {}
        blocked, stale = name == "blocked", name == "independent_stale"
        arms = (*CORE, *RULES) if stale else (*ARMS, *RULES)
        initial = initial_session(cell, tape, blocked).view()
        for arm in arms:
            rows[arm] = replay(initial_session(cell, tape, blocked), arm, planner, fit, history,
                               model, settings, seed, gate18["max_turns"])
        if stale:
            rows["no_history"] = matched[family, seed]["no_history"]
        if name == "independent":
            matched[family, seed] = rows
        require(all(row["views"][0] == initial for row in rows.values()), "Paired initial views differ")
        metrics, comparisons = evaluate(tape, rows)
        for arm in ("no_history", "btm_retry"):
            if arm in rows:
                metrics[arm]["model_seconds"] = sum(r["latency_seconds"] for r in rows[arm]["requests"])
        identity = f"{name}-{family}-{seed}"
        calibration = btm_calibration(rows["btm"], history)
        if not stale and not blocked:
            forecasts[identity] = forecast_replays(initial_session(cell, tape), planner, fit)
            btm_rows.extend(calibration)
        write(out / f"{identity}.json", {
            "history": cohort, "tape": tape._asdict(), "rows": rows, "metrics": metrics,
            "comparisons": comparisons, "btm_calibration": calibration,
            "retry_opportunities": {arm: retry_adherence(rows[arm])
                                    for arm in ("btm", "btm_retry") if arm in rows},
        })
        recorded.append((name, family, seed, metrics))
        print(f"Recorded {identity}; {model.count} model requests", flush=True)
    return summarize(recorded), {"rows": forecasts, "errors": forecast_report(forecasts),
                                 "btm_calibration": calibration_report(btm_rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    from extensions.toolmaze_diagnostic_mvp.model_adapter import MODEL_CONFIG, VLLMAgent

    config, gate18, gate17 = map(read, (CONFIG, GATE18_CONFIG, GATE17_CONFIG))
    root, out = Path(config["history_run"]), args.out
    out.mkdir(parents=True, exist_ok=False)
    model = None
    try:
        archived = read(root / "config.json")
        require(archived["commit"] == config["history_commit"] and archived["gate18"] == gate18
                and archived["gate17"] == gate17 and archived["model_config"] == MODEL_CONFIG,
                "Frozen source configuration mismatch")
        client = VLLMAgent(model=MODEL_CONFIG["model"], base_url=MODEL_CONFIG["base_url"])
        model = Requests(client.client.with_options(max_retries=0), config["request_limit"])
        server = model.client.models.list().model_dump(mode="json")
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        write(out / "config.json", {
            "commit": commit, "gate19": config, "gate18": gate18, "gate17": gate17,
            "model_config": MODEL_CONFIG, "model_server": server, "inference_framework": "vLLM",
            "vllm": version("vllm"), "openai": version("openai"), "python": platform.python_version(),
        })
        fits, histories, sources = fit_history(root, gate18, gate17)
        write(out / "shared_history.json", {"fits": fits, "btm": histories, "sha256": sources})
        write(out / "validation.json", validation_predictions(root, fits))
        cases = list(test_cases(gate18, gate17))
        write(out / "binding_audit.json", binding_audit(root, cases))
        check_smoke(gate17, gate18, fits, histories, model, MODEL_CONFIG, config["smoke_seed"], out)
        evaluation, forecasts = paired_run(cases, gate18, fits, histories, model, MODEL_CONFIG, out / "cases")
        write(out / "forecast_replays.json", forecasts)
        write(out / "evaluation.json", evaluation)
        print(f"Finished Gate 19 with {len(cases)} paired cases and {model.count} model requests", flush=True)
    except Exception as error:
        write(out / "failure.json", {"error": repr(error), "model_requests": model.count if model else 0})
        raise


if __name__ == "__main__":
    main()
