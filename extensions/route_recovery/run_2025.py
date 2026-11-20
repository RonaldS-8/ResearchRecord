import json
import sys
from pathlib import Path

from .entry_2025 import build
from .run_2017 import run
from extensions.toolmaze_recovery.gate42a import ARCHIVE, VALIDATE, WRITE, VERIFY, sample
from extensions.toolmaze_recovery.gate44a import restored

if __name__ == '__main__':
    root, upstream, model = map(Path, sys.argv[1:4])
    prior = Path(sys.argv[4]) if len(sys.argv) == 5 else None
    plans = {}
    for case in ('M3', 'M4'):
        directory = root / case
        if prior is not None and case == 'M3':
            if (prior/'source-commit.txt').read_text().strip() != '6158268257d7d5c746a173cd9eebcf7c7498924a':
                raise ValueError('Unexpected M3 build source')
            saved = json.loads((prior/case/'build.json').read_text())
            assert saved['history'] == restored(case).view()['history']
            directory.symlink_to(prior/case, target_is_directory=True)
            plans[case] = {arm:saved[arm][:1] for arm in ('rule','goat')}
            continue
        directory.mkdir()
        view = restored(case).view()
        plans[case] = build({key:view[key] for key in ('tools','history','remaining_calls')}, lambda: sample(case, 25000), directory, upstream, model)
    # Oracle is added only after both independent policies have emitted outputs.
    plans['M3']['oracle_full'] = [ARCHIVE, VALIDATE, WRITE, VERIFY]
    (root/'plans.json').write_text(json.dumps(plans, indent=2))
    for index in range(16):
        seed = 24000 + index
        directory = root / str(seed)
        directory.mkdir()
        for case in list(plans)[::1 if index % 2 == 0 else -1]:
            arms = list(plans[case].items())
            offset = index % len(arms)
            for arm, route in arms[offset:] + arms[:offset]:
                hint = 'Candidate continuation in order: '+', '.join(route)+'.' if route else None
                run(case, arm, directory, post_prefix=hint, seed=seed, temperature=0.6)
