"""Simple-rule baselines for experiment 042. These are NOT the project's method.

A rule here reads plain success frequencies from the logged history and follows a fixed
recipe. It builds no model, estimates no values, runs no planner and never looks ahead,
so it shares nothing with the action-conditioned planner or the hidden-state model it is
compared against. Every threshold is fixed in advance and none is tuned on results.
"""
from collections import defaultdict

from .autoresearch import DIAGNOSE, STOP
from .multipath import DONE, PASS, position

SUPPORT = 5  # calls needed before a frequency is used


def _last(events):
    """The most recent feedback as the agent saw it: (tool, what came back), or None at the start."""
    if not events:
        return None
    action, seen = events[-1]
    return action, ("ok" if seen in (DONE, PASS) else seen)


class LastFeedbackRule:
    """Call the tool that most often succeeded right after the same most recent feedback, per unit of
    its public cost on success (its price plus the calls that follow a success automatically).

    Frequencies are looked up at three levels and the first with at least SUPPORT calls is used:
    (context, last feedback, tool), then (context, tool), then (tool). A tool never seen to succeed
    at the level used is not called; a tool with too few calls at every level is tried after the
    known ones. When nothing is left the rule stops. With `diagnose_first` it buys the diagnostic
    as its first action whenever one is offered, and the signal then counts as the last feedback."""

    def __init__(self, history, diagnose_first=False):
        self.diagnose_first = diagnose_first
        self.levels = [defaultdict(lambda: [0, 0]) for _ in range(3)]
        for row in history:
            for events, action, seen in row["steps"]:
                if action == DIAGNOSE:
                    continue
                for level, key in zip(self.levels, ((row["x"], _last(events), action), (row["x"], action), action)):
                    level[key][0] += seen in (DONE, PASS)
                    level[key][1] += 1

    def rate(self, x, last, tool):
        for level, key in zip(self.levels, ((x, last, tool), (x, tool), tool)):
            hits, calls = level.get(key, (0, 0))
            if calls >= SUPPORT:
                return hits / calls
        return None

    def __call__(self, view):
        options = [a for a in view.legal() if a not in (STOP, DIAGNOSE)]
        if self.diagnose_first and not view.events and DIAGNOSE in view.legal():
            return DIAGNOSE
        last, known, unknown = _last(view.events), [], []
        follow = {step.tool: step.certain for step in view.graph[position(view.graph, view.events)]}
        for tool in options:
            rate = self.rate(view.x, last, tool)
            if rate is None:
                unknown.append(tool)
            elif rate > 0:
                known.append((-rate / float(view.quote.of(tool) + follow[tool]), len(known), tool))
        if known:
            return min(known)[2]
        return unknown[0] if unknown else STOP
