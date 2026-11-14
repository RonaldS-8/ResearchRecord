"""Post-hoc descriptive audit; no fitting, model calls, score changes or CI claims."""
import argparse,json,hashlib
from pathlib import Path
from collections import defaultdict,Counter
from fractions import Fraction as F

def hashval(x):return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 from extensions.toolmaze_recovery.gate45c import schedule,session
 from extensions.toolmaze_recovery.gate44a import restored,digest
 from extensions.toolmaze_recovery.gate42a import evaluate
 assigned={r['id']:r for r in schedule()};rows=[];groups=defaultdict(list)
 lines=['# Gate45 全部74回合行为时间线','', '独立重放原始实参与评分；无自动纠错、无反事实重评分。完整参数、引用和终答留云端原始文件。','']
 for run in ('045-real-agent-01','045c-training-01','045-stat-01'):
  for folder in sorted((a.root/'results'/run).iterdir()):
   if not folder.is_dir():continue
   r=json.loads((folder/'result.json').read_text());c=json.loads((folder/'config.json').read_text());m=c['mechanism'];arm=c['arm'];training=run=='045c-training-01'
   s=session(assigned[folder.name]) if training else restored(m);cut=len(s.events)
   for t in r['transitions']:s.call(t['tool'],t['arguments'])
   assert all(r[k]==v for k,v in evaluate(s,r.get('answer')).items())
   req=[json.loads(x) for x in (folder/'requests.jsonl').read_text().splitlines()];assert req and not any('error' in q or 'tool_choice' in q['request'] for q in req)
   suffix=r['events'][cut:];actual=suffix[0]['tool'] if suffix else 'stop';primary='success' if r['strict_success'] else 'recovery_decision'
   if r['illegal_calls']:
    bad=[e for e in suffix if e['illegal']];assert len(bad)==1 and bad[0]['arguments']['content']=='Valve A: 12 units; Valve B: 8 units'
    primary='format_exact_match'
   elif not r['strict_success'] and any(e['tool']=='publish_verified_record' and 'publication_id' in e['result'] for e in suffix):primary='continuation_missing_readback'
   early=not r['strict_success'] and primary!='continuation_missing_readback' and (not suffix or m=='M3')
   followed=(actual==arm) if training else (actual==('read_archive_record' if m=='M3' else 'prepare_alternate_publication')) if arm in ('R1','R3') else None
   counts={'input_tokens':sum(q['response']['usage']['prompt_tokens'] for q in req),'output_tokens':sum(q['response']['usage']['completion_tokens'] for q in req),'reasoning_tokens':sum((q['response']['usage'].get('completion_tokens_details') or {}).get('reasoning_tokens',0) or 0 for q in req)}
   assert counts['input_tokens']==r['tokens']['input_tokens'] and counts['output_tokens']==r['tokens']['output_tokens']
   row=dict(run=run,id=folder.name,checkpoint=m,arm=arm,training=training,actual_first=actual,strict=r['strict_success'],obligations=r['obligations_complete'],illegal=r['illegal_calls'],primary=primary,early_stop=early,first_suggestion_followed=followed,calls=len(suffix),binding_accepted=sum(not e['illegal'] for e in suffix),fee=str(sum((F(e['fee']) for e in suffix),F())),prefix_fee=str(sum((F(e['fee']) for e in r['events'][:cut]),F())),sdk=len(req),model_seconds=sum(q['model_seconds'] for q in req),wall_seconds=r['wall_seconds'],initial_tokens=req[0]['rendered_tokens'],behavior_hash=digest([{'tool':e['tool'],'arguments':e['arguments'],'result':e['result']} for e in suffix]),**counts)
   rows.append(row);groups[run,m,arm].append(row)
   sequence=' → '.join('E'+str(e['call'])+' '+e['tool']+(' [非法：正文少末尾句点]' if e['illegal'] else ' [合法服务失败]' if 'error' in e['result'] else ' [接受]') for e in suffix) or '直接终答，无后缀调用'
   explanation={'success':'完整发布及回读通过','recovery_decision':'有公开可行路径时停止，或先消耗恢复关键预算再停止','format_exact_match':'E6选路/真实引用正确，正文少末尾句点被拒；其后停止，未继续业务义务','continuation_missing_readback':'E6发布成功，未执行E7回读即给终答'}[primary]
   lines += ['## '+run+'/'+folder.name,'',f"起点已用{cut}次、剩{6 if m=='M3' else 3}次；信息组/建议：{arm}。",sequence+' → 原始终答。',f"严格/义务={r['strict_success']}/{r['obligations_complete']}；主因={primary}；{explanation}。",f"首建议遵从={followed}（R2/R4无单一建议NA）；绑定={row['binding_accepted']}/{len(suffix)}；非法={row['illegal']}；后缀费={row['fee']}。",f"SDK={len(req)}；输入/输出/推理Token={counts['input_tokens']}/{counts['output_tokens']}/{counts['reasoning_tokens']}（推理已含输出）；模型/端到端秒={row['model_seconds']:.3f}/{row['wall_seconds']:.3f}。",f"证据：云端results/{run}/{folder.name}/result.json、requests.jsonl；参数及回执按E编号逐条可查。",'']
 summary=[]
 for key,g in groups.items():
  sums={k:sum(r[k] for r in g) for k in ('strict','obligations','illegal','early_stop','calls','binding_accepted','sdk','input_tokens','output_tokens','reasoning_tokens','model_seconds','wall_seconds')}
  summary.append(dict(run=key[0],checkpoint=key[1],arm=key[2],n=len(g),**sums,fee=str(sum((F(r['fee']) for r in g),F())),prefix_fee=str(sum((F(r['prefix_fee']) for r in g),F())),unique_behaviors=len({r['behavior_hash'] for r in g}),suggestion_followed=sum(r['first_suggestion_followed'] is True for r in g),suggestion_applicable=sum(r['first_suggestion_followed'] is not None for r in g),primary_counts=dict(Counter(r['primary'] for r in g))))
 assert len(rows)==74 and sum(r['sdk'] for r in rows)==238
 a.output.mkdir(parents=True,exist_ok=False)
 (a.output/'metrics.json').write_text(json.dumps({'analysis':'post-hoc descriptive; repeated seen checkpoints; no causal or task-generalization inference','rows':rows,'groups':summary},indent=2))
 (a.output/'timelines.md').write_text('\n'.join(lines))
 print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
