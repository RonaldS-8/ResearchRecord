"""Development comparison; policies consume only a projected public envelope."""
import argparse
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import re
import time

import jsonschema
import yaml
from openai import OpenAI
from evaluation.core.sandbox import InferenceContext
from tools.plugins import create_reminder, express_checkout, hold_best_recommendation, schedule_meeting
from extensions.toolmaze_recovery import gate50 as pub
from extensions.toolmaze_recovery.run import MODEL

ROOT = Path(__file__).resolve().parents[2]
CASES = ('start', 'end', 'original', 'recommended', *pub.WORLDS)
METHOD = """Decide from the public record. Output one JSON object:
{"remaining":"specific user obligation","commit_state":"unknown|absent|confirmed|not_applicable",
"tool":"advertised name or finish","arguments":{},"answer":"final text if finished"}.
For values from receipts use {"$ref":"history index/path"} e.g. {"$ref":"0/content"}
or {"$ref":"2/publications/0/publication_id"}. Indices start at zero and paths start at the result.
Use literals for user-supplied values. When prior commitment is unknown, use public read-only evidence
before another side effect. After each result reconsider what remains. Finish explicitly."""


@lru_cache
def cards():
    return {t['name']: t['paradigms']['function_call']['spec']
            for name in ('source','processor','action')
            for t in yaml.safe_load((ROOT/f'benchmarks/ToolMaze/tools/definitions/{name}.yaml').read_text())['tools']}


def event(tool,args,result):
    return dict(tool=tool,arguments=args,result=result)


def setup(case):
    if case in pub.WORLDS:
        session=pub.checkpoint(case)
        env=session.public()
        specs=[t['paradigms']['function_call']['spec'] for t in env['tools']]
        history=[event(e['tool'],e['arguments'],e['result']) for e in session.events]
        view=dict(task=env['task'],contracts=specs,history=history,candidates=[],prices=env['prices'])
        return view,session.call,session
    if case in ('start','end'):
        src,dst=schedule_meeting,create_reminder
        args=dict(title='Review',start_time='2026-11-19 10:00',end_time='2026-11-19 11:00')
        task=f'Create exactly one reminder titled Meeting reminder at the {case} of the Review meeting.'
    else:
        src,dst=hold_best_recommendation,express_checkout
        args=dict(product_id='p_sony_xm5_blk',quantity=1,user_id='user_01')
        task=f'Use express checkout once for one unit of the {case} product for user_01.'
    context=InferenceContext()
    receipt=src.execute(args,context)
    rows=json.loads((ROOT/'docs/evidence/2_013/comparison.json').read_text())['rows']
    candidates=[{k:r[k] for k in ('source','field','target','parameter','author')} for r in rows
                if r['source']==src.TOOL_NAME and r['target']==dst.TOOL_NAME and r['author'] in ('strong-edge','weak-edge')]
    view=dict(task=task,contracts=[cards()[dst.TOOL_NAME]],history=[event(src.TOOL_NAME,args,receipt)],
              candidates=candidates,source_contract=cards()[src.TOOL_NAME],prices={})
    return view,lambda name,params:dst.execute(params,context),None


def bind(value,history):
    if isinstance(value,dict) and set(value)=={'$ref'}:
        index,*path=value['$ref'].split('/')
        if not index.isdecimal() or not path:
            raise ValueError('Invalid receipt reference')
        item=history[int(index)]['result']
        if 'error' in item:
            raise ValueError('Cannot bind a failed receipt')
        for key in path:
            item=item[int(key)] if isinstance(item,list) and key.isdecimal() else item[key]
        return item
    if isinstance(value,dict):
        return {k:bind(v,history) for k,v in value.items()}
    if isinstance(value,list):
        return [bind(v,history) for v in value]
    return value


def business_rule(view):
    h=view['history']
    if view['candidates']:
        if len(h)>1:
            return 'finish',{},'Finished.' if 'error' not in h[-1]['result'] else 'Blocked: rejected.'
        words=set(re.findall(r'[a-z]+',view['task'].lower()))
        ranked=sorted(((len(words & set(r['field'].split('_'))),r['field'],r) for r in view['candidates']),reverse=True)
        if ranked[0][0]==0 or len(ranked)>1 and ranked[0][0]==ranked[1][0]:
            return 'finish',{},'Blocked: ambiguous binding.'
        _,field,r=ranked[0]
        # Task fixture supplies the common scalar defaults; the object/time comes from the selected receipt.
        args={'title':'Meeting reminder'} if r['target']==create_reminder.TOOL_NAME else {'user_id':h[0]['arguments']['user_id'],'quantity':h[0]['arguments']['quantity']}
        args[r['parameter']]=h[0]['result'][field]
        return r['target'],args,''
    first=h[0]['result']
    write={k:first[k] for k in ('record_id','content','evidence_ref')}
    last=h[-1]['result']
    if 'error' in last:
        return pub.LOOKUP,{'record_id':first['record_id']},''
    if h[-1]['tool']==pub.LOOKUP:
        items=[p for p in last['publications'] if p['content']==first['content'] and p['status']=='active']
        if not items and not last['publications']:
            return pub.ALTWRITE,write,''
        if len(items)!=1:
            return 'finish',{},'Blocked: conflicting published state.'
        return pub.VERIFY,{'publication_id':items[0]['publication_id']},''
    if h[-1]['tool']==pub.VERIFY:
        return 'finish',{},'Published and verified.'
    if 'pending_publication_ref' in last:
        return pub.CONFIRM,{'record_id':first['record_id'],'pending_publication_ref':last['pending_publication_ref']},''
    return pub.VERIFY,{'publication_id':last['publication_id']},''


def decide(client,arm,view,log):
    if arm=='rule':
        return business_rule(view)
    messages=[dict(role='system',content=METHOD if arm=='method' else 'Complete the user request using the advertised tools and public history. Finish with a final answer.'),
              dict(role='user',content=json.dumps(view))]
    request=dict(model=MODEL,messages=messages,temperature=0,seed=201501,max_tokens=4096)
    if arm=='direct':
        request.update(tools=[dict(type='function',function=s) for s in view['contracts']],parallel_tool_calls=False)
    start=time.monotonic()
    response=client.chat.completions.create(**request)
    log.append(dict(request=request,response=response.model_dump(),seconds=time.monotonic()-start))
    choice=response.choices[0]
    if choice.finish_reason=='length':
        raise ValueError('Truncated decision')
    msg=choice.message
    if arm=='direct':
        if not msg.tool_calls:
            return 'finish',{},msg.content or ''
        if len(msg.tool_calls)!=1:
            raise ValueError('Expected one tool')
        fn=msg.tool_calls[0].function
        return fn.name,json.loads(fn.arguments),''
    plan=json.loads((msg.content or '').strip().removeprefix('```json').removesuffix('```').strip())
    if not plan.get('remaining') or plan.get('commit_state') not in ('unknown','absent','confirmed','not_applicable'):
        raise ValueError('Missing obligation or commitment assessment')
    name=plan['tool']
    if plan['commit_state']=='unknown' and name!='finish':
        spec=next((s for s in view['contracts'] if s['name']==name),{})
        if not re.search(r'^(read|list|get|query|lookup)\b|read-only',spec.get('description',''),re.I):
            raise ValueError('Commit state unknown; seek read-only evidence')
    return name,bind(plan.get('arguments',{}),view['history']),plan.get('answer','')


def episode(case,arm,client):
    view,call,session=setup(case)
    prefix=len(view['history'])
    base=deepcopy(view)
    specs={s['name']:s for s in view['contracts']}
    log,errors=[],[]
    answer=''
    start=time.monotonic()
    for turn in range(7):
        count=len(view['history'])-prefix
        view.update(remaining_calls=5-count,remaining_decisions=7-turn,feedback=errors[-1:])
        try:
            name,args,answer=decide(client,arm,view,log)
            if name=='finish':
                break
            if count>=5 or name not in specs:
                raise ValueError('Budget exhausted or unadvertised tool')
            jsonschema.validate(args,specs[name]['parameters'])
            result=call(name,args)
            view['history'].append(event(name,args,result))
        except (ValueError,IndexError,KeyError,TypeError,jsonschema.ValidationError) as exc:
            errors.append(str(exc)[:240])
    suffix=view['history'][prefix:]
    if session:
        grade=pub.evaluate(session,answer)
        grade.pop('events')
        grade['durable_state']='simulator ledger'
    else:
        param='datetime' if case in ('start','end') else 'product_id'
        key={'start':'start_time','end':'end_time','original':'original_product_id','recommended':'recommended_product_id'}[case]
        expected=view['history'][0]['result'][key]
        values=[e['result'].get(param) for e in suffix if 'error' not in e['result']]
        grade=dict(expected=expected,actual=values,receipt_match=values==[expected],
                   strict_success=None,durable_state='unknown',write_attempts=len(suffix),readbacks=0)
    return dict(public_prefix=base,actions=suffix,answer=answer,errors=errors,grade=grade,requests=log,
                wall_seconds=time.monotonic()-start)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('output',type=Path)
    parser.add_argument('--cpu',action='store_true')
    args=parser.parse_args()
    args.output.mkdir(exist_ok=False)
    client=None if args.cpu else OpenAI(base_url='http://127.0.0.1:8010/v1',api_key='local',max_retries=0,timeout=120)
    assert setup('C')[0]==setup('T')[0]==setup('P')[0]
    assert bind({'$ref':'0/x/0/y'},[{'result':{'x':[{'y':'ok'}]}}])=='ok'
    for case in CASES:
        for arm in (('rule',) if args.cpu else ('direct','rule','method')):
            result=episode(case,arm,client)
            (args.output/f'{case}-{arm}.json').write_text(json.dumps(result,indent=2))
            print(case,arm,result['grade'].get('receipt_match',result['grade']['strict_success']),flush=True)
            if args.cpu:
                assert result['grade'].get('receipt_match',result['grade']['strict_success'])


if __name__=='__main__':
    main()
