"""Strict staged live-model experiment; any interaction fault stops the run."""
import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import statistics
import subprocess
import time
import traceback

from .environment import CONFIG, ROOT, RecoverySession, load_case
from .model_adapter import MODEL_CONFIG, SYSTEM, INTERFACE_INSTRUCTION, RecordedModelPolicy, ProtocolFailure, public_model_view
from .policies import theory
from .verification import evaluate

BASELINE=ROOT/'results/005-gate3-full-20261105-01/artifacts'


def dump(path,value):
    with path.open('x') as f: json.dump(value,f,ensure_ascii=False,indent=2)


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def decision_errors(view,action,turn):
    errors=[]; c=view['costs']; decisions=view['decisions']; t=theory(view)
    if turn==0 and c['diagnosis']<t['gross_information_value'] and action!='diagnose':
        errors.append('low_price_initial_no_diagnosis')
    if turn==0 and action=='switch' and c['switch']>t['best_no_diagnosis']:
        errors.append('higher_expected_cost_initial_switch')
    previous=[d for d in decisions if d['action']=='diagnose']
    failed_retry=any(d['action']=='retry' and not d['result']['recovered'] for d in decisions)
    if action=='diagnose':
        if c['diagnosis']>t['gross_information_value']: errors.append('high_price_diagnosis')
        if previous: errors.append('repeated_diagnosis')
        if failed_retry: errors.append('diagnosis_after_failed_retry')
    if previous:
        recover=previous[-1]['result']['retry_will_recover']
        if action=='retry' and not recover: errors.append('retry_after_persistent_diagnosis')
        if action=='switch' and recover: errors.append('switch_after_recoverable_diagnosis')
    if action=='retry' and failed_retry: errors.append('retry_after_failed_retry')
    return errors


def episode(task,mode,price,out,interface=False):
    logs=[]; views=[]; errors=[]; session=None; start=time.perf_counter()
    with (out/f'{task}_{mode}_{price}.jsonl').open('x') as stream:
        def record(value):
            logs.append(value); stream.write(json.dumps(value,ensure_ascii=False)+'\n'); stream.flush()
        try:
            session=RecoverySession(task,mode,price)
            policy=RecordedModelPolicy(interface_check=interface)
            view=session.view()
            for turn in range(CONFIG['max_decisions']):
                views.append(public_model_view(view))
                action=policy.choose(view,turn,record)
                if interface and turn==0 and action!='diagnose':
                    raise ProtocolFailure('interface_did_not_call_diagnose_first')
                errors.extend(decision_errors(view,action,turn))
                view=session.act(action)
                record({'event':'environment_audit','audit':session.audit()})
                policy.feedback(action,view,record)
                if view['done']: break
            if not view['done']: raise ProtocolFailure('decision_budget_exhausted')
            audit=session.audit(); score=evaluate(task,mode,audit['events'])
            if score['native_pass']!=score['independent_valid']:
                raise ProtocolFailure('scoring_anomaly')
            if not score['legal_success']: raise ProtocolFailure('basic_recovery_failed')
            if interface and sum(d['action']=='diagnose' for d in audit['decisions'])!=1:
                raise ProtocolFailure('interface_diagnosis_count_not_one')
            result={**audit,'task':task,'price':price,'score':score,'status':'completed'}
        except Exception as exc:
            partial=session.audit() if session is not None else {}
            score=evaluate(task,mode,partial['events']) if 'events' in partial else None
            result={**partial,'task':task,'mode':mode,'price':price,'status':'stopped',
                    'fatal_error':str(exc),'traceback':traceback.format_exc(),'score':score}
            record({'event':'fatal_stop','error':repr(exc)})
    responses=[r for r in logs if r['event']=='response']
    requests=[r for r in logs if r['event']=='request']
    usages=[r['response'].get('usage') for r in responses]
    known=[u for u in usages if u is not None]
    result.update(interface_check=interface,public_views=views,error_types=errors,
        model_requests=len(requests),unknown_usage_requests=len(requests)-len(known),
        known_token_totals={k:sum(u.get(k,0) or 0 for u in known) for k in ('prompt_tokens','completion_tokens','total_tokens')},
        request_latencies=[r['latency_seconds'] for r in logs if r['event'] in ('response','request_error')],
        wall_elapsed_seconds=time.perf_counter()-start)
    dump(out/f'{task}_{mode}_{price}.json',result)
    return result


def snapshot(tasks):
    baseline=json.loads((BASELINE/'config.json').read_text())
    frozen={**baseline['original_source_hashes'],**baseline['input_hashes']}
    if any(sha(ROOT/p)!=h for p,h in frozen.items()):
        raise ProtocolFailure('gate3_original_source_or_input_changed')
    mvp={}
    for name in ('environment.py','config.json','verification.py','policies.py','oracle.py','run.py'):
        path=Path(__file__).with_name(name)
        old=subprocess.check_output(['git','show',f'c127428:extensions/toolmaze_diagnostic_mvp/{name}'],cwd=ROOT)
        if hashlib.sha256(old).hexdigest()!=sha(path):
            raise ProtocolFailure('gate3_mvp_changed:'+name)
        mvp[str(path.relative_to(ROOT))]=sha(path)
    model_root=ROOT/'models'/MODEL_CONFIG['model']
    model_files={p.name:{'bytes':p.stat().st_size} for p in model_root.glob('*.safetensors')}
    model_metadata={p.name:sha(p) for p in model_root.glob('*.json')}
    revisions={}
    for p in (model_root/'.cache/huggingface/download').glob('*.metadata'):
        lines=p.read_text().splitlines()
        if lines: revisions[p.name]=lines[0]
    if MODEL_CONFIG['model_revision'] not in set(revisions.values()):
        raise ProtocolFailure('registered_model_revision_not_verified')
    return {'gate3_baseline_config_sha256':sha(BASELINE/'config.json'),'original_hashes':frozen,
            'mvp_hashes':mvp,'model_weight_manifest':model_files,'model_json_hashes':model_metadata,
            'model_cached_revisions':revisions,'weight_bytes_hashed':False}


def summarize(rows):
    result={'attempted':len(rows),'groups':{},'error_types':dict(Counter(e for r in rows for e in r['error_types']))}
    for price in CONFIG['diagnostic_costs']:
        rs=[r for r in rows if r['price']==price]
        if not rs: continue
        successes=[r for r in rs if r.get('score') and r['score']['legal_success']]
        calls=[t for r in rs for t in r['request_latencies']]
        recovery=[r['recovery_cost'] for r in rs if 'recovery_cost' in r]
        totals=[r['total_cost'] for r in rs if 'total_cost' in r]
        references=defaultdict(list)
        for r in rs:
            for policy in ('switch','retry_then_switch','cost_selective','oracle'):
                p=BASELINE/f'{r["task"]}_{r["mode"]}_{price}_{policy}.json'
                references[policy].append(json.loads(p.read_text())['recovery_cost'])
        result['groups'][price]={'attempted':len(rs),'legal_completed':len(successes),
             'legal_completion_rate':len(successes)/len(rs),
             'mean_recovery_cost_all_attempts':statistics.mean(recovery) if recovery else None,
             'mean_total_cost_all_attempts':statistics.mean(totals) if totals else None,
             'mean_recovery_cost_completed':statistics.mean(r['recovery_cost'] for r in successes) if successes else None,
             'diagnosis_episode_rate':sum(any(d['action']=='diagnose' for d in r.get('decisions',[])) for r in rs)/len(rs),
             'diagnostic_calls':sum(sum(d['action']=='diagnose' for d in r.get('decisions',[])) for r in rs),
             'model_requests':sum(r['model_requests'] for r in rs),
             'unknown_usage_requests':sum(r['unknown_usage_requests'] for r in rs),
             'known_token_totals':{k:sum(r['known_token_totals'][k] for r in rs) for k in ('prompt_tokens','completion_tokens','total_tokens')},
             'mean_request_latency_seconds':statistics.mean(calls) if calls else None,
             'mean_episode_wall_seconds':statistics.mean(r['wall_elapsed_seconds'] for r in rs),
             'matched_gate3_mean_recovery_costs':{p:statistics.mean(values) for p,values in references.items()},
             'cost_advantage_claim_allowed':len(successes)==len(rs)}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',choices=('interface','smoke','full'),required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--prerequisite',type=Path)
    args=parser.parse_args(); args.out.mkdir(parents=True,exist_ok=False)
    rows=[]; stage=args.stage
    try:
        tasks=list(CONFIG['tasks']) if stage=='full' else ['018']
        hashes=snapshot(tasks)
        if stage!='interface':
            if args.prerequisite is None: raise ProtocolFailure('missing_stage_prerequisite')
            prior=json.loads((args.prerequisite/'evaluation.json').read_text())
            prior_config=json.loads((args.prerequisite/'config.json').read_text())
            expected='interface' if stage=='smoke' else 'smoke'
            if prior['status']!='completed' or prior['stage']!=expected:
                raise ProtocolFailure('stage_prerequisite_failed')
            if prior_config['model_config']!=MODEL_CONFIG or prior_config['system_prompt']!=SYSTEM:
                raise ProtocolFailure('model_conditions_changed_between_stages')
        metadata_client=RecordedModelPolicy().agent.client
        served=metadata_client.models.list().model_dump(mode='json')
        if MODEL_CONFIG['model'] not in [m['id'] for m in served['data']]:
            raise ProtocolFailure('registered_model_not_served')
        dump(args.out/'config.json',{'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'stage':stage,'tasks':tasks,'seed':0,'model_config':MODEL_CONFIG,'system_prompt':SYSTEM,
            'interface_instruction':INTERFACE_INSTRUCTION,'environment_config':CONFIG,'served_models':served,
            'python':platform.python_version(),'packages':{p:importlib.metadata.version(p) for p in ('vllm','transformers','openai')},
            'provenance':hashes})
        specs=[('018','P1','low')] if stage=='interface' else [(t,m,p) for t in tasks for p in CONFIG['diagnostic_costs'] for m in ('P1','P2')]
        for task,mode,price in specs:
            print(f'Starting {task} {mode} {price} ({stage})',flush=True)
            row=episode(task,mode,price,args.out,stage=='interface'); rows.append(row)
            print(f'Finished {task} {mode} {price}: {row["status"]}',flush=True)
            if row['status']!='completed': break
        summary=summarize(rows)
        summary.update(stage=stage,planned=len(specs),status='completed' if len(rows)==len(specs) and all(r['status']=='completed' for r in rows) else 'stopped')
        summary['model_conditions_unchanged']=snapshot(tasks)==hashes
        summary['paired_first_requests_equal']=None
        if stage!='interface' and summary['status']=='completed':
            paired=[]
            for task in tasks:
                for price in CONFIG['diagnostic_costs']:
                    requests=[]
                    for mode in ('P1','P2'):
                        first=json.loads((args.out/f'{task}_{mode}_{price}.jsonl').read_text().splitlines()[0])
                        requests.append(first['request'])
                    paired.append(requests[0]==requests[1])
            summary['paired_first_requests_equal']=all(paired)
            if not all(paired): summary['status']='stopped'
        if not summary['model_conditions_unchanged']: summary['status']='stopped'
        dump(args.out/'evaluation.json',summary)
        print(json.dumps(summary,ensure_ascii=False),flush=True)
        if summary['status']!='completed': raise SystemExit(1)
    except Exception as exc:
        dump(args.out/'setup_failure.json',{'stage':stage,'error':repr(exc),'traceback':traceback.format_exc()})
        raise


if __name__=='__main__': main()
