"""Replay each observed action and report simulator outcomes without policy access."""
import hashlib
import json
import sys
from pathlib import Path

from extensions.route_recovery.agent_2015 import setup, pub


def audit(folder):
    rows = {}
    for path in sorted(folder.glob('*.json')):
        if path.name == 'models.json':
            continue
        data = json.loads(path.read_text())
        requests = data['requests']
        usage = [r['response']['usage'] for r in requests]
        row = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), requests=len(requests),
                   input_tokens=sum(u['prompt_tokens'] for u in usage),
                   output_tokens=sum(u['completion_tokens'] for u in usage),
                   reasoning_tokens=sum(u['completion_tokens_details']['reasoning_tokens'] for u in usage),
                   seconds=round(sum(r['seconds'] for r in requests),3),
                   stops=[r['response']['choices'][0]['finish_reason'] for r in requests])
        if path.stem.startswith('diagnostic'):
            row['final_content'] = requests[0]['response']['choices'][0]['message']['content']
            row['legal_schema_and_binding'] = data['legal_schema_and_binding']
        else:
            view, call, session = setup(path.stem.split('-')[0])
            for action in data['actions']:
                assert call(action['tool'],action['arguments']) == action['result']
            grade = pub.evaluate(session,data['answer'])
            assert grade == data['grade']
            row.update(grade={k:v for k,v in grade.items() if k!='events'},
                       actions=data['actions'],answer=data['answer'],errors=data['errors'],
                       persisted=list(session.publications.values()),readbacks=session.checks)
        rows[path.stem] = row
    assert len(rows)==8
    return rows


if __name__=='__main__':
    print(json.dumps(audit(Path(sys.argv[1])),indent=2))
