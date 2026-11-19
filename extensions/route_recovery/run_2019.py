"""Produce one ordered hint per strategy without goal labels or endpoint names."""
import itertools
import json
import subprocess
import sys
import time
from pathlib import Path

from extensions.route_recovery.reproduce_in_n_out_m4 import public_parameters, available_receipts
from extensions.toolmaze_recovery.gate44a import restored


def select(routes, used, available, required, outputs):
    ranked = []
    for route in set(map(tuple,routes)):
        fields = set(available)
        for name in route:
            if not set(required[name]) <= fields:
                break
            fields.update(outputs[name])
        else:
            links = sum(bool(set(outputs[a]).intersection(required[b])) for a,b in zip(route, route[1:]))
            ranked.append(((len(used.intersection(route)), int(links!=len(route)-1), -len(route),route),route))
    return list(min(ranked)[1]) if ranked else []


def main(out, upstream):
    out.mkdir()
    view=restored('M4').view()
    start=time.perf_counter()
    cards,_,outputs=public_parameters(view)
    required={k:v['parameters']['required'] for k,v in cards.items()}
    available=available_receipts(view)
    used={e['tool'] for e in view['history']}
    budget=view['remaining_calls']
    graph=out/'edges.txt'
    graph.write_text(''.join(f'{a} {b} {i}\n' for a in cards for b in cards if a!=b
                             for i,key in enumerate(required[b]) if key in outputs[a]))
    shared=time.perf_counter()-start
    result={'shared_seconds':shared,'edges':graph.read_text().splitlines(),'arms':{}}
    for arm in ('rule','goat'):
        start=time.perf_counter()
        if arm=='rule':
            routes=[r for n in range(1,budget+1) for r in itertools.permutations(cards,n)]
        else:
            sha=subprocess.check_output(['git','-C',str(upstream),'rev-parse','HEAD'],text=True).strip()
            assert sha=='a72e266af2d4f196d341b82607bbb6016f77f6fb'
            seq=out/'seq.json'
            subprocess.run([sys.executable,str(upstream/'data_generation/instance_generation/sample_sequences.py'),
                            '--graph_path',str(graph),'--output_path',str(seq),'--max_size',str(budget)],check=True)
            routes=[r for g in json.loads(seq.read_text()) for r in g['topo_sort']]
        route=select(routes,used,available,required,outputs)
        result['arms'][arm]=dict(generated=len(routes),distinct=len(set(map(tuple,routes))),route=route,seconds=time.perf_counter()-start)
    (out/'result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))


if __name__=='__main__': main(*map(Path,sys.argv[1:]))
