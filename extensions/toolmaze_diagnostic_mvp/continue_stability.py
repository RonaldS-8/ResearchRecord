"""Finish only unsampled Gate 5 pairs; never retry existing failures."""
import argparse
import hashlib
import json
from pathlib import Path
import traceback

from .model_adapter import ProtocolFailure
from .run_stability import config_snapshot, dump, pair, specs, summary


def remaining(previous):
    planned = list(specs())
    by_key = {p['key']: p for p in previous}
    prefix = ['_'.join(map(str, case)) for case in planned[:len(previous)]]
    if len(by_key) != len(previous) or set(by_key) != set(prefix):
        raise ProtocolFailure('previous_pairs_not_unique_registered_prefix')
    return [by_key[k] for k in prefix], planned[len(previous):]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    old, added = [], []
    try:
        old, cases = remaining([json.loads(p.read_text()) for p in args.previous.glob('*_pair.json')])
        if len(old) != 79 or len(cases) != 41:
            raise ProtocolFailure('unexpected_continuation_size')
        original = json.loads((args.previous / 'config.json').read_text())
        config = config_snapshot()
        for field in ('model_config', 'prompts', 'seeds', 'environment_config', 'provenance', 'service_processes',
                      'model_generation_config', 'packages', 'active_capacity_service_script'):
            if original[field] != json.loads(json.dumps(config[field])):
                raise ProtocolFailure('conditions_changed:' + field)
        manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.previous.iterdir() if p.is_file()}
        dump(args.out / 'config.json', {**config, 'continuation_registration': '220fd5c',
             'previous_directory': str(args.previous.resolve()), 'previous_commit': original['commit'],
             'previous_file_hashes': manifest, 'remaining_cases': cases, 'continue_budget': True})
        for index, case in enumerate(cases):
            print(f'Starting remaining pair {index + 1}/{len(cases)} {case}', flush=True)
            result = pair(*case, args.out, continue_budget=True)
            added.append(result)
            print(f'Finished {result["key"]}: {result["status"]}', flush=True)
            if result['status'] == 'stopped':
                break
        if config_snapshot()['provenance'] != config['provenance']:
            raise ProtocolFailure('frozen_conditions_changed')
        if any(hashlib.sha256((args.previous / name).read_bytes()).hexdigest() != value for name, value in manifest.items()):
            raise ProtocolFailure('previous_results_changed')
        merged = old + added
        result = summary(merged)
        rows = [r for p in merged for r in p['rows']]
        dump(args.out / 'evaluation.json', {**result, 'status': 'schedule_completed' if len(added) == len(cases)
             and all(p['status'] != 'stopped' for p in added) else 'stopped',
             'previous_pairs': len(old), 'new_pairs': len(added), 'all_pairs': len(merged),
             'started_states': len(rows), 'legal_completed_states': sum(r['score']['legal_success'] for r in rows),
             'failed_samples': [{'id': r['sample_id'], 'status': r['status']} for r in rows if not r['score']['legal_success']],
             'all_decision_action_counts': {action: sum(d['action'] == action for r in rows for d in r['decisions'])
                                            for action in ('retry', 'switch', 'diagnose')},
             'previous_error_label_limitation': 'Original fatal partial row omits seven retry_after_failed_retry labels; completion-inspection-01.json records correction.',
             'model_conditions_unchanged': True})
        if len(added) != len(cases) or any(p['status'] == 'stopped' for p in added):
            raise SystemExit(1)
    except Exception as exc:
        dump(args.out / 'failure.json', {'error': repr(exc), 'traceback': traceback.format_exc(), 'new_pairs': len(added)})
        raise


if __name__ == '__main__':
    main()
