"""Gate 32 CPU protocol witnesses; these are not real Agent training outcomes."""

from copy import deepcopy
import json
from types import SimpleNamespace
import unittest

from extensions.toolmaze_agent_recovery.methods import (
    recovery_context, sequential_write_context, simple_feedback_action, unknown_action_values,
)
from extensions.toolmaze_recovery.environment import RecoverySession, evaluate
from extensions.toolmaze_recovery.run import (
    FeedbackRuleAgent, WRITE_CONTRACT, prepare_write_checkpoint, run_episode,
)
from test_toolmaze_agent_recovery import fake_agent


LOOKUP = WRITE_CONTRACT["lookup"]
WRITE = WRITE_CONTRACT["write"]
VERIFY = WRITE_CONTRACT["verify"]


def public_events(session):
    return [{key: deepcopy(event[key]) for key in ("tool", "arguments", "result")}
            for event in session.events]


def context(session):
    return sequential_write_context(public_events(session), WRITE_CONTRACT)


class SequentialRecoveryTests(unittest.TestCase):
    def session(self, fault="write_not_committed", **kwargs):
        session = RecoverySession("stock-write-recovery", fault, **kwargs)
        prepare_write_checkpoint(session)
        return session

    def test_equal_public_prefix_and_unknown_values(self):
        sessions = [self.session(fault) for fault in ("write_not_committed", "write_response_lost")]
        self.assertEqual(sessions[0].public(), sessions[1].public())
        self.assertEqual(public_events(sessions[0]), public_events(sessions[1]))
        self.assertEqual(context(sessions[0]), context(sessions[1]))
        for session in sessions:
            self.assertIsNone(recovery_context(session.events, session.method_contract()))
            checkpoint = context(session)
            self.assertEqual(checkpoint["phase"], "commit_unknown")
            self.assertNotIn(WRITE, checkpoint["available"])
            self.assertNotIn(VERIFY, checkpoint["available"])
            values = unknown_action_values(checkpoint, "test-only continuation")
            for value in values.values():
                self.assertEqual(value["support"], 0)
                self.assertIsNone(value["completion"])
                self.assertIsNone(value["remaining_tool_fee"])
                self.assertEqual(value["continuation"], "test-only continuation")
            encoded = json.dumps(checkpoint)
            for private in (session.fault, "effects", "valid_paths", *session.reservations):
                self.assertNotIn(private, encoded)

    def test_not_found_keeps_checkpoint_until_actual_write_and_verification(self):
        session = self.session()
        prefix = public_events(session)
        session.call(LOOKUP, {"request_ref": "HOLD-2702"})
        checkpoint = context(session)
        self.assertEqual(checkpoint["phase"], "confirmed_absent")
        self.assertEqual(simple_feedback_action(checkpoint, WRITE_CONTRACT), WRITE)
        self.assertEqual(public_events(session)[:2], prefix)
        self.assertEqual(len(public_events(session)), 3)
        self.assertNotIn(VERIFY, checkpoint["available"])
        created = session.call(WRITE, dict(session.events[1]["arguments"]))
        self.assertEqual(context(session)["phase"], "verify_existing")
        self.assertNotIn(WRITE, context(session)["available"])
        self.assertFalse(evaluate(session, "Done.")["strict_success"])
        session.call(VERIFY, {"reservation_id": created["reservation_id"]})
        self.assertIsNone(context(session))
        result = evaluate(session, "Done.")
        self.assertTrue(result["strict_success"], result["issues"])
        self.assertEqual((result["tool_fee"], result["diagnostic_fee"]), (4, 1))

    def test_found_exposes_only_actual_ids_and_never_selects_another_write(self):
        session = self.session("write_response_lost")
        result = session.call(LOOKUP, {"request_ref": "HOLD-2702"})
        checkpoint = context(session)
        self.assertEqual(checkpoint["reservation_ids"], result["reservation_ids"])
        self.assertEqual(checkpoint["phase"], "verify_existing")
        self.assertNotIn(WRITE, checkpoint["available"])
        self.assertEqual(simple_feedback_action(checkpoint, WRITE_CONTRACT), VERIFY)
        session.call(VERIFY, {"reservation_id": result["reservation_ids"][0]})
        self.assertIsNone(context(session))
        self.assertTrue(evaluate(session, "Done.")["strict_success"])
        self.assertEqual(len(session.reservations), 1)

    def test_query_failure_and_connectivity_are_not_absence_evidence(self):
        for fault in ("write_not_committed", "write_response_lost"):
            session = self.session(fault, diagnosis_available=False)
            session.call(LOOKUP, {"request_ref": "HOLD-2702"})
            checkpoint = context(session)
            self.assertEqual(checkpoint["phase"], "commit_unknown")
            self.assertTrue(checkpoint["query_failed"])
            self.assertNotIn(WRITE, checkpoint["available"])
            self.assertNotIn(VERIFY, checkpoint["available"])
            self.assertEqual(simple_feedback_action(checkpoint, WRITE_CONTRACT), "stop")
            session.call("read_service_status", {"resource_id": "P-140"})
            self.assertEqual(context(session)["phase"], "commit_unknown")
            self.assertNotIn(WRITE, context(session)["available"])
        # An invalid request identifier returns an error, never a safe not_found.
        session = self.session()
        session.call(LOOKUP, {"request_ref": "HOLD-WRONG"})
        self.assertNotIn(WRITE, context(session)["available"])

    def test_forged_id_is_rejected_and_checkpoint_remains(self):
        session = self.session("write_response_lost")
        session.call(LOOKUP, {"request_ref": "HOLD-2702"})
        session.call(VERIFY, {"reservation_id": "invented-id"})
        self.assertEqual(session.events[-1]["result"]["code"], "invalid_argument")
        self.assertIsNotNone(context(session))
        self.assertFalse(evaluate(session, "Done.")["strict_success"])

    def test_budget_and_duplicate_obligations_do_not_become_safe_writes(self):
        session = self.session("write_response_lost")
        session.call(LOOKUP, {"request_ref": "HOLD-2702"})
        session.call(WRITE, dict(session.events[1]["arguments"]))
        session.call(LOOKUP, {"request_ref": "HOLD-2702"})
        self.assertEqual(len(context(session)["reservation_ids"]), 2)
        self.assertNotIn(WRITE, context(session)["available"])
        self.assertEqual(simple_feedback_action(context(session), WRITE_CONTRACT), "stop")
        while len(session.events) < 16:
            session.call(LOOKUP, {"request_ref": "HOLD-2702"})
        self.assertEqual(context(session)["available"], ["stop"])

    def witness(self, fault, rule):
        session = self.session(fault)
        agent, _ = fake_agent([])
        requests = []

        def create(**kwargs):
            requests.append(deepcopy(kwargs))
            previous = json.loads(kwargs["messages"][-1]["content"])
            if len(requests) == 1:
                tool, args = LOOKUP, {"request_ref": "HOLD-2702"}
            elif previous.get("status") == "not_found":
                # Bind exclusively from actual conversation, never session private state.
                original = kwargs["messages"][4]["tool_calls"][0]["function"]["arguments"]
                tool, args = WRITE, json.loads(original)
            elif previous.get("status") != "active":
                identifier = previous.get("reservation_id") or previous["reservation_ids"][0]
                tool, args = VERIFY, {"reservation_id": identifier}
            else:
                message = {"role": "assistant", "content": "Finished."}
            if previous.get("status") != "active":
                message = {"role": "assistant", "content": "", "tool_calls": [{
                    "id": f"cpu_{len(requests)}", "type": "function",
                    "function": {"name": tool, "arguments": json.dumps(args)},
                }]}
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                model_dump=lambda **_: message))], usage=None)

        agent.client.chat.completions.create = create
        controlled = FeedbackRuleAgent(agent) if rule else agent
        result = run_episode(controlled, session, resume=True, first_tool=LOOKUP)
        self.assertTrue(result["strict_success"], result["issues"])
        self.assertEqual(result["illegal_calls"], 0)
        self.assertEqual(len(result["effects"]), 1)
        phases = [c["context"]["phase"] for c in result["checkpoints"]]
        self.assertEqual(phases, ["commit_unknown", *(["confirmed_absent"] if fault == "write_not_committed" else []),
                                  "verify_existing"])
        self.assertEqual(result["checkpoints"][0]["external_tool_constraint"], LOOKUP)
        self.assertIsNone(result["checkpoints"][0]["rule_selected"])
        for checkpoint in result["checkpoints"]:
            self.assertEqual(checkpoint["sunk_fees"]["execution"] + checkpoint["realized_suffix_fees"]["execution"],
                             result["tool_fee"])
            self.assertEqual(checkpoint["sunk_fees"]["diagnosis"] + checkpoint["realized_suffix_fees"]["diagnosis"],
                             result["diagnostic_fee"])
            self.assertEqual(len(checkpoint["history"]), checkpoint["after"])
        if rule:
            for checkpoint, request in zip(result["checkpoints"][1:], requests[1:]):
                self.assertEqual([t["function"]["name"] for t in request["tools"]],
                                 [checkpoint["rule_selected"]])
        else:
            self.assertTrue(all(len(request["tools"]) == 6 for request in requests))
        return requests

    def test_native_and_rule_protocol_witnesses_and_equal_first_requests(self):
        streams = [self.witness(fault, rule) for rule in (False, True)
                   for fault in ("write_not_committed", "write_response_lost")]
        self.assertTrue(all(stream[0] == streams[0][0] for stream in streams))

    def test_rule_does_not_fabricate_call_or_complete_after_model_stops(self):
        session = self.session()
        agent, _ = fake_agent([])
        result = run_episode(FeedbackRuleAgent(agent), session, resume=True)
        self.assertFalse(result["strict_success"])
        self.assertEqual(len(result["events"]), 2)
        self.assertEqual(result["checkpoints"][0]["rule_selected"], LOOKUP)
        self.assertEqual(result["checkpoints"][0]["model_action"]["tool"], "stop")
