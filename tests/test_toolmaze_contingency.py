"""Contingency-program executor: sandbox, budget, isolation and the real Agent loop (CPU only)."""

from copy import deepcopy
import json
from types import SimpleNamespace
import unittest

from extensions.toolmaze_recovery.contingency import (
    PROGRAM_SYSTEM, check_program, extract_program, program_episode, run_program, ProgramRejected,
)
from extensions.toolmaze_recovery.environment import TIMEOUT, RecoverySession
from extensions.toolmaze_recovery.contingency_cpu import PROGRAMS, cells
from evaluation.agents.vllm_agent import VLLMAgent

CLEAN_CASE = '''
r = call("get_case_record", case_id="HD-582")
if "error" in r:
    escalate("primary read failed")
n = call("publish_case_note", case_id="HD-582", title="Scanner incident", content=r["summary"],
         evidence_ref=r["record_ref"])
finish("Published " + n["url"])
'''


def scripted_agent(replies):
    """The native Agent with a scripted SDK. Each reply is a code reply (str) or a tool call."""
    agent = VLLMAgent("cp01-scripted", "http://127.0.0.1:1/v1")
    requests = []
    replies = iter(replies)

    def create(**kwargs):
        requests.append(deepcopy(kwargs))
        reply = next(replies, "Finished.")
        if callable(reply):
            reply = reply(kwargs)
        message = {"role": "assistant", "content": reply}
        if isinstance(reply, tuple):
            tool, arguments = reply
            message = {"role": "assistant", "content": "", "tool_calls": [{
                "id": f"call_{len(requests)}", "type": "function",
                "function": {"name": tool, "arguments": json.dumps(arguments)}}]}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(model_dump=lambda **_: message))],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))

    agent.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return agent, requests


class SandboxTest(unittest.TestCase):
    def test_rejects_escape_routes(self):
        for source in ("import os", "x = ().__class__", "_x = 1", "try:\n    pass\nexcept:\n    pass",
                       "try:\n    pass\nexcept BaseException:\n    pass", "s = '{0}'.format(1)",
                       "class A:\n    pass", "with x:\n    pass", "global y", "f = lambda: 1",
                       "def g(_a):\n    pass"):
            with self.subTest(source=source), self.assertRaises(ProgramRejected):
                check_program(source)

    def test_unlisted_builtins_and_globals_are_absent(self):
        for source in ("open('x')", "globals()", "getattr(call, 'x')", "eval('1')", "type(1)"):
            session = RecoverySession("case-archive")
            record = run_program(session, source)
            self.assertEqual(record["status"], "crashed", source)
            self.assertIn("NameError", record["error"])
            self.assertFalse(session.events)

    def test_infinite_loop_is_halted(self):
        record = run_program(RecoverySession("case-archive"), "while True:\n    pass")
        self.assertEqual(record["status"], "halted_steps")

    def test_call_budget_is_the_session_budget(self):
        session = RecoverySession("case-archive", "persistent")
        record = run_program(session, 'while True:\n    call("get_case_record", case_id="HD-582")')
        self.assertEqual(record["status"], "halted_budget")
        self.assertEqual(len(session.events), 16)
        self.assertTrue(all(e["result"] == TIMEOUT and e["fee"] == 1 for e in session.events))

    def test_finish_and_escalate_cannot_be_caught(self):
        for exit_call, status in (('finish("done")', "finished"), ('escalate("why")', "escalated")):
            session = RecoverySession("case-archive")
            source = f'try:\n    {exit_call}\nexcept Exception:\n    call("get_case_record", case_id="HD-582")'
            record = run_program(session, source)
            self.assertEqual(record["status"], status)
            self.assertFalse(session.events)

    def test_program_ends_without_finish_or_crashes(self):
        self.assertEqual(run_program(RecoverySession("case-archive"), "x = 1")["status"], "no_finish")
        record = run_program(RecoverySession("case-archive"), 'r = call("get_case_record", case_id="HD-582")\nr["nope"]')
        self.assertEqual(record["status"], "crashed")
        self.assertIn("KeyError", record["error"])

    def test_calls_use_the_unchanged_contract(self):
        session = RecoverySession("case-archive")
        record = run_program(session, 'r = call("get_case_record", {"case_id": "582"})\nfinish(r["error"])')
        self.assertEqual(record["answer"], "Validation failed")
        self.assertTrue(session.events[0]["illegal"])
        record = run_program(RecoverySession("case-archive"), 'call("get_case_record", {"case_id": "HD-582"}, x=1)')
        self.assertEqual(record["status"], "crashed")

    def test_extract_program_takes_the_last_block(self):
        self.assertEqual(extract_program("a\n```python\nx = 1\n```\nb\n```\ny = 2\n```"), "y = 2\n")
        self.assertIsNone(extract_program("no code"))


class ReferenceProgramTest(unittest.TestCase):
    def test_programs_cover_every_registered_cell_and_pass_the_sandbox(self):
        self.assertEqual(len(cells()), 38)
        for styles in PROGRAMS.values():
            for text in styles.values():
                check_program(text)


class ProgramEpisodeTest(unittest.TestCase):
    def test_finished_program_needs_one_request_and_is_scored_unchanged(self):
        agent, requests = scripted_agent(["Plan:\n```python" + CLEAN_CASE + "```"])
        session = RecoverySession("case-archive")
        session.engine.private_fixture = "PRIVATE_STATE_SENTINEL"
        result = program_episode(agent, session, max_requests=12)
        self.assertTrue(result["strict_success"], result["issues"])
        self.assertEqual(len(requests), 1)
        self.assertIsNone(requests[0]["tools"])
        self.assertEqual(requests[0]["messages"][0]["content"], PROGRAM_SYSTEM)
        payload = json.dumps(requests)
        self.assertIn("publish_case_note", payload)
        for term in ("PRIVATE_STATE_SENTINEL", "Dock scanner drops", "persistent", "correlated",
                     "transient", "case-archive", "valid_paths"):
            self.assertNotIn(term, payload)
        self.assertIsNone(result["continuation"])
        tokens = result["program"]["tokens"]
        self.assertEqual((tokens["input_tokens"], tokens["output_tokens"]), (10, 5))

    def test_escalation_continues_with_the_native_agent_and_replayed_calls(self):
        def publish(kwargs):
            archive = json.loads(kwargs["messages"][-1]["content"])
            return ("publish_case_note", {"case_id": "HD-582", "title": "Scanner incident",
                                          "content": archive["case_file"]["summary"],
                                          "evidence_ref": archive["archive_ref"]})
        agent, requests = scripted_agent([
            "```python" + CLEAN_CASE + "```",
            ("read_case_archive", {"ticket": "HD-582"}), publish, "Published the note.",
        ])
        result = program_episode(agent, RecoverySession("case-archive", "persistent"), max_requests=12)
        self.assertEqual(result["program"]["status"], "escalated")
        self.assertTrue(result["strict_success"], result["issues"])
        self.assertEqual(len(requests), 4)
        replay = requests[1]["messages"]
        self.assertNotEqual(replay[0]["content"], PROGRAM_SYSTEM)
        self.assertEqual(replay[2]["tool_calls"][0]["function"]["name"], "get_case_record")
        self.assertEqual(json.loads(replay[3]["content"]), TIMEOUT)
        self.assertTrue(requests[1]["tools"])
        self.assertEqual([e["tool"] for e in result["events"]],
                         ["get_case_record", "read_case_archive", "publish_case_note"])

    def test_missing_or_rejected_program_falls_back_from_the_start(self):
        for reply, status in (("I will do it step by step.", "no_program"), ("```python\nimport os\n```", "rejected")):
            agent, requests = scripted_agent([reply, ("get_case_record", {"case_id": "HD-582"})])
            result = program_episode(agent, RecoverySession("case-archive"), max_requests=3)
            self.assertEqual(result["program"]["status"], status)
            self.assertEqual(len(requests), 3)
            self.assertEqual(len(requests[1]["messages"]), 2)  # fresh native start, no replay
            self.assertEqual([e["tool"] for e in result["events"]], ["get_case_record"])
            self.assertFalse(result["strict_success"])

    def test_no_fallback_scores_the_program_alone(self):
        agent, requests = scripted_agent(["```python" + CLEAN_CASE + "```"])
        result = program_episode(agent, RecoverySession("case-archive", "persistent"), max_requests=12, fallback=False)
        self.assertEqual(len(requests), 1)
        self.assertFalse(result["strict_success"])
        self.assertEqual(result["tool_fee"], 1)


if __name__ == "__main__":
    unittest.main()
