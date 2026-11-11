"""Gate 32 and 33 CPU protocol witnesses; these are not real Agent training outcomes."""

from copy import deepcopy
import json
from types import SimpleNamespace
import unittest

from extensions.toolmaze_agent_recovery.methods import (
    recovery_context, sequential_write_context, simple_feedback_action, unknown_action_values,
)
from extensions.toolmaze_recovery.environment import RELEASE_TIMEOUT, RecoverySession, evaluate
from extensions.toolmaze_recovery.run import (
    FeedbackRuleAgent, RELEASE_CONTRACT, WRITE_CONTRACT, enumerated_assignment, prepare_write_checkpoint,
    run_episode, sequential_contract,
)
from extensions.toolmaze_recovery.tasks import DEVELOPMENT
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
            self.assertEqual(checkpoint["lookup_failures"], 1)
            self.assertNotIn(WRITE, checkpoint["available"])
            self.assertNotIn(VERIFY, checkpoint["available"])
            # One failed lookup proves nothing, so the rule asks once more and then gives up.
            self.assertEqual(simple_feedback_action(checkpoint, WRITE_CONTRACT), LOOKUP)
            session.call("read_service_status", {"resource_id": "P-140"})
            self.assertEqual(context(session)["phase"], "commit_unknown")
            self.assertNotIn(WRITE, context(session)["available"])
            session.call(LOOKUP, {"request_ref": "HOLD-2702"})
            self.assertEqual(context(session)["lookup_failures"], 2)
            self.assertNotIn(WRITE, context(session)["available"])
            self.assertEqual(simple_feedback_action(context(session), WRITE_CONTRACT), "stop")
            # A lookup that answers after one failure clears the count and restores the evidence.
            session = self.session(fault, diagnosis_available=False)
            session.call(LOOKUP, {"request_ref": "HOLD-2702"})
            session.diagnosis_available = True
            session.call(LOOKUP, {"request_ref": "HOLD-2702"})
            self.assertEqual(context(session)["lookup_failures"], 0)
            self.assertEqual(simple_feedback_action(context(session), WRITE_CONTRACT),
                             WRITE if fault == "write_not_committed" else VERIFY)
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

    def protocol_agent(self):
        """A scripted client that binds only from the conversation and obeys a required tool."""
        agent, _ = fake_agent([])
        requests = []

        def create(**kwargs):
            requests.append(deepcopy(kwargs))
            previous = json.loads(kwargs["messages"][-1]["content"])
            required = kwargs.get("tool_choice", {}).get("function", {}).get("name")
            if len(requests) == 1 or required == LOOKUP:
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
            if previous.get("status") != "active" or required:
                message = {"role": "assistant", "content": "", "tool_calls": [{
                    "id": f"cpu_{len(requests)}", "type": "function",
                    "function": {"name": tool, "arguments": json.dumps(args)},
                }]}
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                model_dump=lambda **_: message))], usage=None)

        agent.client.chat.completions.create = create
        return agent, requests

    def witness(self, fault, rule):
        session = self.session(fault)
        agent, requests = self.protocol_agent()
        controlled = FeedbackRuleAgent(agent, enforce=rule == "enforced") if rule else agent
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
        # run_episode leaves the shared first request alone; only the launcher constrains it.
        self.assertNotIn("tool_choice", requests[0])
        decided = list(zip(result["checkpoints"][1:], requests[1:]))
        self.assertTrue(decided)
        for checkpoint, request in decided:
            offered = [t["function"]["name"] for t in request["tools"]]
            system = request["messages"][0]["content"]
            self.assertIsNone(checkpoint["assignment"])
            self.assertTrue(checkpoint["model_action"]["accepted"])
            if rule == "enforced":
                # Enforced: one tool offered, and the request itself requires a call to it.
                self.assertEqual(offered, [checkpoint["rule_selected"]])
                self.assertEqual(request["tool_choice"]["function"]["name"], checkpoint["rule_selected"])
                self.assertIn(f"Recovery control selected {checkpoint['rule_selected']}.", system)
            elif rule == "advice":
                # Advice: nothing is removed or required; the suggestion is only a sentence.
                self.assertEqual(len(offered), 6)
                self.assertNotIn("tool_choice", request)
                self.assertIn(f"Recovery advice suggests {checkpoint['rule_selected']} as the next tool.", system)
                self.assertNotIn("Recovery control", system)
            else:
                self.assertEqual(len(offered), 6)
                self.assertNotIn("tool_choice", request)
                self.assertEqual(system, requests[0]["messages"][0]["content"])
                self.assertIsNone(checkpoint["rule_selected"])
                self.assertNotIn("rule_followed", checkpoint)
            if rule:
                self.assertEqual(checkpoint["rule_mode"], rule)
                self.assertTrue(checkpoint["rule_followed"])
                self.assertIn(rule if rule == "enforced" else "advice_only",
                              checkpoint["values"]["stop"]["continuation"])
        return requests

    def test_native_and_rule_protocol_witnesses_and_equal_first_requests(self):
        streams = [self.witness(fault, rule) for rule in (None, "enforced", "advice")
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
        self.assertFalse(result["checkpoints"][0]["rule_followed"])
        self.assertIsNone(result["checkpoints"][0]["model_action"]["accepted"])

    def test_unfollowed_advice_is_recorded_and_changes_nothing_else(self):
        session = self.session()
        agent, requests = fake_agent([(LOOKUP, {"request_ref": "HOLD-2702"})])
        result = run_episode(FeedbackRuleAgent(agent, enforce=False), session, resume=True, first_tool=LOOKUP)
        advised = result["checkpoints"][1]
        self.assertEqual((advised["context"]["phase"], advised["rule_selected"], advised["rule_mode"]),
                         ("confirmed_absent", WRITE, "advice"))
        self.assertEqual(advised["model_action"]["tool"], "stop")
        self.assertFalse(advised["rule_followed"])
        self.assertEqual(len(requests[1]["tools"]), 6)
        self.assertNotIn("tool_choice", requests[1])
        self.assertFalse(result["strict_success"])
        self.assertEqual((len(result["events"]), result["effects"]), (3, []))

    def assigned(self, fault, tool, agent=None, phase="confirmed_absent"):
        session = self.session(fault)
        agent, requests = agent or self.protocol_agent()
        result = run_episode(agent, session, resume=True, first_tool=LOOKUP,
                             assignment=enumerated_assignment(phase, tool))
        for checkpoint in result["checkpoints"]:
            # One assigned branch is one observation. It never becomes an estimate.
            for value in checkpoint["values"].values():
                self.assertEqual((value["status"], value["support"], value["completion"]), ("unknown", 0, None))
                self.assertEqual(value["continuation"], "native Agent")
        return session, result, requests

    def test_assigned_action_is_required_once_and_recorded_against_the_actual_call(self):
        _, result, requests = self.assigned("write_not_committed", WRITE)
        self.assertTrue(result["strict_success"], result["issues"])
        first, branch, after = result["checkpoints"]
        self.assertEqual(branch["assignment"], {
            "phase": "confirmed_absent", "tool": WRITE, "schedule": "enumerated", "probability": 1.0,
            "applied": True, "followed": True,
        })
        self.assertEqual(branch["external_tool_constraint"], WRITE)
        self.assertEqual(branch["model_action"]["tool"], WRITE)
        self.assertTrue(branch["model_action"]["accepted"])
        self.assertIsNone(first["assignment"])
        self.assertIsNone(after["assignment"])
        self.assertIsNone(after["external_tool_constraint"])
        # A tool-level intervention on one request: every tool stays offered, no prompt is added,
        # and the continuation is the unconstrained native Agent.
        self.assertEqual(requests[1]["tool_choice"]["function"]["name"], WRITE)
        self.assertEqual(len(requests[1]["tools"]), 6)
        self.assertEqual(requests[1]["messages"][0], requests[0]["messages"][0])
        self.assertTrue(all("tool_choice" not in request for request in (requests[0], *requests[2:])))

        # Repeating the diagnosis is a second branch of the same checkpoint and is not repeated.
        _, result, requests = self.assigned("write_not_committed", LOOKUP)
        self.assertTrue(result["strict_success"], result["issues"])
        self.assertEqual([c["context"]["phase"] for c in result["checkpoints"]],
                         ["commit_unknown", "confirmed_absent", "confirmed_absent", "verify_existing"])
        self.assertEqual([bool(c["assignment"]) for c in result["checkpoints"]], [False, True, False, False])
        self.assertEqual(["tool_choice" in request for request in requests], [False, True, False, False, False])
        self.assertEqual(result["diagnostic_fee"], 2)

    def test_assignment_never_counts_an_unexecuted_or_unsupported_action(self):
        # The model answers instead of calling the assigned tool.
        ignoring = fake_agent([(LOOKUP, {"request_ref": "HOLD-2702"})])
        session, result, _ = self.assigned("write_not_committed", WRITE, ignoring)
        branch = result["checkpoints"][1]
        self.assertTrue(branch["assignment"]["applied"])
        self.assertFalse(branch["assignment"]["followed"])
        self.assertEqual((branch["model_action"]["tool"], branch["model_action"]["accepted"]), ("stop", None))
        self.assertFalse(result["strict_success"])
        self.assertEqual(session.effects, [])

        # The model calls the assigned tool with an invented reference and the executor rejects it.
        prefix = self.session().events[1]["arguments"]
        forging = fake_agent([(LOOKUP, {"request_ref": "HOLD-2702"}), (WRITE, {**prefix, "evidence_ref": "0" * 24})])
        session, result, _ = self.assigned("write_not_committed", WRITE, forging)
        branch = result["checkpoints"][1]
        self.assertTrue(branch["assignment"]["followed"])
        self.assertFalse(branch["model_action"]["accepted"])
        self.assertEqual((result["illegal_calls"], session.effects), (1, []))
        self.assertFalse(result["strict_success"])

        # The assigned tool is not supported by the public evidence, so nothing is required.
        _, result, requests = self.assigned("write_not_committed", VERIFY)
        branch = result["checkpoints"][1]
        self.assertEqual((branch["assignment"]["applied"], branch["external_tool_constraint"]), (False, None))
        self.assertFalse(branch["assignment"]["followed"])
        self.assertTrue(all("tool_choice" not in request for request in requests))
        self.assertTrue(result["strict_success"], result["issues"])

        # The assigned phase never occurs when the lookup finds the committed reservation.
        _, result, requests = self.assigned("write_response_lost", WRITE)
        self.assertTrue(all(c["assignment"] is None for c in result["checkpoints"]))
        self.assertTrue(all("tool_choice" not in request for request in requests))

        # An assignment is an intervention, not an arm, and has no stop or unknown phase.
        agent, _ = fake_agent([])
        with self.assertRaises(ValueError):
            run_episode(FeedbackRuleAgent(agent), self.session(), resume=True,
                        assignment=enumerated_assignment("confirmed_absent", WRITE))
        for phase, tool in (("resolved", WRITE), ("confirmed_absent", "stop"), ("confirmed_absent", "")):
            with self.assertRaises(ValueError):
                enumerated_assignment(phase, tool)

    def test_release_obligation_is_reconstructed_from_its_own_public_contract(self):
        goal = DEVELOPMENT["artifact-release"]
        scope = {"project": goal.project, "version": goal.version}
        for fault in ("write_not_committed", "write_response_lost"):
            session = RecoverySession("artifact-release", fault)
            names = [tool["name"] for tool in session.public()["tools"]]
            self.assertIs(sequential_contract(names), RELEASE_CONTRACT)
            release = lambda: sequential_write_context(public_events(session), RELEASE_CONTRACT)
            build = session.call("get_build_manifest", {"build_id": goal.resource})
            grant = session.call("get_project_publish_permission", {"project": goal.project})
            self.assertIsNone(release())
            arguments = {**scope, "sha256": goal.digest, "build_ref": build["build_ref"],
                         "permission_ref": grant["permission_ref"]}
            self.assertEqual(session.call("publish_release", arguments), RELEASE_TIMEOUT)
            unknown = release()
            self.assertEqual(unknown["phase"], "commit_unknown")
            self.assertEqual(unknown["available"], [
                "inspect_project_release", "get_build_manifest", "read_artifact_mirror",
                "get_project_publish_permission", "stop"])
            self.assertEqual(simple_feedback_action(unknown, RELEASE_CONTRACT), "inspect_project_release")
            for private in (fault, "effects", *session.family_backend.records):
                self.assertNotIn(private, json.dumps(unknown))
            if fault == "write_not_committed":
                # A rejected, differently written query is not evidence of absence.
                other = deepcopy(session)
                other.call("inspect_project_release", {**scope, "version": "v" + goal.version})
                rejected = sequential_write_context(public_events(other), RELEASE_CONTRACT)
                self.assertEqual((rejected["phase"], rejected["lookup_failures"]), ("commit_unknown", 1))
                self.assertNotIn("publish_release", rejected["available"])
            found = session.call("inspect_project_release", scope)["release_ids"]
            checkpoint = release()
            if fault == "write_not_committed":
                self.assertEqual((checkpoint["phase"], checkpoint["release_ids"]), ("confirmed_absent", []))
                self.assertEqual(simple_feedback_action(checkpoint, RELEASE_CONTRACT), "publish_release")
                found = [session.call("publish_release", arguments)["release_id"]]
                checkpoint = release()
            self.assertEqual((checkpoint["phase"], checkpoint["release_ids"]), ("verify_existing", found))
            self.assertNotIn("publish_release", checkpoint["available"])
            self.assertEqual(simple_feedback_action(checkpoint, RELEASE_CONTRACT), "get_release_status")
            session.call("get_release_status", {"release_id": found[0]})
            self.assertIsNone(release())
            self.assertTrue(evaluate(session, "Done.")["strict_success"])
            # A read-back that shows another digest or state does not discharge the obligation.
            for field, value in (("sha256", "0" * 64), ("status", "withdrawn")):
                shown = public_events(session)
                shown[-1]["result"][field] = value
                self.assertIsNotNone(sequential_write_context(shown, RELEASE_CONTRACT))
        # Families without this write obligation get no sequential context, and the two never mix.
        for task, expected in (("stock-write-recovery", WRITE_CONTRACT), ("stock-reservation", None),
                               ("case-handoff", None), ("facility-access", None)):
            names = [tool["name"] for tool in RecoverySession(task).public()["tools"]]
            self.assertIs(sequential_contract(names), expected)
