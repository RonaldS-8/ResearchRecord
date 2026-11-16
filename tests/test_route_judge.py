import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from extensions.toolmaze_recovery import route_discovery as rd
from extensions.toolmaze_recovery import route_judge as j


def fake_client(replies):
    """replies: list of content strings (or exceptions) returned in call order."""
    calls = []

    def create(**kw):
        calls.append(kw)
        r = replies.pop(0)
        if isinstance(r, Exception):
            raise r
        msg = SimpleNamespace(content=r, reasoning_content="thinking")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")], usage=None)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), calls


class RouteJudgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts = rd.load_contracts()
        g = next(g for g in rd.load_groups() if g["kind"] == "many_to_many")
        cls.failed, cls.gold = g["paths"]
        cls.other = next(t for t in cls.contracts if t not in set(cls.failed) | set(cls.gold))
        cls.q = {"id": "C3_task_999:x", "task": "C3_task_999", "query": "Please do the thing for alice.",
                 "failed": cls.failed, "gold": [cls.gold], "split": "test",
                 "pool": sorted(set(cls.failed) | set(cls.gold) | {cls.other}),
                 "candidates": [(cls.other,), cls.gold], "b1": [(cls.other,)]}

    def test_prompts_carry_public_contracts_only(self):
        for messages in (j.judge_messages(self.q, self.contracts, self.q["candidates"]),
                         j.propose_messages(self.q, self.contracts)):
            text = json.dumps(messages)
            for word in ("substitutes", "alternatives.yaml", "alt_", "gold", "valid_paths", "is_perturbed"):
                self.assertNotIn(word, text)
            self.assertIn(self.q["query"], text)
            self.assertIn(self.failed[0], text)
        available = j.propose_messages(self.q, self.contracts)[1]["content"].split("Available tools:")[1]
        for t in self.failed:
            self.assertNotIn(f"- {t}:", available)
        self.assertIn(f"- {self.gold[0]}:", available)

    def test_parse_maps_answers_and_rejects_unusable_ones(self):
        names = {self.contracts[t]["name"]: t for t in self.q["pool"] if t not in self.failed}
        cands = self.q["candidates"]
        self.assertEqual(j.parse('x {"ranking": ["C2", "C1", "C2", "C9"]}', "L", cands, names), [cands[1], cands[0]])
        self.assertIsNone(j.parse("no json here", "L", cands, names))
        p = json.dumps({"routes": [list(self.gold), [self.failed[0]], ["made_up_tool"]]})
        self.assertEqual(j.parse(p, "P", cands, names), [self.gold])

    def test_observe_and_score_through_fake_client(self):
        replies = ['{"ranking": ["C2"]}', json.dumps({"routes": [list(self.gold)]})]
        client, calls = fake_client(replies)
        results = [j.observe(client, "m", self.q, arm, self.contracts) for arm in j.ARMS]
        self.assertEqual(calls[0]["extra_body"], {"top_k": 20})
        self.assertEqual((calls[0]["temperature"], calls[0]["seed"]), (0.6, j.SEED))
        s = j.score([self.q], results)["test"]
        self.assertEqual((s["B1@3"], s["L@1"], s["P@1"], s["candidate_ceiling"]), (0.0, 1.0, 1.0, 1.0))
        self.assertEqual(j.verdict({"test": s})["verdict"], "go")

    def test_request_errors_are_recorded_and_invalidate_the_verdict(self):
        client, _ = fake_client([TimeoutError("slow"), "garbage"])
        results = [j.observe(client, "m", self.q, arm, self.contracts) for arm in j.ARMS]
        self.assertTrue(results[0]["error"].startswith("TimeoutError"))
        s = j.score([self.q], results)["test"]
        self.assertEqual((s["L_errors"], s["P_unusable"], s["P@3"]), (1.0, 1.0, 0.0))
        self.assertEqual(j.verdict({"test": s})["verdict"], "invalid_request_errors")

    def test_queries_build_rule_candidates_on_c3_distractor_pool(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name) / "perturbed_tasks" / "c3"
        d.mkdir(parents=True)
        prefix = "get_weather_openweather"
        paths = [[prefix, *self.failed], [prefix, *self.gold]]
        task = {"task_id": "C3_task_999", "domains": ["Financial"], "user_input": {"query": "q"},
                "valid_paths": [{"tools": p, "execution_trace": [{"tool_name": t} for t in p]} for p in paths]}
        (d / "C3_task_999_P0.json").write_text(json.dumps(task), encoding="utf-8")
        qs = list(j.queries(tmp.name))
        self.assertEqual(len(qs), 2)
        for q in qs:
            self.assertIn(q["split"], ("dev", "test"))
            self.assertLessEqual(len(q["candidates"]), j.K)
            self.assertNotIn(q["failed"], q["candidates"])


if __name__ == "__main__":
    unittest.main()
