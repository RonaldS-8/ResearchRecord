"""Seen publication checkpoints. Only the final evaluator receives the session."""
import json
import sys
import time
from pathlib import Path

import jsonschema
from openai import OpenAI
from extensions.route_recovery.agent_2015 import MODEL, setup, pub, event, bind


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))


def evidence(history):
    rows = []
    for i, e in enumerate(history):
        result = e['result']
        records = result.get('publications', [result])
        for record in records:
            if record.get('publication_id'):
                rows.append(dict(source=i, arguments=e['arguments'], receipt=record))
    return rows


def request(client, payload, trace):
    start = time.monotonic()
    reply = client.chat.completions.create(**payload)
    trace.append(dict(request=payload.copy(), response=reply.model_dump(), seconds=time.monotonic()-start))
    return reply.choices[0]


def run(client, folder, case, arm):
    view, call, session = setup(case)
    history = list(view['history'])
    specs = {s['name']:s for s in view['contracts']}
    messages = [dict(role='system',content='Complete the user request using the advertised tools and public history. Finish with a final answer.'),dict(role='user',content=json.dumps(view))]
    trace, actions, errors = [], [], []
    answer = ''
    for turn in range(7):
        budget = dict(remaining_calls=5-len(actions),remaining_decisions=7-turn)
        if arm=='evidence':
            budget.update(publication_receipts=evidence(history), instruction='Check the object and content against the request. Consider what still needs evidence before the next action.')
        messages.append(dict(role='user',content=json.dumps(budget)))
        choice = request(client, dict(model=MODEL,messages=list(messages),tools=[dict(type='function',function=s) for s in specs.values()],parallel_tool_calls=False,temperature=0,seed=201501,max_tokens=8192), trace)
        msg = choice.message
        if choice.finish_reason=='length':
            errors.append('length'); continue
        if not msg.tool_calls:
            answer=msg.content or ''; break
        messages.append(dict(role='assistant',content=msg.content,tool_calls=[t.model_dump(include={'id','type','function'}) for t in msg.tool_calls]))
        for t in msg.tool_calls:
            try:
                name=t.function.name
                args=json.loads(t.function.arguments)
                jsonschema.validate(args,specs[name]['parameters'])
                if len(actions)>=5: raise ValueError('Call budget exhausted')
                result=call(name,args)
                action=event(name,args,result)
                actions.append(action); history.append(action)
            except (KeyError,ValueError,jsonschema.ValidationError) as exc:
                result={'error':str(exc)}; errors.append(str(exc))
            messages.append(dict(role='tool',tool_call_id=t.id,content=json.dumps(result)))
    grade=pub.evaluate(session,answer)
    save(folder/f'{case}-{arm}.json',dict(actions=actions,grade=grade,answer=answer,requests=trace,errors=errors))
    print(case,arm,grade['strict_success'],flush=True)


def main():
    folder, old=map(Path,sys.argv[1:])
    client=OpenAI(base_url='http://127.0.0.1:8010/v1',api_key='local',max_retries=0,timeout=360)
    frozen=json.loads(old.read_text())['requests'][0]['request']
    view=json.loads(frozen['messages'][1]['content'])
    assert setup('C')[0]==setup('T')[0]==setup('P')[0]
    for limit in (4096,8192):
        trace=[]
        choice=request(client,dict(frozen,max_tokens=limit),trace)
        legal=False
        try:
            plan=json.loads((choice.message.content or '').strip().removeprefix('```json').removesuffix('```'))
            spec=next(s for s in view['contracts'] if s['name']==plan['tool'])
            jsonschema.validate(bind(plan['arguments'],view['history']),spec['parameters'])
            legal=choice.finish_reason!='length'
        except (StopIteration,KeyError,ValueError,TypeError,IndexError,jsonschema.ValidationError): pass
        save(folder/f'diagnostic-{limit}.json',dict(requests=trace,legal_schema_and_binding=legal))
        print('diagnostic',limit,choice.finish_reason,legal,flush=True)
    for case in 'CTP':
        for arm in ('direct','evidence'): run(client,folder,case,arm)


if __name__=='__main__': main()
