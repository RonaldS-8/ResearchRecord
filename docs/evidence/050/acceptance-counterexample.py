"""CPU-only counting counterexample, NOT Agent data; no SDK/model imports."""
import ast
from fractions import Fraction
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[3]
source = root / 'extensions/toolmaze_recovery/gate50.py'
tree = ast.parse(subprocess.check_output(
    ['git', 'show', 'd6a873aed468310422a6f7a1f6f8289f918eb445:extensions/toolmaze_recovery/gate50.py'],
    cwd=root, text=True))
functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name in {'wilson', 'summarize'}]
namespace = {'ARMS': ('R0', 'BTM', 'BTM_NR', 'H'), 'WORLDS': ('C', 'T', 'P'), 'F': Fraction}
exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), namespace)
rows = []
for arm in namespace['ARMS']:
    for world in namespace['WORLDS']:
        for seed in range(500001, 500011):
            failed = arm == 'BTM' and world == 'C'
            rows.append(dict(arm=arm, world=world, seed=seed, strict_success=not failed,
                             publications=1, budget_exhausted=failed, illegal_calls=int(failed),
                             lookups=0, raw_usage=[], suffix_execution_fee='5', suffix_diagnostic_fee='0'))
result = {
    'evidence_kind': 'CPU synthetic analysis counterexample; NOT Agent results',
    'source_commit': 'd6a873aed468310422a6f7a1f6f8289f918eb445',
    'scenario': 'All 10 BTM C failures have illegal calls plus budget exhaustion; no duplicates. '
                'Aggregate counting does not exclude execution-caused failures. '
                'These fields alone cannot establish actual causality.',
    'summary': namespace['summarize'](rows),
}
Path(__file__).with_suffix('.json').write_text(json.dumps(result, indent=2) + '\n')
assert result['summary']['verdict'] == 'go'
assert result['summary']['btm_failure_share_duplicate_or_budget'] == 1.0
print('Synthetic counterexample reproduced: share=1.0, verdict=go; NOT Agent evidence.')
