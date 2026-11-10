"""Offline acceptance checks. Reference tasks never enter the agent request."""

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
import json
import re

from extensions.toolmaze_diagnostic_mvp.environment import resolve
from .session import UNAVAILABLE

ARCHIVES = {
    "archive_aviationstack_gate_board_native": "gate_board",
    "archive_flightaware_trip_timeline_native": "trip_timeline",
    "archive_bank_balance_sheet_native": "balance_sheet",
    "archive_broker_balance_ledger_native": "balance_ledger",
    "archive_light_mesh_snapshot_native": "mesh_snapshot",
    "archive_light_bridge_payload_native": "bridge_payload",
    "archive_visualcrossing_forecast_chip_native": "forecast_chip",
    "archive_weatherapi_alert_card_native": "alert_card",
    "archive_alpha_market_window_native": "market_window",
    "archive_polygon_market_board_native": "market_board",
    "archive_booking_stay_sheet_native": "stay_sheet",
    "archive_expedia_lodging_packet_native": "lodging_packet",
}
BALANCE_NOTICES = {
    "publish_bank_balance_sheet_native": (
        "balance_sheet", "Bank", "bucket_name", "balance_amount", "denomination", "sheet_id",
    ),
    "publish_broker_balance_ledger_native": (
        "balance_ledger", "Broker", "account_bucket", "equity_value", "currency_code", "ledger_ref",
    ),
}
EXPECTED_WRITES = {
    "publish_google_slot_ticket_native": ("push_alert",),
    "email_contact_by_name": ("send_email",),
    "schedule_meeting": ("schedule_meeting",),
    "snapshot_workspace": ("snapshot_workspace",),
    "push_alert": ("push_alert",),
    "send_email": ("send_email",),
    "create_document_and_alert": ("create_document", "push_alert"),
    **dict.fromkeys(BALANCE_NOTICES, ("push_alert",)),
}
RECEIPT_REF = re.compile(r"__slot_ref:(s\w+)(\.[\w.]+)?|\{\{\s*(s\w+)(\.[\w.]+)?\s*\}\}")


def task_path(template, path):
    nodes = {node["id"]: node["tool_name"] for node in template["dag"]["nodes"]}
    bindings = template["parameter_bindings_by_node"]
    aliases = {}
    for group in template["alternative_groups"]:
        for choice in group["paths"]:
            if f"{group['group_id']}:{choice['path_id']}" in path["group_choices"]:
                aliases[group["slot_id"]] = choice["node_ids"][-1]
    return [(node, nodes[node], bindings[node]) for node in path["node_sequence"]], aliases


def bound_arguments(bindings, user_input, prior, aliases):
    """Return expected arguments and earlier call IDs compatible with the binding."""
    outputs = {node: event["result"] for node, event in prior.items()}
    outputs.update({slot: outputs[node] for slot, node in aliases.items() if node in outputs})
    arguments, sources = {}, {}

    for name, expression in bindings.items():
        match = RECEIPT_REF.fullmatch(expression) if isinstance(expression, str) else None
        if match:
            node = match[1] or match[3]
            suffix = match[2] or match[4] or ""
            producer = aliases.get(node, node)
            sources[name] = {"call": prior[producer]["call"], "field": suffix.removeprefix(".")}
            expression = "{{ " + node + suffix + " }}"
        arguments[name] = resolve(expression, user_input, outputs)
    return arguments, sources


def matches_arguments(tool, actual, expected):
    if tool == "schedule_meeting" and "end_time" in actual:
        start, end = actual.get("start_time"), actual["end_time"]
        try:
            start_at = datetime.strptime(start, "%Y-%m-%d %H:%M")
            end_at = datetime.strptime(end, "%Y-%m-%d %H:%M")
            if end_at <= start_at:
                return False
        except (ValueError, TypeError):
            return False
        actual = {key: value for key, value in actual.items() if key != "end_time"}
    return actual == expected


def match_path(session, path):
    steps, aliases = task_path(session.template, path)
    user = session.engine.task_json["user_input"]
    prior, sources, blocked = {}, {}, set()
    for event in session.events:
        if len(prior) == len(steps):
            break
        node, tool, bindings = steps[len(prior)]
        if event["tool"] != tool or event["illegal"]:
            continue
        try:
            expected, evidence = bound_arguments(bindings, user, prior, aliases)
        except (KeyError, ValueError, TypeError, IndexError):
            continue
        if not matches_arguments(tool, event["arguments"], expected):
            continue
        if event["result"] == UNAVAILABLE and tool in session.read_tools:
            blocked.add(tool)
        if "error" not in event["result"]:
            prior[node] = event
            sources[event["call"]] = evidence
    return {"nodes": prior, "sources": sources, "blocked": sorted(blocked),
            "remaining": [tool for _, tool, _ in steps[len(prior):]]}


def write_issues(matched, effects):
    by_call = defaultdict(list)
    for effect in effects:
        by_call[effect["call"]].append(effect)
    issues = []
    for event in matched["nodes"].values():
        tool = event["tool"]
        arguments, result = event["arguments"], event["result"]
        writes = by_call.pop(event["call"], [])
        expected = ("create_document", "push_alert") if tool in ARCHIVES else EXPECTED_WRITES.get(tool, ())
        if tuple(write["operation"] for write in writes) != expected:
            issues.append(f"unexpected or missing writes at call {event['call']}")
            continue
        if tool in ARCHIVES:
            document, notice = (write["arguments"] for write in writes)
            if (json.loads(document["content"]) != arguments[ARCHIVES[tool]]
                    or document["title"] != arguments["title"]
                    or notice != {
                        "message": arguments["title"], "user_id": arguments["user_id"],
                        "priority": arguments["priority"], "channel": arguments["channel"],
                    } or result.get("status") != "archived"):
                issues.append("archive content or destination mismatch")
        elif tool in BALANCE_NOTICES:
            payload, label, account, amount, currency, reference = BALANCE_NOTICES[tool]
            data = arguments[payload]
            notice = writes[0]["arguments"]
            if (notice != {
                    "message": f"{label} balance {data[account]}: {data[amount]} {data[currency]}",
                    "user_id": arguments["user_id"], "priority": arguments["priority"],
                    "channel": arguments["channel"],
                } or result.get("status") != "published"
                    or result.get("target_user") != arguments["user_id"]
                    or result.get("account_ref") != data[reference]):
                issues.append("balance publication effect mismatch")
        elif tool == "snapshot_workspace":
            if (writes[0]["arguments"] != arguments or result.get("status") != "completed"
                    or any(result.get(key) != arguments[key] for key in ("workspace_path", "backup_name"))):
                issues.append("workspace backup effect mismatch")
        elif tool in {"push_alert", "send_email"}:
            if writes[0]["arguments"] != arguments:
                issues.append("direct notification effect mismatch")
        elif tool == "create_document_and_alert":
            document, notice = (write["arguments"] for write in writes)
            if (document["content"] != arguments["content"]
                    or document["title"] != arguments.get("title", "Untitled")
                    or document["tags"] != arguments.get("tags", [])
                    or notice != {
                        "message": document["title"], "user_id": arguments.get("user_id", "default_user"),
                        "priority": arguments.get("priority", "medium"), "channel": arguments.get("channel", "app"),
                    }):
                issues.append("document or notification effect mismatch")
        elif tool == "publish_google_slot_ticket_native":
            notice = writes[0]["arguments"]
            if (result.get("slot_ref") != arguments["slot_ticket"].get("slot_id")
                    or notice.get("user_id") != arguments["user_id"]
                    or notice.get("channel") != arguments["channel"]):
                issues.append("published slot receipt does not identify the requested ticket")
        elif tool == "email_contact_by_name":
            email = writes[0]["arguments"]
            if (email.get("subject") != arguments["subject"] or email.get("body") != arguments["body"]
                    or email.get("recipients") != result.get("recipients")
                    or result.get("resolved_name", "").casefold() != arguments["name"].casefold()):
                issues.append("email content or destination mismatch")
        elif tool == "schedule_meeting":
            if (writes[0]["arguments"] != arguments or result.get("status") != "meeting scheduled"
                    or any(result.get(key) != arguments[key] for key in ("participants", "start_time", "title"))):
                issues.append("meeting effect mismatch")
        elif tool == "get_account_balance_bank_api":
            if (any(result.get(key) != arguments.get(key) for key in ("user_id", "account_type"))
                    or not isinstance(result.get("balance"), (int, float))
                    or not result.get("currency")):
                issues.append("bank verification returned the wrong account or incomplete balance")
    if by_call:
        issues.append("extra or duplicate effects outside the matched path")
    return issues


def evaluate(session, answer):
    paths = session.engine.task_json["valid_paths"]
    candidates = [match_path(session, path) for path in paths]
    for candidate in candidates:
        candidate["issues"] = write_issues(candidate, session.effects)
        if session.task == "001":
            candidate["issues"].append("room booking request is not an actual room booking")
    best = min(candidates, key=lambda row: (len(row["remaining"]), len(row["issues"])))
    blocked = {tool for row in candidates for tool in row["blocked"]}
    illegal = sum(event["illegal"] for event in session.events)
    responded = bool(answer and answer.strip() and not answer.startswith(("Error:", "Error during execution:")))
    completed = responded and not (best["remaining"] or best["issues"] or illegal)
    correct_stop = (
        responded and blocked == set(session.read_tools) and not session.effects and not illegal
    )
    if completed:
        termination = "complete"
    elif correct_stop:
        termination = "blocked_stop"
    elif not responded:
        termination = "agent_error" if answer else "budget_exhausted"
    else:
        termination = "incomplete_stop"
    failed_calls = sum("error" in event["result"] for event in session.events)
    successful_reads = Counter(
        (event["tool"], json.dumps(event["arguments"], sort_keys=True))
        for event in session.events
        if event.get("kind") != "diagnosis" and "error" not in event["result"] and event["tool"] not in ARCHIVES
        and event["tool"] not in EXPECTED_WRITES
    )
    return deepcopy({
        "strict_success": completed, "correct_stop": correct_stop, "termination": termination,
        "remaining": best["remaining"], "issues": best["issues"], "sources": best["sources"],
        "blocked_tools": sorted(blocked), "events": session.events, "effects": session.effects,
        "tool_fee": sum(event["fee"] for event in session.events if event.get("kind") != "diagnosis"),
        "diagnostic_fee": sum(event["fee"] for event in session.events if event.get("kind") == "diagnosis"),
        "diagnostic_calls": sum(event.get("kind") == "diagnosis" for event in session.events),
        "illegal_calls": illegal,
        "failed_calls": failed_calls,
        "repeated_successful_reads": sum(count - 1 for count in successful_reads.values()),
        "extra_successful_calls": sum(
            event.get("kind") != "diagnosis" and "error" not in event["result"]
            for event in session.events
        )
        - len(best["nodes"]),
    })
