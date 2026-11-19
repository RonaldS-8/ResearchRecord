import json
import sys
from pathlib import Path
from extensions.route_recovery.run_2017 import run

if __name__=='__main__':
    out, cpu=map(Path,sys.argv[1:])
    arms=json.loads((cpu/'result.json').read_text())['arms']
    for arm,data in arms.items():
        run('M4',arm,out,post_prefix='Candidate continuation in order: '+', '.join(data['route'])+'.')
