"""Experiment 042: the learnable hidden-state model against exact references and its own guards."""
from fractions import Fraction as Q
from math import sqrt
import unittest

from extensions.toolmaze_recovery import autoresearch as ar
from extensions.toolmaze_recovery import autoresearch_rounds as rounds40
from extensions.toolmaze_recovery import belief
from extensions.toolmaze_recovery import belief_rounds as rounds
from extensions.toolmaze_recovery import multipath as mp
from extensions.toolmaze_recovery import multipath_rounds as r41
from extensions.toolmaze_recovery.belief import OK, Model


def true_model(cell, move=None):
    """The generator written as a Model. Used only by tests, never by a fitted policy."""
    states = list(cell.faults)
    tools = r41.tools(cell)
    emit = {tool: {OK: [float(cell.faults[z].rates[tool]) if not isinstance(cell.faults[z].rates[tool], tuple)
                        else float(cell.faults[z].rates[tool][0]) for z in states]} for tool in tools}
    for tool in tools:
        emit[tool][None] = [1 - p for p in emit[tool][OK]]
    start = {x: [float(dict(prior).get(z, 0)) for z in states] for _, x, _, prior in cell.roots}
    identity = [[float(i == j) for j in range(len(states))] for i in range(len(states))]
    return Model(start, emit, move or identity, move is not None)


class BeliefModelTests(unittest.TestCase):
    def nearly(self, got, expected):
        self.assertAlmostEqual(float(got[0]), float(expected[0]), places=9)
        self.assertAlmostEqual(float(got[1]), float(expected[1]), places=9)

    def plan_value(self, model, cell):
        policy = belief.BeliefPolicy(model, cell, {(None, (), t): {mp.DONE: 9} for t in r41.tools(cell)},
                                     lambda view: ar.STOP, guard=False)
        return mp.value(cell, policy), policy

    def test_planning_on_the_true_static_model_gives_the_public_optimum(self):
        for cell in (r41.fresh_cells()["M5"], r41.m3(8), r41.m4()):
            got, policy = self.plan_value(true_model(cell), cell)
            self.nearly(got, mp.value(cell))
            for (x, quote), estimate in policy.estimates.items():
                self.nearly(estimate, mp.at_root(cell, policy, x, quote))

    def test_a_fault_that_clears_after_one_call_needs_the_transition(self):
        cell = r41.held_cells()["S4b"]          # states: fast, shared (clears after one call), persistent, blocked
        clears = [[1.0, 0, 0, 0], [1.0, 0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]]
        self.nearly(self.plan_value(true_model(cell, clears), cell)[0], mp.value(cell))
        static = self.plan_value(true_model(cell), cell)[0]
        self.assertTrue(ar.better(mp.value(cell), static, Q(1, 10 ** 9)))
        self.assertEqual(mp.shift(cell, {(0, "fast"): Q(1)}), {(0, "fast"): Q(1)})  # Gate 41 cells stay static

    def test_belief_update_by_hand_and_unknown_feedback(self):
        model = Model({None: [0.5, 0.5]}, {"a": {OK: [0.9, 0.2], None: [0.1, 0.8]}}, [[1.0, 0.0], [0.5, 0.5]], True)
        posterior = model.filter(None, (("a", None),))
        # after a failure: (0.05, 0.40) / 0.45, then the second state moves halfway to the first
        self.assertAlmostEqual(posterior[0], 0.05 / 0.45 + 0.5 * 0.40 / 0.45)
        self.assertAlmostEqual(sum(posterior), 1.0)
        self.assertAlmostEqual(model.success(None, (), "a"), 0.55)
        self.assertIsNone(model.filter(None, (("a", "never seen label"),)))
        self.assertIsNone(model.filter(None, (("unknown tool", None),)))

    def test_fit_uses_only_logged_public_history_and_recovers_predictions(self):
        cell = r41.fresh_cells()["M5"]
        rows = mp.simulate(cell, mp.uniform, 3000, 4001)
        model = belief.train(rows, cell, 4, 4001)
        blank = mp.Cell(cell.name, cell.graph, {"only": mp.Fault({t: Q(1) for t in r41.tools(cell)})},
                        cell.roots[:1], cell.left)
        again = belief.train(rows, blank, 4, 4001)       # a cell with no generator in it: same fit
        self.assertEqual((model.start, model.emit, model.move), (again.start, again.emit, again.move))
        # With diagnostic signals the fit also needs their public names, and nothing else, from the cell.
        signalled = rounds.cells()["E"][0]
        names = signalled.alphabet()[ar.DIAGNOSE]
        only = mp.Fault({t: Q(1) for t in r41.tools(signalled)}, signal=tuple((name, Q(1, 2)) for name in names))
        nameless = mp.Cell(signalled.name, signalled.graph, {"only": only}, signalled.roots, signalled.left)
        logged = mp.simulate(signalled, mp.uniform, 300, 4001)
        first, second = belief.train(logged, signalled, 2, 4001), belief.train(logged, nameless, 2, 4001)
        self.assertEqual((first.start, first.emit, first.move), (second.start, second.emit, second.move))
        truth = true_model(cell)
        for x in ("X1", "X2", "X3"):
            for events, tool in (((), "r0"), ((("r0", None),), "r1"), ((("r0", None), ("r1", None)), "r2")):
                self.assertAlmostEqual(model.success(x, events, tool), truth.success(x, events, tool), delta=0.06)
        counts = mp.fit(rows)
        self.assertTrue(belief.consistent(model, counts))
        policy = belief.BeliefPolicy(model, cell, counts, mp.Planner(counts, cell))
        got, best = mp.value(cell, policy), mp.value(cell)
        self.assertLess(abs(float(got[0] - best[0])), 0.005)
        self.assertLess(float(got[1]), float(best[1]) * 1.05)   # 3.9% above the optimum on this seed

    def test_guard_rejects_a_model_that_contradicts_well_supported_frequencies(self):
        cell = r41.held_cells()["S4b"]
        counts = mp.fit(mp.simulate(cell, mp.uniform, 3000, 4002))
        clears = [[1.0, 0, 0, 0], [1.0, 0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]]
        self.assertTrue(belief.consistent(true_model(cell, clears), counts))
        self.assertFalse(belief.consistent(true_model(cell), counts))    # static: wrong about the second call
        refused = belief.BeliefPolicy(true_model(cell), cell, counts, lambda view: "fallback")
        self.assertTrue(refused.rejected)
        self.assertEqual(refused(mp.View("X1", cell.roots[0][2], (), cell.left, cell.graph)), "fallback")

    def test_a_tool_that_was_never_logged_is_left_out_and_unplanned_histories_fall_back(self):
        cell = r41.m3(8)
        seen = [r for r in mp.simulate(cell, mp.uniform, 1500, 4003) if all(a != "archive" for _, a, _ in r["steps"])]
        counts = mp.fit(seen)
        policy = belief.BeliefPolicy(belief.train(seen, cell, 3, 4003), cell, counts, lambda view: "fallback",
                                     guard=False)
        self.assertNotIn("archive", set(policy.table.values()))
        odd = mp.View("X1", cell.roots[0][2], (("archive", None),), 7, cell.graph)
        self.assertEqual(policy(odd), "fallback")

    def test_same_history_scoring_runs_every_registered_policy(self):
        cell, true_k = rounds.cells()["E"]
        got = rounds.compare(cell, cell, true_k, mp.uniform, (300,), range(2), rounds.MAIN)
        self.assertEqual(set(got["by_size"][300]), set(rounds.MAIN))
        self.assertEqual(sum(got["auto_k_counts"][300].values()), 2)


class BeliefFollowUpTests(unittest.TestCase):
    def test_snapping_removes_only_outcomes_that_rest_on_pseudo_counts(self):
        mass = ({None: [10.0, 0.2]},
                {"a": {OK: [9.9, 0.0], None: [0.1, 0.2]}},
                [[5.0, 0.01], [0.0, 0.0]])
        model = Model({None: [0.98, 0.02]}, {"a": {OK: [0.97, 0.3], None: [0.03, 0.7]}},
                      [[0.99, 0.01], [0.4, 0.6]], True, mass=mass)
        clean = belief.snapped(model, 0.5)
        self.assertEqual(clean.start[None], [1.0, 0.0])
        self.assertEqual([clean.emit["a"][OK][0], clean.emit["a"][None][0]], [1.0, 0.0])   # failure never observed
        self.assertEqual([clean.emit["a"][OK][1], clean.emit["a"][None][1]], [0.3, 0.7])   # no evidence: left as is
        self.assertEqual(clean.move, [[1.0, 0.0], [0.4, 0.6]])
        self.assertEqual(model.emit["a"][OK], [0.97, 0.3])                                 # the fit is not altered

    def test_merging_seed_ranges_adds_counts_and_weights_means(self):
        def part(seeds, fee, regret, k, rejected=0, bias=None):
            row = {"material_regret_seeds": regret, "mean_fee": fee, "model_rejected_seeds": rejected}
            if bias is not None:
                row["completion_estimate_bias"] = bias
            return {"public_optimum": ["1", "4", 4.0], "blind_optimum_no_history": ["1", "4", 4.0], "seeds": seeds,
                    "auto_k_counts": {"300": {k: seeds}}, "by_size": {"300": {"p": row}}}
        got = rounds.merged([part(25, 4.0, 2, "2"), part(75, 3.0, 6, "3")])
        self.assertEqual(got["seeds"], 100)
        self.assertEqual(got["by_size"]["300"]["p"],
                         {"material_regret_seeds": 8, "mean_fee": 3.25, "model_rejected_seeds": 0})
        self.assertEqual(got["auto_k_counts"]["300"], {"2": 25, "3": 75})
        # An estimate is averaged over the seeds whose model was kept: 50 and 10 of them here, not 50 and 50.
        uneven = rounds.merged([part(50, 4.0, 0, "2", 0, 0.10), part(50, 4.0, 0, "2", 40, 0.50)])
        self.assertAlmostEqual(uneven["by_size"]["300"]["p"]["completion_estimate_bias"], 0.16667, places=5)
        absent = rounds.merged([part(50, 4.0, 0, "2", 50), part(50, 4.0, 0, "2", 0, 0.20)])
        self.assertAlmostEqual(absent["by_size"]["300"]["p"]["completion_estimate_bias"], 0.20)

    def test_strict_comparison_acts_on_smoothing_and_a_tie_band_does_not(self):
        cell = r41.lift(rounds40.cells()["A"])          # retry is right nine times in ten; optimum 3.2
        model = true_model(cell)
        for tool in model.emit:                         # what 0.1 pseudo-counts leave after 500 clean observations
            ok = [(p * 500 + 0.1) / 500.2 for p in model.emit[tool][OK]]
            model.emit[tool] = {OK: ok, None: [1 - p for p in ok]}
        counts = {(None, (), t): {mp.DONE: 500} for t in r41.tools(cell)}

        def fee(tolerance):
            policy = belief.BeliefPolicy(model, cell, counts, lambda view: ar.STOP, guard=False, tolerance=tolerance)
            return float(mp.value(cell, policy)[1])
        self.assertAlmostEqual(fee(belief.NUMERIC), 4.0)   # switches for a few billionths of estimated completion
        self.assertAlmostEqual(fee(0.01), 3.2)
        self.assertAlmostEqual(fee(belief.confident_band), 3.2)
        counts = {(None, (), t): {mp.DONE: 10} for t in r41.tools(cell)}     # twenty logged episodes: no band left
        self.assertAlmostEqual(fee(belief.confident_band), 4.0)
        for calls, completion in ((4, 0.9), (5, 1.0)):                        # a tool needs five logged calls to be planned
            counts = {(None, (), "retry"): {mp.DONE: 500}, (None, (), "switch"): {mp.DONE: calls}}
            policy = belief.BeliefPolicy(model, cell, counts, lambda view: ar.STOP, guard=False, tolerance=0.01)
            self.assertAlmostEqual(float(mp.value(cell, policy)[0]), completion)

    def test_confident_band_closes_when_the_log_is_thin(self):
        self.assertAlmostEqual(belief.confident_band(0.9, 1000), 0.05 - 2 * sqrt(0.09 / 1000) - 0.001)
        self.assertAlmostEqual(belief.confident_band(1.0, 300), 0.05 - 1 / 300)
        self.assertEqual(belief.confident_band(0.9, 100), belief.NUMERIC)   # two standard errors exceed the margin
        self.assertEqual(belief.confident_band(0.5, 0), belief.NUMERIC)

    def test_follow_up_round_scores_every_variant(self):
        cell, true_k = rounds.cells()["E"]
        got = rounds.compare(cell, cell, true_k, mp.uniform, (100,), range(1), rounds.FOLLOW)
        self.assertEqual(set(got["by_size"][100]), set(rounds.FOLLOW))
        self.assertEqual(sum(got["wide_transition_counts"][100].values()), 1)


if __name__ == "__main__":
    unittest.main()
