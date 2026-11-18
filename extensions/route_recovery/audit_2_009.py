"""Independent trace-based acceptance for the scoped ToolMaze tasks."""

import json
import re


FIELDS = {
    2: (
        ("user_id", "owner_id", "principal_id", "account_identifier"),
        ("account_type", "bucket_name", "account_bucket"),
        ("balance", "balance_amount", "equity_value", "account_balance"),
        ("currency", "denomination", "currency_code"),
    ),
    5: (
        ("device_id", "mesh_node", "bridge_light_id", "light_id"),
        ("power_state", "lamp_state", "bridge_state"),
        ("brightness", "level_pct", "dimmer"),
        ("color", "hue_name", "tone"),
    ),
    11: (
        ("flight_number", "flight_code", "flight_no"),
        ("departure", "dep_airport", "departure_airport"),
        ("arrival", "arr_airport", "arrival_airport"),
        ("gate", "gate_label", "checkpoint_gate"),
        ("status", "status_text", "latest_state"),
    ),
    26: (
        ("city", "city_label", "locality"),
        ("temperature_celsius", "celsius_now", "metric_temp"),
        ("condition", "sky_text", "conditions_brief"),
        ("advice_level", "advisory_level"),
    ),
}

SINK = {
    2: ("bank_balance_sheet", "broker_balance_ledger"),
    5: ("light_mesh_snapshot", "light_bridge_payload"),
    11: ("aviationstack_gate_board", "flightaware_trip_timeline"),
    26: ("weatherapi_alert_card", "visualcrossing_forecast_chip"),
}
GENERIC = "create_document_and_alert_from_data"


def canonical(number, record):
    if not isinstance(record, dict) or "error" in record:
        return None
    if number == 11 and "route_text" in record:
        route = str(record["route_text"]).split(" -> ")
        if len(route) == 2:
            record = {"departure": route[0], "arrival": route[1]} | record
    values = []
    for aliases in FIELDS[number]:
        observed = [record[key] for key in aliases if key in record]
        if not observed or observed[0] is None or observed[0] == "" or any(
            value != observed[0] for value in observed
        ):
            return None
        values.append(observed[0])
    return tuple(values)


def output_compatible(task, schema):
    fields = set(schema)
    if task.number == 11 and "route_text" in fields:
        fields |= {"departure", "arrival"}
    return all(fields.intersection(aliases) for aliases in FIELDS[task.number])


def sink_compatible(task, tool):
    return tool == GENERIC or tool in {f"archive_{name}_native" for name in SINK[task.number]}


def candidate_covers(task, cards, route):
    return (
        len(route) >= 2 and route[0] != task.failed_tool
        and output_compatible(task, cards[route[0]]["outputs"])
        and all(not sink_compatible(task, name) for name in route[:-1])
        and sink_compatible(task, route[-1])
    )


def intended_source(task, event):
    args = event["arguments"]
    source_keys = {
        2: ("user_id",), 5: ("device_id", "light_id"),
        11: ("flight_number",), 26: ("city",),
    }
    matching = any(
        str(args.get(key, "")).casefold() == task.target.casefold() for key in source_keys[task.number]
    )
    return matching and (task.number != 2 or args.get("account_type", "investment") == "investment")


def corresponds(task, output):
    fields = canonical(task.number, output)
    return (
        fields is not None and str(fields[0]).casefold() == task.target.casefold()
        and (task.number != 2 or fields[1] == "investment")
    )


def token_present(text, identifier):
    return bool(identifier and re.search(rf"(?<!\w){re.escape(str(identifier))}(?!\w)", text))


def grade(task, cards, episode):
    events = episode["events"]
    found_source = False
    found_path = False
    bound_reads = []
    writes = []
    notices = []
    bindings = {}
    source_set = {
        name for name, card in cards.items()
        if name != task.failed_tool and output_compatible(task, card["outputs"])
    }
    archive_set = {name for name in cards if sink_compatible(task, name)}
    for index, event in enumerate(events):
        tool = event["tool"]
        if tool in source_set:
            found_source = True
            if intended_source(task, event) and corresponds(task, event["output"]):
                bound_reads.append((index, canonical(task.number, event["output"])))
        if tool in archive_set:
            found_path |= found_source
        for nested in event["plugins"]:
            if nested["tool"] == "create_document":
                writes.append((index, nested))
                try:
                    content = json.loads(nested["arguments"].get("content", ""))
                except (TypeError, ValueError):
                    content = None
                actual = canonical(task.number, content)
                bindings[index] = next(
                    (read_index for read_index, value in reversed(bound_reads) if value == actual), None
                )
            if nested["tool"] == "push_alert":
                notices.append((index, nested))

    business = False
    note_id = notice_id = None
    if len(writes) == len(notices) == 1:
        write_index, write = writes[0]
        notice_index, notice = notices[0]
        note_id = write["output"].get("note_id")
        notice_id = notice["output"].get("notification_id")
        business = bool(
            write_index == notice_index and bindings[write_index] is not None
            and write["arguments"].get("title") == task.title
            and notice["arguments"].get("message") == task.title
            and notice["arguments"].get("user_id") == task.recipient
            and notice["arguments"].get("priority") == task.priority
            and notice["arguments"].get("channel") == task.channel
            and note_id and notice_id
            and "error" not in write["output"] and "error" not in notice["output"]
        )

    answer = episode["answer"] or ""
    reported = token_present(answer, note_id) and token_present(answer, notice_id)
    legal = all(event["tool"] in cards and "error" not in event["output"] and not event["coerced"]
                for event in events)
    strict = business and reported and legal and episode["status"] == "answered"
    # Reasoning is auxiliary evidence, not a requirement for the strict endpoint.
    audit_text = "\n".join((episode.get("final_reasoning") or "", answer))
    checked = None
    if writes or notices:
        check_signal = re.search(r"\b(check(?:ed|ing)?|confirm(?:ed|ing)?|verif\w*|receipt\w*)\b", audit_text, re.I)
        if reported and check_signal and (task.title in audit_text or "success" in audit_text.lower()):
            checked = True
    proposed = any(token_present(answer, name) for name in source_set) and any(
        token_present(answer, name) for name in archive_set
    )
    execution = any(
        event["tool"] in archive_set and "error" not in event["output"] for event in events
    )
    bound = any(link is not None for link in bindings.values())
    if episode["status"] in {"context_budget", "request_budget", "length", "empty", "tool_budget",
                             "response_parse", "multiple_tool_calls", "service_error"}:
        blocker = episode["status"]
    elif strict:
        blocker = "none"
    elif not found_path:
        blocker = "plan_not_executed" if proposed else "path_not_observed"
    elif not legal and not bound and not execution:
        blocker = "binding" if any(
            event["output"].get("error") in ("Validation failed", "Tool not allowed") or event["coerced"]
            for event in events
        ) else "execution_or_binding_unknown"
    elif not business:
        blocker = "business" if execution else "execution_or_binding_unknown"
    elif not reported:
        blocker = "receipt_report"
    else:
        blocker = "strict_protocol"
    return {
        "path": found_path, "proposed_unexecuted": proposed and not found_path,
        "source_bound": bool(bound_reads), "payload_bound": bound,
        "archive_returned_success": execution, "business": business, "strict": strict,
        "reported": reported, "visible_check": checked, "legal": legal,
        "blocker": blocker, "payload_sources": bindings, "writes": len(writes), "notifications": len(notices),
        "note_id": note_id, "notification_id": notice_id, "full_c3": None, "external_delivery": None,
    }


def independent_audit(root, run_dir, out):
    """Rebuild action bindings from raw requests and re-execute in fresh contexts."""
    from hashlib import sha256
    from pathlib import Path
    from time import perf_counter

    from . import gate_2_009 as protocol
    from .run_2_009 import ToolSession, comparable, digest, write_json

    started = perf_counter()
    out.mkdir(exist_ok=False, parents=True)
    archived = {str(path.relative_to(run_dir)): sha256(path.read_bytes()).hexdigest()
                for path in sorted(run_dir.rglob("*")) if path.is_file()}
    freeze = json.loads((run_dir / "freeze.json").read_bytes())
    cards = freeze["contracts"]
    outcomes = []
    for task, frozen in zip(protocol.TASKS, freeze["tasks"]):
        task_path = root / "benchmarks/ToolMaze/data/perturbed_tasks/c3" / (task.identifier + ".json")
        if sha256(task_path.read_bytes()).hexdigest() != frozen["task_sha256"]:
            raise RuntimeError(f"Audit task source changed: {task.identifier}")
        for arm in (*frozen["order"], "D"):
            folder = run_dir / f"{task.number:03d}-{arm}"
            path = folder / "episode.json"
            if not path.exists():
                continue
            episode = json.loads(path.read_bytes())
            logged = folder / "events.jsonl"
            logged_events = [json.loads(line) for line in logged.read_text().splitlines()] if logged.exists() else []
            if logged_events != episode["events"]:
                raise RuntimeError(f"Tool event log mismatch: {folder.name}")
            if arm != "D":
                request_path = folder / "requests.jsonl"
                rows = [json.loads(line) for line in request_path.read_text().splitlines()] if request_path.exists() else []
            else:
                rows = []
            if len(rows) != episode["requests"] or len(rows) > protocol.MAX_REQUESTS:
                raise RuntimeError(f"SDK budget mismatch: {folder.name}")
            if len(logged_events) > protocol.MAX_CALLS:
                raise RuntimeError(f"Tool budget mismatch: {folder.name}")

            requests = []
            if rows:
                first = rows[0]["request"]
                if digest({key: first[key] for key in ("messages", "tools")}) != frozen["prompts"][arm]["sha256"]:
                    raise RuntimeError(f"Initial SDK prompt mismatch: {folder.name}")
                for index, row in enumerate(rows):
                    request = row["request"]
                    if request["seed"] != frozen["seed"] or request["temperature"] != 0 or (
                        request["max_tokens"] != protocol.MAX_OUTPUT or request["parallel_tool_calls"] is not False
                    ) or request.get("tool_choice") is not None:
                        raise RuntimeError(f"SDK settings mismatch: {folder.name}")
                    response = row.get("response") or {}
                    usage = response.get("usage") or {}
                    if usage and usage["prompt_tokens"] + protocol.MAX_OUTPUT > protocol.CONTEXT:
                        raise RuntimeError(f"Context budget mismatch: {folder.name}")
                    choices = response.get("choices") or []
                    if not choices or not choices[0].get("message") or choices[0]["finish_reason"] == "length":
                        continue
                    message = choices[0]["message"]
                    calls = message.get("tool_calls") or []
                    if len(calls) > 1:
                        continue
                    if calls:
                        function = calls[0]["function"]
                    else:
                        function = message.get("function_call")
                    if function is None:
                        continue
                    try:
                        args = json.loads(function.get("arguments") or "{}")
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(args, dict):
                        continue
                    if len(requests) == len(logged_events) and episode["status"] in {"usage_mismatch", "tool_budget"}:
                        continue
                    requests.append((function["name"], args))
                    if index + 1 < len(rows):
                        tool_reply = rows[index + 1]["request"]["messages"][-1]
                        expected_reply = logged_events[len(requests) - 1]["output"]
                        if tool_reply.get("role") != "tool" or json.loads(tool_reply["content"]) != expected_reply:
                            raise RuntimeError(f"Model tool feedback mismatch: {folder.name}")
                if episode["status"] == "answered" and rows[-1]["response"]["choices"][0]["message"].get(
                    "content"
                ) != episode["answer"]:
                    raise RuntimeError(f"Model answer mismatch: {folder.name}")
                if requests != [(e["tool"], e["arguments"]) for e in logged_events]:
                    raise RuntimeError(f"Raw SDK action mismatch: {folder.name}")

            replay = ToolSession(task, task_path)
            if comparable(replay.initial) != comparable(episode["initial"]):
                raise RuntimeError(f"Fault replay mismatch: {folder.name}")
            for original in logged_events:
                replay.call(original["tool"], original["arguments"])
                if comparable(replay.events[-1]) != comparable(original):
                    raise RuntimeError(f"Independent replay differs: {folder.name}")
            scores = grade(task, cards, episode | {"events": replay.events})
            usages = [(row.get("response") or {}).get("usage") or {} for row in rows]
            reasoning = [(usage.get("completion_tokens_details") or {}).get("reasoning_tokens") for usage in usages]
            costs = {
                "requests": len(rows), "input_tokens": sum(usage.get("prompt_tokens", 0) for usage in usages),
                "output_tokens": sum(usage.get("completion_tokens", 0) for usage in usages),
                "thinking_tokens": sum(reasoning) if all(value is not None for value in reasoning) else None,
                "model_seconds": sum(row["seconds"] for row in rows),
                "tokenizer_seconds": sum(row["tokenizer_seconds"] for row in rows),
                "top_level_calls": len(logged_events),
                "plugin_entries_including_top": sum(len(event["plugins"]) for event in logged_events),
                "nested_plugin_entries": sum(max(0, len(event["plugins"]) - 1) for event in logged_events),
                "tool_seconds": sum(event["seconds"] for event in logged_events),
                "reset_seconds": episode["reset_seconds"], "fault_seconds": episode["initial"]["seconds"],
                "search_seconds_allocated": frozen["search_seconds"] if arm in ("10", "11", "D") else 0,
                "episode_seconds": episode["seconds"], "money": None,
            }
            outcomes.append({
                "case": task.number, "arm": arm, "status": episode["status"], "scores": scores, "costs": costs,
                "calls": [event["tool"] for event in logged_events],
                "proposed_routes_cover": (
                    any(candidate_covers(task, cards, route) for route in frozen["routes"][:5])
                    if arm in ("10", "11") else None
                ),
            })
    if not all(sha256((run_dir / name).read_bytes()).hexdigest() == value for name, value in archived.items()):
        raise RuntimeError("Original run artifacts changed during audit")
    write_json(out / "audit.json", {
        "source_commit": freeze["commit"], "frozen_contracts_sha256": freeze["contracts_sha256"],
        "complete": len(outcomes) == 20, "outcomes": outcomes,
        "shared_search_seconds": sum(task["search_seconds"] for task in freeze["tasks"]),
        "preparation_seconds": freeze["preparation_seconds"],
        "replay_environment_calls": sum(row["costs"]["top_level_calls"] + 1 for row in outcomes),
        "audit_seconds": perf_counter() - started, "sha256": archived,
    })
    print(f"Independently audited {len(outcomes)} episodes", flush=True)


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    cli = argparse.ArgumentParser()
    cli.add_argument("--root", type=Path, required=True)
    cli.add_argument("--run", type=Path, required=True)
    cli.add_argument("--out", type=Path, required=True)
    opts = cli.parse_args()
    independent_audit(opts.root, opts.run, opts.out)
