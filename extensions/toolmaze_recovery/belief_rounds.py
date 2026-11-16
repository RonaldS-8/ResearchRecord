"""Experiment 042 (Gate 42B) rounds. Registered in docs/experiments/042-*.md before each run.

All values are references inside the CPU environment model; none is an estimate of
what an LLM agent achieves.
"""
import argparse
from collections import defaultdict
from fractions import Fraction as Q
import json
from pathlib import Path
import platform
import subprocess
import sys

from . import autoresearch as ar
from . import autoresearch_rounds as rounds40
from . import belief
from . import multipath as mp
from . import multipath_rounds as r41
from . import simple_rules

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
    # Simple-rule baselines: plain log frequencies, no planner and no model (see simple_rules.py).
    if "simple_last_feedback" in names:
        found["simple_last_feedback"] = simple_rules.LastFeedbackRule(rows)
    if "simple_diagnose_first" in names:
        found["simple_diagnose_first"] = simple_rules.LastFeedbackRule(rows, diagnose_first=True)
    notes, plans = {}, {}

    def plan(model, guard=True, floor=None, tolerance=belief.NUMERIC):
        key = (id(model), guard, floor, tolerance)
        if key not in plans:
            plans[key] = belief.BeliefPolicy(model, cell, counts, fallback, guard, tolerance=tolerance, floor=floor)
        return plans[key]
    if any(n.startswith("belief_") for n in names):
        models = {k: belief.train(rows, cell, k, seed) for k in KS}
        auto = min(models.values(), key=lambda m: m.bic())
        notes["auto_k"] = auto.k
        registered = {"belief_auto": lambda: plan(auto), "belief_auto_noguard": lambda: plan(auto, False),
                      "belief_trueK": lambda: plan(models[true_k]), "belief_K+1": lambda: plan(models[true_k + 1]),
                      "belief_K-1": lambda: plan(models[true_k - 1]),
                      "belief_static": lambda: plan(belief.train(rows, cell, true_k, seed, transitions=False))}
        found.update({n: registered[n]() for n in names if n in registered and (n != "belief_K-1" or true_k > 1)})
    if any(n.startswith("belief2") for n in names):
        # Follow-up (round c4): 300 EM iterations, the widest state count, static or with transitions by BIC.
        ks = KS if "belief2bic_tol0.05" in names else KS[-1:]
        fits = {(k, moving): belief.train(rows, cell, k, seed, moving, iterations=LONG)
                for k in ks for moving in (False, True)}
        wide = min((fits[KS[-1], moving] for moving in (False, True)), key=lambda m: m.bic())
        notes["wide_transitions"] = int(wide.transitions)
        found.update({n: plan(wide, floor=SECOND[n][0], tolerance=SECOND[n][1]) for n in names if n in SECOND})
        if "belief2bic_tol0.05" in names:
            found["belief2bic_tol0.05"] = plan(min(fits.values(), key=lambda m: m.bic()), tolerance=0.05)
    if any(n in THIRD for n in names):
        found.update(corrected(cell, rows, counts, seed, names, notes))
    return found, notes


def corrected(cell, rows, counts, seed, names, notes):
    """Round d1 (Gate 43A-R). Differences from the second version: the likelihood belongs to the returned
    parameters, the label table is read from the log, every comparison rule is order-free, and the
    fallback is the count planner under the same order-free rule. `notes` records whether the stale
    likelihood of rounds c1-c5 would have picked a different restart, structure or state count."""
    labels = belief.logged_labels(rows)
    starts = {(k, moving): [belief.fit(rows, cell, k, seed * 1000 + r, moving, LONG, labels, True) for r in range(2)]
              for k in KS for moving in (False, True)}

    def pick(by):
        fits = {key: max(group, key=by) for key, group in starts.items()}
        wide = min((fits[KS[-1], moving] for moving in (False, True)), key=lambda m: m.bic(by(m)))
        return fits, wide, min(fits.values(), key=lambda m: m.bic(by(m)))
    (fits, wide, free), (old, old_wide, old_free) = pick(lambda m: m.loglik), pick(lambda m: m.stale)
    notes["exact_changes_restart"] = sum(fits[key] is not old[key] for key in fits)
    notes["exact_changes_structure"] = int(wide.transitions != old_wide.transitions)
    notes["exact_changes_states"] = int((free.k, free.transitions) != (old_free.k, old_free.transitions))
    notes["free_states"] = free.k
    fallback = mp.Planner(counts, cell, compare=("within", Q(1, 20)))
    models = {"pooled": fits[1, False], "belief3": wide, "belief3bic": free}
    found = {"acv_untried": mp.Planner(counts, cell, untried=True),
             "acv_within0.01_untried": mp.Planner(counts, cell, compare=("within", Q(1, 100)), untried=True)}
    for name in names:
        if name in THIRD and name not in found:
            found[name] = belief.BeliefPolicy(models[name.split("_")[0]], cell, counts, fallback, rule=THIRD[name])
    return {name: policy for name, policy in found.items() if name in names}


def compare(train, test, true_k, logging, sizes, seeds, names, insider=False):
    reference = r41.Reference(test)
    orders = r41.learned_orders(test, TOLERANT[1])["learned_context_order"]
    table = {n: {name: defaultdict(float) for name in names} for n in sizes}
    chosen = {n: defaultdict(int) for n in sizes}
    moving = {n: defaultdict(int) for n in sizes}
    audit = {n: defaultdict(int) for n in sizes}
    for seed in seeds:
        rows = mp.simulate(train, logging, max(sizes), seed, insider)
        for n in sizes:
            found, notes = policies(test, true_k, rows[:n], mp.fit(rows[:n]), seed, orders, names)
            if "auto_k" in notes:
                chosen[n][notes["auto_k"]] += 1
            if "wide_transitions" in notes:
                moving[n][notes["wide_transitions"]] += 1
            for key, value in notes.items():
                if key.startswith("exact_"):
                    audit[n][key] += value
                elif key == "free_states":
                    audit[n][f"free_states_{value}"] += 1
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
    out = {"public_optimum": r41.show(reference.best), "blind_optimum_no_history": r41.show(mp.value(test, sees=())),
           "seeds": count, "auto_k_counts": {n: dict(sorted(c.items())) for n, c in chosen.items()},
           "by_size": {n: {name: brief(c) for name, c in by.items() if c} for n, by in table.items()}}
    if any(moving.values()):
        out["wide_transition_counts"] = {n: dict(sorted(c.items())) for n, c in moving.items()}
    if any(audit.values()):
        out["likelihood_fix_audit"] = {n: dict(sorted(c.items())) for n, c in audit.items()}
    return out


MAIN = ("acv_strict", "acv_tol0.05", "learned_context_order", "belief_auto", "belief_auto_noguard",
        "belief_trueK", "belief_K-1", "belief_K+1", "belief_static")


def round_c1(name, seeds=SEEDS):
    """Same-history comparison on one cell under uniform randomized logging."""
    cell, true_k = cells()[name]
    return compare(cell, cell, true_k, mp.uniform, SIZES, seeds, MAIN)


def round_c2(name, seeds=FEWER, shares=(0.3, 0.1),
             names=("acv_tol0.05", "learned_context_order", "belief_auto", "belief_trueK")):
    """Thinner coverage: only a share of logged steps is randomized, the rest follow the contract order."""
    cell, true_k = cells()[name]
    default = mp.priority(r41.tools(cell))
    out = {}
    for share in shares:
        logging = (lambda view, rng, s=share: mp.uniform(view, rng) if rng.random() < s else default(view))
        out[str(share)] = compare(cell, cell, true_k, logging, (300, 3000), seeds, names)
    return out


def round_c3(name, seeds=FEWER, names=("acv_tol0.05", "belief_auto", "belief_trueK")):
    """Negative controls: confounded logs and distribution shift."""
    hidden = r41.lift(rounds40.binary("K", rounds40.one(Q(3, 10))))
    out = {"confounded_insider_log": compare(hidden, hidden, 2, r41.insider, (1000,), seeds, names, True),
           "uniform_log": compare(hidden, hidden, 2, mp.uniform, (1000,), seeds, names)}
    simple = r41.lift(rounds40.cells()["A"])
    for p in (Q(9, 10), Q(3, 10), Q(1, 10)):
        test = r41.lift(rounds40.binary("A", rounds40.one(p)))
        out[f"shift_to_{p}"] = compare(simple, test, 2, mp.uniform, (1000,), seeds, names)
    return out


def merged(parts):
    """Combine compare() results of disjoint seed ranges. Counts add and means are weighted by seeds.
    The estimate fields are means over the seeds whose model was not rejected, so those are the
    weights there; for the count-based planners, whose support can also differ by context, this
    is approximate."""
    total = sum(p["seeds"] for p in parts)
    out = {"public_optimum": parts[0]["public_optimum"], "blind_optimum_no_history": parts[0]["blind_optimum_no_history"],
           "seeds": total, "auto_k_counts": {}, "by_size": {}}
    tallies = [key for key in ("auto_k_counts", "wide_transition_counts") if key in parts[0]]
    for n in parts[0]["by_size"]:
        for key in tallies:
            counts = defaultdict(int)
            for p in parts:
                for k, v in p[key][n].items():
                    counts[k] += v
            out.setdefault(key, {})[n] = dict(sorted(counts.items()))
        out["by_size"][n] = {}
        for name in parts[0]["by_size"][n]:
            rows, row = [(p["by_size"][n][name], p["seeds"]) for p in parts], {}
            for key in dict.fromkeys(key for found, _ in rows for key in found):
                if key.endswith("_seeds"):
                    row[key] = sum(found.get(key, 0) for found, _ in rows)
                    continue
                values = [(found[key], seeds - found.get("model_rejected_seeds", 0) if "estimate" in key else seeds)
                          for found, seeds in rows if key in found]
                row[key] = round(sum(v * w for v, w in values) / sum(w for _, w in values), 5)
            out["by_size"][n][name] = row
    return out


FLOOR, LONG, LATER = 0.5, 300, range(6000, 6060)
# name: (floor for never-observed outcomes or None, tie band on the model's completion estimates)
SECOND = {"belief2_strict": (None, belief.NUMERIC), "belief2_snap": (FLOOR, belief.NUMERIC),
          "belief2_tol0.01": (None, 0.01), "belief2_tol0.05": (None, 0.05),
          "belief2_conf": (None, belief.confident_band)}
FOLLOW = ("acv_strict", "acv_tol0.05", "learned_context_order", "belief_auto", *SECOND, "belief2bic_tol0.05")
CONTROL = ("acv_tol0.05", "belief_auto", "belief2_snap", "belief2_tol0.01", "belief2_conf")


def round_c4(name, seeds=LATER):
    """Follow-up registered after rounds c1-c3: the same cells and controls with new seeds."""
    if name == "controls":
        return round_c3("all", seeds, CONTROL)
    if name.startswith("thin-"):
        return round_c2(name[5:], seeds, (0.1,), FOLLOW[1:])
    if name == "A":
        cell, true_k = r41.lift(rounds40.cells()["A"]), 2
    else:
        cell, true_k = cells()[name]
    return compare(cell, cell, true_k, mp.uniform, SIZES, seeds, FOLLOW)


SIMPLE = ("acv_tol0.05", "simple_last_feedback", "simple_diagnose_first")


def round_c5(name, seeds=LATER):
    """Simple rules that use the most recent feedback, on the histories of round c4."""
    if name == "controls":
        return round_c3("all", seeds, SIMPLE)
    if name.startswith("thin-"):
        return round_c2(name[5:], seeds, (0.1,), SIMPLE)
    cell = r41.lift(rounds40.cells()["A"]) if name == "A" else cells()[name][0]
    return compare(cell, cell, 0, mp.uniform, SIZES, seeds, SIMPLE)


# name: the order-free rule of belief.BeliefPolicy; None is strict. "pooled" is one state: statistics
# shared across nodes with no hidden state at all.
THIRD = {"acv_untried": None, "acv_within0.01_untried": None,
         "pooled_within0.01": ("within", 0.01), "belief3_strict": None, "belief3_within0.01": ("within", 0.01),
         "belief3_priced0.01": ("priced", 0.01), "belief3_priced0.05": ("priced", 0.05),
         "belief3bic_within0.01": ("within", 0.01)}
REPAIRED = ("acv_strict", "acv_tol0.05", *THIRD)


def round_d1(name, seeds=LATER):
    """Gate 43A-R: the corrected version on the histories of round c4. A new version, not a re-run of c4."""
    if name == "controls":
        return round_c3("all", seeds, REPAIRED)
    if name.startswith("thin-"):
        return round_c2(name[5:], seeds, (0.1,), REPAIRED)
    cell = r41.lift(rounds40.cells()["A"]) if name == "A" else cells()[name][0]
    return compare(cell, cell, 0, mp.uniform, SIZES, seeds, REPAIRED)


def unsigned(value):
    """Results of round d1 on are stored without negative zeros, whose sign depends on how the Python
    version sums floats (see docs/reviews/043a-r-reflection.md)."""
    if isinstance(value, dict):
        return {key: unsigned(item) for key, item in value.items()}
    if isinstance(value, list):
        return [unsigned(item) for item in value]
    return value + 0.0 if isinstance(value, float) else value


ROUNDS = {"c1": round_c1, "c2": round_c2, "c3": round_c3, "c4": round_c4, "c5": round_c5, "d1": round_d1}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--round", required=True, choices=sorted(ROUNDS))
    parser.add_argument("--cell", default="all")
    parser.add_argument("--seeds", default="", help="first:stop, to run a registered seed range in parts")
    args = parser.parse_args()
    part = range(*map(int, args.seeds.split(":"))) if args.seeds else None
    args.out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], text=True).strip())
    # Exclusive creation: an earlier result, including a failed or negative one, is never overwritten.
    path = args.out / f"round{args.round}-{args.cell}{'-' + args.seeds.replace(':', '-') if part else ''}.json"
    with path.open("x", encoding="utf-8") as stream:
        result = ROUNDS[args.round](args.cell, part) if part else ROUNDS[args.round](args.cell)
        json.dump({"commit": commit, "uncommitted_changes": dirty, "round": args.round, "cell": args.cell,
                   "seeds": args.seeds, "python": sys.version, "platform": platform.platform(),
                   "command": " ".join(sys.argv),
                   "result": unsigned(result) if args.round >= "d" else result},
                  stream, indent=1, ensure_ascii=False)
    print(f"round {args.round} {args.cell} written, result sha256 {r41.digest(path)}", flush=True)


if __name__ == "__main__":
    main()
