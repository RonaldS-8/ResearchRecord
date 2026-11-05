import copy
import unittest
from extensions.toolmaze_diagnostic_mvp.environment import CONFIG, RecoverySession
from extensions.toolmaze_diagnostic_mvp.verification import evaluate


def complete(task='018',mode='P1',action='switch',controlled=True):
    env=RecoverySession(task,mode,controlled=controlled)
    env.act(action)
    if not env.view()['done']: env.act('switch')
    return env.audit()


class CompletionTests(unittest.TestCase):
    def test_positive_paths_all_selected_tasks(self):
        for task in CONFIG['tasks']:
            for mode in ('P1','P2'):
                for action in ('retry','switch'):
                    audit=complete(task,mode,action)
                    score=evaluate(task,mode,audit['events'])
                    self.assertTrue(score['legal_success'],(task,mode,action,score))

    def test_skip_branch_step_native_pass_is_rejected(self):
        audit=complete(); events=copy.deepcopy(audit['events'])
        del events[audit['sunk_calls']]
        score=evaluate('018','P1',events)
        self.assertTrue(score['native_pass'])
        self.assertFalse(score['legal_success'])
        self.assertTrue(any(x['issue']=='no_complete_legal_path' for x in score['issues']))

    def test_wrong_parameter_is_rejected(self):
        audit=complete(); events=copy.deepcopy(audit['events'])
        event=events[audit['sunk_calls']]
        key=next(iter(event['arguments'])); event['arguments'][key]='WRONG_ENTITY'
        score=evaluate('018','P1',events)
        self.assertFalse(score['legal_success'])
        self.assertTrue(any(x['issue']=='binding_value_mismatch' for x in score['issues']))

    def test_wrong_nested_object_is_rejected(self):
        audit=complete('020'); events=copy.deepcopy(audit['events'])
        changed=False
        for event in events[audit['sunk_calls']:]:
            for key,value in event['arguments'].items():
                if isinstance(value,(dict,list)):
                    event['arguments'][key]={'forged':True}; changed=True; break
            if changed: break
        self.assertTrue(changed,'Fixture must contain a bound object')
        self.assertFalse(evaluate('020','P1',events)['legal_success'])

    def test_forged_output_is_rejected(self):
        audit=complete(); events=copy.deepcopy(audit['events'])
        events[-1]['raw_output']['forged']=True; events[-1]['output']['forged']=True
        self.assertFalse(evaluate('018','P1',events)['legal_success'])

    def test_consumer_before_producer_is_rejected(self):
        audit=complete(); events=copy.deepcopy(audit['events']); i=audit['sunk_calls']
        events[i],events[i+1]=events[i+1],events[i]
        self.assertFalse(evaluate('018','P1',events)['legal_success'])

    def test_duplicate_call_ids_are_rejected(self):
        audit=complete(); events=copy.deepcopy(audit['events']); events[-1]['call_id']=events[0]['call_id']
        self.assertFalse(evaluate('018','P1',events)['legal_success'])

    def test_original_error_control_and_failed_stop(self):
        audit=complete(controlled=False)
        self.assertTrue(evaluate('018','P1',audit['events'],controlled=False)['legal_success'])
        env=RecoverySession('018','P2'); env.act('retry'); env.act('stop')
        self.assertFalse(evaluate('018','P2',env.audit()['events'])['legal_success'])


if __name__=='__main__': unittest.main()
