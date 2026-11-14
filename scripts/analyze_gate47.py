"""Read-only Gate47 aggregation and evidence references; never reclassifies from success."""
import argparse
from collections import defaultdict
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extensions.toolmaze_recovery.gate44a import restored, digest
from extensions.toolmaze_recovery.gate42a import evaluate
from extensions.toolmaze_recovery.gate46 import VariantSession, score


def h(value):
    return sha256(value).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--results', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    codes = json.loads((Path(__file__).resolve().parents[1]/'docs/evidence/047/blind-coding.json').read_text())['rows']
    mapping = json.loads((a.results/'047-attribution-01/blind-map.json').read_text())
    rows, index, failures, requests = [], {}, [], []
    for run in ('047-api-01', '046-real-agent-01'):
        root = a.results/run
        assert (root/'completed.json').exists(), 'Do not analyze incomplete batches'
        for f in sorted(root.glob('*/result.json')):
            folder = f.parent
            r = json.loads(f.read_text())
            raw = [json.loads(line) for line in (folder/'requests.jsonl').read_text().splitlines()]
            if run == '047-api-01':
                mechanism, variant, contract = folder.name[-2:], None, 'original'
                replay, scorer = restored(mechanism), evaluate
                blind = None
            else:
                mechanism, variant, contract = 'M4', r['variant'], r['contract']
                replay, scorer = VariantSession(variant, contract), score
                blind = mapping[folder.name]
            prefix = len(replay.events)
            suffix = r['events'][prefix:]
            for e in suffix:
                replay.call(e['tool'], e['arguments'])
            expected = scorer(replay, r['answer'])
            assert replay.events == r['events'], (folder, 'policy event replay')
            for k, v in expected.items():
                if k == 'events':
                    # Variant scorer reports canonical events, result adds policy events separately.
                    if run == '047-api-01':
                        assert v == r['events']
                else:
                    assert r[k] == v, (folder, k)
            request_hashes, response_hashes, msg_hashes = [], [], []
            reasoning = []
            for q in raw:
                response, request = q['response'], q['request']
                assert 'error' not in q and 'tool_choice' not in request
                assert response['choices'][0]['finish_reason'] in ('stop', 'tool_calls')
                m = response['choices'][0]['message']
                text = m.get('reasoning') or m.get('reasoning_content') or ''
                reasoning.append({'q': q['index'], 'text': text, 'field': 'reasoning' if m.get('reasoning') else 'reasoning_content'})
                semantic = deepcopy(m)
                for tc in semantic.get('tool_calls') or []:
                    tc.pop('id', None)
                request_hashes.append(digest(request)); response_hashes.append(digest(response)); msg_hashes.append(digest(semantic))
                requests.append({'episode': run+'/'+folder.name, 'q': q['index'], 'started_utc': q['started_utc'],
                                 'created': response.get('created'), 'request_sha256': request_hashes[-1],
                                 'response_sha256': response_hashes[-1], 'message_sha256': msg_hashes[-1],
                                 'reasoning_sha256': h(text.encode()), 'reasoning_field': reasoning[-1]['field'],
                                 'usage': response['usage'], 'usage_cost_cny': q.get('usage_cost_cny'),
                                 'seconds': q['seconds']})
            usages = [q['response']['usage'] for q in raw]
            row = {'id': run+'/'+folder.name, 'checkpoint': mechanism, 'variant': variant, 'contract': contract,
                   'blind_id': blind, 'strict': r['strict_success'], 'obligations': r['obligations_complete'],
                   'protocol': r['protocol'], 'calls': len(suffix), 'illegal': r['illegal_calls'],
                   'binding_accepted': sum(not e['illegal'] for e in suffix), 'sdk': len(raw),
                   'prefix_fee': str(sum((Fraction(e['fee']) for e in r['events'][:prefix]), Fraction())),
                   'suffix_fee': str(sum((Fraction(e['fee']) for e in suffix), Fraction())),
                   'tool_sequence': [e['tool'] for e in suffix],
                   'model_actions': [c['model_action'] for c in r['checkpoints']],
                   'budget_rejections': sum('rejection' in c.get('execution', {}) for c in r['checkpoints']),
                   'input_tokens': sum(u['prompt_tokens'] for u in usages),
                   'output_tokens': sum(u['completion_tokens'] for u in usages),
                   'cached_input_tokens': sum((u.get('prompt_tokens_details') or {}).get('cached_tokens', 0) or 0 for u in usages),
                   'reasoning_tokens': sum((u.get('completion_tokens_details') or {}).get('reasoning_tokens', 0) or 0 for u in usages),
                   'cost_cny': sum(float(q.get('usage_cost_cny') or 0) for q in raw) if run == '047-api-01' else None,
                   'model_seconds': sum(q['seconds'] for q in raw), 'wall_seconds': r['wall_seconds'],
                   'first_request_sha256': request_hashes[0], 'first_message_sha256': msg_hashes[0],
                   'action_trajectory_sha256': r['action_trajectory_sha256'],
                   'attempt_trajectory_sha256': digest([c['model_action'] for c in r['checkpoints']]),
                   'answer': r['answer']}
            rows.append(row)
            if not r['strict_success']:
                evidence = {'id': row['id'], 'blind_id': blind, 'manifestation': 'premature_stop' if not suffix else 'retry_read_retry_exhaustion',
                            'legal_alternative_identified': 'U', 'alternative_satisfies_task': 'U',
                            'feedback_no_commit_understood': 'E', 'selected_suffix_can_complete': False,
                            'initial_budget_feasible_better_path': 'B: CPU verified prepare-confirm-readback, 3 calls',
                            'primary': 'unknown', 'execution_semantic_error': False, 'format_error': False,
                            'recovery_decision_C_under_correct_understanding': 'U', 'reasoning_is_causal_proof': False,
                            'sources': []}
                if blind:
                    coding = codes[blind]
                    evidence.update(primary=coding['primary'], alternative_satisfies_task='E: excluded or misread' if coding['primary']=='A' else 'U')
                    needle = coding['anchor'].lower()
                    found = False
                    for part in reasoning:
                        pos = part['text'].lower().find(needle)
                        if pos >= 0:
                            evidence['sources'].append({'q': part['q'], 'field': part['field'], 'start': pos,
                                'end': pos+len(needle), 'quote': part['text'][pos:pos+len(needle)],
                                'reasoning_sha256': h(part['text'].encode())})
                            found = True
                    assert found, ('Manual evidence anchor missing', blind)
                    # Attention is only explicit when actual tool names occur in the reasoning.
                    evidence['legal_alternative_identified'] = 'E: tool names noticed; legality not necessarily understood' if any('prepare_' in x['text'] for x in reasoning) else 'U: no named prepare in available text'
                else:
                    evidence['secondary'] = 'E budget miscount and unexecuted over-budget proposal' if row['budget_rejections'] else 'B retry/read/retry; motive U'
                    evidence['sources'] = [{'q': x['q'], 'field': x['field'], 'start': 0, 'end': min(len(x['text']), 700),
                        'quote': x['text'][:700], 'reasoning_sha256': h(x['text'].encode())} for x in reasoning]
                failures.append(evidence)
        for f in root.rglob('*'):
            if f.is_file():
                index[str(f.relative_to(a.results))] = h(f.read_bytes())
    groups = []
    by = defaultdict(list)
    for row in rows:
        by[(row['id'].split('/')[0], row['checkpoint'], row['contract'])].append(row)
    for key, group in by.items():
        g = {'run': key[0], 'checkpoint': key[1], 'contract': key[2], 'n': len(group)}
        for k in ('strict','obligations','calls','illegal','binding_accepted','sdk','input_tokens','output_tokens',
                  'cached_input_tokens','reasoning_tokens','model_seconds','wall_seconds','budget_rejections'):
            g[k] = sum(r[k] for r in group)
        g['cost_cny'] = sum(r['cost_cny'] for r in group) if key[0]=='047-api-01' else None
        g['suffix_fee'] = str(sum((Fraction(r['suffix_fee']) for r in group), Fraction()))
        g['prefix_fee'] = str(sum((Fraction(r['prefix_fee']) for r in group), Fraction()))
        for k in ('first_request_sha256','first_message_sha256','action_trajectory_sha256','attempt_trajectory_sha256'):
            g['unique_'+k.removesuffix('_sha256')] = len({r[k] for r in group})
        g['unique_tool_sequences'] = len({tuple(r['tool_sequence']) for r in group})
        groups.append(g)
    for name, value in [('metrics.json', {'episodes': rows, 'groups': groups}), ('failure-evidence.json', failures),
                        ('request-index.json', requests), ('raw-index.json', index)]:
        (a.output/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'groups':groups,'failures':len(failures),'raw_files':len(index)},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
