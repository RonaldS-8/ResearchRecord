"""Cloud-only deterministic audit; no inference and no clean tool execution."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'benchmarks/ToolMaze'))
from evaluation.agents.vllm_agent import VLLMAgent
from evaluation.core.sandbox import ExecutionEngine


def dump(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def engine(doc):
    agent = VLLMAgent(model='audit-no-inference', base_url='http://127.0.0.1:1/v1')
    env = ExecutionEngine(doc, agent)
    agent.perturbation_mode = env.mode
    agent.initialize(env.task_description, env.tool_definitions)
    agent.messages.append({'role': 'user', 'content': env.task_description})
    return env, agent


def initial(agent):
    return copy.deepcopy({'messages': agent.messages, 'tools': agent.tools})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    dump(args.out / 'config.json', {
        'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'seed': 0, 'model': None, 'model_version': None, 'inference_calls': 0,
        'python': platform.python_version(),
        'packages': {p: importlib.metadata.version(p) for p in ('openai', 'pydantic')},
        'scope': 'C2 P1/P2 initial inputs and isolated first fault; no reference history replay',
    })
    files = {}
    for mode in ('P1', 'P2'):
        files[mode] = {p.stem.rsplit('_', 1)[0]: p for p in
                       (ROOT / 'benchmarks/ToolMaze/data/perturbed_tasks').rglob(f'C2*_{mode}.json')}
    summary = {'pairs': 0, 'missing_pairs': sorted(set(files['P1']) ^ set(files['P2'])),
               'initial_different': 0, 'fault_checks': 0, 'fault_response_different': 0,
               'errors': [], 'limitations': ['Script-selected calls, not model trajectories.',
                'No valid preceding tool history replay; full-history audit remains pending.',
                'No diagnostic interface or test_no_leakage validation; no strategy evaluation.']}
    for task in sorted(set(files['P1']) & set(files['P2'])):
        record = {'task': task, 'data_sha256': {}, 'initial': {}, 'faults': []}
        try:
            docs = {}
            for mode in files:
                raw = files[mode][task].read_bytes()
                record['data_sha256'][mode] = hashlib.sha256(raw).hexdigest()
                docs[mode] = json.loads(raw)
                _, agent = engine(docs[mode])
                record['initial'][mode] = initial(agent)
            summary['pairs'] += 1
            record['initial_equal'] = record['initial']['P1'] == record['initial']['P2']
            summary['initial_different'] += not record['initial_equal']
            environments = {m: engine(d)[0] for m, d in docs.items()}
            entrances = {m: set(e._c2_path_perturbation_maps) for m, e in environments.items()}
            record['unpaired_entrances'] = sorted(entrances['P1'] ^ entrances['P2'])
            for tool in sorted(entrances['P1'] & entrances['P2']):
                step = next(s for v in docs['P1']['valid_paths'] for s in v['execution_trace']
                            if s['tool_name'] == tool and s.get('is_perturbed'))
                arguments = step.get('arguments', {})
                fault = {'tool': tool, 'arguments_source': 'P1 reference; identical in both calls',
                         'arguments': arguments, 'observations': {}}
                for mode in docs:
                    env, agent = engine(docs[mode])
                    # Guard before interception: this exact call must return a fault,
                    # never fall through to a normal plugin execution.
                    assert tool in env.alternative_tools
                    assert tool in env._c2_path_perturbation_maps[tool]
                    result, status = env._intercept_tool_call(tool, arguments)
                    assert status == 'perturbed'
                    agent.messages.append({'role': 'assistant', 'content': None, 'tool_calls': [
                        {'id': 'audit_call', 'type': 'function', 'function':
                         {'name': tool, 'arguments': json.dumps(arguments, ensure_ascii=False)}}]})
                    agent.receive_tool_result(tool, result)
                    fault['observations'][mode] = initial(agent)
                fault['equal'] = fault['observations']['P1'] == fault['observations']['P2']
                fault['response_equal'] = (fault['observations']['P1']['messages'][-1] ==
                                           fault['observations']['P2']['messages'][-1])
                summary['fault_checks'] += 1
                summary['fault_response_different'] += not fault['response_equal']
                record['faults'].append(fault)
        except Exception as exc:
            record['error'] = repr(exc)
            summary['errors'].append({'task': task, 'error': repr(exc)})
        dump(args.out / f'{task}.json', record)
    dump(args.out / 'evaluation.json', summary)
    print(json.dumps(summary, ensure_ascii=False))
    if not summary['pairs'] or summary['errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
