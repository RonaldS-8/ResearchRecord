"""Private original-engine backend with a JSON-only recovery decision view."""
from __future__ import annotations

import copy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'benchmarks/ToolMaze'))
from evaluation.core.sandbox import ExecutionEngine, InferenceContext

CONFIG = json.loads((Path(__file__).with_name('config.json')).read_text())


def json_copy(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def field(value, path):
    for key in path.split('.') if path else []:
        value = value[int(key)] if isinstance(value, list) else value[key]
    return copy.deepcopy(value)


def resolve(value, user, outputs):
    if isinstance(value, dict):
        return {k: resolve(v, user, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, user, outputs) for v in value]
    if isinstance(value, str):
        if value.startswith('user_input.'):
            return field(user, value[len('user_input.'):])
        match = re.fullmatch(r'\{\{\s*(s\w+)(?:\.(\w+(?:\.\w+)*))?\s*\}\}', value)
        if match:
            return field(outputs[match[1]], match[2] or '')
        if '{{' in value:
            raise ValueError('Unregistered binding expression')
    return copy.deepcopy(value)


def fresh_engine(base):
    env = copy.copy(base)
    env.context = InferenceContext()
    env.perturbation_map = {}
    env._c2_activated = False
    env._c2_activated_tool = None
    return env


def load_json(path):
    return json.loads(path.read_text())


@lru_cache(maxsize=20)
def load_case(task, mode):
    if task not in CONFIG['tasks'] or mode not in ('P1', 'P2'):
        raise ValueError('Outside registered cohort')
    data = ROOT / 'benchmarks/ToolMaze/data/perturbed_tasks'
    files = {}
    docs = {}
    for m in ('P0', mode):
        matches = list(data.rglob(f'C2_task_{task}_{m}.json'))
        if len(matches) != 1:
            raise ValueError('Task file not unique')
        files[m] = matches[0]
        docs[m] = load_json(matches[0])
    tpl = ROOT / 'benchmarks/ToolMaze/data/templates/c2' / (docs['P0']['template_id']+'.json')
    template = load_json(tpl)
    files['template'] = tpl
    base = ExecutionEngine(docs[mode], None)
    paths = docs['P0']['valid_paths']
    source = next(p for p in paths if p['path_id'] == CONFIG['source_path'])
    fault_trace = next(p for p in docs[mode]['valid_paths'] if p['path_id'] == source['path_id'])['execution_trace']
    position = next(i for i, s in enumerate(fault_trace) if s.get('is_perturbed'))
    if source['tools'][position] != fault_trace[position]['tool_name']:
        raise ValueError('Fault/source mismatch')
    target = min((p for p in paths if source['tools'][position] not in p['tools']), key=lambda p:len(p['tools']))
    return {'base': base, 'template': template, 'docs': docs, 'source': source, 'target': target,
            'position': position, 'files': files, 'hashes': {m: hashlib.sha256(p.read_bytes()).hexdigest() for m,p in files.items()}}


class RecoverySession:
    """Never pass this object to a strategy; pass view() and an action string."""

    def __init__(self, task, mode, price='low', controlled=True):
        self._case = load_case(task, mode)
        self._engine = fresh_engine(self._case['base'])
        self._task, self._mode = task, mode
        self._price = CONFIG['diagnostic_costs'][price]
        self._controlled = controlled
        self._outputs = {}
        self._events = []
        self._decisions = []
        self._done = False
        self._nodes = {n['id']: n['tool_name'] for n in self._case['template']['dag']['nodes']}
        source = self._case['source']['node_sequence']
        for node in source[:self._case['position']]:
            if not self._call(node):
                raise ValueError('Registered clean prefix failed')
        self._victim_node = source[self._case['position']]
        if self._call(self._victim_node):
            raise ValueError('Expected first failure did not occur')
        self._sunk_calls = len(self._events)

    def _arguments(self, node):
        bindings = self._case['template']['parameter_bindings'][self._nodes[node]]
        return resolve(bindings, self._case['docs']['P0']['user_input'], self._outputs)

    def _call(self, node):
        if len(self._events) >= CONFIG['max_tool_calls']:
            raise ValueError('Tool budget exhausted')
        tool = self._nodes[node]
        arguments = self._arguments(node)
        raw, status = self._engine._intercept_tool_call(tool, copy.deepcopy(arguments))
        returned = CONFIG['error'] if self._controlled and status == 'perturbed' else raw
        event = {'call_id':f'call_{len(self._events)}','node':node,'tool':tool,'arguments':arguments,
                 'raw_output':copy.deepcopy(raw),'output':copy.deepcopy(returned),'perturbation_status':status,
                 'charge':CONFIG['tool_attempt_cost']}
        self._events.append(event)
        successful = 'error' not in returned
        if successful:
            self._outputs[node] = copy.deepcopy(returned)
        return successful

    def _finish(self, path):
        for node in path['node_sequence']:
            if node not in self._outputs and not self._call(node):
                return False
        self._done = True
        return True

    def view(self):
        R, S = CONFIG['tasks'][self._task]
        specs = [d['paradigms']['function_call']['spec'] for d in self._case['base'].tool_definitions]
        view = json_copy({'task':self._case['base'].task_description,
             'tools':sorted(specs,key=lambda d:d['name']),
             'actions':{'retry':'Retry the failed operation once; finish original workflow if it succeeds.',
                        'switch':'Complete an alternative workflow.',
                        'diagnose':'Accurately report whether the next valid retry can recover; each call is charged.',
                        'stop':'End without further recovery.'},
             'costs':{'retry_if_recovers':R,'switch':S,'failed_retry':1,'diagnosis':self._price},
             'prior_transient':CONFIG['prior_transient'],
             'history':[{'call_id':e['call_id'],'tool':e['tool'],'arguments':e['arguments'],'output':e['output']} for e in self._events],
             'decisions':self._decisions,'done':self._done})
        if not self._controlled:
            del view['actions']['diagnose']
            del view['costs']['diagnosis']
        return view

    def act(self, action):
        if self._done or len(self._decisions) >= CONFIG['max_decisions']:
            raise ValueError('Decision budget exhausted or session finished')
        if action not in ('retry','switch','diagnose','stop'):
            raise ValueError('Unknown action')
        charge = 0
        if action == 'diagnose':
            if not self._controlled:
                raise ValueError('Original-error controls have no diagnostic tool')
            result = {'retry_will_recover':self._mode == 'P1'}
            charge = self._price
        elif action == 'retry':
            recovered = self._call(self._victim_node)
            result = {'recovered':recovered}
            if recovered:
                result['workflow_completed'] = self._finish(self._case['source'])
        elif action == 'switch':
            result = {'workflow_completed':self._finish(self._case['target'])}
        else:
            self._done = True
            result = {'stopped':True}
        self._decisions.append({'action':action,'result':result,'diagnostic_charge':charge})
        return self.view()

    def audit(self):
        tool_cost = len(self._events)*CONFIG['tool_attempt_cost']
        diagnosis = sum(d['diagnostic_charge'] for d in self._decisions)
        return json_copy({'task':self._task,'mode':self._mode,'controlled':self._controlled,
             'events':self._events,'decisions':self._decisions,'sunk_calls':self._sunk_calls,
             'total_tool_calls':len(self._events),'recovery_tool_calls':len(self._events)-self._sunk_calls,
             'diagnostic_cost':diagnosis,'total_cost':tool_cost+diagnosis,
             'recovery_cost':(len(self._events)-self._sunk_calls)+diagnosis,'input_hashes':self._case['hashes']})
