import json
import unittest

from extensions.toolmaze_diagnostic_mvp.environment import CONFIG, RecoverySession
from extensions.toolmaze_diagnostic_mvp.policies import choose


class InformationIsolationTests(unittest.TestCase):
    def test_all_paired_initial_views_are_identical(self):
        for task in CONFIG['tasks']:
            for price in CONFIG['diagnostic_costs']:
                a=RecoverySession(task,'P1',price).view()
                b=RecoverySession(task,'P2',price).view()
                self.assertEqual(json.dumps(a,sort_keys=True),json.dumps(b,sort_keys=True))
                self.assertEqual(a['history'][-1]['output'],CONFIG['error'])

    def test_no_private_fields_or_tags_in_view(self):
        view=RecoverySession('018','P1').view()
        serialized=json.dumps(view)
        for text in ('perturbation_mode','perturbation_status','valid_paths','execution_trace','source_path','raw_output','"P1"','"P2"'):
            self.assertNotIn(text,serialized)

    def test_views_cannot_mutate_backend(self):
        session=RecoverySession('018','P2')
        view=session.view(); view['history'][-1]['output']['error']='P2'
        self.assertEqual(session.view()['history'][-1]['output'],CONFIG['error'])

    def test_diagnostic_is_only_paid_state_channel(self):
        a=RecoverySession('018','P1'); b=RecoverySession('018','P2')
        a.act('diagnose'); b.act('diagnose')
        self.assertTrue(a.view()['decisions'][-1]['result']['retry_will_recover'])
        self.assertFalse(b.view()['decisions'][-1]['result']['retry_will_recover'])
        self.assertEqual(a.audit()['diagnostic_cost'],.25)
        self.assertEqual(b.audit()['diagnostic_cost'],.25)

    def test_normal_policies_receive_no_state(self):
        for name in ('retry_only','switch','retry_then_switch','always_diagnose','cost_selective'):
            self.assertEqual(choose(name,RecoverySession('018','P1').view()),choose(name,RecoverySession('018','P2').view()))


if __name__=='__main__':
    unittest.main()
