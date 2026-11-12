"""Experiment 040: the macro decision model against the Gate 34 exact reference and its own invariants."""
from fractions import Fraction as Q
from itertools import combinations, product
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from extensions.toolmaze_recovery import autoresearch as ar
from extensions.toolmaze_recovery import autoresearch_rounds as rounds
from extensions.toolmaze_recovery.autoresearch import (
    DIAGNOSE, HINTS, PUBLIC, RETRY, STOP, SWITCH, Fault, Planner, Quote, View, build)
from extensions.toolmaze_recovery.autoresearch_rounds import gate34, hint
from extensions.toolmaze_recovery.gate34a import BACKUP, MAIN
from extensions.toolmaze_recovery.gate34a_cpu import ExactReference, State, registered_cases, replay_plan


def pair(reference_value):
    return reference_value.success, reference_value.cost


class AutoresearchModelTests(unittest.TestCase):
    def test_macro_model_equals_the_call_level_reference_on_every_registered_case(self):
        for distribution, context in registered_cases():
            cell = gate34(distribution, context)
            reference = ExactReference(distribution, context)
            with self.subTest(cell=distribution.cell, context=context, gamma=distribution.gamma,
                              fee=distribution.diagnostic_fee):
                self.assertEqual(ar.value(cell), pair(reference.solve(State(), reference.initial)[0]))
                self.assertEqual(ar.value(cell, ar.fixed(0)),
                                 pair(reference.action_value(State(), reference.initial, BACKUP)))
                self.assertEqual(ar.value(cell, ar.fixed(1)),
                                 pair(reference.action_value(State(), reference.initial, MAIN)))
                # The oracle replay runs the real contracts, so this also ties the macro fees to them.
                self.assertEqual(ar.oracle(cell), pair(replay_plan(distribution, context, "oracle", oracle=True)[0]))
                if distribution.cell == "E":
                    bought = pair(replay_plan(distribution, context, "buy_diagnostic")[0])
                    follow = lambda v: (DIAGNOSE if DIAGNOSE in v.legal() else
                                        ar.fixed(0 if v.last(DIAGNOSE) == HINTS[1] else 1)(v))
                    self.assertEqual(ar.value(cell, follow), bought)

    def test_registered_gate34_targets(self):
        from extensions.toolmaze_recovery.gate34a import Distribution
        self.assertEqual(ar.value(gate34(Distribution("A"))), (1, Q(16, 5)))
        self.assertEqual(ar.value(gate34(Distribution("B"))), (1, Q(37, 10)))
        self.assertEqual(ar.oracle(gate34(Distribution("B"))), (1, Q(7, 2)))
        for gamma, fee, cost in ((Q(9, 10), Q(1, 10), Q(37, 10)), (Q(4, 5), Q(1, 10), Q(19, 5)),
                                 (Q(1, 2), Q(1, 10), Q(4)), (Q(9, 10), Q(1, 2), Q(4))):
            cell = gate34(Distribution("E", gamma, fee))
            self.assertEqual(ar.value(cell), (1, cost))
            self.assertEqual(ar.value(cell, ar.simple_feedback)[1],
                             Q(23, 5) - gamma if fee <= Q(1, 10) else Q(4))

    def small(self, tag=""):
        t, slow, p = "T" + tag, "L" + tag, "P" + tag
        faults = {t: Fault(Q(1), detail=(("a", Q(1)),), signal=hint(Q(4, 5), True)),
                  slow: Fault(Q(1, 2), Q(1), (("a", Q(3, 4)), ("b", Q(1, 4))), hint(Q(4, 5), True)),
                  p: Fault(Q(0), Q(1), (("a", Q(1, 4)), ("b", Q(3, 4))), hint(Q(4, 5), False))}
        contexts = {"X1": (Q(1, 2), {t: Q(1, 2), slow: Q(1, 4), p: Q(1, 4)}),
                    "X2": (Q(1, 2), {t: Q(1, 10), slow: Q(3, 10), p: Q(3, 5)})}
        quotes = ((Quote(Q(1), Q(1, 10)), Q(1, 2)), (Quote(Q(3), Q(1, 10)), Q(1, 2)))
        return build("small", faults, contexts, quotes, first_detail=True)

    def test_optimum_is_not_beaten_by_any_enumerated_policy(self):
        cell = build("tiny", {"T": Fault(Q(1), detail=(("a", Q(1)),)),
                              "P": Fault(Q(0), Q(3, 4), (("a", Q(1, 4)), ("b", Q(3, 4))))},
                     {None: (Q(1), {"T": Q(2, 5), "P": Q(3, 5)})})
        nodes = {}
        best = ar.value(cell, table=nodes)
        shallow = sorted((k for k in nodes if len(k[2]) <= 1), key=repr)
        self.assertEqual(len(shallow), 4)
        deep = (lambda v: nodes[v.x, v.quote, v.events], lambda v: STOP,
                lambda v: SWITCH if SWITCH in v.legal() else RETRY)
        for choice, tail in product(product((SWITCH, RETRY, STOP), repeat=4), deep):
            plan = dict(zip(shallow, choice))
            got = ar.value(cell, lambda v: plan[v.x, v.quote, v.events] if len(v.events) <= 1 else tail(v))
            self.assertFalse(ar.better(got, best), (plan, got, best))
        self.assertEqual(ar.value(cell, deep[0]), best)

    def test_more_public_information_never_hurts_and_the_oracle_bounds_it(self):
        cell = self.small()
        values = {frozenset(s): ar.value(cell, sees=s)
                  for n in range(5) for s in combinations(sorted(PUBLIC), n)}
        for small, big in product(values, repeat=2):
            if small <= big:
                self.assertFalse(ar.better(values[small], values[big]), (small, big))
        self.assertFalse(ar.better(values[PUBLIC], ar.oracle(cell)))
        self.assertTrue(ar.better(values[PUBLIC], values[frozenset()]))

    def test_closed_form_net_value_of_a_binary_diagnostic(self):
        for p, gamma, fee, backup in product((Q(1, 10), Q(3, 10), Q(1, 2), Q(9, 10)), (Q(1, 2), Q(4, 5), Q(9, 10)),
                                             (Q(1, 10), Q(3, 10)), (Q(1), Q(3))):
            quote = Quote(backup, fee)
            cell = build("v", {"T": Fault(Q(1), signal=hint(gamma, True)), "P": Fault(Q(0), signal=hint(gamma, False))},
                         {None: (Q(1), {"T": p, "P": 1 - p})}, ((quote, Q(1)),))
            saving, wasted = quote.fee(SWITCH, True) - quote.fee(RETRY, True), quote.fee(RETRY)
            without = ar.value(cell, ban=(DIAGNOSE,))[1]
            self.assertEqual(without, quote.fee(SWITCH, True) + min(Q(0), -p * saving + (1 - p) * wasted))
            net = (p * gamma * saving - (1 - p) * (1 - gamma) * wasted if p <= quote.break_even()
                   else (1 - p) * gamma * wasted - p * (1 - gamma) * saving) - fee
            self.assertEqual(without - ar.value(cell)[1], max(net, Q(0)), (p, gamma, fee, backup))

    def test_policies_and_histories_never_receive_the_hidden_state(self):
        cell = self.small()
        self.assertEqual(set(View.__dataclass_fields__), {"x", "quote", "events", "left"})
        rows = ar.simulate(cell, ar.uniform, 200, 7)
        self.assertEqual(rows, ar.simulate(cell, ar.uniform, 200, 7))
        self.assertNotEqual(rows, ar.simulate(cell, ar.uniform, 200, 8))
        text = repr(rows)
        self.assertEqual({key for row in rows for key in row}, {"x", "quote", "steps", "done", "fee"})
        for state in cell.faults:
            self.assertNotIn(repr(state), text)
        # Relabelling hidden states changes nothing a learner can see.
        self.assertEqual(ar.simulate(self.small("-renamed"), ar.uniform, 200, 7), rows)

    def test_sampled_fees_and_completion_match_exact_evaluation(self):
        cell, n = self.small(), 4000
        rows = ar.simulate(cell, ar.deterministic(ar.fixed(1)), n, 3)
        completion, fee = ar.value(cell, ar.fixed(1))
        self.assertAlmostEqual(sum(r["done"] for r in rows) / n, float(completion), delta=0.03)
        self.assertAlmostEqual(float(sum(r["fee"] for r in rows)) / n, float(fee), delta=0.08)

    def test_planner_recovers_the_optimum_with_enough_randomized_history(self):
        from extensions.toolmaze_recovery.gate34a import Distribution
        for distribution in (Distribution("A"), Distribution("B"), Distribution("E")):
            cell = gate34(distribution)
            planner = Planner(ar.fit(ar.simulate(cell, ar.uniform, 3000, 11)), cell.alphabet())
            self.assertEqual(ar.value(cell, planner), ar.value(cell), distribution.cell)

    def test_unsupported_actions_fall_back_and_never_look_attractive(self):
        from extensions.toolmaze_recovery.gate34a import Distribution
        cell = gate34(Distribution("A"))
        natural = ar.simulate(cell, ar.deterministic(ar.fixed(0)), 500, 5)
        planner = Planner(ar.fit(natural), cell.alphabet())
        self.assertEqual(ar.value(cell, planner), ar.value(cell, ar.fixed(0)))
        self.assertEqual(Planner({}, cell.alphabet())(View(None, Quote(), (), 6)), SWITCH)
        # A retry whose failure branch was never continued is worth only its own success mass.
        only_retries = [r for r in ar.simulate(cell, ar.uniform, 3000, 5)
                        if all(action == RETRY for _, action, _ in r["steps"])]
        _, _, values = Planner(ar.fit(only_retries), cell.alphabet()).node(None, Quote(), (), 6)
        self.assertLess(values[RETRY][0], 1)
        self.assertNotIn(SWITCH, values)

    def test_btm_statistics_are_episode_level_and_the_proxy_reads_only_them(self):
        from extensions.toolmaze_recovery.gate34a import Distribution
        cell = gate34(Distribution("B"))
        rows = ar.simulate(cell, ar.deterministic(ar.fixed(1)), 400, 2)
        statistics = ar.btm_statistics(rows)
        self.assertEqual(statistics["recovery"], {None: Q(401, 402)})
        self.assertEqual(statistics["support"]["recovery"], {None: 400})
        proxy = ar.btm_style(statistics)
        for x in ("X1", "X2"):
            self.assertEqual(proxy(View(x, Quote(Q(9)), (), 6)), RETRY)
            self.assertEqual(proxy(View(x, Quote(), ((RETRY, None),), 5)), SWITCH)
        self.assertEqual(ar.value(cell, proxy), ar.value(cell, ar.fixed(1)))
        # Compared with the switch belief, two saturated Beta means are ordered by support alone.
        self.assertLess(statistics["switch"], statistics["recovery"][None])
        self.assertEqual(ar.btm_style(statistics, None)(View("X2", Quote(), ((RETRY, None),), 5)), RETRY)


class AutoresearchRoundTests(unittest.TestCase):
    """Exact values registered in docs/experiments/040; none of these samples anything."""

    def test_registered_cells_and_their_minimal_public_information(self):
        expected = {
            "A": ((1, Q(16, 5)), [set()]), "B": ((1, Q(37, 10)), [{"x"}]), "C": ((1, Q(39, 10)), [{"quote"}]),
            "D": ((1, Q(4)), [set()]), "E": ((1, Q(37, 10)), [{"signal"}]), "F": ((1, Q(77, 20)), [{"detail"}]),
            "G": ((Q(1, 2), Q(2)), [set()]), "H": ((1, Q(7, 2)), [set()]),
            "CX": ((1, Q(43, 10)), [{"quote", "x"}]), "V": ((1, Q(37, 10)), [{"quote", "signal", "x"}]),
        }
        cells = rounds.cells()
        self.assertEqual(set(cells), set(expected))
        for name, (best, minimal) in expected.items():
            values = {frozenset(s): ar.value(cells[name], sees=s)
                      for n in range(5) for s in combinations(sorted(PUBLIC), n)}
            enough = [s for s, v in values.items() if v == values[PUBLIC]]
            with self.subTest(cell=name):
                self.assertEqual(values[PUBLIC], best)
                self.assertCountEqual([set(s) for s in enough if not any(o < s for o in enough)], minimal)
        self.assertEqual(ar.value(cells["D"], ar.fixed(1, guard=False)), (Q(4, 5), Q(13, 5)))
        self.assertEqual(ar.value(cells["D"], ar.simple_feedback), (Q(4, 5), Q(13, 5)))
        self.assertEqual(ar.value(cells["G"], ar.fixed(1)), (Q(1, 2), Q(3)))
        self.assertEqual(ar.value(cells["H"], ar.fixed(1)), (1, Q(4)))
        self.assertEqual(ar.value(cells["CX"], sees=("x",)), (1, Q(217, 50)))
        self.assertEqual(ar.value(cells["V"], ar.simple_feedback), (1, Q(77, 20)))

    def test_no_policy_saves_more_than_the_headroom_cap(self):
        for p, gamma, fee, primary, backup in product((Q(1, 10), Q(1, 2), Q(9, 10)), (Q(9, 10), Q(1)),
                                                      (Q(0), Q(1, 10)), (Q(1), Q(3)), (Q(1, 5), Q(1), Q(5), Q(17))):
            quote = Quote(backup, fee, primary)
            cell = rounds.binary("grid", {"X1": (Q(1, 2), p), "X2": (Q(1, 2), 1 - p)}, ((quote, Q(1)),), gamma)
            simple = min(ar.value(cell, ar.fixed(0))[1], ar.value(cell, ar.fixed(1))[1])
            wasted, success = primary, quote.fee(RETRY, True)
            premium = max(quote.fee(SWITCH, True) - success, Q(0))
            saving = simple - ar.value(cell)[1]
            self.assertLessEqual(saving, min(premium, wasted) / 2)
            cap = wasted * premium / ((wasted + premium) * (success + premium))
            self.assertLessEqual(saving / simple, cap)
            self.assertLessEqual(cap, Q(1, 4))
        unit = rounds.binary("grid", {None: (Q(1), Q(1, 2))}, ((Quote(diagnostic=Q(0)), Q(1)),), Q(1))
        self.assertEqual(ar.value(unit), (1, Q(7, 2)))  # the 12.5% unit-price ceiling is attained

    def test_strict_completion_first_ignores_cost_and_never_stops_on_a_noisy_signal(self):
        for beta in (Q(99, 100), Q(7, 10)):
            cell = rounds.binary("U", rounds.one(Q(9, 10)), backup=beta)
            strict, loose = rounds.optimal_policy(cell), rounds.optimal_policy(cell, tolerance=Q(1, 20))
            start = View(None, Quote(), (), cell.left)
            self.assertEqual((strict(start), loose(start)), (SWITCH, RETRY))
            gain = ar.value(cell)[0] - ar.value(cell, ar.fixed(1))[0]
            self.assertEqual(gain, Q(1, 10) * (1 - beta) ** 2 * beta)
            self.assertGreater(ar.value(cell)[1] - ar.value(cell, ar.fixed(1))[1], Q(4, 5))
        blocked = build("GD", {"persistent": Fault(Q(0), Q(1), signal=hint(Q(9, 10), True)),
                               "blocked": Fault(Q(0), Q(0), signal=hint(Q(9, 10), False))},
                        {None: (Q(1), {"persistent": Q(1, 2), "blocked": Q(1, 2)})},
                        ((Quote(diagnostic=Q(1, 10)), Q(1)),))
        table = {}
        self.assertEqual(ar.value(blocked, table=table), (Q(1, 2), Q(5, 2)))
        self.assertEqual(table[None, blocked.roots[0][2], ()], SWITCH)
        self.assertNotEqual(table[None, blocked.roots[0][2], ((DIAGNOSE, HINTS[1]),)], STOP)

    def test_composite_cell_and_rule_scoring_on_estimates(self):
        cell = rounds.composite()
        self.assertEqual(ar.value(cell), (Q(49, 60), Q(209, 60)))
        self.assertEqual(ar.value(cell, sees=()), (Q(49, 60), Q(109, 30)))
        self.assertEqual(ar.value(cell, ar.order(SWITCH, RETRY)), (Q(49, 60), Q(109, 30)))
        # A rule's futile paid calls are charged when it is scored on estimates.
        blocked = rounds.cells()["G"]
        planner = Planner(ar.fit(ar.simulate(blocked, ar.uniform, 4000, 1)), blocked.alphabet())
        for sequence in ((RETRY,), (RETRY, SWITCH), (RETRY, SWITCH, SWITCH), (SWITCH, SWITCH)):
            rule = ar.order(*sequence)
            estimate = planner.node(None, Quote(), (), blocked.left, rule)[1]
            exact = ar.value(blocked, rule)
            self.assertAlmostEqual(float(estimate[0]), float(exact[0]), delta=0.04, msg=sequence)
            self.assertAlmostEqual(float(estimate[1]), float(exact[1]), delta=0.12, msg=sequence)
        self.assertGreater(planner.node(None, Quote(), (), blocked.left, ar.order(RETRY, SWITCH, SWITCH))[1][1],
                           planner.node(None, Quote(), (), blocked.left, ar.order(RETRY))[1][1] + Q(1, 2))

    def test_noise_in_estimated_completion_decides_a_strict_planner_and_a_tolerance_stops_it(self):
        """Round 7 failure, seed 0: equal true completion, estimates about 0.02 apart."""
        cell = rounds.composite()
        counts = ar.fit(ar.simulate(cell, ar.uniform, 3000, 0))
        strict, loose = Planner(counts, cell.alphabet()), Planner(counts, cell.alphabet(), tolerance=Q(1, 20))
        best = rounds.optimal_policy(cell)
        for x, wrong in (("X1", SWITCH), ("X2", RETRY)):
            start = View(x, Quote(), (), cell.left)
            values = strict.node(x, Quote(), (), cell.left)[2]
            self.assertLess(abs(values[SWITCH][0] - values[RETRY][0]), Q(1, 20))
            self.assertGreater(abs(values[SWITCH][1] - values[RETRY][1]), Q(3, 10))
            self.assertEqual(strict(start), wrong)
            self.assertEqual(loose(start), best(start))
            self.assertNotEqual(best(start), wrong)
        self.assertTrue(ar.better(ar.value(cell, loose), ar.value(cell, strict), Q(1, 20)))

    def test_result_digest_ignores_run_metadata(self):
        with TemporaryDirectory() as directory:
            paths = []
            for index, commit in enumerate(("a", "b")):
                paths.append(Path(directory) / f"{index}.json")
                paths[-1].write_text(json.dumps({"commit": commit, "result": {"100": {"k": [1, "1/2"]}}}),
                                     encoding="utf-8")
            self.assertEqual(rounds.digest(paths[0]), rounds.digest(paths[1]))
            paths[1].write_text(json.dumps({"commit": "a", "result": {"100": {"k": [2, "1/2"]}}}), encoding="utf-8")
            self.assertNotEqual(rounds.digest(paths[0]), rounds.digest(paths[1]))


if __name__ == "__main__":
    unittest.main()
