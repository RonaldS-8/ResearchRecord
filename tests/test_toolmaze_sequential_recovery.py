"""Gate 32 and 33 CPU protocol witnesses; these are not real Agent training outcomes."""

from copy import deepcopy
import json
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from extensions.toolmaze_agent_recovery.methods import (
    recovery_context, sequential_write_context, simple_feedback_action, unknown_action_values,
)
from extensions.toolmaze_recovery.environment import RELEASE_TIMEOUT, RecoverySession, evaluate
from extensions.toolmaze_recovery.run import (
    FeedbackRuleAgent, RELEASE_CONTRACT, WRITE_CONTRACT, enumerated_assignment, prepare_write_checkpoint,
    run_episode, sequential_contract, smoke,
)
from extensions.toolmaze_recovery.tasks import DEVELOPMENT
from evaluation.agents.vllm_agent import VLLMAgent
from openai.types.chat import ChatCompletion
from test_toolmaze_agent_recovery import fake_agent


LOOKUP = WRITE_CONTRACT["lookup"]
WRITE = WRITE_CONTRACT["write"]
VERIFY = WRITE_CONTRACT["verify"]
# SHA-256 of the first SDK request shared by the eight Gate 33 episodes, as archived in experiment 035.
GATE33_FIRST_REQUEST = "e5a227c1052115acd5d03f138b7acfc3d000ce7fb5f10650ec44f611e20ea528"
# Experiment 036, written out here independently of run.py: the registered exit sentences.
EXIT_SYSTEM_STOP = (
    "- If you determine that a required step cannot be accomplished by any available tool or approach, "
    "stop the workflow and clearly report which step failed and why, rather than proceeding with incomplete results."
)
EXIT_SYSTEM_HALTED = (
    '- If HALTED: State clearly that the task was aborted and the reason (e.g., "Task aborted: the pricing tool '
    'returned corrupted data after retry and no other alternative approaches exist"). Do not apologize excessively.'
)
EXIT_USER_BLOCKED = "If unable to complete the task, start your final reply with 'Blocked:' and briefly explain."


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

    def release_session(self, fault):
        session = RecoverySession("artifact-release", fault)
        goal = session.goal
        build = session.call("get_build_manifest", {"build_id": goal.resource})
        grant = session.call("get_project_publish_permission", {"project": goal.project})
        arguments = {"project": goal.project, "version": goal.version, "sha256": goal.digest,
                     "build_ref": build["build_ref"], "permission_ref": grant["permission_ref"]}
        self.assertEqual(session.call("publish_release", arguments), RELEASE_TIMEOUT)
        return session, arguments

    def protocol_agent(self, contract=WRITE_CONTRACT, agent=None):
        """A scripted client that binds only from the conversation and obeys a required tool."""
        agent = agent or fake_agent([])[0]
        requests = []

        def create(**kwargs):
            requests.append(deepcopy(kwargs))
            previous = json.loads(kwargs["messages"][-1]["content"])
            required = kwargs.get("tool_choice", {}).get("function", {}).get("name")
            # The interrupted write is read back from the conversation, never from the session.
            written = next(json.loads(call["function"]["arguments"]) for message in kwargs["messages"]
                           for call in message.get("tool_calls") or ()
                           if call["function"]["name"] == contract["write"])
            returned = previous.get(contract["ids"])
            message = {"role": "assistant", "content": "Finished."}
            tool = None
            if len(requests) == 1 or required == contract["lookup"]:
                tool, args = contract["lookup"], {field: written[field] for field in contract["scope"]}
            elif returned == []:
                tool, args = contract["write"], written
            elif previous.get("status") != "active":
                tool, args = contract["verify"], {contract["id"]: previous.get(contract["id"]) or returned[0]}
            if tool:
                message = {"role": "assistant", "content": "", "tool_calls": [{
                    "id": f"cpu_{len(requests)}", "type": "function",
                    "function": {"name": tool, "arguments": json.dumps(args)},
                }]}
            return ChatCompletion(
                id="cpu", object="chat.completion", created=0, model="cpu",
                choices=[{"index": 0, "message": message, "finish_reason": "tool_calls" if tool else "stop"}],
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})

        # One scripted endpoint behind both the Agent's own client and the launcher's wrapper.
        completions = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        agent.client = SimpleNamespace(chat=completions.chat, with_options=lambda **_: completions)
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
            # The episode loop passes a generator; it must be read once for every candidate.
            self.assertIs(sequential_contract(name for name in names), expected)
        release_names = [tool["name"] for tool in RecoverySession("artifact-release").public()["tools"]]
        self.assertIs(sequential_contract(name for name in release_names), RELEASE_CONTRACT)

    def test_release_obligation_is_tracked_inside_the_agent_loop(self):
        for fault in ("write_not_committed", "write_response_lost"):
            for rule in (None, "enforced", "advice"):
                session, _ = self.release_session(fault)
                offered_all = len(session.public()["tools"])
                agent, requests = self.protocol_agent(RELEASE_CONTRACT)
                controlled = FeedbackRuleAgent(agent, enforce=rule == "enforced") if rule else agent
                result = run_episode(controlled, session, resume=True)
                self.assertTrue(result["strict_success"], result["issues"])
                self.assertEqual((result["illegal_calls"], len(result["family_state"]["releases"])), (0, 1))
                checkpoints = result["checkpoints"]
                self.assertEqual([c["context"]["phase"] for c in checkpoints], [
                    "commit_unknown", *(["confirmed_absent"] if fault == "write_not_committed" else []),
                    "verify_existing"])
                # Every decision before the read-back is a checkpoint; the final answer is not.
                self.assertEqual(len(checkpoints), len(requests) - 1)
                expected = ["inspect_project_release",
                            *(["publish_release"] if fault == "write_not_committed" else []), "get_release_status"]
                self.assertEqual([c["model_action"]["tool"] for c in checkpoints], expected)
                for checkpoint, request, tool in zip(checkpoints, requests, expected):
                    offered = [t["function"]["name"] for t in request["tools"]]
                    self.assertTrue(checkpoint["model_action"]["accepted"])
                    self.assertEqual(checkpoint["rule_selected"], tool if rule else None)
                    if rule == "enforced":
                        self.assertEqual(offered, [tool])
                        self.assertEqual(request["tool_choice"]["function"]["name"], tool)
                    else:
                        self.assertEqual(len(offered), offered_all)
                        self.assertNotIn("tool_choice", request)
                    if rule:
                        self.assertTrue(checkpoint["rule_followed"])
                self.assertNotIn("tool_choice", requests[-1])
                self.assertEqual(len(requests[-1]["tools"]), offered_all)

    def test_known_identifier_is_verified_whatever_later_lookups_do(self):
        def cases(fault):
            stock = self.session(fault)
            release, published = self.release_session(fault)
            return ((stock, WRITE_CONTRACT, {"request_ref": "HOLD-2702"}, dict(stock.events[1]["arguments"])),
                    (release, RELEASE_CONTRACT, {"project": published["project"], "version": published["version"]},
                     published))

        for fault in ("write_response_lost", "write_not_committed"):
            for session, contract, scope, written in cases(fault):
                rebuilt = lambda: sequential_write_context(public_events(session), contract)
                # The identifier comes from the lookup, or from the receipt of the repeated write.
                known = session.call(contract["lookup"], scope)[contract["ids"]]
                if fault == "write_not_committed":
                    known = [session.call(contract["write"], written)[contract["id"]]]
                session.diagnosis_available = False
                for failures in (1, 2, 3):
                    self.assertIn("error", session.call(contract["lookup"], scope))
                    checkpoint = rebuilt()
                    self.assertEqual((checkpoint["phase"], checkpoint["lookup_failures"], checkpoint[contract["ids"]]),
                                     ("verify_existing", failures, known))
                    self.assertIn(contract["verify"], checkpoint["available"])
                    self.assertEqual(simple_feedback_action(checkpoint, contract), contract["verify"])
                session.call(contract["verify"], {contract["id"]: known[0]})
                self.assertIsNone(rebuilt())
                self.assertTrue(evaluate(session, "Done.")["strict_success"])

        # The stop-loss still bounds a state that needs lookup evidence, in both families.
        for session, contract, scope, _ in cases("write_not_committed"):
            session.diagnosis_available = False
            for expected in (contract["lookup"], "stop", "stop"):
                session.call(contract["lookup"], scope)
                checkpoint = sequential_write_context(public_events(session), contract)
                self.assertEqual(checkpoint["phase"], "commit_unknown")
                self.assertEqual(simple_feedback_action(checkpoint, contract), expected)

        # An exhausted budget comes before everything, a known identifier included.
        for session, contract, scope, _ in cases("write_response_lost"):
            while len(session.events) < 16:
                session.call(contract["lookup"], scope)
            checkpoint = sequential_write_context(public_events(session), contract)
            self.assertEqual((checkpoint["phase"], len(checkpoint[contract["ids"]])), ("verify_existing", 1))
            self.assertEqual((checkpoint["available"], simple_feedback_action(checkpoint, contract)),
                             (["stop"], "stop"))

    def test_rule_choice_is_supported_by_public_evidence_on_random_histories(self):
        random = Random(33)
        open_obligations = set()
        for trial in range(400):
            fault = random.choice(("write_not_committed", "write_response_lost"))
            stock = random.random() < 0.5
            contract = WRITE_CONTRACT if stock else RELEASE_CONTRACT
            references = {argument: ["0" * 24] for argument in contract["evidence"]}
            if random.random() < 0.25:
                # A history that opens anywhere, including a write attempted before any evidence.
                session = RecoverySession("stock-write-recovery" if stock else "artifact-release", fault)
            else:
                # A history that opens at the interrupted write.
                session, written = (self.session(fault), None) if stock else self.release_session(fault)
                written = written or session.events[1]["arguments"]
                for argument in references:
                    references[argument].append(written[argument])
            session.diagnosis_available = random.random() > 0.2
            goal = session.goal
            scope = {"request_ref": "HOLD-2702"} if stock else {"project": goal.project, "version": goal.version}
            wrong = {"request_ref": "HOLD-0000"} if stock else {**scope, "version": "v" + goal.version}
            identifiers = ["f" * 24]
            for _ in range(random.randint(3, 12)):
                move = random.choice(("evidence", "evidence", "write", "write", "lookup", "lookup", "wrong",
                                      "verify", "toggle"))
                if move == "evidence":
                    argument = random.choice(list(contract["evidence"]))
                    tool = random.choice(list(contract["evidence"][argument]))
                    field = {"get_depot_inventory": "sku", "read_depot_count": "item_code",
                             "get_build_manifest": "build_id", "read_artifact_mirror": "artifact_key",
                             "get_project_publish_permission": "project"}[tool]
                    value = goal.project if field == "project" else goal.resource
                    receipt = session.call(tool, {field: value})
                    references[argument].append(receipt.get(contract["evidence"][argument][tool], "0" * 24))
                elif move == "write":
                    cited = {argument: random.choice(issued[-2:]) for argument, issued in references.items()}
                    fixed = ({"sku": "P-140", "quantity": 3, "request_ref": "HOLD-2702"} if stock else
                             {**scope, "sha256": goal.digest})
                    identifiers.append(session.call(contract["write"], {**fixed, **cited}).get(contract["id"], "f" * 24))
                elif move in ("lookup", "wrong"):
                    identifiers.extend(session.call(contract["lookup"], scope if move == "lookup" else wrong)
                                       .get(contract["ids"], []))
                elif move == "verify":
                    session.call(contract["verify"], {contract["id"]: random.choice(identifiers)})
                else:
                    session.diagnosis_available = not session.diagnosis_available
                checkpoint = sequential_write_context(public_events(session), contract)
                if checkpoint is None:
                    continue
                committed = session.reservations if stock else session.family_backend.records
                known = checkpoint[contract["ids"]]
                choice = simple_feedback_action(checkpoint, contract)
                failures = checkpoint["lookup_failures"]
                open_obligations.add((stock, checkpoint["phase"], min(failures, 2), min(len(known), 2), choice))
                self.assertIn(choice, checkpoint["available"])
                self.assertTrue(set(known) <= set(committed))
                if contract["write"] in checkpoint["available"] or choice == contract["write"]:
                    # Repeating the write is offered only when nothing is committed, so never a duplicate.
                    self.assertEqual((checkpoint["phase"], len(committed), failures), ("confirmed_absent", 0, 0))
                if len(known) == 1:
                    self.assertEqual(choice, contract["verify"])
                if choice == "stop":
                    self.assertTrue(len(known) > 1 or checkpoint["phase"] == "commit_unknown" and failures >= 2)
        # The random histories reached every branch of the rule in both families.
        for stock in (True, False):
            reached = {row[1:] for row in open_obligations if row[0] == stock}
            contract = WRITE_CONTRACT if stock else RELEASE_CONTRACT
            self.assertTrue({contract["lookup"], contract["write"], contract["verify"], "stop"}
                            <= {row[-1] for row in reached})
            self.assertIn(("verify_existing", 2, 1, contract["verify"]), reached)
            self.assertIn(("commit_unknown", 2, 0, "stop"), reached)

    def launched(self, arm, fault, assignment=None, exit_wording="original"):
        # The launcher's own model, temperature and limits reach the request; only the endpoint is scripted.
        def scripted(*args, **kwargs):
            return self.protocol_agent(agent=VLLMAgent(*args, **kwargs))[0]

        with TemporaryDirectory() as directory, \
                patch("extensions.toolmaze_recovery.run.VLLMAgent", side_effect=scripted), \
                patch("extensions.toolmaze_recovery.run.version", return_value="cpu"):
            output = Path(directory) / "episode"
            smoke(output, "stock-write-recovery", fault, "http://127.0.0.1:1/v1", start_mode="write-checkpoint",
                  seed=3301, first_tool=LOOKUP, arm=arm, assignment=assignment,
                  # Left out for the original prompt, so the launcher's own default is what runs.
                  **({} if exit_wording == "original" else {"exit_wording": exit_wording}))
            config = json.loads((output / "config.json").read_text())
            logged = [json.loads(line)["request"] for line in (output / "requests.jsonl").read_text().splitlines()]
            episode = json.loads((output / "episode.json").read_text())
        self.assertTrue(episode["strict_success"], episode["issues"])
        self.assertEqual((config["arm"], config["fault"], config["seed"], config["assignment"], config["exit_wording"]),
                         (arm, fault, 3301, assignment, exit_wording))
        self.assertTrue(all(request["seed"] == 3301 for request in logged))
        # Every episode on the original prompt opens with the request the Gate 33 cloud run archived.
        self.assertEqual(episode["first_request_sha256"] == GATE33_FIRST_REQUEST, exit_wording == "original")
        return [request.get("tool_choice", {}).get("function", {}).get("name") for request in logged], logged, episode

    def test_launcher_requires_a_tool_only_at_the_registered_positions(self):
        absent, lost = "write_not_committed", "write_response_lost"
        # The eight registered episodes of experiment 035, through the launch entry and its request log.
        for arm in ("react", "advice_only"):
            for fault, turns in ((absent, 4), (lost, 3)):
                required, logged, episode = self.launched(arm, fault)
                self.assertEqual(required, [LOOKUP, *[None] * (turns - 1)])
                self.assertTrue(all(len(request["tools"]) == 6 for request in logged))
                advised = ["Recovery advice suggests" in request["messages"][0]["content"] for request in logged]
                self.assertEqual(advised, [False, *[arm == "advice_only"] * (turns - 2), False])
                self.assertEqual([c["rule_mode"] for c in episode["checkpoints"]][1:],
                                 ["advice" if arm == "advice_only" else None] * (turns - 2))
        for fault, expected in ((absent, [LOOKUP, WRITE, VERIFY, None]), (lost, [LOOKUP, VERIFY, None])):
            required, logged, episode = self.launched("simple_feedback", fault)
            self.assertEqual(required, expected)
            self.assertEqual([len(request["tools"]) for request in logged], [6, *[1] * (len(expected) - 2), 6])
            self.assertEqual([c["rule_selected"] for c in episode["checkpoints"]], [None, *expected[1:-1]])
        for tool, expected in ((WRITE, [LOOKUP, WRITE, None, None]), (LOOKUP, [LOOKUP, LOOKUP, None, None, None])):
            assignment = enumerated_assignment("confirmed_absent", tool)
            required, logged, episode = self.launched("react", absent, assignment)
            self.assertEqual(required, expected)
            self.assertTrue(all(len(request["tools"]) == 6 for request in logged))
            self.assertEqual(logged[1]["messages"][0], logged[0]["messages"][0])
            recorded = [c["assignment"] for c in episode["checkpoints"]]
            self.assertEqual(recorded[1], {**assignment, "applied": True, "followed": True})
            self.assertEqual([bool(row) for row in recorded], [False, True, *[False] * (len(recorded) - 2)])
        # Unregistered combinations are refused before anything is written.
        with TemporaryDirectory() as directory:
            for arguments in (
                    {"arm": "advice_only", "assignment": enumerated_assignment("confirmed_absent", WRITE)},
                    {"arm": "simple_feedback", "assignment": enumerated_assignment("confirmed_absent", WRITE)},
                    {"arm": "advice_only", "task": "artifact-release"},
                    {"arm": "react", "task": "artifact-release",
                     "assignment": enumerated_assignment("confirmed_absent", "publish_release")}):
                task = arguments.pop("task", "stock-write-recovery")
                output = Path(directory) / "refused"
                with self.assertRaises(ValueError):
                    smoke(output, task, absent, "http://127.0.0.1:1/v1", **arguments)
                self.assertFalse(output.exists())

    def test_exit_wording_control_removes_the_registered_sentences_and_nothing_else(self):
        absent, lost = "write_not_committed", "write_response_lost"
        sentences = (EXIT_SYSTEM_STOP, EXIT_SYSTEM_HALTED, EXIT_USER_BLOCKED)

        def cut(text):
            for sentence in (EXIT_SYSTEM_STOP, EXIT_SYSTEM_HALTED):
                text = text.replace("\n" + sentence, "")
            return text.replace(" " + EXIT_USER_BLOCKED, "")

        def prompts(request):
            return [message["content"] for message in request["messages"][:2]]

        # The four registered episodes of experiment 036, through the launch entry and its request log.
        for fault in (absent, lost):
            required, original, _ = self.launched("react", fault)
            control_required, control, _ = self.launched("react", fault, exit_wording="removed")
            self.assertEqual(control_required, required)
            self.assertEqual(len(control), len(original))
            for sentence in sentences:
                self.assertEqual("".join(prompts(original[0])).count(sentence), 1)
            # The first request differs by exactly the three sentences: same model, limits, seed,
            # tools, required first tool and replayed prefix.
            expected = deepcopy(original[0])
            for message in expected["messages"][:2]:
                message["content"] = cut(message["content"])
            self.assertEqual(control[0], expected)
            for before, after in zip(original, control):
                self.assertEqual(prompts(after), [cut(text) for text in prompts(before)])
                self.assertEqual(after["tools"], before["tools"])
                self.assertEqual([m["role"] for m in after["messages"]], [m["role"] for m in before["messages"]])
                for sentence in sentences:
                    self.assertNotIn(sentence, json.dumps(after["messages"]))
        # The control exists only for the unassigned native Agent at the registered write checkpoint.
        with TemporaryDirectory() as directory:
            for arguments in (
                    {"arm": "advice_only"}, {"arm": "simple_feedback"},
                    {"assignment": enumerated_assignment("confirmed_absent", WRITE)},
                    {"task": "artifact-release"}, {"first_tool": None, "start_mode": "full"},
                    {"exit_wording": "softened"}):
                output = Path(directory) / "refused"
                with self.assertRaises(ValueError):
                    smoke(output, **{
                        "task": "stock-write-recovery", "condition": absent, "endpoint": "http://127.0.0.1:1/v1",
                        "start_mode": "write-checkpoint", "first_tool": LOOKUP, "exit_wording": "removed",
                        **arguments})
                self.assertFalse(output.exists())
        for arguments in ({"assignment": enumerated_assignment("confirmed_absent", WRITE)}, {"rule": True}):
            agent = fake_agent([])[0]
            controlled = FeedbackRuleAgent(agent) if arguments.pop("rule", False) else agent
            with self.assertRaises(ValueError):
                run_episode(controlled, self.session(), resume=True, exit_wording="removed", **arguments)
        # A prompt that no longer holds a registered sentence is refused, never run as if it were removed.
        for name in ("EXIT_USER", "EXIT_SYSTEM"):
            missing = " A sentence the prompt never held."
            with patch(f"extensions.toolmaze_recovery.run.{name}", missing if name == "EXIT_USER" else (missing,)):
                with self.assertRaises(ValueError):
                    run_episode(fake_agent([])[0], self.session(), resume=True, exit_wording="removed")
        # Without the sentences a stop is still a stop: nothing is called, written or scored as complete.
        session = self.session()
        agent, requests = fake_agent([])
        result = run_episode(agent, session, resume=True, exit_wording="removed")
        self.assertFalse(result["strict_success"])
        self.assertEqual((len(result["events"]), len(result["effects"]), len(requests)), (2, 0, 1))
        self.assertFalse(any(sentence in json.dumps(requests[0]["messages"]) for sentence in sentences))
        # Asked for nothing, the loop sends the original prompt.
        agent, requests = fake_agent([])
        run_episode(agent, self.session(), resume=True)
        self.assertEqual(["".join(prompts(requests[0])).count(sentence) for sentence in sentences], [1, 1, 1])
        self.assertEqual(result["checkpoints"][0]["model_action"]["tool"], "stop")
