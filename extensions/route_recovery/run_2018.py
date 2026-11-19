"""Nested, informed interventions on a single frozen checkpoint."""
import sys
from pathlib import Path
from extensions.route_recovery.run_2017 import run

names = ['prepare_alternate_publication','confirm_alternate_publication','read_published_record']
ordered = 'Candidate continuation in order: '+', '.join(names)+'.'
arms = {
    'unordered':'Candidate tools: '+', '.join(sorted(names))+'.',
    'ordered':ordered,
    'sources':ordered+' For preparation take record_id and content from the backup read and evidence_ref from validation. For confirmation use the same record_id and the preparation receipt’s pending_publication_ref. For readback use the confirmation receipt’s publication_id.',
}

if __name__=='__main__':
    for arm, message in arms.items():
        run('M4',arm,Path(sys.argv[1]),post_prefix=message)
