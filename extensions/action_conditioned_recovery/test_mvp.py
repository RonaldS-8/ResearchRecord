import copy
from fractions import Fraction as F
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from extensions.action_conditioned_recovery.mvp import Session
from extensions.action_conditioned_recovery.run import run


class Gate9Tests(unittest.TestCase):
    def test_exact_values_match_paired_replay(self):
        with TemporaryDirectory() as path:
            result = run(Path(path))
            self.assertEqual(len(list(Path(path).glob("*.json"))), 24)
        self.assertEqual(result["A"]["best"], "retry_then_switch")
        self.assertEqual(result["A"]["values"]["retry_then_switch"], (1, F(3, 2)))
        self.assertEqual(result["B"]["best"], "switch")
        self.assertEqual(result["B"]["values"]["switch"], (1, 2))
        self.assertEqual(result["4/5"]["best"], (1, F(9, 5)))
        self.assertEqual(result["1/2"]["diagnose"], (1, F(21, 10)))
        self.assertEqual(result["1/2"]["best"], (1, 2))

    def test_isolation_and_action_budget(self):
        healthy = Session("feedback", "H", F(4, 5))
        blocked = Session("feedback", "P", F(4, 5))
        initial = blocked.view()
        self.assertEqual(healthy.view(), initial)
        serialized = json.dumps(initial)
        for field in ("state", "valid_paths", "execution_trace", "raw_output",
                      "perturbation_status", "prior_transient", "hazard"):
            self.assertNotIn(f'"{field}"', serialized)
        initial["history"][-1]["output"].clear()
        self.assertEqual(healthy.view(), blocked.view())
        blocked.act("diagnose")
        self.assertEqual(blocked.audit()["diagnostic_fee"], F(1, 10))
        with self.assertRaises(ValueError):
            blocked.act("diagnose")
        blocked.act("retry")
        with self.assertRaises(ValueError):
            blocked.act("retry")
        self.assertEqual(blocked.view()["actions"], ["switch", "stop"])
        blocked.act("switch")
        self.assertTrue(blocked.audit()["score"]["legal_success"])
        self.assertEqual(healthy.audit()["recovery_calls"], 0)
        self.assertEqual(healthy.view()["decisions"], [])

    def test_invalid_completion_is_rejected(self):
        session = Session("A", "P")
        session.act("switch")
        replay = session._backend
        self.assertTrue(session.audit()["score"]["legal_success"])
        for corruption in ("wrong_argument", "forged_output", "skipped_call", "reused_call"):
            events = copy.deepcopy(replay.events)
            if corruption == "wrong_argument":
                events[-1]["arguments"]["invented"] = True
            elif corruption == "forged_output":
                events[-1]["output"] = {"forged": True}
            elif corruption == "skipped_call":
                del events[replay.sunk]
                for index, event in enumerate(events):
                    event["call_id"] = index
            else:
                events.append(copy.deepcopy(events[-1]))
            with self.subTest(corruption=corruption):
                self.assertFalse(replay.verify(events, replay.target, False)["legal_success"])

    def test_recovery_ledger_detects_tampering(self):
        session = Session("A", "P", task="020", per_call=True)
        session.act("retry")
        session.act("switch")
        row = session.audit()
        self.assertTrue(row["score"]["legal_success"])
        self.assertEqual(row["tool_fee"], row["recovery_calls"])
        session._ledger[0]["tool_fee"] += 1
        self.assertIn("recovery ledger mismatch", session.audit()["score"]["issues"])
