"""Gate47 bounded native Agent observations; no repair, advice or automatic continuation."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
from time import perf_counter
from types import SimpleNamespace

from .gate34b import initialize, run_episode
from .gate44a import digest, restored
from .gate44obs import check_frozen, tokenizer_renderer
from .gate42a import evaluate
from .gate46 import VariantSession, conditions, manifest, schedule, score
from .run import MODEL, MODEL_REVISION, VLLMAgent


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))


def now():
    return datetime.now(timezone.utc).isoformat()


def api_config():
    required = ('API_KEY', 'BASE_URL', 'MODEL', 'MAX_COST', 'CURRENCY',
                'INPUT_PER_MILLION', 'OUTPUT_PER_MILLION', 'CACHED_INPUT_PER_MILLION')
    c = {k: os.environ.get('GATE47_' + k, '') for k in required}
    if any(not x for x in c.values()):
        raise ValueError('Missing Gate47 environment fields (values redacted)')
    expected = {'BASE_URL': 'https://cn-beijing.maas.qianwenaiapi.com/compatible-mode/v1',
                'MODEL': 'qwen3.7-flash-2026-07-15', 'CURRENCY': 'CNY',
                'INPUT_PER_MILLION': '0.2', 'OUTPUT_PER_MILLION': '0.8',
                'CACHED_INPUT_PER_MILLION': '0.04'}
    if any(c[k] != v for k, v in expected.items()) or not 0 < Decimal(c['MAX_COST']) <= 15:
        raise ValueError('Unregistered API model, endpoint, price or budget')
    return c


class Budget:
    """Serial, persistent reservations: ambiguous requests retain worst-case liability."""
    reserve = (Decimal(991808) * Decimal('1.2') + Decimal(12288) * Decimal('4.8')) / 1000000

    def __init__(self, path, limit):
        self.path, self.limit, self.spent = path, Decimal(limit), Decimal(0)
        write(path, {'limit_cny': str(self.limit), 'reserved_or_settled_cny': '0'})

    def save(self):
        write(self.path, {'limit_cny': str(self.limit), 'reserved_or_settled_cny': str(self.spent),
                         'per_request_reserve_cny': str(self.reserve)})

    def begin(self):
        if self.spent + self.reserve > self.limit:
            raise RuntimeError('API monetary budget reached before dispatch')
        self.spent += self.reserve
        self.save()

    def settle(self, usage):
        p, o = usage['prompt_tokens'], usage['completion_tokens']
        cached = (usage.get('prompt_tokens_details') or {}).get('cached_tokens', 0) or 0
        if not (isinstance(p, int) and isinstance(o, int) and 0 <= cached <= p <= 991808 and 0 <= o <= 12288):
            raise ValueError('Usage outside reserved model limits; stop and audit')
        factor = Decimal(1 if p <= 32768 else 3 if p <= 262144 else 6)
        cost = ((p-cached)*Decimal('0.2') + cached*Decimal('0.04') + o*Decimal('0.8')) * factor / 1000000
        self.spent += cost - self.reserve
        self.save()
        return str(cost)


def trajectory(result, prefix):
    """Actual actions/arguments/legality; receipts use the frozen deterministic reference stream."""
    return digest([{'tool': e['tool'], 'arguments': e['arguments'], 'illegal': e['illegal']}
                   for e in result['events'][prefix:]] + ['FINAL' if result.get('answer') is not None else 'NO_FINAL'])


def observe(agent, factory, scorer, output, *, seed, api=False, budget=None, render=None):
    output.mkdir(parents=True, exist_ok=False)
    session = factory()
    initialize(agent, session)
    initial = {'messages': deepcopy(agent.messages), 'tools': deepcopy(agent.tools)}
    write(output/'initial-prompt.json', initial)
    prefix = len(session.events)
    backend = agent.client.with_options(max_retries=0).chat.completions.create
    calls, transitions, errors = [], [], []
    halted = False
    original_call = session.call

    def call(tool, arguments):
        before = deepcopy(session.view())
        try:
            return original_call(tool, arguments)
        finally:
            transitions.append({'before': before, 'tool': tool, 'arguments': deepcopy(arguments),
                                'after': deepcopy(session.view())})
    session.call = call

    def create(**kwargs):
        nonlocal halted
        if halted or len(calls) >= 12:
            raise RuntimeError('Gate47 request guard stopped; no replacement request')
        if 'tool_choice' in kwargs or kwargs.get('parallel_tool_calls') is not False:
            raise ValueError('Native tool contract drift')
        if (kwargs['temperature'], kwargs['max_tokens'], kwargs['timeout']) != (0, 6144, 120):
            raise ValueError('Sampling drift')
        request = deepcopy(kwargs)
        request['seed'] = seed
        if api:
            request.update(top_p=1, stream=False, extra_body={'enable_thinking': True, 'thinking_budget': 6144})
        row = {'index': len(calls)+1, 'started_utc': now(), 'request': request,
               'public_view': deepcopy(session.view())}
        if render:
            row['rendered_chat'], row['rendered_tokens'] = render(request['messages'], request['tools'])
            if row['rendered_tokens'] + 6144 > 32768:
                halted = True
                raise RuntimeError('Local context limit before dispatch')
        calls.append(row)
        start = perf_counter()
        try:
            if budget:
                budget.begin()
                row['reservation_cny'] = str(budget.reserve)
            # Save dispatch intent before network I/O, including liability after process failure.
            write(output/'dispatch-intent.json', row)
            response = backend(**request)
            raw = response.model_dump(mode='json')
            row['response'] = raw
            if budget:
                row['usage_cost_cny'] = budget.settle(raw['usage'])
                if raw.get('model') != request['model']:
                    raise ValueError('API response model version differs from fixed snapshot')
            choices = raw.get('choices') or []
            if len(choices) != 1 or choices[0].get('finish_reason') not in ('stop', 'tool_calls'):
                raise ValueError('Unexpected choices or truncation')
            if len((choices[0].get('message') or {}).get('tool_calls') or []) > 1:
                raise ValueError('Parallel tool response incompatible with serial contract')
            return response
        except Exception as exc:
            # No backend retry or contract fallback; the native loop may return an Error final.
            halted = True
            errors.append(type(exc).__name__)
            row['error'] = type(exc).__name__ + ': ' + str(exc).replace(os.environ.get('GATE47_API_KEY') or '\0', '[REDACTED]')
            raise RuntimeError('Gate47 protocol/infrastructure stopped') from None
        finally:
            row['seconds'], row['finished_utc'] = perf_counter()-start, now()
            with (output/'requests.jsonl').open('a') as stream:
                stream.write(json.dumps(row, ensure_ascii=False)+'\n')
                stream.flush()

    original_client = agent.client
    agent.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    start = perf_counter()
    try:
        result = run_episode(agent, session, request_limit=12, scorer=scorer)
    finally:
        agent.client = original_client
    # Replay only actual raw arguments; never repair them or supply missing continuation.
    replay = factory()
    for event in session.events[prefix:]:
        replay.call(event['tool'], event['arguments'])
    expected = scorer(replay, result['answer'])
    for k, v in expected.items():
        if result[k] != v:
            raise ValueError('Independent actual-argument replay mismatch: ' + k)
    result.update(events=deepcopy(session.events), transitions=transitions, prefix_calls=prefix,
                  sdk_requests=len(calls), errors=errors, protocol='pass' if not errors else 'blocked',
                  wall_seconds=perf_counter()-start, initial_prompt_sha256=digest(initial),
                  raw_usage=[r.get('response', {}).get('usage') for r in calls])
    result['action_trajectory_sha256'] = trajectory(result, prefix)
    write(output/'result.json', result)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=('api', 'gate46-freeze', 'gate46'))
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--model-path', type=Path)
    p.add_argument('--freeze', type=Path)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    if a.mode.startswith('gate46'):
        from importlib.metadata import version
        import platform
        if (platform.python_version(), version('vllm'), version('openai')) != ('3.10.12', '0.31.0', '3.42.0'):
            raise ValueError('Frozen runtime drift')
        for name in ('config.json', 'tokenizer_config.json'):
            if (a.model_path/'.cache/huggingface/download'/(name+'.metadata')).read_text().splitlines()[0] != MODEL_REVISION:
                raise ValueError('Frozen model revision drift')
        render = tokenizer_renderer(a.model_path)
        factory = lambda: VLLMAgent(MODEL, 'http://127.0.0.1:8000/v1', temperature=0, max_tokens=6144, request_timeout=120)
        frozen = {'source_commit': commit, 'model': MODEL, 'revision': MODEL_REVISION,
                  'conditions': manifest(factory, render), 'schedule': schedule()}
        payloads = {}
        for v, c in conditions():
            s, agent = VariantSession(v, c), factory()
            initialize(agent, s)
            payloads[v+'-'+c] = {'messages': agent.messages, 'tools': agent.tools}
            if frozen['conditions'][v+'-'+c]['rendered_tokens'] + 6144 > 32768:
                raise ValueError('Gate46 initial context overflow')
        check_frozen('M4', 'R0', factory(), restored('M4'))
        write(a.output/'freeze.json', frozen)
        write(a.output/'payloads.json', payloads)
        if a.mode == 'gate46-freeze':
            return
        expected = json.loads(a.freeze.read_text())
        if frozen != expected:
            raise ValueError('Gate46 freeze drift')
        progress = []
        for row in schedule():
            r = observe(factory(), lambda row=row: VariantSession(row['variant'], row['contract']), score,
                        a.output/row['id'], seed=460001, render=render)
            progress.append({**row, 'strict_success': r['strict_success'], 'protocol': r['protocol']})
            write(a.output/'progress.json', progress)
            if r['protocol'] != 'pass':
                raise RuntimeError('Gate46 protocol blocked; no replacement')
    else:
        c = api_config()
        write(a.output/'config.json', {k: v for k, v in c.items() if k != 'API_KEY'} | {'source_commit': commit,
              'sampling': {'temperature': 0, 'top_p': 1, 'seed': 470001, 'max_tokens': 6144,
                           'thinking_budget': 6144, 'enable_thinking': True, 'stream': False}})
        budget = Budget(a.output/'budget.json', c['MAX_COST'])
        progress, hashes, active = [], {'M3': set(), 'M4': set()}, {'M3', 'M4'}
        for repeat in range(1, 11):
            for mechanism in ('M3', 'M4'):
                if mechanism not in active:
                    continue
                agent = VLLMAgent(c['MODEL'], c['BASE_URL'], api_key=c['API_KEY'], temperature=0,
                                  max_tokens=6144, request_timeout=120)
                check_frozen(mechanism, 'R0', agent, restored(mechanism))
                r = observe(agent, lambda: restored(mechanism), evaluate,
                            a.output/f'{repeat:02d}-{mechanism}', seed=470001, api=True, budget=budget)
                hashes[mechanism].add(r['action_trajectory_sha256'])
                progress.append({'repeat': repeat, 'checkpoint': mechanism, 'strict_success': r['strict_success'],
                                 'protocol': r['protocol'], 'action_trajectory_sha256': r['action_trajectory_sha256']})
                write(a.output/'progress.json', progress)
                if r['protocol'] != 'pass':
                    raise RuntimeError('API protocol blocked; no replacement')
                if repeat == 3 and len(hashes[mechanism]) == 1:
                    active.remove(mechanism)
            if repeat == 1:
                write(a.output/'pilot-pass.json', {'episodes': 2, 'selection_by_performance': False})
            if not active:
                break
        write(a.output/'diversity-stop.json', {'counts': {k: len(v) for k, v in hashes.items()},
                                              'rule': 'single action trajectory at first 3 per cell stops cell'})
    write(a.output/'completed.json', {'status': 'raw_results_ready_for_attribution', 'episodes': len(progress)})


if __name__ == '__main__':
    main()
