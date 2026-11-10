from fractions import Fraction as F
import json
from unittest import TestCase

from .gate14 import CONFIG, Recovery, Realization, exact_policy, history_key, simple_policy, support
from .multistep import REPORTS
from .run import execute, score


class Gate14Tests(TestCase):
    def test_probe_only_observes_and_is_billed(self):
        cell = {"cue": True, "accuracy": "4/5", "fee": "1/10", "execution": False}
        a = Recovery("invoice", cell, Realization(True, False, True, True, True, REPORTS[0]))
        b = Recovery("invoice", cell, Realization(False, True, False, True, False, REPORTS[1]))
        self.assertEqual(a.view(), b.view())
        before = a.view()["history"]
        self.assertEqual(a.act("diagnose")["history"], before)
        self.assertEqual(a.audit()["tool_fee"], 0)
        self.assertEqual(a.audit()["diagnostic_fee"], F(1, 10))
        with self.assertRaises(ValueError):
            a.act("diagnose")
        a.act("retry")
        self.assertEqual(history_key(a.view()), (True, (("diagnose", True), ("retry", REPORTS[0]))))
        self.assertEqual(a.audit()["tool_fee"], 1)
        a._diagnosis[0]["fee"] = F(0)
        self.assertIn("Independent recovery bill mismatch", a.audit()["score"]["issues"])

    def test_second_failure_preserves_first_report(self):
        cell = {"cue": False, "accuracy": "1/2", "fee": "1/10", "execution": True}
        a = Recovery("invoice", cell, Realization(True, False, False, None, True, REPORTS[0]))
        a.act("retry")
        a.act("retry")
        self.assertEqual(history_key(a.view()), (None, (("retry", REPORTS[0]), ("retry", None))))
        a.act("switch")
        self.assertEqual(score(a.audit()), (1, 4))

    def test_exact_values_and_simple_rule_on_each_cell(self):
        config = json.loads(CONFIG.read_text())
        for name, cell in config["cells"].items():
            with self.subTest(cell=name):
                samples = list(support(cell))
                value, optimal = exact_policy(samples, cell)
                self.assertEqual(value, (1, F(cell["expected"])))
                for _, sample in samples:
                    a = execute(Recovery(config["family"], cell, sample), optimal)
                    b = execute(Recovery(config["family"], cell, sample), simple_policy("simple_probe"))
                    self.assertEqual(a["decisions"], b["decisions"])
                    self.assertEqual(a["diagnostic_ledger"], b["diagnostic_ledger"])
