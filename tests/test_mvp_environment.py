import unittest
from extensions.toolmaze_diagnostic_mvp.environment import CONFIG, RecoverySession, resolve
from extensions.toolmaze_diagnostic_mvp.policies import theory


class EnvironmentTests(unittest.TestCase):
    def test_theory_all_cases(self):
        for task in CONFIG['tasks']:
            view=RecoverySession(task,'P1').view()
            self.assertEqual(theory(view)['gross_information_value'],.5)
            self.assertEqual(.5-CONFIG['diagnostic_costs']['low'],.25)
            self.assertEqual(.5-CONFIG['diagnostic_costs']['high'],-.25)

    def test_retry_and_switch_all_cases(self):
        for task,(r,s) in CONFIG['tasks'].items():
            for mode in ('P1','P2'):
                a=RecoverySession(task,mode); a.act('retry')
                self.assertEqual(a.view()['done'],mode=='P1')
                self.assertEqual(a.audit()['recovery_tool_calls'],r if mode=='P1' else 1)
                b=RecoverySession(task,mode); b.act('switch')
                self.assertTrue(b.view()['done']); self.assertEqual(b.audit()['recovery_tool_calls'],s)

    def test_repeated_diagnosis_and_budget(self):
        a=RecoverySession('018','P2','high'); a.act('diagnose'); a.act('diagnose')
        self.assertEqual(a.audit()['diagnostic_cost'],1.5)
        for _ in range(CONFIG['max_decisions']-2): a.act('diagnose')
        with self.assertRaises(ValueError): a.act('diagnose')

    def test_binding_resolves_actual_values(self):
        self.assertEqual(resolve({'x':'{{ s4b1.currency }}','y':'user_input.city'}, {'city':'Tokyo'}, {'s4b1':{'currency':'USD'}}),{'x':'USD','y':'Tokyo'})
        with self.assertRaises(KeyError): resolve('{{ s4b1.currency }}',{}, {})


if __name__=='__main__': unittest.main()
