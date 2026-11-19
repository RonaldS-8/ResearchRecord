import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from .agent_2015 import bind, business_rule, decide, setup


class RecoveryTests(unittest.TestCase):
    def test_timeout_hides_world(self):
        views=[setup(k)[0] for k in ('C','T','P')]
        self.assertEqual(views[0],views[1])
        self.assertEqual(views[0],views[2])
        self.assertEqual(set(views[0]['history'][-1]),{'tool','arguments','result'})

    def test_unobserved_reference(self):
        with self.assertRaises(IndexError):
            bind({'$ref':'1/content'},[])
        with self.assertRaises(ValueError):
            bind({'$ref':'0/content'},[{'result':{'error':'timeout'}}])

    def test_uncertain_write_is_rejected_before_execution(self):
        view=setup('C')[0]
        name=view['history'][-1]['tool']
        proposal=dict(remaining='only one publication',commit_state='unknown',tool=name,arguments={})
        client=Mock()
        response=client.chat.completions.create.return_value
        response.choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content=json.dumps(proposal)))]
        with self.assertRaisesRegex(ValueError,'read-only'):
            decide(client,'method',view,[])

    def test_rule_follows_contract_even_if_endpoint_renamed(self):
        view=setup('C')[0]
        old_name=business_rule(view)[0]
        for spec in view['contracts']:
            if spec['name']==old_name:
                spec['name']='state_probe'
        self.assertEqual(business_rule(view)[0],'state_probe')


if __name__=='__main__':
    unittest.main()
