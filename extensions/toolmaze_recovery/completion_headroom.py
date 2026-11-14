"""Experiment 047: completion-rate headroom when a write may have committed silently.

After a first write ends in an ambiguous failure, the hidden state is the number of
committed publications n (0, 1, 2) and the writer status w (transient, primary down,
shared backend down). Writing again after a silent commit makes n=2, which no later
action can undo. A read-back is a paid, possibly noisy or failing, explicit diagnosis.
Round 2 adds an unreliable backup writer, a backup route of several calls (prepare
then confirm), failing read-backs and lagged (one-sided) read-back noise; the defaults
reproduce round 1 exactly.

Values are (strict completion probability, expected remaining fee), compared
lexicographically with a 1e-9 completion tie. Floats are used for speed. Policies
see only the first-failure detail and their own receipts; hidden states stay in the
mass vectors, which merge every state consistent with what was seen.
"""
from dataclasses import dataclass
from itertools import product

RETRY, SWITCH, READ, FINISH, STOP = "retry", "switch", "read", "finish", "stop"
CALLS = (RETRY, SWITCH, READ)
WRITES = (RETRY, SWITCH)
T, P, S = 0, 1, 2  # writer status
STATES = tuple((n, w) for n in range(3) for w in (T, P, S))
INDEX = {s: i for i, s in enumerate(STATES)}
TIE = 1e-9
DETAIL = {  # P(timeout | category); categories C (silent commit), T, P, S
    "none": {"C": 0.5, "T": 0.5, "P": 0.5, "S": 0.5},
    "weak": {"C": 0.7, "T": 0.5, "P": 0.4, "S": 0.4},
    "strong": {"C": 0.95, "T": 0.5, "P": 0.2, "S": 0.2},
}


@dataclass(frozen=True)
class Cell:
    left: int = 4
    q_commit: float = 0.3          # P(the first ambiguous failure committed silently)
    split: tuple = (0.6, 0.3, 0.1)  # (T, P, S) among uncommitted first failures
    p_retry: float = 0.8           # P(a retry commits with a receipt | transient)
    c_lost: float = 0.0            # P(a failed write still committed | writer not down)
    accuracy: float = 1.0          # P(found | committed); also P(missing | not) when symmetric
    read_fee: float = 0.5
    detail: str = "none"
    retry_fee: float = 1.0
    switch_fee: float = 2.0
    p_switch: float = 1.0          # P(the backup route commits with a receipt | not shared)
    backup_calls: int = 1          # calls the backup route needs (2: prepare then confirm)
    read_fail: float = 0.0         # P(a read-back returns an error without state evidence)
    read_noise: str = "symmetric"  # "lag": an uncommitted write is never read as found

    def fee(self, action):
        return {RETRY: self.retry_fee, SWITCH: self.switch_fee, READ: self.read_fee}[action]

    def calls(self, action):
        return self.backup_calls if action == SWITCH else 1

    def prior(self):
        """{category: (state, P(category))}."""
        rest = 1 - self.q_commit
        return {"C": ((1, T), self.q_commit), "T": ((0, T), rest * self.split[0]),
                "P": ((0, P), rest * self.split[1]), "S": ((0, S), rest * self.split[2])}

    def roots(self):
        """{public first detail: mass vector}; the detail is all a policy sees at the start."""
        out = {}
        for label in ("timeout", "error"):
            mass = [0.0] * len(STATES)
            for category, (state, p) in self.prior().items():
                pt = DETAIL[self.detail][category]
                mass[INDEX[state]] += p * (pt if label == "timeout" else 1 - pt)
            out[label] = tuple(mass)
        return out


def step(cell, mass, action):
    """Split mass by one call. Returns (success mass, fee mass, {observation: mass}).
    A receipt ends the episode; success means exactly one publication."""
    success, branches = 0.0, {}
    fee = cell.fee(action) * sum(mass)

    def add(obs, state, weight):
        if weight:
            branches.setdefault(obs, [0.0] * len(STATES))[INDEX[state]] += weight

    for (n, w), weight in zip(STATES, mass):
        if not weight:
            continue
        if action == READ:
            add("error", (n, w), weight * cell.read_fail)
            ok = weight * (1 - cell.read_fail)
            if n >= 1:
                found = cell.accuracy
            else:
                found = 0.0 if cell.read_noise == "lag" else 1 - cell.accuracy
            add("found", (n, w), ok * found)
            add("missing", (n, w), ok * (1 - found))
            continue
        works = (w == T) if action == RETRY else (w != S)
        if not works:
            add("fail", (n, w), weight)
            continue
        rate = cell.p_retry if action == RETRY else cell.p_switch
        if n == 0:
            success += weight * rate
        add("fail", (min(n + 1, 2), w), weight * (1 - rate) * cell.c_lost)
        add("fail", (n, w), weight * (1 - rate) * (1 - cell.c_lost))
    return success, fee, {obs: tuple(m) for obs, m in branches.items()}


def finish(mass):
    return sum(weight for (n, _), weight in zip(STATES, mass) if n == 1)


def merge(*masses):
    present = [m for m in masses if m is not None]
    return tuple(map(sum, zip(*present))) if present else None


def better(a, b):
    return a[1] < b[1] if abs(a[0] - b[0]) <= TIE else a[0] > b[0]


def optimum(cell, mass, left, ban=(), cache=None):
    """Lexicographic optimum over policies that condition on observations only."""
    total = sum(mass)
    if total <= 0:
        return (0.0, 0.0)
    cache = {} if cache is None else cache
    key = (tuple(round(m / total, 12) for m in mass), left)
    if key in cache:
        c, f = cache[key]
        return (c * total, f * total)
    best = (0.0, 0.0)  # stop
    if FINISH not in ban and better((finish(mass), 0.0), best):
        best = (finish(mass), 0.0)
    for action in CALLS:
        if action in ban or left < cell.calls(action):
            continue
        completion, fee, branches = step(cell, mass, action)
        for part in branches.values():  # every observation is its own information state
            c, f = optimum(cell, part, left - cell.calls(action), ban, cache)
            completion, fee = completion + c, fee + f
        if better((completion, fee), best):
            best = (completion, fee)
    cache[key] = (best[0] / total, best[1] / total)
    return best


def sequence_value(cell, mass, actions, end):
    """A fixed order of calls, then `end` (FINISH or STOP). A receipt or a found
    read-back declares completion; any other observation moves to the next call."""
    completion = fee = 0.0
    for action in actions:
        c, f, branches = step(cell, mass, action)
        completion, fee = completion + c, fee + f
        if action == READ:
            if "found" in branches:
                completion += finish(branches["found"])
            mass = merge(branches.get("missing"), branches.get("error"))
        else:
            mass = branches.get("fail")
        if mass is None:
            return completion, fee
    if end == FINISH:
        completion += finish(mass)
    return completion, fee


def orders(left, options, backup_calls=1):
    """Every order of calls from `options` whose total calls fit in `left`."""
    def grow(prefix, used):
        yield prefix
        for action in options:
            need = backup_calls if action == SWITCH else 1
            if used + need <= left:
                yield from grow(prefix + (action,), used + need)
    return grow((), 0)


def sequences(left, backup_calls=1):
    for actions in orders(left, CALLS, backup_calls):
        for end in (FINISH, STOP):
            yield actions, end


def oracle(cell):
    """Knows the initial hidden state, not later coin flips; a reference only."""
    completion = fee = 0.0
    for state, p in cell.prior().values():
        if p:
            mass = [0.0] * len(STATES)
            mass[INDEX[state]] = p
            c, f = optimum(cell, tuple(mass), cell.left)
            completion, fee = completion + c, fee + f
    return completion, fee


NAMED = {"retry_then_switch": ((RETRY, SWITCH), STOP),
         "read_first": ((READ, RETRY, SWITCH), STOP)}


def vote_value(cell, mass, reads, need, actions, end):
    """Read back `reads` times, finish if at least `need` say found, otherwise run a
    fixed order of writes, then `end`. A read-back error counts as not found."""
    fee = cell.read_fee * reads * sum(mass)
    by_count = {0: mass}
    for _ in range(reads):
        nxt = {}
        for count, m in by_count.items():
            _, _, branches = step(cell, m, READ)
            for obs, part in branches.items():
                key = count + (obs == "found")
                nxt[key] = merge(nxt.get(key), part)
        by_count = nxt
    completion = 0.0
    for count, m in by_count.items():
        if count >= need:
            completion += finish(m)
        else:
            c, f = sequence_value(cell, m, actions, end)
            completion, fee = completion + c, fee + f
    return completion, fee


def best_vote(cell, mass):
    best = None
    for reads in range(1, cell.left + 1):
        for need in range(1, reads + 1):
            for actions in orders(cell.left - reads, WRITES, cell.backup_calls):
                for end in (FINISH, STOP):
                    v = vote_value(cell, mass, reads, need, actions, end)
                    if best is None or better(v, best[0]):
                        best = (v, (reads, need, actions, end))
    return best


def reread_value(cell, mass, actions, end, left, rereads, used=0):
    """Round-2 follow-up rule: a fixed order of calls in which a read-back that returns
    an error is repeated, at most `rereads` times, while the budget allows; calls that
    no longer fit are skipped. A receipt or a found read-back declares completion."""
    if mass is None or not actions:
        return ((finish(mass) if end == FINISH and mass is not None else 0.0), 0.0)
    action, rest = actions[0], actions[1:]
    if left < cell.calls(action):
        return reread_value(cell, mass, rest, end, left, rereads)
    completion, fee, branches = step(cell, mass, action)
    left -= cell.calls(action)
    if action == READ:
        completion += finish(branches["found"]) if "found" in branches else 0.0
        parts = [(branches.get("missing"), rest, 0)]
        if used < rereads and left >= 1:
            parts.append((branches.get("error"), actions, used + 1))
        else:
            parts.append((branches.get("error"), rest, 0))
    else:
        parts = [(branches.get("fail"), rest, 0)]
    for part, nxt, count in parts:
        if part is not None:
            c, f = reread_value(cell, part, nxt, end, left, rereads, count)
            completion, fee = completion + c, fee + f
    return completion, fee


def best_reread(cell, mass, max_rereads=2):
    best = None
    for rereads in range(1, max_rereads + 1):
        for actions, end in sequences(cell.left, cell.backup_calls):
            if READ not in actions:
                continue
            v = reread_value(cell, mass, actions, end, cell.left, rereads)
            if best is None or better(v, best[0]):
                best = (v, (rereads, actions, end))
    return best


def evaluate(cell, vote=False):
    """All reference values of one cell; `vote` adds the round-2 simple rule class FIX-V."""
    roots = cell.roots()
    cache = {}
    opt = [optimum(cell, mass, cell.left, cache=cache) for mass in roots.values()]
    no_read = [optimum(cell, mass, cell.left, ban=(READ,)) for mass in roots.values()]
    per_label, pooled = [], None
    scores = {label: [] for label in roots}
    for seq in sequences(cell.left, cell.backup_calls):
        values = {label: sequence_value(cell, mass, *seq) for label, mass in roots.items()}
        for label, v in values.items():
            scores[label].append((v, seq))
        total = tuple(sum(v[i] for v in values.values()) for i in (0, 1))
        if pooled is None or better(total, pooled[0]):
            pooled = (total, seq)
    for label in roots:
        best = None
        for v, seq in scores[label]:
            if best is None or better(v, best[0]):
                best = (v, seq)
        per_label.append(best)

    def add(values):
        return tuple(sum(v[i] for v in values) for i in (0, 1))

    named = {name: add([sequence_value(cell, mass, *seq) for mass in roots.values()])
             for name, seq in NAMED.items()}
    out = {
        "oracle": oracle(cell),
        "opt": add(opt),
        "opt_no_read": add(no_read),
        "fix_x": add([b[0] for b in per_label]),
        "fix_x_seq": {label: b[1] for label, b in zip(roots, per_label)},
        "fix": pooled[0],
        "fix_seq": pooled[1],
        **named,
    }
    if vote:
        picks = {}
        for (label, mass), fixed in zip(roots.items(), per_label):
            v = best_vote(cell, mass)
            picks[label] = v if better(v[0], fixed[0]) else (fixed[0], (0, 0) + fixed[1])
        out["fix_v"] = add([p[0] for p in picks.values()])
        out["fix_v_rule"] = {label: p[1] for label, p in picks.items()}
    return out


GRID = {
    "left": (3, 4, 6),
    "q_commit": (0.1, 0.3, 0.5),
    "split": ((0.6, 0.3, 0.1), (0.3, 0.5, 0.2), (0.2, 0.4, 0.4)),
    "p_retry": (0.5, 0.8),
    "c_lost": (0.0, 0.3),
    "accuracy": (1.0, 0.9, 0.7),
    "read_fee": (0.1, 0.5, 1.0),
    "detail": ("none", "weak", "strong"),
}

GRID2 = {
    "left": (4, 6),
    "q_commit": (0.1, 0.3, 0.5),
    "split": ((0.6, 0.3, 0.1), (0.3, 0.5, 0.2), (0.2, 0.4, 0.4)),
    "p_retry": (0.5, 0.8),
    "c_lost": (0.0, 0.3),
    "p_switch": (1.0, 0.7),
    "backup_calls": (1, 2),
    "accuracy": (1.0, 0.8),
    "read_noise": ("symmetric", "lag"),
    "read_fail": (0.0, 0.3),
    "detail": ("none", "strong"),
}


def grid(spec=GRID):
    keys = tuple(spec)
    for values in product(*(spec[k] for k in keys)):
        yield Cell(**dict(zip(keys, values)))
