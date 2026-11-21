"""Summarize observable failures; aggregate scores alone cannot identify bad bindings."""
from collections import Counter
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
rows = json.loads((root/'docs/evidence/2_025/replay.json').read_text())
counts = Counter()
for key, row in rows.items():
    if row['strict']:
        continue
    if key in {'24001/M3-rule', '24014/M3-rule'}:
        # Manually compared original arguments and receipts in the frozen 2_025 review.
        cause = 'confirmed_content_copy_error_and_misleading_receipt'
    elif 'Missing actual post-commit readback.' in row['issues']:
        cause = 'observed_missing_readback'
    else:
        cause = 'unresolved_from_summary'
    counts[cause] += 1
print(json.dumps(dict(counts), indent=2))
