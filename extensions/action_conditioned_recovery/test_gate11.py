from fractions import Fraction as F
import unittest

from .audit_gate11 import feedback_costs
from .learn import fit, repriced_values, select, threshold


class Gate11Tests(unittest.TestCase):
    def test_fit_separates_direct_and_failed_retry_switch(self):
        def row(arm, recovered, success):
            decisions = [{"action": "switch"}] if arm == "switch" else [
                {"action": "retry", "recovered": recovered}]
            if arm != "switch" and not recovered:
                decisions.append({"action": "switch"})
            return {
                "views": [{"context": "A", "history": [{"tool": "primary", "output": {"error": "fault"}}]}],
                "arm": arm, "decisions": decisions,
                "ledger": [{"calls": [0]} for _ in decisions],
                "events": [{"tool": "fallback"}],
                "score": {"legal_success": success}, "tool_fee": 1, "diagnostic_fee": 0,
            }
        fitted = fit([row("switch", False, True), row("retry_then_switch", True, True),
                      row("retry_then_switch", False, False)])
        self.assertEqual(fitted["context"]["A"], F(1, 2))
        self.assertEqual(fitted["continuations"]["A"], {
            "direct_switch": {"n": 1, "mean": 1},
            "retry_success": {"n": 1, "mean": 1},
            "retry_switch": {"n": 1, "mean": 0},
        })

    def test_repricing_and_fallback(self):
        view = {"context": "A", "prices": {"retry_success": 3, "retry_failure": 1, "switch": 5}}
        branches = {b: {"mean": F(1), "n": 4} for b in
                    ("direct_switch", "retry_success", "retry_switch")}
        fitted = {"context": {"A": F(1, 2)}, "continuations": {"A": branches}}
        self.assertEqual(repriced_values(view, F(1, 2), branches)["retry_then_switch"], (1, F(9, 2)))
        for price in (3, 4, 5):
            view["prices"]["switch"] = price
            self.assertEqual(select("repriced_action_values", view, fitted), threshold(view, F(1, 2)))
        branches["retry_switch"]["mean"] = F(1, 2)
        self.assertEqual(select("repriced_action_values", view, fitted), "switch")
        del branches["retry_switch"]
        self.assertIsNone(repriced_values(view, F(1, 2), branches))
        self.assertEqual(select("repriced_action_values", view, fitted), "retry_then_switch")

    def test_feedback_exact_and_null(self):
        values = feedback_costs((F(4, 5), F(1, 5)))
        self.assertEqual(min(values, key=values.__getitem__), "retry_then_switch/switch")
        self.assertEqual(min(values.values()), F(37, 20))
        self.assertEqual(values["switch/switch"], 2)
        self.assertEqual(values["retry_then_switch/retry_then_switch"], 2)
        self.assertEqual(set(feedback_costs((F(1, 2), F(1, 2))).values()), {F(2)})
