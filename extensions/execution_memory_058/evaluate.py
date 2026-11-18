"""Isolated post-hoc truth comparison and summary; never feeds runner or memory."""
import collections,hashlib,json,sys
from pathlib import Path
root=Path('/home/ubuntu/Song/Agent');out=root/'results/058-execution-memory-01'
r=json.loads((out/'results.json').read_text());rows=[]
for c in r['cases']:
    p=next((root/'benchmarks/ToolMaze/data/perturbed_tasks/c3').glob(c['context']+'_P0.json'))
    task=json.loads(p.read_text());route=[x[0] for x in c['plan']]
    listed=any(any(v['tools'][i:i+len(route)]==route for i in range(len(v['tools'])-len(route)+1)) for v in task['valid_paths'])
    # Only independent facts: executor error, explicit wrong-value counterexamples;
    # remaining order/invoice persistence has no reference label and remains unknown.
    reference='incorrect' if c['candidate'] in ('wrong_original','wrong_email','overstock') else 'correct_local' if c['scope']=='selection' else 'unknown'
    rows.append({k:c[k] for k in ('context','scope','candidate','B0','B1','M')}|{'exact_segment_in_valid_paths':listed,'reference':reference,'receipt':c['evidence']['receipt']})
counts={}
for judge in ('B0','B1','M'):
    totals=collections.Counter()
    for x in rows:
        action=x[judge] if judge=='M' else 'accept' if x[judge] else 'reject'
        ref=x['reference']
        if action=='unknown':totals['unknown']+=1
        elif ref=='unknown':totals['unverified_accept' if action=='accept' else 'unverified_reject']+=1
        elif action=='accept':totals['correct_accept' if ref=='correct_local' else 'false_accept']+=1
        else:totals['false_reject' if ref=='correct_local' else 'correct_reject']+=1
    counts[judge]=dict(totals)
summary={'cases':rows,'counts':counts,'costs':r['costs'],'reuse':{k:v for k,v in r['reuse'].items() if k!='trace'},'native_state':{k:{s:v[s]['outputs'][-1] for s in ('before','held','after','fresh')} for k,v in r['state_audit'].items()},'results_sha256':hashlib.sha256((out/'results.json').read_bytes()).hexdigest(),'notes':['Manual counterexamples and local obligation labels, not blind independent ground truth.','Read valid_paths only in this evaluator after execution; exact segment membership is not semantic correctness.']}
(out/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
