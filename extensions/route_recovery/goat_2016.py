"""Author sequence sampler on a public name-match graph; isolated execution per sequence."""
import json
import re
import subprocess
import sys
from pathlib import Path

from extensions.route_recovery.agent_2015 import setup, pub


def main(out, upstream):
    out.mkdir()
    sampler = upstream/'data_generation/instance_generation/sample_sequences.py'
    sha = subprocess.check_output(['git','-C',str(upstream),'rev-parse','HEAD'],text=True).strip()
    assert sha=='a72e266af2d4f196d341b82607bbb6016f77f6fb'
    specs = {s['name']:s for s in setup('C')[0]['contracts']}
    edges = []
    for name,spec in specs.items():
        match = re.search(r'\breturns (\w+)', spec['description'], re.I)
        if match:
            for target,dest in specs.items():
                for idx,param in enumerate(dest['parameters']['required']):
                    if param==match[1] and name!=target: edges.append(f'{name} {target} {idx}')
    graph=out/'edges.txt'
    graph.write_text('\n'.join(edges)+'\n')
    sequences=out/'sequences.json'
    subprocess.run([sys.executable,str(sampler),'--graph_path',str(graph),'--output_path',str(sequences)],check=True)
    rows=[]
    for entry in json.loads(sequences.read_text()):
        for seq in entry['topo_sort']:
            for world in 'CTP':
                view,call,session=setup(world)
                receipts=[e['result'] for e in view['history'] if 'error' not in e['result']]
                actions=[]
                for name in seq:
                    args={}
                    for param in specs[name]['parameters']['required']:
                        values=[r[param] for r in receipts if param in r]
                        if values and all(v==values[0] for v in values): args[param]=values[0]
                    if len(args)!=len(specs[name]['parameters']['required']): break
                    result=call(name,args)
                    actions.append(dict(tool=name,arguments=args,result=result))
                    if 'error' in result: break
                    receipts.append(result)
                executed=len(actions)==len(seq) and all('error' not in a['result'] for a in actions)
                grade=pub.evaluate(session,'CPU sequence replay.')
                rows.append(dict(world=world,sequence=seq,actions=actions,executed=executed,strict=grade['strict_success'],effects=grade['publications']))
    (out/'execution.json').write_text(json.dumps(dict(upstream=sha,edges=edges,rows=rows),indent=2))


if __name__=='__main__': main(*map(Path,sys.argv[1:]))
