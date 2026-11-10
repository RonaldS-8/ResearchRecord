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
    for family in families:
        overlapping = [group for group in groups if group[0] & family]
        size = 1 + sum(group[1] for group in overlapping)
        merged = family.union(*(group[0] for group in overlapping))
        groups = [group for group in groups if group not in overlapping]
        groups.append((merged, size))
    return sorted((size for _, size in groups), reverse=True)


def inventory():
    rows = {}
    for complexity in ("c2", "c3", "c4"):
        files = sorted((DATA / "tasks" / complexity).glob("*.json"))
        stock = Counter()
        families = []
        for file in files:
            if file.stem in DESIGN:
                continue
            stock["candidates_after_design_exclusion"] += 1
            task = load_json(file)
            template = load_json(DATA / "templates" / complexity / f"{task['template_id']}.json")
            nodes = {node["id"]: node["tool_name"] for node in template["dag"]["nodes"]}
            entries = {nodes[path["node_ids"][0]] for group in template["alternative_groups"]
                       for path in group["paths"]}
            if entries:
                families.append(entries)
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
            "entry_tool_group_sizes": contract_components(families),
            "verified_independent_holdout": 0,
        }
    return rows


if __name__ == "__main__":
    print(json.dumps(inventory(), indent=2))
