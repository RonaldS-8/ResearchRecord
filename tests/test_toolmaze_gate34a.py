"""Gate 34-A: real receipt obligations, exact references and public isolation."""
from copy import deepcopy
from fractions import Fraction as Q
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from extensions.toolmaze_agent_recovery.session import TIMEOUT
from extensions.toolmaze_recovery.gate34a import (
    BACKUP, CALL_BUDGET, CONTENT, DIAGNOSE, MAIN, RESOURCE, VALIDATE, VERIFY, WRITE,
    Distribution, MechanismSession, assign_tool, bernoulli, evaluate, execution_record, sample,
)
from extensions.toolmaze_recovery.gate34a_cpu import (
    ExactReference, State, actions, bind_from_view, calculate, check_all_transitions,
    main as cpu_main, registered_cases, replay_plan, worlds,
)


class Gate34ATests(unittest.TestCase):
    def setUp(self):
        self.evidence = []

    def tearDown(self):
        if directory := os.environ.get("GATE34A_OUTPUT"):
            with (Path(directory) / f"{self._testMethodName}.json").open("x") as stream:
                json.dump(self.evidence, stream, indent=2)

    def outcome(self, session, answer="Published and verified.", label=None):
        row = evaluate(session, answer)
        self.evidence.append({"case": label, **row})
        return row

    def start(self, transient=True, **kwargs):
        session = MechanismSession(transient, **kwargs)
        self.assertEqual(session.call(MAIN, {"record_id": RESOURCE}), TIMEOUT)
        return session

    def call(self, session, tool):
        return session.call(tool, bind_from_view(session.view(), tool))

    def finish(self, session, branch=MAIN, *, omit=False):
        receipt = self.call(session, branch)
        if branch == BACKUP:
            receipt = self.call(session, VALIDATE)
        write = self.call(session, WRITE)
        if not omit:
            self.call(session, VERIFY)
        return receipt, write

    def test_primary_and_backup_real_paths_cost_three_and_four(self):
        for transient in (True, False):
            for branch in (MAIN, BACKUP):
                if branch == MAIN and not transient:
                    continue
                session = self.start(transient)
                self.finish(session, branch)
                row = self.outcome(session)
                self.assertTrue(row["strict_success"], row)
                self.assertEqual(Q(row["sunk_fee"]), 1)
                self.assertEqual(Q(row["suffix_fee"]), 3 if branch == MAIN else 4)
                self.assertEqual(len(session.effects), 1)
                self.assertEqual(len(session.engine.context.history), len(session.events))

    def test_skip_granularity_never_writes(self):
        session = self.start()
        raw = self.call(session, BACKUP)
        result = session.call(WRITE, {"record_id": RESOURCE, "content": CONTENT, "evidence_ref": raw["pending_ref"]})
        self.assertIn("error", result)
        self.assertFalse(session.publications or session.effects)
        self.assertFalse(self.outcome(session, label="skip_granularity")["strict_success"])
        self.assertTrue(session.events[-1]["illegal"])

    def test_fake_and_cross_task_credentials_rejected(self):
        other = self.start()
        primary = self.call(other, MAIN)
        backup = self.call(other, BACKUP)
        certificate = self.call(other, VALIDATE)
        for ref in ("forged", primary["evidence_ref"], backup["pending_ref"], certificate["evidence_ref"]):
            session = self.start()
            result = session.call(WRITE, {"record_id": RESOURCE, "content": CONTENT, "evidence_ref": ref})
            self.assertIn("error", result)
            self.assertFalse(session.effects)
            self.assertFalse(self.outcome(session, label="foreign_or_fake_write")["strict_success"])
        for ref in ("forged", backup["pending_ref"]):
            session = self.start()
            self.assertIn("error", session.call(VALIDATE, {"record_id": RESOURCE, "pending_ref": ref}))
            self.assertFalse(session.certificates)
            self.assertFalse(self.outcome(session, label="foreign_or_fake_validation")["strict_success"])

    def test_granularity_checks_actual_item_coverage(self):
        for mutation in ("missing_item", "aggregate_only", "wrong_units", "wrong_scope"):
            session = self.start()
            receipt = self.call(session, BACKUP)
            source = session.acquisitions[receipt["pending_ref"]]
            if mutation == "missing_item":
                source["items"].pop()
            elif mutation == "aggregate_only":
                source["items"] = [{"item": "all", "units": 20}]
            elif mutation == "wrong_units":
                source["items"][0]["units"] = 13
            else:
                source["record_id"] = "other"
            self.assertIn("error", self.call(session, VALIDATE))
            self.assertFalse(session.certificates or session.effects)
            self.assertFalse(self.outcome(session, label=mutation)["strict_success"])

    def test_wrong_content_scope_and_id_rejected(self):
        for changes in ({"record_id": "REC-other"}, {"content": "wrong"}, {"evidence_ref": "fake"}):
            session = self.start()
            receipt = self.call(session, MAIN)
            result = session.call(WRITE, {"record_id": RESOURCE, "content": CONTENT,
                                           "evidence_ref": receipt["evidence_ref"], **changes})
            self.assertIn("error", result)
            self.assertFalse(session.effects)
            self.assertFalse(self.outcome(session, label=str(changes))["strict_success"])
        session = self.start()
        self.assertIn("error", session.call(VERIFY, {"publication_id": "guessed"}))
        self.assertFalse(self.outcome(session, label="guessed_readback")["strict_success"])

    def test_duplicate_write_no_extra_effect_but_strict_failure(self):
        session = self.start()
        self.finish(session)
        self.assertTrue(self.outcome(session)["strict_success"])
        self.assertIn("error", self.call(session, WRITE))
        self.assertEqual(len(session.effects), 1)
        self.assertFalse(self.outcome(session, label="duplicate_write")["strict_success"])

    def test_missing_readback_and_invalid_final_answer(self):
        session = self.start()
        self.finish(session, omit=True)
        self.assertFalse(self.outcome(session, label="missing_readback")["strict_success"])
        self.call(session, VERIFY)
        for answer in (None, "", "  ", "Blocked: done", "Error: execution"):
            row = self.outcome(session, answer, "invalid_answer")
            self.assertTrue(row["obligations_complete"])
            self.assertFalse(row["strict_success"])
        self.assertTrue(self.outcome(session)["strict_success"])

    def test_malformed_calls_do_not_advance_first_failure(self):
        for args in ({}, {"record_id": 42}, {"record_id": RESOURCE, "extra": "x"},
                     {"record_id": "another"}, [], None):
            session = MechanismSession(True)
            self.assertIn("error", session.call(MAIN, args))
            self.assertEqual(Q(session.events[-1]["fee"]), 1)
            self.assertEqual(session.attempts[MAIN], 0)
            self.assertEqual(session.call(MAIN, {"record_id": RESOURCE}), TIMEOUT)
            self.assertEqual(session.attempts[MAIN], 1)
            self.assertNotIn("error", self.call(session, MAIN))
            self.assertEqual(session.attempts[MAIN], 2)
            self.assertFalse(self.outcome(session, label="invalid_arguments")["strict_success"])
        session = self.start()
        self.assertIn("error", session.call("unadvertised", {}))
        self.assertEqual(Q(session.events[-1]["fee"]), 0)

    def test_persistent_failure_is_fixed_backup_always_available(self):
        session = self.start(False)
        self.assertEqual(self.call(session, MAIN), TIMEOUT)
        self.assertEqual(self.call(session, MAIN), TIMEOUT)
        self.finish(session, BACKUP)
        row = self.outcome(session)
        self.assertTrue(row["strict_success"])
        self.assertEqual(Q(row["suffix_fee"]), 6)

    def test_once_only_diagnostic_contract_and_executor(self):
        for fee in (Q(1, 10), Q(1, 2)):
            session = self.start(False, diagnostic_fee=fee, signal="transient_hint")
            snapshot = (session.fault, session.attempts[MAIN], deepcopy(session.effects))
            self.assertEqual(self.call(session, DIAGNOSE), {"signal": "transient_hint"})
            self.assertEqual((session.fault, session.attempts[MAIN], session.effects), snapshot)
            self.assertEqual(session.attempts[DIAGNOSE], 1)
            self.assertIn("At most one", next(t for t in session.public()["tools"] if t["name"] == DIAGNOSE)
                          ["paradigms"]["function_call"]["spec"]["description"])
            self.assertIn("error", self.call(session, DIAGNOSE))
            self.assertTrue(session.events[-1]["illegal"])
            row = self.outcome(session, label="repeated_diagnostic")
            self.assertEqual(Q(row["diagnostic_fee"]), 2 * fee)
            json.dumps(session.view())
        for args in ({}, None, []):
            malformed = self.start(diagnostic_fee=Q(1, 10))
            malformed.call(DIAGNOSE, args)
            self.assertEqual(Q(malformed.events[-1]["fee"]), Q(1, 10))
            self.assertIn("error", self.call(malformed, DIAGNOSE))
            self.assertEqual(Q(self.outcome(malformed, label="malformed_diagnostic_consumes_permission")["diagnostic_fee"]), Q(1, 5))

    def test_exact_per_call_prices_and_maximum_path_budget(self):
        for fee in (Q(1, 10), Q(1, 2)):
            session = self.start(False, diagnostic_fee=fee)
            self.call(session, DIAGNOSE)
            self.assertEqual(self.call(session, MAIN), TIMEOUT)
            self.finish(session, BACKUP)
            row = self.outcome(session)
            self.assertTrue(row["strict_success"])
            self.assertEqual(len(session.events), CALL_BUDGET)
            self.assertEqual(Q(row["execution_fee"]), 6)
            self.assertEqual(Q(row["diagnostic_fee"]), fee)
            self.assertEqual(Q(row["suffix_fee"]), 5 + fee)
            self.assertTrue(all(Q(e["fee"]) == (fee if e["tool"] == DIAGNOSE else 1) for e in row["events"]))
            previous = deepcopy(session.events)
            with self.assertRaisesRegex(ValueError, "budget"):
                self.call(session, MAIN)
            self.assertEqual(session.events, previous)

    def test_score_checks_real_receipt_graph_and_ledger(self):
        for mutation in ("read", "certificate", "write", "verify", "fee", "state"):
            session = self.start()
            self.finish(session, BACKUP)
            if mutation == "read":
                session.events[1]["result"]["pending_ref"] = "fake"
            elif mutation == "certificate":
                session.events[2]["arguments"]["pending_ref"] = "fake"
            elif mutation == "write":
                session.events[3]["result"]["publication_id"] = "fake"
            elif mutation == "verify":
                session.events[4]["result"]["content"] = "wrong"
            elif mutation == "fee":
                session.events[1]["fee"] = "0"
            else:
                next(iter(session.publications.values()))["content"] = "wrong"
            self.assertFalse(self.outcome(session, label="tamper_" + mutation)["strict_success"])

    def test_public_views_identical_across_hidden_worlds(self):
        for fee in (None, Q(1, 10), Q(1, 2)):
            pair = [self.start(t, signal="persistent_hint", diagnostic_fee=fee, _namespace="same") for t in (True, False)]
            self.assertEqual(pair[0].view(), pair[1].view())
            for seed in range(6):
                self.assertEqual(assign_tool(pair[0].view(), seed), assign_tool(pair[1].view(), seed))
            if fee is not None:
                for session in pair:
                    self.call(session, DIAGNOSE)
                self.assertEqual(pair[0].view(), pair[1].view())
            raw = json.dumps(pair[0].view())
            for forbidden in ('"fault"', '"seed"', '"gamma"', '"cell"', '"distribution"',
                              '"transient_probability"', '"oracle"', '"_namespace"', '"correct"'):
                self.assertNotIn(forbidden, raw)
            snapshot = pair[0].view()
            snapshot["history"][0]["result"]["error"] = "mutated"
            self.assertEqual(pair[0].view(), pair[1].view())

    def test_contexts_only_change_neutral_public_context(self):
        first = self.start(context="X1", _namespace="same").view()
        second = self.start(context="X2", _namespace="same").view()
        self.assertEqual(first.pop("context"), "X1")
        self.assertEqual(second.pop("context"), "X2")
        self.assertEqual(first, second)

    def test_fixed_seed_and_independent_sampling_domains(self):
        for distribution, _ in registered_cases():
            for seed in range(12):
                a, b = sample(distribution, seed), sample(distribution, seed)
                self.assertEqual(a.fault, b.fault)
                self.assertEqual(a._signal, b._signal)
                self.assertEqual(a.view(), b.view())
                self.call(a, MAIN)
                self.call(b, MAIN)
                self.call(a, BACKUP)
                self.call(b, BACKUP)
                self.assertEqual(a.view(), b.view())
                old_fault = a.fault
                assign_tool(self.start().view(), seed)
                self.assertEqual(a.fault, old_fault)
        # Accuracy and price change neither the fault draw nor pre-diagnostic view
        # (except the public quote when price changes).
        for seed in range(20):
            pair = [sample(Distribution("E", gamma, Q(1, 10)), seed) for gamma in (Q(1, 2), Q(9, 10))]
            self.assertEqual(pair[0].fault, pair[1].fault)
            self.assertEqual(pair[0].view(), pair[1].view())

    def test_exact_sampling_confusion_matrix(self):
        # Exhaust all equally weighted possible discrete noise draws, not a
        # finite Monte Carlo estimate of the registered confusion matrix.
        for gamma in (Q(4, 5), Q(9, 10), Q(1, 2)):
            for transient in (True, False):
                signals = []
                for noise in range(gamma.denominator):
                    def controlled_stream(seed, domain):
                        if domain == "fault":
                            return SimpleNamespace(randrange=lambda n: 0 if transient else n - 1)
                        if domain == "diagnostic-noise":
                            return SimpleNamespace(randrange=lambda n: noise)
                        return SimpleNamespace(getrandbits=lambda n: 1234)
                    with patch("extensions.toolmaze_recovery.gate34a.stream", controlled_stream):
                        s = sample(Distribution("E", gamma), 0)
                    signals.append(s._signal == ("transient_hint" if transient else "persistent_hint"))
                self.assertEqual(Q(sum(signals), len(signals)), gamma)
        for p in (Q(9, 10), Q(4, 5), Q(1, 5)):
            outcomes = [bernoulli(SimpleNamespace(randrange=lambda n, i=i: i), p) for i in range(p.denominator)]
            self.assertEqual(Q(sum(outcomes), len(outcomes)), p)

    def test_assigned_executed_accepted_usable_and_outcome_separate(self):
        session = self.start(False)
        assignment = {"assigned_tool": MAIN, "probability": "1/2"}
        self.call(session, MAIN)
        row = execution_record(assignment, session.events[-1], "cpu_native_followup")
        self.assertTrue(row["legal"] and row["assignment_followed"])
        self.assertFalse(row["usable_result"])
        self.evidence.append({"assignment_execution": row})
        self.call(session, BACKUP)
        row = execution_record(assignment, session.events[-1], "cpu_native_followup")
        self.assertFalse(row["assignment_followed"])
        self.assertTrue(row["legal"] and row["usable_result"])
        self.evidence.append({"assignment_execution": row})
        self.assertFalse(self.outcome(session)["strict_success"])
        session.call(WRITE, {})
        rejected = execution_record(assignment, session.events[-1], "cpu_rule")
        self.assertFalse(rejected["legal"])
        self.evidence.append({"assignment_execution": rejected})
        for fee, probability in ((None, "1/2"), (Q(1, 10), "1/3")):
            s = self.start(diagnostic_fee=fee)
            self.assertEqual(assign_tool(s.view(), 19)["probability"], probability)

    def test_exact_theoretical_targets_and_unconditional_failure_cost(self):
        a = calculate(Distribution("A"), check_transitions=False)["plans"]
        self.assertEqual(Q(a["retry_then_switch"]["expected_suffix_fee"]), Q(16, 5))
        self.assertEqual(Q(a["switch"]["expected_suffix_fee"]), 4)
        self.assertEqual(Q(a["oracle"]["expected_suffix_fee"]), Q(31, 10))
        self.assertEqual(Q(a["retry_only"]["strict_completion_probability"]), Q(9, 10))
        self.assertEqual(Q(a["retry_only"]["expected_suffix_fee"]), Q(14, 5))
        self.assertEqual(Q(a["stop"]["expected_suffix_fee"]), 0)
        b = [calculate(Distribution("B"), x, check_transitions=False)["plans"] for x in ("X1", "X2")]
        self.assertEqual([Q(p["bayes"]["expected_suffix_fee"]) for p in b], [Q(17, 5), Q(4)])
        self.assertEqual(sum(Q(p["bayes"]["expected_suffix_fee"]) for p in b) / 2, Q(37, 10))
        for name in ("switch", "retry_then_switch"):
            self.assertEqual(sum(Q(p[name]["expected_suffix_fee"]) for p in b) / 2, 4)
        self.assertEqual(sum(Q(p["oracle"]["expected_suffix_fee"]) for p in b) / 2, Q(7, 2))
        expected = {(Q(4, 5), Q(1, 10)): (Q(19, 5), Q(1, 5)),
                    (Q(4, 5), Q(1, 2)): (Q(4), -Q(1, 5)),
                    (Q(9, 10), Q(1, 10)): (Q(37, 10), Q(3, 10)),
                    (Q(9, 10), Q(1, 2)): (Q(4), -Q(1, 10)),
                    (Q(1, 2), Q(1, 10)): (Q(4), -Q(1, 10)),
                    (Q(1, 2), Q(1, 2)): (Q(4), -Q(1, 2))}
        for (gamma, fee), (cost, saving) in expected.items():
            e = calculate(Distribution("E", gamma, fee), check_transitions=False)["plans"]
            self.assertEqual(Q(e["bayes"]["expected_suffix_fee"]), cost)
            self.assertEqual(Q(e["diagnostic_net_saving_if_bought"]), saving)
            self.assertEqual(Q(e["no_diagnostic"]["expected_suffix_fee"]), 4)
            self.assertEqual(Q(e["oracle"]["expected_suffix_fee"]), Q(7, 2))
            self.assertEqual(Q(e["bayes"]["strict_completion_probability"]), 1)

    def test_every_reachable_kernel_transition_has_real_contract_witness(self):
        # All prices/accuracies share the execution transition kernel; checking
        # both fee variants covers the only per-call ledger difference.
        for d, context in ((Distribution("A"), None), (Distribution("B"), "X1"),
                           (Distribution("E", Q(4, 5), Q(1, 10)), None),
                           (Distribution("E", Q(9, 10), Q(1, 2)), None)):
            checked = check_all_transitions(d, context)
            self.assertGreater(checked, 100)
            self.evidence.append({"cell": d.cell, "checked_transitions": checked})

    def test_same_public_history_cannot_choose_by_latent_world(self):
        for distribution, context in registered_cases():
            reference = ExactReference(distribution, context)
            reference.solve(State(), reference.initial)
            decisions = {}
            for t, h, _ in worlds(distribution, context):
                session = self.start(t, signal="transient_hint" if h else "persistent_hint",
                                     context=context, diagnostic_fee=distribution.diagnostic_fee if distribution.cell == "E" else None,
                                     _namespace="same-counterfactual")
                state, belief = State(), reference.initial
                while True:
                    public = json.dumps(session.view(), sort_keys=True)
                    action = reference.solve(state, belief)[1]
                    self.assertEqual(decisions.setdefault(public, action), action)
                    if action == "final_answer":
                        break
                    from extensions.toolmaze_recovery.gate34a_cpu import observation
                    result = session.call(action, bind_from_view(session.view(), action))
                    state, belief = reference.update(state, belief, action, observation(action, result))
            self.evidence.append({"cell": distribution.cell, "context": context, "public_histories": len(decisions)})

    def test_budget_is_finite_even_for_useless_retries(self):
        session = self.start(False)
        for _ in range(CALL_BUDGET - 1):
            self.assertEqual(self.call(session, MAIN), TIMEOUT)
        self.assertFalse(self.outcome(session, label="budget_exhausted")["strict_success"])
        self.assertEqual(session.view()["remaining_calls"], 0)
        with self.assertRaises(ValueError):
            self.call(session, MAIN)
        self.assertEqual(actions(State(remaining=0), True), ("final_answer",))

    def test_archive_refuses_overwrite(self):
        with TemporaryDirectory() as directory:
            with patch("sys.argv", ["gate34a_cpu", "--out", directory]):
                with self.assertRaises(FileExistsError):
                    cpu_main()


if __name__ == "__main__":
    unittest.main()
