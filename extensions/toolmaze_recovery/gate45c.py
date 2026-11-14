"""Authorized 24-episode advice-only training feasibility collection; no fitting."""
import argparse
from copy import deepcopy
import json
import random
from pathlib import Path
from time import perf_counter
from importlib.metadata import version
import platform
import subprocess
from .gate44a import digest, restored
from .gate44obs import observe, tokenizer_renderer
from .gate34b import initialize
from .gate42a import checkpoint, evaluate, MAIN, WRITE, ARCHIVE, ALTWRITE
from .run import VLLMAgent, MODEL, MODEL_REVISION

RUN = '045c-training-01'
TEXT = 'First recovery action suggestion: {action}. This is advice only. Use the public task and actual receipts for any arguments. After this decision, continue independently to satisfy the remaining obligations within the original budget.'


def schedule():
    rng=random.Random(4519001)
    rows=[]
    for block in range(4):
        for mechanism in (('M3','M4') if block%2==0 else ('M4','M3')):
            actions=[MAIN,ARCHIVE,'stop'] if mechanism=='M3' else [WRITE,ALTWRITE,'stop']
            rng.shuffle(actions)
            for position,action in enumerate(actions):
                rows.append({'id':f'{block+1}-{mechanism}-{position+1}','mechanism':mechanism,
                    'block':block+1,'seed':451001+block,'action':action,
                    'marginal_assignment_probability':'1/3',
                    'conditional_assignment_probability':f'1/{3-position}',
                    'advice':TEXT.format(action=action)})
    return rows


def session(row):
    return checkpoint(row['mechanism'],_namespace=RUN+'-'+row['id'])


def native():
    return VLLMAgent(MODEL,'http://127.0.0.1:8000/v1',temperature=0,max_tokens=6144,request_timeout=120)


def payload(row, agent):
    s=session(row)
    if s.public()!=restored(row['mechanism']).public():
        raise ValueError('Public contract/checkpoint drift')
    initialize(agent,s)
    messages=deepcopy(agent.messages)+[{'role':'user','content':'Recovery information:\n'+row['advice']}]
    return s,{'messages':messages,'tools':deepcopy(agent.tools)}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--model-path',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--freeze',type=Path,required=True)
    p.add_argument('--prepare',action='store_true')
    args=p.parse_args()
    versions={k:version(k) for k in ('vllm','openai','transformers')}
    if (platform.python_version(),versions['vllm'],versions['openai'])!=('3.10.12','0.31.0','3.42.0'):
        raise ValueError('Runtime drift')
    for name in ('config.json','tokenizer_config.json'):
        if (args.model_path/'.cache/huggingface/download'/(name+'.metadata')).read_text().splitlines()[0]!=MODEL_REVISION:
            raise ValueError('Revision drift')
    render=tokenizer_renderer(args.model_path)
    entries=[]
    for row in schedule():
        s,data=payload(row,native())
        text,n=render(data['messages'],data['tools'])
        if n+6144>32768:raise ValueError('Context overflow')
        entries.append({**row,'request_payload':data,'prompt_sha256':digest(data),'rendered_sha256':digest(text),'input_tokens':n})
    freeze={'run':RUN,'model':MODEL,'revision':MODEL_REVISION,'versions':versions,'entries':entries,
            'limits':{'episodes':24,'requests':288,'output_tokens':1769472,'service_hours':12},
            'excluded_training_roots':['results/044a-obs-01','results/045-real-agent-01'],
            'source_policy':'randomized first suggestion, actual action unrestricted, original native suffix'}
    if args.prepare:
        args.freeze.parent.mkdir(parents=True,exist_ok=True)
        with args.freeze.open('x') as f:json.dump(freeze,f,indent=2)
        return
    if json.loads(args.freeze.read_text())!=freeze:raise ValueError('Frozen collection drift')
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'freeze.json').write_text(json.dumps(freeze,indent=2))
    (args.output/'source-commit.txt').write_text(subprocess.check_output(['git','rev-parse','HEAD'],text=True))
    deadline=perf_counter()+11*3600
    exports=[]
    try:
        for row in schedule():
            folder=args.output/row['id']
            r=observe(native(),row['mechanism'],row['action'],folder,render,evidence_kind='real_Qwen_training_feasibility',
                deadline=deadline,seed=row['seed'],run_id=RUN,collection_session=session(row),collection_advice=row['advice'])
            if r['budget_stopped'] or r.get('error'):raise ValueError('Episode infrastructure stop')
            s=session(row);cut=len(s.events)
            for t in r['transitions']:s.call(t['tool'],t['arguments'])
            score=evaluate(s,r.get('answer'))
            if any(r[k]!=v for k,v in score.items()):raise ValueError('Independent replay mismatch')
            requests=[json.loads(x) for x in (folder/'requests.jsonl').read_text().splitlines()]
            if not requests or any('error' in x for x in requests):raise ValueError('SDK error')
            first=r['checkpoints'][0]['model_action']
            export={**row,'source_policy':freeze['source_policy'],'contract':s.public(),
                'public_checkpoint':session(row).view(),'events':r['events'],'checkpoint':cut,
                'actual_first_action':first,'suggestion_followed':first['tool']==row['action'] if row['action']!='stop' else first['type']=='final_answer',
                'strict_success':r['strict_success'],'obligations_complete':r['obligations_complete'],
                'answer':r['answer'],'tokens':r['tokens'],'raw_usage':r['raw_usage'],'model_seconds':r['model_seconds'],
                'wall_seconds':r['wall_seconds'],'remaining_fees':r['checkpoints'][0]['realized_suffix_fees'],
                'source_result_sha256':digest(r),'status':'candidate_training_only_pending_eligibility_review'}
            exports.append(export)
            with (args.output/'public-training-candidates.jsonl').open('a') as f:f.write(json.dumps(export)+'\n')
            (args.output/'progress.json').write_text(json.dumps({'episodes':len(exports),'requests':sum(json.loads((args.output/e['id']/'result.json').read_text())['sdk_requests'] for e in exports)}))
        (args.output/'completed.json').write_text(json.dumps({'episodes':24,'status':'collection_complete_not_fitted'}))
    except Exception as exc:
        (args.output/'stopped.json').write_text(json.dumps({'error':repr(exc),'episodes':len(exports)}))
        raise

if __name__=='__main__':main()
