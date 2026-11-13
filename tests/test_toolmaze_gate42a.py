"""Real contracts and independent scoring, CPU only; binders below are named CPU rules."""
from copy import deepcopy
from fractions import Fraction as F
import json
import unittest

from extensions.toolmaze_recovery.gate42a import (
    ALTWRITE, ARCHIVE, BACKUP, CONFIRM, CONTENT, MAIN, RESOURCE, VALIDATE, VERIFY, WRITE,
    MultipathSession, checkpoint, evaluate, sample,
)
from extensions.toolmaze_recovery.gate34b import run_episode
from evaluation.agents.base_agent import AgentAction


def bind(view, tool):
    """CPU replay only: reads actual public receipts, never Session, Z or a reference path."""
    events = view["history"]
    if tool in (MAIN, BACKUP, ARCHIVE):
        return {"record_id": RESOURCE}
    if tool == VALIDATE:
        return {"record_id": RESOURCE, "pending_ref": next(e["result"]["pending_ref"]
                  for e in reversed(events) if "pending_ref" in e["result"])}
    if tool in (WRITE, ALTWRITE):
        evidence = next(e for e in reversed(events) if "evidence_ref" in e["result"])
        source = (evidence if "content" in evidence["result"] else
                  next(e for e in events if e["result"].get("pending_ref") == evidence["arguments"]["pending_ref"]))
        return {"record_id": RESOURCE, "content": source["result"]["content"],
                "evidence_ref": evidence["result"]["evidence_ref"]}
    if tool == CONFIRM:
        return {"record_id": RESOURCE, "pending_publication_ref": next(e["result"]["pending_publication_ref"]
                  for e in reversed(events) if "pending_publication_ref" in e["result"])}
    return {"publication_id": next(e["result"]["publication_id"] for e in reversed(events)
                                   if "publication_id" in e["result"])}


def call(session, tool):
    return session.call(tool, bind(session.view(), tool))


def start(mechanism, state, **kwargs):
    session = MultipathSession(mechanism, state, _namespace="cpu-public-receipts", **kwargs)
    assert call(session, MAIN) == {"error": "Upstream request timed out."}
    return session


def play(session, tools):
    for tool in tools:
        call(session, tool)
    return evaluate(session, "Published and verified.")


def expanded_call(session, action):
    """CPU-only expansion of one registered macro action into actual contract calls."""
    names = {"primary": MAIN, "backup": BACKUP, "archive": ARCHIVE, "validate": VALIDATE,
             "writer": WRITE, "altwriter": ALTWRITE}
    first = call(session, names[action])
    ok = "error" not in first
    if ok:
        tails = ({"primary": (WRITE, VERIFY), "backup": (), "validate": (WRITE, VERIFY),
                  "archive": (VALIDATE, WRITE, VERIFY)} if ARCHIVE in session.view()["prices"] else
                 {"primary": (), "backup": (VALIDATE,), "writer": (VERIFY,), "altwriter": (CONFIRM, VERIFY)})
        for tool in tails[action]:
            assert "error" not in call(session, tool)
    return ok


def contract_transitions():
    """Exhaust each deterministic world and feasible macro history via fresh real Sessions."""
    from extensions.toolmaze_recovery import multipath as mp
    from extensions.toolmaze_recovery import multipath_rounds as rounds
    results = {}
    for label, cell, states in (("M3-8", rounds.m3(8), ("transient", "persistent", "stale", "outage")),
                                ("M3-6", rounds.m3(6), ("transient", "persistent", "stale", "outage")),
                                ("M4", rounds.m4(), ("transient", "shared", "independent"))):
        transitions = terminals = calls = 0
        for state in states:
            frontier = [()]
            while frontier:
                events = frontier.pop()
                original = start(label[:2], state, recovery_calls=cell.left)
                for action, _ in events:
                    expanded_call(original, action)
                left = original.view()["remaining_calls"]
                for action in mp.legal(cell.graph, events, left, False):
                    if action == "stop":
                        continue
                    s = start(label[:2], state, recovery_calls=cell.left)
                    for old, _ in events:
                        expanded_call(s, old)
                    before_calls = len(s.events)
                    before_fee = sum(F(e["fee"]) for e in s.events)
                    success = expanded_call(s, action)
                    step = next(t for t in cell.graph[mp.position(cell.graph, events)] if t.tool == action)
                    expected = mp.chance(cell.faults[state].rates[action], events)
                    assert F(int(success)) == expected
                    assert len(s.events) - before_calls == 1 + (step.certain if success else 0)
                    assert sum(F(e["fee"]) for e in s.events) - before_fee == (
                        cell.roots[0][2].of(action) + (step.certain if success else 0))
                    assert not any(e["illegal"] for e in s.events)
                    transitions += 1
                    calls += len(s.events) - before_calls
                    if success and step.to == mp.DONE:
                        assert evaluate(s, "Published and verified.")["strict_success"]
                        terminals += 1
                    else:
                        frontier.append((*events, (action, mp.PASS if success else None)))
        results[label] = {"real_macro_transitions": transitions, "expanded_tool_calls": calls,
                          "strict_terminal_paths": terminals}
    return results


def reference_replay():
    """Evaluator-only ideal public policies; actual calls/fees/receipt-graph scoring."""
    from extensions.toolmaze_recovery import multipath as mp
    from extensions.toolmaze_recovery import multipath_rounds as rounds
    results = {}
    for label, cell in (("M3-8", rounds.m3(8)), ("M3-6", rounds.m3(6)), ("M4", rounds.m4())):
        table = {}
        mp.value(cell, table=table)  # CPU reference only; never passed to the Agent loop.
        completion = fee = F()
        seen_decisions = {}
        for root_weight, x, quote, prior in cell.roots:
            for state, weight in prior:
                s = start(label[:2], state, context=x, recovery_calls=cell.left)
                events = ()
                while True:
                    action = table[x, quote, events]
                    public = json.dumps(s.view(), sort_keys=True)
                    if public in seen_decisions:
                        assert seen_decisions[public] == action
                    seen_decisions[public] = action
                    if action == "stop":
                        break
                    step = next(t for t in cell.graph[mp.position(cell.graph, events)] if t.tool == action)
                    success = expanded_call(s, action)
                    if success and step.to == mp.DONE:
                        break
                    events += ((action, mp.PASS if success else None),)
                scored = evaluate(s, "Published and verified.")
                completion += root_weight * weight * int(scored["strict_success"])
                fee += root_weight * weight * F(scored["suffix_fee"])
        results[label] = [str(completion), str(fee)]
    return results


class Gate42AContracts(unittest.TestCase):
    def test_private_sampling_priors_and_budgets_equal_the_registered_gate41_cells(self):
        from extensions.toolmaze_recovery import multipath_rounds as rounds
        from extensions.toolmaze_recovery.gate42a import PRIORS, STATES
        for mechanism, cell in (("M3", rounds.m3(8)), ("M4", rounds.m4())):
            for mass, context, _, prior in cell.roots:
                self.assertEqual(mass, F(1, 3))
                self.assertEqual(dict(prior), dict(zip(STATES[mechanism], (F(n, 10) for n in PRIORS[mechanism][context]))))
                session = sample(mechanism, 42001)
                self.assertEqual(session.call_budget, cell.left + 1)
        self.assertEqual(sample("M3", 42001, recovery_calls=6).call_budget, 7)
        with self.assertRaises(ValueError):
            sample("M4", 42001, recovery_calls=8)

    def test_public_ideal_reference_uses_one_action_per_public_history_and_matches_real_fees(self):
        self.assertEqual(reference_replay(), {"M3-8": ["1", "53/10"], "M3-6": ["1", "16/3"],
                                               "M4": ["1", "68/15"]})

    def test_all_reachable_macro_transitions_match_real_contract_cost_budget_and_completion(self):
        results = contract_transitions()
        self.assertEqual(set(results), {"M3-8", "M3-6", "M4"})
        self.assertTrue(all(row["real_macro_transitions"] > row["strict_terminal_paths"] > 0
                            for row in results.values()))

    def test_primary_backup_archive_and_both_writers_are_real_chains(self):
        cases = [("M3", "transient", (MAIN, WRITE, VERIFY), 3),
                 ("M4", "transient", (MAIN, WRITE, VERIFY), 3)]
        for state in ("transient", "persistent", "stale", "outage"):
            cases.append(("M3", state, (ARCHIVE, VALIDATE, WRITE, VERIFY), 6))
        for state in ("transient", "persistent"):
            cases.append(("M3", state, (BACKUP, VALIDATE, WRITE, VERIFY), 4))
        for state in ("transient", "shared", "independent"):
            cases.append(("M4", state, (BACKUP, VALIDATE, ALTWRITE, CONFIRM, VERIFY), 5))
        cases.append(("M4", "independent", (BACKUP, VALIDATE, WRITE, VERIFY), 4))
        for mechanism, state, tools, fee in cases:
            with self.subTest(mechanism=mechanism, state=state, tools=tools):
                s = start(mechanism, state)
                result = play(s, tools)
                self.assertTrue(result["strict_success"], result)
                self.assertEqual(F(result["suffix_fee"]), fee)
                self.assertEqual(len(s.effects), 1)
                self.assertEqual(len(s.publications), 1)
                self.assertEqual(result["illegal_calls"], 0)

    def test_m3_failed_real_coverage_check_requires_new_source_not_a_fabricated_certificate(self):
        s = checkpoint("M3", _namespace="m3-checkpoint")
        self.assertEqual(len(s.events), 3)
        self.assertEqual(s.events[-1]["result"]["code"], "verification_failed")
        self.assertFalse(s.events[-1]["illegal"])
        self.assertFalse(s.certificates or s.effects)
        self.assertEqual(s.view()["remaining_calls"], 6)
        before = sum(F(e["fee"]) for e in s.events)
        result = play(s, (ARCHIVE, VALIDATE, WRITE, VERIFY))
        self.assertTrue(result["strict_success"], result)
        self.assertEqual(F(result["execution_fee"]) - before, 6)
        self.assertEqual(F(result["suffix_fee"]), 8)

    def test_m4_shared_writer_failure_and_exactly_three_actual_remaining_calls(self):
        s = checkpoint("M4", _namespace="m4-checkpoint")
        self.assertEqual(len(s.events), 4)
        self.assertEqual(s.view()["remaining_calls"], 3)
        self.assertFalse(s.effects or s.publications)
        self.assertFalse(s.events[-1]["illegal"])
        self.assertIn("no publication was committed", s.events[-1]["result"]["error"])
        prepared = call(s, ALTWRITE)
        self.assertIn("pending_publication_ref", prepared)
        self.assertFalse(s.effects or s.publications)  # Preparation is not a publication.
        self.assertFalse(evaluate(s, "done")["obligations_complete"])
        call(s, CONFIRM)
        self.assertEqual(len(s.effects), 1)
        self.assertFalse(evaluate(s, "done")["obligations_complete"])
        result = play(s, (VERIFY,))
        self.assertTrue(result["strict_success"], result)
        self.assertEqual(s.view()["remaining_calls"], 0)
        self.assertEqual(F(result["suffix_fee"]), 6)

    def test_skip_verification_or_confirmation_and_guessing_never_commits(self):
        for mechanism, tool in (("M3", BACKUP), ("M3", ARCHIVE), ("M4", BACKUP)):
            s = start(mechanism, "transient")
            pending = call(s, tool)
            receipt = s.call(WRITE, {"record_id": RESOURCE, "content": pending["content"],
                                      "evidence_ref": pending["pending_ref"]})
            self.assertIn("error", receipt)
            self.assertTrue(s.events[-1]["illegal"])
            self.assertFalse(s.effects)
        s = checkpoint("M4")
        result = s.call(CONFIRM, {"record_id": RESOURCE, "pending_publication_ref": "guessed"})
        self.assertIn("error", result)
        self.assertFalse(s.effects)

    def test_cross_task_evidence_and_preparation_are_rejected(self):
        one = start("M4", "transient")
        primary = call(one, MAIN)
        prepared = call(one, ALTWRITE)
        two = MultipathSession("M4", "transient", _namespace="different-task")
        call(two, MAIN)
        for tool, args in (
            (WRITE, {"record_id": RESOURCE, "content": CONTENT, "evidence_ref": primary["evidence_ref"]}),
            (CONFIRM, {"record_id": RESOURCE, "pending_publication_ref": prepared["pending_publication_ref"]})):
            self.assertIn("error", two.call(tool, args))
            self.assertTrue(two.events[-1]["illegal"])
        self.assertFalse(two.effects)

    def test_invalid_arguments_are_charged_and_not_masked_by_writer_outage(self):
        s = checkpoint("M4")
        good = bind(s.view(), WRITE)
        variants = ({}, {**good, "content": CONTENT[:-1]}, {**good, "record_id": "other"},
                    {**good, "unexpected": "value"}, [], {**good, "evidence_ref": "forged"})
        for args in variants:
            fresh = checkpoint("M4")
            result = fresh.call(WRITE, args)
            self.assertIn("error", result)
            self.assertNotIn("no publication was committed", result["error"])
            self.assertTrue(fresh.events[-1]["illegal"])
            self.assertEqual(F(fresh.events[-1]["fee"]), 1)
            self.assertFalse(fresh.effects)
        fresh = start("M3", "transient")
        fresh.call(ARCHIVE, [])
        self.assertTrue(fresh.events[-1]["illegal"])
        self.assertEqual(F(fresh.events[-1]["fee"]), 3)

    def test_duplicate_commit_has_no_second_effect_but_loses_strict_completion(self):
        for duplicate in (WRITE, ALTWRITE, CONFIRM):
            s = start("M4", "transient")
            call(s, MAIN)
            call(s, ALTWRITE)
            call(s, CONFIRM)
            self.assertIn("error", call(s, duplicate))
            result = play(s, (VERIFY,))
            self.assertTrue(result["obligations_complete"])
            self.assertFalse(result["strict_success"])
            self.assertEqual(len(s.effects), 1)
            self.assertEqual(result["illegal_calls"], 1)

    def test_missing_readback_answer_and_extra_read_cannot_be_hidden_by_score(self):
        s = start("M3", "transient")
        play(s, (MAIN, WRITE))
        self.assertFalse(evaluate(s, "done")["obligations_complete"])
        call(s, VERIFY)
        for answer in (None, "", "Blocked: stopped", "Error: failed"):
            scored = evaluate(s, answer)
            self.assertTrue(scored["obligations_complete"])
            self.assertFalse(scored["strict_success"])
        tight = checkpoint("M4")
        call(tight, MAIN)  # legal but futile; a known certificate remains usable.
        call(tight, ALTWRITE)
        call(tight, CONFIRM)
        before = deepcopy(tight.events)
        with self.assertRaises(ValueError):
            call(tight, VERIFY)
        self.assertEqual(tight.events, before)
        self.assertFalse(evaluate(tight, "done")["obligations_complete"])

    def test_first_valid_failure_counts_and_unknown_tool_budget_fee(self):
        s = MultipathSession("M3", "transient", _namespace="counting")
        s.call(MAIN, {})
        self.assertEqual(s.attempts[MAIN], 0)
        self.assertIn("error", call(s, MAIN))
        self.assertIn("evidence_ref", call(s, MAIN))
        s.call("unadvertised", {})
        self.assertEqual(s.events[-1]["fee"], "0")
        self.assertTrue(s.events[-1]["illegal"])
        self.assertEqual(len(s.engine.context.history), len(s.events))

    def test_scorer_rejects_changed_effect_receipt_authority_preparation_or_ledger(self):
        for change in ("effect", "readback", "authority", "preparation", "ledger", "fee", "category"):
            s = start("M4", "transient")
            play(s, (BACKUP, VALIDATE, ALTWRITE, CONFIRM, VERIFY))
            self.assertTrue(evaluate(s, "done")["strict_success"])
            if change == "effect":
                s.effects[0]["state"]["content"] = "forged"
            elif change == "readback":
                s.events[-1]["result"]["status"] = "inactive"
            elif change == "authority":
                s._coverage[next(iter(s._coverage))] = ()
            elif change == "preparation":
                next(iter(s.pending_publications.values()))["content"] = "forged"
            elif change == "ledger":
                s.engine.context.history[-1].arguments["publication_id"] = "different"
            elif change == "fee":
                s.events[-1]["fee"] = "0"
            else:
                s.events[-1]["kind"] = "diagnosis"
            self.assertFalse(evaluate(s, "done")["strict_success"], change)

    def test_private_world_and_generation_law_never_cross_public_boundary(self):
        for mechanism, states in (("M3", ("transient", "persistent", "stale", "outage")),
                                  ("M4", ("transient", "shared", "independent"))):
            sessions = [start(mechanism, state) for state in states]
            self.assertTrue(all(s.view() == sessions[0].view() for s in sessions))
            text = json.dumps(sessions[0].view())
            for forbidden in ('"_state"', '"seed"', '"priors"', '"oracle"', '"gamma"', '"M3"', '"M4"'):
                self.assertNotIn(forbidden, text)
            view = sessions[0].view()
            view["history"][0]["result"]["error"] = "mutated"
            self.assertNotEqual(view, sessions[0].view())
        a, b = start("M3", "persistent"), start("M3", "stale")
        call(a, BACKUP); call(b, BACKUP)
        self.assertEqual(a.view(), b.view())
        call(a, VALIDATE); call(b, VALIDATE)
        self.assertNotEqual(a.view(), b.view())  # Only an actual new legal observation separates them.
        for mechanism in ("M3", "M4"):
            a, b = sample(mechanism, 42001), sample(mechanism, 42001)
            self.assertEqual((a._state, a.public()), (b._state, b.public()))
            self.assertEqual(call(a, MAIN), call(b, MAIN))
            self.assertEqual(call(a, BACKUP), call(b, BACKUP))

    def test_existing_agent_loop_consumes_real_parameters_without_external_constraints(self):
        class CPUAgent:
            # Explicit CPU public-feedback policy, not a real model observation.
            perturbation_mode = None
            def initialize(self, task, tools):
                self.messages = [{"role": "system", "content": "CPU fake Agent"}]
                self.receipts = []
                self.plan = iter((ALTWRITE, CONFIRM, VERIFY))
            def receive_tool_result(self, tool, result):
                self.receipts.append((tool, result))
            def step(self):
                tool = next(self.plan, None)
                if tool is None:
                    return AgentAction(type="final_answer", content="Published and verified.")
                if tool == ALTWRITE:
                    content = next(r["content"] for _, r in self.receipts if "content" in r)
                    ref = next(r["evidence_ref"] for _, r in self.receipts if "evidence_ref" in r)
                    args = {"record_id": RESOURCE, "content": content, "evidence_ref": ref}
                elif tool == CONFIRM:
                    args = {"record_id": RESOURCE, "pending_publication_ref": self.receipts[-1][1]["pending_publication_ref"]}
                else:
                    args = {"publication_id": self.receipts[-1][1]["publication_id"]}
                return AgentAction(type="tool_call", tool_name=tool, arguments=args)
            def get_conversation_history(self):
                return self.messages
            def get_token_usage(self):
                return type("Usage", (), {"to_dict": lambda self: {}})()
        result = run_episode(CPUAgent(), checkpoint("M4"), scorer=evaluate)
        self.assertTrue(result["strict_success"], result)
        self.assertTrue(all(c["assigned_tool"] is None for c in result["checkpoints"]))
        self.assertEqual([c["execution"]["executed_tool"] for c in result["checkpoints"][:-1]],
                         [ALTWRITE, CONFIRM, VERIFY])


if __name__ == "__main__":
    unittest.main()
