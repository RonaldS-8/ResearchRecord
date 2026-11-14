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


def within(band):
    """Order-free form of the tie band: of the actions whose completion is within `band` of the best
    at this node, the cheapest (the first in the public order on an exact tie). Each decision gives up
    at most `band` of conditional completion, so a plan of H decisions gives up at most H * band."""
    def choose(candidates, total):
        top = max(value[0] for _, value in candidates)
        return min((c for c in candidates if c[1][0] >= top - band * total), key=lambda c: c[1][1])
    return choose


def priced(rate):
    """Total order: completion - rate * fee. If no plan can cost more than F, then with rate = d / F
    the chosen plan's completion is within d of the best achievable, whatever the tree looks like:
    c(best) - c(chosen) <= rate * (fee(best) - fee(chosen)) <= rate * F = d."""
    def choose(candidates, total):
        return max(candidates, key=lambda c: c[1][0] - rate * c[1][1])
    return choose


def fee_bound(cell, quote):
    """No episode can cost more than its call budget at the dearest public price."""
    prices = [1, *(price for _, price in quote.tool)] + ([quote.diagnostic] if quote.diagnostic is not None else [])
    return cell.left * float(max(prices))


def confident_band(completion, episodes, margin=0.05, z=2.0):
    """A tie band that closes when the log is thin: the fixed margin less z binomial standard errors
    of an estimate from `episodes` complete episodes and one episode's worth. Two plans tie only
    when, allowing for that much estimation error, the cheaper one is still within `margin`."""
    if not episodes:
        return NUMERIC
    return max(NUMERIC, margin - z * sqrt(max(completion * (1 - completion), 0.0) / episodes) - 1 / episodes)


def snapped(model, floor):
    """The model with every probability that rests on less than `floor` expected observations set to
    zero, so that pseudo-counts alone never make an unobserved outcome possible. Rows left with no
    observed mass keep their smoothed values."""
    def clean(values, weights):
        kept = [v if w >= floor else 0.0 for v, w in zip(values, weights)]
        return [v / sum(kept) for v in kept] if sum(kept) > 0 else list(values)
    first, seen, hops = model.mass
    start = {x: clean(model.start[x], first[x]) for x in model.start}
    emit = {}
    for tool, by_label in model.emit.items():
        names = list(by_label)
        rows = [clean([by_label[name][z] for name in names], [seen[tool][name][z] for name in names])
                for z in range(model.k)]
        emit[tool] = {name: [rows[z][i] for z in range(model.k)] for i, name in enumerate(names)}
    move = [clean(model.move[z], hops[z]) for z in range(model.k)] if model.transitions else model.move
    return Model(start, emit, move, model.transitions, model.loglik, model.size, model.mass)


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
    `enough` times have no outcome estimate and are left out of the plan. `tolerance` is the tie
    band on the model's own completion estimates: a number, or a function of (strict completion
    estimate, logged episodes in that context) such as `confident_band`. `rule`, when given, replaces
    it by an order-free rule: ("within", d) or ("priced", d), d being the completion given up per
    decision or over the whole plan (see `within` and `priced`)."""

    def __init__(self, model, cell, counts, fallback, guard=True, enough=5, tolerance=NUMERIC, floor=None,
                 rule=None):
        self.model, self.fallback, self.table, self.estimates = model, fallback, {}, {}
        self.rejected = guard and not consistent(model, counts)
        if self.rejected:
            return
        if floor is not None:
            model = snapped(model, floor)
        calls, episodes = defaultdict(int), defaultdict(int)
        for (context, events, action), seen in counts.items():
            calls[action] += sum(seen.values())
            if not events:
                episodes[context] += sum(seen.values())
        tools = {step.tool for steps in cell.graph.values() for step in steps} | {DIAGNOSE}
        ban = tuple(t for t in tools if calls[t] < enough or t not in model.emit)
        learned = learned_cell(model, cell)
        for (x, quote), mass in mp.groups(learned, mp.PUBLIC).items():
            total, band = sum(mass.values()), tolerance
            if callable(tolerance):
                strict = mp.solve(learned, mass, cell.left, (), mp.PUBLIC, ban=ban, tolerance=NUMERIC)[0] / total
                band = tolerance(strict, episodes[x])
            choose = None
            if rule is not None:
                choose = within(rule[1]) if rule[0] == "within" else priced(rule[1] / fee_bound(cell, quote))
            completion, fee = mp.solve(learned, mass, cell.left, (), mp.PUBLIC, ban=ban, table=self.table,
                                       x=x, quote=quote, tolerance=band, choose=choose)
            self.estimates[x, quote] = (completion / total, fee / total)

    def __call__(self, view):
        action = None if self.rejected else self.table.get((view.x, view.quote, view.events))
        return self.fallback(view) if action is None else action
