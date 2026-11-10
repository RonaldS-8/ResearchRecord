"""Checks for the contextual contract and preregistered exact witnesses."""

from fractions import Fraction as F
import json
from unittest import TestCase

from . import gate21, gate22
from .workflow21 import Preparation, World, Workflow, binding, execute_action


class ContextualRecoveryTests(TestCase):
    def test_preparation_is_public_evidence_and_not_an_execution_argument(self):
        prep = Preparation("portable", True, F(4, 5))
        left = Workflow("archive", World((False, True, True), True, True), F(4, 5), preparation=prep)
        right = Workflow("archive", World((False, True, False), False, False), F(4, 5), preparation=prep)
        self.assertEqual(left.view(), right.view())
        view = execute_action(left, "A")
        self.assertEqual(view, execute_action(right, "A"))
        self.assertEqual(binding(view, "B")["arguments"],
                         {"credential_id": "request", "retention": "90d", "scope": "portable"})
        execute_action(left, "B")
        self.assertNotIn("register_native", left.view()["actions"])
        execute_action(left, "verify")
        execute_action(left, "register_native")
        row = left.audit()
        self.assertTrue(row["score"]["legal_success"])
        self.assertEqual(row["effect"]["scope"], "portable")
        self.assertEqual(row["diagnostic_fee"], 0)

    def test_all_registered_reversals_and_ablation_expectations(self):
        config = json.loads(gate22.CONFIG.read_text())
        inherited = json.loads(gate21.CONFIG.read_text())
        results = gate22.witnesses(gate22.mechanism_laws(config, inherited))
        self.assertEqual(set(results), set(config["cells"]))
        self.assertTrue(all(len(records) == 4 for records in results.values()))
