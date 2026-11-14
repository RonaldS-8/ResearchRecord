"""Public-history-only statistical information arms. No generator or reference planner."""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from time import perf_counter
import subprocess
from .gate44a import BTM,digest,restored
from .gate44obs import observe,tokenizer_renderer
from .gate34b import initialize
from .gate42a import evaluate
from .run import VLLMAgent,MODEL,MODEL_REVISION
from . import gate45_hmm as hmm

RUN='045-stat-01'
ARMS=('R2','R3','R4')

def outcome(e):return 'ok' if 'error' not in e['result'] else str(e['result'].get('code',e['result']['error']))
def frozen_information(rows,mechanism):
    pool=[r for r in rows if r['mechanism']==mechanism]
    memory=Counter();switch=Counter();values={};history=[]
    for r in pool:
        events=r['events'];success=int(r['strict_success'])
        memory.update((tool,err,success) for tool,err in {(e['tool'],outcome(e)) for e in events if 'error' in e['result']})
        keys={(x['tool'],y['tool']) for x,y in zip(events,events[1:]) if 'error' in x['result'] and x['tool']!=y['tool']}
        switch.update((x,y,success) for x,y in keys)
        suffix=events[r['checkpoint']:];action=suffix[0]['tool'] if suffix else 'stop'
        values.setdefault(action,[]).append((success,float(r['remaining_fees']['execution'])+float(r['remaining_fees']['diagnosis'])))
        history.append({'x':mechanism,'steps':[(None,e['tool'],outcome(e)) for e in events]})
    def beta(counter,key):
        good=counter[(*key,1)];bad=counter[(*key,0)]
        return {'n':good+bad,'successes':good,'beta_mean':(good+1)/(good+bad+2),'prior':'Beta(1,1)'}
    recover=[{'tool':t,'error':e,**beta(memory,(t,e))} for t,e in sorted({(t,e) for t,e,y in memory})]
    switching=[{'source':s,'target':t,**beta(switch,(s,t))} for s,t in sorted({(s,t) for s,t,y in switch})]
    actions=set(restored(mechanism).tools)|{'stop'}
    acv={a:{'support':len(values.get(a,[])),'completion':sum(y for y,c in values[a])/len(values[a]) if a in values else None,'remaining_fee':sum(c for y,c in values[a])/len(values[a]) if a in values else None} for a in sorted(actions)}
    supported=[a for a,v in acv.items() if v['support']]
    chosen=min(supported,key=lambda a:(-acv[a]['completion'],acv[a]['remaining_fee'],a)) if supported else None
    labels=hmm.logged_labels(history)
    models=[hmm.train(history,None,k,4529001,transitions=dynamic,restarts=2,iterations=300,labels=labels,exact=True) for k in (1,2) for dynamic in (False,True)]
    best=min(models,key=lambda m:(m.bic(),m.k,m.transitions))
    events=restored(mechanism).view()['history'];public=[(e['tool'],outcome(e)) for e in events]
    belief=best.filter(mechanism,public)
    predictions={tool:{'p_next_receipt_ok':best.success(mechanism,public,tool),'observed_calls':sum(e['tool']==tool for r in pool for e in r['events'])} for tool in sorted(best.emit) if 'ok' in best.emit[tool]}
    return {'training_episodes':len(pool),'btm':{'tool_error':recover,'switch':switching},'acv':acv,'acv_suggestion':chosen,
        'hmm':{'states':best.k,'dynamic':best.transitions,'loglik':best.loglik,'bic':best.bic(),'candidate_bic':[{'states':m.k,'dynamic':m.transitions,'bic':m.bic()} for m in models],'belief':belief,'next_call':predictions,'parameters':{'start':best.start,'emit':best.emit,'move':best.move},'clock':'one actual logged tool call and its receipt, including prefix; no automatic tails','recommendation':None,'limitation':'Next-receipt probabilities are not final completion or remaining cost; no CPU reference planner transplanted.'}}

def advice(arm,info):
    common='Frozen shared training pool: 24 real Agent episodes, same seen task/checkpoints, randomized FIRST SUGGESTION (not actual action), original native continuation with suggestion remaining in conversation. Observational associations only; no causal action effects or independent-task guarantee. Unsupported entries are unknown. Use only actual receipts for arguments and independently execute all remaining obligations.\n'
    if arm=='R2':return common+BTM+'\nFrozen Bayesian Tool Memory (final episode strict success, per episode key deduplication; includes publicly observed write/validation errors):\n'+json.dumps(info['btm'])
    if arm=='R3':return common+'Historical ACTUAL first-action completion and remaining simulated tool fee (includes that action and entire realized suffix):\n'+json.dumps(info['acv'])+'\nSuggested first action among supported entries, greatest observed completion then lowest fee on exact ties: '+str(info['acv_suggestion'])
    if arm=='R4':return common+'History-fitted HMM information only; anonymous statistical states are not named fault causes. No final-completion planner or forced action.\n'+json.dumps({k:v for k,v in info['hmm'].items() if k!='parameters'})
    raise ValueError(arm)

def plan(n=10):
    return [(452001+i,m,arm) for i in range(n) for m in (('M3','M4') if i%2==0 else ('M4','M3')) for arm in ARMS[i%3:]+ARMS[:i%3]]

def native():return VLLMAgent(MODEL,'http://127.0.0.1:8000/v1',temperature=0,max_tokens=6144,request_timeout=120)

def main():
    p=argparse.ArgumentParser();p.add_argument('--training',type=Path);p.add_argument('--freeze',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--model-path',type=Path,required=True);p.add_argument('--prepare',action='store_true');a=p.parse_args()
    from importlib.metadata import version
    import platform
    assert (platform.python_version(),version('vllm'),version('openai'))==('3.10.12','0.31.0','3.42.0')
    for name in ('config.json','tokenizer_config.json'):
        assert (a.model_path/'.cache/huggingface/download'/(name+'.metadata')).read_text().splitlines()[0]==MODEL_REVISION
    render=tokenizer_renderer(a.model_path)
    if a.prepare:
        rows=[json.loads(x) for x in a.training.read_text().splitlines()];assert len(rows)==24
        from .gate45c import session,schedule
        assigned={r['id']:r for r in schedule()}
        assert {r['id'] for r in rows}==set(assigned)
        for row in rows:
            original=json.loads((a.training.parent/row['id']/'result.json').read_text())
            assert row['source_result_sha256']==digest(original)
            s=session(assigned[row['id']])
            assert row['public_checkpoint']==s.view() and row['contract']==s.public()
            for e in row['events'][row['checkpoint']:]:s.call(e['tool'],e['arguments'])
            score=evaluate(s,row['answer']);assert score['strict_success']==row['strict_success'] and score['events']==row['events']
        infos={m:frozen_information(rows,m) for m in ('M3','M4')};prompts={}
        for m in ('M3','M4'):
            for arm in ARMS:
                agent=native();initialize(agent,restored(m));text=advice(arm,infos[m]);messages=deepcopy(agent.messages)+[{'role':'user','content':'Recovery information:\n'+text}]
                rendered,n=render(messages,agent.tools);assert n+6144<=32768
                prompts[m+arm]={'advice':text,'messages':messages,'tools':agent.tools,'sha256':digest({'messages':messages,'tools':agent.tools}),'input_tokens':n,'rendered_sha256':digest(rendered)}
        data={'versions':{'python':platform.python_version(),'vllm':version('vllm'),'openai':version('openai'),'transformers':version('transformers')},'run':RUN,'model':MODEL,'revision':MODEL_REVISION,'training_path':str(a.training),'training_sha256':__import__('hashlib').sha256(a.training.read_bytes()).hexdigest(),'training_episodes':24,'information':infos,'prompts':prompts,'plan':plan()}
        a.freeze.parent.mkdir(parents=True,exist_ok=True)
        with a.freeze.open('x') as f:json.dump(data,f,indent=2)
        return
    data=json.loads(a.freeze.read_text());a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'freeze.json').write_text(json.dumps(data,indent=2));(a.output/'source-commit.txt').write_text(subprocess.check_output(['git','rev-parse','HEAD'],text=True))
    deadline=perf_counter()+19*3600;done=[];behaviors={};skip=set()
    try:
        for seed,m,arm in plan():
            if (m,arm) in skip:continue
            agent=native();s=restored(m);initialize(agent,s);info=data['prompts'][m+arm]
            assert digest({'messages':agent.messages+[{'role':'user','content':'Recovery information:\n'+info['advice']}],'tools':agent.tools})==info['sha256']
            folder=a.output/(str(seed)+'-'+m+'-'+arm)
            r=observe(agent,m,arm,folder,render,evidence_kind='real_Qwen_statistical_exploratory',deadline=deadline,seed=seed,run_id=RUN,collection_session=s,collection_advice=info['advice'])
            if r.get('error') or r['budget_stopped']:raise ValueError('Episode protocol stop')
            check=restored(m);cut=len(check.events)
            for t in r['transitions']:check.call(t['tool'],t['arguments'])
            assert all(r[k]==v for k,v in evaluate(check,r['answer']).items())
            req=[json.loads(x) for x in (folder/'requests.jsonl').read_text().splitlines()];assert req and not any('error' in q for q in req)
            behavior=digest([{'tool':e['tool'],'arguments':e['arguments'],'result':e['result']} for e in r['events'][cut:]])
            behaviors.setdefault((m,arm),set()).add(behavior)
            done.append({'seed':seed,'checkpoint':m,'arm':arm,'sdk':len(req),'behavior_sha256':behavior,'protocol':'pass'})
            (folder/'method-recommendation.json').write_text(json.dumps({'arm':arm,'training_sha256':data['training_sha256'],'information':data['information'][m],'actual_first_action':r['checkpoints'][0]['model_action'],'note':'R2 static/Beta constraints; R3 explicit first-action suggestion; R4 information-only, no final-completion recommendation'},indent=2))
            (a.output/'progress.json').write_text(json.dumps(done,indent=2))
            if seed==452005 and len(behaviors[m,arm])<3:
                skip.add((m,arm));(a.output/(m+'-'+arm+'-extension-skipped.json')).write_text(json.dumps({'reason':'fewer than 3 distinct executed tool/argument/receipt suffixes in first 5; do not manufacture sample size with seeds'}))
        (a.output/'completed.json').write_text(json.dumps({'episodes':len(done),'status':'raw_results_complete_pending_review','extension_skipped':[list(k) for k in sorted(skip)]}))
    except Exception as exc:
        (a.output/'stopped.json').write_text(json.dumps({'episodes':len(done),'error':repr(exc)}));raise
if __name__=='__main__':main()
