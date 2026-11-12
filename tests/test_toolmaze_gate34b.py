"""CPU protocol checks; fake client is explicitly not a real Agent experiment."""
from copy import deepcopy
from fractions import Fraction as F
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from extensions.toolmaze_recovery.gate34a import MechanismSession, RESOURCE, evaluate
from extensions.toolmaze_recovery.gate34b import (
    BACKUP, DIAGNOSE, MAIN, VALIDATE, VERIFY, WRITE, MODEL, PAIRS, SMOKE,
    VLLMAgent, episode, feedback_tool, initialize, run_episode,
)
from extensions.toolmaze_recovery.run import EXIT_SYSTEM, EXIT_USER


def client_agent(plan):
    agent = VLLMAgent(MODEL, "http://127.0.0.1:1/v1")
    requests = []
    actions = iter(plan)
    def create(**kwargs):
        requests.append(deepcopy(kwargs))
        step = next(actions, None)
        receipts = [json.loads(m["content"]) for m in kwargs["messages"] if m["role"] == "tool"]
        msg = {"role": "assistant", "content": "Published and verified."}
        if step:
            tool, args = step
            args = args(receipts) if callable(args) else args
            msg = {"role": "assistant", "content": "", "tool_calls": [{"id": f"call-{len(requests)}",
                   "type": "function", "function": {"name": tool, "arguments": json.dumps(args)}}]}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(model_dump=lambda **kw: msg))],
                               usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2))
    agent.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return agent, requests


def session(transient=True, fee=None):
    s = MechanismSession(transient, diagnostic_fee=fee, _namespace="gate34b-cpu")
    s.call(MAIN, {"record_id": RESOURCE})
    return s


def backup_plan():
    return [(BACKUP, {"record_id": RESOURCE}),
            (VALIDATE, lambda r: {"record_id": RESOURCE, "pending_ref": r[-1]["pending_ref"]}),
            (WRITE, lambda r: {"record_id": RESOURCE, "content": r[-2]["content"], "evidence_ref": r[-1]["evidence_ref"]}),
            (VERIFY, lambda r: {"publication_id": r[-1]["publication_id"]})]


class Gate34BTests(unittest.TestCase):
    def test_original_prompt_and_public_facts_only(self):
        a,_ = client_agent([])
        b,_ = client_agent([])
        s=session(fee=F(1,10))
        initialize(a,s)
        b.initialize(s.public()["task"],s.public()["tools"])
        self.assertEqual(a.messages[0],b.messages[0])
        for sentence in EXIT_SYSTEM:
            self.assertIn(sentence,a.messages[0]["content"])
        self.assertIn(EXIT_USER,a.messages[1]["content"])
        for forbidden in ('"gamma"','"seed"','"fault"','"cell"','oracle','35001'):
            self.assertNotIn(forbidden,json.dumps(a.messages))
        self.assertIn('1/10',a.messages[1]["content"])
        self.assertIn('7 total',a.messages[1]["content"])
        self.assertEqual(a.messages[-1]["role"],"tool")

    def test_first_force_then_native_with_actual_backup_chain(self):
        a,requests=client_agent(backup_plan())
        r=run_episode(a,session(False),first_tool=BACKUP)
        self.assertTrue(r["strict_success"],r)
        self.assertEqual(F(r["suffix_fee"]),4)
        self.assertEqual(requests[0]["tool_choice"]["function"]["name"],BACKUP)
        self.assertTrue(all('tool_choice' not in q for q in requests[1:]))
        self.assertEqual(r["checkpoints"][0]["execution"]["executed_tool"],BACKUP)
        self.assertEqual(len([e for e in r["events"] if e["tool"]==WRITE]),1)

    def test_rule_forces_tools_only_and_rejects_model_parameters(self):
        a,requests=client_agent([(MAIN,{"record_id":RESOURCE}),(WRITE,{})])
        s=session()
        r=run_episode(a,s,arm="simple_feedback")
        self.assertFalse(r["strict_success"])
        self.assertFalse(s.effects)
        self.assertTrue(s.events[-1]["illegal"])
        self.assertEqual(s.events[-1]["arguments"],{})
        self.assertEqual(requests[1]["tool_choice"]["function"]["name"],WRITE)
        self.assertFalse(r["checkpoints"][1]["execution"]["legal"])

    def test_rule_only_uses_price_and_observed_feedback(self):
        s=session(False,fee=F(1,10))
        self.assertEqual(feedback_tool(s.view()),DIAGNOSE)
        s.call(DIAGNOSE,{"record_id":RESOURCE})
        self.assertEqual(feedback_tool(s.view()),MAIN) # default public signal is transient_hint
        s.call(MAIN,{"record_id":RESOURCE})
        self.assertEqual(feedback_tool(s.view()),BACKUP)
        s=session(False,fee=F(1,2))
        self.assertEqual(feedback_tool(s.view()),MAIN)
        a=session(True,fee=F(1,10)); b=session(False,fee=F(1,10))
        self.assertEqual(a.view(),b.view())
        self.assertEqual(feedback_tool(a.view()),feedback_tool(b.view()))

    def test_full_rule_chain_consumes_model_generated_receipts(self):
        a,requests=client_agent([(MAIN,{"record_id":RESOURCE}),*backup_plan()])
        r=run_episode(a,session(False),arm="simple_feedback")
        self.assertTrue(r["strict_success"])
        self.assertEqual([q['tool_choice']['function']['name'] for q in requests[:-1]],
                         [MAIN,BACKUP,VALIDATE,WRITE,VERIFY])
        self.assertNotIn('tool_choice',requests[-1])

    def test_write_feedback_condition_reaches_the_model_and_only_changes_that_text(self):
        # The experiment 038 P05 mistake: the trailing period dropped from the content.
        plan = [*backup_plan()[:2],
                (WRITE, lambda r: {"record_id": RESOURCE, "content": r[-2]["content"][:-1],
                                   "evidence_ref": r[-1]["evidence_ref"]})]
        runs = {}
        for condition in ("original", "specific"):
            s = MechanismSession(False, write_feedback=condition, _namespace="gate34b-cpu")
            s.call(MAIN, {"record_id": RESOURCE})
            a, requests = client_agent(plan)
            r = run_episode(a, s)
            self.assertFalse(r["strict_success"])
            self.assertFalse(s.effects)
            self.assertTrue(s.events[-1]["illegal"])
            runs[condition] = (requests, r)
        (old_requests, old), (new_requests, new) = runs["original"], runs["specific"]
        self.assertEqual(json.loads(old_requests[-1]["messages"][-1]["content"])["error"],
                         "An actual primary or granularity-verified backup evidence_ref is required.")
        self.assertEqual(json.loads(new_requests[-1]["messages"][-1]["content"])["error"],
                         "content does not exactly match the content returned with this evidence_ref.")
        self.assertEqual(old_requests[:-1], new_requests[:-1])
        self.assertEqual(old_requests[-1]["messages"][:-1], new_requests[-1]["messages"][:-1])
        self.assertEqual((old["suffix_fee"], old["illegal_calls"]), (new["suffix_fee"], new["illegal_calls"]))

    def test_budget_attempt_saved_not_executed_or_automatically_finished(self):
        a,_=client_agent([(BACKUP,{"record_id":RESOURCE})]*7)
        s=session()
        r=run_episode(a,s)
        self.assertEqual(len(s.events),7)
        self.assertFalse(r["strict_success"])
        self.assertIn('budget',r["checkpoints"][-1]["execution"]["rejection"])
        self.assertIsNone(r["answer"])

    def test_unfollowed_assignment_and_natural_request_distinct(self):
        a,requests=client_agent([])
        r=run_episode(a,session(),first_tool=MAIN)
        self.assertFalse(r["strict_success"])
        self.assertFalse(r["checkpoints"][0]["assignment_followed"])
        a,requests=client_agent([])
        run_episode(a,session())
        self.assertNotIn('tool_choice',requests[0])

    def test_fixed_manifest_and_archive_refuses_overwrite(self):
        self.assertEqual(len(SMOKE),8)
        self.assertEqual(len(PAIRS)*2,12)
        self.assertEqual([s[2] for s in SMOKE],list(range(34001,34009)))
        self.assertEqual([s[2] for s in PAIRS],list(range(35001,35007)))
        with TemporaryDirectory() as directory:
            with self.assertRaises(FileExistsError):
                episode(Path(directory),SMOKE[0],"react","http://127.0.0.1:1/v1")


if __name__=="__main__":
    unittest.main()
