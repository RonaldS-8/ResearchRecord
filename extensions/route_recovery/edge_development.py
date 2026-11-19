"""Shared public-schema candidates and 2_013 development comparison."""
import argparse
import json
import re
import time
from pathlib import Path

import yaml


def compatible(outputs, target):
    return sorted(name for name, schema in outputs.items()
                  if schema.get('type') and (schema['type'] == target.get('type')
                  or (schema['type'], target.get('type')) == ('integer', 'number')))


def main():
    from sentence_transformers import SentenceTransformer
    from .reproduce_in_n_out import LocalModel, load_module

    parser = argparse.ArgumentParser()
    for name in ('upstream', 'embedding', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=False)
    root = Path('benchmarks/ToolMaze/tools/definitions')
    cards = {t['name']: t['paradigms'] for family in ('source','processor','action')
             for t in yaml.safe_load((root / (family + '.yaml')).read_text())['tools']}
    inventory = json.loads(Path('docs/evidence/2_012/inventory.json').read_text())
    queries = sorted({(r['source'], r['target'], r['parameter']) for r in inventory['edges']
                      if r['field'] and r['field'] != r['parameter']})
    emb = SentenceTransformer(str(args.embedding), device='cpu')
    rows = []
    started = time.monotonic()
    for source, target, param in queries:
        source_doc = cards[source]['mcp']['prompt_description']
        outputs = cards[source]['mcp']['output_schema']
        spec = cards[target]['function_call']['spec']
        schema = spec['parameters']['properties'][param]
        target_text = ' '.join((param, schema.get('description',''),spec['description']))
        for field in compatible(outputs, schema):
            source_text = field + ' ' + source_doc
            vectors = emb.encode([source_text.replace('_',' '),target_text.replace('_',' ')], normalize_embeddings=True)
            src = set(field.split('_'))
            dst = set(re.findall(r'[a-z]+',target_text.lower()))
            score = .75 * float(vectors[0] @ vectors[1]) + .25 * len(src & dst)/len(src)
            rows.append(dict(source=source,target=target,parameter=param,field=field,
                             source_doc=source_doc,target_doc=spec['description'],input_schema=schema,
                             output_schema=outputs[field],rule_score=score))
    for row in rows:
        peers = sorted((r['rule_score'] for r in rows if (r['source'],r['target'],r['parameter']) ==
                        (row['source'],row['target'],row['parameter'])),reverse=True)
        row['rule'] = ('unknown' if peers[0]<.45 or len(peers)>1 and peers[0]-peers[1]<.05
                       else 'accept' if row['rule_score']==peers[0] else 'reject')
    (args.output/'candidates.json').write_text(json.dumps(dict(queries=queries,rows=rows,
                                                   cpu_seconds=time.monotonic()-started),indent=2))
    author=load_module('author',args.upstream/'src/graph_construction/test_zero-shot_models.py')
    model=LocalModel('http://127.0.0.1:8010/v1','Qwen3-4B-Thinking-2507',args.output,request_limit=48)
    author.openai_client=model
    model.phase='development-edge'
    prefix=json.loads((args.upstream/'data/nestful/graph_construction/test_data.json').read_text())['input'][0].split('Source API Information:',1)[0]
    for row in rows:
        if model.requests>=48:
            break
        prompt=(prefix+'\nSource API Information:\n'+json.dumps(dict(name=row['source'],description=row['source_doc'],output_params={row['field']:row['output_schema']}))
                +'\nTarget API Information:\n'+json.dumps(dict(name=row['target'],description=row['target_doc'],input_params={row['parameter']:row['input_schema']}))
                +f"\nPlease classify the edge between:\n{row['source']} (output: {row['field']}) -> {row['target']} (input: {row['parameter']})")
        try:
            result=author.classify_edge(model.model,prompt)
        except TypeError:
            # The upstream parser applies a membership test to null content.
            last=json.loads((args.output/'requests.jsonl').read_text().splitlines()[-1])
            if last['response']['choices'][0]['message']['content'] is not None:
                raise
            result={}
        with (args.output/'predictions.jsonl').open('a') as f:
            print(json.dumps({k:row[k] for k in ('source','field','target','parameter')} | {'author':result}),file=f,flush=True)


if __name__=='__main__':
    main()
