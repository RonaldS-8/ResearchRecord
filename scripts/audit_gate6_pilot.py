"""Gate 6 C3 structural pilot. Reference plans are audit-only."""
import argparse
from collections import Counter
import copy
import json
import platform
import subprocess

from audit_observability import ROOT, dump, engine, initial
from audit_observability_full import append_call
from audit_recovery_decisions import JudgeSystem, call, pending_steps, sha


def signature(steps):
    return json.dumps(
        [(step['tool_name'], step.get('arguments', {})) for step in steps],
        sort_keys=True,
    )


def starts(doc):
    result = {}
    for path in doc['valid_paths']:
        trace = path['execution_trace']
        fault = next(i for i, step in enumerate(trace) if step.get('is_perturbed'))
        prefix = trace[:fault + 1]
        result[signature(prefix)] = prefix
    return result


def replay(doc, prefix, target, retries, budget):
    env, agent = engine(copy.deepcopy(doc))
    events = []
    for step in prefix:
        event = call(env, step, events)
        append_call(agent, event['tool'], event['arguments'], event['output'], len(events))
    observation = initial(agent)
    legal_start = (
        all(e['success'] and e['perturbation_status'] == 'clean' for e in events[:-1])
        and not events[-1]['success']
        and events[-1]['perturbation_status'] == 'perturbed'
    )
    if legal_start:
        for _ in range(retries):
            if call(env, prefix[-1], events)['success']:
                break
        if target:
            successful = [e['tool'] for e in events if e['success']]
            for step in pending_steps(target['execution_trace'], successful):
                if len(events) - len(prefix) == budget:
                    break
                if not call(env, step, events)['success']:
                    break
    trace = env.logger.to_dict()
    judge = JudgeSystem()
    score = judge.judge(env.task_json, copy.deepcopy(trace))
    recovery = events[len(prefix):]
    return {
        'legal_start': legal_start,
        'observation': observation,
        'target': target['path_id'] if target else None,
        'retry_limit': retries,
        'reference_only': target is not None,
        'events': events,
        'trace': trace,
        'score': score,
        'score_consistent': score == judge.judge(env.task_json, json.loads(json.dumps(trace))),
        'recovery_calls': len(recovery),
        'calls_by_tool': Counter(e['tool'] for e in recovery),
        'failed_calls_by_tool': Counter(e['tool'] for e in recovery if not e['success']),
    }


def audit_pair(files):
    docs = {mode: json.loads(path.read_text()) for mode, path in files.items()}
    prefixes = {mode: starts(doc) for mode, doc in docs.items()}
    budget = max(len(path['execution_trace']) for doc in docs.values()
                 for path in doc['valid_paths']) + 2
    rows = []
    for key in sorted(prefixes['P1'].keys() | prefixes['P2'].keys()):
        row = {'prefix': json.loads(key), 'runs': {}}
        rows.append(row)
        for mode, doc in docs.items():
            if key not in prefixes[mode]:
                continue
            prefix = prefixes[mode][key]
            runs = [replay(doc, prefix, None, 0, budget)]
            if runs[0]['legal_start']:
                for target in doc['valid_paths']:
                    for retries in (0, 1, 2):
                        runs.append(replay(doc, prefix, target, retries, budget))
            row['runs'][mode] = runs
        paired = len(row['runs']) == 2 and all(r[0]['legal_start'] for r in row['runs'].values())
        row['paired_legal'] = paired
        row['observation_equal'] = (
            row['runs']['P1'][0]['observation'] == row['runs']['P2'][0]['observation']
            if paired else None
        )
    return {'hashes': {mode: sha(path) for mode, path in files.items()}, 'budget': budget, 'rows': rows}


def main():
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    out = parser.parse_args().out
    out.mkdir(parents=True, exist_ok=False)
    inputs = ROOT / 'benchmarks/ToolMaze/data/perturbed_tasks'
    paths = {}
    for path in sorted(inputs.rglob('C3*.json')):
        task, mode = path.stem.rsplit('_', 1)
        if mode in ('P1', 'P2'):
            files = paths.setdefault(task, {})
            if mode in files:
                raise ValueError(f'Duplicate input: {path}')
            files[mode] = path
    tasks = sorted(task for task, files in paths.items() if len(files) == 2)[:3]
    dump(out / 'config.json', {
        'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'python': platform.python_version(), 'tasks': tasks, 'seed': None, 'inference_calls': 0,
        'cost_proxy': 'tool calls only',
    })
    if len(tasks) != 3:
        raise ValueError('Expected three paired C3 inputs')
    summary = {}
    for task in tasks:
        result = audit_pair(paths[task])
        dump(out / f'{task}.json', result)
        rows = result['rows']
        runs = [run for row in rows for group in row['runs'].values() for run in group]
        summary[task] = {
            'starts': len(rows), 'paired_legal': sum(row['paired_legal'] for row in rows),
            'equal_observations': sum(row['observation_equal'] is True for row in rows),
            'runs': len(runs), 'passes': sum(bool(run['score']['pass']) for run in runs),
            'score_mismatches': sum(not run['score_consistent'] for run in runs),
        }
    dump(out / 'evaluation.json', summary)
    print(json.dumps(summary))
    if any(row['score_mismatches'] for row in summary.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
