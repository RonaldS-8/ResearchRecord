"""Fixed Gate059 CPU evidence check. No route discovery or model calls."""
import argparse,copy,hashlib,json,sys,time
from pathlib import Path
from .adapter import runner
from extensions.execution_memory_058.run import contract_check,plans
MODES=('native','reservation_projection_v1');ROUTES=('macro','expanded')

def call(r,ctx,name,args):
    result=r.execute([(name,args)],{},ctx)
    return result['outputs'][-1]

def locate(r,ctx,inp):
    rec=call(r,ctx,'get_recommendations',{k:inp[k] for k in ('product_id','category','user_id')})
    if 'error' in rec:return None
    sel=call(r,ctx,'select_recommendation',{'similar_products':rec['similar_products'],'quantity':inp['quantity']})
    return sel if 'error' not in sel else None

def prepare(r,inp,used):
    r.phase='preparation';ctx=r.fresh()
    if used:
        sel=locate(r,ctx,dict(inp,quantity=8))
        call(r,ctx,'hold_inventory',{'product_id':sel['product_id'],'quantity':8,'user_id':inp['user_id']})
    return ctx

def static_check(history,inp,route,loader):
    # Schema/value/dependency rules plus all known public state; no private table.
    rec=plans()['selection']['select']; p=rec+[('hold_inventory',{'product_id':'$1.product_id','quantity':'$input.quantity','user_id':'$input.user_id'})]
    if route=='macro':p=[('hold_best_recommendation',{k:'$input.'+k for k in ('product_id','category','quantity','user_id')})]
    if not contract_check(p,inp,loader) or inp['quantity']<=0:return 'reject'
    known=[h for h in history if h.tool_name=='select_recommendation' and 'error' not in h.output]
    if not known:return 'unknown'
    sel=known[-1].output;pid=sel['product_id'];stock=sel.get('available_stock')
    if stock is None:return 'unknown'
    if inp.get('desired') and inp['desired']!=pid:return 'reject'
    # This history contains actual preparatory direct holds; never hide them.
    stock-=sum(h.output.get('quantity',0) for h in history if h.tool_name=='hold_inventory' and h.output.get('product_id')==pid and 'error' not in h.output)
    return 'accept' if stock>=inp['quantity'] else 'reject'

def check_receipt(before,out,inp,pid):
    if 'error' in out:return 'reject'
    if before.get('stock') is None:return 'unknown'
    if before['stock']<inp['quantity']:return 'reject'
    if out.get('product_id')!=pid or out.get('quantity')!=inp['quantity']:return 'reject'
    if inp.get('desired') and out.get('product_id')!=inp['desired']:return 'reject'
    return 'accept'

def state_check(before,after,out,inp,pid):
    receipt=check_receipt(before,out,inp,pid)
    if receipt!='accept':return receipt
    if 'error' in after or 'stock' not in after:return 'unknown'
    return 'accept' if before['stock']-after['stock']==inp['quantity'] else 'reject'

def execute_route(r,ctx,inp,route,stop_if_insufficient=False):
    sel=locate(r,ctx,inp)
    if sel is None:return {'before':{},'after':{},'output':{'error':'selection failed'},'verdict':'reject','early_reject':True}
    pid=sel['product_id'];before=call(r,ctx,'get_stock_level',{'product_id':pid})
    if stop_if_insufficient and ('stock' not in before or before['stock']<inp['quantity'] or (inp.get('desired') and inp['desired']!=pid)):
        return {'before':before,'after':{},'output':{},'verdict':'reject','early_reject':True,'pid':pid}
    if route=='macro':out=call(r,ctx,'hold_best_recommendation',{k:inp[k] for k in ('product_id','category','user_id','quantity')})
    else:
        sel=locate(r,ctx,inp);pid=sel['product_id']
        out=call(r,ctx,'hold_inventory',{'product_id':pid,'quantity':inp['quantity'],'user_id':inp['user_id']})
    after=call(r,ctx,'get_stock_level',{'product_id':out.get('product_id',pid)})
    return {'before':before,'after':after,'output':out,'pid':pid,'early_reject':False,'verdict':state_check(before,after,out,inp,pid)}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=False)
    def guard(event,args):
        if event=='open' and (Path(str(args[0])).name=='alternatives.yaml' or '/perturbed_tasks/' in str(args[0])):raise PermissionError('No benchmark truth in policy')
    sys.addaudithook(guard)
    inp={'product_id':'p_sony_xm5_blk','category':'electronics','quantity':4,'user_id':'u_alice'}
    results=[];memory=None;costs={};total=0
    for mode in MODES:
        for used in (False,True):
            for route in ROUTES:
                r=runner(mode);ctx=prepare(r,inp,used);initial=copy.deepcopy(ctx.to_trace());b0=static_check(ctx.history,inp,route,r.loader)
                r.phase='candidate';ev=execute_route(r,ctx,inp,route)
                b1=check_receipt(ev['before'],ev['output'],inp,ev.get('pid'));m=ev['verdict']
                row={'mode':mode,'state':'prior_hold8' if used else 'fresh','route':route,'B0':b0,'B1':b1,'M':m,'dynamic_rule':m,'success_only':'reject' if 'error' in ev['output'] else 'accept','evidence':ev,'initial':initial,'trace':ctx.to_trace(),'costs':r.costs}
                results.append(row);total+=sum(x.get('tool_calls',0) for x in r.costs.values())
                if mode==MODES[1] and not used and route=='macro' and m=='accept':
                    memory={'route':route,'input_scope':inp,'source':'059 fresh projected context, manual route','contract_mode':mode,'evidence':ev,'costs':copy.deepcopy(r.costs),'parameterized':True,'failures':[]}
    reuse=[]
    if memory:
        target=dict(inp,user_id='user_123',desired='p_sony_xm5_slv')
        for used in (False,True):
            for policy in ('rediscover','success_cache','checked_cache','evidence_memory'):
                r=runner(MODES[1]);ctx=prepare(r,target,used);r.phase='reuse';r.bump('memory_reads',int(policy!='rediscover'));r.bump('candidate_scans',1 if policy=='rediscover' else 0)
                if policy in ('checked_cache','evidence_memory'):r.bump('applicability_checks')
                ev=execute_route(r,ctx,target,memory['route'],stop_if_insufficient=policy!='success_cache')
                # Success cache remains parameterized and updates from error; checked cache has exactly M's feedback.
                action=('accept' if 'error' not in ev['output'] else 'reject') if policy=='success_cache' else ev['verdict']
                reuse.append({'state':'prior_hold8' if used else 'fresh','policy':policy,'decision':action,'verified':ev['verdict'],'evidence':ev,'trace':ctx.to_trace(),'costs':r.costs})
                total+=sum(x.get('tool_calls',0) for x in r.costs.values())
    assert total<=240,total
    for row in results:assert row['costs']['candidate']['tool_calls']<=8
    for row in reuse:assert row['costs']['reuse']['tool_calls']<=16
    result={'candidates':results,'reuse':reuse,'memory':memory,'total_tool_calls':total,'model_requests':0,'seed':None,'knowledge':'manual candidates/bindings; no autonomous discovery; previously seen assets'}
    (a.out/'results.json').write_text(json.dumps(result,indent=2))
    summary={'candidates':[{k:r[k] for k in ('mode','state','route','B0','B1','M','dynamic_rule','success_only','costs')} for r in results],'reuse':[{k:r[k] for k in ('state','policy','decision','verified','costs')} for r in reuse],'total_tool_calls':total,'model_requests':0,'raw_sha256':hashlib.sha256((a.out/'results.json').read_bytes()).hexdigest()}
    (a.out/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
