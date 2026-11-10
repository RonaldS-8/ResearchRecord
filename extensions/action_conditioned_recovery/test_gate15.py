from fractions import Fraction as F
import json
from unittest import TestCase

from .gate15 import CONFIG, enumerate_policy, public_key, rule, support
from .run import execute, score
from .workflow15 import Workflow


class Gate15Tests(TestCase):
    def setUp(self):
        self.cells = json.loads(CONFIG.read_text())["cells"]

    def test_paired_views_and_probe_boundary(self):
        cell = self.cells["shared_cheap_probe"]
        a = Workflow(cell, (True, True), False)
        b = Workflow(cell, (False, False), True)
        self.assertEqual(a.view(), b.view())
        before = a.view()["history"]
        a.act("diagnose")
        self.assertEqual(a.view()["history"], before)
        self.assertEqual(a.audit()["diagnostic_fee"], F(1, 10))
        with self.assertRaises(ValueError):
            a.act("diagnose")
        b.act("A")
        self.assertEqual(b.view()["slot"], 0)
        self.assertNotIn("A", b.view()["actions"])
        b.act("B")
        self.assertEqual(b.view()["slot"], 1)

    def test_provenance_checks_duplicate_and_fees(self):
        cell = self.cells["shared_long"]
        run = Workflow(cell, (True, True), True)
        run.act("B")
        run.act("A")
        self.assertEqual(score(run.audit()), (1, F(13, 4)))
        with self.assertRaises(ValueError):
            run.act("B")
        run.events[-1]["arguments"] = {"credential": "forged"}
        self.assertFalse(run.audit()["score"]["legal_success"])
        run.ledger[-1]["fee"] = F(0)
        self.assertIn("independent ledger mismatch", run.audit()["score"]["issues"])
        skipped = Workflow(cell, (True, True), True)
        skipped.act("B")
        skipped.act("A")
        del skipped.events[1]
        self.assertFalse(skipped.audit()["score"]["legal_success"])

    def test_matrix_exact_and_cross_slot_rule(self):
        for name, cell in self.cells.items():
            with self.subTest(cell=name):
                samples = support(cell)
                value, plans = enumerate_policy(samples, cell)
                self.assertEqual(value, (1, F(cell["expected"])))
                for _, health, report in samples:
                    choose = lambda view: plans[public_key(view)]["optimal"][0]
                    exact = execute(Workflow(cell, health, report), choose)
                    simple = execute(Workflow(cell, health, report),
                                     lambda view: rule("cross_slot_rule", view))
                    self.assertEqual(simple["decisions"], exact["decisions"])
                    self.assertEqual(score(simple), score(exact))
                if cell["backups"] == 2:
                    self.assertEqual(plans[()]["choices"]["B"], plans[()]["choices"]["B2"])
                    self.assertIn("B2", plans[((0, "A", False),)]["optimal"])
