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


class Gate41RoundTests(unittest.TestCase):
    """Exact values registered in docs/experiments/041; nothing here samples except where noted."""

    def test_blind_search_over_exclusive_routes_matches_its_closed_form(self):
        for k, share in ((2, Q(1, 7)), (3, Q(1, 4)), (4, Q(1, 3))):
            cell = rounds.exclusive([Q(1, k)] * k, [Q(1)] * k, 2)
            blind, top = mp.value(cell, sees=()), mp.oracle(cell)
            self.assertEqual(top, (1, 3))
            self.assertEqual((blind[1] - top[1]) / blind[1], share)
        self.assertEqual(mp.value(rounds.exclusive([Q(1, 4)] * 4, [Q(3)] * 4, 0))[1], Q(15, 2))  # 60% above the oracle's 3
        mixed = rounds.exclusive([Q(1, 5), Q(3, 10), Q(1, 2)], [Q(1), Q(2), Q(3)], 2)
        self.assertEqual(mp.value(mixed), (1, Q(6)))
        self.assertEqual(mp.value(mixed, mp.priority(("r0", "r2", "r1"))), (1, Q(6)))  # prior / price order

    def test_three_path_cell_with_a_check_that_can_fail_after_the_switch(self):
        ample, tight = rounds.m3(8), rounds.m3(6)
        self.assertEqual((mp.value(ample), mp.value(ample, sees=()), mp.oracle(ample)),
                         ((1, Q(53, 10)), (1, Q(169, 30)), (1, Q(14, 3))))
        self.assertEqual((mp.value(tight), mp.value(tight, sees=())), ((1, Q(16, 3)), (1, Q(169, 30))))
        self.assertEqual(mp.value(ample, sees=("x",)), mp.value(ample))
        through = mp.priority(("primary", "backup", "validate", "archive"))
        self.assertEqual(mp.value(ample, through), (1, Q(61, 10)))
        self.assertEqual(mp.value(tight, through)[0], Q(23, 30))
        firsts = {x: mp.first_values(rounds.only(ample, x), x, ample.roots[0][2]) for x in ("X1", "X2", "X3")}
        best = {x: max(found, key=lambda a: (found[a][0], -found[a][1])) for x, found in firsts.items()}
        self.assertEqual(best, {"X1": "primary", "X2": "backup", "X3": "archive"})
        self.assertEqual(rounds.strongest_order(rounds.only(ample, "X3"))[1], (1, Q(6)))

    def test_two_slot_cell_fails_again_in_the_second_slot(self):
        cell = rounds.m4()
        self.assertEqual((mp.value(cell), mp.value(cell, sees=()), mp.oracle(cell)),
                         ((1, Q(68, 15)), (1, Q(23, 5)), (1, Q(119, 30))))
        retry_first = mp.priority(("primary", "backup", "writer", "altwriter"))
        self.assertEqual(mp.value(cell, retry_first)[0], Q(7, 10))  # no calls left for the other writer
        self.assertEqual(mp.position(cell.graph, (("primary", None), ("backup", PASS))), "evidence")
        # After the writer fails with two calls left, only another try of the same writer is affordable.
        self.assertEqual(mp.legal(cell.graph, (("primary", None), ("backup", PASS), ("writer", None)), 2, False),
                         ("writer", STOP))

    def test_bench2robust_style_noise_and_scenarios(self):
        chance = rounds.noisy("alt", Q(37, 50), (), 0)
        self.assertEqual(chance(()), Q(37, 50))
        self.assertEqual(chance((("alt", None),)), Q(37, 50))
        self.assertEqual(chance((("alt", None), ("alt", None))), 1)            # two failures in a row: clean
        self.assertEqual(rounds.noisy("lookup", Q(37, 50), (), 1)((("lookup", None),)), 1)
        self.assertEqual(chance((("lookup", None),) * 4), 1)                   # five injections with the first timeout
        self.assertEqual(rounds.noisy("alt", Q(37, 50), ("lookup",), 0)((("lookup", None),) * 4), Q(37, 50))
        cell = rounds.b2r((Q(2, 5), Q(1, 2), Q(1, 10)))
        prior = dict(cell.roots[0][3])
        self.assertEqual(prior["S2_lookup_blocked"] + prior["S3"], Q(350, 519))  # lookup blocked: about 0.675
        first = mp.first_values(cell, None, Prices())
        self.assertEqual(first["alt"][0], first["lookup"][0])
        self.assertLess(first["alt"][1], first["lookup"][1])
        noise_only = rounds.b2r((Q(1), Q(0), Q(0)))
        self.assertEqual(mp.value(noise_only), (1, Q(163, 50)))
        self.assertEqual(mp.value(noise_only, mp.priority(("lookup",), {"lookup": 2})), (1, Q(163, 50)))
        roomy = mp.Cell(cell.name, cell.graph, cell.faults, cell.roots, 12)
        for order in (("lookup", "alt"), ("alt", "lookup")):
            self.assertEqual(mp.value(roomy, mp.priority(order, {"lookup": 3, "alt": 3}))[0], Q(419, 519))
        self.assertEqual(mp.value(cell, mp.priority(("lookup", "alt"), {"lookup": 3, "alt": 3}))[0], Q(169, 519))

    def test_scoring_against_the_exact_reference(self):
        self.assertTrue(rounds.material((Q(9, 10), Q(3)), (Q(1), Q(4))))
        self.assertTrue(rounds.material((Q(1), Q(43, 10)), (Q(1), Q(4))))
        self.assertFalse(rounds.material((Q(1), Q(41, 10)), (Q(1), Q(4))))
        self.assertFalse(rounds.material((Q(99, 100), Q(3)), (Q(1), Q(4))))
        cell = rounds.m3(8)
        reference = rounds.Reference(cell)
        table = {}
        mp.value(cell, table=table)
        optimal = reference.score(lambda view: table[view.x, view.quote, view.events])
        self.assertEqual((optimal["completion"], optimal["fee"], optimal["wrong"]), (1, Q(53, 10), 0))
        archive = reference.score(mp.priority(("archive",)))
        self.assertEqual((archive["fee"], archive["wrong"], archive["wrong_material"]), (6, Q(2, 3), Q(2, 3)))
        counts = mp.fit(mp.simulate(cell, mp.uniform, 3000, 4))
        strict = reference.score(mp.Planner(counts, cell))
        self.assertEqual((strict["supported"], strict["completion"], strict["bias"]), (1.0, 1, 0.0))
        # Recorded failure (experiment 041): on this deep tree the interval rule keeps a cheap action whose
        # completion is very uncertain, and the executed policy then completes less often than it estimated.
        loose = reference.score(mp.Planner(counts, cell, compare=("interval", 1.96, True)))
        self.assertLess(loose["completion"], Q(9, 10))
        self.assertGreater(loose["bias"], 0.05)

    def test_registered_selection_rule_and_digest(self):
        def row(regret, wrong):
            return {"material_regret_seeds": regret, "materially_wrong_first_action": wrong}
        names = rounds.rules()
        developed = {"cell": {"by_size": {str(n): {name: row(50, 0.2) for name in names} for n in (100, 300, 1000)}}}
        for n in (100, 300, 1000):
            developed["cell"]["by_size"][str(n)]["ci_1.96_guard"] = row(10, 0.1)
            developed["cell"]["by_size"][str(n)]["ci_1.96"] = row(10, 0.1)
            developed["cell"]["by_size"][str(n)]["tol_0.05"] = row(20, 0.1)
            developed["cell"]["by_size"][str(n)]["tol_0.1"] = row(20, 0.1)
        chosen = rounds.choose(developed)
        self.assertEqual((chosen["interval"], chosen["tolerance"]), ("ci_1.96_guard", "tol_0.05"))
        self.assertEqual(chosen["scores"]["ci_1.96_guard"], [0.05, 0.1])

    def test_noninferior_rule_never_lets_uncertainty_favour_the_cheaper_action(self):
        cell = rounds.lift(old_cells()["A"])
        planner = mp.Planner({}, cell, compare=rounds.NONINFERIOR)
        thin = {STOP: (Q(), Q(), 0.0), SWITCH: (Q(1), Q(4), 0.0001), RETRY: (Q(86, 100), Q(3), 0.01)}
        self.assertEqual(planner.choose(thin), SWITCH)        # 0.86 +/- 0.1: not shown to be within 0.05
        self.assertEqual(mp.Planner({}, cell, compare=("interval", 1.96, True)).choose(thin), RETRY)
        close = {STOP: (Q(), Q(), 0.0), SWITCH: (Q(92, 100), Q(4), 0.0001), RETRY: (Q(90, 100), Q(33, 10), 0.0001)}
        self.assertEqual(planner.choose(close), RETRY)        # 0.90 - 1.64 * 0.01 >= 0.92 - 0.05: cheaper wins
        wide = {STOP: (Q(), Q(), 0.0), SWITCH: (Q(92, 100), Q(4), 0.0001), RETRY: (Q(90, 100), Q(33, 10), 0.0009)}
        self.assertEqual(planner.choose(wide), SWITCH)        # same estimates, sd 0.03: stays with the higher
        self.assertEqual(planner.choose({STOP: (Q(), Q(), 0.0), RETRY: (Q(1, 50), Q(1), 0.0)}), RETRY)
        self.assertEqual(planner.choose({STOP: (Q(), Q(), 0.0), RETRY: (Q(), Q(1), 0.0)}), STOP)

    def test_untried_tool_is_called_before_stopping_but_a_supported_dead_end_is_not(self):
        cell = rounds.m3(8)
        stuck = (("backup", PASS), ("validate", None))
        counts = {("X1", stuck, "validate"): {None: 5}}            # only a failing retry of the check has support
        view = View("X1", cell.roots[0][2], stuck, 6, cell.graph)
        self.assertEqual(mp.Planner(counts, cell)(view), STOP)
        self.assertEqual(mp.Planner(counts, cell, untried=True)(view), "archive")
        counts[("X1", stuck, "archive")] = {None: 5}                # now the archive has support and never worked
        counts[("X1", stuck, "primary")] = {None: 5}
        self.assertEqual(mp.Planner(counts, cell, untried=True)(view), STOP)
        empty = View("X1", cell.roots[0][2], stuck + (("archive", None),), 5, cell.graph)
        self.assertEqual(mp.Planner({}, cell, untried=True)(empty), "primary")   # nothing supported: first not yet failed
        self.assertEqual(mp.Planner({}, cell)(empty), "validate")                 # old fallback repeats a failed tool
        self.assertEqual(set(rounds.fresh_cells()), {"M3c", "M4c", "M5", "S4c", "Dc", "Uc", "B2R-mini-phase5"})
        self.assertEqual(mp.value(rounds.fresh_cells()["M5"])[0], Q(9, 10))
