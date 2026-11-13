"""Gate45 protocol evidence only; fake SDK is never training."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from test_toolmaze_gate34b import client_agent
from extensions.toolmaze_recovery.gate44obs import observe
from extensions.toolmaze_recovery.gate45 import plan, protocol_check

class Gate45Tests(unittest.TestCase):
    def test_fixed_schedule(self):
        p=plan()
        self.assertEqual(len(p),20)
        self.assertEqual(len(set(p)),20)
        self.assertEqual(set(s for s,m,a in p),set(range(450001,450006)))
        for m in ('M3','M4'):
            for a in ('R0','R1'):
                self.assertEqual(sum((m,a)==(x,y) for s,x,y in p),5)
    def test_replay_seed_and_logs(self):
        with TemporaryDirectory() as d:
            for m in ('M3','M4'):
                for arm in ('R0','R1'):
                    a,requests=client_agent([])
                    a.temperature=0;a.max_tokens=6144;a.request_timeout=120
                    folder=Path(d)/(m+arm)
                    r=observe(a,m,arm,folder,lambda m,t:('fake',100),evidence_kind='CPU_fake_SDK',seed=450001,run_id='045-test')
                    self.assertEqual(requests[0]['seed'],450001)
                    self.assertEqual(len(protocol_check(r,folder,m)),64)
