"""Permissions, bindings, and full recovery-loop regression checks."""
from fractions import Fraction as F
import json
from unittest import TestCase

from .gate17 import DEFAULTS
from .gate18 import BTM_RETRY, DecisionFailure, planner_for, public_view
from .gate19 import (
    EXTRACT, SELECT, bind_and_execute, conditional_likelihood, expected_evidence, forecast_replays,
    initial_session, replay, request_for, selected_action, verified_view,
)
from .workflow17 import Tape, Workflow

FIT = {"stay": F(9, 10), "emission": F(9, 10), "backup": F(1), "support": {}}
HISTORY = {"recovery": [], "switch": []}
MODEL = {"model": "mock", "temperature": 1, "max_tokens": 100, "seed": 0, "timeout_seconds": 10}
TAPE = Tape(("hidden-split", "archive", 1821, 0), (True,) * 3, (True,) * 3, True, True)


class EvidenceModel:
    def call(self, request, record):
        self.request = request
        public = json.loads(request["messages"][-1]["content"])["observation"]
        record["latency_seconds"] = 0
        return EXTRACT, expected_evidence(public)


class Gate19Tests(TestCase):
    def test_action_only_binding_and_wrong_arguments(self):
        session = Workflow(DEFAULTS, TAPE)
        view = session.view()
        with self.assertRaises(DecisionFailure):
            selected_action(view, (SELECT, {"action": "B_acquire", "retention": " 90d "}))
        with self.assertRaises(DecisionFailure):
            selected_action(view, (SELECT, {"action": "B_register"}))
        self.assertEqual(session.view(), view)
        action = selected_action(view, (SELECT, {"action": "B_acquire"}))
        next_view, binding = bind_and_execute(session, view, action)
        self.assertEqual(binding["arguments"]["retention"], "90d")
        self.assertEqual(binding["receipt_index"], 0)
        with self.assertRaises(DecisionFailure):
            bind_and_execute(session, view, "B")
        _, downstream = bind_and_execute(session, next_view, "B")
        self.assertEqual(downstream["arguments"], {"credential": session.events[0]["output"]["credential"]})
        self.assertEqual(session.audit()["score"]["issues"], [])

    def test_extraction_is_only_permission_and_no_hidden_outcomes(self):
        original = Workflow(DEFAULTS, TAPE).view()
        modified = Workflow(DEFAULTS, TAPE._replace(a=(False,) * 3, extra=False, signal=False)).view()
        planner = planner_for(DEFAULTS, FIT)
        for arm in ("btm", "btm_retry", "memory", "hybrid", "no_history"):
            with self.subTest(arm=arm):
                r = request_for(original, arm, MODEL, 1, 0, planner, FIT, HISTORY)
                self.assertEqual(r, request_for(modified, arm, MODEL, 1, 0, planner, FIT, HISTORY))
                self.assertNotIn("hidden-split", str(r))
                function = EXTRACT if arm == "hybrid" else SELECT
                self.assertEqual([t["function"]["name"] for t in r["tools"]], [function])
                self.assertEqual(r["tool_choice"]["function"]["name"], function)
        with self.assertRaises(DecisionFailure):
            verified_view(original, ("B_acquire", {}))
        with self.assertRaises(DecisionFailure):
            verified_view(original, (EXTRACT, {**expected_evidence(public_view(original)), "outcome": "success"}))
        retry = request_for(original, "btm_retry", MODEL, 1, 0, planner, FIT, HISTORY)
        base = request_for(original, "btm", MODEL, 1, 0, planner, FIT, HISTORY)
        retry["messages"][0]["content"] = retry["messages"][0]["content"].removesuffix("\n" + BTM_RETRY)
        self.assertEqual(base, retry)

    def test_multi_turn_engine_diagnosis_and_branch(self):
        cell = {**DEFAULTS, "fee": "1/20"}
        planner = planner_for(cell, FIT)
        model = EvidenceModel()
        run = replay(Workflow(cell, TAPE), "hybrid", planner, FIT, HISTORY, model, MODEL)
        control = replay(Workflow(cell, TAPE), "parser_control", planner, FIT, HISTORY)
        self.assertTrue(run["score"]["legal_success"])
        self.assertEqual(run["decisions"], control["decisions"])
        self.assertEqual(run["diagnostic_fee"], F(1, 20))
        self.assertEqual(run["decisions"][0]["action"], "diagnose")
        self.assertEqual(run["decisions"][-1]["slot"], 2)
        self.assertEqual(len(run["requests"]), len(run["decisions"]))
        self.assertTrue(all(step["decision_engine"] for step in run["checkpoints"]))
        self.assertTrue(any(step["evidence"]["route"] == "required" for step in run["checkpoints"]))

    def test_stale_evidence_and_certified_stop(self):
        session = initial_session(DEFAULTS, TAPE._replace(a=(False,) * 3, b=(False,) * 3), True)
        view = session.view()
        evidence = expected_evidence(public_view(view))
        with self.assertRaises(DecisionFailure):
            verified_view(view, (EXTRACT, {**evidence, "observation_index": 0}))
        result = replay(session, "hybrid", planner_for(DEFAULTS, FIT), FIT, HISTORY, EvidenceModel(), MODEL)
        self.assertEqual(result["termination"], "blocked_stop")
        self.assertEqual(result["offset"], 2)
        self.assertEqual(len(result["requests"]), 1)

    def test_forecasts_use_suffix_fees(self):
        planner = planner_for(DEFAULTS, FIT)
        rows = forecast_replays(Workflow(DEFAULTS, TAPE), planner, FIT)
        later_stop = next(row for row in rows if row["view"]["current_node"] == "register"
                          and row["action"] == "stop")
        self.assertEqual(later_stop["actual"], (0, 0, 0))
        self.assertEqual(conditional_likelihood([], F(1, 2), F(9, 10)), 1)
