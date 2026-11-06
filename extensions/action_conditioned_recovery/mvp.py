"""Exact values and a restricted C2-018 recovery session for Gate 9."""
from fractions import Fraction as F

from extensions.toolmaze_belief_ssp.enumeration import diagnostic_probability, rank, weighted
from extensions.toolmaze_belief_ssp.replay import Replay, verify

PRIORS = {"A": F(3, 4), "B": F(1, 4), "feedback": F(1, 2)}
STATES = ("H", "P")
RETRY, SWITCH, DIAGNOSIS = F(1), F(2), F(1, 10)
POLICIES = {
    "switch": ("switch",),
    "retry_then_switch": ("retry", "switch"),
    "retry_only": ("retry", "stop"),
    "stop": ("stop",),
}


def values(p):
    return {
        "switch": (F(1), SWITCH),
        "retry_then_switch": (F(1), RETRY + (1 - p) * SWITCH),
        "retry_only": (p, RETRY),
        "stop": (F(0), F(0)),
    }


def best_policy(p):
    options = values(p)
    return max(options, key=lambda policy: rank(options[policy]))


def signal_outcomes(p, accuracy):
    for report in (False, True):
        healthy = p * diagnostic_probability("H", report, accuracy)
        blocked = (1 - p) * diagnostic_probability("P", report, accuracy)
        if healthy + blocked:
            yield report, healthy + blocked, healthy / (healthy + blocked)


def diagnostic_value(p, accuracy):
    return weighted(
        [(mass, values(posterior)[best_policy(posterior)])
         for _, mass, posterior in signal_outcomes(p, accuracy)],
        DIAGNOSIS,
    )


class Session:
    def __init__(self, context, state, accuracy=None, draw=F(1, 2)):
        if context not in PRIORS or state not in STATES:
            raise ValueError("Unknown context or fault state")
        if (context == "feedback") != (accuracy is not None):
            raise ValueError("Diagnostic calibration is limited to the feedback cell")
        self._context = context
        self._accuracy = accuracy
        self._replay = Replay(state, F(0), accuracy, DIAGNOSIS, {},
                              transition_draw=lambda: F(0), diagnostic_draw=lambda: draw)
        self._tools = F(0)
        self._diagnosis = F(0)

    def view(self):
        replay = self._replay
        view = replay.view()
        actions = []
        used = {d["action"] for d in replay.decisions}
        if not replay.done:
            actions = ["switch", "stop"]
            if "retry" not in used:
                actions.append("retry")
            if self._accuracy is not None and not used:
                actions.append("diagnose")
        public = {k: view[k] for k in ("task", "tools", "history", "decisions", "remaining_tools")}
        public.update(context=self._context, actions=actions, done=replay.done,
                      remaining_decisions=0 if replay.done else (
                          1 if "retry" in used else 2 + int("diagnose" in actions)
                      ), prices={"retry": str(RETRY), "switch": str(SWITCH)})
        if self._accuracy is not None:
            public["prices"]["diagnose"] = str(DIAGNOSIS)
            public["diagnostic_accuracy"] = str(self._accuracy)
        return public

    def act(self, action):
        if action not in self.view()["actions"]:
            raise ValueError("Action unavailable")
        self._replay.act(action)
        self._tools += {"retry": RETRY, "switch": SWITCH}.get(action, F(0))
        if action == "diagnose":
            self._diagnosis += DIAGNOSIS
        return self.view()

    def audit(self):
        replay = self._replay
        return {
            "events": replay.events,
            "decisions": replay.decisions,
            "score": verify(replay, replay.events),
            "recovery_calls": len(replay.events) - replay.sunk,
            "tool_fee": self._tools,
            "diagnostic_fee": self._diagnosis,
        }
