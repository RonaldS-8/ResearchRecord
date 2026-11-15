"""Experiment 050 lost-receipt checkpoint, scorer, arms and runner, with a fake SDK only."""
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from test_toolmaze_gate34b import client_agent
from extensions.toolmaze_recovery import gate50 as g
from extensions.toolmaze_recovery.gate34a import CONTENT, MAIN, RESOURCE, VERIFY, WRITE
from extensions.toolmaze_recovery.gate42a import ALTWRITE, CONFIRM


def write_args(r):
    return {"record_id": RESOURCE, "content": CONTENT, "evidence_ref": r[0]["evidence_ref"]}


LOOKUP_VERIFY = [(g.LOOKUP, {"record_id": RESOURCE}),
                 (VERIFY, lambda r: {"publication_id": r[-1]["publications"][0]["publication_id"]})]
RETRY_VERIFY = [(WRITE, write_args), (VERIFY, lambda r: {"publication_id": r[-1]["publication_id"]})]
LOOKUP_SWITCH = [(g.LOOKUP, {"record_id": RESOURCE}), (ALTWRITE, write_args),
                 (CONFIRM, lambda r: {"record_id": RESOURCE, "pending_publication_ref": r[-1]["pending_publication_ref"]}),
                 (VERIFY, lambda r: {"publication_id": r[-1]["publication_id"]})]


def sdk_agent(plan):
    agent, requests = client_agent(plan)
    agent.temperature, agent.max_tokens, agent.request_timeout = 0.6, 6144, 120
    original = agent.client.chat.completions.create

    def backend(**kwargs):
        response = original(**kwargs)
        dump = response.model_dump

        def raw(**kw):
            value = dump(**kw)
            value["choices"][0]["finish_reason"] = "tool_calls" if value["choices"][0]["message"].get("tool_calls") else "stop"
            return value
        response.model_dump = raw
        return response
    agent.client.chat.completions.create = backend
    return agent, requests


def observe(world, arm, plan):
    with TemporaryDirectory() as d:
        agent, requests = sdk_agent(plan)
        return g.observe(agent, world, arm, Path(d) / "episode", seed=500001), requests


class CheckpointTests(unittest.TestCase):
    def test_worlds_share_one_public_prefix_without_private_fields(self):
        views = [g.checkpoint(w).view() for w in g.WORLDS]
        self.assertTrue(views[0] == views[1] == views[2])
        self.assertEqual([e["tool"] for e in views[0]["history"]], [MAIN, WRITE])
        self.assertEqual(views[0]["history"][1]["result"], g.TIMEOUT)
        self.assertEqual(views[0]["remaining_calls"], g.RECOVERY_CALLS)
        text = str(views[0])
        for private in ("_world", "receipt_lost", "'C'", "persistent"):
            self.assertNotIn(private, text)

    def test_committed_world_hides_publication_until_lookup(self):
        s = g.checkpoint("C")
        self.assertEqual(len(s.publications), 1)
        found = s.call(g.LOOKUP, {"record_id": RESOURCE})["publications"]
        self.assertEqual([p["content"] for p in found], [CONTENT])
        self.assertEqual(s.events[-1]["kind"], "diagnosis")
        self.assertTrue(g.evaluate(s, "done")["obligations_complete"] is False)  # No readback yet.
        s.call(VERIFY, {"publication_id": found[0]["publication_id"]})
        self.assertTrue(g.evaluate(s, "Published and verified.")["strict_success"])

    def test_rewrite_in_committed_world_is_a_silent_duplicate(self):
        s = g.checkpoint("C")
        receipt = s.call(WRITE, write_args([s.events[0]["result"]]))
        self.assertIn("publication_id", receipt)  # The endpoint does not reject it.
        s.call(VERIFY, receipt)
        score = g.evaluate(s, "Published and verified.")
        self.assertFalse(score["strict_success"])
        self.assertEqual((score["publications"], score["rewrites"]), (2, 1))

    def test_transient_retry_works_and_persistent_retry_times_out_without_commit(self):
        t, p = g.checkpoint("T"), g.checkpoint("P")
        self.assertIn("publication_id", t.call(WRITE, write_args([t.events[0]["result"]])))
        self.assertEqual(p.call(WRITE, write_args([p.events[0]["result"]])), g.TIMEOUT)
        self.assertEqual(p.publications, {})
        self.assertEqual(p.call(g.LOOKUP, {"record_id": RESOURCE})["publications"], [])

    def test_invalid_evidence_is_illegal_and_budget_is_enforced(self):
        s = g.checkpoint("T")
        s.call(WRITE, {"record_id": RESOURCE, "content": CONTENT, "evidence_ref": "guessed"})
        self.assertTrue(s.events[-1]["illegal"])
        for _ in range(g.RECOVERY_CALLS - 1):
            s.call(g.LOOKUP, {"record_id": RESOURCE})
        with self.assertRaises(ValueError):
            s.call(g.LOOKUP, {"record_id": RESOURCE})

    def test_cpu_reference_matches_registered_design(self):
        table = g.reference_table()
        strict = {k: sum(c["strict"] for c in row.values()) for k, row in table.items()}
        self.assertEqual(strict["5:retry_then_switch"], 2)
        self.assertEqual(strict["5:switch_first"], 2)
        self.assertEqual(strict["5:lookup_then_retry"], 2)
        self.assertEqual(strict["5:lookup_then_switch"], 3)
        self.assertEqual(strict["5:oracle"], 3)
        self.assertEqual(table["5:retry_then_switch"]["C"]["publications"], 2)
        self.assertEqual(strict["6:lookup_then_retry"], 3)


class ArmTests(unittest.TestCase):
    def test_arms_share_task_tools_and_prefix(self):
        payloads = {arm: g.prompt(sdk_agent([])[0], arm) for arm in g.ARMS}
        base = payloads["R0"]
        for arm, payload in payloads.items():
            self.assertEqual(payload["tools"], base["tools"])
            self.assertEqual(payload["messages"][:len(base["messages"])], base["messages"])
            self.assertEqual(len(payload["messages"]) - len(base["messages"]), 0 if arm == "R0" else 1)

    def test_btm_ablation_removes_only_the_retry_constraint(self):
        btm, nr = g.advice("BTM"), g.advice("BTM_NR")
        self.assertIn(g.BTM_RETRY_LINE, btm)
        self.assertNotIn(g.BTM_RETRY_LINE, nr)
        self.assertEqual(btm.replace(g.BTM_RETRY_LINE + "\n", ""), nr)
        self.assertIn(g.MAPPING, btm)

    def test_plan_is_balanced(self):
        rows = g.plan()
        self.assertEqual(len(rows), 120)
        self.assertEqual(set(Counter((r["arm"], r["world"]) for r in rows).values()), {10})
        self.assertEqual(len({r["id"] for r in rows}), 120)


def fake_rows(arm, world, k, n=10, duplicate=False):
    usage = [{"prompt_tokens": 100, "completion_tokens": 10}]
    return [{"arm": arm, "world": world, "strict_success": i < k, "publications": 2 if duplicate and i >= k else 1,
             "budget_exhausted": False, "illegal_calls": 0, "lookups": 0, "suffix_execution_fee": "2",
             "suffix_diagnostic_fee": "0", "raw_usage": usage} for i in range(n)]


class AnalysisTests(unittest.TestCase):
    def rows(self, btm_c, h=10, duplicate=True):
        rows = []
        for arm in g.ARMS:
            for world in g.WORLDS:
                k = btm_c if arm == "BTM" and world == "C" else h if arm == "H" else 10
                rows += fake_rows(arm, world, k, duplicate=duplicate)
        return rows

    def test_registered_verdicts(self):
        self.assertEqual(g.summarize(self.rows(0))["verdict"], "go")  # 33pp gap, all duplicates.
        self.assertEqual(g.summarize(self.rows(0, duplicate=False))["verdict"], "inconclusive")
        self.assertEqual(g.summarize(self.rows(9))["verdict"], "no_go")  # 3.3pp gap.
        self.assertEqual(g.summarize(self.rows(0, h=7))["verdict"], "invalid_hint_not_executed")

    def test_weighting_and_interval(self):
        s = g.summarize(self.rows(4))
        self.assertAlmostEqual(s["h_minus_btm"], 0.2)
        low, high = s["h_minus_btm_bootstrap95"]
        self.assertLess(low, 0.2)
        self.assertGreater(high, 0.15)
        self.assertEqual(s["arms"]["BTM"]["by_world"]["C"]["k"], 4)

    def test_execution_contaminated_budget_failures_cannot_trigger_go(self):
        rows = self.rows(0, duplicate=False)
        for row in rows:
            if not row["strict_success"]:
                row.update(budget_exhausted=True, illegal_calls=1)
        s = g.summarize(rows)
        btm = s["arms"]["BTM"]
        self.assertEqual(btm["budget_failures"], 10)  # Raw observations retained.
        self.assertEqual(btm["execution_contaminated_failures"], 10)
        self.assertEqual(btm["mechanism_budget_failures"], 0)
        self.assertEqual(s["btm_failure_share_duplicate_or_budget"], 0)
        self.assertEqual(s["verdict"], "inconclusive")
        for row in rows:
            row["illegal_calls"] = 0
        self.assertEqual(g.summarize(rows)["verdict"], "go")

    def test_mixed_duplicate_failures_use_all_failures_as_denominator(self):
        rows = self.rows(0)
        failures = [r for r in rows if r["arm"] == "BTM" and not r["strict_success"]]
        for row in failures[:6]:
            row["illegal_calls"] = 1
        s = g.summarize(rows)
        self.assertEqual(s["arms"]["BTM"]["duplicate_failures"], 10)
        self.assertEqual(s["arms"]["BTM"]["mechanism_duplicate_failures"], 4)
        self.assertEqual(s["btm_failure_share_duplicate_or_budget"], 0.4)
        self.assertEqual(s["verdict"], "inconclusive")


class RunnerTests(unittest.TestCase):
    def test_lookup_then_verify_succeeds_in_committed_world_through_native_loop(self):
        result, requests = observe("C", "H", LOOKUP_VERIFY)
        self.assertTrue(result["strict_success"])
        self.assertEqual(result["protocol"], "pass")
        first = requests[0]
        self.assertNotIn("tool_choice", first)
        self.assertEqual((first["seed"], first["top_p"], first["extra_body"]), (500001, 0.95, {"top_k": 20}))
        self.assertEqual(first["messages"][-1]["content"], "Recovery information:\n" + g.HINT)

    def test_blind_retry_duplicates_in_committed_world_but_succeeds_in_transient(self):
        committed, _ = observe("C", "BTM", RETRY_VERIFY)
        transient, _ = observe("T", "BTM", RETRY_VERIFY)
        self.assertFalse(committed["strict_success"])
        self.assertEqual(committed["publications"], 2)
        self.assertTrue(transient["strict_success"])

    def test_lookup_then_switch_completes_in_persistent_world(self):
        result, requests = observe("P", "R0", LOOKUP_SWITCH)
        self.assertTrue(result["strict_success"])
        self.assertEqual(result["suffix_execution_fee"], "3")
        self.assertEqual(result["suffix_diagnostic_fee"], "1")
        self.assertFalse(any("Recovery information" in str(m.get("content")) for m in requests[0]["messages"]))


if __name__ == "__main__":
    unittest.main()
