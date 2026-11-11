"""Gate 28 checkpoint construction and native Agent continuation, without model inference."""

from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

from extensions.toolmaze_recovery.environment import RecoverySession, WRITE_TIMEOUT
from extensions.toolmaze_recovery.run import prepare_write_checkpoint, run_episode, write_behavior
from test_toolmaze_agent_recovery import fake_agent


class WriteAgentTests(unittest.TestCase):
    def save(self, name, row):
        if directory := os.environ.get("GATE28_OUTPUT"):
            with (Path(directory) / f"{name}.json").open("x") as stream:
                json.dump(row, stream, ensure_ascii=False, indent=2)

    def test_checkpoint_requests_identical_and_no_automatic_recovery(self):
        streams = []
        for fault in ("write_not_committed", "write_response_lost"):
            session = RecoverySession("stock-write-recovery", fault)
            prepare_write_checkpoint(session)
            self.assertEqual(session.events[-1]["result"], WRITE_TIMEOUT)
            self.assertEqual(len(session.reservations), int(fault == "write_response_lost"))
            agent, requests = fake_agent([])
            result = run_episode(agent, session, resume=True)
            self.save(f"checkpoint-{fault}", {"requests": requests, **result})
            streams.append(requests)
            self.assertEqual(len(result["events"]), 2)
            self.assertFalse(result["strict_success"])
            encoded = json.dumps(requests)
            for private in ("write_response_lost", "write_not_committed", "stock-write-recovery",
                            *session.reservations):
                self.assertNotIn(private, encoded)
        self.assertEqual(*streams)
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            prepare_write_checkpoint(RecoverySession("case-handoff"))

    def test_native_checkpoint_continuation_uses_query_and_actual_id(self):
        for fault in ("write_not_committed", "write_response_lost"):
            session = RecoverySession("stock-write-recovery", fault)
            prepare_write_checkpoint(session)
            agent, _ = fake_agent([])
            requests = []
            verified = False

            def create(**kwargs):
                nonlocal verified
                requests.append(deepcopy(kwargs))
                previous = json.loads(kwargs["messages"][-1]["content"])
                if len(requests) == 1:
                    self.assertEqual(previous, WRITE_TIMEOUT)
                    tool, args = "lookup_reservations_by_request", {"request_ref": "HOLD-2702"}
                elif previous.get("status") == "not_found":
                    tool, args = "reserve_stock", dict(session.events[1]["arguments"])
                elif not verified:
                    reservation_id = previous.get("reservation_id")
                    if reservation_id is None:
                        reservation_id = previous["reservation_ids"][0]
                    tool, args = "get_reservation_status", {"reservation_id": reservation_id}
                    verified = True
                else:
                    message = {"role": "assistant", "content": "Finished."}
                if not verified or previous.get("status") != "active":
                    message = {"role": "assistant", "content": "", "tool_calls": [{
                        "id": f"live_{len(requests)}", "type": "function",
                        "function": {"name": tool, "arguments": json.dumps(args)},
                    }]}
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                    model_dump=lambda **_: message))], usage=None)

            agent.client.chat.completions.create = create
            result = run_episode(agent, session, resume=True)
            self.save(f"continuation-{fault}", {"requests": requests, **result})
            self.assertTrue(result["strict_success"], result["issues"])
            self.assertEqual(len(result["effects"]), 1)
            self.assertEqual(result["diagnostic_fee"], 1)
            self.assertEqual(write_behavior(result["events"])["blind_write_retries"], 0)

    def test_blind_retry_counter_requires_post_fault_transaction_evidence(self):
        lost = RecoverySession("stock-write-recovery", "write_response_lost")
        prepare_write_checkpoint(lost)
        lost.call("read_service_status", {"resource_id": "P-140"})
        lost.call("reserve_stock", dict(lost.events[1]["arguments"]))
        self.assertEqual(write_behavior(lost.events)["blind_write_retries"], 1)
        self.save("blind-retry", {"behavior": write_behavior(lost.events), "events": lost.events})
        before = RecoverySession("stock-write-recovery", "write_not_committed")
        prepare_write_checkpoint(before)
        before.call("lookup_reservations_by_request", {"request_ref": "HOLD-2702"})
        before.call("reserve_stock", dict(before.events[1]["arguments"]))
        self.assertEqual(write_behavior(before.events)["blind_write_retries"], 0)
        self.save("informed-retry", {"behavior": write_behavior(before.events), "events": before.events})
