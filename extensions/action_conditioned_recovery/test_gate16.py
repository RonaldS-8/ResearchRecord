from fractions import Fraction as F
import json
from unittest import TestCase

from .gate16 import CONFIG, DEFAULTS, Planner, rank
from .workflow16 import Progress, Workflow, World


class Gate16Tests(TestCase):
    def cell(self, name):
        return {**DEFAULTS, **json.loads(CONFIG.read_text())["cells"][name]}

    def values(self, name, cue=None):
        cell = self.cell(name)
        model = Planner(cell, F(cell["w"]))
        world = next(world for world, _ in model.support if world.cue == cue)
        view = Workflow(cell, world).view()
        return model.values(Progress(0, (), cell["budget"], True), model.belief(view, "full"))

    def test_routing_reverses_action_at_same_belief(self):
        for name, winner, difference in (("rare_extra", "B", F(97, 1600)),
                                         ("frequent_extra", "A", F(-109, 1600))):
            options = self.values(name)
            self.assertEqual(max(options, key=lambda a: rank(options[a])), winner)
            self.assertEqual(options["A"][1] - options["B"][1], difference)
        self.assertEqual(self.values("frequent_extra"), self.values("extra_checks"))

    def test_legal_history_changes_action(self):
        for cue, winner in ((True, "A"), (False, "B")):
            options = self.values("history_cue", cue)
            self.assertEqual(max(options, key=lambda a: rank(options[a])), winner)

    def test_routing_and_diagnosis_do_not_leak(self):
        cell = self.cell("frequent_extra")
        a = Workflow(cell, World((True, True), (True, True), True, None, False))
        b = Workflow(cell, World((True, False), (True, True), False, None, False))
        self.assertEqual(a.view(), b.view())
        self.assertEqual(a.act("diagnose"), b.act("diagnose"))
        self.assertEqual(a.audit()["diagnostic_fee"], 1)
        self.assertEqual(a.audit()["tool_fee"], 0)
        self.assertFalse(a.act("A")["done"])
        self.assertTrue(b.act("A")["done"])
        self.assertNotIn("diagnose", a.view()["actions"])
        a.act("A")
        self.assertTrue(a.audit()["score"]["legal_success"])

    def test_stop_and_budget_are_separate(self):
        cell = self.cell("unreliable_backup")
        blocked = Workflow(cell, World((False, False), (False, False), True, None, False))
        blocked.act("A")
        blocked.act("B")
        blocked.act("stop")
        self.assertEqual(blocked.audit()["termination"], "blocked_stop")
        exhausted = Workflow(self.cell("tight_budget"),
                             World((False, False), (True, True), True, None, False))
        for action in ("A", "B", "A"):
            exhausted.act(action)
        self.assertEqual(exhausted.audit()["termination"], "exhausted")
        premature = Workflow(cell, World((True, True), (True, True), True, None, False))
        premature.act("stop")
        self.assertEqual(premature.audit()["termination"], "premature_stop")
        for run in (blocked, exhausted, premature):
            self.assertEqual(run.audit()["score"]["issues"], [])
        exhausted.ledger[-1]["fee"] = 0
        self.assertIn("independent ledger mismatch", exhausted.audit()["score"]["issues"])

    def test_required_checks_and_terminal_write(self):
        run = Workflow(self.cell("extra_checks"), World((True, True), (True, True), True, None, False))
        run.act("A")
        run.act("B")
        self.assertTrue(run.audit()["score"]["legal_success"])
        self.assertEqual(run.audit()["recovery_calls"], 4)
        with self.assertRaises(ValueError):
            run.act("B")
        del run.events[1]
        self.assertFalse(run.audit()["score"]["legal_success"])
