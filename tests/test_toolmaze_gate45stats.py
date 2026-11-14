import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from test_toolmaze_gate34b import client_agent
from extensions.toolmaze_recovery.gate45stats import ARMS,plan,advice,frozen_information
from extensions.toolmaze_recovery.gate44a import restored,BTM
from extensions.toolmaze_recovery.gate44obs import observe

class StatisticalProtocolTests(unittest.TestCase):
    def test_fitting_public_history_only(self):
        pool=[]
        for m in ('M3','M4'):
            s=restored(m)
            for _ in range(2):
                pool.append({'mechanism':m,'events':s.events,'checkpoint':len(s.events),'strict_success':False,'remaining_fees':{'execution':'0','diagnosis':'0'}})
        for m in ('M3','M4'):
            info=frozen_information(pool,m)
            self.assertEqual(info['training_episodes'],2)
            self.assertEqual(info['acv']['stop']['support'],2)
            self.assertIsNone(info['acv']['read_primary_record']['completion'])
            self.assertIn(BTM,advice('R2',info))
            self.assertIsNone(info['hmm']['recommendation'])
            self.assertEqual(len(plan()),60)
    def test_information_does_not_control_model(self):
        with TemporaryDirectory() as d:
            for arm in ARMS:
                a,requests=client_agent([]);a.temperature=0;a.max_tokens=6144;a.request_timeout=120
                r=observe(a,'M4',arm,Path(d)/arm,lambda m,t:('fake',100),evidence_kind='CPU_fake_SDK',run_id='045-stat-01',seed=452001,collection_session=restored('M4'),collection_advice='suggested tool: prepare_alternate_publication')
                self.assertEqual(len(r['transitions']),0)
                self.assertNotIn('tool_choice',requests[0])
                self.assertEqual(len(requests[0]['tools']),len(restored('M4').public()['tools']))
