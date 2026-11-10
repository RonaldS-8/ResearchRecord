"""Cloud-only paired P3/P4 audit and descriptive dependency inventory."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import copy
import json
import math
from pathlib import Path
import platform
import re
import subprocess

from audit_observability import ROOT, dump, engine, initial
from audit_observability_full import append_call, digest, path_key, prefix_steps, visible_prefix, wilson
from evaluation.core.sandbox import InferenceContext


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def anomaly_flags(value):
    flags = []
    if not isinstance(value, dict):
        flags.append('root_not_object')
    if isinstance(value, dict) and 'error' in value:
        flags.append('explicit_error')
    def walk(item):
        if isinstance(item, float) and not math.isfinite(item):
            flags.append('nonfinite_number')
        elif isinstance(item, str) and item.strip().casefold() in ('corrupted', '[corrupted]', 'invalid'):
            flags.append('literal_anomaly_marker')
        elif isinstance(item, dict):
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
    walk(value)
    return sorted(set(flags))


def shape(value):
    if isinstance(value, dict):
        return ['object', {k: shape(v) for k, v in sorted(value.items())}]
    if isinstance(value, list):
        return ['array', [shape(v) for v in value]]
    if isinstance(value, str):
        marker = value.strip().casefold()
        return ['string', marker if marker in ('corrupted', '[corrupted]', 'invalid') else 'ordinary']
    return ['null' if value is None else 'bool' if isinstance(value, bool)
            else 'integer' if isinstance(value, int) else 'number']


def signature(value, kind):
    return canonical(value if kind == 'exact' else shape(value))


def learn_rules(records):
    tables = {}
    for kind in ('exact', 'shape'):
        labels = {}
        for record in records:
            for row in record['paths']:
                for mode, output in row['outputs'].items():
                    labels.setdefault(signature(output, kind), set()).add(mode)
        tables[kind] = {key: next(iter(modes)) if len(modes) == 1 else None
                        for key, modes in sorted(labels.items())}
    return tables


def predict(output, tables):
    return {kind: table.get(signature(output, kind)) for kind, table in tables.items()}


def mask_last_output(obs):
    masked = copy.deepcopy(obs)
    masked['messages'][-1]['content'] = '<FIRST ANOMALOUS OUTPUT>'
    return masked


def extract_bindings(value, location=''):
    found = []
    if isinstance(value, dict):
        for k, v in value.items():
            found.extend(extract_bindings(v, location+'.'+k if location else k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found.extend(extract_bindings(v, f'{location}[{i}]'))
    else:
        row = {'parameter': location, 'expression': value, 'kind': 'literal'}
        if isinstance(value, str):
            expression = value.strip()
            if re.fullmatch(r'user_input(?:\.[A-Za-z_][\w]*)+', expression):
                row.update(kind='user_input', source=expression)
            else:
                match = re.fullmatch(r'\{\{\s*(s\w+(?:\.\w+)*)\s*\}\}', expression)
                if match is None:
                    match = re.fullmatch(r'(s\d+[a-z]*\d*(?:\.\w+)*)', expression)
                if match:
                    row.update(kind='node_output', source=match.group(1), source_node=match.group(1).split('.')[0])
                elif '{{' in expression or 'user_input.' in expression:
                    row['kind'] = 'unresolved_expression'
        found.append(row)
    return found


def inventory(template, normal):
    nodes = {n['id']: n for n in template['dag']['nodes']}
    paths, issues = [], []
    for path in normal['valid_paths']:
        sequence = path['node_sequence']
        rows = []
        for index, node in enumerate(sequence):
            if node not in nodes:
                issues.append({'path': path['path_id'], 'node': node, 'issue': 'missing_node'})
                continue
            tool = nodes[node]['tool_name']
            bindings = template.get('parameter_bindings', {}).get(tool)
            if bindings is None:
                issues.append({'path': path['path_id'], 'node': node, 'issue': 'missing_tool_bindings'})
            refs = extract_bindings(bindings or {})
            for ref in refs:
                if ref['kind'] == 'node_output':
                    src = ref['source_node']
                    if src not in sequence:
                        issues.append({'path': path['path_id'], 'node': node, 'binding': ref, 'issue': 'source_not_on_path'})
                    elif sequence.index(src) >= index:
                        issues.append({'path': path['path_id'], 'node': node, 'binding': ref, 'issue': 'source_not_prior'})
                elif ref['kind'] == 'unresolved_expression':
                    issues.append({'path': path['path_id'], 'node': node, 'binding': ref, 'issue': 'unresolved_expression'})
            rows.append({'node': node, 'tool': tool, 'raw_bindings': bindings, 'parameter_sources': refs})
        if [r['tool'] for r in rows] != path['tools'] or path['tools'] != [s['tool_name'] for s in path['execution_trace']]:
            issues.append({'path': path['path_id'], 'issue': 'node_tool_trace_mismatch'})
        paths.append({'path_id': path['path_id'], 'nodes': rows})
    return {'template_id': template['template_id'], 'dag': template['dag'],
            'alternative_groups': template.get('alternative_groups', []), 'paths': paths, 'issues': issues}


def audit_task(spec):
    task, files, template_dir = spec
    record = {'task': task, 'paths': [], 'hashes': {m: digest(Path(p)) for m, p in files.items()}}
    try:
        docs = {m: json.loads(Path(p).read_text()) for m, p in files.items()}
        normal = docs['P0']
        template_file = Path(template_dir)/(normal['template_id']+'.json')
        record['template_hash'] = digest(template_file)
        template = json.loads(Path(template_file).read_text())
        record['contract_inventory'] = inventory(template, normal)
        record['template_id'] = template['template_id']
        bases, agents = {}, {}
        for mode in ('P3', 'P4'):
            bases[mode], agents[mode] = engine(docs[mode])
        record['initial'] = {m: initial(a) for m, a in agents.items()}
        record['initial_equal'] = record['initial']['P3'] == record['initial']['P4']
        maps = {m: {path_key(p): p for p in docs[m]['valid_paths']} for m in ('P3', 'P4')}
        if any(len(maps[m]) != len(docs[m]['valid_paths']) for m in maps) or maps['P3'].keys() != maps['P4'].keys():
            raise ValueError('Invalid pre-fault path pairing')
        for key in sorted(maps['P3']):
            row = {'prefix_tools_through_fault': key, 'observations': {}, 'outputs': {}, 'anomaly_flags': {}}
            prefix_values, arg_values = {}, {}
            for mode in maps:
                prefix, fault = prefix_steps(maps[mode][key]['execution_trace'])
                prefix_values[mode] = visible_prefix(prefix)
                arg_values[mode] = fault.get('arguments', {})
                env = copy.copy(bases[mode])
                env.context = InferenceContext()
                env.perturbation_map = {}
                env._c2_activated = False
                env._c2_activated_tool = None
                agent = copy.copy(agents[mode])
                agent.messages = copy.deepcopy(agents[mode].messages)
                tool = fault['tool_name']
                if tool not in env.alternative_tools or tool not in env._c2_path_perturbation_maps.get(tool, {}):
                    raise ValueError('Cannot guarantee fault-only call')
                for i, step in enumerate(prefix):
                    append_call(agent, step['tool_name'], step.get('arguments', {}), step.get('output', {}), i)
                output, status = env._intercept_tool_call(tool, fault.get('arguments', {}))
                if status != 'perturbed' or output != fault['output']:
                    raise ValueError('Runtime/reference first anomaly mismatch')
                append_call(agent, tool, fault.get('arguments', {}), output, len(prefix))
                row['observations'][mode] = initial(agent)
                row['outputs'][mode] = output
                row['anomaly_flags'][mode] = anomaly_flags(output)
            row['prefix_equal'] = prefix_values['P3'] == prefix_values['P4']
            row['arguments_equal'] = arg_values['P3'] == arg_values['P4']
            row['output_equal'] = row['outputs']['P3'] == row['outputs']['P4']
            row['full_observation_equal'] = row['observations']['P3'] == row['observations']['P4']
            row['equal_except_output'] = mask_last_output(row['observations']['P3']) == mask_last_output(row['observations']['P4'])
            matches = [p for p in normal['valid_paths'] if tuple(s['tool_name'] for s in p['execution_trace'][:len(key)]) == key]
            if len(matches) != 1:
                raise ValueError('No unique P0 normal prefix')
            normal_output = matches[0]['execution_trace'][len(key)-1]['output']
            row['P0_reference_output'] = normal_output
            row['P0_anomaly_flags'] = anomaly_flags(normal_output)
            row['differs_from_reference'] = {m: row['outputs'][m] != normal_output for m in maps}
            record['paths'].append(row)
        if any(digest(Path(p)) != record['hashes'][m] for m, p in files.items()) or digest(Path(template_file)) != record['template_hash']:
            raise ValueError('Input changed during audit')
    except Exception as exc:
        record['error'] = repr(exc)
    return record


def evaluate(records, tables):
    result = {'tasks': len(records), 'path_pairs': sum(len(r['paths']) for r in records), 'rules': {}}
    for kind in tables:
        counts, confusion = Counter(), Counter()
        task_correct = 0
        for record in records:
            correct_task = bool(record['paths']) and 'error' not in record
            for row in record['paths']:
                for mode, output in row['outputs'].items():
                    label = predict(output, tables)[kind]
                    counts['n'] += 1
                    counts['covered'] += label is not None
                    counts['correct'] += label == mode
                    confusion[f'{mode}->{label or "abstain"}'] += 1
                    correct_task = correct_task and label == mode
            task_correct += correct_task
        n = counts['n']; tasks = len(records); interval = wilson(task_correct, tasks)
        result['rules'][kind] = {'counts': dict(counts), 'confusion': dict(confusion),
            'accuracy_with_abstention': counts['correct']/n if n else None,
            'coverage': counts['covered']/n if n else None,
            'accuracy_when_covered': counts['correct']/counts['covered'] if counts['covered'] else None,
            'tasks_all_correct': task_correct, 'task_accuracy': task_correct/tasks if tasks else None,
            'task_wilson95': interval,
            'reliable': bool(n and tasks and task_correct/tasks >= .95 and interval[0] >= .90 and counts['covered']/n >= .95)}
    return result


def self_test():
    assert shape({'x': 1.2, 'label': 'Tokyo'}) == shape({'x': 9.1, 'label': 'Paris'})
    assert shape({'x': 1}) != shape({'x': '1'})
    assert anomaly_flags({'x': '[CORRUPTED]'}) == ['literal_anomaly_marker']
    assert anomaly_flags({'x': None}) == []
    fake = [{'paths': [{'outputs': {'P3': {'x': 1}, 'P4': {'x': 1}}}]}]
    rules = learn_rules(fake)
    assert predict({'x': 1}, rules) == {'exact': None, 'shape': None}
    assert predict({'unseen': True}, rules) == {'exact': None, 'shape': None}
    refs = extract_bindings({'a': ['{{ s4b1.currency }}', 'user_input.city', 'USD']})
    assert [r['kind'] for r in refs] == ['node_output', 'user_input', 'literal']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    self_test()
    if args.self_test:
        print('Frozen-feature, refusal, anomaly separation and binding inventory checks passed')
        return
    if args.out is None:
        parser.error('--out required')
    args.out.mkdir(parents=True, exist_ok=False)
    protected = {str(p.relative_to(ROOT)): digest(p) for folder in ('evaluation', 'toolmaze', 'tools')
                 for p in (ROOT/'benchmarks/ToolMaze'/folder).rglob('*') if p.suffix in ('.py', '.yaml')}
    dump(args.out/'config.json', {'commit': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
         'seed': 0, 'model': None, 'model_version': None, 'inference_calls': 0, 'normal_tool_calls': 0,
         'python': platform.python_version(), 'history': 'reference reconstruction', 'protected_hashes': protected})
    files = {m: {} for m in ('P0', 'P3', 'P4')}
    for mode in files:
        for p in (ROOT/'benchmarks/ToolMaze/data/perturbed_tasks').rglob(f'C2*_{mode}.json'):
            task = p.stem.rsplit('_',1)[0]
            if task in files[mode]:
                raise ValueError('Duplicate task')
            files[mode][task] = str(p)
    if any(len(f) != 100 or f.keys() != files['P0'].keys() for f in files.values()):
        raise ValueError('Expected 100 complete pairs and P0 references')
    tasks = sorted(files['P0']); dev_ids = set(tasks[:13])
    specs = [(t, {m: files[m][t] for m in files}, str(ROOT/'benchmarks/ToolMaze/data/templates/c2')) for t in tasks]
    records = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        dev = list(pool.map(audit_task, specs[:13]))
        if any('error' in r for r in dev):
            dump(args.out/'development_failure.json', dev)
            raise ValueError('Development audit failed')
        tables = learn_rules(dev)
        dump(args.out/'rules.json', tables)
        dump(args.out/'split.json', {'development': sorted(dev_ids), 'holdout': tasks[13:], 'rules_sha256': digest(args.out/'rules.json')})
        for record in dev:
            record['split'] = 'development'
            records.append(record)
        # No holdout task content is read before the frozen table is saved.
        for record in pool.map(audit_task, specs[13:]):
            record['split'] = 'holdout'; records.append(record)
            if len(records)%10 == 0:
                print(f'Completed {len(records)}/100 tasks',flush=True)
    identical, counts, issues = [], Counter(), []
    for record in records:
        for row in record['paths']:
            row['predictions'] = {m: predict(o,tables) for m,o in row['outputs'].items()}
            for key in ('prefix_equal','arguments_equal','output_equal','full_observation_equal','equal_except_output'):
                counts[key] += row[key]
            counts['P0_rule_flagged'] += bool(row['P0_anomaly_flags'])
            for mode in ('P3','P4'):
                counts[f'{mode}_rule_flagged'] += bool(row['anomaly_flags'][mode])
                counts[f'{mode}_reference_differs'] += row['differs_from_reference'][mode]
            if row['output_equal']:
                identical.append({'task': record['task'],'split':record['split'],**row})
        issues.extend({'task':record['task'],**issue} for issue in record.get('contract_inventory',{}).get('issues',[]))
        dump(args.out/f'{record["task"]}.json',record)
    template_sets = {s:{r['template_id'] for r in records if r['split']==s and 'template_id' in r} for s in ('development','holdout')}
    summary={'all':evaluate(records,tables),'holdout':evaluate([r for r in records if r['split']=='holdout'],tables),
        'development':evaluate(dev,tables),'visible_counts':dict(counts),'initial_equal_tasks':sum(r.get('initial_equal',False) for r in records),
        'identical_output_pairs':len(identical),'identical_output_tasks':sorted({r['task'] for r in identical}),
        'contract_paths':sum(len(r.get('contract_inventory',{}).get('paths',[])) for r in records),
        'contract_issues':issues,'errors':[{'task':r['task'],'error':r['error']} for r in records if 'error' in r],
        'template_overlap':sorted(template_sets['development'] & template_sets['holdout']),
        'protected_sources_unchanged':all(digest(ROOT/p)==h for p,h in protected.items())}
    dump(args.out/'identical_output_pairs.json',identical)
    dump(args.out/'evaluation.json',summary)
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    if summary['errors'] or summary['template_overlap'] or not summary['protected_sources_unchanged']:
        raise SystemExit(1)


if __name__=='__main__':
    main()
