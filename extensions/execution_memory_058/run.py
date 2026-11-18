"""CPU prototype using native ToolExecutor and InferenceContext, no benchmark truth."""
import argparse,copy,hashlib,json,sys,time
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'benchmarks/ToolMaze'))
from toolmaze.core.executor import ToolExecutor
from evaluation.core.sandbox import InferenceContext

class PublicLoader:
    def __init__(self):
        self.tools={}
        for name in ('source','processor','action'):
            for t in yaml.safe_load((ROOT/f'benchmarks/ToolMaze/tools/definitions/{name}.yaml').read_text())['tools']:
                spec=t['paradigms']['function_call']['spec']
                self.tools[t['name']]={'paradigms':{'function_call':{'spec':copy.deepcopy(spec)}},'outputs':copy.deepcopy(t['paradigms']['mcp']['output_schema'])}
    def get_tool_by_name(self,name):return self.tools.get(name)


def resolve(v,inputs,outs):
    if isinstance(v,str) and v.startswith('$'):
        head,*keys=v[1:].split('.')
        value=inputs if head=='input' else outs[int(head)]
        for k in keys:value=value[k]
        return copy.deepcopy(value)
    return v


def contract_check(plan,inputs,loader):
    """Prospective check of required args, reference provenance and top-level types."""
    types={'string':str,'integer':int,'number':(int,float),'array':list,'object':dict,'boolean':bool}
    for i,(tool,args) in enumerate(plan):
        spec=loader.tools[tool]['paradigms']['function_call']['spec']['parameters']
        if not set(spec.get('required',[]))<=args.keys():return False
        for key,value in args.items():
            expect=spec.get('properties',{}).get(key,{}).get('type')
            if isinstance(value,str) and value.startswith('$'):
                head,*path=value[1:].split('.')
                if head=='input':
                    try:actual=resolve(value,inputs,[])
                    except KeyError:return False
                    if expect in types and not isinstance(actual,types[expect]):return False
                else:
                    n=int(head)
                    if n>=i:return False
                    out=loader.tools[plan[n][0]]['outputs']
                    if path and path[0] not in out:return False
                    actualtype=out[path[0]].get('type') if path else 'object'
                    if expect and actualtype and expect!=actualtype:return False
            elif expect in types and not isinstance(value,types[expect]):return False
    return True

class Runner:
    def __init__(self):
        self.loader=PublicLoader();self.ex=ToolExecutor(str(ROOT/'benchmarks/ToolMaze/tools/plugins'),str(ROOT/'benchmarks/ToolMaze/tools/definitions'),self.loader)
        self.costs={};self.phase='setup';self.internal=0
    def bump(self,key,n=1):
        d=self.costs.setdefault(self.phase,{})
        d[key]=d.get(key,0)+n
    def fresh(self):self.bump('context_resets');return InferenceContext()
    def execute(self,plan,inputs,context=None):
        ctx=context if context is not None else self.fresh();outs=[];ok=True;t0=time.perf_counter()
        def profile(frame,event,arg):
            if event=='call' and frame.f_code.co_name=='execute' and '/tools/plugins/' in frame.f_code.co_filename:self.bump('plugin_execute_entries')
        for tool,args in plan:
            try:bound={k:resolve(v,inputs,outs) for k,v in args.items()}
            except (KeyError,IndexError,TypeError) as err:
                outs.append({'error':'binding: '+str(err)});ok=False;break
            sys.setprofile(profile)
            try:out=self.ex.execute(tool,bound,ctx,len(ctx.history)+1)
            finally:sys.setprofile(None)
            self.bump('tool_calls');outs.append(copy.deepcopy(out))
            if 'error' in out:ok=False;break
        self.bump('execution_seconds',time.perf_counter()-t0)
        return {'success':ok,'outputs':outs,'trace':ctx.to_trace()}


def obligation(scope,inputs,trace):
    if not trace['success']:return {'receipt':'reject','state':'unknown','reason':'execution_failed'}
    out=trace['outputs'][-1]
    if scope=='selection':
        rec=trace['outputs'][0].get('similar_products',[])
        eligible={p['id'] for p in rec if p.get('stock',0)>=inputs['quantity']}
        pid=out.get('product_id');good=pid in eligible and out.get('available_stock',0)>=inputs['quantity']
        if inputs.get('desired'):good=good and pid==inputs['desired']
        return {'receipt':'accept' if good else 'reject','state':'not_applicable','reason':'recommended_in_stock_and_requested' if good else 'selection_mismatch'}
    if scope=='order':
        pid=out.get('product_id');good=pid!=inputs['product_id'] and out.get('quantity')==inputs['quantity']
        if inputs.get('desired'):good=good and pid==inputs['desired']
        return {'receipt':'accept' if good else 'reject','state':'unknown','reason':'no_order_payment_readback' if good else 'wrong_product'}
    good=(out.get('billing_email')==inputs['email'] and out.get('total_due')==inputs['amount'] and out.get('status')=='generated' and '/'+inputs['payment_gateway']+'/' in out.get('payment_link',''))
    return {'receipt':'accept' if good else 'reject','state':'unknown','reason':'invoice_payload_receipt_only' if good else 'invoice_fields_mismatch'}


def plans():
    rec=('get_recommendations',{'product_id':'$input.product_id','category':'$input.category','user_id':'$input.user_id'})
    select=('select_recommendation',{'similar_products':'$0.similar_products','quantity':'$input.quantity'})
    hold=('hold_inventory',{'product_id':'$input.product_id','quantity':'$input.quantity','user_id':'$input.user_id'})
    best=('hold_best_recommendation',{'product_id':'$input.product_id','quantity':'$input.quantity','user_id':'$input.user_id','category':'$input.category'})
    inv={'items':'$input.items','user_id':'$input.user_id','email':'$input.email','payment_gateway':'$input.payment_gateway','coupon_code':'SAVE15'}
    return {'selection':{'select':[rec,select],'wrong_original':[rec,hold],'overstock':[rec,('select_recommendation',{'similar_products':'$0.similar_products','quantity':999})]},'order':{'held':[best,('build_checkout_from_hold',{'hold_data':'$0','quantity':'$input.quantity'}),('confirm_held_recommendation_order',{'reservation_id':'$1.reservation_id','product_id':'$1.product_id','quantity':'$1.quantity'})],'wrong_original':[hold,('confirm_order',{'reservation_id':'$0.reservation_id','product_id':'$input.product_id','quantity':'$input.quantity'})]},'invoice':{'invoice':[('generate_invoice_from_cart',inv)],'wrong_email':[('generate_invoice_from_cart',dict(inv,email='wrong@example.com'))]}}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--contexts',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    def forbid_truth(event,values):
        if event=='open':
            path=str(values[0])
            if Path(path).name=='alternatives.yaml' or '/perturbed_tasks/' in path:
                raise PermissionError('Benchmark truth access forbidden in 058 runner')
    sys.addaudithook(forbid_truth)
    contexts=json.loads(args.contexts.read_text());r=Runner();cases=[];pool=plans();memory=None
    for scope,group in [('selection',contexts['purchase']),('order',contexts['purchase']),('invoice',contexts['invoice'])]:
        for c in group:
            inp=copy.deepcopy(c['inputs'])
            if scope=='invoice':
                r.phase='invoice_preconditions'
                # Public receipt establishes selected item and coupon-derived amount; no hidden item table.
                result=r.execute(pool['selection']['select'],inp)
                pid=result['outputs'][-1]['product_id'];inp['items']=[{'product_id':pid,'quantity':inp['quantity']}]
                total=r.execute([('get_cart_summary',{'items':'$input.items','user_id':'$input.user_id','coupon_code':'SAVE15'})],inp)
                inp['amount']=total['outputs'][0]['final_total']
            for name,plan in pool[scope].items():
                r.phase='B_'+scope;r.bump('candidate_scans');b0=contract_check(plan,inp,r.loader)
                trace=r.execute(plan,inp);r.bump('obligation_checks');m=obligation(scope,inp,trace)
                overall=m['receipt'] if scope=='selection' or m['receipt']=='reject' else 'unknown'
                cases.append({'context':c['task'],'scope':scope,'candidate':name,'B0':b0,'B1':b0 and trace['success'],'M':overall,'evidence':m,'plan':plan,'inputs':inp,'trace':trace})
                if scope=='selection' and name=='select' and c==group[0] and overall=='accept':
                    r.phase='memory_build';r.bump('memory_writes');memory={'scope':'selection','preconditions':{'category':inp['category'],'quantity_min':1,'quantity_max':inp['quantity'],'original_product':inp['product_id']},'plan':plan,'source':c['task'],'result':m,'verified_range':'one source context; no backend/version or distribution generalization','failures':['wrong_original','overstock'],'construction_cost_phase':'B_selection','parameter_dependencies':'step1.similar_products -> step2.similar_products; fresh task user/product/quantity'}
    assert memory
    target=contexts['purchase'][1]['inputs']
    r.phase='C_rediscover'
    for plan in pool['selection'].values():
        r.bump('candidate_scans');t=r.execute(plan,target);r.bump('obligation_checks');obligation('selection',target,t)
    baseline=r.execute(pool['selection']['select'],target);r.bump('obligation_checks');base=obligation('selection',target,baseline)
    r.phase='C_reuse';r.bump('memory_reads');r.bump('applicability_checks')
    eligible=(target['category']==memory['preconditions']['category'] and target['product_id']==memory['preconditions']['original_product'] and 1<=target['quantity']<=memory['preconditions']['quantity_max'])
    reuse=r.execute(memory['plan'],target) if eligible else None
    if reuse:r.bump('obligation_checks')
    reused=obligation('selection',target,reuse) if reuse else {'receipt':'unknown'}
    # 058A: observe native history-based state, no private globals queried by M.
    r.phase='A_state';state={}
    for label,holdplan in [('direct',[('hold_inventory',{'product_id':'$input.product_id','quantity':1})]),('macro',[('hold_best_recommendation',{'product_id':'$input.product_id','quantity':1})])]:
        ctx=r.fresh();probe=[('get_stock_level',{'product_id':'p_sony_xm5_slv' if label=='macro' else target['product_id']})]
        before=r.execute(probe,target,ctx);held=r.execute(holdplan,target,ctx);after=r.execute(probe,target,ctx);fresh=r.execute(probe,target)
        state[label]={'before':before,'held':held,'after':after,'fresh':fresh}
    result={'cases':cases,'costs':r.costs,'memory':memory,'reuse':{'applicable':eligible,'source':contexts['purchase'][0]['task'],'target':contexts['purchase'][1]['task'],'baseline':base,'reused':reused,'trace':reuse,'independence':'different existing task, same interface/product/backend; not independent generalization'},'state_audit':state,'model_calls':0,'context_sha256':hashlib.sha256(args.contexts.read_bytes()).hexdigest()}
    (args.out/'results.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({'cases':[{k:x[k] for k in ('context','scope','candidate','B0','B1','M')} for x in cases],'costs':r.costs,'reuse':result['reuse']|{'trace':'see results.json'}},indent=2))
if __name__=='__main__':main()
