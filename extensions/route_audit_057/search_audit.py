"""Attribution of missing candidates; gold only consumed after public search."""
import json,time,collections
from pathlib import Path
from extensions.toolmaze_recovery import route_discovery as rd
root=Path('/home/ubuntu/Song/Agent'); out=root/'results/057-route-audit-01'
rows=[json.loads(s) for s in (out/'cases.jsonl').read_text().splitlines()]
qs={q['task']+':'+ '-'.join(q['failed']):q for q in rd.task_queries(root/'benchmarks/ToolMaze/data','domain',complexities=('c3',))}
c=rd.load_contracts();subs=rd.substitutes(); results=[];start=time.perf_counter()
for r in rows:
 if r['category']!='candidate_absent':continue
 q=qs[r['id']];d=rd.Deriver({k:c[k] for k in q['pool']},{'beam':200})
 context=sum((d.bag[t] for t in q['failed']),collections.Counter())
 chains=d.chains(q['inputs'],context,avoid=q['failed'])
 # Evaluation starts here, after blind search.
 gold=q['gold'][0]; exact=any(rd.hit(x,gold,subs) for x in chains)
 ranks={arm:next((i+1 for i,x in enumerate(d.rank(q['failed'],q['inputs'],arm,k=len(chains),chains=chains)) if rd.hit(x,gold,subs)),None) for arm in ('B1','D')}
 results.append({'id':r['id'],'group':r['group'],'split':r['split'],'in_search':exact,'rank':ranks,'chains':len(chains)})
result={'n':len(results),'in_search':sum(r['in_search'] for r in results),'by_group':{g:dict(collections.Counter('rank_or_top20_merge' if r['in_search'] else 'search_pruned_or_expansion' for r in results if r['group']==g)) for g in sorted({r['group'] for r in results})},'seconds':time.perf_counter()-start,'cases':results}
(out/'search-audit.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='cases'},indent=2))
