"""Frozen Gate45 Ready arms only; no estimator, tool forcing or argument repair."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import platform
import subprocess
from time import perf_counter
from importlib.metadata import version
from .gate44obs import observe, check_frozen, tokenizer_renderer
from .gate44a import restored, digest, RULE, BTM, empty_training
from .gate42a import evaluate
from .run import MODEL, MODEL_REVISION, VLLMAgent

RUN_ID = '045-real-agent-01'


def plan():
    return [(450001+i, mech, arm) for i in range(5)
            for mech in (('M3', 'M4') if i % 2 == 0 else ('M4', 'M3'))
            for arm in (('R0', 'R1') if i % 2 == 0 else ('R1', 'R0'))]


def protocol_check(result, folder, mechanism):
    """Replay actual arguments independently; never invent a successful continuation."""
    s = restored(mechanism)
    prefix = len(s.events)
    for t in result['transitions']:
        s.call(t['tool'], t['arguments'])
    expected = evaluate(s, result.get('answer'))
    # Compare the scorer fields using the exact final-answer key from native loop.
    for key, value in expected.items():
        if result.get(key) != value:
            raise ValueError('Independent scorer mismatch: ' + key)
    if s.events != result['events'] or len(s.events)-prefix > (6 if mechanism == 'M3' else 3):
        raise ValueError('Event replay or call budget mismatch')
    rows = [json.loads(line) for line in (folder/'requests.jsonl').read_text().splitlines()]
    if not rows or len(rows) != result['sdk_requests'] or any('error' in r for r in rows):
        raise ValueError('SDK protocol error; preserve and stop batch')
    return digest({'transitions': result['transitions'], 'answer': result.get('answer')})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model-path', type=Path, required=True)
    args = parser.parse_args()
    runtime = {k: version(k) for k in ('vllm', 'openai', 'transformers')}
    if (platform.python_version(),runtime['vllm'],runtime['openai']) != ('3.10.12','0.31.0','3.42.0'):
        raise ValueError('Runtime drift')
    for name in ('config.json','tokenizer_config.json'):
        if (args.model_path/'.cache/huggingface/download'/(name+'.metadata')).read_text().splitlines()[0] != MODEL_REVISION:
            raise ValueError('Model revision drift')
    render = tokenizer_renderer(args.model_path)
    args.output.mkdir(parents=True, exist_ok=False)
    freeze = {'run': RUN_ID, 'commit': subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
              'runtime': runtime, 'model': MODEL, 'revision': MODEL_REVISION, 'plan': plan(),
              'training': empty_training(), 'training_sha256': digest(empty_training()),
              'rule_sha256': digest(RULE), 'original_btm_guidance_sha256': digest(BTM), 'prompts': {}}
    for mechanism in ('M3','M4'):
        for arm in ('R0','R1'):
            a = VLLMAgent(MODEL,'http://127.0.0.1:8000/v1',temperature=0,max_tokens=6144,request_timeout=120)
            s = restored(mechanism)
            messages = check_frozen(mechanism,arm,a,s)
            text,n = render(messages,a.tools)
            if n+6144 > 32768:
                raise ValueError('Initial context overflow')
            freeze['prompts'][mechanism+arm] = {'messages': messages,'tools': deepcopy(a.tools),
                'sha256':digest({'messages':messages,'tools':a.tools}),'rendered_tokens':n,
                'rendered_sha256':digest(text),'checkpoint_sha256':digest(s.public())}
    (args.output/'freeze.json').write_text(json.dumps(freeze,ensure_ascii=False,indent=2))
    deadline = perf_counter()+7*3600
    summary = []
    try:
        for index,(seed,mechanism,arm) in enumerate(plan()):
            folder = args.output/(str(seed)+'-'+mechanism+'-'+arm)
            a=VLLMAgent(MODEL,'http://127.0.0.1:8000/v1',temperature=0,max_tokens=6144,request_timeout=120)
            r=observe(a,mechanism,arm,folder,render,evidence_kind='real_Qwen',deadline=deadline,seed=seed,run_id=RUN_ID)
            if r['budget_stopped'] or r.get('error'):
                raise ValueError('Episode stopped; no replacement')
            trajectory_hash=protocol_check(r,folder,mechanism)
            summary.append({'seed':seed,'checkpoint':mechanism,'arm':arm,'trajectory_sha256':trajectory_hash,
                            'sdk_requests':r['sdk_requests'],'protocol':'pass'})
            (args.output/'progress.json').write_text(json.dumps(summary,indent=2))
            if index == 3:
                (args.output/'stage-A-pass.json').write_text(json.dumps({'protocol':'pass','advance':'B','performance_used':False}))
        (args.output/'completed.json').write_text(json.dumps({'episodes':len(summary),'status':'raw_results_ready_for_behavior_audit'}))
    except Exception as exc:
        (args.output/'stopped.json').write_text(json.dumps({'error':repr(exc),'completed':len(summary)}))
        raise

if __name__ == '__main__':
    main()
