"""Informed route-prefix controls on both registered historical checkpoints."""
import sys
from pathlib import Path
from extensions.route_recovery.run_2017 import run
from extensions.toolmaze_recovery.gate42a import ARCHIVE, VALIDATE, WRITE, VERIFY, ALTWRITE, CONFIRM

def run_conditions(out, **agent_options):
    for case, route in [('M3',[ARCHIVE,VALIDATE,WRITE,VERIFY]),('M4',[ALTWRITE,CONFIRM,VERIFY])]:
        for arm, count in [('direct',0),('first',1),('pair',2),('full',len(route))]:
            hint='Candidate continuation in order: '+', '.join(route[:count])+'.' if count else None
            run(case,arm,out,post_prefix=hint, **agent_options)


if __name__ == "__main__":
    run_conditions(Path(sys.argv[1]))
