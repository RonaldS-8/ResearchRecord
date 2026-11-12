"""Experiment 040 cells and rounds. Registered in docs/experiments/040-*.md before each run."""
from fractions import Fraction as Q

from .autoresearch import HINTS, Fault, Quote, build


def hint(gamma, transient):
    """Diagnostic signal law with accuracy gamma, in the fixture's public labels."""
    right, wrong = (HINTS[0], HINTS[1]) if transient else (HINTS[1], HINTS[0])
    return ((right, gamma), (wrong, 1 - gamma))


def binary(name, contexts, quotes=((Quote(), Q(1)),), gamma=None, backup=Q(1)):
    """Fast transient or persistent: contexts is {x: (P(x), P(transient | x))}."""
    faults = {"transient": Fault(Q(1), backup, signal=hint(gamma, True) if gamma else ()),
              "persistent": Fault(Q(0), backup, signal=hint(gamma, False) if gamma else ())}
    return build(name, faults, {x: (px, {"transient": p, "persistent": 1 - p})
                                for x, (px, p) in contexts.items()}, quotes)


def gate34(distribution, context=None):
    """The registered Gate 34 cells A, B and E as macro cells."""
    if distribution.cell == "B":
        names = (context,) if context else ("X1", "X2")
        contexts = {x: (Q(1, len(names)), distribution.transient_probability(x)) for x in names}
        return binary("B", contexts)
    contexts = {None: (Q(1), distribution.transient_probability())}
    if distribution.cell == "A":
        return binary("A", contexts)
    return binary("E", contexts, ((Quote(diagnostic=distribution.diagnostic_fee), Q(1)),), distribution.gamma)
