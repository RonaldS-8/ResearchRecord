"""Eight episodes with the existing native VLLMAgent, no new agent framework."""
import argparse,copy,hashlib,json,subprocess,time
from pathlib import Path
from types import SimpleNamespace
from .adapter import ProjectionExecutor
from .run import call,runner
from extensions.execution_memory_058.run import PublicLoader
from extensions.toolmaze_recovery import route_discovery as rd
from extensions.toolmaze_recovery.gate44obs import tokenizer_renderer
from evaluation.agents.vllm_agent import VLLMAgent
from evaluation.core.sandbox import ExecutionEngine
MODEL='Qwen3-4B-Thinking-2507'
NAMES=['get_recommendations','get_recommendations_collaborative','get_recommendations_content','get_recommendations_popularity','get_recommendations_trending','select_recommendation','hold_inventory','hold_best_recommendation','get_stock_level','add_best_recommendation_to_cart','add_to_cart','get_cart_summary']
ARMS=['react','rule','discover','btm_structure']
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True).encode()).hexdigest()
def setup(root,n):
    # Trusted simulator only. No task object or private path is returned to policy.
    task=json.loads(next((root/'benchmarks/ToolMaze/data/perturbed_tasks/c3').glob('*'+n+'_P2.json')).read_text())
    user='u_alice' if n=='015' else 'user_123';failed='get_recommendations_popularity' if n=='015' else 'get_recommendations_collaborative'
    engine=ExecutionEngine(task,None)
    engine.tool_executor=ProjectionExecutor(engine.tool_executor,'reservation_projection_v1')
    arguments={'product_id':'p_sony_xm5_blk','category':'electronics','user_id':user}
    receipt,_=engine._intercept_tool_call(failed,arguments)
    if 'error' not in receipt:raise ValueError('Expected existing P2 error not restored')
    visible={'user_id':user,'product_id':'p_sony_xm5_blk','quantity':1,'category':'electronics','failed_tool':failed,'failed_arguments':arguments,'receipt':receipt,'desired':'p_sony_xm5_slv' if n=='018' else None}
    return engine,visible

def initial(loader,public,arm):
    tools={k:copy.deepcopy(loader.tools[k]) for k in NAMES}
    for t in tools.values():
        spec=t['paradigms']['function_call']['spec'];spec['description']+=' Public returned fields: '+', '.join(t['outputs'])
    inp={k:public[k] for k in ('product_id','quantity','category','user_id')}
    contracts={k:v for k,v in rd.load_contracts().items() if k in NAMES}
    d=rd.Deriver(contracts,{'beam':200});start=time.perf_counter();cand=d.candidates((public['failed_tool'],),list(inp),k=5);search=time.perf_counter()-start
    # The model selects all subsequent actions/arguments; no executable recipe injected.
    common=('Continue after this actual failed recommendation call. Remaining obligation: select an available recommended alternative to the original product and create exactly one new reservation of quantity 1. '
       'Do not buy, confirm an order, or add to cart. Verify the selected product stock before reserving and after reserving using get_stock_level, and report the reserved product and quantity. '
       'The session inventory query counts direct holds and hold_best_recommendation effects. Repeated holds consume stock again; a success receipt alone is not proof of sufficient stock. '
       'All facts and arguments must come from this task or actual feedback. '+json.dumps(public))
    if arm=='rule':common+=' Rule guidance: try the first contract-compatible fallback candidate '+json.dumps(cand[:1])+'. Check task semantics, arguments and before/after stock; reject insufficient stock. Guidance is not an executed action.'
    if arm=='discover':common+=' Public-contract search candidates for replacing the failed recommendation step: '+json.dumps(cand)+'. Decide which fits the same remaining obligation; discover and execute all remaining steps yourself. Check real results and stock changes.'
    if arm=='btm_structure':common+=' Manual fallback map: failed recommendation provider -> get_recommendations; then select_recommendation -> hold_inventory, or use hold_best_recommendation. Recoverability statistics: unknown, support=0. Retry only with meaningful evidence, avoid repeated effects, verify before and after writes; stop only when no legal path remains. This is BTM structural guidance, no fitted posterior evidence.'
    return common,tools,search,cand

def evaluate(engine,start,public,agent_events):
    verify=runner('reservation_projection_v1');verify.phase='independent_acceptance'
    holds=[r for r in engine.context.history[start:] if r.tool_name in ('hold_inventory','hold_best_recommendation') and 'error' not in r.output]
    if len(holds)!=1:return {'business_success':False,'strict_success':False,'reason':'expected exactly one new hold','acceptance_costs':{}}
    hold=holds[0];pid=hold.output.get('product_id');quantity=hold.output.get('quantity')
    prefix=copy.deepcopy(engine.context);prefix._inner.history=copy.deepcopy(engine.context.history[:start]);prefix._inner.data={}
    before=call(verify,prefix,'get_stock_level',{'product_id':pid});after=call(verify,copy.deepcopy(engine.context),'get_stock_level',{'product_id':pid})
    recommended=(hold.tool_name=='hold_best_recommendation' and hold.output.get('recommended_product_id')==pid and hold.arguments.get('product_id')==public['product_id']) or any(h.tool_name.startswith('get_recommendations') and h.output.get('original_product_id')==public['product_id'] and any(x.get('id')==pid and x.get('stock',0)>=1 for x in h.output.get('similar_products',[])) for h in engine.context.history[start:])
    business=(recommended and pid!=public['product_id'] and quantity==1 and before.get('stock',-1)-after.get('stock',-1)==1 and (not public['desired'] or pid==public['desired']))
    queries=[e for e in agent_events if e['tool']=='get_stock_level' and e['arguments'].get('product_id')==pid and 'stock' in e['output']]
    holdindex=next((i for i,e in enumerate(agent_events) if e['tool'] in ('hold_inventory','hold_best_recommendation') and 'error' not in e['output']),-1)
    seenbefore=any(i<holdindex and e['tool']=='get_stock_level' and e['arguments'].get('product_id')==pid and e['output'].get('stock',-1)>=1 for i,e in enumerate(agent_events))
    seenafter=any(i>holdindex and e['tool']=='get_stock_level' and e['arguments'].get('product_id')==pid and 'stock' in e['output'] for i,e in enumerate(agent_events))
    legal=all('error' not in e['output'] and e['tool'] not in ('add_to_cart','add_best_recommendation_to_cart') for e in agent_events)
    return {'business_success':bool(business),'strict_success':bool(business and seenbefore and seenafter and legal),'agent_verified':seenbefore and seenafter,'reason':'local reservation only','before':before,'after':after,'acceptance_costs':verify.costs}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();a.out.mkdir(exist_ok=False,parents=True)
    render=tokenizer_renderer(a.root/'models'/MODEL);loader=PublicLoader();prepared=[]
    for n in ('015','018'):
        for arm in ARMS:
            engine,public=setup(a.root,n);text,tools,search,cand=initial(loader,public,arm)
            agent=VLLMAgent(MODEL,'http://127.0.0.1:8000/v1',temperature=0,max_tokens=6144,request_timeout=180);agent.initialize(text,tools)
            initial_messages=copy.deepcopy(agent.messages)+[{'role':'user','content':text}];_,tokens=render(initial_messages,agent.tools)
            if tokens+6144>32768:raise ValueError('Initial context overflow')
            prepared.append({'checkpoint':n,'arm':arm,'public':public,'messages':initial_messages,'tools':agent.tools,'tokens':tokens,'sha256':digest({'messages':initial_messages,'tools':agent.tools}),'search_seconds':search,'candidates':cand})
    (a.out/'freeze.json').write_text(json.dumps({'commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'plan':prepared,'temperature':0,'max_tokens':6144,'cap':8,'seed':[600001,600002]},indent=2))
    summaries=[]
    for p in prepared:
        n,arm=p['checkpoint'],p['arm'];folder=a.out/(n+'-'+arm);folder.mkdir();engine,public=setup(a.root,n);start=len(engine.context.history)
        agent=VLLMAgent(MODEL,'http://127.0.0.1:8000/v1',temperature=0,max_tokens=6144,request_timeout=180);agent.tools=p['tools'];agent.messages=copy.deepcopy(p['messages'])
        backend=agent.client.with_options(max_retries=0).chat.completions.create;requests=[];events=[];halt=False
        def create(**kw):
            nonlocal halt
            if halt or len(requests)>=8:raise RuntimeError('Episode request stopped')
            _,count=render(kw['messages'],kw['tools'])
            if count+6144>32768:halt=True;raise RuntimeError('Context capacity')
            kw['seed']=600001 if n=='015' else 600002;row={'request':copy.deepcopy(kw),'rendered_tokens':count};requests.append(row);t=time.perf_counter()
            try:
                response=backend(**kw);row['response']=response.model_dump(mode='json')
                msg=response.choices[0].message
                if response.choices[0].finish_reason=='length' or (not msg.tool_calls and not msg.content):halt=True
                return response
            except Exception as exc:row['error']=repr(exc);halt=True;raise
            finally:
                row['seconds']=time.perf_counter()-t
                with (folder/'requests.jsonl').open('a') as stream:stream.write(json.dumps(row)+'\n')
        agent.client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        answer=None
        for _ in range(8):
            action=agent.step()
            if action.type!='tool_call':answer=action.content;break
            if action.tool_name not in NAMES:out={'error':'Tool not allowed'}
            else:out,_=engine._intercept_tool_call(action.tool_name,action.arguments)
            events.append({'tool':action.tool_name,'arguments':action.arguments,'output':copy.deepcopy(out)})
            agent.receive_tool_result(action.tool_name,out)
            if halt:break
        score=evaluate(engine,start,public,events)
        score['strict_success']=score['strict_success'] and bool(answer) and not halt
        result={'checkpoint':n,'arm':arm,'events':events,'answer':answer,'requests':len(requests),'halted':halt,'usage':[x.get('response',{}).get('usage') for x in requests],**score}
        (folder/'result.json').write_text(json.dumps(result,indent=2));summaries.append(result|{'events':'see per-episode result.json'})
        (a.out/'summary.json').write_text(json.dumps(summaries,indent=2))
    (a.out/'completed.json').write_text(json.dumps({'episodes':8,'requests':sum(x['requests'] for x in summaries)}))
if __name__=='__main__':main()
