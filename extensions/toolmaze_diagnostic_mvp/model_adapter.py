"""Strict recorded Qwen tool decisions using the existing VLLMAgent client."""
import copy
import json
from pathlib import Path
import time

from .environment import json_copy
from evaluation.agents.vllm_agent import VLLMAgent

MODEL_CONFIG=json.loads(Path(__file__).with_name('qwen_config.json').read_text())
SYSTEM="""You are resuming an interrupted workflow immediately after a tool failure.
Complete the workflow while minimizing the environment costs stated in the observation.
Choose exactly one of the provided zero-argument tools: retry, switch, or diagnose.
Background tool descriptions explain the workflow but are not directly callable here.
The executor expands retry and switch into valid workflow calls with actual data bindings.
In this controlled environment, the hidden failure is either transient (the next valid retry succeeds) or persistent (valid retries continue to fail). Switching can complete the alternative workflow. The prior and all action prices are provided in the observation.
Diagnose accurately reports whether a valid retry can recover. It costs the stated price on every call and does not itself complete the workflow. Retry outcomes also provide information.
Do not assume a particular hidden state. Do not invent results. After a tool response, decide again if the workflow is incomplete. While incomplete, respond with a single tool call, not a final text answer."""
INTERFACE_INSTRUCTION="Interface check only: call diagnose once before any recovery action. After receiving its response, choose a recovery action yourself and complete the workflow."
TOOLS=[{'type':'function','function':{'name':name,'description':description,
        'parameters':{'type':'object','properties':{},'additionalProperties':False}}}
       for name,description in (
           ('retry','Retry the failed operation once. On success the original workflow is completed automatically.'),
           ('switch','Complete the alternative workflow automatically.'),
           ('diagnose','Pay the stated diagnostic price and accurately learn whether a valid retry can recover.'))]


class ProtocolFailure(RuntimeError):
    pass


def public_model_view(view):
    value=json_copy(view)
    value['actions']={k:v for k,v in value['actions'].items() if k in ('retry','switch','diagnose')}
    text=json.dumps(value,ensure_ascii=False)
    for forbidden in ('perturbation_mode','perturbation_profile','perturbation_status','valid_paths',
                      'execution_trace','source_path','raw_output','"P1"','"P2"'):
        if forbidden in text:
            raise ProtocolFailure('information_leak:'+forbidden)
    return value


def parse_action(payload):
    choices=payload.get('choices',[])
    if len(choices)!=1:
        raise ProtocolFailure('invalid_choice_count')
    if choices[0].get('finish_reason')=='length':
        raise ProtocolFailure('output_length_limit')
    message=choices[0].get('message') or {}
    calls=message.get('tool_calls') or []
    if not calls:
        raise ProtocolFailure('premature_text_or_empty_response')
    if len(calls)!=1:
        raise ProtocolFailure('multiple_tool_calls')
    call=calls[0]; function=call.get('function') or {}
    if call.get('type')!='function' or not call.get('id') or function.get('name') not in ('retry','switch','diagnose'):
        raise ProtocolFailure('invalid_tool_call')
    try:
        arguments=json.loads(function.get('arguments','{}'))
    except (ValueError,TypeError) as exc:
        raise ProtocolFailure('invalid_arguments_json') from exc
    if arguments!={}:
        raise ProtocolFailure('nonempty_arguments')
    return function['name']


class RecordedModelPolicy:
    def __init__(self, interface_check=False, client=None):
        c=MODEL_CONFIG
        self.agent=VLLMAgent(model=c['model'],base_url=c['base_url'],api_key='EMPTY',
             temperature=c['temperature'],max_tokens=c['max_tokens'],request_timeout=c['timeout_seconds'])
        self.agent.client=client if client is not None else self.agent.client.with_options(max_retries=0)
        self.agent.initialize('',{'function_call':TOOLS})
        self.agent.messages[0]['content']=SYSTEM
        self.interface_check=interface_check
        self.started=False

    def request(self, view, turn):
        legal=public_model_view(view)
        if not self.started:
            content={'observation':legal}
            if self.interface_check: content['interface_check_instruction']=INTERFACE_INSTRUCTION
            self.agent.messages.append({'role':'user','content':json.dumps(content,ensure_ascii=False,sort_keys=True)})
            self.started=True
        return {'model':MODEL_CONFIG['model'],'messages':copy.deepcopy(self.agent.messages),
                'tools':copy.deepcopy(TOOLS),'temperature':MODEL_CONFIG['temperature'],
                'max_tokens':MODEL_CONFIG['max_tokens'],'seed':MODEL_CONFIG['seed']+turn,
                'parallel_tool_calls':False,'tool_choice':'auto','timeout':MODEL_CONFIG['timeout_seconds']}

    def choose(self,view,turn,record):
        request=self.request(view,turn)
        record({'event':'request','turn':turn,'request':request})
        start=time.perf_counter()
        try:
            response=self.agent.client.chat.completions.create(**request)
            payload=response.model_dump(mode='json')
        except Exception as exc:
            record({'event':'request_error','turn':turn,'latency_seconds':time.perf_counter()-start,'error':repr(exc),'usage':None})
            raise ProtocolFailure('model_request_error') from exc
        elapsed=time.perf_counter()-start
        record({'event':'response','turn':turn,'latency_seconds':elapsed,'response':payload})
        action=parse_action(payload)
        message={k:v for k,v in payload['choices'][0]['message'].items() if v is not None}
        self.agent.messages.append(message)
        record({'event':'parsed_action','turn':turn,'action':action})
        return action

    def feedback(self,action,view,record):
        legal=public_model_view(view)
        self.agent.receive_tool_result(action,legal)
        record({'event':'tool_feedback','action':action,'message':copy.deepcopy(self.agent.messages[-1])})
