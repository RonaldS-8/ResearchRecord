"""Experiment 050: behaviour logs, likelihood and plug-in planning."""
import unittest

from extensions.toolmaze_recovery import completion_headroom as ch
from extensions.toolmaze_recovery import history_estimation as he
from extensions.toolmaze_recovery.completion_headroom import Cell


class HistoryEstimation(unittest.TestCase):
    def setUp(self):
        self.cells = list(ch.grid(ch.GRID2))[::577]

    def test_trajectory_probabilities_sum_to_one(self):
        for cell in self.cells:
            self.assertAlmostEqual(sum(he.trajectories(cell).values()), 1.0, places=12)

    def test_logs_hold_public_content_only(self):
        for key in he.trajectories(self.cells[0]):
            label, first, seen, ok = key
            self.assertIn(label, ("timeout", "error"))
            self.assertIn(first, he.FIRST)
            self.assertTrue(set(seen) <= {"receipt", "fail", "found", "missing", "error"})
            self.assertIn(ok, (0, 1))

    def test_success_flag_separates_duplicates(self):
        # A receipt after a silent commit is a duplicate: same observations, different flag.
        cell = Cell(left=4, q_commit=0.5, split=(1.0, 0.0, 0.0), p_retry=1.0)
        d = he.trajectories(cell)
        self.assertGreater(d[("timeout", ch.RETRY, ("receipt",), 0)], 0)
        self.assertGreater(d[("timeout", ch.RETRY, ("receipt",), 1)], 0)

    def test_planning_with_true_parameters_is_the_optimum(self):
        for cell in self.cells:
            v, opt = he.plug_in(cell, cell), ch.evaluate(cell)["opt"]
            self.assertAlmostEqual(v[0], opt[0], places=9)
            self.assertAlmostEqual(v[1], opt[1], places=9)

    def test_wrong_plan_never_beats_optimum(self):
        a = Cell(left=4, q_commit=0.5, accuracy=0.8, read_fail=0.3)
        b = Cell(left=4, q_commit=0.1, detail="strong", p_switch=0.7)
        self.assertLessEqual(he.plug_in(a, b)[0], ch.evaluate(a)["opt"][0] + 1e-9)
        self.assertLess(he.plug_in(a, b)[0], ch.evaluate(a)["opt"][0] - 1e-3)

    def test_true_cell_is_most_likely_with_much_history(self):
        a, b = self.cells[1], Cell(left=self.cells[1].left, backup_calls=self.cells[1].backup_calls,
                                   q_commit=0.5, split=(0.2, 0.4, 0.4), read_noise="lag")
        counts = he.sample(he.trajectories(a), 2000, "test")
        self.assertGreater(he.log_likelihood(he.trajectories(a), counts),
                           he.log_likelihood(he.trajectories(b), counts))

    def test_empirical_rule_uses_counts_only(self):
        cell = Cell(left=4, q_commit=0.5, split=(1.0, 0.0, 0.0), p_retry=1.0)
        counts = {("timeout", ch.READ, ("found",), 1): 5, ("timeout", ch.RETRY, ("receipt",), 0): 5,
                  ("error", ch.SWITCH, ("receipt",), 1): 5, ("error", ch.READ, ("missing",), 0): 5}
        _, choice = he.empirical_first(cell, counts)
        self.assertEqual(choice, {"timeout": ch.READ, "error": ch.SWITCH})


class Runner(unittest.TestCase):
    def test_excluding_truth_never_returns_truth(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        import run_history_estimation as rh
        group = rh.GROUPS[(4, 1)][:6]
        dists = [None] * len(rh.CELLS)
        for h in group:
            dists[h] = he.trajectories(rh.CELLS[h])
        rh._init(dists)
        saved = rh.GROUPS[(4, 1)]
        rh.GROUPS[(4, 1)] = group
        try:
            counts = he.sample(dists[group[2]], 500, "x")
            self.assertEqual(rh.posterior_map(group[2], counts), group[2])
            self.assertNotEqual(rh.posterior_map(group[2], counts, exclude_true=True), group[2])
        finally:
            rh.GROUPS[(4, 1)] = saved


if __name__ == "__main__":
    unittest.main()
