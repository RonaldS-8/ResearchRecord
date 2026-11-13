"""Experiment 041: the multi-route model against the experiment 040 model and its own invariants."""
from fractions import Fraction as Q
from itertools import combinations
import unittest

from extensions.toolmaze_recovery import autoresearch as ar
from extensions.toolmaze_recovery import autoresearch_rounds as rounds40
from extensions.toolmaze_recovery import multipath as mp
from extensions.toolmaze_recovery import multipath_rounds as rounds
from extensions.toolmaze_recovery.autoresearch import DIAGNOSE, RETRY, STOP, SWITCH
from extensions.toolmaze_recovery.multipath import DONE, PASS, PUBLIC, START, Fault, Prices, View


def old_cells():
    cells = dict(rounds40.cells())
    cells["S4"] = rounds40.composite()
    cells["U"] = rounds40.binary("U", rounds40.one(Q(9, 10)), backup=Q(7, 10))
    return cells


def as_old(policy):
    """Run an experiment 040 rule on a multipath View of a lifted cell."""
    return lambda view: policy(ar.View(view.x, ar.Quote(view.quote.of(SWITCH), view.quote.diagnostic,
                                                         view.quote.of(RETRY)), view.events, view.left))


class MultipathAnchorTests(unittest.TestCase):
    def test_lifted_cells_equal_experiment_040_under_every_information_set(self):
        for name, cell in old_cells().items():
            lifted = rounds.lift(cell)
            with self.subTest(cell=name):
                for n in range(5):
                    for sees in combinations(sorted(PUBLIC), n):
                        self.assertEqual(mp.value(lifted, sees=sees), ar.value(cell, sees=sees), sees)
                self.assertEqual(mp.oracle(lifted), ar.oracle(cell))
                self.assertEqual(mp.value(lifted, tolerance=Q(1, 20)), ar.value(cell, tolerance=Q(1, 20)))
                self.assertEqual(mp.value(lifted, ban=(DIAGNOSE,)), ar.value(cell, ban=(DIAGNOSE,)))
                for rule in (ar.fixed(0), ar.fixed(1), ar.fixed(2), ar.fixed(1, guard=False),
                             ar.simple_feedback, ar.order(SWITCH, RETRY)):
                    self.assertEqual(mp.value(lifted, as_old(rule)), ar.value(cell, rule))

    def test_planner_with_a_tolerance_equals_the_experiment_040_planner_on_the_same_counts(self):
        for name in ("A", "E", "G", "CX", "S4"):
            cell = old_cells()[name]
            lifted = rounds.lift(cell)
            counts = ar.fit(ar.simulate(cell, ar.uniform, 600, 3))
            for tolerance in (Q(0), Q(1, 20)):
                old = ar.Planner(counts, cell.alphabet(), tolerance=tolerance)
                new = mp.Planner(rounds.lift_counts(counts), lifted, compare=("tolerance", tolerance))
                self.assertEqual(mp.value(lifted, new), ar.value(cell, old), (name, tolerance))
        empty = mp.Planner({}, rounds.lift(old_cells()["A"]))
        self.assertEqual(empty(View(None, Prices(), (), 6, empty.graph)), SWITCH)

    def test_sampled_history_matches_exact_evaluation_and_never_logs_the_hidden_state(self):
        cell = rounds.lift(old_cells()["S4"])
        rule = as_old(ar.order(SWITCH, RETRY))
        rows = mp.simulate(cell, mp.deterministic(rule), 4000, 5)
        completion, fee = mp.value(cell, rule)
        self.assertAlmostEqual(sum(r["done"] for r in rows) / 4000, float(completion), delta=0.03)
        self.assertAlmostEqual(float(sum(r["fee"] for r in rows)) / 4000, float(fee), delta=0.08)
        logged = mp.simulate(cell, mp.uniform, 300, 7)
        self.assertEqual(logged, mp.simulate(cell, mp.uniform, 300, 7))
        self.assertEqual({key for row in logged for key in row}, {"x", "quote", "steps", "done", "fee"})
        for state in cell.faults:
            self.assertNotIn(repr(state), repr(logged))
        self.assertEqual(set(View.__dataclass_fields__), {"x", "quote", "events", "left", "graph"})


class MultipathModelTests(unittest.TestCase):
    def two_call_backup(self, left=8):
        """Primary read; backup read then a check that fails when the backup copy is stale; a slow third route."""
        graph = mp.parallel(((("backup", "validate"), 2), (("third",), 4), (("primary",), 2)))
        works = {"backup": Q(1), "validate": Q(1), "third": Q(1)}
        faults = {"transient": Fault({**works, "primary": Q(1)}),
                  "persistent": Fault({**works, "primary": Q(0)}),
                  "stale": Fault({**works, "primary": Q(0), "validate": Q(0)})}
        prior = {"transient": Q(1, 2), "persistent": Q(1, 4), "stale": Q(1, 4)}
        return mp.build("two-call", graph, faults, {None: (Q(1), prior)}, left=left)

    def test_shared_progress_budget_and_failing_again_after_a_switch(self):
        cell = self.two_call_backup()
        self.assertEqual(mp.position(cell.graph, ()), START)
        self.assertEqual(mp.position(cell.graph, (("backup", PASS), ("third", None), (DIAGNOSE, "x"))), (1, 0, 0))
        self.assertEqual(mp.needs(cell.graph, START), 3)
        # The backup needs its read, its check and two more calls; with 3 calls left only the primary fits.
        self.assertEqual(mp.legal(cell.graph, (), 3, False), ("primary", STOP))
        self.assertEqual(mp.legal(cell.graph, (("backup", PASS),), 3, False), ("validate", "primary", STOP))
        plan = mp.priority(("primary", "backup", "validate", "third"))
        self.assertEqual(mp.value(cell, plan), (1, Q(1, 2) * 3 + Q(1, 4) * (1 + 4) + Q(1, 4) * (1 + 2 + 5)))
        # A check that may fail after the switch makes the obvious backup worse than the slow third route.
        self.assertEqual(mp.value(cell), (1, Q(1, 2) * 3 + Q(1, 2) * (1 + 5)))
        self.assertEqual(mp.value(cell), mp.value(cell, mp.priority(("primary", "third"))))
        self.assertEqual(mp.oracle(cell), (1, Q(1, 2) * 3 + Q(1, 4) * 4 + Q(1, 4) * 5))
        # With one call fewer, the stale state cannot reach the third route after the check fails.
        tight = self.two_call_backup(left=7)
        self.assertEqual(mp.value(tight, plan)[0], Q(3, 4))
        self.assertEqual(mp.value(tight)[0], 1)
        rows = mp.simulate(cell, mp.deterministic(plan), 2000, 1)
        self.assertAlmostEqual(float(sum(r["fee"] for r in rows)) / 2000, float(mp.value(cell, plan)[1]), delta=0.12)
        self.assertTrue(all(r["done"] for r in rows))

    def test_first_action_values_and_root_values_are_consistent(self):
        cell = self.two_call_backup()
        found = mp.first_values(cell, None, Prices())
        self.assertEqual(max(found.values(), key=lambda v: (v[0], -v[1])), mp.value(cell))
        self.assertEqual(found[STOP], (0, 0))
        self.assertEqual(mp.at_root(cell, mp.priority(("third",)), None, Prices()), (1, Q(5)))

    def test_interval_comparison_keeps_uncertain_ties_and_separates_clear_differences(self):
        cell = rounds.lift(old_cells()["A"])
        planner = mp.Planner({}, cell, compare=("interval", 1.96, True))
        tie = {STOP: (Q(), Q(), 0.0), SWITCH: (Q(92, 100), Q(4), 0.0004), RETRY: (Q(90, 100), Q(33, 10), 0.0004)}
        self.assertEqual(planner.choose(tie), RETRY)                      # 0.02 apart, sd 0.02 each: cheaper wins
        clear = {STOP: (Q(), Q(), 0.0), SWITCH: (Q(1), Q(4), 0.0001), RETRY: (Q(8, 10), Q(26, 10), 0.0004)}
        self.assertEqual(planner.choose(clear), SWITCH)                   # 0.2 apart: completion wins
        weak = {STOP: (Q(), Q(), 0.0), RETRY: (Q(1, 10), Q(1), 0.01)}
        self.assertEqual(planner.choose(weak), RETRY)                     # guard: do not stop on mere uncertainty
        self.assertEqual(mp.Planner({}, cell, compare=("interval", 1.96, False)).choose(weak), STOP)
        self.assertEqual(mp.Planner({}, cell, compare=("tolerance", Q())).choose(tie), SWITCH)
        self.assertEqual(mp.Planner({}, cell, compare=("lcb", 1.96)).choose(tie), SWITCH)

    def test_posterior_spread_shrinks_with_support_and_is_positive_at_a_saturated_frequency(self):
        cell = rounds.lift(old_cells()["A"])
        spreads = []
        for n in (5, 50, 500):
            counts = {(None, (), SWITCH): {DONE: n}}
            value = mp.Planner(counts, cell).node(None, Prices(), (), 6)[2][SWITCH]
            self.assertEqual(value[:2], (1, 4))
            spreads.append(value[2])
        self.assertTrue(spreads[0] > spreads[1] > spreads[2] > 0)


if __name__ == "__main__":
    unittest.main()
