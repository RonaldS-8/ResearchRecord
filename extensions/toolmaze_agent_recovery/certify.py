"""Gate 26 holdout certification. Private fixtures never enter the Agent interface."""

import argparse
import ast
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata

from .session import DATA, ROOT, TIMEOUT, UNAVAILABLE, ExecutionEngine, Session, load_json
from .verification import ARCHIVES, EXPECTED_WRITES, bound_arguments, evaluate, task_path

COHORTS = {
    "task": ("007", "011"),
    "contract": ("016", "050", "066", "068"),
    "fault": ("089",),
}
PLUGINS = ROOT / "benchmarks/ToolMaze/tools/plugins"


class CandidateSession(Session):
    def fault_result(self, tool):
        if self.fault == "delayed" and tool == self.read_tools[0] and self.attempts[tool] <= 2:
            return TIMEOUT
        return super().fault_result(tool)


def text(value):
    normalized = unicodedata.normalize("NFKC", str(value)).casefold()
    return " " + re.sub(r"[^\w]+|_+", " ", normalized).strip() + " "


def visible(value, query):
    if isinstance(value, dict):
        return all(visible(item, query) for item in value.values())
    if isinstance(value, list):
        return all(visible(item, query) for item in value)
    if value in ("", None):
        return False
    if text(value) in text(query):
        return True
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        day = date.fromisoformat(value)
        return any(text(form) in text(query) for form in (
            f"{day.strftime('%B')} {day.day}, {day.year}",
            f"{day.day} {day.strftime('%B')} {day.year}",
        ))
    return False


def public_arguments(expected, sources, schema, query):
    unavailable = []
    for key, value in expected.items():
        spec = schema.get("properties", {}).get(key, {})
        if key not in sources and not visible(value, query) and not (
            "default" in spec and spec["default"] == value
        ):
            unavailable.append(key)
    return unavailable


def imported_plugins(tool):
    seen = set()
    pending = [tool]
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        file = PLUGINS / f"{name}.py"
        if not file.is_file():
            continue
        for node in ast.walk(ast.parse(file.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module == "tools.plugins":
                pending.extend(alias.name for alias in node.names)
    return sorted(seen)


def run_witness(task, case, reads, mode, branch, retry=0):
    session = CandidateSession(task, mode, case=case, read_tools=reads)
    document = session.engine.task_json
    path, aliases = task_path(session.template, document["valid_paths"][branch])
    known = {}
    error = None
    for node, tool, binding in path:
        if mode in {"persistent", "blocked"} and tool == reads[1]:
            primary_path, primary_aliases = task_path(session.template, document["valid_paths"][0])
            _, _, primary_binding = next(step for step in primary_path if step[1] == reads[0])
            try:
                args, sources = bound_arguments(primary_binding, document["user_input"], known, primary_aliases)
            except (KeyError, ValueError, IndexError) as exc:
                error = f"{reads[0]} has unresolved recovery arguments: {exc}"
                break
            schema = session.engine.tool_loader.get_tool_by_name(reads[0])["paradigms"]["function_call"]["spec"]["parameters"]
            if missing := public_arguments(args, sources, schema, session.public()["task"]):
                error = f"{reads[0]} has no public source for {', '.join(missing)}"
                break
            expected_failure = UNAVAILABLE if mode == "blocked" else TIMEOUT
            if session.call(reads[0], args) != expected_failure:
                error = "Registered primary fault did not occur"
                break
        definition = session.engine.tool_loader.get_tool_by_name(tool)
        if definition["category"].casefold() == "action" and tool not in ARCHIVES and tool not in EXPECTED_WRITES:
            error = f"Effect not independently covered: {tool}"
            break
        try:
            args, sources = bound_arguments(binding, document["user_input"], known, aliases)
        except (KeyError, ValueError, IndexError) as exc:
            error = f"{tool} has unresolved receipt binding: {exc}"
            break
        spec = definition["paradigms"]["function_call"]["spec"]["parameters"]
        if missing := public_arguments(args, sources, spec, session.public()["task"]):
            error = f"{tool} has no public source for {', '.join(missing)}"
            break
        response = session.call(tool, args)
        for _ in range(retry if tool == reads[0] else 0):
            if response != TIMEOUT:
                break
            response = session.call(tool, args)
        if "error" in response:
            if not (mode == "blocked" and tool == reads[1] and response == UNAVAILABLE):
                error = f"{tool} failed with a legal call"
            break
        known[node] = session.events[-1]

    result = evaluate(session, "Offline certification witness.")
    passed = result["correct_stop"] if mode == "blocked" else result["strict_success"]
    return {"passed": passed and error is None, "issue": error, "evaluation": result}


def certify(task, axis):
    p0 = DATA / "perturbed_tasks/c3" / f"C3_task_{task}_P0.json"
    document = load_json(p0)
    template_file = DATA / "templates/c3" / (document["template_id"] + ".json")
    template = load_json(template_file)
    base = ExecutionEngine(document, None)
    nodes = {n["id"]: n["tool_name"] for n in template["dag"]["nodes"]}
    paths = document["valid_paths"]
    group = template["alternative_groups"]
    if len(group) != 1 or len(paths) != 2 or len(group[0]["paths"]) != 2:
        raise ValueError(f"Unexpected native alternatives: {task}")
    entries = {p["path_id"]: nodes[p["node_ids"][0]] for p in group[0]["paths"]}
    reads = tuple(entries[path["group_choices"][0].split(":", 1)[1]] for path in paths)
    witnesses = {
        "clean_primary": ("clean", 0, 0), "clean_alternative": ("clean", 1, 0),
        "transient_retry": ("transient", 0, 1), "persistent_switch": ("persistent", 1, 0),
        "blocked_stop": ("blocked", 1, 0),
    }
    if axis == "fault":
        witnesses["heldout_delayed_retry"] = ("delayed", 0, 2)
    results = {name: run_witness(task, (base, template), reads, *settings)
               for name, settings in witnesses.items()}
    return {
        "task": task, "axis": axis, "passed_cpu": all(row["passed"] for row in results.values()),
        "reads": reads, "read_implementations": {tool: imported_plugins(tool) for tool in reads},
        "input_sha256": {path.name: sha256(path.read_bytes()).hexdigest() for path in (p0, template_file)},
        "results": results,
    }


def main(output):
    summary = {}
    for axis, tasks in COHORTS.items():
        for task in tasks:
            row = certify(task, axis)
            (output / f"c3-{task}.json").write_text(json.dumps(row, indent=2, ensure_ascii=False))
            summary[task] = {
                "axis": axis, "passed_cpu": row["passed_cpu"], "reads": row["reads"],
                "failed": {name: value["issue"] or value["evaluation"]["issues"] or value["evaluation"]["remaining"]
                           for name, value in row["results"].items() if not value["passed"]},
            }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    main(parser.parse_args().out)
