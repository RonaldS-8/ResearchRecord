"""Experiment 042 (Gate 42B): a small learnable hidden-state model on the Gate 41 progress graph.

The model is a hidden Markov model with K states: a start distribution per public
context, one outcome distribution per (state, tool), and one transition matrix applied
after every call. The belief after a call with outcome o is

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
    def __init__(self, start, emit, move, transitions, loglik=0.0, size=1):
        self.start, self.emit, self.move, self.transitions = start, emit, move, transitions
        self.k, self.loglik, self.size = len(move), loglik, size
        self.pooled = [sum(v[i] for v in start.values()) / len(start) for i in range(self.k)]

    def parameters(self):
        free = sum(len(by_label) - 1 for by_label in self.emit.values())
        return len(self.start) * (self.k - 1) + self.k * free + (self.k * (self.k - 1) if self.transitions else 0)

    def bic(self):
        return -2 * self.loglik + self.parameters() * log(self.size)

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


def fit(history, cell, k, seed, transitions=True, iterations=40):
    """EM for one K from one random start. Only logged tools get outcome distributions."""
    data = {key: n for key, n in sequences(history).items() if key[1]}
    # Sorted, because the alphabet is built from a set and the random start must not depend on its order.
    alphabet = cell.alphabet()
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
    for _ in range(iterations):
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
        start = {x: [v / sum(row) for v in row] for x, row in first.items()}
        for tool, by_label in seen.items():
            totals = [sum(by_label[name][z] for name in by_label) for z in states]
            emit[tool] = {name: [by_label[name][z] / totals[z] for z in states] for name in by_label}
        if transitions:
            move = [[v / sum(row) for v in row] for row in hops]
        if previous is not None and loglik - previous < 1e-7 * size:
            break
        previous = loglik
    return Model(start, emit, move, transitions and k > 1, loglik, size)


def train(history, cell, k, seed, transitions=True, restarts=2):
    """Best of a few EM starts by likelihood."""
    return max((fit(history, cell, k, seed * 1000 + r, transitions) for r in range(restarts)),
               key=lambda m: m.loglik)


def learned_cell(model, cell):
    """The fitted model as a Gate 41 cell over the same public graph, prices, contexts and budget."""
    faults = {}
    for z in range(model.k):
        rates, detail = {}, {}
        for tool, by_label in model.emit.items():
            if tool == DIAGNOSE:
                continue
            rates[tool] = by_label[OK][z]
            fails = [(name, p[z]) for name, p in by_label.items() if name != OK]
            total = sum(p for _, p in fails)
            detail[tool] = tuple((name, p / total if total > 0 else 1.0 / len(fails)) for name, p in fails)
        signal = tuple((name, p[z]) for name, p in model.emit.get(DIAGNOSE, {}).items())
        faults[z] = mp.Fault(rates, detail, signal)
    roots = tuple((p, x, quote, tuple(enumerate(model.start.get(x, model.pooled)))) for p, x, quote, _ in cell.roots)
    moves = {z: tuple(enumerate(model.move[z])) for z in range(model.k)} if model.transitions else None
    return mp.Cell(cell.name, cell.graph, faults, roots, cell.left, moves)


def consistent(model, counts, support=30, limit=4.0):
    """Predictive check: at every logged node with enough calls, the model's success rate must
    agree with the observed frequency. A model that fails it is not trusted anywhere."""
    for (x, events, action), seen in counts.items():
        total = sum(seen.values())
        if total < support or action == DIAGNOSE or action not in model.emit:
            continue
        p = model.success(x, events, action)
        if p is None:
            return False
        hits = seen.get(mp.DONE, 0) + seen.get(mp.PASS, 0)
        if abs(hits / total - p) > limit * sqrt(p * (1 - p) / total + 1e-4):
            return False
    return True


class BeliefPolicy:
    """Plan on the fitted hidden-state model; hand over to `fallback` when the model fails the
    predictive check, or at a history the model gave no plan for. Tools logged fewer than
    `enough` times have no outcome estimate and are left out of the plan."""

    def __init__(self, model, cell, counts, fallback, guard=True, enough=5, tolerance=NUMERIC):
        self.model, self.fallback, self.table, self.estimates = model, fallback, {}, {}
        self.rejected = guard and not consistent(model, counts)
        if self.rejected:
            return
        calls = defaultdict(int)
        for (_, _, action), seen in counts.items():
            calls[action] += sum(seen.values())
        tools = {step.tool for steps in cell.graph.values() for step in steps} | {DIAGNOSE}
        ban = tuple(t for t in tools if calls[t] < enough or t not in model.emit)
        learned = learned_cell(model, cell)
        for (x, quote), mass in mp.groups(learned, mp.PUBLIC).items():
            total = sum(mass.values())
            completion, fee = mp.solve(learned, mass, cell.left, (), mp.PUBLIC, ban=ban, table=self.table,
                                       x=x, quote=quote, tolerance=tolerance)
            self.estimates[x, quote] = (completion / total, fee / total)

    def __call__(self, view):
        action = None if self.rejected else self.table.get((view.x, view.quote, view.events))
        return self.fallback(view) if action is None else action
