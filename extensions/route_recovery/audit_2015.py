"""Re-execute recorded arguments in new sessions; independently summarize observed costs."""
import hashlib
import json
from pathlib import Path
import sys

from .agent_2015 import CASES, setup
from extensions.toolmaze_recovery import gate50


def main(folder):
    summary={}
    for case in CASES:
        prefix=None
        for arm in ('direct','rule','method'):
            f=folder/f'{case}-{arm}.json'
            data=json.loads(f.read_text())
            view,call,session=setup(case)
            if prefix is None:
                prefix=data['public_prefix']
            assert view==prefix==data['public_prefix']
            actions=data['actions']
            for e in actions:
                assert call(e['tool'],e['arguments'])==e['result']
            g=data['grade']
            if session:
                replay=gate50.evaluate(session,data['answer'])
                assert all(g[k]==replay[k] for k in replay if k!='events')
                passed=g['strict_success']
                cnt=len(session.effects)
                verified=sum(e['tool']==gate50.VERIFY and 'error' not in e['result'] for e in actions)
                value=[x['state']['content'] for x in session.effects]
            else:
                good=[e for e in actions if 'error' not in e['result']]
                if case in ('start','end'):
                    source=view['history'][0]['arguments']
                    expected=source[case+'_time']
                    passed=len(good)==1 and good[0]['result']['datetime']==expected and good[0]['result']['title']=='Meeting reminder'
                else:
                    source=view['history'][0]
                    expected=source['arguments']['product_id'] if case=='original' else source['result']['recommended_product_id']
                    passed=(len(good)==1 and good[0]['result']['product_id']==expected and
                            good[0]['result']['quantity']==1 and good[0]['arguments'].get('user_id')=='user_01')
                cnt=None
                verified=0
                value=g['actual']
            requests=data['requests']
            usages=[r['response']['usage'] for r in requests]
            summary[f.stem]=dict(passed=passed,value=value,durable_writes=cnt,readbacks=verified,
                calls=[e['tool'] for e in actions],requests=len(requests),errors=data['errors'],
                answer_present=bool(data['answer']),input=sum(u['prompt_tokens'] for u in usages),
                output=sum(u['completion_tokens'] for u in usages),
                thinking=sum((u.get('completion_tokens_details') or {}).get('reasoning_tokens') or 0 for u in usages),
                seconds=data['wall_seconds'],fee=[g.get('suffix_execution_fee'),g.get('suffix_diagnostic_fee')],
                sha256=hashlib.sha256(f.read_bytes()).hexdigest())
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main(Path(sys.argv[1]))
