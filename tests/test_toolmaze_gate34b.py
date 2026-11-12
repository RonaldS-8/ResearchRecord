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
    VLLMAgent, episode, feedback_tool, initialize, run_episode, p05_checkpoint,
)
from extensions.toolmaze_recovery.gate34a import Distribution, sample
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
                               usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2),
                               model_dump=lambda **kw: {"choices": [{"message": msg}],
                                   "usage": {"prompt_tokens": 3, "completion_tokens": 2}})
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    client.with_options = lambda **kw: client
    agent.client = client
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
    def checkpoint_archive(self, directory):
        s = sample(Distribution("E", F(9, 10), F(1, 10)), 35005)
        s.call(MAIN, {"record_id": RESOURCE})
        plan = [(DIAGNOSE, {"record_id": RESOURCE}), *backup_plan()[:2],
                (WRITE, lambda r: {"record_id": RESOURCE, "content": r[-2]["content"][:-1],
                                    "evidence_ref": r[-1]["evidence_ref"]})]
        a, requests = client_agent(plan)
        result = run_episode(a, s, arm="simple_feedback")
        for request in requests:
            request["seed"] = 3301
        path = Path(directory)
        (path / "config.json").write_text(json.dumps({"case": "P05", "arm": "simple_feedback", "cell": "E",
                 "env_seed": 35005, "gamma": "9/10", "diagnostic_fee": "1/10"}))
        (path / "result.json").write_text(json.dumps(result))
        (path / "requests.jsonl").write_text("\n".join(json.dumps({"request": r}) for r in requests))
        return path, requests

    def test_checkpoint_actual_history_and_only_one_rejection_changes(self):
        with TemporaryDirectory() as directory:
            path, requests = self.checkpoint_archive(directory)
            old, oq, _ = p05_checkpoint(path, "original")
            new, nq, provenance = p05_checkpoint(path, "specific")
            self.assertEqual(oq["messages"], requests[4]["messages"])
            self.assertEqual(oq["messages"][:-1], nq["messages"][:-1])
            self.assertNotEqual(oq["messages"][-1]["content"], nq["messages"][-1]["content"])
            self.assertNotIn("tool_choice", oq)
            self.assertNotIn("tool_choice", nq)
            self.assertEqual(provenance["prior_model_requests"], 4)
            for s in (old, new):
                self.assertEqual(s.view()["remaining_calls"], 2)
                self.assertEqual(s._write_feedback, "original")
                bad = deepcopy(s.events[-1]["arguments"])
                receipt = s.call(WRITE, bad)
                self.assertEqual(receipt["error"], "An actual primary or granularity-verified backup evidence_ref is required.")

    def test_checkpoint_repair_is_model_bound_and_strict_failure_is_retained(self):
        with TemporaryDirectory() as directory:
            path, _ = self.checkpoint_archive(directory)
            for condition in ("original", "specific"):
                s, request, _ = p05_checkpoint(path, condition)
                plan = [(WRITE, lambda r: {"record_id": RESOURCE,
                            "content": next(x["content"] for x in r if "pending_ref" in x),
                            "evidence_ref": next(x["evidence_ref"] for x in r if "evidence_ref" in x)}),
                        (VERIFY, lambda r: {"publication_id": r[-1]["publication_id"]})]
                a, actual = client_agent(plan)
                result = run_episode(a, s, initial_messages=request["messages"], request_limit=8)
                self.assertEqual(actual[0]["messages"], request["messages"])
                self.assertTrue(result["obligations_complete"])
                self.assertFalse(result["strict_success"])
                self.assertEqual(result["illegal_calls"], 1)
                self.assertEqual(len(result["events"]), 7)
                self.assertEqual(F(result["execution_fee"]), 6)
                self.assertEqual(F(result["diagnostic_fee"]), F(1, 10))
                self.assertTrue(all("tool_choice" not in q for q in actual))
                self.assertEqual(len(s.effects), 1)

    def test_checkpoint_refuses_corrupted_prefix(self):
        with TemporaryDirectory() as directory:
            path, _ = self.checkpoint_archive(directory)
            result = json.loads((path / "result.json").read_text())
            result["events"][2]["result"]["content"] = "fabricated"
            (path / "result.json").write_text(json.dumps(result))
            with self.assertRaises(ValueError):
                p05_checkpoint(path, "original")

    def test_checkpoint_episode_archives_explicit_feedback_and_guards_first_request(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            path, _ = self.checkpoint_archive(source)
            for condition in ("original", "specific"):
                a, _ = client_agent([])
                with patch("extensions.toolmaze_recovery.gate34b.VLLMAgent", return_value=a):
                    out = Path(directory) / condition
                    result = episode(out, PAIRS[4], "react", "http://127.0.0.1:1/v1",
                                     write_feedback=condition, resume_source=path)
                config = json.loads((out / "config.json").read_text())
                self.assertEqual(config["write_feedback"], condition)
                self.assertEqual(config["feedback_scope"], "checkpoint_rejection_only")
                self.assertEqual(config["continuation_request_cap"], 8)
                self.assertFalse(result["sdk_error"])
                self.assertEqual(result["model_requests"], 1)
                self.assertEqual(len(result["events"]), 5)  # Executor never repairs model parameters.
                self.assertFalse(result["obligations_complete"])
                with self.assertRaises(FileExistsError):
                    episode(out, PAIRS[4], "react", "http://127.0.0.1:1/v1",
                            write_feedback=condition, resume_source=path)

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
