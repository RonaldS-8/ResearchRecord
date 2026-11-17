"""Gate057 CPU attribution. Evaluator truth is never passed to probe()."""
import argparse, collections, hashlib, json, time
from pathlib import Path
from extensions.toolmaze_recovery import route_discovery as rd


def probe(contracts, failed, inputs, candidates, proposed, l_routes, b1):
    d=rd.Deriver(contracts, {'beam':200})
    union=list(dict.fromkeys(tuple(x) for x in candidates+proposed))
    return {'fallback':l_routes if l_routes is not None else b1,
            'union_D':d.rank(tuple(failed),inputs,'D',k=3,chains=union), 'union':union}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',type=Path,required=True); ap.add_argument('--out',type=Path,required=True); a=ap.parse_args()
    a.out.mkdir(parents=True,exist_ok=False); start=time.perf_counter()
    run=a.root/'results/055-route-judge-01'; hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir() if p.is_file()}
    freeze=json.loads((run/'freeze.json').read_text()); responses=[json.loads(s) for s in (run/'responses.jsonl').read_text().splitlines()]; by={(r['id'],r['arm']):r for r in responses}
    contracts=rd.load_contracts(); subs=rd.substitutes(); groups={frozenset(g['paths']):g['id'] for g in rd.load_groups()}
    public={q['task']+':'+ '-'.join(q['failed']):q for q in rd.task_queries(a.root/'benchmarks/ToolMaze/data','domain',complexities=('c3',))}
    rows=[]; timing=0
    for f in freeze['queries']:
        q=public[f['id']]; gold=q['gold'][0]; l=by[f['id'],'L']; p=by[f['id'],'P']; cc=[tuple(x) for x in f['candidates']]
        pos=lambda rr:next((i+1 for i,c in enumerate(rr or []) if rd.hit(c,gold,subs)),None)
        bp=pos(f['b1']); lp=pos(l['routes']); pp=pos(p['routes']); cp=pos(cc)
        d=rd.Deriver({k:contracts[k] for k in q['pool']}); avail=set(q['inputs']); blocked=[]
        for t in gold:
            if not d.satisfied(t,avail): blocked.append(t)
            avail|=set(contracts[t]['outputs'])|{d.obj(t)}
        t0=time.perf_counter(); ex=probe({k:contracts[k] for k in q['pool']},q['failed'],q['inputs'],f['candidates'],p['routes'] or [],l['routes'],f['b1']); timing+=time.perf_counter()-t0
        category='candidate_absent' if cp is None else 'truncated' if l['routes'] is None else 'L_success' if lp and lp<=3 else 'rank_below3' if lp else 'omitted'
        rr=l.get('reasoning') or ''; words=rr.split(); grams=[tuple(words[i:i+8]) for i in range(max(0,len(words)-7))]
        row={'id':f['id'],'split':f['split'],'group':groups.get(frozenset([q['failed'],gold]),'unmapped'),'failed':q['failed'],'gold':gold,'gold_len':len(gold),'pool':len(q['pool']),'candidates':len(cc),'candidate_pos':cp,'B1_pos':bp,'L_pos':lp,'P_pos':pp,'category':category,'gold_blocked_by_contract_rule':blocked,'L_valid':l['routes'] is not None,'L_finish':l['finish_reason'],'L_content_chars':len(l.get('content') or ''),'L_reasoning_chars':len(rr),'L_repeated_8gram_fraction':1-len(set(grams))/len(grams) if grams else 0,'source_lines':{'L':responses.index(l)+1,'P':responses.index(p)+1},'fallback_pos':pos(ex['fallback']),'union_D_pos':pos(ex['union_D']),'union_ceiling':pos(ex['union']) is not None,'tokens':{arm:by[f['id'],arm]['usage'] for arm in ('L','P')}}
        rows.append(row)
    (a.out/'cases.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    def agg(rs):
        c=collections.Counter(r['category'] for r in rs)
        cross={str(k):dict(collections.Counter(('both' if r['B1_pos'] and r['B1_pos']<=k and r['L_pos'] and r['L_pos']<=k else 'B1_only' if r['B1_pos'] and r['B1_pos']<=k else 'L_only' if r['L_pos'] and r['L_pos']<=k else 'neither') for r in rs)) for k in (1,3)}
        valid=[r for r in rs if r['L_valid']]
        return {'n':len(rs),'loss_partition':dict(c),'cross':cross,'valid_n':len(valid),'valid_L_hits':{str(k):sum(bool(r['L_pos'] and r['L_pos']<=k) for r in valid) for k in (1,3)},'scores':{name:{str(k):sum(bool(r[name+'_pos'] and r[name+'_pos']<=k) for r in rs) for k in (1,3)} for name in ('B1','L','P','fallback','union_D')},'union_ceiling':sum(r['union_ceiling'] for r in rs),'contract_blocked':sum(bool(r['gold_blocked_by_contract_rule']) for r in rs),'mean_pool':sum(r['pool'] for r in rs)/len(rs)}
    summary={'split':{s:agg([r for r in rows if r['split']==s]) for s in ('dev','test')},'groups':{s:{g:agg([r for r in rows if r['split']==s and r['group']==g]) for g in sorted({r['group'] for r in rows if r['split']==s})} for s in ('dev','test')},'lengths':{s:{str(n):agg([r for r in rows if r['split']==s and r['gold_len']==n]) for n in sorted({r['gold_len'] for r in rows if r['split']==s})} for s in ('dev','test')},'probe_seconds':timing,'wall_seconds':time.perf_counter()-start,'source_sha256':hashes,'requests':len(responses),'gpu_calls':0}
    assert hashes=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir() if p.is_file()}
    (a.out/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary['split'],indent=2))
if __name__=='__main__': main()
