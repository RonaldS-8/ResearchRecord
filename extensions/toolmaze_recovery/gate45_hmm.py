# Fitting-only extraction from verified PR16 belief.py; source SHA in experiment045.
# Gate45 adapter supplies actual tool-call sequences and log-derived labels;
# no CPU planner, certain-tail expansion or generator cell is used here.
"""Experiment 042 (Gate 42B): a small learnable hidden-state model on the Gate 41 progress graph.

The model is a hidden Markov model with K states: a start distribution per public
context, one outcome distribution per (state, tool), and one transition matrix applied
after every decision step: one logged action with its feedback. The calls that follow a
success automatically (a step's `certain` calls) do not advance it, in fitting, filtering
and planning alike. The belief after a step with outcome o is

    b'(z') ~ sum_z b(z) P(o | z, tool) P(z' | z).

It is fitted by EM from logged episodes only: public context, tool calls, their
feedback and the episode outcome. It never reads the generator's hidden state, its
transition law or any test outcome. Planning solves the fitted model exactly with the
Gate 41 solver. Everything here is a reference inside the CPU environment model; it
says nothing about what an LLM agent would do.
"""
from collections import defaultdict
from math import log, sqrt

from . import multipath as mp
from .autoresearch import DIAGNOSE
from .gate34a import stream

OK = "ok"
NUMERIC = 1e-9  # completions of a float model closer than this are the same number, not a tolerance on scores
SOFT, STICKY, LOOSE = 0.1, 2.0, 0.05  # pseudo-counts: outcomes and starts; staying in a state; leaving it


def outcome(seen):
    return OK if seen in (mp.DONE, mp.PASS) else seen


def sequences(history):
    """Distinct (context, ((tool, outcome), ...)) episodes with their counts: all the model ever sees."""
    found = defaultdict(int)
    for row in history:
        found[row["x"], tuple((action, outcome(seen)) for _, action, seen in row["steps"])] += 1
    return found


class Model:
    def __init__(self, start, emit, move, transitions, loglik=0.0, size=1, mass=None, stale=None):
        self.start, self.emit, self.move, self.transitions = start, emit, move, transitions
        self.k, self.loglik, self.size = len(move), loglik, size
        self.stale = loglik if stale is None else stale  # the likelihood one M-step behind (rounds c1-c5 used it)
        self.mass = mass  # expected counts behind start, emit and move at the last E-step, without pseudo-counts
        self.pooled = [sum(v[i] for v in start.values()) / len(start) for i in range(self.k)]

    def parameters(self):
        free = sum(len(by_label) - 1 for by_label in self.emit.values())
        return len(self.start) * (self.k - 1) + self.k * free + (self.k * (self.k - 1) if self.transitions else 0)

    def bic(self, loglik=None):
        return -2 * (self.loglik if loglik is None else loglik) + self.parameters() * log(self.size)

    def filter(self, x, events):
        """Belief over hidden states after the public events; None when the model gives them no mass."""
        belief = list(self.start.get(x, self.pooled))
        for action, seen in events:
            weight = self.emit.get(action, {}).get(outcome(seen))
            if weight is None:
                return None
            belief = [b * w for b, w in zip(belief, weight)]
            total = sum(belief)
            if total <= 0:
                return None
            belief = [sum(belief[i] / total * self.move[i][j] for i in range(self.k)) for j in range(self.k)]
        return belief

    def success(self, x, events, tool):
        belief = self.filter(x, events)
        return None if belief is None else sum(b * w for b, w in zip(belief, self.emit[tool][OK]))


def logged_labels(history):
    """The feedback label table read from the log alone: every tool can fail with whatever labels its
    logged failures carried (the unlabelled failure always included), and the diagnostic has the
    signals that were seen. Nothing about the cell is needed."""
    found = defaultdict(set)
    for row in history:
        for _, action, seen in row["steps"]:
            found[action].add(outcome(seen))
    labels = {tool: tuple(sorted(found[tool] - {OK, None}, key=str)) for tool in found if tool != DIAGNOSE}
    labels = {tool: names or (None,) for tool, names in labels.items()}
    labels[DIAGNOSE] = tuple(sorted(found.get(DIAGNOSE, ())))
    return labels


def fit(history, cell, k, seed, transitions=True, iterations=40, labels=None, exact=False):
    """EM for one K from one random start. Only logged tools get outcome distributions. The label
    table defaults to the cell's public contract (`cell.alphabet()`, as in the registered rounds);
    pass `logged_labels(history)` to use nothing but the log. Rounds c1-c5 kept the likelihood and
    expected counts of the E-step before the last M-step; `exact` adds one E-step so that both
    belong to the parameters that are returned."""
    data = {key: n for key, n in sequences(history).items() if key[1]}
    # Sorted, because the alphabet is built from a set and the random start must not depend on its order.
    alphabet = cell.alphabet() if labels is None else labels
    labels = {tool: alphabet[tool] if tool == DIAGNOSE else (OK, *alphabet[tool]) for tool in sorted(alphabet)}
    labels = {tool: names for tool, names in labels.items() if names and any(
        action == tool for _, obs in data for action, _ in obs)}
    rng = stream(seed, f"042:init:{k}:{transitions}")

    def simplex(n):
        raw = [rng.random() + 0.5 for _ in range(n)]
        return [v / sum(raw) for v in raw]
    start = {x: simplex(k) for x in sorted({x for x, _ in data}, key=repr)}
    columns = {tool: [simplex(len(names)) for _ in range(k)] for tool, names in labels.items()}
    emit = {tool: {name: [columns[tool][z][i] for z in range(k)] for i, name in enumerate(names)}
            for tool, names in labels.items()}
    move = [[1.0 if i == j else 0.0 for j in range(k)] for i in range(k)]
    if transitions and k > 1:
        move = [[0.9 if i == j else 0.1 / (k - 1) for j in range(k)] for i in range(k)]
    states, size, previous, loglik = range(k), sum(data.values()), None, 0.0

    def expect():
        first = {x: [SOFT] * k for x in start}
        seen = {tool: {name: [SOFT] * k for name in names} for tool, names in labels.items()}
        hops = [[(STICKY if i == j else LOOSE) for j in states] for i in states]
        loglik = 0.0
        for (x, obs), n in data.items():
            alphas, scales, alpha = [], [], start[x]
            for action, name in obs:
                weight = emit[action][name]
                joint = [alpha[z] * weight[z] for z in states]
                scale = sum(joint) or 1e-300
                alphas.append(alpha)
                scales.append(scale)
                alpha = [sum(joint[i] / scale * move[i][j] for i in states) for j in states]
            loglik += n * sum(log(s) for s in scales)
            beta = [1.0] * k
            for t in range(len(obs) - 1, -1, -1):
                action, name = obs[t]
                weight, alpha, scale = emit[action][name], alphas[t], scales[t]
                ahead = [sum(move[i][j] * beta[j] for j in states) for i in states]
                if transitions and t < len(obs) - 1:
                    for i in states:
                        base = n * alpha[i] * weight[i] / scale
                        for j in states:
                            hops[i][j] += base * move[i][j] * beta[j]
                beta = [weight[i] * ahead[i] / scale for i in states]
                for z in states:
                    seen[action][name][z] += n * alpha[z] * beta[z]
            for z in states:
                first[x][z] += n * alphas[0][z] * beta[z]
        mass = ({x: [v - SOFT for v in row] for x, row in first.items()},
                {tool: {name: [v - SOFT for v in row] for name, row in by.items()} for tool, by in seen.items()},
                [[hops[i][j] - (STICKY if i == j else LOOSE) for j in states] for i in states])
        return first, seen, hops, loglik, mass
    for _ in range(iterations):
        first, seen, hops, loglik, mass = expect()
        start = {x: [v / sum(row) for v in row] for x, row in first.items()}
        for tool, by_label in seen.items():
            totals = [sum(by_label[name][z] for name in by_label) for z in states]
            emit[tool] = {name: [by_label[name][z] / totals[z] for z in states] for name in by_label}
        if transitions:
            move = [[v / sum(row) for v in row] for row in hops]
        if previous is not None and loglik - previous < 1e-7 * size:
            break
        previous = loglik
    stale = loglik
    if exact:
        _, _, _, loglik, mass = expect()
    return Model(start, emit, move, transitions and k > 1, loglik, size, mass, stale)


def train(history, cell, k, seed, transitions=True, restarts=2, iterations=40, labels=None, exact=False):
    """Best of a few EM starts by likelihood."""
    return max((fit(history, cell, k, seed * 1000 + r, transitions, iterations, labels, exact)
                for r in range(restarts)), key=lambda m: m.loglik)
