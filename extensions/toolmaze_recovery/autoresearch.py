"""Experiment 040: CPU-only decision model of recovery after the first primary timeout.

A cell is a small partially observable decision problem laid over the Gate 34
fixture's two paths: three calls finish the task after a successful primary
read, four after a successful backup read, and six calls remain once the first
timeout is spent. Values are exact rationals (strict completion probability,
expected remaining fee) compared lexicographically. Nothing here calls a model
or an executor. A policy receives a View only; hidden states never leave this
module's generator, and logged histories hold legal observations only.
"""
from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction as Q

from .gate34a import stream

RETRY, SWITCH, DIAGNOSE, STOP = "retry", "switch", "diagnose", "stop"
ACTIONS = (SWITCH, RETRY, DIAGNOSE, STOP)  # also the order that breaks exact ties
CALLS_LEFT, PRIMARY_PATH, BACKUP_PATH = 6, 3, 4
PUBLIC = frozenset(("x", "quote", "detail", "signal"))
HINTS = ("transient_hint", "persistent_hint")


@dataclass(frozen=True)
class Quote:
    """Public prices of one task. Only first-call prices vary and the primary
    read never costs less than 1, so finishing a started path stays best."""
    backup: Q = Q(1)
    diagnostic: Q = None
    primary: Q = Q(1)

    def fee(self, action, ok=False):
        if action == DIAGNOSE:
            return self.diagnostic
        first, rest = (self.primary, PRIMARY_PATH - 1) if action == RETRY else (self.backup, BACKUP_PATH - 1)
        return first + rest if ok else first

    def break_even(self):
        """Retry success rate above which retry-then-switch is cheaper than switching."""
        saving = self.fee(SWITCH, True) - self.fee(RETRY, True)
        return Q(1) if saving <= 0 else self.primary / (self.primary + saving)


@dataclass(frozen=True)
class Fault:
    """One hidden failure state; attempts are independent given the state. A rate is a
    constant, or a tuple indexed by the calls made since the first timeout (the last
    entry repeats), which is how a fault that clears after some calls is written."""
    retry: object       # P(a primary read succeeds)
    backup: object = Q(1)  # P(a backup read succeeds)
    detail: tuple = ()  # ((label, P(label | failed primary read)), ...)
    signal: tuple = ()  # ((label, P(label | diagnostic call)), ...)


@dataclass(frozen=True)
class Cell:
    name: str
    faults: dict              # hidden state -> Fault
    roots: tuple              # ((P, x, Quote, ((state, P(state | x, quote)), ...)), ...)
    first_detail: bool = False  # the first timeout already carries a detail label
    left: int = CALLS_LEFT      # calls left once the first timeout is spent

    @property
    def diagnostic(self):
        return self.roots[0][2].diagnostic is not None

    def alphabet(self):
        """Public outcome labels of each action, known from the tool contracts."""
        details = sorted({label for f in self.faults.values() for label, _ in f.detail}) or [None]
        signals = sorted({label for f in self.faults.values() for label, _ in f.signal})
        return {RETRY: (True, *details), SWITCH: (True, None), DIAGNOSE: tuple(signals)}


def build(name, faults, contexts, quotes=((Quote(), Q(1)),), first_detail=False, left=CALLS_LEFT):
    """Independent public context and quote: contexts is {x: (P(x), {state: P(state | x)})}."""
    roots = tuple((px * pq, x, quote, tuple(prior.items()))
                  for x, (px, prior) in contexts.items() for quote, pq in quotes)
    return Cell(name, faults, roots, first_detail, left)


def rate(spec, events):
    if not isinstance(spec, tuple):
        return spec
    return spec[min(sum(e[0] != "first" for e in events), len(spec) - 1)]


@dataclass(frozen=True)
class View:
    """Everything a policy may read."""
    x: object
    quote: Quote
    events: tuple  # (("first", detail),)? then (action, observation) of each non-completing step
    left: int

    def legal(self):
        return legal(self.left, self.events, self.quote.diagnostic is not None)

    def count(self, action):
        return sum(e[0] == action for e in self.events)

    def last(self, *kinds):
        return next((e[1] for e in reversed(self.events) if e[0] in kinds), None)


def legal(left, events, diagnostic):
    """A path may start only if the call budget can still finish it."""
    options = [SWITCH] if left >= BACKUP_PATH else []
    if left >= PRIMARY_PATH:
        options.append(RETRY)
    if diagnostic and left >= 1 and all(e[0] != DIAGNOSE for e in events):
        options.append(DIAGNOSE)
    return (*options, STOP)


def better(a, b, tolerance=Q()):
    """Lexicographic: completion first, then fee. Completions within tolerance tie."""
    return a[1] < b[1] if abs(a[0] - b[0]) <= tolerance else a[0] > b[0]


def branches(cell, mass, action, events=()):
    """Split joint mass {(root, state): weight} by one action's outcome."""
    done, after = {}, defaultdict(dict)
    for (root, state), weight in mass.items():
        fault = cell.faults[state]
        if action == DIAGNOSE:
            for label, p in fault.signal:
                if p:
                    after[label][root, state] = weight * p
            continue
        ok = rate(fault.retry if action == RETRY else fault.backup, events)
        if ok:
            done[root, state] = weight * ok
        for label, p in (fault.detail if action == RETRY and fault.detail else ((None, Q(1)),)):
            if p and ok < 1:
                after[label][root, state] = weight * (1 - ok) * p
    return done, after


def solve(cell, mass, left, events, sees, policy=None, ban=(), table=None, x=None, quote=None,
          tolerance=Q()):
    """Exact (completion mass, fee mass) from one information state on.

    Without a policy this is the lexicographic optimum over everything that
    conditions only on `sees`; unseen labels merge into one information state.
    A positive `tolerance` ties completion probabilities that close at each node.
    """
    def fees(part, action, ok):
        return sum((w * cell.roots[root][2].fee(action, ok) for (root, _), w in part.items()), Q())

    options = [a for a in legal(left, events, cell.diagnostic) if a not in ban]
    if policy is not None:
        choice = policy(View(x, quote, events, left))
        options = [choice if choice in options else STOP]
    best = None
    for action in options:
        value = (Q(), Q())
        if action != STOP:
            done, after = branches(cell, mass, action, events)
            completion, fee = sum(done.values(), Q()), fees(done, action, True)
            merged = defaultdict(dict)
            channel = "signal" if action == DIAGNOSE else "detail"
            for label, part in after.items():
                fee += fees(part, action, False)
                seen = merged[label if channel in sees else None]
                for key, weight in part.items():
                    seen[key] = seen.get(key, Q()) + weight
            for label, part in merged.items():
                c, f = solve(cell, part, left - 1, events + ((action, label),), sees, policy, ban, table,
                             x, quote, tolerance)
                completion, fee = completion + c, fee + f
            value = (completion, fee)
        if best is None or better(value, best[1], tolerance * sum(mass.values(), Q())):
            best = (action, value)
    if table is not None:
        table[x, quote, events] = best[0]
    return best[1]


def value(cell, policy=None, sees=PUBLIC, ban=(), table=None, tolerance=Q()):
    """(strict completion probability, expected remaining fee) over the whole cell."""
    sees = PUBLIC if policy is not None else frozenset(sees)
    groups = defaultdict(dict)
    for root, (p, x, quote, prior) in enumerate(cell.roots):
        for state, ps in prior:
            for label, pl in (cell.faults[state].detail if cell.first_detail else ((None, Q(1)),)):
                first = (("first", label if "detail" in sees else None),) if cell.first_detail else ()
                group = groups[x if "x" in sees else None, quote if "quote" in sees else None, first]
                group[root, state] = group.get((root, state), Q()) + p * ps * pl
    completion = fee = Q()
    for (x, quote, events), mass in groups.items():
        c, f = solve(cell, mass, cell.left, events, sees, policy, ban, table, x, quote, tolerance)
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


# ---- Named simple rules. Each reads a View and nothing else. ----

def fixed(retries, backups=3, guard=True):
    """Retry up to `retries` times, then the backup up to `backups` times, then stop.
    With `guard` a retry is skipped when its failure would leave the backup unaffordable."""
    def choose(view):
        if (not view.count(SWITCH) and view.count(RETRY) < retries and RETRY in view.legal()
                and (view.left - 1 >= BACKUP_PATH or not guard)):
            return RETRY
        return SWITCH if view.count(SWITCH) < backups and SWITCH in view.legal() else STOP
    return choose


def order(*actions):
    """A fixed sequence of attempts, one per call since the first timeout, then stop."""
    def choose(view):
        step = sum(e[0] != "first" for e in view.events)
        return actions[step] if step < len(actions) and actions[step] in view.legal() else STOP
    return choose


def recent_feedback(good, first=RETRY):
    """Retry while the latest primary error detail is in `good`; otherwise switch."""
    def choose(view):
        detail = view.last("first", RETRY)
        wants = (detail in good) if (view.events and view.events[-1][0] in ("first", RETRY)) else first == RETRY
        if wants and not view.count(SWITCH) and RETRY in view.legal() and view.left - 1 >= BACKUP_PATH:
            return RETRY
        return SWITCH if SWITCH in view.legal() else STOP
    return choose


def cost_threshold(rate):
    """One global success-rate guess against the current quote's break-even rate."""
    return lambda view: (fixed(1) if rate > view.quote.break_even() else fixed(0))(view)


def by_context(rules):
    return lambda view: rules[view.x](view)


def simple_feedback(view):
    """Macro form of the frozen gate34b.feedback_tool: buy a diagnostic priced at most
    1/10, switch on persistent_hint or after one failed retry, otherwise retry."""
    if view.count(RETRY) or view.count(SWITCH):
        return SWITCH if SWITCH in view.legal() else STOP
    if DIAGNOSE in view.legal() and view.quote.diagnostic <= Q(1, 10):
        return DIAGNOSE
    if view.last(DIAGNOSE) == HINTS[1]:
        return SWITCH
    return RETRY if RETRY in view.legal() else STOP


# ---- Legal history: sampled episodes, counts and policies learned from them. ----

def draw(rng, pairs):
    point, total = rng.random(), 0.0
    for item, p in pairs:
        total += float(p)
        if point < total:
            return item
    return pairs[-1][0]


def simulate(cell, behaviour, n, seed, insider=False):
    """n logged episodes holding x, quote, steps, completion and fee; never the hidden state.

    `insider` models a logging policy that also saw the hidden state; its logs
    still omit that state, which is what makes them confounded.
    """
    rng, rows = stream(seed, f"040:{cell.name}"), []
    for _ in range(n):
        _, x, quote, prior = cell.roots[draw(rng, [(i, r[0]) for i, r in enumerate(cell.roots)])]
        state = draw(rng, prior)
        fault = cell.faults[state]
        events = (("first", draw(rng, fault.detail)),) if cell.first_detail else ()
        left, steps, fee, done = cell.left, [], Q(), False
        while not done:
            view = View(x, quote, events, left)
            action = behaviour(view, rng, state) if insider else behaviour(view, rng)
            if action == STOP or action not in view.legal():
                break
            if action == DIAGNOSE:
                seen = draw(rng, fault.signal)
            else:
                done = rng.random() < float(rate(fault.retry if action == RETRY else fault.backup, events))
                seen = True if done else draw(rng, fault.detail) if action == RETRY and fault.detail else None
            fee += quote.fee(action, done)
            steps.append((events, action, seen))
            events, left = events + ((action, seen),), left - 1
        rows.append({"x": x, "quote": quote, "steps": steps, "done": done, "fee": fee})
    return rows


def uniform(view, rng):
    """Randomized logging policy: every legal non-stop action with equal probability."""
    options = [a for a in view.legal() if a != STOP]
    return options[rng.randrange(len(options))] if options else STOP


def deterministic(policy):
    return lambda view, rng: policy(view)


def fit(history, key=lambda x, quote: x):
    """Action-outcome counts at observable nodes. The default key pools quotes."""
    counts = defaultdict(lambda: defaultdict(int))
    for row in history:
        context = key(row["x"], row["quote"])
        for events, action, seen in row["steps"]:
            counts[context, events, action][seen] += 1
    return counts


class Planner:
    """Action-conditioned values from counts, priced with the current task's quote.

    An action without support at a node is not considered, and a node with no
    supported action is worth (0, 0) to its parent; there the executed action is
    the registered fallback. `tolerance` treats close completion estimates as tied.
    """

    def __init__(self, counts, alphabet, key=lambda x, quote: x, smooth=Q(), tolerance=Q(),
                 fallback=SWITCH):
        self.counts, self.alphabet, self.key = counts, alphabet, key
        self.smooth, self.tolerance, self.fallback = smooth, tolerance, fallback
        self.cache = {}

    def outcome(self, context, events, action):
        seen = self.counts.get((context, events, action), {})
        total, labels = sum(seen.values()), self.alphabet[action]
        if not total:
            return None
        return {label: (seen.get(label, 0) + self.smooth) / (total + self.smooth * len(labels))
                for label in labels}

    def node(self, context, quote, events, left, policy=None):
        """(action, its value, all supported values) at one estimated node."""
        cached = (context, quote, events, left, policy)
        if cached not in self.cache:
            values = {STOP: (Q(), Q())}
            options = legal(left, events, quote.diagnostic is not None)
            if policy is not None:
                options = [a for a in (policy(View(None, quote, events, left)),) if a in options]
            for action in options:
                chances = self.outcome(context, events, action) if action != STOP else None
                if chances is None:
                    continue
                completion = fee = Q()
                for label, p in chances.items():
                    if label is True:
                        completion, fee = completion + p, fee + p * quote.fee(action, True)
                    elif p:
                        c, f = self.node(context, quote, events + ((action, label),), left - 1, policy)[1]
                        completion, fee = completion + p * c, fee + p * (quote.fee(action) + f)
                values[action] = (completion, fee)
            chosen = STOP
            for action in ACTIONS:
                if action in values and better(values[action], values[chosen], self.tolerance):
                    chosen = action
            self.cache[cached] = (chosen, values[chosen], values)
        return self.cache[cached]

    def __call__(self, view):
        action, _, values = self.node(self.key(view.x, view.quote), view.quote, view.events, view.left)
        if len(values) > 1:
            return action
        return next(a for a in (self.fallback, RETRY, STOP) if a in view.legal())

    def select(self, candidates, tasks, left=CALLS_LEFT):
        """Name of the candidate with the best estimated value over (weight, x, quote) tasks.
        A candidate maps x to a rule, because estimated nodes carry no x."""
        weights = defaultdict(Q)
        for w, x, quote in tasks:
            weights[x, quote] += w

        def estimate(rule):
            rules = {x: rule(x) for x, _ in weights}
            pairs = [(w, self.node(self.key(x, quote), quote, (), left, rules[x])[1])
                     for (x, quote), w in weights.items()]
            return tuple(sum((w * v[i] for w, v in pairs), Q()) for i in (0, 1))
        best = None
        for name, rule in candidates.items():
            score = estimate(rule)
            if best is None or better(score, best[1], self.tolerance):
                best = (name, score)
        return best[0]


def btm_statistics(history):
    """Episode-level Beta means, as extensions/action_conditioned_recovery/learn.py keys them:
    final strict completion of training episodes after a (tool, error) key, and after a switch."""
    task, switch = defaultdict(list), []
    for row in history:
        keys = {row["steps"][0][0][0][1]} if row["steps"] and row["steps"][0][0] else {None}
        keys |= {seen for _, action, seen in row["steps"] if action == RETRY and seen is not True}
        for key in keys:
            task[key].append(row["done"])
        if any(action == SWITCH for _, action, _ in row["steps"]):
            switch.append(row["done"])

    def beta(records):
        return Q(1 + sum(records), 2 + len(records))
    return {"recovery": {key: beta(records) for key, records in task.items()}, "switch": beta(switch),
            "support": {"recovery": {key: len(records) for key, records in task.items()}, "switch": len(switch)}}


def btm_style(statistics, bar=Q(1), poor=None):
    """Deterministic CPU proxy of the BTM prompt clauses (gate18.BTM_RETRY, BTM_GUIDANCE,
    BTM_CONSTRAINTS): the same tool again at least once; another try only while the
    (tool, error) recovery belief exceeds `bar` (None: the switch belief); stop only
    when no route is left, or, with `poor`, once both beliefs are below it after that
    first retry ("when both look poor ... stop"). It never buys a diagnostic and never
    reads x or prices. This is not the original BTM, where an LLM reads these statistics."""
    def choose(view):
        options = view.legal()
        if not view.count(SWITCH):
            belief = statistics["recovery"].get(view.last("first", RETRY), Q(1, 2))
            if poor is not None and view.count(RETRY) and belief < poor and statistics["switch"] < poor:
                return STOP
            if RETRY in options and view.left - 1 >= BACKUP_PATH and (
                    not view.count(RETRY) or belief > (statistics["switch"] if bar is None else bar)):
                return RETRY
            return next(a for a in (SWITCH, RETRY, STOP) if a in options)
        order = (SWITCH, RETRY, STOP) if view.count(SWITCH) == 1 else (RETRY, SWITCH, STOP)
        return next(a for a in order if a in options)
    return choose
