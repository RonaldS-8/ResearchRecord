import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from test_toolmaze_gate34b import client_agent
from extensions.toolmaze_recovery.gate45c import schedule, session, payload, RUN
from extensions.toolmaze_recovery.gate44obs import observe
from extensions.toolmaze_recovery.gate42a import MAIN

class CollectionTests(unittest.TestCase):
    def test_balanced_assignment(self):
        rows=schedule()
        self.assertEqual(len(rows),24)
        self.assertEqual(len({r['id'] for r in rows}),24)
        for m in ('M3','M4'):
            for a in {r['action'] for r in rows if r['mechanism']==m}:
                self.assertEqual(sum(r['mechanism']==m and r['action']==a for r in rows),4)
        self.assertEqual(schedule(),rows)
    def test_advice_only_and_public_export(self):
        with TemporaryDirectory() as d:
            for row in schedule():
                a,requests=client_agent([(MAIN,{})]);a.temperature=0;a.max_tokens=6144;a.request_timeout=120
                s,data=payload(row,a)
                r=observe(a,row['mechanism'],row['action'],Path(d)/row['id'],lambda m,t:('fake',100),
                    evidence_kind='CPU_fake_SDK',seed=row['seed'],run_id=RUN,
                    collection_session=s,collection_advice=row['advice'])
                self.assertEqual(requests[0]['messages'],data['messages'])
                self.assertEqual(requests[0]['tools'],data['tools'])
                self.assertNotIn('tool_choice',requests[0])
                self.assertEqual(r['transitions'][0]['arguments'],{})
                self.assertTrue(r['events'][-1]['illegal'])
                self.assertNotIn('_state',str(data))
