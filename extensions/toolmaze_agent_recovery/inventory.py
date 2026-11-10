"""Read-only inventory. Counts are candidate coverage, not validated holdouts."""

from collections import Counter
import json

from extensions.toolmaze_diagnostic_mvp.environment import load_json
from .session import DATA

DESIGN = {
    "C2_task_001", "C2_task_018", "C2_task_055",
    "C3_task_001", "C3_task_002", "C3_task_003",
}


def contract_components(families):
    # Shared first tools in registered alternative branches connect task families.
    # Semantic aliases and shared services still require a separate review.
    groups = []
    for task, tools in families:
        overlapping = [group for group in groups if group[0] & tools]
        tasks = {task}.union(*(group[1] for group in overlapping))
        merged = tools.union(*(group[0] for group in overlapping))
        groups = [group for group in groups if group not in overlapping]
        groups.append((merged, tasks))
    return [tasks for _, tasks in groups]


def inventory():
    rows = {}
    all_families = []
    diagnostic_candidates = []
    for complexity in ("c2", "c3", "c4"):
        files = sorted((DATA / "tasks" / complexity).glob("*.json"))
        stock = Counter()
        families = []
        for file in files:
            task = load_json(file)
            template = load_json(DATA / "templates" / complexity / f"{task['template_id']}.json")
            nodes = {node["id"]: node["tool_name"] for node in template["dag"]["nodes"]}
            entries = {nodes[path["node_ids"][0]] for group in template["alternative_groups"]
                       for path in group["paths"]}
            if entries:
                all_families.append((file.stem, entries))
            if file.stem in DESIGN:
                continue
            stock["candidates_after_design_exclusion"] += 1
            if entries:
                families.append((file.stem, entries))
            if "get_iot_device_status" in nodes.values() and any(
                name.startswith(("set_", "adjust_")) for name in nodes.values()
            ):
                diagnostic_candidates.append(file.stem)
            pairs = []
            for mode in ("P1", "P2"):
                path = DATA / "perturbed_tasks" / complexity / f"{file.stem}_{mode}.json"
                if path.is_file():
                    pairs.append(load_json(path))
            if len(pairs) == 2:
                stock["native_p1_p2_pairs"] += 1
                fault_returns = [
                    {(step["tool_name"], json.dumps(step["arguments"], sort_keys=True),
                      json.dumps(step["output"], sort_keys=True))
                     for branch in doc["valid_paths"] for step in branch["execution_trace"]
                     if step.get("is_perturbed")}
                    for doc in pairs
                ]
                if fault_returns[0] & fault_returns[1]:
                    stock["pair_has_matching_fault_tool_args_and_output"] += 1
        rows[complexity] = {
            "base_tasks": len(files), **stock,
            "pair_has_matching_fault_tool_args_and_output":
                stock["pair_has_matching_fault_tool_args_and_output"],
            "entry_tool_group_sizes": sorted(map(len, contract_components(families)), reverse=True),
            "verified_independent_holdout": 0,
        }
    components = contract_components(all_families)
    isolated = [group for group in components if group.isdisjoint(DESIGN)]
    return {
        "levels": rows,
        "cross_level_entry_tool_group_sizes": sorted(map(len, components), reverse=True),
        "candidate_groups_disjoint_from_design": sorted(map(len, isolated), reverse=True),
        "device_status_and_control_candidates": diagnostic_candidates,
    }


if __name__ == "__main__":
    print(json.dumps(inventory(), indent=2))
