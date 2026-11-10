from unittest import TestCase

from .general import Session, facts
from .gate13 import estimate, fit


class Gate13Tests(TestCase):
    def test_same_observation_and_real_duplicate(self):
        good = Session("appointment", "verify", "hint", 1, False)
        bad = Session("appointment", "verify", "hint", 1, True)
        self.assertEqual(good.view(), bad.view())
        self.assertTrue(good.finish("retry")["legal_success"])
        row = bad.finish("retry")
        self.assertFalse(row["legal_success"])
        self.assertEqual(row["duplicates"], 1)
        checked = Session("appointment", "verify", "hint", 1, True).finish("verify")
        self.assertTrue(checked["legal_success"])
        self.assertEqual((checked["tool_fee"], checked["diagnostic_fee"]), (0, 1))

    def test_refresh_provenance_and_independent_ledger(self):
        session = Session("publish", "refresh", "hint", 1, True)
        self.assertTrue(session.finish("refresh")["legal_success"])
        session.events[-1]["arguments"]["permit"] = "forged"
        session.ledger[-1]["fee"] = 0
        self.assertIn("binding or tool response mismatch", session.audit()["issues"])
        self.assertIn("ledger mismatch", session.audit()["issues"])

    def test_action_value_reprices_across_families(self):
        rows = []
        for arm in ("retry", "switch", "refresh"):
            train = Session("parcel", "refresh", "hint", 1, True)
            rows.append({"view": train.view(), "first": arm, **train.finish(arm)})
        learned = fit(rows)
        for price, expected in ((1, "refresh"), (5, "switch")):
            view = Session("publish", "refresh", "hint", price, True).view()
            self.assertEqual(estimate(view, facts(view), learned), (expected, []))
