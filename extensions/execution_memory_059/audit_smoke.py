"""Offline independent replay/scoring of fixed 060 artifacts; zero model requests."""
import argparse,collections,copy,hashlib,json,re,time
from pathlib import Path
from .agent_smoke import setup,digest,NAMES
from .run import call,runner
from extensions.toolmaze_recovery.gate44obs import tokenizer_renderer

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=False)
    run=a.root/'results/060-agent-route-smoke-01';allfiles=[p for p in run.rglob('*') if p.is_file()]
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    hashes={str(p.relative_to(run)):sha(p) for p in allfiles}
    freeze=json.loads((run/'freeze.json').read_text());assert freeze['commit']=='1bcfad5e106f744fd8968b31a511c4de9958f317'
    assert len(freeze['plan'])==8
    render=tokenizer_renderer(a.root/'models/Qwen3-4B-Thinking-2507')
    reports=[];aggregate={};replayed=0
    for p in freeze['plan']:
        folder=run/(p['checkpoint']+'-'+p['arm']);saved=json.loads((folder/'result.json').read_text());requests=[json.loads(s) for s in (folder/'requests.jsonl').read_text().splitlines()]
        assert digest({'messages':p['messages'],'tools':p['tools']})==p['sha256']
        assert requests[0]['request']['messages']==p['messages'] and requests[0]['request']['tools']==p['tools']
        env,public=setup(a.root,p['checkpoint']);replayed+=1;start=len(env.context.history);initial=copy.deepcopy(env.context)
        events=[];tot=collections.Counter();finishes=collections.Counter();modelsecs=0;reason_chars=0
        for index,row in enumerate(requests):
            kw=row['request'];assert kw['model']=='Qwen3-4B-Thinking-2507' and kw['temperature']==0 and kw['max_tokens']==6144 and kw['timeout']==180
            assert kw['seed']==(600001 if p['checkpoint']=='015' else 600002)
            assert kw['tools']==p['tools'] and 'tool_choice' not in kw
            _,n=render(kw['messages'],kw['tools']);assert n==row['rendered_tokens'] and n+6144<=32768
            assert 'error' not in row
            response=row['response'];choice=response['choices'][0];m=choice['message'];finishes[choice['finish_reason']]+=1
            calls=m.get('tool_calls') or [];assert len(calls)<=1
            usage=response['usage'];modelsecs+=row['seconds'];reason_chars+=len(m.get('reasoning') or m.get('reasoning_content') or '')
            for key in ('prompt_tokens','completion_tokens','total_tokens'):tot[key]+=usage[key]
            tot['reasoning_tokens']+=(usage.get('completion_tokens_details') or {}).get('reasoning_tokens') or 0
            if calls:
                fn=calls[0]['function'];tool=fn['name'];args=json.loads(fn['arguments']);assert tool in NAMES
                out,_=env._intercept_tool_call(tool,copy.deepcopy(args));replayed+=1
                events.append({'tool':tool,'arguments':args,'output':out})
                if index+1<len(requests):
                    history=requests[index+1]['request']['messages'];matched=[x for x in history if x.get('role')=='tool' and x.get('tool_call_id')==calls[0]['id']]
                    assert len(matched)==1 and json.loads(matched[0]['content'])==out
        assert events==saved['events'] and len(requests)==saved['requests'] and len(requests)<=8
        suffix=env.context.history[start:];holds=[h for h in suffix if h.tool_name in ('hold_inventory','hold_best_recommendation') and 'error' not in h.output]
        verify=runner('reservation_projection_v1');verify.phase='audit_only';business=False;before={};after={};pre=False;post=False;recommendation=False
        if len(holds)==1:
            hold=holds[0];pid=hold.output.get('product_id');before=call(verify,initial,'get_stock_level',{'product_id':pid});after=call(verify,copy.deepcopy(env.context),'get_stock_level',{'product_id':pid});replayed+=2
            recommendation=(hold.tool_name=='hold_best_recommendation' and hold.output.get('recommended_product_id')==pid and hold.arguments.get('product_id')==public['product_id'])
            for e in events:
                out=e['output']
                if e['tool'].startswith('get_recommendations') and out.get('original_product_id')==public['product_id']:
                    recommendation|=any(x.get('id')==pid and x.get('stock',0)>=1 for x in out.get('similar_products',[]))
            business=bool(recommendation and pid!=public['product_id'] and hold.output.get('quantity')==1 and before.get('stock',-1)-after.get('stock',-1)==1 and (public['desired'] is None or pid==public['desired']))
            hi=next(i for i,e in enumerate(events) if e['tool'] in ('hold_inventory','hold_best_recommendation') and 'error' not in e['output'])
            pre=any(i<hi and e['tool']=='get_stock_level' and e['arguments'].get('product_id')==pid and e['output'].get('stock',-1)>=1 for i,e in enumerate(events))
            post=any(i>hi and e['tool']=='get_stock_level' and e['arguments'].get('product_id')==pid and 'stock' in e['output'] for i,e in enumerate(events))
        legal=all('error' not in e['output'] and e['tool'] not in ('add_to_cart','add_best_recommendation_to_cart') for e in events)
        strict=bool(business and pre and post and legal and saved['answer'] and not saved['halted'])
        assert (business,strict)==(saved['business_success'],saved['strict_success'])
        assert before==saved['before'] and after==saved['after']
        final_message=requests[-1]['response']['choices'][0]['message'];assert saved['answer']==final_message.get('content')
        reasons=[]
        if not recommendation:reasons.append('no_recommendation_receipt')
        if not pre:reasons.append('missing_pre_stock_query')
        if not post:reasons.append('missing_post_stock_query')
        report={'checkpoint':p['checkpoint'],'arm':p['arm'],'requests':len(requests),'agent_tools':len(events),'stock_queries':sum(e['tool']=='get_stock_level' for e in events),'business_success':business,'strict_success':strict,'failure_evidence':reasons,'recommendation_evidence':bool(recommendation),'before_stock':before.get('stock'),'after_stock':after.get('stock'),'sequence':[e['tool'] for e in events],'tokens':dict(tot),'model_seconds':modelsecs,'recorded_reasoning_chars':reason_chars,'finish_reasons':dict(finishes),'search_seconds':p['search_seconds']}
        reports.append(report);ag=aggregate.setdefault(p['arm'],collections.Counter());ag.update(tot);ag.update({'episodes':1,'requests':len(requests),'agent_tools':len(events),'stock_queries':report['stock_queries'],'business_success':int(business),'strict_success':int(strict),'model_seconds':modelsecs,'search_seconds':p['search_seconds']})
    completed=json.loads((run/'completed.json').read_text());assert completed=={'episodes':8,'requests':sum(r['requests'] for r in reports)}
    log=(a.root/'results/060-service-01/vllm.log').read_text();statuses=collections.Counter(re.findall(r'POST /v1/chat/completions HTTP/1.1" (\d+)',log));assert statuses=={'200':33}
    assert hashes=={str(p.relative_to(run)):sha(p) for p in allfiles}
    result={'checks_passed':True,'episodes':reports,'aggregate':aggregate,'sdk_requests':33,'http_statuses':statuses,'independent_replay_environment_calls':replayed,'model_requests_added':0,'raw_sha256':hashes,'recorded_reasoning_present_all':all(x['recorded_reasoning_chars']>0 for x in reports),'all_scores_match':True,'notes':['Native simulator and projection reused for replay, scoring implemented independently.','Additional replay calls are audit-only, not new experimental trajectories.','Original costs for internal plugin entries/reset timing were not fully instrumented.']}
    (a.out/'audit.json').write_text(json.dumps(result,indent=2));print(json.dumps({'aggregate':aggregate,'checks_passed':True,'replay_calls':replayed},indent=2))
if __name__=='__main__':main()
