"""Cloud-only recovery audit with original in-memory tools; no model calls."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import copy
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'benchmarks/ToolMaze'))
from evaluation.core.sandbox import ExecutionEngine, InferenceContext
from evaluation.core.judge import JudgeSystem
from evaluation.core.metrics import MetricsCalculator
from evaluation.utils import TraceLogger
from audit_observability import dump


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clone(base):
    env = copy.copy(base)
    env.context = InferenceContext()
    env.perturbation_map = {}
    env._c2_activated = False
    env._c2_activated_tool = None
    env.logger = TraceLogger(base.task_id, base.mode)
    return env


def pending_steps(trace, successful_tools):
    available = Counter(successful_tools)
    pending = []
    for step in trace:
        tool = step['tool_name']
        if available[tool]:
            available[tool] -= 1
        else:
            pending.append(step)
    return pending


def vector(events):
    return dict(sorted(Counter(e['tool'] for e in events).items()))


def expression(counts):
    return ' + '.join(f'{n}*c[{tool}]' for tool, n in sorted(counts.items())) or '0'


def visible(step):
    return {'tool': step['tool_name'], 'arguments': step.get('arguments', {}), 'output': step.get('output', {})}


def call(env, step, events):
    arguments = copy.deepcopy(step.get('arguments', {}))
    output, status = env._intercept_tool_call(step['tool_name'], arguments)
    event = {'tool': step['tool_name'], 'arguments': arguments, 'output': copy.deepcopy(output),
             'perturbation_status': status, 'success': 'error' not in output,
             'reference_output_equal': output == step.get('output')}
    events.append(event)
    env.logger.log_round(len(events), {'type': 'tool_call', 'tool_name': step['tool_name'], 'arguments': arguments}, output, status)
    return event


def run_plan(base, source, position, target, action):
    env, events = clone(base), []
    trace = source['execution_trace']
    for step in trace[:position]:
        event = call(env, step, events)
        if not event['success'] or event['perturbation_status'] != 'clean':
            raise ValueError('Normal source prefix did not succeed cleanly')
    hit = call(env, trace[position], events)
    if hit['success'] or hit['perturbation_status'] != 'perturbed':
        raise ValueError('Expected explicit first fault not observed')
    after_hit = len(events)
    successful_prefix = [e['tool'] for e in events if e['success']]
    continuation = target
    retry_event = None
    if action in ('retry_only', 'retry_then_switch', 'repeat_retry_check'):
        retry_event = call(env, trace[position], events)
        if action == 'repeat_retry_check':
            call(env, trace[position], events)
            continuation = None
        elif retry_event['success']:
            continuation = source
        elif action == 'retry_only':
            continuation = None
    if continuation is not None:
        successful_now = [e['tool'] for e in events if e['success']]
        for step in pending_steps(continuation['execution_trace'], successful_now):
            event = call(env, step, events)
            if not event['success']:
                break
    native_trace = env.logger.to_dict()
    judgement = JudgeSystem().judge(base.task_json, native_trace)
    recovery = events[after_hit:]
    required_missing = len(pending_steps(target['execution_trace'], successful_prefix)) if target else None
    oracle_calls, oracle_method = MetricsCalculator()._compute_oracle_recovery_calls(
        base.task_json, base.mode, trace[position]['tool_name'], successful_prefix)
    return {'action': action, 'source_path': source['path_id'],
            'target_path': target['path_id'] if target else None, 'first_fault_tool': trace[position]['tool_name'],
            'prefix_calls': position, 'after_first_fault_calls': len(recovery),
            'including_first_fault_calls': len(recovery)+1, 'total_calls': len(events),
            'cost_vector_after_fault': vector(recovery), 'symbolic_cost_after_fault': expression(vector(recovery)),
            'sunk_first_fault_vector': {trace[position]['tool_name']: 1},
            'target_path_missing_call_lower_bound': required_missing,
            'achieves_target_path_lower_bound': bool(judgement['pass'] and len(recovery) == required_missing),
            'benchmark_oracle_calls_including_hit': oracle_calls, 'benchmark_oracle_method': oracle_method,
            'native_C2_pass': judgement['pass'], 'judgement': judgement, 'retry_event': retry_event,
            'events': events, 'native_trace': native_trace}


def static_implicit(docs):
    result = {'static_only': True, 'initial_query_equal': False, 'tool_name_set_equal': False, 'paths': []}
    a, b = docs['P3'], docs['P4']
    query = lambda d: d.get('user_input', {}).get('query', d.get('task_description', ''))
    result['initial_query_equal'] = query(a) == query(b)
    names = lambda d: sorted({s['tool_name'] for v in d['valid_paths'] for s in v['execution_trace']})
    result['tool_name_set_equal'] = names(a) == names(b)
    paths = {}
    for mode in ('P3', 'P4'):
        paths[mode] = {}
        for path in docs[mode]['valid_paths']:
            trace = path['execution_trace']
            index = next(i for i, s in enumerate(trace) if s.get('is_perturbed'))
            key = tuple(s['tool_name'] for s in trace[:index+1])
            if key in paths[mode]:
                raise ValueError('Duplicate implicit pre-fault path')
            paths[mode][key] = (trace[:index], trace[index])
    if paths['P3'].keys() != paths['P4'].keys():
        raise ValueError('Unmatched implicit prefixes')
    for key in sorted(paths['P3']):
        p3, f3 = paths['P3'][key]
        p4, f4 = paths['P4'][key]
        result['paths'].append({'prefix_tools_through_fault': key,
            'prefix_visible_equal': [visible(s) for s in p3] == [visible(s) for s in p4],
            'fault_arguments_equal': f3.get('arguments') == f4.get('arguments'),
            'first_fault_output_equal': f3.get('output') == f4.get('output'),
            'output_P3': f3.get('output'), 'output_P4': f4.get('output'),
            'explicit_error_P3': isinstance(f3.get('output'), dict) and 'error' in f3['output'],
            'explicit_error_P4': isinstance(f4.get('output'), dict) and 'error' in f4['output']})
    return result


def audit_task(spec):
    task, filenames = spec
    record = {'task': task, 'hashes': {}, 'cases': []}
    try:
        docs = {}
        for mode, filename in filenames.items():
            path = Path(filename)
            record['hashes'][mode] = sha(path)
            docs[mode] = json.loads(path.read_text())
        record['P0_paths'] = docs['P0']['valid_paths']
        record['P3_P4_static'] = static_implicit(docs)
        for mode in ('P1', 'P2'):
            base = ExecutionEngine(docs[mode], None)
            for path in docs[mode]['valid_paths']:
                trace = path['execution_trace']
                pos = next(i for i, step in enumerate(trace) if step.get('is_perturbed'))
                key = [s['tool_name'] for s in trace[:pos+1]]
                matches = [p for p in docs['P0']['valid_paths']
                           if [s['tool_name'] for s in p['execution_trace'][:pos+1]] == key]
                if len(matches) != 1:
                    raise ValueError('Non-unique P0 source prefix')
                source = matches[0]
                victim = key[-1]
                alternatives = [p for p in docs['P0']['valid_paths'] if victim not in p['tools']]
                case = {'mode': mode, 'source_path': source['path_id'], 'first_fault_tool': victim,
                        'activation_map': base._c2_path_perturbation_maps,
                        'mode_reference_prefix_arguments_equal': [s.get('arguments') for s in trace[:pos+1]] ==
                            [s.get('arguments') for s in source['execution_trace'][:pos+1]],
                        'retry_only': run_plan(base, source, pos, source, 'retry_only'),
                        'switches': [], 'retry_then_switch': []}
                for target in alternatives:
                    case['switches'].append(run_plan(base, source, pos, target, 'switch'))
                    case['retry_then_switch'].append(run_plan(base, source, pos, target, 'retry_then_switch'))
                if mode == 'P2':
                    case['repeat_retry_check'] = run_plan(base, source, pos, None, 'repeat_retry_check')
                switch_success = [r for r in case['switches'] if r['native_C2_pass']]
                retry = case['retry_only']
                case['min_switch_calls_after_fault'] = min((r['after_first_fault_calls'] for r in switch_success), default=None)
                case['retry_calls_after_fault_if_pass'] = retry['after_first_fault_calls'] if retry['native_C2_pass'] else None
                if not case['switches']:
                    raise ValueError('No legal alternative path')
                record['cases'].append(case)
        for mode, filename in filenames.items():
            if sha(Path(filename)) != record['hashes'][mode]:
                raise ValueError('Data changed during audit')
    except Exception as exc:
        record['error'] = repr(exc)
    return record


def self_test():
    trace = [{'tool_name': name} for name in ('shared', 'alt', 'finish')]
    assert [s['tool_name'] for s in pending_steps(trace, ['shared'])] == ['alt', 'finish']
    assert len(pending_steps([{'tool_name': 'x'}, {'tool_name': 'x'}], ['x'])) == 1
    assert expression({'a': 2, 'b': 1}) == '2*c[a] + 1*c[b]'
    assert visible({'tool_name': 'a', 'is_perturbed': True}) == {'tool': 'a', 'arguments': {}, 'output': {}}


def summarize(records):
    result = {'tasks': len(records), 'errors': [], 'modes': {}, 'P3_P4_static': {},
              'task_classification_call_count_only_not_approved_cost': {}, 'approved_cost_comparison': 'unavailable; metrics definition missing'}
    for record in records:
        if 'error' in record:
            result['errors'].append({'task': record['task'], 'error': record['error']})
    for mode in ('P1', 'P2'):
        cases = [c for r in records for c in r['cases'] if c['mode'] == mode]
        allswitch = [run for c in cases for run in c['switches']]
        result['modes'][mode] = {'first_fault_cases': len(cases), 'switch_plans': len(allswitch),
            'switch_pass': sum(r['native_C2_pass'] for r in allswitch),
            'switch_path_lower_bound_achieved': sum(r['achieves_target_path_lower_bound'] for r in allswitch),
            'switch_after_fault_call_counts': dict(Counter(str(r['after_first_fault_calls']) for r in allswitch)),
            'switch_total_call_counts': dict(Counter(str(r['total_calls']) for r in allswitch)),
            'retry_only_pass': sum(c['retry_only']['native_C2_pass'] for c in cases),
            'retry_after_fault_call_counts_if_pass': dict(Counter(str(c['retry_calls_after_fault_if_pass']) for c in cases)),
            'conditional_retry_switch_pass': sum(r['native_C2_pass'] for c in cases for r in c['retry_then_switch']),
            'conditional_retry_switch_after_fault_call_counts': dict(Counter(str(r['after_first_fault_calls']) for c in cases for r in c['retry_then_switch'])),
            'reference_prefix_arguments_equal': sum(c['mode_reference_prefix_arguments_equal'] for c in cases),
            'normal_output_reference_mismatches': sum(not e['reference_output_equal'] for r in allswitch for e in r['events'] if e['perturbation_status'] == 'clean')}
        if mode == 'P2':
            result['modes'][mode]['two_retries_both_perturbed'] = sum(
                all(e['perturbation_status'] == 'perturbed' and not e['success'] for e in c['repeat_retry_check']['events'][-2:]) for c in cases)
    classifications = {}
    for record in records:
        c1 = {c['source_path']: c for c in record['cases'] if c['mode'] == 'P1'}
        c2 = {c['source_path']: c for c in record['cases'] if c['mode'] == 'P2'}
        classes = []
        for key in sorted(set(c1) & set(c2)):
            a, b = c1[key], c2[key]
            s1, r1, s2 = a['min_switch_calls_after_fault'], a['retry_calls_after_fault_if_pass'], b['min_switch_calls_after_fault']
            if s1 is None or s2 is None or r1 is None or b['retry_calls_after_fault_if_pass'] is not None:
                label = 'unresolved_or_behavior_counterexample'
            elif r1 < s1:
                label = 'strict_state_dependent_actions_under_call_count_proxy'
            elif r1 == s1:
                label = 'switch_common_optimum_P1_tie_P2_strict_under_call_count_proxy'
            else:
                label = 'switch_strict_common_optimum_under_call_count_proxy'
            classes.append(label)
        classifications[record['task']] = classes
    result['task_classification_call_count_only_not_approved_cost'] = classifications
    result['task_class_summary'] = dict(Counter(
        next(iter(set(labels))) if labels and len(set(labels)) == 1 else 'mixed_or_unresolved'
        for labels in classifications.values()))
    implicit = [r['P3_P4_static'] for r in records if 'P3_P4_static' in r]
    rows = [p for r in implicit for p in r['paths']]
    result['P3_P4_static'] = {'tasks': len(implicit), 'path_pairs': len(rows),
        'query_equal': sum(r['initial_query_equal'] for r in implicit), 'tool_name_set_equal': sum(r['tool_name_set_equal'] for r in implicit),
        **{k: sum(p[k] for p in rows) for k in ('prefix_visible_equal', 'fault_arguments_equal', 'first_fault_output_equal', 'explicit_error_P3', 'explicit_error_P4')}}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    self_test()
    if args.self_test:
        print('Prefix reuse, lower-bound counting, symbolic expression and metadata filtering checks passed')
        return
    if args.out is None:
        parser.error('--out required')
    args.out.mkdir(parents=True, exist_ok=False)
    protected = [p for folder in ('evaluation/core', 'toolmaze/core', 'tools')
                 for p in (ROOT/'benchmarks/ToolMaze'/folder).rglob('*') if p.suffix in ('.py', '.yaml')]
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in protected}
    dump(args.out/'config.json', {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
         'seed': 0, 'model': None, 'model_version': None, 'inference_calls': 0, 'python': platform.python_version(),
         'cost_definition': 'missing; symbolic only', 'protected_source_hashes': hashes})
    files = {mode: {} for mode in ('P0', 'P1', 'P2', 'P3', 'P4')}
    for mode in files:
        for path in (ROOT/'benchmarks/ToolMaze/data/perturbed_tasks').rglob(f'C2*_{mode}.json'):
            task = path.stem.rsplit('_', 1)[0]
            if task in files[mode]:
                raise ValueError('Duplicate task file')
            files[mode][task] = str(path)
    if any(len(f) != 100 or f.keys() != files['P0'].keys() for f in files.values()):
        raise ValueError('Expected 100 complete C2 mode groups')
    records = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for record in pool.map(audit_task, [(task, {m: files[m][task] for m in files}) for task in sorted(files['P0'])]):
            dump(args.out/f'{record["task"]}.json', record)
            records.append(record)
            if len(records) % 10 == 0:
                print(f'Completed {len(records)}/100 tasks', flush=True)
    summary = summarize(records)
    summary['protected_sources_unchanged'] = all(sha(ROOT/p) == h for p, h in hashes.items())
    dump(args.out/'evaluation.json', summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if summary['errors'] or not summary['protected_sources_unchanged']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
