"""Evaluator-only inventory. Never import into a policy or expose to the agent."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

import yaml

root = Path(sys.argv[1])
defs = root / "tools/definitions"
groups = {}
edges = defaultdict(set)
for category in yaml.safe_load((defs / "alternatives.yaml").read_text())["alternatives"].values():
    for group, spec in category.items():
        groups[group] = spec
        for path in spec["paths"]:
            providers = {}
            for step in path["tools"]:
                tool = step["tool_name"]
                for arg, expression in (step.get("params") or {}).items():
                    for alias, field in re.findall(r"\$(\w+)(?:\.(\w+))?", str(expression)):
                        if alias in providers:
                            edges[providers[alias], field, tool, arg].add(group)
                if step.get("output"):
                    providers[step["output"]] = tool

inventory = {}
witnesses = Counter()
task_hash = hashlib.sha256()
for folder in sorted((root / "data/tasks").iterdir()):
    used = set()
    unseen = set()
    files = sorted(folder.glob("*.json"))
    path_counts = Counter()
    for f in files:
        raw = f.read_bytes()
        task_hash.update(f.name.encode() + raw)
        task = json.loads(raw)
        paths = task.get("valid_paths", [])
        path_counts[len(paths)] += 1
        for path in paths:
            for choice in path["group_choices"]:
                group = choice.split(":")[0]
                used.add(group)
                if group not in groups:
                    unseen.add(group)
            prior = {}
            for entry in path["execution_trace"]:
                name = entry["tool_name"]
                args = entry.get("arguments", {})
                for source, field, target, arg in edges:
                    if target != name or source not in prior or arg not in args:
                        continue
                    output = prior[source]
                    if not isinstance(output, dict) or "error" in output:
                        continue
                    value = output.get(field) if field else output
                    if value is not None and (value == args[arg] or [value] == args[arg]):
                        witnesses[source, field, target, arg] += 1
                prior[name] = entry.get("output")
    inventory[folder.name] = dict(tasks=len(files), groups=len(used), outside_catalog=sorted(unseen),
                                  path_counts=path_counts)
rows = [dict(source=s, field=f, target=t, parameter=a, groups=sorted(g),
             matching_trace_values=witnesses[s,f,t,a])
        for (s,f,t,a), g in sorted(edges.items())]
print(json.dumps(dict(tasks=inventory, task_sha256=task_hash.hexdigest(), groups=len(groups),
                      edges=rows), indent=2))
