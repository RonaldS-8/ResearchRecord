"""Gate 25 CPU acceptance against the archived native ToolMaze task fixtures."""

from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

from extensions.toolmaze_agent_recovery.session import (
    BUDGET, READS, TIMEOUT, UNAVAILABLE, Session, run_episode,
)
from extensions.toolmaze_agent_recovery.verification import (
    bound_arguments, evaluate, task_path,
)
from evaluation.agents.vllm_agent import VLLMAgent


def save(name, result):
    if directory := os.environ.get("GATE25_OUTPUT"):
        path = Path(directory) / f"{name}.json"
        with path.open("x") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)


def steps_for(session, branch):
    return task_path(session.template, session.engine.task_json["valid_paths"][branch])


def play(session, branch=0, *, count=None, retry=False, changes=None):
    """CPU-only fixture. Bind from earlier actual calls, never archived outputs."""
    steps, aliases = steps_for(session, branch)
    user = session.engine.task_json["user_input"]
    prior = {}
    for node, tool, bindings in steps[:count]:
        arguments, _ = bound_arguments(bindings, user, prior, aliases)
        if changes and node in changes:
            arguments.update(changes[node])
        result = session.call(tool, arguments)
        if result == TIMEOUT and retry:
            result = session.call(tool, arguments)
        if "error" in result:
            break
        prior[node] = session.events[-1]
    return prior


def fake_agent(calls):
    """Capture SDK requests through the actual native Agent message construction."""
    agent = VLLMAgent("gate25-scripted", "http://127.0.0.1:1/v1")
    requests = []
    actions = iter(calls)

    def create(**kwargs):
        requests.append(deepcopy(kwargs))
        selected = next(actions, None)
        message = {"role": "assistant", "content": "Stopped or finished."}
        if selected is not None:
            tool, arguments = selected
            message = {
                "role": "assistant", "content": "",
                "tool_calls": [{
                    "id": f"call_{len(requests)}", "type": "function",
                    "function": {"name": tool, "arguments": json.dumps(arguments)},
                }],
            }
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(model_dump=lambda **_: message))],
            usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0),
        )

    agent.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return agent, requests


class ToolMazeRecoveryTests(unittest.TestCase):
    def test_transient_retry_and_receipt_chain(self):
        session = Session("002", "transient")
        play(session, retry=True)
        result = evaluate(session, "Finished.")
        save("transient_retry", result)
        self.assertTrue(result["strict_success"], result["issues"])
        self.assertEqual(result["failed_calls"], 1)
        self.assertEqual(result["tool_fee"], 8)
        self.assertEqual(result["diagnostic_fee"], 0)
        self.assertEqual(result["sources"][6]["balance_sheet"], {"call": 5, "field": ""})
        self.assertEqual(result["sources"][7]["body"], {"call": 6, "field": "status"})
        self.assertEqual(result["sources"][8]["participants"], {"call": 7, "field": "recipients"})
        self.assertEqual([e["operation"] for e in result["effects"]],
                         ["create_document", "push_alert", "send_email", "schedule_meeting"])

    def test_persistent_switch_through_native_agent_protocol(self):
        fixture = Session("002", "persistent")
        play(fixture, count=4)
        play(fixture, branch=1)
        first = fixture.events[:4]
        alternative = fixture.events[-4:]
        agent, requests = fake_agent([(e["tool"], e["arguments"]) for e in first + alternative])
        result = run_episode(agent, Session("002", "persistent"))
        save("persistent_switch_agent_protocol", {"result": result, "requests": requests})
        self.assertTrue(result["strict_success"], result["issues"])
        self.assertEqual(result["events"][3]["result"], TIMEOUT)
        self.assertEqual(result["events"][4]["tool"], READS["002"][1])
        self.assertEqual(result["tool_fee"], 8)
        self.assertEqual(len(requests), 9)
        self.assertEqual(result["illegal_calls"], 0)

    def test_both_c3_001_archives_observed_but_task_not_completed(self):
        for branch in (0, 1):
            session = Session("001")
            play(session, branch)
            result = evaluate(session, "Finished.")
            save(f"c3_001_branch_{branch}", result)
            self.assertFalse(result["strict_success"])
            self.assertEqual(result["remaining"], [])
            self.assertEqual([e["operation"] for e in result["effects"]],
                             ["create_document", "push_alert", "push_alert"])
            self.assertIn("published slot receipt does not identify the requested ticket", result["issues"])
            self.assertIn("room booking request is not an actual room booking", result["issues"])

    def test_wrong_parameters_and_fabricated_upstream_do_not_pass(self):
        session = Session("002")
        play(session, changes={"s4a2": {"user_id": "wrong-object"}})
        result = evaluate(session, "Finished.")
        save("wrong_object", result)
        self.assertFalse(result["strict_success"])
        self.assertTrue(result["remaining"])
        self.assertIn("extra or duplicate effects outside the matched path", result["issues"])

        source = Session("002")
        play(source, count=5)
        fabricated = Session("002")
        play(fabricated, count=3)
        archive = source.events[-1]
        fabricated.call(archive["tool"], archive["arguments"])
        result = evaluate(fabricated, "Finished.")
        save("no_prior_receipt", result)
        self.assertFalse(result["strict_success"])
        self.assertEqual(len(result["effects"]), 2)
        self.assertEqual(result["remaining"][0], READS["002"][0])

    def test_missing_step_and_duplicate_write_do_not_pass(self):
        session = Session("002")
        play(session, count=6)
        result = evaluate(session, "Finished.")
        save("missing_schedule", result)
        self.assertFalse(result["strict_success"])
        self.assertEqual(result["remaining"], ["schedule_meeting"])

        clean = Session("002")
        play(clean)
        self.assertTrue(evaluate(clean, "Finished.")["strict_success"])
        last = clean.events[-1]
        clean.call(last["tool"], last["arguments"])
        result = evaluate(clean, "Finished.")
        save("duplicate_write", result)
        self.assertFalse(result["strict_success"])
        self.assertEqual(sum(e["operation"] == "schedule_meeting" for e in result["effects"]), 2)

    def test_early_stop_and_publicly_certified_stop(self):
        session = Session("002", "blocked")
        prior = play(session, count=4)
        early = evaluate(session, "Stopped after first failure.")
        save("early_stop", early)
        self.assertFalse(early["correct_stop"])
        steps, aliases = steps_for(session, 1)
        _, tool, bindings = steps[3]
        arguments, _ = bound_arguments(bindings, session.engine.task_json["user_input"], prior, aliases)
        self.assertEqual(session.call(tool, arguments), UNAVAILABLE)
        blocked = evaluate(session, "Both compatible reads are unavailable.")
        save("blocked_stop", blocked)
        self.assertTrue(blocked["correct_stop"])
        self.assertFalse(blocked["strict_success"])
        self.assertEqual(blocked["tool_fee"], 5)
        self.assertFalse(blocked["effects"])

    def test_persistent_timeout_and_invalid_attempts(self):
        session = Session("002", "persistent")
        play(session, count=4)
        failed = session.events[-1]
        self.assertEqual(session.call(failed["tool"], failed["arguments"]), TIMEOUT)
        self.assertEqual(session.call("send_email", {})["error"], "Invalid or unavailable tool call.")
        self.assertEqual(session.call(failed["tool"], {})["error"], "Validation failed")
        result = evaluate(session, "Stopped.")
        save("illegal_attempts", result)
        self.assertEqual(result["illegal_calls"], 2)
        self.assertEqual(result["tool_fee"], 6)
        self.assertFalse(result["correct_stop"])

    def test_requests_are_identical_through_first_failure(self):
        fixture = Session("002", "transient")
        play(fixture, count=4)
        calls = [(e["tool"], e["arguments"]) for e in fixture.events]
        streams = []
        for fault in ("transient", "persistent"):
            agent, requests = fake_agent(calls)
            session = Session("002", fault)
            session.engine.task_json = deepcopy(session.engine.task_json)
            session.engine.task_json["user_input"]["private_field"] = "PRIVATE_SENTINEL"
            session.engine.task_json["perturbation_mode"] = "PRIVATE_MODE_SENTINEL"
            result = run_episode(agent, session)
            streams.append(requests)
            self.assertEqual(result["events"][-1]["result"], TIMEOUT)
        self.assertEqual(*streams)
        encoded = json.dumps(streams[0])
        for private in (
            "perturbation_mode", "valid_paths", "execution_trace", "PRIVATE_SENTINEL",
            "PRIVATE_MODE_SENTINEL", "transient", "persistent", "C3_task_002",
        ):
            self.assertNotIn(private, encoded)
        save("public_request_pair", streams)

    def test_effect_records_are_isolated_and_budget_is_bounded(self):
        first, second = Session("002"), Session("002")
        play(first)
        self.assertEqual(len(first.effects), 4)
        self.assertFalse(second.effects)
        for _ in range(BUDGET):
            second.call("unavailable", {})
        with self.assertRaisesRegex(ValueError, "budget"):
            second.call("unavailable", {})
        self.assertFalse(second.effects)
