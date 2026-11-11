"""Classify rejected calls in archived ToolMaze-Recovery episodes by the rule that rejected them.

Read-only: episode files are hashed and parsed, never rewritten, and the report goes to a new
file. Stored scores are copied, not recomputed. Needs no model, tool data or project imports.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

RULES = ("unadvertised_tool", "argument_schema", "task_scope", "business_precondition", "unclassified")
SCHEMA_DETAILS = (
    "Missing required parameter", "Parameter '", "Undeclared arguments", "Quantity must be",
    "Argument 'expires_at' must be",
)
# Wording before and after the Gate 30 contract revision.
SCOPE_DETAILS = ("authorized scope", "authorized by this task")


def illegal_rules(event):
    """The rule layers that rejected one call, from its stored public result. Not the caller's intent."""
    if not event["illegal"]:
        return ()
    result = event["result"]
    if result.get("error") == "Invalid or unavailable tool call.":
        return ("unadvertised_tool",)
    if result.get("code") == "invalid_argument":
        return ("business_precondition",)
    found = set()
    if result.get("error") == "Validation failed":
        for detail in result.get("details", ()):
            if any(text in detail for text in SCOPE_DETAILS):
                found.add("task_scope")
            elif detail.startswith(SCHEMA_DETAILS):
                found.add("argument_schema")
            else:
                found.add("unclassified")
    return tuple(rule for rule in RULES if rule in found) or ("unclassified",)


def breakdown(report):
    """Additive view of one stored episode. The stored outcome fields are copied as they are."""
    rejected = [event for event in report["events"] if event["illegal"]]
    effect_calls = {effect["call"] for effect in report.get("effects", ())}
    counts = Counter(rule for event in rejected for rule in illegal_rules(event))
    # The same answer conditions as strict completion, so this isolates the illegal-call veto.
    answer = report.get("answer")
    answered = bool(answer and answer.strip() and not answer.startswith(("Error:", "Error during execution:")))
    reports_block = answered and answer.strip().casefold().startswith("blocked:")
    return {
        "strict_success": report["strict_success"], "issues": report["issues"],
        "stored_illegal_calls": report["illegal_calls"],
        "illegal_calls": len(rejected), "count_matches_archive": report["illegal_calls"] == len(rejected),
        "by_rule": {rule: counts[rule] for rule in RULES},
        "charged_fee": sum(event["fee"] for event in rejected),
        "with_recorded_effect": sum(event["call"] in effect_calls for event in rejected),
        "strict_denied_only_by_illegal_calls": bool(
            rejected and answered and not reports_block and not report["issues"]),
        "calls": [{"call": event["call"], "tool": event["tool"], "fee": event["fee"],
                   "rules": list(illegal_rules(event))} for event in rejected],
    }


def episode_files(sources):
    """Every source must be a directory that holds episodes, and no episode may be reached twice."""
    files, seen = [], {}
    for source in sources:
        source = Path(source)
        if not source.is_dir():
            raise ValueError(f"Source is not an existing directory: {source}")
        found = sorted(source.rglob("episode.json"))
        if not found:
            raise ValueError(f"Source holds no episode.json: {source}")
        for path in found:
            key = path.resolve()
            if key in seen:
                raise ValueError(f"Sources overlap: {path} is also reached through {seen[key]}")
            seen[key] = source
            files.append(path)
    return files


def audit(sources):
    episodes = []
    for path in episode_files(sources):
        raw = path.read_bytes()
        config = path.with_name("config.json")
        labels = json.loads(config.read_text()) if config.is_file() else {}
        episodes.append({
            "episode": path.as_posix(), "sha256": sha256(raw).hexdigest(),
            **{key: labels.get(key) for key in ("task", "fault", "arm", "start_mode", "seed", "commit")},
            **breakdown(json.loads(raw)),
        })
    return {
        "rules": list(RULES), "sources": [Path(source).as_posix() for source in sources],
        "summary": {
            "episodes": len(episodes),
            "episodes_with_illegal_calls": sum(bool(row["illegal_calls"]) for row in episodes),
            "illegal_calls": sum(row["illegal_calls"] for row in episodes),
            "by_rule": {rule: sum(row["by_rule"][rule] for row in episodes) for rule in RULES},
            "charged_fee": sum(row["charged_fee"] for row in episodes),
            "with_recorded_effect": sum(row["with_recorded_effect"] for row in episodes),
            "strict_denied_only_by_illegal_calls": sum(
                row["strict_denied_only_by_illegal_calls"] for row in episodes),
            "count_mismatches": sum(not row["count_matches_archive"] for row in episodes),
        },
        "episodes": episodes,
    }


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="+", type=Path, help="Result directories holding episode.json files.")
    parser.add_argument("--out", type=Path, required=True, help="New report file. Must not exist.")
    args = parser.parse_args(arguments)
    if args.out.exists():
        parser.error(f"Report file already exists: {args.out}")
    try:
        report = audit(args.sources)
    except ValueError as problem:
        parser.error(str(problem))  # Exit status 2 and no report, never an empty audit.
    with args.out.open("x") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    main()
