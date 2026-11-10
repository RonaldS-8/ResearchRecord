#!/usr/bin/env python3
"""Audit ToolMaze perturbed-task JSONs using Python standard library only.

Usage:
  python scripts/audit_toolmaze.py ./benchmarks/ToolMaze/data
  python scripts/audit_toolmaze.py ./benchmarks/ToolMaze/data --out ./toolmaze_audit_report.json

Reads task definitions; does not execute tools or modify the dataset.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

FILE_RE = re.compile(r"^(C[1-4]_task_\d+)_(P[0-4])\.json$", re.I)
ALL_MODES = {"P0", "P1", "P2", "P3", "P4"}


def counts(items: Counter[Any]) -> dict[str, int]:
    return dict(sorted(((str(k), v) for k, v in items.items()), key=lambda p: p[0]))


def summarize(values: list[int]) -> dict[str, float | int] | None:
    if not values:
        return None
    return {
        "n": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "mean": round(statistics.mean(values), 2),
        "max": max(values),
    }


def get_trace_paths(task: dict[str, Any]) -> list[dict[str, Any]]:
    valid_paths = task.get("valid_paths")
    if isinstance(valid_paths, list) and valid_paths:
        return [path for path in valid_paths if isinstance(path, dict)]
    return [{"path_id": "single", "execution_trace": task.get("execution_trace", []),
             "expected_result": task.get("expected_result", {})}]


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit ToolMaze task schema and fault data")
    ap.add_argument("data_root", type=Path, help="Dataset data directory (or perturbed_tasks directory)")
    ap.add_argument("--out", type=Path, default=Path("toolmaze_audit_report.json"),
                    help="Output JSON summary path (default: ./toolmaze_audit_report.json)")
    args = ap.parse_args()
    base = args.data_root.expanduser()
    source = base / "perturbed_tasks" if (base / "perturbed_tasks").is_dir() else base
    if not source.is_dir():
        ap.error(f"Directory does not exist: {source}")

    paths = sorted(p for p in source.rglob("*.json")
                   if FILE_RE.fullmatch(p.name) and ".cache" not in p.parts)
    if not paths:
        ap.error(f"No files matching C[1-4]_task_NNN_P[0-4].json in {source}")

    categories: Counter[str] = Counter()
    modes: Counter[str] = Counter()
    cat_modes: dict[str, Counter[str]] = defaultdict(Counter)
    domains: Counter[str] = Counter()
    top_fields: Counter[str] = Counter()
    path_fields: Counter[str] = Counter()
    trace_fields: Counter[str] = Counter()
    corruption: Counter[str] = Counter()
    perturb_status: Counter[str] = Counter()
    size_steps: dict[str, list[int]] = defaultdict(list)
    path_counts: dict[str, list[int]] = defaultdict(list)
    perturbed_steps: dict[str, list[int]] = defaultdict(list)
    pair_modes: dict[str, set[str]] = defaultdict(set)
    path_examples: dict[str, str] = {}
    faults_examples: dict[str, str] = {}
    issues: list[dict[str, str]] = []
    json_errors: list[dict[str, str]] = []
    valid_file_count = 0
    file_sizes: list[int] = []
    has_reference = 0
    has_expected = 0
    has_alternative = 0
    flagged_files = 0
    flagged_steps = 0
    fault_with_error_message = 0
    fault_with_output_error = 0
    fault_with_status_success = 0
    fault_with_status_error = 0
    traces_total = 0
    steps_total = 0
    expected_total = 0

    for path in paths:
        match = FILE_RE.fullmatch(path.name)
        assert match is not None
        filename_task_id, filename_mode = match.groups()
        rel = str(path.relative_to(source))
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict):
                raise ValueError("root JSON is not object")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            json_errors.append({"file": rel, "error": str(exc)[:300]})
            continue

        valid_file_count += 1
        file_sizes.append(path.stat().st_size)
        cat = str(doc.get("complexity", "MISSING")).upper()
        mode = str(doc.get("perturbation_mode", "MISSING")).upper()
        categories[cat] += 1
        modes[mode] += 1
        cat_modes[cat][mode] += 1
        pair_modes[str(doc.get("task_id", filename_task_id))].add(mode)
        top_fields.update(doc.keys())
        for domain in doc.get("domains", []) or []:
            domains[str(domain)] += 1
        if "corruption_type" in doc:
            corruption[str(doc["corruption_type"])] += 1
        if doc.get("alternative_tools"):
            has_alternative += 1
        if str(doc.get("task_id", "")) != filename_task_id:
            issues.append({"file": rel, "issue": "task_id differs from filename"})
        if cat != filename_task_id.split("_", 1)[0].upper():
            issues.append({"file": rel, "issue": "complexity differs from filename"})
        if mode != filename_mode.upper():
            issues.append({"file": rel, "issue": "perturbation_mode differs from filename"})

        trace_paths = get_trace_paths(doc)
        path_counts[cat].append(len(trace_paths))
        if doc.get("valid_paths"):
            path_examples.setdefault(cat, rel)
        num_fault = 0
        steps_this_file = 0
        expected_any = False
        reference_any = False
        for vp in trace_paths:
            path_fields.update(vp.keys())
            trace = vp.get("execution_trace")
            if isinstance(trace, list) and trace:
                reference_any = True
                traces_total += 1
                steps_this_file += len(trace)
                steps_total += len(trace)
                for step in trace:
                    if not isinstance(step, dict):
                        continue
                    trace_fields.update(step.keys())
                    if step.get("is_perturbed") is True:
                        num_fault += 1
                        flagged_steps += 1
                        perturb_status[str(step.get("status", "MISSING"))] += 1
                        if step.get("status") == "success":
                            fault_with_status_success += 1
                        if step.get("status") == "error":
                            fault_with_status_error += 1
                        if "error_message" in step:
                            fault_with_error_message += 1
                        if isinstance(step.get("output"), dict) and "error" in step["output"]:
                            fault_with_output_error += 1
            expected = vp.get("expected_result", {})
            if isinstance(expected, dict) and "tool_calls" in expected:
                expected_any = True
                if isinstance(expected["tool_calls"], list):
                    expected_total += len(expected["tool_calls"])

        size_steps[cat].append(steps_this_file)
        perturbed_steps[mode].append(num_fault)
        if reference_any:
            has_reference += 1
        if expected_any:
            has_expected += 1
        if num_fault:
            flagged_files += 1
            faults_examples.setdefault(mode, rel)
        if mode != "P0" and num_fault == 0:
            issues.append({"file": rel, "issue": "fault mode but no is_perturbed in reference trace"})
        if mode == "P0" and num_fault:
            issues.append({"file": rel, "issue": "P0 contains is_perturbed=true"})

    incomplete_pairs = [
        {"task_id": task_id, "modes_present": sorted(ms), "modes_missing": sorted(ALL_MODES - ms)}
        for task_id, ms in sorted(pair_modes.items()) if ms != ALL_MODES
    ]

    report = {
        "directory": str(source.resolve()),
        "matched_filename_count": len(paths),
        "valid_json_count": valid_file_count,
        "invalid_json_count": len(json_errors),
        "invalid_json_examples": json_errors[:30],
        "file_bytes": summarize(file_sizes),
        "complexity_counts": counts(categories),
        "mode_counts": counts(modes),
        "complexity_x_mode": {k: counts(v) for k, v in sorted(cat_modes.items())},
        "unique_task_ids": len(pair_modes),
        "task_ids_with_incomplete_mode_pairs": len(incomplete_pairs),
        "incomplete_mode_pair_examples": incomplete_pairs[:25],
        "domains": counts(domains),
        "top_level_field_presence_counts": counts(top_fields),
        "path_field_presence_counts": counts(path_fields),
        "trace_step_field_presence_counts": counts(trace_fields),
        "corruption_types": counts(corruption),
        "path_count_per_file": {k: summarize(v) for k, v in sorted(path_counts.items())},
        "reference_steps_per_file": {k: summarize(v) for k, v in sorted(size_steps.items())},
        "perturbed_steps_per_file": {k: summarize(v) for k, v in sorted(perturbed_steps.items())},
        "files_with_reference_trace": has_reference,
        "files_with_expected_result": has_expected,
        "files_with_alternative_tools": has_alternative,
        "reference_trace_instances": traces_total,
        "reference_trace_total_steps": steps_total,
        "reference_expected_total_calls": expected_total,
        "files_with_perturbed_step": flagged_files,
        "reference_perturbed_steps": flagged_steps,
        "perturbed_status_counts": counts(perturb_status),
        "perturbed_steps_with_error_message": fault_with_error_message,
        "perturbed_steps_with_output_error_key": fault_with_output_error,
        "perturbed_steps_with_status_success": fault_with_status_success,
        "perturbed_steps_with_status_error": fault_with_status_error,
        "example_multipath_files": path_examples,
        "example_perturbed_files": faults_examples,
        "issues_count": len(issues),
        "issues_examples": issues[:50],
        "interpretation_note": (
            "These are task-definition reference traces, NOT actual model inference traces. "
            "Dynamic success/pass and token usage must be obtained by running the sandbox/evaluator. "
            "Do not expose reference execution_trace, valid_paths, or expected_result to the agent."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"JSON: {valid_file_count}/{len(paths)} valid | tasks={len(pair_modes)} | incomplete mode sets={len(incomplete_pairs)}")
    print("By complexity:", counts(categories))
    print("By mode:", counts(modes))
    print("Complexity x mode:", report["complexity_x_mode"])
    print("Reference trace files:", has_reference, "/", valid_file_count)
    print("Expected result files:", has_expected, "/", valid_file_count)
    print("Alternative tools files:", has_alternative, "/", valid_file_count)
    print("Flagged fault files/steps:", flagged_files, "/", flagged_steps)
    print("Perturbed step status:", counts(perturb_status))
    print("Faults with error_message / output.error:", fault_with_error_message, "/", fault_with_output_error)
    print("Corruption types:", counts(corruption))
    print("Paths per file:", report["path_count_per_file"])
    print("Reference steps per file:", report["reference_steps_per_file"])
    print("Potential issues:", len(issues), "(see report for details)")
    print("Report saved:", args.out.resolve())


if __name__ == "__main__":
    main()
