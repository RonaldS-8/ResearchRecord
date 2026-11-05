"""Gate 5: sample each hidden-state pair's first decision exactly once."""
import argparse
from collections import Counter
import copy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import statistics
import subprocess
import time
import traceback

from .environment import CONFIG, ROOT, RecoverySession
from .model_adapter import MODEL_CONFIG, SYSTEM, RecordedModelPolicy, ProtocolFailure, public_model_view
from .run_qwen import decision_errors, dump, snapshot, summarize
from .verification import evaluate

REGISTRATION = '69ec7fd'
SEEDS = (0, 1, 2)
COST_SENTENCE = '决策前比较重试、切换和诊断的预期总成本，诊断收益不足时不要购买。'
PROMPTS = {'original': SYSTEM, 'cost': SYSTEM + '\n' + COST_SENTENCE}


class PairedPolicy(RecordedModelPolicy):
    def __init__(self, prompt, seed, temperature=1, client=None):
        super().__init__(client=client)
        self.agent.messages[0]['content'] = PROMPTS[prompt]
        self.prompt, self.seed, self.temperature = prompt, seed, temperature

    def request(self, view, turn):
        value = super().request(view, turn)
        value.update(seed=self.seed + turn, temperature=self.temperature)
        return value

    def fork(self):
        # Never copy a transport/client or an environment; only the sampled conversation.
        other = PairedPolicy(self.prompt, self.seed, self.temperature)
        other.agent.messages = copy.deepcopy(self.agent.messages)
        other.started = self.started
        return other


def resource_totals(records):
    requests = [r for r in records if r['event'] == 'request']
    responses = [r for r in records if r['event'] == 'response']
    known = [r['response']['usage'] for r in responses if r['response'].get('usage') is not None]
    return {
        'model_requests': len(requests), 'unknown_usage_requests': len(requests) - len(known),
        'known_token_totals': {k: sum(u.get(k, 0) or 0 for u in known)
                               for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')},
        'request_latencies': [r['latency_seconds'] for r in records
                              if r['event'] in ('response', 'request_error')]}


def attributed_resources(shared, own):
    """Half of the shared physical request belongs to each environment trajectory."""
    a, b = resource_totals(shared), resource_totals(own)
    return {
        'model_requests': a['model_requests'] / 2 + b['model_requests'],
        'unknown_usage_requests': a['unknown_usage_requests'] / 2 + b['unknown_usage_requests'],
        'known_token_totals': {k: a['known_token_totals'][k] / 2 + b['known_token_totals'][k]
                               for k in a['known_token_totals']},
        # Full initial latency in each trajectory describes perceived decision latency;
        # physical totals are separately computed from the once-only request ledger.
        'request_latencies': a['request_latencies'] + b['request_latencies']}


def pair(task, price, prompt, seed, out, policy_factory=PairedPolicy):
    key = f'{task}_{price}_{prompt}_{seed}'
    sessions, rows, records = {}, [], []
    branches = {'shared': [], 'P1': [], 'P2': []}
    started = time.perf_counter()
    status, fatal = 'completed', None
    with (out / f'{key}.jsonl').open('x') as stream:
        def recorder(branch):
            def record(value):
                entry = {'branch': branch, **value}
                records.append(entry); branches[branch].append(entry)
                stream.write(json.dumps(entry, ensure_ascii=False) + '\n'); stream.flush()
            return record
        try:
            sessions = {m: RecoverySession(task, m, price) for m in ('P1', 'P2')}
            views = {m: sessions[m].view() for m in sessions}
            policies = {m: policy_factory(prompt, seed) for m in sessions}
            requests = {m: policies[m].request(views[m], 0) for m in sessions}
            if requests['P1'] != requests['P2']:
                raise ProtocolFailure('paired_initial_requests_differ')
            request_hash = hashlib.sha256(json.dumps(requests['P1'], sort_keys=True).encode()).hexdigest()
            recorder('shared')({'event': 'paired_request_verified', 'request_sha256': request_hash})
            initial = policies['P1'].choose(views['P1'], 0, recorder('shared'))
            # Each fork starts with the SAME real assistant message, before any feedback.
            policies = {m: policies['P1'].fork() for m in sessions}
            for mode in sessions:
                branch_start = time.perf_counter()
                session, policy = sessions[mode], policies[mode]
                view, errors, public_views = views[mode], [], []
                for turn in range(CONFIG['max_decisions']):
                    public_views.append(public_model_view(view))
                    action = initial if turn == 0 else policy.choose(view, turn, recorder(mode))
                    errors.extend(decision_errors(view, action, turn))
                    view = session.act(action)
                    recorder(mode)({'event': 'environment_audit', 'turn': turn, 'audit': session.audit()})
                    policy.feedback(action, view, recorder(mode))
                    if view['done']:
                        break
                if not view['done']:
                    raise ProtocolFailure('decision_budget_exhausted')
                audit = session.audit()
                score = evaluate(task, mode, audit['events'])
                if score['native_pass'] != score['independent_valid']:
                    raise ProtocolFailure('scoring_anomaly')
                if not score['legal_success']:
                    raise ProtocolFailure('basic_recovery_failed')
                row = {**audit, 'task': task, 'price': price, 'prompt': prompt, 'seed': seed,
                       'status': 'completed', 'score': score, 'error_types': errors,
                       'public_views': public_views, 'initial_action': initial,
                       'shared_request': key + '.jsonl#shared',
                       'wall_elapsed_seconds': time.perf_counter() - branch_start,
                       **attributed_resources(branches['shared'], branches[mode])}
                dump(out / f'{key}_{mode}.json', row)
                rows.append(row)
        except Exception as exc:
            status, fatal = 'stopped', {'error': repr(exc), 'traceback': traceback.format_exc()}
            recorder('shared')({'event': 'fatal_stop', **fatal})
            # Preserve both states even if the second state was never executed.
            for mode, session in sessions.items():
                dump(out / f'{key}_{mode}_partial.json', session.audit())
    result = {'key': key, 'task': task, 'price': price, 'prompt': prompt, 'seed': seed,
              'status': status, 'fatal': fatal, 'rows': rows,
              'initial_action': locals().get('initial'),
              'paired_request_sha256': locals().get('request_hash'),
              'physical_resources': resource_totals(records),
              'wall_elapsed_seconds': time.perf_counter() - started}
    dump(out / f'{key}_pair.json', result)
    return result


def group_summary(pairs):
    rows = [r for p in pairs for r in p['rows']]
    base = summarize(rows)
    base['pair_count'] = len(pairs)
    base['completed_pairs'] = sum(p['status'] == 'completed' for p in pairs)
    for price, group in base['groups'].items():
        ps = [p for p in pairs if p['price'] == price]
        rs = [r for r in rows if r['price'] == price]
        actions = Counter(p['initial_action'] for p in ps if p['initial_action'] is not None)
        n = sum(actions.values())
        group.update(initial_action_counts=dict(actions),
                     initial_action_proportions={a: actions[a] / n if n else None
                                                 for a in ('retry', 'switch', 'diagnose')},
                     all_decision_action_counts=dict(Counter(d['action'] for r in rs for d in r['decisions'])),
                     native_completed=sum(r['score']['native_pass'] for r in rs),
                     independently_valid=sum(r['score']['independent_valid'] for r in rs))
        ledger = [p['physical_resources'] for p in ps]
        latencies = [v for p in ledger for v in p['request_latencies']]
        group['physical_resources'] = {
            'model_requests': sum(p['model_requests'] for p in ledger),
            'unknown_usage_requests': sum(p['unknown_usage_requests'] for p in ledger),
            'token_totals': {k: sum(p['known_token_totals'][k] for p in ledger)
                             for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')},
            'total_request_latency_seconds': sum(latencies),
            'mean_request_latency_seconds': statistics.mean(latencies) if latencies else None,
            'mean_pair_wall_seconds': statistics.mean(p['wall_elapsed_seconds'] for p in ps)}
        # Parent helper's list duplicates shared perceived latency; publish only ledger mean.
        group['mean_request_latency_seconds'] = group['physical_resources']['mean_request_latency_seconds']
        group['branch_wall_excludes_shared_initial_request'] = True
        group.pop('cost_advantage_claim_allowed', None)
    return base


def summary(pairs):
    groups = {}
    for prompt in PROMPTS:
        ps = [p for p in pairs if p['prompt'] == prompt]
        if ps:
            groups[prompt] = {'pooled': group_summary(ps),
                              'by_seed': {str(seed): group_summary([p for p in ps if p['seed'] == seed])
                                          for seed in SEEDS if any(p['seed'] == seed for p in ps)}}
    result = {'prompts': groups}
    if len(pairs) == 120 and all(p['status'] == 'completed' for p in pairs):
        high = {p: [groups[p]['by_seed'][str(s)]['groups']['high'] for s in SEEDS] for p in PROMPTS}
        result['registered_descriptive_checks'] = {
            'original_high_diagnosis_at_least_half_every_seed': all(
                g['initial_action_proportions']['diagnose'] >= .5 for g in high['original']),
            'cost_prompt_solves_high_price_in_this_run': all(
                b['initial_action_proportions']['diagnose'] < a['initial_action_proportions']['diagnose']
                and b['legal_completion_rate'] >= a['legal_completion_rate']
                and b['mean_recovery_cost_all_attempts'] <= 4.05
                for a, b in zip(high['original'], high['cost']))}
    return result


def deterministic_checks(out):
    rows, by_temp = [], {}
    view = RecoverySession('018', 'P1', 'high').view()
    with (out / 'requests.jsonl').open('x') as stream:
        for temperature in (1, 0):
            requests, messages, actions = [], [], []
            for repeat in range(3):
                records = []
                def record(value):
                    entry = {'temperature': temperature, 'repeat': repeat, **value}
                    records.append(entry)
                    stream.write(json.dumps(entry, ensure_ascii=False) + '\n'); stream.flush()
                policy = PairedPolicy('original', 0, temperature)
                action = policy.choose(view, 0, record)
                request = next(r['request'] for r in records if r['event'] == 'request')
                response = next(r['response'] for r in records if r['event'] == 'response')
                requests.append(request); messages.append(response['choices'][0]['message']); actions.append(action)
                rows.append({'temperature': temperature, 'repeat': repeat, 'action': action,
                             'physical_resources': resource_totals(records)})
            if not all(r == requests[0] for r in requests):
                raise ProtocolFailure('determinism_check_requests_differ')
            by_temp[str(temperature)] = {'actions': actions, 'all_actions_equal': len(set(actions)) == 1,
                                         'all_assistant_messages_equal': all(m == messages[0] for m in messages),
                                         'requests_identical': True}
    result = {'status': 'completed', 'comparisons': by_temp, 'requests': rows}
    dump(out / 'determinism_results.json', result)
    return result


def config_snapshot():
    processes = subprocess.check_output(['ps', '-eo', 'pid,args'], text=True)
    vllm_root = Path(importlib.metadata.distribution('vllm').locate_file('vllm'))
    sampling_sources = {}
    for relative, ranges in {
        'config/model.py': ((325, 340), (1816, 1859)),
        'entrypoints/openai/chat_completion/serving.py': ((168, 181), (320, 344)),
        'entrypoints/openai/chat_completion/protocol.py': ((615, 750),),
    }.items():
        path = vllm_root / relative
        source = path.read_text()
        sampling_sources[relative] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'excerpts': [{'first_line': start, 'text': '\n'.join(source.splitlines()[start - 1:end])}
                         for start, end in ranges]}
    return {'registration_commit': REGISTRATION,
            'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'model_config': MODEL_CONFIG, 'prompts': PROMPTS, 'seeds': SEEDS,
            'environment_config': CONFIG, 'provenance': snapshot(list(CONFIG['tasks'])),
            'packages': {p: importlib.metadata.version(p) for p in ('vllm', 'transformers', 'openai')},
            'served_models': PairedPolicy('original', 0).agent.client.models.list().model_dump(mode='json'),
            'service_processes': [line for line in processes.splitlines() if 'vllm serve ' in line],
            'service_script': (ROOT / 'benchmarks/ToolMaze/evaluation/scripts/serve_local_vllm.sh').read_text(),
            'model_generation_config': json.loads((ROOT / 'models' / MODEL_CONFIG['model'] / 'generation_config.json').read_text()),
            'installed_sampling_sources': sampling_sources,
            'sampling_interpretation': 'Request temperature and seed are explicit; installed vLLM auto generation config supplies omitted top_k/top_p. Numerical determinism is not established.',
            'experiment_concurrent_requests': 1, 'actual_numerical_kernel_determinism': 'not_verified'}


def specs():
    for si, seed in enumerate(SEEDS):
        for ti, task in enumerate(CONFIG['tasks']):
            for pi, price in enumerate(CONFIG['diagnostic_costs']):
                order = ('original', 'cost') if (si + ti + pi) % 2 == 0 else ('cost', 'original')
                for prompt in order:
                    yield task, price, prompt, seed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('smoke', 'determinism', 'full'), required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--prerequisite', type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    pairs = []
    try:
        config = config_snapshot()
        if MODEL_CONFIG['model'] not in [m['id'] for m in config['served_models']['data']]:
            raise ProtocolFailure('registered_model_not_served')
        dump(args.out / 'config.json', config)
        if args.stage != 'smoke':
            expected = 'smoke' if args.stage == 'determinism' else 'determinism'
            if args.prerequisite is None:
                raise ProtocolFailure('missing_prerequisite')
            prior = json.loads((args.prerequisite / 'evaluation.json').read_text())
            prior_config = json.loads((args.prerequisite / 'config.json').read_text())
            if prior['status'] != 'completed' or prior['stage'] != expected:
                raise ProtocolFailure('failed_prerequisite')
            for field in ('commit', 'model_config', 'prompts', 'seeds', 'environment_config', 'provenance', 'service_processes'):
                if prior_config[field] != json.loads(json.dumps(config[field])):
                    raise ProtocolFailure('conditions_changed:' + field)
        if args.stage == 'determinism':
            # Write final status only after the end-of-stage hash check below.
            result = deterministic_checks(args.out)
        else:
            cases = list(specs()) if args.stage == 'full' else [('018', 'low', 'original', 0)]
            for index, case in enumerate(cases):
                print(f'Starting pair {index + 1}/{len(cases)} {case}', flush=True)
                p = pair(*case, args.out); pairs.append(p)
                print(f'Finished {p["key"]}: {p["status"]}, initial={p["initial_action"]}', flush=True)
                if p['status'] != 'completed':
                    break
            result = summary(pairs)
            result.update(status='completed' if len(pairs) == len(cases) and all(p['status'] == 'completed' for p in pairs) else 'stopped',
                          planned_pairs=len(cases), attempted_pairs=len(pairs))
        if snapshot(list(CONFIG['tasks'])) != config['provenance']:
            raise ProtocolFailure('frozen_conditions_changed')
        result.update(stage=args.stage, model_conditions_unchanged=True)
        dump(args.out / 'evaluation.json', result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if result['status'] != 'completed':
            raise SystemExit(1)
    except Exception as exc:
        dump(args.out / 'failure.json', {'status': 'stopped', 'stage': args.stage,
             'error': repr(exc), 'traceback': traceback.format_exc(), 'completed_pairs': len(pairs)})
        raise


if __name__ == '__main__':
    main()
