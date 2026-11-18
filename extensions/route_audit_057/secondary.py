"""Reproduce secondary diagnostics from cloud case records, never modify 055."""
import collections,json
from pathlib import Path
r=Path('/home/ubuntu/Song/Agent/results');out=r/'057-route-audit-01'
raw=[json.loads(s) for s in (r/'055-route-judge-01/responses.jsonl').read_text().splitlines()]
rows=[json.loads(s) for s in (out/'cases.jsonl').read_text().splitlines()]
by={(x['id'],x['arm']):x for x in raw}
def subseq(a,b):
 it=iter(b);return all(any(x==y for y in it) for x in a)
s={}
for split in ('dev','test'):
 rs=[x for x in rows if x['split']==split];valid=[x for x in rs if x['L_valid'] and x['candidate_pos'] is not None]
 s[split]={'valid_covered_n':len(valid),'valid_covered_hits3':sum(bool(x['L_pos'] and x['L_pos']<=3) for x in valid),'omitted_with_gold_subsequence':sum(any(subseq(x['gold'],p) for p in by[x['id'],'L']['routes'] or []) for x in rs if x['category']=='omitted'),'missing_and_length':sum(x['candidate_pos'] is None and x['L_finish']=='length' for x in rs)}
assert s==json.loads((out/'secondary-summary.json').read_text())
extra={'recorded_reasoning_nonempty':sum(bool(x.get('reasoning')) for x in raw),'truncated_usage':dict(collections.Counter(str((x['usage']['completion_tokens'],(x['usage'].get('completion_tokens_details') or {}).get('reasoning_tokens'),x.get('content'),x.get('reasoning'))) for x in raw if x['finish_reason']=='length')),'secondary':s}
(out/'recording-diagnostics.json').write_text(json.dumps(extra,indent=2))
print(json.dumps(extra,indent=2))
