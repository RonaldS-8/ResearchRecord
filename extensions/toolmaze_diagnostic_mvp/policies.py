"""Fixed audit policies; inputs are public JSON dictionaries only."""


def theory(view):
    c = view['costs']; p = view['prior_transient']
    retry = p*c['retry_if_recovers']+(1-p)*(c['failed_retry']+c['switch'])
    informed = p*min(c['retry_if_recovers'],c['switch'])+(1-p)*c['switch']
    return {'best_no_diagnosis':min(c['switch'],retry),'informed':informed,
            'gross_information_value':min(c['switch'],retry)-informed,
            'no_diagnosis_policy':'switch' if c['switch'] <= retry else 'retry_then_switch'}


def choose(policy, view):
    decisions = view['decisions']
    if policy == 'cost_selective':
        t = theory(view)
        policy = 'always_diagnose' if view['costs']['diagnosis'] < t['gross_information_value'] else t['no_diagnosis_policy']
    if policy == 'always_diagnose':
        diagnosis = next((d for d in decisions if d['action']=='diagnose'),None)
        if diagnosis is None:
            return 'diagnose'
        return 'retry' if diagnosis['result']['retry_will_recover'] else 'switch'
    if policy == 'switch':
        return 'switch'
    if policy in ('retry_only','retry_then_switch'):
        tried = any(d['action']=='retry' for d in decisions)
        return ('stop' if policy=='retry_only' else 'switch') if tried else 'retry'
    raise ValueError('Unregistered policy')
