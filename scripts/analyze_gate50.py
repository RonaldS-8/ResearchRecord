"""Experiment 050: apply the registered analysis to a finished run directory.

Usage: python scripts/analyze_gate50.py <results/050-lost-receipt-01>
Writes <run>/summary.json and docs/evidence/050/summary.json; reads only result.json files.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extensions.toolmaze_recovery import gate50 as g  # noqa: E402


def main(run):
    run = Path(run)
    freeze = json.loads((run / "freeze.json").read_text(encoding="utf-8"))
    results = []
    for row in freeze["plan"]:
        path = run / row["id"] / "result.json"
        if not path.exists():
            raise SystemExit(f"Missing episode {row['id']}; the registered plan is incomplete, no summary")
        r = json.loads(path.read_text(encoding="utf-8"))
        if r["protocol"] != "pass":
            raise SystemExit(f"Protocol-blocked episode {row['id']}; report it, do not summarize")
        results.append(r)
    summary = {"experiment": "050", "run": run.name, "source_commit": freeze["commit"], **g.summarize(results)}
    text = json.dumps(summary, indent=1)
    (run / "summary.json").write_text(text, encoding="utf-8")
    evidence = ROOT / "docs" / "evidence" / "050"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "summary.json").write_text(text, encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("verdict", "h_minus_btm", "h_minus_btm_bootstrap95",
                                              "btm_failure_share_duplicate_or_budget")}, indent=1))
    for arm, a in summary["arms"].items():
        print(arm, round(a["strict_weighted"], 3), {w: f"{c['k']}/{c['n']}" for w, c in a["by_world"].items()})


if __name__ == "__main__":
    main(sys.argv[1])
