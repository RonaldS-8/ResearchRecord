"""Gate46 stage-1 CPU checks through the native Agent loop; fake SDK is not an experiment."""
import json
from pathlib import Path
import unittest

from test_toolmaze_gate34b import client_agent
from extensions.toolmaze_recovery import gate46 as g
from extensions.toolmaze_recovery.gate34a import RESOURCE, VERIFY, WRITE
from extensions.toolmaze_recovery.gate34b import run_episode
from extensions.toolmaze_recovery.gate42a import ALTWRITE, CONFIRM
from extensions.toolmaze_recovery.gate44a import restored

FROZEN = json.loads((Path(__file__).resolve().parents[1] / "docs/evidence/044a-0/manifest.json").read_text())


def names(variant):
    mapping = g.NAMINGS[variant[3:]]
    return mapping.get(ALTWRITE, ALTWRITE), mapping.get(CONFIRM, CONFIRM)


def shown(variant):
    record_id, rows = g.RECORDS[variant[0]]
    return record_id, g.content(rows)


def alternate_plan(variant):
    prepare, confirm = names(variant)
    record_id, _ = shown(variant)
    def write(r):
        return {"record_id": record_id, "content": next(x["content"] for x in r if "content" in x),
                "evidence_ref": next(x["evidence_ref"] for x in reversed(r) if "evidence_ref" in x)}
    return [(prepare, write),
            (confirm, lambda r: {"record_id": record_id, "pending_publication_ref": r[-1]["pending_publication_ref"]}),
            (VERIFY, lambda r: {"publication_id": r[-1]["publication_id"]})]


def run(variant, contract, plan):
    agent, requests = client_agent(plan)
    session = g.VariantSession(variant, contract)
    return run_episode(agent, session, scorer=g.score), requests, session


class Gate46Tests(unittest.TestCase):
    def test_anchor_is_the_frozen_m4_checkpoint(self):
        s = g.VariantSession("AW0N0", "C0")
        self.assertEqual(g.digest(s.public()), FROZEN["checkpoints"]["M4"]["public_sha256"])
        self.assertEqual(s.events, restored("M4").events)
        rows = g.manifest(lambda: client_agent([])[0])
        self.assertEqual(rows["AW0N0-C0"]["prompt_sha256"], FROZEN["files"]["M4/R0-prompt.json"])
        self.assertEqual(len({r["prompt_sha256"] for r in rows.values()}), 24)
        self.assertEqual({r["remaining_calls"] for r in rows.values()}, {3})

    def test_policy_sees_only_variant_values(self):
        for v, c in g.conditions():
            s = g.VariantSession(v, c)
            text = json.dumps(s.view())
            record_id, body = shown(v)
            self.assertIn(record_id, text)
            self.assertIn(json.dumps(body)[1:-1], text)
            for name in names(v):
                self.assertIn(name, text)
            if v[0] != "A":
                self.assertNotIn(RESOURCE, text)
                self.assertNotIn("Valve", text)
            if v[3:] == "N1":
                self.assertNotIn(ALTWRITE, text)
                self.assertNotIn(CONFIRM, text)
            self.assertNotIn("shared", json.dumps(s.view()["history"]))

    def test_clarification_changes_only_two_descriptions(self):
        for v in g.variants():
            a, b = g.VariantSession(v, "C0").public(), g.VariantSession(v, "C1").public()
            self.assertEqual(a["task"], b["task"])
            changed = [x["name"] for x, y in zip(a["tools"], b["tools"]) if x != y]
            self.assertEqual(sorted(changed), sorted(names(v)))
            for x, y in zip(a["tools"], b["tools"]):
                if x != y:
                    d0 = x["paradigms"]["function_call"]["spec"]["description"]
                    d1 = y["paradigms"]["function_call"]["spec"]["description"]
                    self.assertTrue(d1.startswith(d0) and len(d1) > len(d0))

    def test_wording_changes_task_only(self):
        for r in g.RECORDS:
            for n in g.NAMINGS:
                a, b = g.VariantSession(r + "W0" + n, "C0").public(), g.VariantSession(r + "W1" + n, "C0").public()
                self.assertNotEqual(a["task"], b["task"])
                self.assertEqual({k: v for k, v in a.items() if k != "task"}, {k: v for k, v in b.items() if k != "task"})

    def test_alternate_chain_succeeds_in_native_loop(self):
        for v, c in g.conditions():
            result, requests, _ = run(v, c, alternate_plan(v))
            self.assertTrue(result["strict_success"], (v, c, result["issues"]))
            self.assertEqual(result["illegal_calls"], 0)
            self.assertNotIn("tool_choice", requests[0])
            self.assertEqual([e["tool"] for e in result["policy_events"][4:]], [*names(v), VERIFY])

    def test_stop_and_writer_retry_fail(self):
        for v, c in g.conditions():
            stop, _, _ = run(v, c, [])
            self.assertFalse(stop["strict_success"])
            record_id, body = shown(v)
            retry, _, s = run(v, c, [(WRITE, lambda r: {"record_id": record_id, "content": body,
                                                      "evidence_ref": r[-2]["evidence_ref"]})])
            self.assertFalse(retry["strict_success"])
            self.assertEqual(s.events[-1]["result"], {"error": "Publication endpoint unavailable; no publication was committed."})

    def test_unseen_canonical_values_are_rejected(self):
        plan = alternate_plan("BW0N1")
        canonical_tool = [(ALTWRITE,) + plan[0][1:]] + plan[1:]
        result, _, _ = run("BW0N1", "C0", canonical_tool)
        self.assertFalse(result["strict_success"])
        self.assertTrue(result["events"][4]["illegal"])
        canonical_record = [(names("BW0N1")[0], lambda r: {**plan[0][1](r), "record_id": RESOURCE})] + plan[1:]
        result, _, _ = run("BW0N1", "C0", canonical_record)
        self.assertTrue(result["events"][4]["illegal"])

    def test_schedule_is_balanced(self):
        rows = g.schedule()
        self.assertEqual(len(rows), 24)
        self.assertEqual({(r["variant"], r["contract"]) for r in rows}, set(g.conditions()))
        firsts = [rows[i]["contract"] for i in range(0, 24, 2)]
        self.assertEqual(firsts.count("C0"), 6)
        self.assertEqual(rows, g.schedule())


if __name__ == "__main__":
    unittest.main()
