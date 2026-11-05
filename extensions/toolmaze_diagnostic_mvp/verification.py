"""Independent subset checks plus unchanged original C2 Judge."""
import copy

from .environment import CONFIG, load_case, fresh_engine, resolve
from evaluation.core.judge import JudgeSystem
from evaluation.utils import TraceLogger


def evaluate(task, mode, events, controlled=True):
    case = load_case(task,mode)
    engine = fresh_engine(case['base'])
    logger = TraceLogger(case['base'].task_id,mode)
    for i,event in enumerate(events):
        logger.log_round(i+1,{'type':'tool_call','tool_name':event['tool'],'arguments':event['arguments']},event['output'],event['perturbation_status'])
    native = JudgeSystem().judge(case['docs'][mode],logger.to_dict())
    issues=[]; outputs={}; ids=set()
    nodes={n['id']:n['tool_name'] for n in case['template']['dag']['nodes']}
    prefix=case['source']['node_sequence'][:case['position']+1]
    if [e['node'] for e in events[:len(prefix)]] != prefix:
        issues.append({'issue':'fixed_start_prefix_mismatch'})
    for index,event in enumerate(events):
        before=len(issues)
        node=event['node']; tool=event['tool']
        if event['call_id'] in ids:
            issues.append({'index':index,'issue':'duplicate_call_id'})
        ids.add(event['call_id'])
        if nodes.get(node)!=tool:
            issues.append({'index':index,'issue':'node_tool_mismatch'})
            continue
        try:
            bindings=case['template']['parameter_bindings'][tool]
            expected=resolve(bindings,case['docs']['P0']['user_input'],outputs)
            if event['arguments']!=expected:
                issues.append({'index':index,'issue':'binding_value_mismatch','expected':expected,'actual':event['arguments']})
        except (KeyError,ValueError,IndexError,TypeError) as exc:
            issues.append({'index':index,'issue':'missing_or_invalid_source','detail':str(exc)})
        try:
            raw,status=engine._intercept_tool_call(tool,copy.deepcopy(event['arguments']))
            expected_public=CONFIG['error'] if controlled and status=='perturbed' else raw
            if raw!=event['raw_output'] or status!=event['perturbation_status'] or expected_public!=event['output']:
                issues.append({'index':index,'issue':'runtime_replay_mismatch'})
        except Exception as exc:
            issues.append({'index':index,'issue':'replay_exception','detail':repr(exc)})
        if event['charge']!=CONFIG['tool_attempt_cost']:
            issues.append({'index':index,'issue':'tool_charge_mismatch'})
        if len(issues)==before and 'error' not in event['output']:
            outputs[node]=copy.deepcopy(event['output'])
    matched=[p['path_id'] for p in case['docs']['P0']['valid_paths'] if all(n in outputs for n in p['node_sequence'])]
    if not matched:
        issues.append({'issue':'no_complete_legal_path'})
    valid=not issues
    return {'native_pass':native['pass'],'independent_valid':valid,'legal_success':valid and native['pass'],
            'matched_paths':matched,'issues':issues,'native_judgement':native}
