"""Run preregistered deterministic end-to-end controls on LabServer only."""
import argparse
from collections import defaultdict
import hashlib
import json
import math
import platform
import subprocess
import traceback

from .environment import CONFIG, ROOT, RecoverySession, load_case
from .policies import choose, theory
from .oracle import choose_informed
from .verification import evaluate

POLICIES=('retry_only','switch','retry_then_switch','always_diagnose','cost_selective','oracle')


def dump(path,value):
    with path.open('x') as f: json.dump(value,f,ensure_ascii=False,indent=2)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def episode(task,mode,price,policy,controlled):
    inputs=[]; session=None
    try:
        session=RecoverySession(task,mode,price,controlled)
        view=session.view()
        while not view['done']:
            inputs.append(view)
            action=choose_informed(mode,view) if policy=='oracle' else choose(policy,view)
            view=session.act(action)
        inputs.append(view)
        audit=session.audit()
        score=evaluate(task,mode,audit['events'],controlled)
        return {**audit,'policy':policy,'price':price if controlled else 'original',
                'privileged_reference':policy=='oracle','policy_inputs':inputs,'score':score}
    except Exception as exc:
        return {'task':task,'mode':mode,'policy':policy,'price':price,'controlled':controlled,
                'error':repr(exc),'traceback':traceback.format_exc(),'policy_inputs':inputs,
                'partial_audit':session.audit() if session is not None else None}


def summarize(rows,tasks):
    groups=defaultdict(list)
    unexpected=[]
    for r in rows:
        if 'error' in r:
            unexpected.append({k:r[k] for k in ('task','mode','policy','error')})
            continue
        groups[(r['price'],r['policy'])].append(r)
        expected=not(r['policy']=='retry_only' and r['mode']=='P2')
        if r['score']['legal_success']!=expected:
            unexpected.append({'task':r['task'],'mode':r['mode'],'policy':r['policy'],'score':r['score']})
    summary={'groups':{},'benefits':[],'unexpected_outcomes':unexpected,'checks':{}}
    for (price,policy),rs in groups.items():
        summary['groups'][price+'/'+policy]={'episodes':len(rs),'legal_successes':sum(r['score']['legal_success'] for r in rs),
             'native_successes':sum(r['score']['native_pass'] for r in rs),
             'mean_recovery_cost':sum(r['recovery_cost'] for r in rs)/len(rs),
             'mean_total_cost':sum(r['total_cost'] for r in rs)/len(rs),
             'diagnosis_calls':sum(sum(d['action']=='diagnose' for d in r['decisions']) for r in rs)}
    paired=[]
    for task in tasks:
        for price in CONFIG['diagnostic_costs']:
            rs=[r for r in rows if r.get('controlled') and r['task']==task and r['price']==price and 'error' not in r]
            if len(rs)!=12:
                summary['unexpected_outcomes'].append({'task':task,'price':price,'issue':'missing_episodes'})
                continue
            for policy in POLICIES:
                pair=[r for r in rs if r['policy']==policy]
                paired.append(pair[0]['policy_inputs'][0]==pair[1]['policy_inputs'][0])
            costs={p:sum(r['recovery_cost'] for r in rs if r['policy']==p)/2 for p in POLICIES}
            best=min(costs['switch'],costs['retry_then_switch'])
            net=best-costs['always_diagnose']
            summary['benefits'].append({'task':task,'price':price,'best_complete_no_diagnosis':best,
                'informed':costs['oracle'],'always_diagnose':costs['always_diagnose'],
                'net_benefit':net,'selective_cost':costs['cost_selective']})
    summary['checks']['paired_initial_views_all_identical']=bool(paired) and all(paired)
    summary['checks']['paired_views_checked']=len(paired)
    summary['checks']['low_price_net_benefit_matches_prediction']=all(math.isclose(b['net_benefit'],.25,abs_tol=1e-9) for b in summary['benefits'] if b['price']=='low')
    summary['checks']['high_price_negative_benefit_preserved']=all(math.isclose(b['net_benefit'],-.25,abs_tol=1e-9) for b in summary['benefits'] if b['price']=='high')
    high=groups.get(('high','cost_selective'),[])
    summary['checks']['high_price_selective_buys_no_diagnosis']=bool(high) and all(not any(d['action']=='diagnose' for d in r['decisions']) for r in high)
    summary['checks']['native_and_independent_agree_on_executed_episodes']=all(r['score']['native_pass']==r['score']['independent_valid'] for r in rows if 'error' not in r)
    return summary


def main():
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--smoke',action='store_true')
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    tasks=['018'] if args.smoke else list(CONFIG['tasks'])
    protected={str(p.relative_to(ROOT)):sha(p) for folder in ('evaluation','tools','toolmaze')
               for p in (ROOT/'benchmarks/ToolMaze'/folder).rglob('*') if p.suffix in ('.py','.yaml')}
    inputs={}
    for task in tasks:
        for mode in ('P1','P2'):
            case=load_case(task,mode)
            inputs.update({str(p.relative_to(ROOT)):sha(p) for p in case['files'].values()})
    dump(args.out/'config.json',{'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
         'seed':0,'model':None,'model_version':None,'inference_calls':0,'python':platform.python_version(),
         'stage':'single-task smoke' if args.smoke else '10-task deterministic MVP','config':CONFIG,
         'tasks':tasks,'input_hashes':inputs,'original_source_hashes':protected})
    # Stop before rollouts if the fixed theoretical positive-gain condition fails.
    for task in tasks:
        t=theory(RecoverySession(task,'P1').view())
        if t['gross_information_value']<=CONFIG['diagnostic_costs']['low']:
            dump(args.out/'theory_failure.json',{'task':task,'theory':t})
            raise SystemExit('No positive theoretical gain; stop without adjusting costs')
    rows=[]
    for task in tasks:
        for price in CONFIG['diagnostic_costs']:
            for mode in ('P1','P2'):
                for policy in POLICIES:
                    row=episode(task,mode,price,policy,True)
                    dump(args.out/f'{task}_{mode}_{price}_{policy}.json',row); rows.append(row)
        for mode in ('P1','P2'):
            for policy in ('retry_only','switch','retry_then_switch'):
                row=episode(task,mode,'low',policy,False)
                dump(args.out/f'{task}_{mode}_original_{policy}.json',row); rows.append(row)
        print(f'Completed task {task}',flush=True)
    summary=summarize(rows,tasks)
    summary['checks']['original_sources_and_inputs_unchanged']=all(sha(ROOT/p)==h for p,h in {**protected,**inputs}.items())
    summary['episode_count']=len(rows)
    dump(args.out/'evaluation.json',summary)
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    if summary['unexpected_outcomes'] or not all(v for k,v in summary['checks'].items() if isinstance(v,bool)):
        raise SystemExit(1)


if __name__=='__main__': main()
