"""Experiment 041 (Gate 41): several recovery paths and uncertainty-aware action comparison.

Generalises the experiment 040 macro model (autoresearch.py, left unchanged) from
"retry or switch" to a public progress graph. Each node offers tool calls; a
successful call moves the task to another node, so paths can share tools, depend on
earlier choices and fail again after a switch. Values stay exact rationals
(strict completion probability, expected remaining fee), compared lexicographically.

Every optimum, oracle and continuation here is a reference inside this environment
model. None of it estimates what an LLM agent would do: action compliance, argument
binding and task completion by a real agent are unknown and are not modelled.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from fractions import Fraction as Q
from itertools import product
from math import sqrt

from .autoresearch import DIAGNOSE, STOP, better, draw, rate
from .gate34a import stream

DONE, PASS, START = "done", "pass", "start"
PUBLIC = frozenset(("x", "quote", "detail", "signal"))
CALLS_LEFT = 6


@dataclass(frozen=True)
class Step:
    """One tool call offered at a public progress node. A success moves the task to
    `to` after `certain` further calls that always succeed (the rest of that tool's
    sub-path); a failure leaves the node unchanged."""
    tool: str
    to: object
    certain: int = 0


@dataclass(frozen=True)
class Prices:
    """Public prices of one task: per-tool overrides (default 1) and the diagnostic fee.
    Certain calls cost 1 each."""
    tool: tuple = ()      # ((tool name, price), ...)
    diagnostic: Q = None

    def of(self, tool):
        return dict(self.tool).get(tool, Q(1))


@dataclass(frozen=True)
class Fault:
    """One hidden failure state. `rates[tool]` is a success rate: a constant, a tuple
    indexed by the calls made since the first timeout (the last entry repeats), or a
    function of the public event sequence."""
    rates: dict
    detail: dict = field(default_factory=dict)  # tool -> ((label, P(label | failed call)), ...)
    signal: tuple = ()                          # ((label, P(label | diagnostic call)), ...)


@dataclass(frozen=True)
class Cell:
    name: str
    graph: dict     # node -> tuple of Step, in tie-breaking order; START follows the first timeout
    faults: dict    # hidden state -> Fault
    roots: tuple    # ((P, x, Prices, ((state, P(state | x, prices)), ...)), ...)
    left: int = CALLS_LEFT
    moves: dict = None  # optional hidden transition after every decision step: state -> ((state, P), ...)

    @property
    def diagnostic(self):
        return self.roots[0][2].diagnostic is not None

    def alphabet(self):
        """Public failure labels of each tool and signal labels, known from the tool contracts."""
        tools = {step.tool for steps in self.graph.values() for step in steps}
        labels = {tool: tuple(sorted({label for f in self.faults.values() for label, _ in f.detail.get(tool, ())})
                              or [None]) for tool in tools}
        labels[DIAGNOSE] = tuple(sorted({label for f in self.faults.values() for label, _ in f.signal}))
        return labels


def parallel(routes):
    """Graph of independent routes: each is (tool names in order, certain tail calls), and
    progress made on one route is kept while another is tried."""
    graph = {}
    for node in product(*(range(len(tools)) for tools, _ in routes)):
        steps = []
        for index, (tools, tail) in enumerate(routes):
            last = node[index] == len(tools) - 1
            target = DONE if last else node[:index] + (node[index] + 1,) + node[index + 1:]
            steps.append(Step(tools[node[index]], target, tail if last else 0))
        graph[START if not any(node) else node] = tuple(steps)
    return graph


def build(name, graph, faults, contexts, quotes=((Prices(), Q(1)),), left=CALLS_LEFT):
    """Independent public context and prices: contexts is {x: (P(x), {state: P(state | x)})}."""
    roots = tuple((px * pq, x, quote, tuple(prior.items()))
                  for x, (px, prior) in contexts.items() for quote, pq in quotes)
    return Cell(name, graph, faults, roots, left)


def chance(spec, events):
    return spec(events) if callable(spec) else rate(spec, events)


def position(graph, events):
    """Public progress node, read from the event sequence."""
    node = START
    for action, seen in events:
        if seen == PASS:
            node = next(step.to for step in graph[node] if step.tool == action)
    return node


def needs(graph, node, seen=()):
    """Fewest calls that can still finish the task from a node."""
    if node == DONE:
        return 0
    return min((1 + step.certain + needs(graph, step.to, seen + (node,))
                for step in graph[node] if step.to not in seen), default=10 ** 6)


def legal(graph, events, left, diagnostic):
    """A tool may be called only while the call budget can still finish the task through it."""
    node = position(graph, events)
    options = [step.tool for step in graph[node] if left >= 1 + step.certain + needs(graph, step.to)]
    if diagnostic and left >= 1 and all(e[0] != DIAGNOSE for e in events):
        options.append(DIAGNOSE)
    return (*options, STOP)


@dataclass(frozen=True)
class View:
    """Everything a policy may read: public context, prices, events, budget and the tool graph."""
    x: object
    quote: Prices
    events: tuple   # (action, observation) of every call that did not finish the task
    left: int
    graph: dict

    def legal(self):
        return legal(self.graph, self.events, self.left, self.quote.diagnostic is not None)

    def fails(self, action):
        return sum(e[0] == action and e[1] != PASS for e in self.events)

    def last(self, action):
        return next((e[1] for e in reversed(self.events) if e[0] == action), None)


def branches(cell, mass, action, events):
    """Split joint mass {(root, state): weight} by one call's outcome label."""
    after = defaultdict(dict)
    if action == DIAGNOSE:
        for (root, state), weight in mass.items():
            for label, p in cell.faults[state].signal:
                if p:
                    after[label][root, state] = weight * p
        return after
    step = next(s for s in cell.graph[position(cell.graph, events)] if s.tool == action)
    for (root, state), weight in mass.items():
        fault = cell.faults[state]
        ok = chance(fault.rates[action], events)
        if ok:
            after[DONE if step.to == DONE else PASS][root, state] = weight * ok
        for label, p in fault.detail.get(action) or ((None, Q(1)),):
            if p and ok < 1:
                after[label][root, state] = weight * (1 - ok) * p
    return after


def shift(cell, mass):
    """Apply the hidden transition that follows one decision step (not each of a step's
    `certain` follow-up calls); cells without `moves` are static."""
    if not cell.moves:
        return mass
    moved = {}
    for (root, state), weight in mass.items():
        for target, p in cell.moves[state]:
            if p:
                moved[root, target] = moved.get((root, target), 0) + weight * p
    return moved


def solve(cell, mass, left, events, sees, policy=None, ban=(), table=None, x=None, quote=None,
          tolerance=Q(), force=None, choose=None):
    """Exact (completion mass, fee mass) from one information state on; see autoresearch.solve.
    `force` fixes the action at this node only. `choose(candidates, total)` replaces the pairwise
    tolerance comparison by a rule that sees all (action, value) candidates of a node at once, so
    its result cannot depend on the order in which they are compared."""
    options = [a for a in legal(cell.graph, events, left, cell.diagnostic) if a not in ban]
    if policy is not None:
        choice = policy(View(x, quote, events, left, cell.graph))
        options = [choice if choice in options else STOP]
    if force is not None:
        options = [force if force in options else STOP]
    best, candidates = None, []
    for action in options:
        value = (Q(), Q())
        if action != STOP:
            step = None if action == DIAGNOSE else next(
                s for s in cell.graph[position(cell.graph, events)] if s.tool == action)
            completion = fee = Q()
            merged = defaultdict(dict)
            for label, part in branches(cell, mass, action, events).items():
                for (root, _), weight in part.items():
                    prices = cell.roots[root][2]
                    fee += weight * (prices.diagnostic if step is None else prices.of(action))
                if label in (DONE, PASS):
                    fee += sum(part.values(), Q()) * step.certain
                if label == DONE:
                    completion += sum(part.values(), Q())
                    continue
                channel = "signal" if step is None else "detail"
                seen = merged[label if label == PASS or channel in sees else None]
                for key, weight in part.items():
                    seen[key] = seen.get(key, Q()) + weight
            for label, part in merged.items():
                spent = 1 + (step.certain if label == PASS else 0)
                c, f = solve(cell, shift(cell, part), left - spent, events + ((action, label),), sees, policy,
                             ban, table, x, quote, tolerance, None, choose)
                completion, fee = completion + c, fee + f
            value = (completion, fee)
        candidates.append((action, value))
        if choose is None and (best is None or better(value, best[1], tolerance * sum(mass.values(), Q()))):
            best = (action, value)
    if choose is not None:
        best = choose(candidates, sum(mass.values(), Q()))
    if table is not None:
        table[x, quote, events] = best[0]
    return best[1]


def groups(cell, sees):
    grouped = defaultdict(dict)
    for root, (p, x, quote, prior) in enumerate(cell.roots):
        for state, ps in prior:
            if p * ps:
                grouped[x if "x" in sees else None, quote if "quote" in sees else None][root, state] = p * ps
    return grouped


def value(cell, policy=None, sees=PUBLIC, ban=(), table=None, tolerance=Q()):
    """(strict completion probability, expected remaining fee) over the whole cell."""
    sees = PUBLIC if policy is not None else frozenset(sees)
    completion = fee = Q()
    for (x, quote), mass in groups(cell, sees).items():
        c, f = solve(cell, mass, cell.left, (), sees, policy, ban, table, x, quote, tolerance)
        completion, fee = completion + c, fee + f
    return completion, fee


def oracle(cell):
    """Reference that knows the hidden state (not future coin flips); never a ranked method."""
    completion = fee = Q()
    for root, (p, _, _, prior) in enumerate(cell.roots):
        for state, ps in prior:
            if p * ps:
                c, f = solve(cell, {(root, state): p * ps}, cell.left, (), PUBLIC)
                completion, fee = completion + c, fee + f
    return completion, fee


def first_values(cell, x, quote):
    """Exact value of each first action at one public root, followed by the strict optimum."""
    mass = groups(cell, PUBLIC)[x, quote]
    total = sum(mass.values(), Q())
    found = {}
    for action in legal(cell.graph, (), cell.left, cell.diagnostic):
        c, f = solve(cell, mass, cell.left, (), PUBLIC, force=action)
        found[action] = (c / total, f / total)
    return found


def at_root(cell, policy, x, quote):
    """Exact value of a policy from one public root, as conditional probabilities."""
    mass = groups(cell, PUBLIC)[x, quote]
    total = sum(mass.values(), Q())
    c, f = solve(cell, mass, cell.left, (), PUBLIC, policy, x=x, quote=quote)
    return c / total, f / total


# ---- Simple rules. Each reads a View and nothing else. ----

def priority(order, limits=None):
    """Fixed order over tools: call the first tool in `order` that is offered, still
    affordable and has failed fewer than its limit (default once); stop when none is left."""
    limits = limits or {}

    def choose(view):
        options = view.legal()
        return next((tool for tool in order if tool in options and view.fails(tool) < limits.get(tool, 1)), STOP)
    return choose


def by_context(rules):
    return lambda view: rules[view.x](view) if view.x in rules else STOP


# ---- Legal history and policies learned from it. ----

def simulate(cell, behaviour, n, seed, insider=False):
    """n logged episodes holding x, prices, steps, completion and fee; never the hidden state."""
    rng, rows = stream(seed, f"041:{cell.name}"), []
    for _ in range(n):
        _, x, quote, prior = cell.roots[draw(rng, [(i, r[0]) for i, r in enumerate(cell.roots)])]
        state = draw(rng, prior)
        fault = cell.faults[state]
        events, left, steps, fee, done = (), cell.left, [], Q(), False
        while not done:
            view = View(x, quote, events, left, cell.graph)
            action = behaviour(view, rng, state) if insider else behaviour(view, rng)
            if action == STOP or action not in view.legal():
                break
            spent = 1
            if action == DIAGNOSE:
                seen, fee = draw(rng, fault.signal), fee + quote.diagnostic
            else:
                step = next(s for s in cell.graph[position(cell.graph, events)] if s.tool == action)
                ok = rng.random() < float(chance(fault.rates[action], events))
                done = ok and step.to == DONE
                seen = DONE if done else PASS if ok else draw(rng, fault.detail.get(action) or ((None, Q(1)),))
                fee += quote.of(action) + (step.certain if ok else 0)
                spent += step.certain if ok else 0
            steps.append((events, action, seen))
            events, left = events + ((action, seen),), left - spent
        rows.append({"x": x, "quote": quote, "steps": steps, "done": done, "fee": fee})
    return rows


def uniform(view, rng):
    """Randomized logging policy: every legal non-stop action with equal probability."""
    options = [a for a in view.legal() if a != STOP]
    return options[rng.randrange(len(options))] if options else STOP


def deterministic(policy):
    return lambda view, rng: policy(view)


def fit(history, key=lambda x, quote: x):
    """Action-outcome counts at observable nodes. The default key pools prices."""
    counts = defaultdict(lambda: defaultdict(int))
    for row in history:
        context = key(row["x"], row["quote"])
        for events, action, seen in row["steps"]:
            counts[context, events, action][seen] += 1
    return counts


class Planner:
    """Action-conditioned values from counts, priced with the current task's prices.

    Point estimates are frequencies, as in experiment 040. `compare` selects how two
    actions' completion estimates are compared before fee decides:
      ("tolerance", d)        tie when they differ by at most d (d = 0 is strict)
      ("interval", z, guard)  drop only actions whose upper bound is below the best
                              lower bound, bounds being estimate +/- z posterior sd;
                              with guard, stopping is never preferred to an action
                              whose estimated completion is positive
      ("lcb", z)              strict comparison of lower bounds
      ("within", d)           the cheapest action whose completion is within d of the highest;
                              unlike "tolerance" the result does not depend on comparison order
      ("priced", r)           the highest completion - r * fee: a total order
      ("noninferior", d, z)   take the action with the highest estimate unless a cheaper
                              one is credibly within d of it (its lower bound, estimate
                              - z posterior sd, is at least the highest estimate - d);
                              uncertainty therefore never favours the cheaper action,
                              and stopping is never preferred to a positive estimate
    The posterior sd comes from a Dirichlet prior of weight `prior` on every public
    outcome label and is propagated up the estimated tree assuming independent nodes.

    `untried=True` changes execution only: where the plan would stop, or nothing has
    support, an affordable tool that has not failed in this episode and has no support
    at this node is called first. Planning still values unsupported branches at zero.
    """

    def __init__(self, counts, cell, key=lambda x, quote: x, compare=("tolerance", Q()), prior=0.5,
                 fallback=None, untried=False):
        self.counts, self.key, self.compare, self.prior = counts, key, compare, prior
        self.graph, self.alphabet = cell.graph, cell.alphabet()
        self.fallback, self.untried = fallback, untried
        self.cache = {}

    def estimate(self, context, quote, events, left, action, policy):
        """(completion, fee, completion variance) of one supported action, or None."""
        seen = self.counts.get((context, events, action), {})
        total, labels = sum(seen.values()), self.alphabet[action]
        if not total:
            return None
        step, price = None, quote.diagnostic
        if action != DIAGNOSE:
            step = next(s for s in self.graph[position(self.graph, events)] if s.tool == action)
            price, labels = quote.of(action), (DONE if step.to == DONE else PASS, *labels)
        completion, fee, mean, square, spread = Q(), price, 0.0, 0.0, 0.0
        weight = total + self.prior * len(labels)
        for label in labels:
            p, soft = Q(seen.get(label, 0), total), (seen.get(label, 0) + self.prior) / weight
            if label == DONE:
                c, f, v = Q(1), Q(step.certain), 0.0
            elif p:
                spent = 1 + (step.certain if label == PASS else 0)
                c, f, v = self.node(context, quote, events + ((action, label),), left - spent, policy)[1]
                f += step.certain if label == PASS else 0
            else:
                c, f, v = Q(), Q(), 0.0
            completion, fee = completion + p * c, fee + p * f
            mean, square = mean + soft * float(c), square + soft * float(c) ** 2
            spread += (soft * (1 - soft) / (weight + 1) + soft ** 2) * v
        return completion, fee, max(square - mean ** 2, 0.0) / (weight + 1) + spread

    def node(self, context, quote, events, left, policy=None):
        """(action, (completion, fee, variance), all supported values) at one estimated node."""
        cached = (context, quote, events, left, policy)
        if cached not in self.cache:
            options = legal(self.graph, events, left, quote.diagnostic is not None)
            if policy is not None:
                options = [a for a in (policy(View(None, quote, events, left, self.graph)),) if a in options]
            values = {STOP: (Q(), Q(), 0.0)}
            for action in options:
                found = self.estimate(context, quote, events, left, action, policy) if action != STOP else None
                if found is not None:
                    values[action] = found
            if policy is not None:
                chosen = options[0] if options and options[0] in values else STOP
            else:
                chosen = self.choose(values)
            self.cache[cached] = (chosen, values[chosen], values)
        return self.cache[cached]

    def choose(self, values):
        order = [a for a in values if a != STOP] + [STOP]
        kind = self.compare[0]
        if kind == "tolerance":
            chosen = STOP
            for action in order:
                if better(values[action][:2], values[chosen][:2], self.compare[1]):
                    chosen = action
            return chosen
        if kind == "within":
            top = max(values[a][0] for a in order)
            return min((a for a in order if values[a][0] >= top - self.compare[1]),
                       key=lambda a: (values[a][1], order.index(a)))
        if kind == "priced":
            return max(order, key=lambda a: (values[a][0] - self.compare[1] * values[a][1], -order.index(a)))
        if kind == "noninferior":
            margin, z = float(self.compare[1]), self.compare[2]
            top = max(values[a][0] for a in order)
            lead = min((a for a in order if values[a][0] == top), key=lambda a: (values[a][1], order.index(a)))
            keep = [a for a in order
                    if a == lead or float(values[a][0]) - z * sqrt(values[a][2]) >= float(top) - margin]
            if any(values[a][0] > 0 for a in keep if a != STOP):
                keep = [a for a in keep if a != STOP]
            return min(keep, key=lambda a: (values[a][1], order.index(a)))
        z = self.compare[1]
        low = {a: float(values[a][0]) - z * sqrt(values[a][2]) for a in order}
        if kind == "lcb":
            return min(order, key=lambda a: (-low[a], values[a][1], order.index(a)))
        keep = [a for a in order if float(values[a][0]) + z * sqrt(values[a][2]) >= max(low.values())]
        if self.compare[2] and any(values[a][0] > 0 for a in keep if a != STOP):
            keep = [a for a in keep if a != STOP]
        return min(keep, key=lambda a: (values[a][1], order.index(a)))

    def __call__(self, view):
        action, _, values = self.node(self.key(view.x, view.quote), view.quote, view.events, view.left)
        if len(values) > 1 and (action != STOP or not self.untried):
            return action
        options = view.legal()
        if self.untried:
            failed = {e[0] for e in view.events if e[1] != PASS}
            return next((a for a in options if a not in (STOP, DIAGNOSE, *failed) and a not in values), STOP)
        return next((a for a in self.fallback or options if a in options), STOP)

    def select(self, candidates, tasks, left):
        """Name of the candidate rule with the best estimated value over (weight, x, quote) tasks,
        compared with this planner's tolerance (rules are compared on point estimates only)."""
        weights = defaultdict(Q)
        for w, x, quote in tasks:
            weights[x, quote] += w
        total, best = sum(weights.values(), Q()), None
        tolerance = self.compare[1] if self.compare[0] == "tolerance" else Q()
        for name, rule in candidates.items():
            pairs = [(w / total, self.node(self.key(x, quote), quote, (), left, rule)[1])
                     for (x, quote), w in weights.items()]
            score = tuple(sum((w * v[i] for w, v in pairs), Q()) for i in (0, 1))
            if best is None or better(score, best[1], tolerance):
                best = (name, score)
        return best[0]
