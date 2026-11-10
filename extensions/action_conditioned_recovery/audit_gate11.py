"""Read existing same-key evidence and enumerate the two-step theory check."""
import argparse
from collections import defaultdict
from fractions import Fraction as F
import json
from pathlib import Path

from .mvp import values
from .run import write


def read(path):
    return json.loads(path.read_text())


def shared(groups):
    return [{"key": key, "members": sorted(members)}
            for key, members in sorted(groups.items()) if len(members) > 1]


def archive_audit(root):
    native, native_switch, controlled, c3 = (defaultdict(set) for _ in range(4))
    gate1 = root / "003-recovery-decision-20261105-01/artifacts"
    for path in sorted(gate1.glob("C2_task_*.json")):
        for case in read(path)["cases"]:
            run = case["retry_only"]
            first = run["events"][run["prefix_calls"]]
            key = first["tool"], first["output"]["error"]
            native[key].add(path.stem)
            for switch in case["switches"]:
                if switch["after_first_fault_calls"]:
                    target = switch["events"][run["prefix_calls"] + 1]["tool"]
                    native_switch[(*key, target)].add(path.stem)
    gate3 = root / "005-gate3-full-20261105-01/artifacts"
    for path in sorted(gate3.glob("*_P1_original_switch.json")):
        row = read(path)
        n = row["sunk_calls"]
        first, target = row["events"][n - 1:n + 1]
        controlled[first["tool"], "Operation unavailable", target["tool"]].add(row["task"])
    gate6 = root / "008-gate6-c3-pilot-01"
    for path in sorted(gate6.glob("C3_task_*.json")):
        for start in read(path)["rows"]:
            for runs in start["runs"].values():
                first = runs[0]["events"][len(start["prefix"]) - 1]
                c3[first["tool"], first["output"]["error"]].add(path.stem)
    return {"native_c2_candidates": shared(native), "native_c3_candidates": shared(c3),
            "native_c2_switch_candidates": shared(native_switch),
            "gate3_candidates_under_shared_error": shared(controlled)}


def feedback_costs(posteriors):
    """Enumerate all four maps from two equally likely failure reports to actions."""
    first_cost, failure = F(1), F(1, 2)
    return {
        f"{high}/{low}": first_cost + failure * (
            values(posteriors[0])[high][1] + values(posteriors[1])[low][1]
        ) / 2
        for high in ("switch", "retry_then_switch")
        for low in ("switch", "retry_then_switch")
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    write(args.out, {"archive": archive_audit(args.results),
                     "feedback": feedback_costs((F(4, 5), F(1, 5))),
                     "no_information": feedback_costs((F(1, 2), F(1, 2))),
                     "initial_switch": F(2)})


if __name__ == "__main__":
    main()
