"""Paired native function-call runs on two frozen development checkpoints."""
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from extensions.route_recovery import gate_2_009 as p
from extensions.route_recovery.run_2_009 import ToolSession, public_scope
from extensions.route_recovery.audit_2_009 import grade
from extensions.toolmaze_recovery.gate34b import initialize
from extensions.toolmaze_recovery.gate44a import restored
from extensions.toolmaze_recovery.gate42a import evaluate
from extensions.toolmaze_recovery.run import VLLMAgent, MODEL

EXIT = "If unable to complete the task, start your final reply with 'Blocked:' and briefly explain."
ROOT = Path('/home/ubuntu/Song/Agent')


def run(case, arm, out, post_prefix=None, model=MODEL, temperature=0, seed=201701):
    agent = VLLMAgent(model,'http://127.0.0.1:8010/v1',temperature=temperature,max_tokens=8192,request_timeout=300)
    if case in ('M3','M4'):
        session=restored(case)
        initialize(agent,session)
        msg=next(m for m in agent.messages if m['role']=='user')
        assert EXIT in msg['content']
        msg['content']=msg['content'].replace(EXIT,'').rstrip()
        budget=session.call_budget-len(session.events)
        names=['prepare_alternate_publication','confirm_alternate_publication','read_published_record']
    else:
        task=p.TASKS[0]
        cards=p.public_contracts()
        session=ToolSession(task,ROOT/'benchmarks/ToolMaze/data/perturbed_tasks/c3'/f'{task.identifier}.json')
        prompt=p.message(task,session.initial['output'],'00',[])
        agent.initialize(prompt,cards)
        agent.messages.append(dict(role='user',content=prompt))
        msg=agent.messages[-1]
        budget=p.MAX_CALLS
        names=['get_broker_balance_ledger_native','create_document_and_alert_from_data']
    msg['content']+=' '+(EXIT if arm=='old' else 'Finish with a final answer.')
    if arm=='names': msg['content']+=' Candidate tools: '+', '.join(sorted(names))+'.'
    if post_prefix is not None:
        agent.messages.append(dict(role="user",content=post_prefix))
    backend=agent.client.with_options(max_retries=0).chat.completions.create
    log=[]
    def create(**payload):
        payload['seed']=seed
        start=time.monotonic()
        reply=backend(**payload)
        log.append(dict(request=json.loads(json.dumps(payload)),response=reply.model_dump(),seconds=time.monotonic()-start))
        return reply
    agent.client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    answer=None
    status='request_budget'
    for i in range(budget+1):
        with public_scope(): action=agent.step()
        if log[-1]['response']['choices'][0]['finish_reason']=='length':
            status='length'; break
        if action.type!='tool_call':
            answer=action.content; status='answered'; break
        if i==budget:
            status='tool_budget'; break
        reply=session.call(action.tool_name,action.arguments)
        agent.receive_tool_result(action.tool_name,reply)
    scores=evaluate(session,answer) if case in ('M3','M4') else grade(task,cards,dict(events=session.events,answer=answer,status=status))
    result=dict(case=case,arm=arm,events=session.events,answer=answer,status=status,scores=scores,requests=log)
    (out/f'{case}-{arm}.json').write_text(json.dumps(result,indent=2))
    print(case,arm,status,scores.get('strict',scores.get('strict_success')),flush=True)


if __name__=='__main__':
    for case in ('M4','002'):
        for arm in ('old','neutral','names'): run(case,arm,Path(sys.argv[1]))
