"""Compare recommendations from frozen policies using identical tool displays."""
import json
import sys
from pathlib import Path

from .run_2017 import run

if __name__ == '__main__':
    out, prior = map(Path, sys.argv[1:])
    plans = {}
    for case in ('M3', 'M4'):
        build = json.loads((prior / case / 'build.json').read_text())
        pairs = {tuple(build[method][:2]) for method in ('rule', 'goat') if len(build[method]) >= 2}
        if len(pairs) != 1:
            raise ValueError('Expected one distinct emitted pair per registered case')
        plans[case] = pairs.pop()
    (out / 'pairs.json').write_text(json.dumps(plans))
    for index in range(16):
        seed = 24000 + index
        directory = out / str(seed)
        directory.mkdir()
        for case in list(plans)[::1 if index % 2 == 0 else -1]:
            first, second = plans[case]
            for reverse in (False, True):
                names = (second, first) if reverse else (first, second)
                display = 'Candidate tools: ' + ', '.join(names) + '. '
                for ordered in (False, True)[::1 if index % 2 == 0 else -1]:
                    note = f'Suggested order: {first} before {second}.' if ordered else 'No order is specified.'
                    arm = f'order{int(ordered)}-reverse{int(reverse)}'
                    run(case, arm, directory, post_prefix=display + note, seed=seed, temperature=0.6)
