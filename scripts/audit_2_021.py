"""Replay each suffix from its frozen checkpoint and recompute the original score."""
import hashlib
import json
import sys
from pathlib import Path

from extensions.toolmaze_recovery.gate42a import evaluate
from extensions.toolmaze_recovery.gate44a import restored

root = Path(sys.argv[1])
assert (root / 'status').read_text().strip() == 'completed'
summary = {}
for case in ('M3', 'M4'):
    for arm in ('direct', 'first', 'pair', 'full'):
        path = root / f'{case}-{arm}.json'
        raw = path.read_bytes()
        row = json.loads(raw)
        session = restored(case)
        prefix = len(session.events)
        assert session.events == row['events'][:prefix]
        suffix = row['events'][prefix:]
        for event in suffix:
            session.call(event['tool'], event['arguments'])
        assert session.events == row['events']
        score = evaluate(session, row['answer'])
        assert score == row['scores']
        requests = row['requests']
        usage = [r['response']['usage'] for r in requests]
        summary[path.stem] = dict(actions=[e['tool'] for e in suffix], fee=sum(int(e['fee']) for e in suffix), strict=score['strict_success'], issues=score['issues'], status=row['status'], requests=len(requests), input=sum(u['prompt_tokens'] for u in usage), output=sum(u['completion_tokens'] for u in usage), seconds=round(sum(r['seconds'] for r in requests), 2), sha256=hashlib.sha256(raw).hexdigest())
print(json.dumps(summary, indent=2))
