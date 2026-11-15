"""Budget liabilities and actual-argument logging, using fake SDK only."""
import json
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from test_toolmaze_gate34b import client_agent
from test_toolmaze_gate46 import alternate_plan
from extensions.toolmaze_recovery import gate47 as g


class Gate47Tests(unittest.TestCase):
    def test_unresolved_requests_keep_reservation_and_stop_before_overrun(self):
        with TemporaryDirectory() as d:
            b = g.Budget(Path(d)/'budget.json', '1.3')
            b.begin()
            first = b.spent
            with self.assertRaises(RuntimeError):
                b.begin()
            self.assertEqual(b.spent, first)
            self.assertEqual(Decimal(json.loads(b.path.read_text())['reserved_or_settled_cny']), first)

    def test_usage_discount_and_tiers_do_not_double_count_reasoning(self):
        with TemporaryDirectory() as d:
            b = g.Budget(Path(d)/'budget.json', '15')
            b.begin()
            cost = b.settle({'prompt_tokens': 1000, 'completion_tokens': 2000,
                             'prompt_tokens_details': {'cached_tokens': 500},
                             'completion_tokens_details': {'reasoning_tokens': 1500}})
            self.assertEqual(Decimal(cost), Decimal('0.00172'))
            self.assertEqual(b.spent, Decimal(cost))
            b.begin()
            with self.assertRaises(ValueError):
                b.settle({'prompt_tokens': 100, 'completion_tokens': 14000})
            self.assertGreater(b.spent, g.Budget.reserve)

    def test_native_raw_parameters_replayed_without_repair(self):
        with TemporaryDirectory() as d:
            agent, requests = client_agent(alternate_plan('BW0N1'))
            agent.temperature, agent.max_tokens, agent.request_timeout = 0, 6144, 120
            # Fake helper lacks finish_reason; real SDK protocol validation requires it.
            original = agent.client.chat.completions.create
            def backend(**kwargs):
                r = original(**kwargs)
                dump = r.model_dump
                def raw(**kw):
                    value = dump(**kw)
                    value['choices'][0]['finish_reason'] = 'tool_calls' if value['choices'][0]['message'].get('tool_calls') else 'stop'
                    return value
                r.model_dump = raw
                return r
            agent.client.chat.completions.create = backend
            result = g.observe(agent, lambda: g.VariantSession('BW0N1', 'C0'), g.score, Path(d)/'episode', seed=460001)
            self.assertTrue(result['strict_success'])
            self.assertEqual(result['protocol'], 'pass')
            self.assertTrue(all('tool_choice' not in r for r in requests))
            self.assertEqual(requests[1]['messages'][-1]['role'], 'tool')
            self.assertEqual(result['transitions'][0]['arguments']['record_id'], 'REC-5172')


if __name__ == '__main__':
    unittest.main()
