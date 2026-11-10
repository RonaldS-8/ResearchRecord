import copy
import unittest
from types import SimpleNamespace

from extensions.toolmaze_diagnostic_mvp.environment import RecoverySession
from extensions.toolmaze_diagnostic_mvp.model_adapter import RecordedModelPolicy, ProtocolFailure, parse_action, public_model_view


def response(action='diagnose',args='{}'):
    return {'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
        'reasoning_content':'Recorded reasoning','tool_calls':[{'id':'a','type':'function','function':{'name':action,'arguments':args}}]}}],
        'usage':{'prompt_tokens':10,'completion_tokens':20,'total_tokens':30}}


class FakeClient:
    def __init__(self,payload):
        self.payload=payload; self.requests=[]
        self.chat=SimpleNamespace(completions=SimpleNamespace(create=self.create))
    def create(self,**kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return SimpleNamespace(model_dump=lambda **_:copy.deepcopy(self.payload))


class ModelAdapterTests(unittest.TestCase):
    def test_paired_first_requests_identical(self):
        requests=[]
        for mode in ('P1','P2'):
            agent=RecordedModelPolicy(client=FakeClient(response()))
            requests.append(agent.request(RecoverySession('018',mode).view(),0))
        self.assertEqual(requests[0],requests[1])

    def test_recording_and_diagnostic_feedback(self):
        client=FakeClient(response()); agent=RecordedModelPolicy(client=client)
        session=RecoverySession('018','P1'); records=[]
        action=agent.choose(session.view(),0,records.append)
        self.assertEqual(action,'diagnose')
        agent.feedback(action,session.act(action),records.append)
        self.assertEqual([r['event'] for r in records],['request','response','parsed_action','tool_feedback'])
        self.assertEqual(records[1]['response']['usage']['total_tokens'],30)
        self.assertIn('Recorded reasoning',str(records[1]))
        self.assertEqual(agent.request(session.view(),1)['seed'],1)
        self.assertEqual(agent.agent.messages[-1]['role'],'tool')
        self.assertEqual(session.audit()['diagnostic_cost'],.25)

    def test_no_parallel_truncation_or_argument_repair(self):
        payload=response(); payload['choices'][0]['message']['tool_calls']*=2
        with self.assertRaises(ProtocolFailure): parse_action(payload)
        for arguments in ('{"x":1}','not json'):
            with self.assertRaises(ProtocolFailure): parse_action(response(args=arguments))

    def test_text_and_truncation_rejected(self):
        payload=response(); payload['choices'][0]['message']['tool_calls']=[]
        with self.assertRaises(ProtocolFailure): parse_action(payload)
        payload=response(); payload['choices'][0]['finish_reason']='length'
        with self.assertRaises(ProtocolFailure): parse_action(payload)

    def test_private_view_rejected(self):
        view=RecoverySession('018','P1').view(); view['raw_output']={'error':'secret'}
        with self.assertRaises(ProtocolFailure): public_model_view(view)

    def test_interface_check_is_separate(self):
        view=RecoverySession('018','P1').view()
        a=RecordedModelPolicy(True,FakeClient(response())).request(view,0)
        b=RecordedModelPolicy(False,FakeClient(response())).request(view,0)
        self.assertIn('Interface check only',a['messages'][-1]['content'])
        self.assertNotIn('Interface check only',b['messages'][-1]['content'])

    def test_request_error_is_logged_without_retry(self):
        client=FakeClient(response())
        def fail(**kwargs):
            client.requests.append(kwargs)
            raise RuntimeError('test transport failure')
        client.chat.completions.create=fail
        agent=RecordedModelPolicy(client=client); records=[]
        with self.assertRaises(ProtocolFailure): agent.choose(RecoverySession('018','P1').view(),0,records.append)
        self.assertEqual(len(client.requests),1)
        self.assertEqual([r['event'] for r in records],['request','request_error'])
        self.assertIsNone(records[-1]['usage'])


if __name__=='__main__': unittest.main()
