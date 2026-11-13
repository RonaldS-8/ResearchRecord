"""Experiment 042 (Gate 42B) rounds. Registered in docs/experiments/042-*.md before each run.

All values are references inside the CPU environment model; none is an estimate of
what an LLM agent achieves.
"""
import argparse
from collections import defaultdict
from fractions import Fraction as Q
import json
from pathlib import Path
import subprocess

from . import autoresearch as ar
from . import autoresearch_rounds as rounds40
from . import belief
from . import multipath as mp
from . import multipath_rounds as r41

SEEDS, FEWER = range(5000, 5100), range(5000, 5060)
SIZES = (30, 100, 300, 1000, 3000)
KS = (1, 2, 3, 4, 5)
TOLERANT = ("tolerance", Q(1, 20))


def cells():
    """Existing cells only, with the number of hidden states their generator has."""
    return {"M5": (r41.fresh_cells()["M5"], 4), "M3-8": (r41.m3(8), 4), "S4b": (r41.held_cells()["S4b"], 4),
            "E": (r41.dev_cells()["E"], 2), "E_placebo": (r41.dev_cells()["E_placebo"], 2),
            "B2R-mini": (r41.b2r((Q(2, 5), Q(1, 2), Q(1, 10))), 4)}


def score(reference, policy):
    """Exact value, first-action errors and the gap between the policy's own estimate and the truth."""
    cell, got = reference.cell, defaultdict(float)
    for x, quote, weight, good, fine in reference.roots:
        completion, fee = mp.at_root(cell, policy, x, quote)
        first, w = policy(mp.View(x, quote, (), cell.left, cell.graph)), float(weight)
        got["completion"] += w * float(completion)
        got["fee"] += w * float(fee)
        got["wrong"] += w * (first not in good)
        got["wrong_material"] += w * (first not in fine)
        estimate = None
        if isinstance(policy, mp.Planner):
            _, value, values = policy.node(policy.key(x, quote), quote, (), cell.left)
            estimate = value if len(values) > 1 else None
        elif getattr(policy, "estimates", None):
            estimate = policy.estimates.get((x, quote))
        if estimate is not None:
            got["supported"] += w
            got["bias"] += w * (float(estimate[0]) - float(completion))
            got["error"] += w * abs(float(estimate[0]) - float(completion))
            got["fee_bias"] += w * (float(estimate[1]) - float(fee))
    return got


def policies(cell, true_k, rows, counts, seed, orders, names):
    """Every compared policy, all fitted on the same logged history."""
    fallback = mp.Planner(counts, cell, compare=TOLERANT)
    found = {"acv_strict": mp.Planner(counts, cell), "acv_tol0.05": fallback}
    if "learned_context_order" in names:
        found["learned_context_order"] = orders(counts, rows)
    if not any(n.startswith("belief") for n in names):
        return found, {}
    models = {k: belief.train(rows, cell, k, seed) for k in KS}
    auto = min(models.values(), key=lambda m: m.bic())
    plans = {}

    def plan(model, guard=True):
        if (id(model), guard) not in plans:
            plans[id(model), guard] = belief.BeliefPolicy(model, cell, counts, fallback, guard)
        return plans[id(model), guard]
    found.update({"belief_auto": plan(auto), "belief_auto_noguard": plan(auto, False),
                  "belief_trueK": plan(models[true_k]), "belief_K+1": plan(models[true_k + 1])})
    if true_k > 1:
        found["belief_K-1"] = plan(models[true_k - 1])
    if "belief_static" in names:
        found["belief_static"] = plan(belief.train(rows, cell, true_k, seed, transitions=False))
    return found, {"auto_k": auto.k}


def compare(train, test, true_k, logging, sizes, seeds, names, insider=False):
    reference = r41.Reference(test)
    orders = r41.learned_orders(test, TOLERANT[1])["learned_context_order"]
    table = {n: {name: defaultdict(float) for name in names} for n in sizes}
    chosen = {n: defaultdict(int) for n in sizes}
    for seed in seeds:
        rows = mp.simulate(train, logging, max(sizes), seed, insider)
        for n in sizes:
            found, notes = policies(test, true_k, rows[:n], mp.fit(rows[:n]), seed, orders, names)
            if notes:
                chosen[n][notes["auto_k"]] += 1
            for name in names:
                if name not in found:
                    continue
                got, row = score(reference, found[name]), table[n][name]
                pair = (got["completion"], got["fee"])
                best = (float(reference.best[0]), float(reference.best[1]))
                row["optimal"] += abs(pair[0] - best[0]) < 1e-9 and abs(pair[1] - best[1]) < 1e-9
                row["material_regret"] += best[0] - pair[0] >= 0.05 or (
                    abs(best[0] - pair[0]) < 0.05 and pair[1] >= best[1] * 1.05)
                row["rejected"] += bool(getattr(found[name], "rejected", False))
                for key, value in got.items():
                    row[key] += value
    count = len(seeds)

    def brief(c):
        row = {"optimal_seeds": int(c["optimal"]), "material_regret_seeds": int(c["material_regret"]),
               "mean_completion": round(c["completion"] / count, 5), "mean_fee": round(c["fee"] / count, 4),
               "wrong_first_action": round(c["wrong"] / count, 4),
               "materially_wrong_first_action": round(c["wrong_material"] / count, 4),
               "model_rejected_seeds": int(c["rejected"])}
        if c["supported"]:
            row.update({"completion_estimate_bias": round(c["bias"] / c["supported"], 5),
                        "completion_estimate_error": round(c["error"] / c["supported"], 5),
                        "fee_estimate_bias": round(c["fee_bias"] / c["supported"], 4)})
        return row
    return {"public_optimum": r41.show(reference.best), "blind_optimum_no_history": r41.show(mp.value(test, sees=())),
            "seeds": count, "auto_k_counts": {n: dict(sorted(c.items())) for n, c in chosen.items()},
            "by_size": {n: {name: brief(c) for name, c in by.items() if c} for n, by in table.items()}}


MAIN = ("acv_strict", "acv_tol0.05", "learned_context_order", "belief_auto", "belief_auto_noguard",
        "belief_trueK", "belief_K-1", "belief_K+1", "belief_static")


def round_c1(name):
    """Same-history comparison on one cell under uniform randomized logging."""
    cell, true_k = cells()[name]
    return compare(cell, cell, true_k, mp.uniform, SIZES, SEEDS, MAIN)


def round_c2(name):
    """Thinner coverage: only a share of logged steps is randomized, the rest follow the contract order."""
    cell, true_k = cells()[name]
    default = mp.priority(r41.tools(cell))
    out = {}
    for share in (0.3, 0.1):
        logging = (lambda view, rng, s=share: mp.uniform(view, rng) if rng.random() < s else default(view))
        out[str(share)] = compare(cell, cell, true_k, logging, (300, 3000), FEWER,
                                  ("acv_tol0.05", "learned_context_order", "belief_auto", "belief_trueK"))
    return out


def round_c3(name):
    """Negative controls: confounded logs and distribution shift."""
    names = ("acv_tol0.05", "belief_auto", "belief_trueK")
    hidden = r41.lift(rounds40.binary("K", rounds40.one(Q(3, 10))))
    out = {"confounded_insider_log": compare(hidden, hidden, 2, r41.insider, (1000,), FEWER, names, True),
           "uniform_log": compare(hidden, hidden, 2, mp.uniform, (1000,), FEWER, names)}
    simple = r41.lift(rounds40.cells()["A"])
    for p in (Q(9, 10), Q(3, 10), Q(1, 10)):
        test = r41.lift(rounds40.binary("A", rounds40.one(p)))
        out[f"shift_to_{p}"] = compare(simple, test, 2, mp.uniform, (1000,), FEWER, names)
    return out


ROUNDS = {"c1": round_c1, "c2": round_c2, "c3": round_c3}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--round", required=True, choices=sorted(ROUNDS))
    parser.add_argument("--cell", default="all")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], text=True).strip())
    # Exclusive creation: an earlier result, including a failed or negative one, is never overwritten.
    path = args.out / f"round{args.round}-{args.cell}.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump({"commit": commit, "uncommitted_changes": dirty, "round": args.round, "cell": args.cell,
                   "result": ROUNDS[args.round](args.cell)}, stream, indent=1, ensure_ascii=False)
    print(f"round {args.round} {args.cell} written, result sha256 {r41.digest(path)}", flush=True)


if __name__ == "__main__":
    main()
