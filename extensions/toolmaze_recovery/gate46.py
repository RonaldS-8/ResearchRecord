"""Gate46 stage-1 CPU preparation: M4 wording/naming variants and a contract clarification.

DRAFT pending preregistration approval; no real-model entry point.
The frozen gate42a M4 executor and scorer run unchanged underneath. A variant only
changes what the policy sees: record identifier/content, task wording, the names of
the two alternate-writer tools and (clarified contract) two description sentences.
Public text and receipts are translated outward and model calls inward by an exact
swap map, so a canonical value the policy never saw is rejected like any wrong value.
"""
from copy import deepcopy
import json
import random
import re

from .gate34a import ITEMS, RESOURCE
from .gate42a import ALTWRITE, CONFIRM, checkpoint, evaluate
from .gate44a import digest

CANON_CONTENT = "Valve A: 12 units; Valve B: 8 units."
RECORDS = {  # record_id, item rows; content is derived exactly like the frozen fixture.
    "A": (RESOURCE, (("Valve A", 12), ("Valve B", 8))),
    "B": ("REC-5172", (("Pump C", 30), ("Pump D", 5))),
    "C": ("REC-6608", (("Filter E", 7), ("Filter F", 21))),
}
WORDINGS = {
    "W0": None,  # Frozen gate34a task text, unchanged.
    "W1": ("Publish a single copy of the current item-level content of record {record}. Its evidence "
           "must be an actual primary read receipt, or a backup read receipt whose granularity has "
           "been verified. Then read the publication back and confirm that its record, content and "
           "active status match. Give a final response."),
}
NAMINGS = {
    "N0": {},
    "N1": {ALTWRITE: "prepare_fallback_publication", CONFIRM: "confirm_fallback_publication"},
}
CLARIFY = {  # Appended verbatim to the frozen descriptions; no pointer from the failing writer.
    ALTWRITE: (" This is another route to the task's single publication, not an additional copy: "
               "a confirmed preparation is that one publication of the record. A writer call that "
               "committed no publication does not use this limit."),
    CONFIRM: " The committed publication is the task's single publication of this record.",
}
CONTRACTS = ("C0", "C1")
NAMESPACE = "gate44a-0-M4"  # Same receipts as the frozen Gate44A/45 M4 checkpoint.


def content(rows):
    return "; ".join(f"{item}: {units} units" for item, units in rows) + "."


def variants():
    return [r + w + n for r in RECORDS for w in WORDINGS for n in NAMINGS]


def conditions():
    return [(v, c) for v in variants() for c in CONTRACTS]


class VariantSession:
    """Policy-facing view of one frozen M4 checkpoint; the scorer only sees .inner."""

    def __init__(self, variant, contract):
        record, wording, naming = variant[0], variant[1:3], variant[3:]
        if record not in RECORDS or wording not in WORDINGS or naming not in NAMINGS or contract not in CONTRACTS:
            raise ValueError("Unregistered Gate46 condition")
        if content(RECORDS["A"][1]) != CANON_CONTENT or tuple((i["item"], i["units"]) for i in ITEMS) != RECORDS["A"][1]:
            raise ValueError("Frozen fixture changed")
        self.variant, self.contract = variant, contract
        self.inner = checkpoint("M4", _namespace=NAMESPACE)
        record_id, rows = RECORDS[record]
        if WORDINGS[wording] is not None:
            self.inner.engine.task_description = WORDINGS[wording].format(record=RESOURCE)
        if contract == "C1":
            for d in self.inner.engine.tool_definitions:
                if d["name"] in CLARIFY:
                    d["paradigms"]["function_call"]["spec"]["description"] += CLARIFY[d["name"]]
        pairs = [(RESOURCE, record_id), (CANON_CONTENT, content(rows)), *NAMINGS[naming].items()]
        self._swap = {}
        for a, b in pairs:
            if a != b:
                self._swap[a], self._swap[b] = b, a
        self._text = (re.compile("|".join(re.escape(k) for k in sorted(self._swap, key=len, reverse=True)))
                      if self._swap else None)
        canon = [{"item": i, "units": u} for i, u in RECORDS["A"][1]]
        shown = [{"item": i, "units": u} for i, u in rows]
        self._rows = {}
        for a, b in zip(canon, shown):
            if a != b:
                self._rows[json.dumps(a, sort_keys=True)], self._rows[json.dumps(b, sort_keys=True)] = b, a

    def _out(self, value):
        if isinstance(value, dict):
            key = json.dumps(value, sort_keys=True)
            if key in self._rows:
                return deepcopy(self._rows[key])
            return {self._out(k) if isinstance(k, str) else k: self._out(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._out(v) for v in value]
        if isinstance(value, str) and self._text is not None:
            return self._text.sub(lambda m: self._swap[m.group(0)], value)
        return value

    def _in(self, value):
        # Inbound is exact whole-value swap only; partial or wrong values pass unchanged and fail.
        if isinstance(value, str):
            return self._swap.get(value, value)
        if isinstance(value, dict):
            return {k: self._in(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._in(v) for v in value]
        return value

    def public(self):
        public = self._out(self.inner.public())
        public["tools"] = sorted(public["tools"], key=lambda d: d["name"])
        public["prices"] = dict(sorted(public["prices"].items()))
        return public

    def view(self):
        return {**self.public(), "history": self.events, "remaining_calls": self.inner.view()["remaining_calls"]}

    @property
    def events(self):
        return self._out(deepcopy(self.inner.events))

    def call(self, tool, arguments):
        return self._out(self.inner.call(self._in(tool) if isinstance(tool, str) else tool, self._in(arguments)))


def score(session, answer):
    """Frozen gate42a scorer on canonical receipts; events reported in both spaces."""
    result = evaluate(session.inner, answer)
    result["policy_events"] = session.events
    result["variant"], result["contract"] = session.variant, session.contract
    return result


def schedule(seed=460001):
    """Fixed order: shuffled variants, contract order alternating within the shuffled list."""
    order = variants()
    random.Random(seed).shuffle(order)
    rows = []
    for index, v in enumerate(order):
        for c in (CONTRACTS if index % 2 == 0 else CONTRACTS[::-1]):
            rows.append({"id": f"{len(rows) + 1:02d}-{v}-{c}", "variant": v, "contract": c})
    return rows


def manifest(native_factory, render=None):
    """Exact policy-facing bytes per condition; tokens only when a tokenizer renderer is supplied."""
    from .gate34b import initialize
    rows = {}
    for v, c in conditions():
        s = VariantSession(v, c)
        agent = native_factory()
        initialize(agent, s)
        payload = {"messages": deepcopy(agent.messages), "tools": deepcopy(agent.tools)}
        row = {"public_sha256": digest(s.public()), "prompt_sha256": digest(payload),
               "prompt_chars": len(json.dumps(payload, ensure_ascii=False)),
               "remaining_calls": s.view()["remaining_calls"]}
        if render is not None:
            row["rendered_tokens"] = render(payload["messages"], payload["tools"])[1]
        rows[v + "-" + c] = row
    return rows
