"""Cloud-only read-only paired audit. Never calls inference or clean tools."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import copy
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import subprocess
import sys

from audit_observability import ROOT, dump, engine, initial
from evaluation.core.sandbox import InferenceContext


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text):
    if not isinstance(text, str):
        raise TypeError('Classifier input must be error text only')
    return ' '.join(text.casefold().split())


def build_rules(records):
    labels = {}
    for record in records:
        for fault in record['faults']:
            for mode, obs in fault['observations'].items():
                text = json.loads(obs['messages'][-1]['content'])['error']
                labels.setdefault(normalize(text), set()).add(mode)
    return {text: next(iter(modes)) if len(modes) == 1 else None
            for text, modes in sorted(labels.items())}


def classify(text, rules):
    return rules.get(normalize(text))


def append_call(agent, name, arguments, result, index):
    agent.messages.append({'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': f'audit_{index}', 'type': 'function', 'function':
         {'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)}}]})
    agent.receive_tool_result(name, result)


def prefix_steps(trace):
    position = next(i for i, step in enumerate(trace) if step.get('is_perturbed'))
    return trace[:position], trace[position]


def visible_prefix(steps):
    return [{'tool_name': s['tool_name'], 'arguments': s.get('arguments', {}),
             'output': s.get('output', {})} for s in steps]


def error_masked(obs):
    result = copy.deepcopy(obs)
    output = json.loads(result['messages'][-1]['content'])
    if not isinstance(output.get('error'), str):
        raise ValueError('First fault lacks a string error field')
    output['error'] = '<ERROR TEXT>'
    result['messages'][-1]['content'] = json.dumps(output, ensure_ascii=False)
    return result


def self_test():
    rules = {'gateway timeout': 'P1', 'tool not found': 'P2', 'conflict': None}
    assert classify(' GATEWAY  Timeout ', rules) == 'P1'
    assert classify('unknown fault', rules) is None
    assert classify('conflict', rules) is None
    try:
        classify({'error': 'Gateway Timeout', 'mode': 'P1'}, rules)
    except TypeError:
        pass
    else:
        raise AssertionError('Non-text classifier input accepted')
    trace = [{'tool_name': 'a', 'arguments': {}, 'output': {'x': 1},
              'is_perturbed': False, 'ground_truth': 'private'},
             {'tool_name': 'b', 'is_perturbed': True}]
    steps, fault = prefix_steps(trace)
    assert visible_prefix(steps) == [{'tool_name': 'a', 'arguments': {}, 'output': {'x': 1}}]
    assert fault['tool_name'] == 'b'
    fake = {'faults': [{'observations': {m: {'messages': [{'content': '{"error":"same"}'}]}
                                        for m in ('P1', 'P2')}}]}
    assert build_rules([fake]) == {'same': None}


def audit_task(spec):
    task, filenames, rules, development = spec
    record = {'task': task, 'split': 'development' if development else 'holdout',
              'data_sha256': {}, 'template_ids': {}, 'initial': {}, 'paths': []}
    try:
        docs, bases, agents = {}, {}, {}
        for mode, filename in filenames.items():
            path = Path(filename)
            record['data_sha256'][mode] = digest(path)
            docs[mode] = json.loads(path.read_text())
            record['template_ids'][mode] = docs[mode].get('template_id')
            bases[mode], agents[mode] = engine(docs[mode])
            record['initial'][mode] = initial(agents[mode])
        record['initial_equal'] = record['initial']['P1'] == record['initial']['P2']
        record['initial_components_equal'] = {
            'system': agents['P1'].messages[0] == agents['P2'].messages[0],
            'query': agents['P1'].messages[1] == agents['P2'].messages[1],
            'tools_including_order': agents['P1'].tools == agents['P2'].tools,
        }
        paths = {}
        for mode in docs:
            paths[mode] = {}
            for path in docs[mode]['valid_paths']:
                key = tuple(s['tool_name'] for s in path['execution_trace'])
                if key in paths[mode]:
                    raise ValueError('Duplicate tool-sequence path key')
                paths[mode][key] = path
        record['path_count'] = {m: len(p) for m, p in paths.items()}
        if set(paths['P1']) != set(paths['P2']):
            raise ValueError('Unmatched reference path tool sequences')
        for key in sorted(paths['P1']):
            row = {'tool_sequence': key, 'observations': {}, 'errors': {}, 'predictions': {},
                   'reference_prefixes': {}, 'reference_fault_arguments': {}}
            prefixes, faults = {}, {}
            for mode in docs:
                prefixes[mode], faults[mode] = prefix_steps(paths[mode][key]['execution_trace'])
                row['reference_prefixes'][mode] = visible_prefix(prefixes[mode])
                row['reference_fault_arguments'][mode] = faults[mode].get('arguments', {})
            if faults['P1']['tool_name'] != faults['P2']['tool_name']:
                raise ValueError('First fault tools do not match')
            tool = faults['P1']['tool_name']
            arguments = faults['P1'].get('arguments', {})
            for mode in docs:
                # Only isolated in-memory state is changed. No normal plugin is called.
                env = copy.copy(bases[mode])
                env.context = InferenceContext()
                env.perturbation_map = {}
                env._c2_activated = False
                env._c2_activated_tool = None
                agent = copy.copy(agents[mode])
                agent.messages = copy.deepcopy(agents[mode].messages)
                if tool not in env.alternative_tools or tool not in env._c2_path_perturbation_maps.get(tool, {}):
                    raise ValueError('Cannot guarantee fault-only interception')
                for i, step in enumerate(prefixes[mode]):
                    append_call(agent, step['tool_name'], step.get('arguments', {}), step.get('output', {}), i)
                output, status = env._intercept_tool_call(tool, arguments)
                if status != 'perturbed' or output != faults[mode]['output']:
                    raise ValueError('Runtime first fault differs from reference output')
                append_call(agent, tool, arguments, output, len(prefixes[mode]))
                row['observations'][mode] = initial(agent)
                row['errors'][mode] = output['error']
                row['predictions'][mode] = classify(output['error'], rules)
            row['reference_prefix_equal'] = row['reference_prefixes']['P1'] == row['reference_prefixes']['P2']
            row['reference_fault_arguments_equal'] = row['reference_fault_arguments']['P1'] == row['reference_fault_arguments']['P2']
            row['equal_except_error_text'] = error_masked(row['observations']['P1']) == error_masked(row['observations']['P2'])
            a, b = normalize(row['errors']['P1']), normalize(row['errors']['P2'])
            row['error_equal'] = a == b
            row['explicit_opposing_duration'] = ('temporarily' in a and any(
                phrase in b for phrase in ('permanently removed', 'data source retired', 'feature discontinued')))
            row['at_least_one_explicit_duration'] = ('temporarily' in a or any(
                phrase in b for phrase in ('permanently removed', 'data source retired', 'feature discontinued')))
            row['known_category_separation'] = (classify(a, rules) == 'P1' and classify(b, rules) == 'P2')
            record['paths'].append(row)
    except Exception as exc:
        record['error'] = repr(exc)
    return record


def wilson(success, total):
    if not total:
        return None
    z = 1.959963984540054
    p = success / total
    center = (p + z*z/(2*total)) / (1 + z*z/total)
    radius = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / (1 + z*z/total)
    return [center-radius, center+radius]


def evaluate(records):
    counts = Counter()
    confusion = Counter()
    categories = {m: Counter() for m in ('P1', 'P2')}
    task_correct = 0
    for record in records:
        all_correct = bool(record['paths']) and 'error' not in record
        counts['pairs'] += 1
        counts['initial_equal'] += bool(record.get('initial_equal'))
        for row in record['paths']:
            for flag in ('reference_prefix_equal', 'reference_fault_arguments_equal', 'equal_except_error_text',
                         'error_equal', 'explicit_opposing_duration', 'known_category_separation'):
                counts[flag] += row[flag]
            counts['paths'] += 1
            counts['at_least_one_explicit_duration'] += row['at_least_one_explicit_duration']
            for mode in categories:
                text, prediction = row['errors'][mode], row['predictions'][mode]
                categories[mode][text] += 1
                confusion[f'{mode}->{prediction or "abstain"}'] += 1
                counts['observations'] += 1
                counts['covered'] += prediction is not None
                counts['correct'] += prediction == mode
                all_correct = all_correct and prediction == mode
        task_correct += all_correct
    n, total, covered = counts['pairs'], counts['observations'], counts['covered']
    interval = wilson(task_correct, n)
    return {'counts': dict(counts), 'error_categories': {m: dict(c) for m, c in categories.items()},
            'shared_error_categories': sorted(set(categories['P1']) & set(categories['P2'])),
            'confusion': dict(confusion), 'accuracy_including_abstention': counts['correct']/total if total else None,
            'coverage': covered/total if total else None,
            'accuracy_when_covered': counts['correct']/covered if covered else None,
            'recall': {m: confusion[f'{m}->{m}']/sum(categories[m].values()) if categories[m] else None for m in categories},
            'tasks_all_correct': task_correct, 'task_accuracy': task_correct/n if n else None,
            'task_wilson95': interval,
            'reliability_criterion_met': bool(n and total and task_correct/n >= .95 and interval[0] >= .90 and covered/total >= .95)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--development', type=Path, default=ROOT/'results/001-observability-20261105-01')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    self_test()
    if args.self_test:
        print('5 classifier/isolation checks passed')
        return
    if args.out is None:
        parser.error('--out required for audit')
    args.out.mkdir(parents=True, exist_ok=False)
    prior_files = sorted(args.development.glob('C2*.json'))
    if len(prior_files) != 13:
        raise ValueError('Expected exactly 13 previously exposed task pairs')
    prior = [json.loads(p.read_text()) for p in prior_files]
    development = {r['task'] for r in prior}
    rules = build_rules(prior)
    dump(args.out/'rules.json', {'rules': rules, 'source_hashes': {p.name: digest(p) for p in prior_files}})
    # Frozen rule artifact exists before loading any current dataset contents.
    config = {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'seed': 0, 'workers': args.workers, 'model': None, 'model_version': None,
              'inference_calls': 0, 'normal_plugin_calls': 0, 'rules_sha256': digest(args.out/'rules.json'),
              'python': platform.python_version(), 'packages': {p: importlib.metadata.version(p) for p in ('openai', 'pydantic', 'PyYAML')},
              'history_kind': 'reference-prefix reconstruction, not model execution'}
    dump(args.out/'config.json', config)
    files = {m: {} for m in ('P1', 'P2')}
    for mode in files:
        for p in (ROOT/'benchmarks/ToolMaze/data/perturbed_tasks').rglob(f'C2*_{mode}.json'):
            key = p.stem.rsplit('_', 1)[0]
            if key in files[mode]:
                raise ValueError('Duplicate task file')
            files[mode][key] = str(p)
    if set(files['P1']) != set(files['P2']) or len(files['P1']) != 100:
        raise ValueError('Expected exactly 100 complete task pairs')
    if not development <= set(files['P1']):
        raise ValueError('Development task missing from current dataset')
    specs = [(t, {m: files[m][t] for m in files}, rules, t in development) for t in sorted(files['P1'])]
    dump(args.out/'split.json', {'development': sorted(development), 'holdout': sorted(set(files['P1'])-development)})
    records = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for record in pool.map(audit_task, specs, chunksize=1):
            dump(args.out/f'{record["task"]}.json', record)
            records.append(record)
            if len(records) % 10 == 0:
                print(f'Completed {len(records)}/100 pairs', flush=True)
    dev = [r for r in records if r['split'] == 'development']
    hold = [r for r in records if r['split'] == 'holdout']
    templates = {split: {tid for r in rs for tid in r['template_ids'].values()}
                 for split, rs in (('development', dev), ('holdout', hold))}
    errors = [{'task': r['task'], 'error': r['error']} for r in records if 'error' in r]
    source_unchanged = all(digest(Path(files[m][r['task']])) == r['data_sha256'][m]
                           for r in records for m in files)
    prior_unchanged = all(r['data_sha256'] == old['data_sha256'] for r in dev
                          for old in prior if old['task'] == r['task'])
    summary = {'all': evaluate(records), 'development': evaluate(dev), 'holdout': evaluate(hold),
               'errors': errors, 'template_overlap': sorted(templates['development'] & templates['holdout']),
               'source_hashes_unchanged': source_unchanged, 'development_data_matches_prior': prior_unchanged,
               'existing_C2_model_traces': sum(1 for _ in (ROOT/'benchmarks/ToolMaze/evaluation/results').rglob('C2*.json')),
               'limitations': ['Reference histories are not actual model trajectories.',
                   'Repeated error vocabulary; heldout tasks do not imply heldout error families.',
                   'Semantic duration rubric is conservative and does not assert real-world permanence.',
                   'Wilson interval uses task units; shared templates and error generation may remain correlated.',
                   'No diagnostic interface implemented; diagnostic isolation test not claimed.']}
    dump(args.out/'evaluation.json', summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if errors or summary['template_overlap'] or not source_unchanged or not prior_unchanged:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
