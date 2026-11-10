from fractions import Fraction as F
from unittest import TestCase

from .gate12 import last_error, recovery_policy, support
from .multistep import INITIAL_ERROR, REPORTS, Session


class Gate12Tests(TestCase):
    def test_equal_initial_views_and_legal_distinct_failure_feedback(self):
        high = Session("invoice", "M", (False, True, REPORTS[0]))
        low = Session("invoice", "M", (False, False, REPORTS[1]))
        opposite = Session("invoice", "M", (False, False, REPORTS[0]))
        self.assertEqual(high.view(), low.view())
        self.assertEqual(last_error(high.view()), INITIAL_ERROR)
        high_view, low_view = high.act("retry"), low.act("retry")
        self.assertEqual(high_view, opposite.act("retry"))
        self.assertEqual(high_view["decisions"], low_view["decisions"])
        self.assertEqual(high_view["actions"], low_view["actions"])
        self.assertNotEqual(last_error(high_view), last_error(low_view))
        choose = recovery_policy("known_feedback", {}, True)
        self.assertEqual(choose(high_view), "retry")
        self.assertEqual(choose(low_view), "switch")
        high.act("retry")
        low.act("retry")
        with self.assertRaises(ValueError):
            low.act("retry")
        self.assertTrue(high.audit()["score"]["legal_success"])
        self.assertEqual(high.audit()["tool_fee"], 2)
        low.act("switch")
        self.assertTrue(low.audit()["score"]["legal_success"])
        self.assertEqual(low.audit()["tool_fee"], 4)

    def test_both_families_check_effect_provenance_and_fees(self):
        for family in ("parcel", "invoice"):
            session = Session(family, "A", (False, False, REPORTS[1]))
            view = session.view()
            view["task"]["input"].clear()
            session.act("switch")
            self.assertTrue(session.audit()["score"]["legal_success"])
            session._ledger[-1]["tool_fee"] = 1
            self.assertIn("recovery ledger mismatch", session.audit()["score"]["issues"])
            session._events[-1]["arguments"] = {"reservation": "forged"}
            self.assertIn("workflow, binding, return or final effect", session.audit()["score"]["issues"])

    def test_weighted_support(self):
        for p in (F(1, 4), F(1, 2), F(3, 4)):
            for accuracy in (F(1, 2), F(4, 5)):
                cells = list(support(p, accuracy))
                self.assertEqual(sum(weight for weight, _ in cells), 1)
                failed_high = [(weight, state) for weight, state in cells
                               if not state[0] and state[2] == REPORTS[0]]
                self.assertEqual(sum(w for w, s in failed_high if s[1]) /
                                 sum(w for w, _ in failed_high), accuracy)
