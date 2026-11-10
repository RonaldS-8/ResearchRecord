from fractions import Fraction as F
from unittest import TestCase

from .gate16 import rank
from .gate17 import DEFAULTS, model, witnesses
from .planning17 import HALF, choose
from .workflow16 import Progress
from .workflow17 import Tape, Workflow, sample

from pathlib import Path
from tempfile import TemporaryDirectory


class Gate17Tests(TestCase):
    def test_routing_history_and_stopping_witnesses(self):
        with TemporaryDirectory() as path:
            witnesses(Path(path))

    def test_keyed_randomness_and_no_future_leak(self):
        cell = {**DEFAULTS, "stay": "9/10", "backup": "1"}
        identity = ("test", "appointment", 1721, 0)
        tape = sample(cell, identity)
        self.assertEqual(tape, sample(cell, identity))
        ready = Tape(identity, (True,) * 3, (True,) * 3, True, True)
        short = ready._replace(extra=False)
        a, b = Workflow(cell, ready), Workflow(cell, short)
        self.assertEqual(a.view(), b.view())
        self.assertEqual(a.act("diagnose"), b.act("diagnose"))
        self.assertEqual(a.act("A"), b.act("A"))
        self.assertFalse(a.act("A")["done"])
        self.assertTrue(b.act("A")["done"])
        self.assertEqual(a.audit()["used_random_keys"], ["probe:0", "A:0", "transition:1",
                                                         "A:1", "route:1", "transition:2"])

    def test_long_checks_budget_and_strict_effect(self):
        cell = {**DEFAULTS, "checks": 2, "budget": 5}
        tape = Tape(("test", "archive", 0, 0), (False, False, False), (True,) * 3, True, False)
        run = Workflow(cell, tape)
        for action in ("A", "B", "A", "B", "A"):
            run.act(action)
        self.assertEqual(run.audit()["termination"], "exhausted")
        self.assertEqual(run.audit()["recovery_calls"], 7)
        self.assertEqual(run.audit()["score"]["issues"], [])
        run.events[2]["arguments"] = {"credential": "forged"}
        self.assertIn("dependency or terminal effect mismatch", run.audit()["score"]["issues"])

    def test_short_lookahead_loses_but_closed_rule_matches(self):
        cell = DEFAULTS
        planner = model(cell, F(9, 10), F(1))
        tape = Tape(("test", "archive", 0, 0), (False,) * 3, (True,) * 3, True, False)
        view = Workflow(cell, tape).view()
        self.assertEqual(choose("two_slot", planner, view), "B")
        self.assertEqual(choose("full_plan", planner, view), "A")
        self.assertEqual(choose("closed_three", planner, view), "A")
        state = Progress(0, (), 6, True)
        self.assertEqual(max(planner.values(state, HALF).values(), key=rank),
                         max(planner.closed(state, HALF).values(), key=rank))
