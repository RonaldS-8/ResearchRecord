"""Gate 26 CPU acceptance. No model service is contacted."""

import unittest
from unittest.mock import patch

from test_toolmaze_agent_recovery import fake_agent, save
from extensions.toolmaze_agent_recovery.integration import (
    BALANCE, DIAGNOSIS, LIGHT, PARTITIONS, RecoverySession,
)
from extensions.toolmaze_agent_recovery.methods import (
    ARMS, CONTINUATION, STOP, History, MethodAgent, recovery_context,
)
from extensions.toolmaze_agent_recovery.session import TIMEOUT, UNAVAILABLE, run_episode
from extensions.toolmaze_agent_recovery.verification import bound_arguments, evaluate, task_path


def replay(session, branch, *, first=None, diagnose=False):
    """Known CPU contract, consuming real receipts. Fork only at the failed read."""
    paths = session.engine.task_json["valid_paths"]
    steps, aliases = task_path(session.template, paths[branch])
    user = session.engine.task_json["user_input"]
    prior = {}
    cut = None
    for index, (node, tool, bindings) in enumerate(steps):
        arguments, _ = bound_arguments(bindings, user, prior, aliases)
        result = session.call(tool, arguments)
        if tool in session.read_tools and "error" in result:
            cut = len(session.events)
            if diagnose:
                session.call(DIAGNOSIS, {"area": "living_room"})
            if first == STOP:
                break
            if first == session.read_tools[1]:
                steps, aliases = task_path(session.template, paths[1])
                node, tool, bindings = steps[index]
                arguments, _ = bound_arguments(bindings, user, prior, aliases)
                result = session.call(tool, arguments)
            else:
                result = session.call(tool, arguments)
                if "error" in result and first is not None:
                    steps, aliases = task_path(session.template, paths[1])
                    node, tool, bindings = steps[index]
                    arguments, _ = bound_arguments(bindings, user, prior, aliases)
                    result = session.call(tool, arguments)
        if "error" in result:
            break
        prior[node] = session.events[-1]
        if cut is not None:
            # Finish the selected native branch, with no copied reference output.
            for next_node, next_tool, next_binding in steps[index + 1:]:
                arguments, _ = bound_arguments(next_binding, user, prior, aliases)
                if "error" in session.call(next_tool, arguments):
                    break
                prior[next_node] = session.events[-1]
            break
    return cut


def training():
    rows = []
    for fault in ("transient", "persistent", "blocked"):
        for selected in (*BALANCE, STOP):
            if fault == "blocked" and selected == BALANCE[0]:
                continue
            session = RecoverySession("002", fault)
            cut = replay(session, 0, first=selected)
            result = evaluate(session, "Finished the training continuation.")
            rows.append({
                "source_task": "002", "task": session.public()["task"], "contract": session.method_contract(),
                "continuation": CONTINUATION, "checkpoint": cut, "condition": fault, **result,
            })
    return rows


class Gate26Tests(unittest.TestCase):
    def test_new_tasks_have_two_verified_routes(self):
        results = {}
        for task in ("005", "055"):
            for branch in (0, 1):
                session = RecoverySession(task)
                replay(session, branch)
                result = evaluate(session, "Finished.")
                results[f"{task}-{branch}"] = result
        save("new_task_certificates", results)
        for key, result in results.items():
            self.assertTrue(result["strict_success"], (key, result["remaining"], result["issues"]))
            self.assertTrue(result["effects"])
            self.assertTrue(result["sources"])

    def test_diagnosis_is_paid_evidence_not_future_result(self):
        results = {}
        for fault in ("transient", "persistent", "offline"):
            session = RecoverySession("005", fault)
            replay(session, 0, first=LIGHT[0], diagnose=True)
            results[fault] = evaluate(session, "Stopped or finished.")
        save("diagnostic_cases", results)
        events = {fault: {event["tool"]: event["result"] for event in result["events"] if event["kind"] == "diagnosis"}
                  for fault, result in results.items()}
        self.assertEqual(events["transient"], events["persistent"])
        self.assertIn("light_living", events["transient"][DIAGNOSIS]["items"])
        self.assertNotIn("light_living", events["offline"][DIAGNOSIS]["items"])
        self.assertTrue(results["transient"]["strict_success"])
        self.assertTrue(results["persistent"]["strict_success"])
        self.assertTrue(results["offline"]["correct_stop"])
        self.assertFalse(results["offline"]["effects"])
        self.assertTrue(all(result["diagnostic_fee"] == 1 for result in results.values()))
        self.assertEqual(results["transient"]["tool_fee"], 7)
        illegal = RecoverySession("005")
        self.assertIn("error", illegal.call(DIAGNOSIS, {"area": "bedroom"}))
        self.assertTrue(illegal.events[-1]["illegal"])

    def test_final_bank_read_cannot_reuse_alternative_cache(self):
        session = RecoverySession("055")
        with patch.object(session.engine.context, "find_alternative_output") as cached:
            cached.return_value = {"user_id": "wrong", "balance": 0, "currency": "USD"}
            receipt = session.call("get_account_balance_bank_api", {
                "user_id": "user_01", "account_type": "investment",
            })
        cached.assert_not_called()
        self.assertEqual(receipt["user_id"], "user_01")
        self.assertGreater(receipt["balance"], 0)

    def test_unseen_duration_keeps_same_public_prefix(self):
        transient, delayed = (RecoverySession("055", mode) for mode in ("transient", "delayed"))
        for session in (transient, delayed):
            replay(session, 0, first=BALANCE[0])
        self.assertEqual(transient.events[:4], delayed.events[:4])
        self.assertNotIn("error", transient.events[4]["result"])
        self.assertEqual(delayed.events[4]["result"], TIMEOUT)
        self.assertTrue(evaluate(delayed, "Finished.")["strict_success"])

    def test_new_task_rejects_duplicate_effect_and_unbound_archive(self):
        session = RecoverySession("005")
        replay(session, 0)
        last = session.events[-1]
        session.call(last["tool"], last["arguments"])
        self.assertIn("extra or duplicate effects outside the matched path",
                      evaluate(session, "Finished.")["issues"])
        invalid = RecoverySession("005")
        archive = next(event for event in session.events if event["tool"] == "archive_light_mesh_snapshot_native")
        invalid.call(archive["tool"], archive["arguments"])
        self.assertFalse(evaluate(invalid, "Finished.")["strict_success"])

    def test_history_uses_only_training_and_marks_support(self):
        rows = training()
        save("training_history", rows)
        history = History(rows)
        row = rows[0]
        context = recovery_context(row["events"][:row["checkpoint"]], row["contract"])
        direct = history.values(row["task"], context)
        self.assertGreater(direct[BALANCE[0]]["support"], 0)
        self.assertEqual(direct[BALANCE[0]]["completion"], 1.0)
        other_task = history.values("Unseen task", context)
        self.assertEqual(other_task[BALANCE[0]]["support"], 0)
        self.assertTrue(other_task[BALANCE[0]]["extrapolated"])
        light = RecoverySession("005", "persistent")
        cut = replay(light, 0, first=STOP)
        light_context = recovery_context(light.events[:cut], light.method_contract())
        self.assertTrue(all(row["completion"] is None
                            for row in history.values(light.public()["task"], light_context).values()))
        with self.assertRaisesRegex(ValueError, "training cohort"):
            History([{**row, "source_task": "055"}])
        self.assertFalse(set(PARTITIONS["training_fixture"]) & set(PARTITIONS["task_candidate"]))

    def test_all_methods_use_native_call_boundary(self):
        history = History(training())
        results = {}
        for arm in ARMS:
            task = "005" if arm == "simple_diagnosis" else "002"
            session = RecoverySession(task, "persistent")
            replay(session, 0, first=session.read_tools[1], diagnose=arm == "simple_diagnosis")
            cut = next(index for index, event in enumerate(session.events, 1) if event["result"] == TIMEOUT)
            prefix = [(event["tool"], event["arguments"]) for event in session.events[:cut]]
            expected_tool = {
                "context": BALANCE[1], "hybrid": BALANCE[1], "simple_diagnosis": DIAGNOSIS,
            }.get(arm, session.read_tools[0])
            expected_arguments = ({"area": "living_room"} if expected_tool == DIAGNOSIS else
                                  next(event["arguments"] for event in session.events if event["tool"] == expected_tool))
            agent, requests = fake_agent([*prefix, (expected_tool, expected_arguments)])
            wrapped = MethodAgent(agent, arm, session.method_contract(), history)
            result = run_episode(wrapped, RecoverySession(task, "persistent"), max_turns=cut + 1)
            self.assertEqual(result["events"][-1]["tool"], expected_tool, arm)
            self.assertEqual(result["illegal_calls"], 0, arm)
            serialized = str(requests[-1])
            for hidden in ("valid_paths", "execution_trace", "C3_task_", "perturbation_mode"):
                self.assertNotIn(hidden, serialized)
            results[arm] = {"result": result, "requests": requests, "interventions": wrapped.interventions}
        save("method_interfaces", results)

    def test_knowledge_diff_and_same_observation_pair(self):
        training_rows = training()
        history = History(training_rows)
        session = RecoverySession("002", "transient")
        cut = replay(session, 0, first=STOP)
        prefix = [(event["tool"], event["arguments"]) for event in session.events[:cut]]
        traces = {}
        for fault in ("transient", "persistent"):
            agent, requests = fake_agent(prefix)
            wrap = MethodAgent(agent, "memory", session.method_contract(), history)
            run_episode(wrap, RecoverySession("002", fault), max_turns=cut + 1)
            traces[fault] = requests
        self.assertEqual(traces["transient"], traces["persistent"])
        self.assertIn('"support":', str(traces["transient"][-1]))
        save("method_isolation_pair", traces)

    def test_shared_contract_explains_backup_without_selecting_tool(self):
        session = RecoverySession("002", "persistent")
        agent, requests = fake_agent([])
        wrapped = MethodAgent(agent, "no_history", session.method_contract(), History())
        run_episode(wrapped, session, max_turns=1)
        request = requests[0]
        names = {entry["function"]["name"] for entry in request["tools"]}
        self.assertTrue(set(BALANCE) <= names)
        self.assertIn("is an accepted alternative", request["messages"][0]["content"])
        self.assertIn("archive_broker_balance_ledger_native", request["messages"][0]["content"])
        self.assertIn("ordinary account balance is a separate obligation", request["messages"][0]["content"])
        self.assertIn("actual archive title as the subject", request["messages"][0]["content"])
        self.assertNotIn("persistent", str(request))
        self.assertEqual(wrapped.interventions, [])
