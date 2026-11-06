import copy
import unittest
from fractions import Fraction as F

from extensions.toolmaze_belief_ssp.enumeration import Pilot
from extensions.toolmaze_belief_ssp.replay import Replay, verify


class Gate7Tests(unittest.TestCase):
    def test_hand_calculated_transitions_and_diagnosis(self):
        model = Pilot(F(1, 4), F(3, 4), F(1, 4), F(1), F(1), F(3))
        self.assertEqual(model.prior, (F(3, 8), F(1, 8), F(1, 2)))
        first, posterior = model.failed(model.prior)
        second, twice = model.failed(posterior)
        self.assertEqual(first * second, F(25, 32))
        self.assertEqual(twice, (F(27, 100), F(9, 100), F(16, 25)))
        signal, p, posterior = list(model.diagnosis(model.prior))[1]
        self.assertTrue(signal)
        _, p2, _ = list(model.diagnosis(posterior))[1]
        self.assertEqual(p * p2, F(1, 8))
        value, actions = model.optimal((F(0), F(1), F(0)), 1)
        self.assertEqual((value, actions), ((1, 2), ("retry",)))
        self.assertEqual(model.optimal(model.prior, 0)[0], (0, 0))

    def test_replay_transition_isolation_and_validation(self):
        draws = iter([F(3, 4), F(0)])
        session = Replay("T", F(1, 4), F(3, 4), F(1, 4), {}, lambda: next(draws), lambda: F(1, 2))
        persistent = Replay("P", F(1, 4), F(3, 4), F(1, 4), {}, lambda: F(0), lambda: F(1, 2))
        self.assertEqual(session.view(), persistent.view())
        self.assertFalse(session.act("diagnose")["decisions"][-1]["report"])
        session.act("retry")
        self.assertTrue(session.events[-1]["blocked"])
        self.assertTrue(session.act("diagnose")["decisions"][-1]["report"])
        session.act("retry")
        self.assertEqual(sum(d["charge"] for d in session.decisions), F(1, 2))
        self.assertTrue(verify(session, session.events)["legal_success"])
        for mutation in ("missing", "wrong_argument", "forged", "wrong_source"):
            with self.subTest(mutation=mutation):
                events = copy.deepcopy(session.events)
                if mutation == "missing":
                    events.pop()
                elif mutation == "wrong_argument":
                    events[-1]["arguments"]["forged"] = True
                elif mutation == "forged":
                    events[-1]["output"] = {"forged": True}
                else:
                    events[-1]["node"] = session.victim
                self.assertFalse(verify(session, events)["legal_success"])
