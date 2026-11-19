"""Evaluator-only paired probes; inputs are frozen historical development cases."""
import json
from pathlib import Path

from evaluation.core.sandbox import InferenceContext
from tools.plugins import create_reminder, express_checkout, hold_best_recommendation, schedule_meeting
from extensions.toolmaze_recovery import gate50


def bindings(source, target, param, args, static, goals):
    receipt = source.execute(args, InferenceContext())
    assert 'error' not in receipt, receipt
    rows = []
    for r in static:
        if (r['source'], r['target'], r['parameter']) != (source.TOOL_NAME, target.TOOL_NAME, param):
            continue
        field = r['field']
        other = {'title': 'Meeting reminder'} if target is create_reminder else {'quantity': 1,'user_id':'user_01'}
        response = target.execute({**other, param: receipt[field]}, InferenceContext())
        rows.append(dict(field=field, rule=r['rule'], graph=r['author'], response=response,
                         matched={goal: 'error' not in response and response.get(param)==expected
                                  for goal,expected in goals(receipt).items()}))
    return dict(receipt=receipt, rows=rows, durable_state='unknown')


def main():
    static=json.loads(Path('docs/evidence/2_013/comparison.json').read_text())['rows']
    meeting=bindings(schedule_meeting, create_reminder,'datetime',
                     dict(title='Review',start_time='2026-11-19 10:00',end_time='2026-11-19 11:00'),static,
                     lambda _:dict(start='2026-11-19 10:00',end='2026-11-19 11:00'))
    shopping=bindings(hold_best_recommendation,express_checkout,'product_id',
                      dict(product_id='p_sony_xm5_blk',quantity=1,user_id='user_01'),static,
                      lambda r:dict(original='p_sony_xm5_blk',recommended=r['recommended_product_id']))
    published={}
    for world in gate50.WORLDS:
        published[world]={}
        for name in gate50.POLICIES:
            result=gate50.play(gate50._policy(name),world)
            published[world][name]={k:v for k,v in result.items() if k!='events'}
            published[world][name]['suffix']=[e['tool'] for e in result['events'][gate50.PREFIX_CALLS:]]
    print(json.dumps(dict(meeting=meeting,shopping=shopping,publication=published),indent=2))


if __name__=='__main__':
    main()
