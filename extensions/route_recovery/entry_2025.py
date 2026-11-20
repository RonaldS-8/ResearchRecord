"""Public-contract policies. Callers supply a fresh, independent probe world."""
import ast
import itertools
import json
import subprocess
import sys
import time
from pathlib import Path

import torch
from openai import OpenAI
from transformers import AutoModel, AutoTokenizer

from .reproduce_in_n_out_m4 import available_receipts, public_parameters
from .run_2019 import select


def build(view, probe_factory, directory, upstream, model_path):
    start = time.monotonic()
    cards, _, outputs = public_parameters(view)
    required = {n: card['parameters']['required'] for n, card in cards.items()}
    available = available_receipts(view)
    used = {event['tool'] for event in view['history']}
    budget = view['remaining_calls']
    routes = (route for n in range(1, budget + 1) for route in itertools.permutations(cards, n))
    rule = select(routes, used, available, required, outputs)
    rule_seconds = time.monotonic() - start
    assert subprocess.check_output(['git', '-C', upstream, 'rev-parse', 'HEAD'], text=True).strip() == 'a72e266af2d4f196d341b82607bbb6016f77f6fb'
    source = upstream / 'data_generation'
    sys.path.insert(0, str(source))
    from prompts.build_semantic import BUILD_SEMANTIC
    tree = ast.parse((source / 'graph_generation/llm_pruning.py').read_text())
    prompt, = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str) and 'API Documentation Assistant' in node.value]
    client = OpenAI(base_url='http://127.0.0.1:8010/v1', api_key='local', max_retries=0)

    def ask(system, message):
        reply = client.chat.completions.create(model='Qwen3-4B-Thinking-2507', messages=[{'role':'system','content':system},{'role':'user','content':message}], temperature=0, seed=25000, max_tokens=4096, response_format={'type':'json_object'})
        with (directory / 'build-requests.jsonl').open('a') as f:
            print(json.dumps([system, message, reply.model_dump()]), file=f)
        try:
            result = json.loads(reply.choices[0].message.content or '{}')
            return result if isinstance(result, dict) else {}
        except ValueError:
            return {}

    tokenizer = AutoTokenizer.from_pretrained(model_path)
    encoder = AutoModel.from_pretrained(model_path).eval()

    def embed(text):
        inputs = tokenizer(text, return_tensors='pt', truncation=True, max_length=128)
        with torch.no_grad():
            return torch.nn.functional.normalize(encoder(**inputs).last_hidden_state.mean(dim=1))[0]

    semantic = {n: ask(BUILD_SEMANTIC + '\nUse input_params entries with name and description.', json.dumps(card)) for n, card in cards.items()}
    predictions = []
    for a, sa in semantic.items():
        if not isinstance(sa.get('output'), str):
            continue
        vector = embed(sa['output'])
        for b, sb in semantic.items():
            if a == b or not isinstance(sb.get('input_params'), list):
                continue
            for param in sb['input_params']:
                if not isinstance(param, dict) or param.get('name') not in required[b] or not isinstance(param.get('description'), str):
                    continue
                similarity = float(vector @ embed(param['description']))
                if similarity <= 0.20:
                    continue
                message = f"API1 Document: {cards[a]}, API1 Semantic Descriptions: {sa['output']}, API2 Document: {cards[b]}, API2 Semantic Descriptions: {param['description']}"
                if str(ask(prompt, message).get('connectable')).lower() == 'true':
                    predictions.append((a, b, param['name']))

    # Probe only on a separate sampled world. Each branch gets fresh receipts.
    # Enumerate short call prefixes once; verify actual producer value reuse.
    initial = view['history'][0]['arguments'].copy()
    verified = set()
    with (directory / 'probe-calls.jsonl').open('w') as log:
        def explore(path, values, provenance):
            for tool in sorted(cards.keys() - {name for name, _ in path}):
                if not set(required[tool]) <= values.keys():
                    continue
                session = probe_factory()
                args = {name: values[name] for name in required[tool]}
                for name, params in [*path, (tool, args)]:
                    receipt = session.call(name, params)
                    print(json.dumps([name, params, receipt, session.events[-1]['fee']]), file=log)
                if 'error' in receipt or session.events[-1]['illegal']:
                    continue
                for field in args:
                    edge = (provenance.get(field), tool, field)
                    if edge in predictions:
                        verified.add(edge)
                if len(path) < 4:
                    explore([*path,(tool,args)], values | receipt, provenance | {k:tool for k in receipt})
        explore([], initial, {})
    graph = directory / 'edges.txt'
    graph.write_text(''.join(f'{a} {b} {required[b].index(field)}\n' for a,b,field in sorted(verified)))
    seq = directory / 'sequences.json'
    subprocess.run([sys.executable, str(source/'instance_generation/sample_sequences.py'), '--graph_path',str(graph),'--output_path',str(seq),'--max_size',str(budget)],check=True)
    goat = select([r for group in json.loads(seq.read_text()) for r in group['topo_sort']],used,available,required,outputs)
    result = dict(rule=rule, goat=goat, semantic=semantic, predictions=predictions, verified=sorted(verified), rule_seconds=rule_seconds, total_seconds=time.monotonic()-start, history=view['history'])
    (directory/'build.json').write_text(json.dumps(result,indent=2))
    return {'rule':rule[:1], 'goat':goat[:1]}
