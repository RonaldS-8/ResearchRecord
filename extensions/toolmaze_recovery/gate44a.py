"""Gate44A-0 CPU preparation. No real-model entry point; training cohort not approved."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

from .gate42a import checkpoint, evaluate
from .gate34b import initialize, run_episode
from extensions.action_conditioned_recovery.gate18 import BTM_GUIDANCE, BTM_RETRY, BTM_CONSTRAINTS

ARMS = ('R0', 'R1', 'R2', 'R3')
RULE = ('Continue the remaining obligations using the task, actual receipts and remaining call budget. '
        'Prefer an untried legal tool with a possible completion within the remaining budget over stopping. '
        'Use actual feedback to exclude infeasible calls; do not repeat failures without meaningful new evidence or progress. '
        'Do not skip required field and authority validation, confirmation, submission or readback. '
        'Preparation is not publication. Ground all arguments in the task and actual receipts; never guess references. '
        'Stop only when all publicly viable routes are exhausted or cannot fit the remaining budget.')
BTM = '\n'.join((BTM_GUIDANCE, BTM_RETRY, BTM_CONSTRAINTS,
                 'Never retry a tool explicitly reported unavailable for this session.'))


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def digest(value):
    return sha256(encoded(value).encode()).hexdigest()


def restored(mechanism):
    if mechanism not in ('M3', 'M4'):
        raise ValueError('Unregistered checkpoint')
    return checkpoint(mechanism, _namespace='gate44a-0-' + mechanism)


def empty_training():
    # This is a missing-data artifact, never a fitted BTM or synthetic Agent history.
    return {'status': 'blocked_missing_approved_real_history', 'sources': [],
            'frequencies': {}, 'btm': None, 'support': 0}


def treatment(arm, view, training):
    if arm not in ARMS:
        raise ValueError('Unregistered arm')
    if arm == 'R0':
        return None
    if arm == 'R1':
        return RULE
    errors = [{'tool': e['tool'], 'result': e['result']} for e in view['history'] if 'error' in e['result']]
    if arm == 'R2':
        return 'Frozen per-tool call success frequencies:\n' + encoded(training['frequencies']) + '\nActual error receipts:\n' + encoded(errors)
    return BTM + '\nFrozen Bayesian Tool Memory:\n' + encoded(training['btm'])


class AdviceAgent:
    """Adds one checkpoint treatment; delegates native parsing and all actual arguments."""
    def __init__(self, native, text):
        self.native, self.text, self.inserted = native, text, False

    def __getattr__(self, name):
        return getattr(self.native, name)

    def initialize(self, task, definitions):
        self.native.perturbation_mode = None
        self.native.initialize(task, definitions)

    def step(self):
        if not self.inserted:
            if self.text is not None:
                self.native.messages.append({'role': 'user', 'content': 'Recovery information:\n' + self.text})
            self.inserted = True
        return self.native.step()


def run_protocol(native, mechanism, arm, output, *, seed=440001):
    """Injected SDK only. Explicitly records CPU protocol evidence, not Agent performance."""
    if seed not in range(440001, 440006):
        raise ValueError('Outside smoke seed schedule')
    session = restored(mechanism)
    training = empty_training()
    wrapped = AdviceAgent(native, treatment(arm, session.view(), training))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    prefix, start = len(session.events), perf_counter()
    original_client = native.client
    backend = original_client.chat.completions.create
    records, denied = [], []

    def create(**kwargs):
        if len(records) >= 12:
            denied.append('request_cap')
            raise RuntimeError('Registered SDK cap reached')
        if 'tool_choice' in kwargs:
            raise ValueError('Forced tool choice forbidden')
        request = deepcopy(kwargs)
        request['seed'] = seed
        entry = {'request': request, 'index': len(records) + 1}
        records.append(entry)
        started = perf_counter()
        try:
            response = backend(**request)
            entry['response'] = response.model_dump(mode='json')
            return response
        except Exception as exc:
            entry['error'] = repr(exc)
            raise
        finally:
            entry['seconds'] = perf_counter() - started
            with (output / 'requests.jsonl').open('a') as stream:
                stream.write(json.dumps(entry, ensure_ascii=False) + '\n')

    native.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    try:
        result = run_episode(wrapped, session, scorer=evaluate)
    except Exception as exc:
        result = {**evaluate(session, None), 'error': repr(exc)}
    finally:
        native.client = original_client
    result.update({'evidence_kind': 'CPU_fake_SDK_only', 'arm': arm, 'checkpoint': mechanism,
                   'sdk_requests': len(records), 'cap_rejections': len(denied),
                   'raw_usage': [r.get('response', {}).get('usage') for r in records],
                   'wall_seconds': perf_counter() - start, 'events': deepcopy(session.events),
                   'prefix_calls': prefix, 'training_sha256': digest(training),
                   'checkpoint_sha256': digest(restored(mechanism).public())})
    (output / 'result.json').write_text(json.dumps(result, indent=2))
    return result


def prepare(output, native_factory):
    """Freeze CPU checkpoint artifacts and actual native initialization/prompt bytes."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {'status': 'Not Ready', 'blockers': ['No approved same-source real Agent training cohort or fitted R2/R3 artifacts'],
                'model': 'Qwen3-4B-Thinking-2507', 'revision': '768f209d9ea81521153ed38c47d515654e938aea',
                'smoke_episodes': 40, 'sdk_cap': 480, 'output_token_cap': 2949120,
                'tool_fee_upper_bound': 420, 'model_calls': 0, 'checkpoints': {}, 'files': {}}
    training = empty_training()
    (output / 'training.json').write_text(encoded(training))
    for mechanism in ('M3', 'M4'):
        session = restored(mechanism)
        folder = output / mechanism
        folder.mkdir()
        public = session.public()
        private = {'mechanism': mechanism, 'state': session._state,
                   'namespace': 'gate44a-0-' + mechanism, 'context': public['context'],
                   'events': session.events, 'constructor': 'gate42a.checkpoint'}
        (folder / 'public.json').write_text(encoded(public))
        (folder / 'private-construction.json').write_text(encoded(private))
        (folder / 'reference-stream.json').write_text(encoded(session.events))
        native = native_factory()
        initialize(native, session)
        common = deepcopy(native.messages)
        for arm in ARMS:
            text = treatment(arm, session.view(), training)
            messages = common + ([{'role': 'user', 'content': 'Recovery information:\n' + text}] if text else [])
            (folder / (arm + '-prompt.json')).write_text(encoded({'messages': messages, 'tools': native.tools}))
        manifest['checkpoints'][mechanism] = {'public_sha256': digest(public), 'prefix_calls': len(session.events),
                                              'remaining_calls': session.view()['remaining_calls']}
    for file in sorted(output.rglob('*.json')):
        manifest['files'][str(file.relative_to(output))] = sha256(file.read_bytes()).hexdigest()
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    return manifest
