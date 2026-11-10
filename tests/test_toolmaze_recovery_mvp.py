"""CPU witnesses using actual native dispatch and actual returned receipts."""

from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

from extensions.toolmaze_recovery.environment import RecoverySession, TIMEOUT, UNAVAILABLE, evaluate
from extensions.toolmaze_recovery.run import ARMS, BUDGET, agent_for, run_episode
from extensions.toolmaze_recovery.tasks import DEVELOPMENT, DIAGNOSTIC, RESOURCE_FIELDS
from test_toolmaze_agent_recovery import fake_agent


DONE = "Finished."
BLOCKED = "Blocked: both compatible acquisition routes report session unavailability."
REF_KEYS = {
    "get_case_record": "record_ref", "read_case_archive": "archive_ref",
    "get_depot_inventory": "inventory_ref", "read_depot_count": "count_ticket",
}


def read(session, branch):
    tool = session.read_tools[branch]
    return session.call(tool, {RESOURCE_FIELDS[tool]: session.goal.resource})


def finish(session, branch, receipt, *, omit=False, **changes):
    goal = session.goal
    ref = receipt[REF_KEYS[session.read_tools[branch]]]
    if goal.family == "case":
        summary = receipt["summary"] if branch == 0 else receipt["case_file"]["summary"]
        args = {"case_id": goal.resource, "title": goal.title, "content": summary, "evidence_ref": ref}
        note = session.call("publish_case_note", {**args, **changes})
        if goal.recipient and not omit and "note_id" in note:
            session.call("send_note_notice", {"note_id": note["note_id"], "recipient": goal.recipient})
        return note
    args = {"sku": goal.resource, "quantity": goal.quantity, "evidence_ref": ref}
    hold = session.call("reserve_stock", {**args, **changes})
    if not omit and "reservation_id" in hold:
        session.call("get_reservation_status", {"reservation_id": hold["reservation_id"]})
    return hold


class RecoveryMVPTests(unittest.TestCase):
    def setUp(self):
        self.archive = []

    def tearDown(self):
        if directory := os.environ.get("GATE27_OUTPUT"):
            for index, row in enumerate(self.archive):
                with (Path(directory) / f"{self._testMethodName}-{index}.json").open("x") as stream:
                    json.dump(row, stream, ensure_ascii=False, indent=2)

    def result(self, session, answer=DONE):
        row = evaluate(session, answer)
        self.archive.append({"task": session.task, "condition": session.fault, "answer": answer, **row})
        return row

    def test_every_development_task_has_two_native_dispatch_routes(self):
        for task in DEVELOPMENT:
            for branch in (0, 1):
                with self.subTest(task=task, branch=branch):
                    session = RecoverySession(task)
                    finish(session, branch, read(session, branch))
                    result = self.result(session)
                    self.assertTrue(result["strict_success"], result["issues"])
                    self.assertFalse(result["recovery_witness"])
                    self.assertEqual(result["tool_fee"], 2 if task == "case-archive" else 3)
                    self.assertEqual(result["diagnostic_fee"], 0)
                    self.assertEqual(len(session.engine.context.history), len(result["events"]))

    def test_retry_switch_and_shared_outage(self):
        for task in DEVELOPMENT:
            for condition, branch, expected_fees in (("transient", 0, 1), ("persistent", 1, 1),
                                                       ("correlated", 1, 2)):
                with self.subTest(task=task, condition=condition):
                    session = RecoverySession(task, condition)
                    self.assertEqual(read(session, 0), TIMEOUT)
                    if condition == "correlated":
                        self.assertEqual(read(session, 1), TIMEOUT)
                    finish(session, branch, read(session, branch))
                    result = self.result(session)
                    self.assertTrue(result["strict_success"], result["issues"])
                    self.assertTrue(result["recovery_witness"])
                    self.assertEqual(result["failed_calls"], expected_fees)
                    self.assertEqual(result["tool_fee"], expected_fees + (2 if task == "case-archive" else 3))

    def test_diagnosis_evidence_ambiguity_failure_and_fee(self):
        statuses, retries = {}, {}
        for fault, available in (("transient", True), ("persistent", True),
                                 ("correlated", True), ("transient", False)):
            session = RecoverySession("stock-reservation", fault, diagnosis_available=available)
            self.assertEqual(read(session, 0), TIMEOUT)
            statuses[fault, available] = session.call(DIAGNOSTIC, {"resource_id": "P-140"})
            self.assertEqual(sum(session.attempts[name] for name in session.read_tools), 1)
            self.assertFalse(session.effects or session.acquisitions)
            retries[fault, available] = read(session, 0)
            row = self.result(session, BLOCKED)
            self.assertEqual((row["diagnostic_fee"], row["tool_fee"]), (1, 2))
            self.assertFalse(row["correct_stop"])
        self.assertEqual(statuses["transient", True], statuses["persistent", True])
        self.assertEqual(retries["persistent", True], TIMEOUT)
        self.assertNotIn("error", retries["transient", True])
        self.assertEqual(statuses["correlated", True]["status"], "degraded")
        self.assertEqual(retries["correlated", True], TIMEOUT)
        self.assertIn("error", statuses["transient", False])
        self.assertNotIn("error", retries["transient", False])

    def test_stopping_requires_explicit_evidence_from_both_routes(self):
        for task in DEVELOPMENT:
            with self.subTest(task=task):
                session = RecoverySession(task, "blocked")
                self.assertEqual(read(session, 0), TIMEOUT)
                self.assertFalse(self.result(session, BLOCKED)["correct_stop"])
                self.assertEqual(read(session, 1), UNAVAILABLE)
                self.assertFalse(self.result(session, BLOCKED)["correct_stop"])
                self.assertEqual(read(session, 0), UNAVAILABLE)
                self.assertFalse(self.result(session)["correct_stop"])
                result = self.result(session, BLOCKED)
                self.assertTrue(result["correct_stop"])
                self.assertFalse(result["strict_success"])
                self.assertFalse(result["effects"])

    def test_fake_cross_session_and_wrong_scope_calls_never_commit(self):
        first, second = RecoverySession("case-handoff"), RecoverySession("case-handoff", "transient")
        receipt = read(first, 0)
        self.assertIn("error", second.call("get_case_record", {"case_id": "HD-582"}))
        self.assertFalse(second.attempts)
        self.assertEqual(read(second, 0), TIMEOUT)
        self.assertIn("error", finish(second, 0, receipt))
        self.assertIn("error", finish(second, 0, {**receipt, "record_ref": "made-up"}))
        result = self.result(second)
        self.assertEqual(result["illegal_calls"], 3)
        self.assertFalse(result["strict_success"] or result["effects"])

    def test_wrong_writes_and_missing_obligations_fail(self):
        for task, omit, changes in (
            ("case-handoff", True, {}), ("case-handoff", False, {"content": "incorrect"}),
            ("case-handoff", False, {"title": "incorrect"}), ("stock-reservation", True, {}),
            ("stock-reservation", False, {"quantity": 2}), ("stock-reservation", False, {"quantity": True}),
        ):
            with self.subTest(task=task, omit=omit, changes=changes):
                session = RecoverySession(task)
                finish(session, 0, read(session, 0), omit=omit, **changes)
                self.assertFalse(self.result(session)["strict_success"])
        wrong_recipient = RecoverySession("case-handoff")
        note = finish(wrong_recipient, 0, read(wrong_recipient, 0), omit=True)
        wrong_recipient.call("send_note_notice", {"note_id": note["note_id"], "recipient": "wrong@company.test"})
        self.assertFalse(self.result(wrong_recipient)["strict_success"])

    def test_extra_and_duplicate_effects_are_rejected(self):
        archived = RecoverySession("case-archive")
        note = finish(archived, 1, read(archived, 1))
        self.assertTrue(self.result(archived)["strict_success"])
        archived.call("send_note_notice", {"note_id": note["note_id"], "recipient": "netops@company.test"})
        self.assertFalse(self.result(archived)["strict_success"])
        for task in ("case-handoff", "stock-reservation"):
            session = RecoverySession(task)
            receipt = read(session, 1)
            finish(session, 1, receipt)
            self.assertTrue(self.result(session)["strict_success"])
            finish(session, 1, receipt)
            self.assertFalse(self.result(session)["strict_success"])

    def test_sdk_receives_equal_prefix_and_no_private_state(self):
        streams = []
        for condition in ("transient", "persistent", "correlated", "blocked"):
            agent, requests = fake_agent([("get_case_record", {"case_id": "HD-417"})])
            session = RecoverySession("case-handoff", condition)
            session.engine.context.metadata["secret"] = "PRIVATE_STATE_SENTINEL"
            result = run_episode(agent, session)
            self.archive.append({"condition": condition, "requests": requests, **result})
            self.assertEqual(result["events"][0]["result"], TIMEOUT)
            streams.append(requests)
        self.assertTrue(all(stream == streams[0] for stream in streams))
        payload = json.dumps(streams[0])
        for term in ("case-handoff", "PRIVATE_STATE_SENTINEL", "DNS resolution fails",
                     "persistent", "correlated", "transient", "valid_paths", "execution_trace"):
            self.assertNotIn(term, payload)
        self.assertIn(TIMEOUT["error"], payload)
        self.assertIn("read_case_archive", payload)

    def test_native_sdk_loop_consumes_receipts_and_completes_recovery(self):
        # Script the choice only for CPU protocol validation. Read the native tool
        # messages at every step rather than reusing another session's receipts.
        agent, _ = fake_agent([])
        requests = []

        def create(**kwargs):
            requests.append(deepcopy(kwargs))
            turn = len(requests)
            result = json.loads(kwargs["messages"][-1]["content"]) if turn > 1 else {}
            if turn == 1:
                tool, args = "get_case_record", {"case_id": "HD-417"}
            elif turn == 2:
                self.assertEqual(result, TIMEOUT)
                tool, args = "read_case_archive", {"ticket": "HD-417"}
            elif turn == 3:
                tool, args = "publish_case_note", {"case_id": "HD-417", "title": "VPN handoff",
                    "content": result["case_file"]["summary"], "evidence_ref": result["archive_ref"]}
            elif turn == 4:
                tool, args = "send_note_notice", {"note_id": result["note_id"], "recipient": "netops@company.test"}
            message = {"role": "assistant", "content": DONE}
            if turn <= 4:
                message = {"role": "assistant", "content": "", "tool_calls": [{
                    "id": f"call_{turn}", "type": "function",
                    "function": {"name": tool, "arguments": json.dumps(args)},
                }]}
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                model_dump=lambda **_: message))], usage=None)

        agent.client.chat.completions.create = create
        result = run_episode(agent, RecoverySession("case-handoff", "persistent"))
        self.archive.append({"requests": requests, **result})
        self.assertTrue(result["strict_success"] and result["recovery_witness"], result["issues"])
        self.assertEqual(len(requests), 5)

    def test_all_baseline_interfaces_share_tools_and_zero_history(self):
        tool_names = []
        for arm in ARMS:
            native, requests = fake_agent([("get_case_record", {"case_id": "HD-417"})])
            session = RecoverySession("case-handoff", "persistent")
            result = run_episode(agent_for(native, session, arm), session, max_turns=2)
            self.archive.append({"arm": arm, "requests": requests, **result})
            self.assertFalse(result["strict_success"])
            self.assertEqual(result["tool_fee"], 1)
            tool_names.append(requests[0]["tools"])
            if arm in {"memory", "hybrid", "threshold"}:
                self.assertIn('"support": 0', requests[-1]["messages"][0]["content"])
                self.assertIn('"completion": null', requests[-1]["messages"][0]["content"])
        self.assertTrue(all(tools == tool_names[0] for tools in tool_names))

    def test_budget_and_nonadvertised_tools_are_enforced(self):
        session = RecoverySession("stock-reservation")
        for _ in range(BUDGET):
            session.call("get_case_record", {"case_id": "HD-417"})
        with self.assertRaisesRegex(ValueError, "budget"):
            read(session, 0)
        result = self.result(session)
        self.assertEqual(result["illegal_calls"], BUDGET)
        self.assertEqual(result["tool_fee"], 0)
        self.assertFalse(result["effects"])
