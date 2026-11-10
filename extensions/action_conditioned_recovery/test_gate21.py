"""Gate 21 receipt, observation and exact-witness checks."""

from fractions import Fraction as F
import json
from unittest import TestCase

from .gate21 import CONFIG, Law, episodes, historical, training, witnesses
from .workflow21 import World, Workflow, binding, execute_action


def configuration():
    config = json.loads(CONFIG.read_text())
    laws = {name: Law(**{key: F(value) for key, value in {**config["generating_rates"], **cell}.items()})
            for name, cell in config["cells"].items()}
    return config, laws


class MultipathRecoveryTests(TestCase):
    def test_future_events_are_hidden_and_credential_changes_menu(self):
        short = Workflow("archive", World((False, True, False), True, True), F(4, 5))
        native = Workflow("archive", World((False, True, True), False, False), F(4, 5))
        self.assertEqual(short.view(), native.view())
        self.assertEqual(execute_action(short, "A"), execute_action(native, "A"))
        self.assertEqual(execute_action(short, "B")["actions"], ("verify", "stop"))
        self.assertEqual(execute_action(native, "B")["actions"], ("register_native", "stop"))
        with self.assertRaises(ValueError):
            execute_action(short, "register_native")
        before_verify = binding(short.view(), "verify")
        execute_action(short, "verify")
        with self.assertRaises(ValueError):
            short.act("register_native", before_verify)
        execute_action(short, "register_native")
        self.assertTrue(short.audit()["score"]["legal_success"])

    def test_prepared_arguments_and_external_receipt(self):
        session = Workflow("archive", World((False, False, True), False, False), F(4, 5))
        correct = binding(session.view(), "C")
        self.assertEqual(correct["arguments"]["retention"], "90d")
        with self.assertRaises(ValueError):
            session.act("C", {"source": 0, "arguments": session.view()["task"]["input"]})
        execute_action(session, "C")
        with self.assertRaises(ValueError):
            execute_action(session, "register_native")
        execute_action(session, "register_external")
        row = session.audit()
        self.assertTrue(row["score"]["legal_success"])
        self.assertEqual(row["effect"]["credential"], "request:external")
        session.events[1]["source"] = 0
        self.assertFalse(session.audit()["score"]["legal_success"])

    def test_ledgers_and_stops(self):
        world = World((False, False, False), False, True)
        session = Workflow("appointment", world, F(4, 5))
        execute_action(session, "diagnose")
        self.assertEqual(session.state.budget, 5)
        with self.assertRaises(ValueError):
            execute_action(session, "diagnose")
        for action in ("B", "C", "A", "stop"):
            execute_action(session, action)
        row = session.audit()
        self.assertFalse(row["score"]["issues"])
        self.assertEqual((row["termination"], row["tool_fee"], row["diagnostic_fee"]),
                         ("blocked_stop", F("3.60"), F("0.05")))
        session.ledger[0]["fee"] = F(0)
        self.assertIn("independent ledger mismatch", session.audit()["score"]["issues"])
        tight = Workflow("appointment", world, F(4, 5), budget=2)
        execute_action(tight, "A")
        self.assertEqual(tight.audit()["termination"], "exhausted")
        early = Workflow("appointment", world, F(4, 5))
        execute_action(early, "stop")
        self.assertEqual(early.audit()["termination"], "premature_stop")

    def test_registered_witnesses_use_strict_replay(self):
        _, laws = configuration()
        self.assertEqual(len(witnesses(laws)), 8)

    def test_training_coverage_and_test_split(self):
        config, laws = configuration()
        law = laws["full"]
        train = training(law, config)
        natural = [row for row in train if not row["assigned"]]
        assigned = [row for row in train if row["assigned"]]
        self.assertEqual((len(natural), len(assigned)), (36, 36))
        _, sparse, _ = historical(natural, ("A", "B", "C"))
        _, balanced, _ = historical(assigned, ("A", "B", "C"))
        self.assertEqual(sparse["first"], dict(A=36, B=0, C=0))
        self.assertEqual(balanced["first"], dict(A=6, B=6, C=6))
        train_ids = {(row["family"], row["seed"], row["instance"]) for row in train}
        test_ids = {identity for identity, _ in episodes(law, config, "test")}
        self.assertEqual(len(test_ids), 64)
        self.assertFalse(train_ids & test_ids)
