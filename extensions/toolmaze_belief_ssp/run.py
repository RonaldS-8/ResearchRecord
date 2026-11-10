"""Cloud-only exact enumeration and native replay of Gate 7."""
import argparse
import json
import platform
import subprocess
from fractions import Fraction as F
from itertools import product
from pathlib import Path

from .enumeration import DECISIONS, Pilot, rank
from .replay import Replay, TOOL_LIMIT, verify


def write(path, data):
    with path.open("x") as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False, default=str)


def replay(prices, state, actions):
    session = Replay(state, F(1, 4), F(3, 4), F(1, 4), prices,
                     transition_draw=lambda: F(0), diagnostic_draw=lambda: F(1, 2))
    initial = session.view()
    views = [session.act(action) for action in actions]
    return session, {"initial": initial, "views": views, "events": session.events,
                     "decisions": session.decisions, "score": verify(session, session.events)}


def policy_graph(model):
    records = {}

    def visit(belief, remaining):
        key = f'{remaining}:' + ','.join(map(str, belief))
        if key in records:
            return key
        value, actions = model.optimal(belief, remaining)
        edges = {}
        if "retry" in actions:
            failure, posterior = model.failed(belief)
            edges["retry"] = []
            if belief[1]:
                edges["retry"].append((belief[1], "recovered_path"))
            if failure:
                edges["retry"].append((failure, visit(posterior, remaining - 1)))
        if "diagnose" in actions:
            edges["diagnose"] = [(signal, p, visit(b, remaining - 1))
                                 for signal, p, b in model.diagnosis(belief)]
        if "switch" in actions:
            edges["switch"] = [(F(1), "alternate_path")]
        records[key] = {"value": value, "actions": actions, "branches": edges}
        return key

    visit(model.prior, DECISIONS)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    out = parser.parse_args().out
    out.mkdir(parents=True, exist_ok=False)
    base, _ = replay({}, "T", [])
    victim = base.nodes[base.victim]
    alternate = next(base.nodes[node] for node in base.case["target"]["node_sequence"]
                     if node not in base.outputs)
    if alternate == victim:
        raise ValueError("Expected a distinct alternative entry")
    prices = {"uniform": {}, "cheap_retry": {victim: F(1, 2), alternate: F(3, 2)},
              "expensive_retry": {victim: F(3, 2), alternate: F(1, 2)}}
    write(out / "config.json", {
        "task": "C2-018", "source": base.case["source"]["path_id"],
        "target": base.case["target"]["path_id"], "input_hashes": base.case["hashes"],
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "python": platform.python_version(), "seed": None, "model": None, "inference": None,
        "hazards": ["1/4", "3/4", "1"], "accuracy": ["1/2", "3/4", "1"],
        "diagnostic_costs": ["1/4", "3/4"], "prices": prices,
        "decision_limit": DECISIONS, "tool_limit": TOOL_LIMIT,
    })
    results = []
    for label, price in prices.items():
        retry, retry_trace = replay(price, "T", ["retry"])
        switch, switch_trace = replay(price, "P", ["switch"])
        _, failed_trace = replay(price, "P", ["retry", "diagnose", "switch"])
        traces = {"retry": retry_trace, "switch": switch_trace, "failed_retry": failed_trace}
        write(out / f"replays-{label}.json", traces)
        if not all(row["score"]["legal_success"] for row in traces.values()):
            raise ValueError(f"Replay did not pass strict verification: {label}")
        if retry_trace["initial"] != switch_trace["initial"]:
            raise ValueError("Unequal initial observations")
        if max(len(retry.events), len(switch.events)) + DECISIONS > TOOL_LIMIT:
            raise ValueError("Tool budget can bind in the registered task")
        retry_price = retry.events[retry.sunk]["charge"]
        suffix = sum(e["charge"] for e in retry.events[retry.sunk + 1:])
        switch_price = sum(e["charge"] for e in switch.events[switch.sunk:])
        for hazard, accuracy, diagnostic in product(
            (F(1, 4), F(3, 4), F(1)), (F(1, 2), F(3, 4), F(1)), (F(1, 4), F(3, 4))
        ):
            model = Pilot(hazard, accuracy, diagnostic, retry_price, suffix, switch_price)
            optimum, actions = model.optimal(model.prior, DECISIONS)
            oracle, _ = model.optimal(model.prior, DECISIONS, oracle=True)
            baselines = model.baselines()
            simple = max((result[0] for result in baselines.values()), key=rank)
            if not rank(oracle) >= rank(optimum) >= rank(simple):
                raise ValueError("Policy ordering violated")
            gap = simple[1] - optimum[1] if simple[0] == optimum[0] else None
            if accuracy == F(1, 2) and optimum != model.optimal(model.prior, DECISIONS, False)[0]:
                raise ValueError("An uninformative diagnostic improved the optimum")
            row = {"prices": label, "hazard": hazard, "accuracy": accuracy,
                   "diagnostic_cost": diagnostic, "optimal": optimum, "optimal_actions": actions,
                   "oracle": oracle, "baselines": baselines, "gap": gap,
                   "no_diagnosis": model.optimal(model.prior, DECISIONS, False),
                   "no_diagnosis_baselines": model.baselines(False)}
            index = len(results)
            write(out / f"cell-{index:02}.json", {"summary": row, "optimal_graph": policy_graph(model)})
            results.append(row)
            model.optimal.cache_clear()
    qualifying = [r for r in results if r["accuracy"] == F(3, 4) and r["hazard"] < 1
                  and r["gap"] is not None and r["gap"] >= F(1, 20)]
    go = (len({r["hazard"] for r in qualifying}) == 2
          and len({r["diagnostic_cost"] for r in qualifying}) == 2
          and len({r["prices"] for r in qualifying}) >= 2)
    summary = {"cells": len(results), "qualifying": qualifying, "research_go": go,
               "positive_gap_cells": sum(r["gap"] is not None and r["gap"] > 0 for r in results),
               "max_gap": max(r["gap"] for r in results if r["gap"] is not None)}
    write(out / "evaluation.json", summary)
    print(json.dumps(summary, default=str))


if __name__ == "__main__":
    main()
