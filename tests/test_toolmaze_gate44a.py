"""CPU only; no network/model requests."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from test_toolmaze_gate34b import client_agent as fake_agent
from extensions.toolmaze_recovery import gate44a as g
from extensions.toolmaze_recovery.gate34a import MAIN, RESOURCE

class Gate44PreparationTests(unittest.TestCase):
    def test_freeze_and_fairness(self):
        with TemporaryDirectory() as d:
            m = g.prepare(Path(d)/'frozen', lambda: fake_agent([])[0])
            self.assertEqual(m['status'], 'Not Ready')
            for mechanism in ('M3','M4'):
                p=Path(d)/'frozen'/mechanism
                base=json.loads((p/'R0-prompt.json').read_text())
                for arm in g.ARMS[1:]:
                    other=json.loads((p/(arm+'-prompt.json')).read_text())
                    self.assertEqual(other['messages'][:-1],base['messages'])
                    self.assertEqual(other['tools'],base['tools'])
                self.assertEqual(g.digest(g.restored(mechanism).public()),m['checkpoints'][mechanism]['public_sha256'])
    def test_four_arms_actual_native_loop(self):
        with TemporaryDirectory() as d:
            for mechanism in ('M3','M4'):
                for arm in g.ARMS:
                    a, calls=fake_agent([])
                    original_client=a.client
                    result=g.run_protocol(a,mechanism,arm,Path(d)/(mechanism+arm))
                    self.assertIs(a.client,original_client)
                    self.assertEqual(result['sdk_requests'],1)
                    self.assertEqual(len(result['events']),result['prefix_calls'])
                    self.assertNotIn('tool_choice',calls[0])
                    self.assertIn('usage',json.loads((Path(d)/(mechanism+arm)/'requests.jsonl').read_text())['response'])
    def test_restore_and_isolation(self):
        a,b=g.restored('M3'),g.restored('M3')
        self.assertEqual(a.public(),b.public())
        a.call(MAIN,{'record_id':RESOURCE})
        self.assertNotEqual(len(a.events),len(b.events))
        self.assertEqual(len(b.events),3)
        view=b.public();view.clear();self.assertTrue(b.public())
    def test_wrong_args_are_not_repaired(self):
        with TemporaryDirectory() as d:
            a,_=fake_agent([(MAIN,{})])
            r=g.run_protocol(a,'M3','R1',Path(d)/'wrong')
            self.assertEqual(r['events'][3]['arguments'],{})
            self.assertTrue(r['events'][3]['illegal'])
    def test_unknown_training_is_not_fitted_memory(self):
        t=g.empty_training();self.assertEqual(t['support'],0);self.assertIsNone(t['btm']);self.assertFalse(t['sources'])
    def test_sdk_cap_counts_internal_requests(self):
        from evaluation.agents.base_agent import AgentAction
        with TemporaryDirectory() as d:
            a,_=fake_agent([])
            def many():
                for _ in range(13):
                    try:a.client.chat.completions.create(messages=[],model='fake')
                    except RuntimeError:break
                return AgentAction(type='final_answer',content='Blocked: cap')
            a.step=many
            r=g.run_protocol(a,'M4','R0',Path(d)/'cap')
            self.assertEqual((r['sdk_requests'],r['cap_rejections']),(12,1))
    def test_successful_model_supplied_suffixes(self):
        from extensions.toolmaze_recovery.gate42a import ARCHIVE, ALTWRITE, CONFIRM
        from extensions.toolmaze_recovery.gate34a import VALIDATE, WRITE, VERIFY, CONTENT
        # Only the fake model produces these arguments; runner never has a binder.
        def write(receipts):
            return {'record_id':RESOURCE,'content':CONTENT,'evidence_ref':next(r['evidence_ref'] for r in reversed(receipts) if 'evidence_ref' in r)}
        def verify(receipts):return {'publication_id':receipts[-1]['publication_id']}
        plans={'M3':[(ARCHIVE,{'record_id':RESOURCE}),(VALIDATE,lambda r:{'record_id':RESOURCE,'pending_ref':r[-1]['pending_ref']}),(WRITE,write),(VERIFY,verify)],
               'M4':[(ALTWRITE,write),(CONFIRM,lambda r:{'record_id':RESOURCE,'pending_publication_ref':r[-1]['pending_publication_ref']}),(VERIFY,verify)]}
        with TemporaryDirectory() as d:
            for mechanism,plan in plans.items():
                for arm in g.ARMS:
                    a,_=fake_agent(plan)
                    r=g.run_protocol(a,mechanism,arm,Path(d)/(mechanism+arm))
                    self.assertTrue(r['strict_success'],r)
