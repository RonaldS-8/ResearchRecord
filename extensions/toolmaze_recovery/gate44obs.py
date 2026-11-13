"""Four-episode observational pilot. Real execution requires separate user approval."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from .gate44a import AdviceAgent, digest, empty_training, restored, treatment
from .gate34b import initialize, run_episode
from .gate42a import evaluate
from .run import MODEL, MODEL_REVISION, VLLMAgent

RUN_ID = '044a-obs-01'
SEED = 444001
PLAN = (('M3', 'R0'), ('M3', 'R1'), ('M4', 'R1'), ('M4', 'R0'))
MANIFEST = Path(__file__).resolve().parents[2] / 'docs/evidence/044a-0/manifest.json'


def check_frozen(mechanism, arm, agent, session):
    if (mechanism, arm) not in PLAN:
        raise ValueError('Only frozen R0/R1 observation enabled')
    frozen = json.loads(MANIFEST.read_text())
    if digest(session.public()) != frozen['checkpoints'][mechanism]['public_sha256']:
        raise ValueError('Checkpoint drift')
    initialize(agent, session)
    text = treatment(arm, session.view(), empty_training())
    messages = deepcopy(agent.messages)
    if text is not None:
        messages.append({'role': 'user', 'content': 'Recovery information:\n' + text})
    expected = frozen['files'][mechanism + '/' + arm + '-prompt.json']
    if digest({'messages': messages, 'tools': agent.tools}) != expected:
        raise ValueError('Prompt/tool drift')
    return messages


def observe(agent, mechanism, arm, output, render, *, evidence_kind, deadline=None):
    """Same entry for fake SDK tests and approved real SDK; render is offline tokenizer."""
    session = restored(mechanism)
    check_frozen(mechanism, arm, agent, session)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'config.json').write_text(json.dumps({'run_id': RUN_ID, 'model': MODEL, 'revision': MODEL_REVISION,
        'seed': SEED, 'mechanism': mechanism, 'arm': arm, 'evidence_kind': evidence_kind,
        'temperature': 0, 'max_tokens': 6144, 'request_timeout': 120, 'request_cap': 12}, indent=2))
    original = agent.client
    backend = original.with_options(max_retries=0).chat.completions.create
    calls, consecutive_errors, stopped = [], 0, False
    transitions = []
    call = session.call

    def logged_call(tool, args):
        before = deepcopy(session.view())
        try:
            return call(tool, args)
        finally:
            transitions.append({'before': before, 'tool': tool, 'arguments': deepcopy(args),
                'after': deepcopy(session.view()), 'effects': deepcopy(session.effects),
                'publications': deepcopy(session.publications)})
    session.call = logged_call

    def create(**kwargs):
        nonlocal stopped, consecutive_errors
        if stopped or len(calls) >= 12 or (deadline is not None and perf_counter() >= deadline):
            stopped = True
            raise RuntimeError('Observation request budget stopped')
        if 'tool_choice' in kwargs or kwargs.get('model') != MODEL:
            raise ValueError('Tool forcing or model drift')
        if (kwargs.get('temperature'), kwargs.get('max_tokens'), kwargs.get('timeout')) != (0, 6144, 120):
            raise ValueError('Sampling configuration drift')
        request = deepcopy(kwargs)
        request['seed'] = SEED
        text, token_count = render(request['messages'], request['tools'])
        if token_count + 6144 > 32768:
            stopped = True
            raise RuntimeError('Observation context budget stopped')
        row = {'index': len(calls) + 1, 'request': request, 'public_view': deepcopy(session.view()),
               'rendered_chat': text, 'rendered_tokens': token_count}
        calls.append(row)
        started = perf_counter()
        try:
            response = backend(**request)
            row['response'] = response.model_dump(mode='json')
            consecutive_errors = 0
            return response
        except Exception as exc:
            row['error'] = repr(exc)
            consecutive_errors += 1
            if consecutive_errors >= 3:
                stopped = True
            raise
        finally:
            row['model_seconds'] = perf_counter() - started
            with (output / 'requests.jsonl').open('a') as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
                stream.flush()
    agent.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    start = perf_counter()
    try:
        result = run_episode(AdviceAgent(agent, treatment(arm, session.view(), empty_training())), session, scorer=evaluate)
    except Exception as exc:
        result = {**evaluate(session, None), 'error': repr(exc), 'history': agent.get_conversation_history()}
    finally:
        agent.client = original
    result.update({'evidence_kind': evidence_kind, 'events': session.events, 'transitions': transitions,
                   'sdk_requests': len(calls), 'budget_stopped': stopped, 'wall_seconds': perf_counter()-start,
                   'raw_usage': [r.get('response', {}).get('usage') for r in calls],
                   'audit_status': 'pending_human_review', 'taxonomy': {k: 'unknown' for k in 'ABCDEF'}})
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    lines = ['# ' + mechanism + ' / ' + arm, '', 'Human failure attribution: pending; A–F unknown.', '']
    prefix = 3 if mechanism == 'M3' else 4
    for index, event in enumerate(session.events, 1):
        label = 'prefix' if index <= prefix else 'Agent suffix'
        if index == prefix + 1:
            label += '; first actual recovery action'
        lines += [f"## Event {index}: {label}", '', '```json', json.dumps(event, ensure_ascii=False, indent=2), '```', '']
    lines += ['Final scorer / answer: see result.json; manual avoidability and competing explanations pending.']
    (output / 'timeline.md').write_text('\n'.join(lines) + '\n')
    return result


def tokenizer_renderer(model_path):
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    def render(messages, tools):
        options = dict(tools=tools, add_generation_prompt=True)
        text = tokenizer.apply_chat_template(messages, tokenize=False, **options)
        ids = tokenizer.apply_chat_template(messages, tokenize=True, **options)
        if hasattr(ids, 'keys'):
            ids = ids['input_ids']
        if ids and isinstance(ids[0], list):
            ids = ids[0]
        return text, len(ids)
    return render


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model-path', type=Path, required=True)
    parser.add_argument('--approved-run', required=True, choices=[RUN_ID])
    args = parser.parse_args()
    # The flag records an approval already given by the user; it is not approval itself.
    import platform
    from importlib.metadata import version
    if (platform.python_version(), version('vllm'), version('openai')) != ('3.10.12','0.31.0','3.42.0'):
        raise ValueError('Runtime version drift')
    for name in ('config.json', 'tokenizer_config.json'):
        metadata = args.model_path / '.cache/huggingface/download' / (name + '.metadata')
        if metadata.read_text().splitlines()[0] != MODEL_REVISION:
            raise ValueError('Model/tokenizer revision drift')
    render = tokenizer_renderer(args.model_path)
    args.output.mkdir(parents=True, exist_ok=False)
    deadline = perf_counter() + 7200
    for mechanism, arm in PLAN:
        native = VLLMAgent(MODEL, 'http://127.0.0.1:8000/v1', temperature=0, max_tokens=6144, request_timeout=120)
        result = observe(native, mechanism, arm, args.output/(mechanism+'-'+arm), render, evidence_kind='real_Qwen', deadline=deadline)
        if result['budget_stopped'] or result.get('error'):
            break

if __name__ == '__main__':
    main()
