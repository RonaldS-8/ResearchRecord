"""Experiment 047: hand-checked cells and invariants of the completion-headroom model."""
from itertools import islice
import unittest

from extensions.toolmaze_recovery import completion_headroom as ch
from extensions.toolmaze_recovery.completion_headroom import (
    FINISH, READ, RETRY, STOP, SWITCH, Cell, better, evaluate, optimum, sequence_value)


def close(test, value, expected):
    test.assertAlmostEqual(value[0], expected[0], places=12)
    test.assertAlmostEqual(value[1], expected[1], places=12)


class HandCells(unittest.TestCase):
    def setUp(self):
        # Half the first failures committed silently; otherwise a transient writer that a retry fixes.
        self.cell = Cell(left=2, q_commit=0.5, split=(1.0, 0.0, 0.0), p_retry=1.0, c_lost=0.0,
                         accuracy=1.0, read_fee=0.1, detail="none")

    def test_read_back_then_retry_is_optimal(self):
        values = evaluate(self.cell)
        close(self, values["opt"], (1.0, 0.6))
        close(self, values["oracle"], (1.0, 0.5))
        close(self, values["fix_x"], (1.0, 0.6))
        close(self, values["read_first"], (1.0, 0.6))

    def test_without_read_back_a_retry_duplicates_the_silent_commit(self):
        values = evaluate(self.cell)
        close(self, values["retry_then_switch"], (0.5, 1.0))
        close(self, values["opt_no_read"], (0.5, 0.0))  # finishing blindly ties and is free

    def test_duplicate_publication_cannot_be_undone(self):
        cell = Cell(left=3, q_commit=1.0, p_retry=1.0)
        mass = cell.roots()["timeout"]
        self.assertAlmostEqual(sequence_value(cell, mass, (RETRY,), FINISH)[0], 0.0)
        self.assertAlmostEqual(sequence_value(cell, mass, (SWITCH,), FINISH)[0], 0.0)
        self.assertAlmostEqual(sequence_value(cell, mass, (), FINISH)[0], 0.5)  # timeout share

    def test_shared_backend_is_unrecoverable_and_stopping_is_free(self):
        values = evaluate(Cell(left=4, q_commit=0.0, split=(0.0, 0.0, 1.0)))
        close(self, values["opt"], (0.0, 0.0))
        close(self, values["oracle"], (0.0, 0.0))

    def test_uninformative_read_back_has_no_value(self):
        for cell in islice(ch.grid(), 0, 2916, 97):
            cell = Cell(**{**cell.__dict__, "accuracy": 0.5})
            values = evaluate(cell)
            close(self, values["opt"], values["opt_no_read"])

    def test_single_vote_equals_read_first_sequence(self):
        for cell in islice(ch.grid(), 5, 2916, 211):
            for mass in cell.roots().values():
                for actions in ((), (SWITCH,), (RETRY, SWITCH)):
                    for end in (FINISH, STOP):
                        close(self, ch.vote_value(cell, mass, 1, 1, actions, end),
                              sequence_value(cell, mass, (READ,) + actions, end))

    def test_vote_rule_never_beats_the_optimum(self):
        for cell in islice(ch.grid(), 0, 2916, 151):
            for mass in cell.roots().values():
                self.assertFalse(better(ch.best_vote(cell, mass)[0], optimum(cell, mass, cell.left)))

    def test_sequence_enumeration(self):
        self.assertEqual(len(list(ch.sequences(3))), 2 * (1 + 3 + 9 + 27))


class RoundTwoMechanisms(unittest.TestCase):
    def test_unreliable_backup_makes_retry_worth_choosing(self):
        # Transient writer only, one call left: a sure retry beats a coin-flip backup.
        cell = Cell(left=1, q_commit=0.0, split=(1.0, 0.0, 0.0), p_retry=1.0, p_switch=0.5)
        close(self, evaluate(cell)["opt"], (1.0, 1.0))
        mass = cell.roots()["timeout"]
        self.assertAlmostEqual(sequence_value(cell, mass, (SWITCH,), STOP)[0], 0.25)  # timeout half

    def test_two_step_backup_needs_the_budget(self):
        cell = Cell(left=1, q_commit=0.0, split=(0.0, 1.0, 0.0), backup_calls=2)
        close(self, evaluate(cell)["opt"], (0.0, 0.0))  # primary down, backup unaffordable
        close(self, evaluate(Cell(**{**cell.__dict__, "left": 2}))["opt"], (1.0, 2.0))
        self.assertTrue(all(sum(2 if a == SWITCH else 1 for a in seq) <= 3
                            for seq, _ in ch.sequences(3, backup_calls=2)))

    def test_failing_backup_can_commit_silently(self):
        cell = Cell(left=4, q_commit=0.0, split=(0.0, 1.0, 0.0), p_switch=0.0, c_lost=1.0)
        mass = cell.roots()["timeout"]
        # The backup always commits without a receipt: a second switch duplicates it.
        self.assertAlmostEqual(sequence_value(cell, mass, (SWITCH,), FINISH)[0], 0.5)
        self.assertAlmostEqual(sequence_value(cell, mass, (SWITCH, SWITCH), FINISH)[0], 0.0)

    def test_failed_read_back_carries_no_evidence(self):
        for cell in islice(ch.grid(ch.GRID2), 3, 4608, 331):
            cell = Cell(**{**cell.__dict__, "read_fail": 1.0})
            values = evaluate(cell)
            close(self, values["opt"], values["opt_no_read"])

    def test_lagged_found_is_conclusive(self):
        cell = Cell(left=3, q_commit=0.5, split=(1.0, 0.0, 0.0), accuracy=0.6, read_noise="lag")
        mass = cell.roots()["timeout"]
        _, _, branches = ch.step(cell, mass, READ)
        found = branches["found"]
        self.assertAlmostEqual(ch.finish(found), sum(found))

    def test_reread_without_rereads_is_the_fixed_order(self):
        for cell in islice(ch.grid(ch.GRID2), 7, 4608, 509):
            for mass in cell.roots().values():
                for seq in islice(ch.sequences(cell.left, cell.backup_calls), 0, None, 37):
                    close(self, ch.reread_value(cell, mass, *seq, cell.left, 0), sequence_value(cell, mass, *seq))

    def test_reread_rule_never_beats_the_optimum(self):
        for cell in islice(ch.grid(ch.GRID2), 11, 4608, 613):
            for mass in cell.roots().values():
                self.assertFalse(better(ch.best_reread(cell, mass)[0], optimum(cell, mass, cell.left)))

    def test_vote_class_never_beats_the_optimum_in_round_two(self):
        for cell in islice(ch.grid(ch.GRID2), 0, 4608, 257):
            v = evaluate(cell, vote=True)
            self.assertFalse(better(v["fix_v"], v["opt"]), cell)
            self.assertFalse(better(v["fix_x"], v["fix_v"]), cell)


class Invariants(unittest.TestCase):
    def test_reference_order_on_a_grid_sample(self):
        for cell in islice(ch.grid(), 0, 2916, 37):
            v = evaluate(cell)
            self.assertGreaterEqual(v["oracle"][0], v["opt"][0] - ch.TIE, cell)
            for weaker in ("fix_x", "opt_no_read", "retry_then_switch", "read_first"):
                self.assertFalse(better(v[weaker], v["opt"]), (cell, weaker))
            self.assertFalse(better(v["fix"], v["fix_x"]), cell)
            self.assertLessEqual(v["opt"][0], 1 + ch.TIE)

    def test_policy_sees_only_the_first_detail(self):
        # Roots are keyed by the public label only and sum to the prior.
        cell = Cell(detail="strong", q_commit=0.3)
        roots = cell.roots()
        self.assertEqual(set(roots), {"timeout", "error"})
        self.assertAlmostEqual(sum(sum(m) for m in roots.values()), 1.0)

    def test_optimum_respects_budget(self):
        cell = Cell(left=0, q_commit=0.3)
        mass = cell.roots()["timeout"]
        self.assertAlmostEqual(optimum(cell, mass, 0)[1], 0.0)


if __name__ == "__main__":
    unittest.main()
