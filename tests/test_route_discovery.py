import inspect
import unittest
from collections import Counter

from extensions.toolmaze_recovery import route_discovery as r


class PublicContractTests(unittest.TestCase):
    def test_contracts_drop_ground_truth_and_private_metadata(self):
        contracts = r.load_contracts()
        self.assertEqual(len(contracts), 270)
        for tool in contracts.values():
            self.assertEqual(set(tool), {"name", "description", "params", "required", "outputs"})
            for key in r.FORBIDDEN:
                self.assertNotIn(key, tool)
            self.assertTrue(tool["outputs"])

    def test_masked_names_leave_no_original_name(self):
        masked = r.load_contracts(mask_names=True)
        for original, tool in masked.items():
            self.assertRegex(tool["name"], r"^T\d{4}$")
            self.assertNotIn(original, tool["description"])

    def test_deriver_code_never_reads_ground_truth(self):
        source = inspect.getsource(r.Deriver) + inspect.getsource(r.load_contracts)
        for word in ("substitutes", "alternatives", "load_groups", "hit("):
            self.assertNotIn(word, source.replace("FORBIDDEN", ""))


class SplitAndScoringTests(unittest.TestCase):
    def test_registered_split_is_fixed_disjoint_and_stratified(self):
        groups = r.load_groups()
        self.assertEqual(Counter(g["kind"] for g in groups),
                         Counter({"many_to_many": 48, "one_to_one": 44, "one_to_many": 34}))
        dev, test = r.split(groups)
        self.assertEqual((len(dev), len(test)), (63, 63))
        self.assertFalse({g["id"] for g in dev} & {g["id"] for g in test})
        for kind in ("many_to_many", "one_to_one", "one_to_many"):
            self.assertEqual(sum(g["kind"] == kind for g in dev), sum(g["kind"] == kind for g in test))
        self.assertEqual([g["id"] for g in r.split(groups)[0]], [g["id"] for g in dev])

    def test_hit_requires_same_length_and_allows_declared_substitutes_only(self):
        subs = {"a": {"a2"}}
        self.assertTrue(r.hit(("a2", "b"), ("a", "b"), subs))
        self.assertFalse(r.hit(("b", "a"), ("a", "b"), subs))
        self.assertFalse(r.hit(("a",), ("a", "b"), subs))
        self.assertFalse(r.hit(("x", "b"), ("a", "b"), subs))

    def test_every_query_has_one_gold_and_excludes_itself(self):
        qs = list(r.queries(r.load_groups()))
        self.assertEqual(len(qs), 252)
        for q in qs:
            self.assertEqual(len(q["gold"]), 1)
            self.assertNotEqual(q["gold"][0], q["failed"])


class DeriverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = r.Deriver(r.load_contracts())

    def test_candidates_never_repeat_the_failed_route(self):
        failed = ("book_best_meeting_room",)
        for arm in r.ARMS:
            self.assertNotIn(failed, self.d.rank(failed, ["attendees", "date", "start_time", "end_time"], arm))

    def test_chains_consume_previous_outputs(self):
        inputs = ["attendees", "date", "start_time", "end_time"]
        for chain in self.d.chains(inputs, Counter(r.tokens("book meeting room"))):
            for a, b in zip(chain, chain[1:]):
                prev = self.d.filled(self.d.c[a]["outputs"])
                self.assertTrue(any((b, p) in prev for p in self.d.c[b]["required"]), chain)

    def test_verdict_rules(self):
        def s(d3, m2m, b3=0.0, fd=0.0, fb=0.0):
            return {"D": {"recall@3": d3, "false_top3": fd, "by_kind": {"many_to_many": {"recall@3": m2m}}},
                    "B1": {"recall@3": b3, "false_top3": fb}}
        self.assertEqual(r.verdict(s(0.85, 0.6))["verdict"], "go")
        self.assertEqual(r.verdict(s(0.85, 0.5))["verdict"], "inconclusive")
        self.assertEqual(r.verdict(s(0.49, 0.9))["verdict"], "no_go")
        self.assertTrue(r.verdict(s(0.85, 0.7, b3=0.82, fd=1, fb=1))["obligation_matching_no_increment"])
        self.assertFalse(r.verdict(s(0.85, 0.7, b3=0.82, fd=0.5, fb=1))["obligation_matching_no_increment"])


if __name__ == "__main__":
    unittest.main()
