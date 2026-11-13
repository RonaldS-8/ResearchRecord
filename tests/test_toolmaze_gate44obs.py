"""Fake SDK through the real observation function, never real inference."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from test_toolmaze_gate34b import client_agent
from extensions.toolmaze_recovery.gate44obs import observe, PLAN
from extensions.toolmaze_recovery.gate34a import MAIN

class ObservationTests(unittest.TestCase):
    def test_roles_logs_usage_and_no_forcing(self):
        with TemporaryDirectory() as d:
            for mech,arm in PLAN:
                a,requests=client_agent([]);a.temperature=0;a.max_tokens=6144;a.request_timeout=120
                r=observe(a,mech,arm,Path(d)/(mech+arm),lambda m,t:('fake rendered chat',100),evidence_kind='CPU_fake_SDK')
                self.assertEqual(r['sdk_requests'],1)
                self.assertEqual(len(r['events']),3 if mech=='M3' else 4)
                self.assertNotIn('tool_choice',requests[0])
                row=json.loads((Path(d)/(mech+arm)/'requests.jsonl').read_text())
                self.assertIn('usage',row['response']);self.assertIn('public_view',row)
                self.assertEqual(row['request']['messages'][-1]['role'],'user' if arm=='R1' else 'tool')
    def test_context_stop_does_not_call_sdk(self):
        with TemporaryDirectory() as d:
            a,requests=client_agent([]);a.temperature=0;a.max_tokens=6144;a.request_timeout=120
            r=observe(a,'M3','R0',Path(d)/'x',lambda m,t:('too long',32768),evidence_kind='CPU_fake_SDK')
            self.assertTrue(r['budget_stopped']);self.assertEqual(requests,[])
    def test_bad_arguments_untouched(self):
        with TemporaryDirectory() as d:
            a,_=client_agent([(MAIN,{})]);a.temperature=0;a.max_tokens=6144;a.request_timeout=120
            r=observe(a,'M3','R1',Path(d)/'x',lambda m,t:('fake',100),evidence_kind='CPU_fake_SDK')
            self.assertEqual(r['transitions'][0]['arguments'],{})
            self.assertTrue(r['events'][3]['illegal'])
    def test_sdk_error_is_preserved(self):
        with TemporaryDirectory() as d:
            a,_=client_agent([]);a.temperature=0;a.max_tokens=6144;a.request_timeout=120
            def fail(**kw):raise RuntimeError('deliberate SDK fault')
            a.client.chat.completions.create=fail
            r=observe(a,'M4','R0',Path(d)/'x',lambda m,t:('fake',100),evidence_kind='CPU_fake_SDK')
            row=json.loads((Path(d)/'x'/'requests.jsonl').read_text())
            self.assertIn('error',row);self.assertEqual(r['sdk_requests'],1)
    def test_internal_sdk_attempts_capped(self):
        from evaluation.agents.base_agent import AgentAction
        with TemporaryDirectory() as d:
            a,requests=client_agent([])
            def many():
                for _ in range(13):
                    try:a.client.chat.completions.create(model=a.model,messages=[],tools=[],temperature=0,max_tokens=6144,timeout=120)
                    except RuntimeError:break
                return AgentAction(type='final_answer',content='Blocked: cap')
            a.step=many
            r=observe(a,'M3','R0',Path(d)/'x',lambda m,t:('fake',100),evidence_kind='CPU_fake_SDK')
            self.assertEqual(len(requests),12);self.assertTrue(r['budget_stopped'])
