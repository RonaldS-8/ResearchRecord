"""Experiment 051: logged history from a behaviour policy, a likelihood over the
GRID2 hypothesis set, and plug-in planning evaluated in the true scenario.

A history episode holds only public content: the first-failure detail label, the
actions, each observation and the episode's final strict-success flag. Hidden states
stay inside the mass vectors of completion_headroom.
"""
from collections import Counter
import math
import random

from .completion_headroom import (CALLS, FINISH, READ, RETRY, S, STATES, STOP, SWITCH, T,
                                  better, finish, optimum, sequence_value, step)

FIRST = (RETRY, SWITCH, READ)
CYCLE = (READ, RETRY, SWITCH)
NEG = -1e9  # log of an impossible trajectory


def behaviour(cell, first):
    """First action, then the fixed cycle read, retry, switch; calls that do not fit are skipped."""
    actions, used = [first], cell.calls(first)
    progressed = True
    while progressed:
        progressed = False
        for action in CYCLE:
            if used + cell.calls(action) <= cell.left:
                actions.append(action)
                used += cell.calls(action)
                progressed = True
    return tuple(actions)


def _receipt(cell, mass, action):
    """Mass that gets a write receipt; the episode ends there."""
    total = 0.0
    for (n, w), weight in zip(STATES, mass):
        works = (w == T) if action == RETRY else (w != S)
        if weight and works:
            total += weight * (cell.p_retry if action == RETRY else cell.p_switch)
    return total




def trajectories(cell):
    """{(label, first, observations, success): probability} under the behaviour policy."""
    out = Counter()
    for label, root in cell.roots().items():
        for first in FIRST:
            mass = tuple(m / len(FIRST) for m in root)
            _walk(cell, mass, behaviour(cell, first), (label, first), (), out)
    return dict(out)


def _walk(cell, mass, actions, prefix, seen, out):
    if not actions:
        out[(*prefix, seen, 0)] += sum(mass)
        return
    action, rest = actions[0], actions[1:]
    success, _, branches = step(cell, mass, action)
    if action == READ:
        for obs, part in branches.items():
            if obs == "found":
                ok = finish(part)
                out[(*prefix, seen + (obs,), 1)] += ok
                out[(*prefix, seen + (obs,), 0)] += sum(part) - ok
            else:
                _walk(cell, part, rest, prefix, seen + (obs,), out)
        return
    receipt = _receipt(cell, mass, action)
    out[(*prefix, seen + ("receipt",), 1)] += success
    out[(*prefix, seen + ("receipt",), 0)] += receipt - success
    if "fail" in branches:
        _walk(cell, branches["fail"], rest, prefix, seen + ("fail",), out)


def sample(dist, n, seed):
    keys = sorted(dist, key=repr)
    return Counter(random.Random(seed).choices(keys, weights=[dist[k] for k in keys], k=n))


def log_likelihood(dist, counts):
    total = 0.0
    for key, count in counts.items():
        p = dist.get(key, 0.0)
        total += count * (math.log(p) if p > 1e-300 else NEG)
    return total


def decide(cell, mass, left, cache):
    """The action the lexicographic optimum takes at this information state."""
    if sum(mass) <= 0:
        return STOP
    best, choice = (0.0, 0.0), STOP
    if better((finish(mass), 0.0), best):
        best, choice = (finish(mass), 0.0), FINISH
    for action in CALLS:
        if left < cell.calls(action):
            continue
        completion, fee, branches = step(cell, mass, action)
        for part in branches.values():
            c, f = optimum(cell, part, left - cell.calls(action), cache=cache)
            completion, fee = completion + c, fee + f
        if better((completion, fee), best):
            best, choice = (completion, fee), action
    return choice


def plug_in(true, plan, cache=None):
    """Value in the true scenario of the policy that is optimal for `plan`.
    The policy updates its belief with `plan`'s parameters from the actual observations."""
    cache = {} if cache is None else cache
    total = [0.0, 0.0]
    for label, mass in true.roots().items():
        c, f = _run(true, plan, mass, plan.roots()[label], true.left, cache)
        total = [total[0] + c, total[1] + f]
    return tuple(total)


def _run(true, plan, mt, mp, left, cache):
    if sum(mt) <= 0:
        return 0.0, 0.0
    action = decide(plan, mp, left, cache)
    if action == STOP:
        return 0.0, 0.0
    if action == FINISH:
        return finish(mt), 0.0
    completion, fee, branches = step(true, mt, action)
    _, _, planned = step(plan, mp, action)
    for obs, part in branches.items():
        c, f = _run(true, plan, part, planned.get(obs, (0.0,) * len(STATES)), left - true.calls(action), cache)
        completion, fee = completion + c, fee + f
    return completion, fee


def empirical_first(cell, counts):
    """EMP: per label, the first action with the highest logged strict-success rate
    (ties: lower mean logged calls), then the behaviour order; pooled over labels when
    a label has no episodes. Uses only the counts, never model parameters."""
    def pick(rows):
        stats = {}
        for (label, first, seen, ok), count in rows:
            s = stats.setdefault(first, [0, 0, 0])
            s[0] += count * ok
            s[1] += count
            s[2] += count * len(seen)
        return min(stats, key=lambda a: (-stats[a][0] / stats[a][1], stats[a][2] / stats[a][1], FIRST.index(a)))
    items = list(counts.items())
    total = [0.0, 0.0]
    choices = {}
    for label, mass in cell.roots().items():
        rows = [r for r in items if r[0][0] == label] or items
        first = pick(rows)
        choices[label] = first
        c, f = sequence_value(cell, mass, behaviour(cell, first), STOP)
        total = [total[0] + c, total[1] + f]
    return tuple(total), choices
