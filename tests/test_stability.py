import copy
import json
from pathlib import Path
import tempfile
import unittest
import httpx
from openai import BadRequestError

from extensions.toolmaze_diagnostic_mvp.environment import RecoverySession
from extensions.toolmaze_diagnostic_mvp.model_adapter import SYSTEM
from extensions.toolmaze_diagnostic_mvp.run_stability import (
    COST_SENTENCE, PROMPTS, PairedPolicy, pair, resource_totals, specs, group_summary,
    is_context_limit, traversed)
from test_model_adapter import FakeClient, response


class ScriptedPolicy(PairedPolicy):
    clients = []
    bad = False
    error_mode = None
    force_retry = False

    def __init__(self, prompt, seed, temperature=1):
        client = FakeClient(response())
        def create(**kwargs):
            client.requests.append(copy.deepcopy(kwargs))
            last = kwargs['messages'][-1]
            action = 'diagnose'
            if last['role'] == 'tool':
                view = json.loads(last['content'])
                action = 'retry' if view['decisions'][-1]['result']['retry_will_recover'] else 'switch'
            if (self.error_mode == 'context_initial' and last['role'] == 'user') or (
                self.error_mode in ('context_recoverable', 'other400_recoverable')
                and last['role'] == 'tool' and action == 'retry'):
                text = 'maximum context length is 40960 tokens; input_tokens exceeds capacity'
                if self.error_mode == 'other400_recoverable':
                    text = 'invalid tool schema'
                raise BadRequestError(text, response=httpx.Response(400, request=httpx.Request('POST', 'http://test')),
                                      body={'message': text})
            payload = response(action)
            if self.force_retry:
                payload = response('retry')
            if self.bad:
                payload['choices'][0]['message']['tool_calls'] = []
            from types import SimpleNamespace
            return SimpleNamespace(model_dump=lambda **_: copy.deepcopy(payload))
        client.chat.completions.create = create
        self.clients.append(client)
        super().__init__(prompt, seed, temperature, client)

    def fork(self):
        other = ScriptedPolicy(self.prompt, self.seed, self.temperature)
        other.agent.messages = copy.deepcopy(self.agent.messages)
        other.started = self.started
        return other


class StabilityTests(unittest.TestCase):
    def setUp(self):
        ScriptedPolicy.clients = []
        ScriptedPolicy.bad = False
        ScriptedPolicy.error_mode = None
        ScriptedPolicy.force_retry = False

    def test_single_sample_independent_feedback_and_physical_accounting(self):
        with tempfile.TemporaryDirectory() as directory:
            result = pair('018', 'low', 'original', 1, Path(directory), ScriptedPolicy)
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['physical_resources']['model_requests'], 3)
            self.assertEqual(result['physical_resources']['known_token_totals']['total_tokens'], 90)
            self.assertEqual(sum(r['model_requests'] for r in result['rows']), 3)
            self.assertEqual(sum(r['known_token_totals']['total_tokens'] for r in result['rows']), 90)
            self.assertEqual([r['recovery_cost'] for r in result['rows']], [2.25, 3.25])
            requests = [q for c in ScriptedPolicy.clients for q in c.requests]
            first = [q for q in requests if q['messages'][-1]['role'] == 'user']
            later = [q for q in requests if q['messages'][-1]['role'] == 'tool']
            self.assertEqual(len(first), 1)
            self.assertEqual(later[0]['messages'][-2], later[1]['messages'][-2])
            self.assertNotEqual(later[0]['messages'][-1], later[1]['messages'][-1])
            self.assertEqual(first[0]['seed'], 1)
            self.assertTrue(all(q['seed'] == 2 for q in later))
            group = group_summary([result])['groups']['low']
            self.assertEqual(group['physical_resources']['model_requests'], 3)
            self.assertEqual(group['initial_action_proportions']['diagnose'], 1)

    def test_failure_stops_and_preserves_both_partial_states(self):
        ScriptedPolicy.bad = True
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            result = pair('018', 'low', 'original', 0, out, ScriptedPolicy)
            self.assertEqual(result['status'], 'stopped')
            self.assertEqual(result['physical_resources']['model_requests'], 1)
            self.assertEqual(len(list(out.glob('*_partial.json'))), 2)
            self.assertIn('fatal_stop', next(out.glob('*.jsonl')).read_text())

    def test_prompt_changes_one_sentence_only_and_determinism_overrides_only_temperature(self):
        self.assertEqual(PROMPTS['original'], SYSTEM)
        self.assertEqual(PROMPTS['cost'], SYSTEM + '\n' + COST_SENTENCE)
        view = RecoverySession('018', 'P1', 'high').view()
        a = PairedPolicy('original', 0, 1, FakeClient(response())).request(view, 0)
        b = PairedPolicy('original', 0, 0, FakeClient(response())).request(view, 0)
        b['temperature'] = 1
        self.assertEqual(a, b)

    def test_fork_copies_messages_without_aliasing(self):
        policy = ScriptedPolicy('cost', 2)
        policy.choose(RecoverySession('018', 'P1').view(), 0, lambda _: None)
        other = policy.fork()
        self.assertEqual(policy.agent.messages, other.agent.messages)
        other.agent.messages[0]['content'] = 'changed'
        self.assertEqual(policy.agent.messages[0]['content'], PROMPTS['cost'])

    def test_frozen_budget_and_seed_prompt_coverage(self):
        cases = list(specs())
        self.assertEqual(len(cases), 120)
        self.assertEqual(len(set(cases)), 120)
        self.assertEqual({s for _, _, _, s in cases}, {0, 1, 2})
        for task, price, _, seed in cases:
            self.assertEqual(sum(t == task and p == price and s == seed for t, p, _, s in cases), 2)

    def test_failed_request_is_counted_with_unknown_usage(self):
        ledger = resource_totals([{'event': 'request'}, {'event': 'request_error', 'latency_seconds': 1}])
        self.assertEqual(ledger['model_requests'], 1)
        self.assertEqual(ledger['unknown_usage_requests'], 1)

    def test_budget_failure_is_preserved_and_next_pair_can_run(self):
        ScriptedPolicy.force_retry = True
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            result = pair('018', 'high', 'cost', 0, out, ScriptedPolicy, continue_budget=True)
            self.assertEqual(result['status'], 'completed_with_sample_failures')
            self.assertEqual([r['status'] for r in result['rows']], ['completed', 'decision_budget_exhausted'])
            self.assertEqual(len(result['rows'][1]['decisions']), 8)
            self.assertEqual(group_summary([result])['groups']['high']['legal_completion_rate'], .5)
            ScriptedPolicy.force_retry = False
            self.assertEqual(pair('018', 'low', 'cost', 0, out, ScriptedPolicy, continue_budget=True)['status'], 'completed')

    def test_continuation_requires_unique_prefix_and_skips_all_old_samples(self):
        from extensions.toolmaze_diagnostic_mvp.continue_stability import remaining
        from extensions.toolmaze_diagnostic_mvp.model_adapter import ProtocolFailure
        cases = list(specs())
        prior = [{'key': '_'.join(map(str, c))} for c in cases[:79]]
        old, todo = remaining(list(reversed(prior)))
        self.assertEqual(len(old), 79)
        self.assertEqual(todo, cases[79:])
        with self.assertRaises(ProtocolFailure): remaining(prior + prior[:1])
        with self.assertRaises(ProtocolFailure): remaining(prior[1:])

    def test_context_limit_in_first_branch_continues_other_state_and_counts_failure(self):
        ScriptedPolicy.error_mode = 'context_recoverable'
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            result = pair('018', 'low', 'original', 0, out, ScriptedPolicy)
            self.assertEqual(result['status'], 'completed_with_context_limits')
            self.assertTrue(traversed(result['status']))
            self.assertEqual([r['status'] for r in result['rows']], ['context_limit', 'completed'])
            self.assertEqual(result['physical_resources']['model_requests'], 3)
            self.assertEqual(result['physical_resources']['unknown_usage_requests'], 1)
            group = group_summary([result])['groups']['low']
            self.assertEqual(group['attempted'], 2)
            self.assertEqual(group['legal_completion_rate'], .5)
            self.assertFalse(group['cost_comparison_complete'])
            self.assertEqual(group['context_limit_samples'], ['018_low_original_0_P1'])
            ScriptedPolicy.error_mode = None
            later = pair('018', 'high', 'original', 0, out, ScriptedPolicy)
            self.assertEqual(later['status'], 'completed')

    def test_shared_context_limit_is_not_resampled_and_marks_both_states(self):
        ScriptedPolicy.error_mode = 'context_initial'
        with tempfile.TemporaryDirectory() as directory:
            result = pair('018', 'low', 'original', 0, Path(directory), ScriptedPolicy)
            self.assertEqual(result['status'], 'completed_with_context_limits')
            self.assertEqual(result['physical_resources']['model_requests'], 1)
            self.assertEqual(len(result['rows']), 2)
            self.assertTrue(all(r['status'] == 'context_limit' for r in result['rows']))
            self.assertEqual(group_summary([result])['groups']['low']['legal_completion_rate'], 0)

    def test_other_badrequest_still_stops_and_text_alone_is_not_a_capacity_error(self):
        ScriptedPolicy.error_mode = 'other400_recoverable'
        with tempfile.TemporaryDirectory() as directory:
            result = pair('018', 'low', 'original', 0, Path(directory), ScriptedPolicy)
            self.assertEqual(result['status'], 'stopped')
            self.assertFalse(traversed(result['status']))
            # No attempt to request a continuation in the second state.
            self.assertEqual(result['physical_resources']['model_requests'], 2)
        self.assertFalse(is_context_limit(RuntimeError('maximum context length tokens input_tokens')))


if __name__ == '__main__':
    unittest.main()
