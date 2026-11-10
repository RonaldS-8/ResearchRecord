"""Gate 23 prompt isolation, receipt grounding and paired billing tests."""

from fractions import Fraction as F
from unittest import TestCase

from . import gate21, gate22, gate23
from .gate18 import DecisionFailure
from .workflow21 import execute_action


class AgentEfficiencyTests(TestCase):
    def setUp(self):
        self.config = gate23.read(gate23.CONFIG)
        frozen, inherited = map(gate23.read, (gate22.CONFIG, gate21.CONFIG))
        laws = gate22.mechanism_laws(frozen, inherited)
        law = laws["full"]["portable"]
        follow = gate21.threshold(law, "full", True)
        memory, values = gate21.action_memory(law, follow)
        self.group = dict(memory=memory, values=values, contexts=gate23.Counter())
        self.btm = gate23.btm_history([], "Operation unavailable")
        self.settings = {"model": "fixture", "seed": 0, "temperature": 1, "max_tokens": 16000, "timeout_seconds": 300}
        self.cases = list(gate23.paired_cases(self.config, frozen, laws))

    def test_frozen_cases_and_public_projection(self):
        self.assertEqual(len(self.cases), 16)
        for start in range(0, 16, 4):
            group = self.cases[start:start + 4]
            self.assertEqual(len({item[0][2:] for item in group}), 1)
            self.assertEqual(len({item[3].quality for item in group}), 1)
            self.assertEqual(len({item[2].available for item in group}), 1)
        self.assertEqual(sum(prep.quality for _, _, _, prep in self.cases), 8)
        public = gate23.public_view(gate23.smoke_session("verify").view())
        self.assertNotIn("world", public)
        self.assertEqual(set(public["available_tools"]), {"B_acquire", "stop"})

    def test_prompt_isolation_and_evidence_validation(self):
        session = gate23.smoke_session("verify")
        view = session.view()
        requests = {arm: gate23.request_for(view, arm, self.settings, 2311, 0, self.group, self.btm, len)[0]
                    for arm in gate23.ARMS}
        for arm in ("no_history", "memory"):
            self.assertEqual(requests["btm"]["messages"][0], requests[arm]["messages"][0])
            self.assertEqual(requests["btm"]["tools"], requests[arm]["tools"])
        self.assertIn(gate23.BTM_RETRY, requests["btm_retry"]["messages"][0]["content"])
        self.assertIn("<tool_reliability>", requests["btm_full"]["messages"][0]["content"])
        self.assertEqual(len(requests["hybrid"]["tools"]), 1)
        evidence = gate23.expected_evidence(gate23.public_view(view))
        self.assertEqual(gate23.selected(view, (gate23.EXTRACT, evidence), "hybrid", self.group), "B")
        with self.assertRaises(DecisionFailure):
            gate23.selected(view, (gate23.EXTRACT, {**evidence, "outcome": "failure"}), "hybrid", self.group)
        with self.assertRaises(DecisionFailure):
            gate23.selected(view, (gate23.SELECT, {"action": "B_acquire", "scope": "portable"}), "btm", self.group)
        for action in ("B", "verify", "register_native"):
            execute_action(session, action)
        self.assertTrue(session.audit()["score"]["legal_success"])

    def test_joint_cost_scenario_and_unknown_usage(self):
        self.assertEqual(gate23.token_usage({"requests": [{"service_error": "timeout"}]}, self.config), (None, None))
        btm = {"model_usd": F("0.001"), "environment_fee": F(3)}
        memory = {"model_usd": F("0.002"), "environment_fee": F(2)}
        scenarios = gate23.paired_summary([(btm, memory)], self.config)["usd_scenarios"]
        self.assertEqual(scenarios["positive_break_even_usd_per_unit"], F("0.001"))
        self.assertEqual(scenarios["cheaper_side"], "above")
