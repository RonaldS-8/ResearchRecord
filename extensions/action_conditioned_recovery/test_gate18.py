"""Contracts for the full-trajectory agent pilot."""
from fractions import Fraction as F
import json
from unittest import TestCase

from .gate17 import DEFAULTS, likelihood
from .gate18 import (CONFIG, DecisionFailure, btm_prompt, evaluate, history_summary,
                     infer_action, planner_for, public_facts, public_view, request_for,
                     run_episode, test_cases as paired_cases, values)
from .gate17 import CONFIG as GATE17_CONFIG
from .workflow17 import Tape, Workflow

FIT = {"emission": F(9, 10), "stay": F(9, 10), "backup": F(1),
       "train_A_sequences": 16, "train_B_attempts": 16, "marginal": F(1, 2)}
MODEL = {"model": "mock", "temperature": 1, "max_tokens": 100, "seed": 0,
         "tool_choice": "auto", "timeout_seconds": 10}
TAPE = Tape(("hidden-split", "archive", 1821, 0),
            (False, True, True), (True, True, True), True, True)


class ScriptedModel:
    def __init__(self, actions):
        self.actions = iter(actions)

    def call(self, request, record):
        public = json.loads(request["messages"][-1]["content"])["observation"]
        action = next(self.actions)
        arguments = public_facts(public)["arguments"] if action[:2] in ("A_", "B_") else {}
        record["latency_seconds"] = 0
        return action, arguments


class Gate18Tests(TestCase):
    def test_requests_depend_only_on_observed_results(self):
        a = Workflow(DEFAULTS, TAPE)
        b = Workflow(DEFAULTS, TAPE._replace(a=(False, False, False), extra=False, signal=False))
        planner = planner_for(DEFAULTS, FIT)
        for action in (None, "A", "B"):
            if action:
                a.act(action)
                b.act(action)
            for arm in ("react", "memory", "hybrid", "btm"):
                def request(workflow):
                    view = workflow.view()
                    return request_for(view, arm, MODEL, 1, 0, FIT,
                                       {"recovery": [], "switch": []}, values(planner, view))
                left = request(a)
                self.assertEqual(left, request(b))
                self.assertNotIn("hidden-split", str(left))

    def test_bindings_after_failure_and_after_routing(self):
        run = Workflow(DEFAULTS, TAPE)
        planner = planner_for(DEFAULTS, FIT)
        for name in ("A_acquire", "B_acquire", "B_register", "A_verify"):
            view = run.view()
            expected = public_facts(public_view(view))
            self.assertTrue(expected["arguments"])
            with self.assertRaises(DecisionFailure):
                infer_action(view, "react", (name, {"credential": "invented"}), None)
            with self.assertRaises(DecisionFailure):
                infer_action(view, "hybrid", ("record_public_facts",
                             {**expected, "receipt_index": -8}), values(planner, view))
            run.act(infer_action(view, "react", (name, expected["arguments"]), None))
        self.assertTrue(run.audit()["score"]["legal_success"])

    def test_full_agent_billing_and_history_uses_episode_results(self):
        planner = planner_for(DEFAULTS, FIT)
        actions = ("diagnose", "A_acquire", "B_acquire", "B_register", "A_verify")
        row = run_episode(Workflow(DEFAULTS, TAPE), "react", planner, FIT, {},
                          ScriptedModel(actions), MODEL, 1, 8)
        metrics, _ = evaluate(TAPE, {"react": row})
        self.assertEqual(metrics["react"]["complete"], 1)
        self.assertEqual(metrics["react"]["diagnostic_calls"], 1)
        self.assertEqual(metrics["react"]["diagnostic_fee"], 1)
        self.assertEqual(metrics["react"]["redundant_tool_calls"], 1)
        self.assertEqual(len(row["requests"]), 5)
        summary = history_summary([row])
        self.assertEqual(summary["recovery"][0]["n"], 1)
        self.assertEqual(summary["switch"], [{"key": ("A_acquire", "B_acquire"),
                                              "n": 1, "successes": 1}])
        error = row["views"][0]["history"][1]["output"]["error"]
        self.assertIn("0.667 (n=1)", btm_prompt("btm", summary, error))
        self.assertIn("at least once", btm_prompt("btm", summary, error))
        self.assertNotIn("at least once", btm_prompt("btm_no_retry", summary, error))
        self.assertNotIn("(n=", btm_prompt("btm_uniform", summary, error))

    def test_common_stop_and_matched_stale_tapes(self):
        config = json.loads(CONFIG.read_text())
        gate17 = json.loads(GATE17_CONFIG.read_text())
        cases = {(name, family, seed): (cell, cohort, tape)
                 for name, cell, cohort, family, seed, tape in paired_cases(config, gate17)}
        self.assertEqual(len(cases), 28)
        matched = cases["independent", "archive", 1821]
        stale = cases["independent_stale", "archive", 1821]
        self.assertEqual((matched[0], matched[2]), (stale[0], stale[2]))
        self.assertNotEqual(matched[1], stale[1])
        cell, _, tape = cases["blocked", "archive", 1821]
        run = Workflow(cell, tape)
        run.act("A")
        run.act("B")
        self.assertEqual(run.view()["actions"], ["stop"])
        row = run_episode(run, "react", None, {}, {}, ScriptedModel(("stop",)), MODEL, 1, 8)
        metrics, _ = evaluate(tape, {"react": row})
        self.assertEqual(metrics["react"]["correct_stop"], 1)
        self.assertEqual(metrics["react"]["tool_fee"], 0)

    def test_emission_calibration_likelihood(self):
        sequence = (True, True, False)
        for accuracy in (F(1, 2), F(3, 5), F(9, 10)):
            self.assertEqual(likelihood(sequence, F(1, 2), accuracy), F(1, 8))
        self.assertNotEqual(likelihood(sequence, F(9, 10), F(9, 10)), F(1, 8))
