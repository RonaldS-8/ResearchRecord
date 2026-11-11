"""Gate 29 business-state and Agent-interface acceptance on authored development tasks."""

from copy import deepcopy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from extensions.toolmaze_recovery.environment import RecoverySession, RELEASE_TIMEOUT, TIMEOUT, UNAVAILABLE, evaluate
from extensions.toolmaze_recovery.families import DENIED, EXPIRED
from extensions.toolmaze_recovery.run import smoke
from extensions.toolmaze_recovery.tasks import DEVELOPMENT, LINEAGE, RESOURCE_FIELDS
from evaluation.agents.vllm_agent import VLLMAgent
from openai.types.chat import ChatCompletion


def acquire(session, branch):
    name = session.read_tools[branch]
    return session.call(name, {RESOURCE_FIELDS[name]: session.goal.resource})


def release_args(session, build):
    grant = session.call("get_project_publish_permission", {"project": session.goal.project})
    manifest = build.get("manifest", build.get("artifact"))
    return {"project": manifest["project"], "version": manifest["version"], "sha256": manifest["sha256"],
            "build_ref": build.get("build_ref", build.get("mirror_ref")),
            "permission_ref": grant["permission_ref"]}


def access_args(session, qualification):
    goal = session.goal
    approval = session.call("get_access_approval", {"person_id": goal.resource, "area": goal.area})
    credential = session.call("get_facility_credential", {"area": goal.area})
    return {"person_id": goal.resource, "area": goal.area, "expires_at": goal.expires_at,
            "qualification_ref": qualification.get("qualification_ref", qualification.get("clearance_ref")),
            "approval_ref": approval["approval_ref"], "credential_ref": credential["credential_ref"]}


def finish(session, receipt, *, omit=False):
    if session.goal.family == "release":
        result = session.call("publish_release", release_args(session, receipt))
        if not omit and "release_id" in result:
            session.call("get_release_status", {"release_id": result["release_id"]})
    else:
        result = session.call("set_facility_access", access_args(session, receipt))
        if not omit and "permission_id" in result:
            session.call("get_effective_access", {"person_id": session.goal.resource, "area": session.goal.area})
    return result


class FamilyExpansionTests(unittest.TestCase):
    def setUp(self):
        self.traces = []

    def tearDown(self):
        if directory := os.environ.get("GATE29_OUTPUT"):
            for index, trace in enumerate(self.traces):
                with (Path(directory) / f"{self._testMethodName}-{index}.json").open("x") as stream:
                    json.dump(trace, stream, ensure_ascii=False, indent=2)

    def result(self, session, answer="Finished."):
        result = evaluate(session, answer)
        self.traces.append({"task": session.task, "fault": session.fault, "answer": answer, **result})
        return result

    def test_both_families_complete_two_routes_with_actual_readback(self):
        for task in ("artifact-release", "facility-access"):
            for branch in (0, 1):
                with self.subTest(task=task, branch=branch):
                    session = RecoverySession(task)
                    finish(session, acquire(session, branch))
                    result = self.result(session)
                    self.assertTrue(result["strict_success"], result["issues"])
                    self.assertEqual(len(result["effects"]), 1)
                    self.assertEqual(result["diagnostic_fee"], 0)
                    self.assertEqual(len(session.engine.context.history), len(result["events"]))

    def test_read_recovery_and_no_backup_stop_have_exact_evidence(self):
        for task in ("artifact-release", "facility-access"):
            for fault, branch in (("transient", 0), ("persistent", 1), ("correlated", 1)):
                session = RecoverySession(task, fault)
                self.assertEqual(acquire(session, 0), TIMEOUT)
                if fault == "correlated":
                    self.assertEqual(acquire(session, 1), TIMEOUT)
                finish(session, acquire(session, branch))
                result = self.result(session)
                self.assertTrue(result["strict_success"] and result["recovery_witness"], result["issues"])
            session = RecoverySession(task, "backup_unavailable")
            self.assertEqual(acquire(session, 0), TIMEOUT)
            self.assertFalse(self.result(session, "Blocked: waiting.")["correct_stop"])
            self.assertEqual(acquire(session, 1), UNAVAILABLE)
            self.assertEqual(acquire(session, 0), UNAVAILABLE)
            self.assertTrue(self.result(session, "Blocked: both acquisition routes unavailable.")["correct_stop"])

    def test_release_write_uncertainty_and_query_recovery(self):
        for fault in ("write_not_committed", "write_response_lost"):
            session = RecoverySession("artifact-release", fault)
            arguments = release_args(session, acquire(session, 0))
            self.assertEqual(session.call("publish_release", arguments), RELEASE_TIMEOUT)
            self.assertFalse(self.result(session)["strict_success"])
            query = session.call("inspect_project_release", {
                "project": session.goal.project, "version": session.goal.version,
            })
            if query["release_ids"]:
                release_id = query["release_ids"][0]
            else:
                release_id = session.call("publish_release", arguments)["release_id"]
            session.call("get_release_status", {"release_id": release_id})
            result = self.result(session)
            self.assertTrue(result["strict_success"] and result["recovery_witness"], result["issues"])
            self.assertEqual(result["diagnostic_fee"], 1)
        session = RecoverySession("artifact-release", "write_response_lost")
        args = release_args(session, acquire(session, 1))
        session.call("publish_release", args)
        session.call("publish_release", args)
        self.assertEqual(len(session.family_backend.records), 2)
        self.assertFalse(self.result(session)["strict_success"])

    def test_expired_credential_refresh_and_denial_are_distinct(self):
        session = RecoverySession("facility-access", "credential_expired")
        args = access_args(session, acquire(session, 1))
        self.assertEqual(session.call("set_facility_access", args), EXPIRED)
        self.assertFalse(self.result(session, "Blocked: credential expired.")["correct_stop"])
        inspected = session.call("inspect_facility_credential", {"credential_ref": args["credential_ref"]})
        self.assertEqual(inspected["status"], "expired")
        refreshed = session.call("refresh_facility_credential", {"expired_credential_ref": args["credential_ref"]})
        self.assertEqual(refreshed["area"], session.goal.area)
        args["credential_ref"] = refreshed["credential_ref"]
        session.call("set_facility_access", args)
        session.call("get_effective_access", {"person_id": session.goal.resource, "area": session.goal.area})
        result = self.result(session)
        self.assertTrue(result["strict_success"] and result["recovery_witness"], result["issues"])
        self.assertEqual(result["diagnostic_fee"], 1)
        denied = RecoverySession("facility-access", "authorization_denied")
        denied_args = access_args(denied, acquire(denied, 0))
        self.assertEqual(denied.call("set_facility_access", denied_args), DENIED)
        stopped = self.result(denied, "Blocked: actual facility approval denied.")
        self.assertTrue(stopped["correct_stop"])
        self.assertFalse(stopped["strict_success"] or stopped["effects"])

    def test_false_receipts_wrong_scope_missing_checks_and_tampering_fail(self):
        for task in ("artifact-release", "facility-access"):
            session = RecoverySession(task)
            receipt = acquire(session, 0)
            finish(session, receipt, omit=True)
            self.assertFalse(self.result(session)["strict_success"])
        release = RecoverySession("artifact-release")
        args = release_args(release, acquire(release, 0))
        for changes in ({"sha256": "wrong"}, {"project": "other"}, {"build_ref": "invented"}):
            self.assertIn("error", release.call("publish_release", {**args, **changes}))
        self.assertFalse(self.result(release)["strict_success"])
        another = RecoverySession("artifact-release")
        self.assertIn("error", another.call("publish_release", args))
        self.assertFalse(self.result(another)["strict_success"])
        access = RecoverySession("facility-access")
        args = access_args(access, acquire(access, 0))
        for changes in ({"area": "other"}, {"person_id": "other"}, {"approval_ref": "invented"},
                        {"expires_at": "2027-01-01T00:00:00Z"}):
            self.assertIn("error", access.call("set_facility_access", {**args, **changes}))
        self.assertFalse(self.result(access)["strict_success"])
        clean = RecoverySession("artifact-release")
        finish(clean, acquire(clean, 0))
        self.assertTrue(self.result(clean)["strict_success"])
        clean.events[-1]["result"]["sha256"] = "changed"
        self.assertFalse(self.result(clean)["strict_success"])

    def test_idempotent_repeat_and_actual_mutation_are_accounted_differently(self):
        session = RecoverySession("facility-access")
        args = access_args(session, acquire(session, 0))
        first = session.call("set_facility_access", args)
        self.assertEqual(session.call("set_facility_access", args), first)
        session.call("get_effective_access", {"person_id": session.goal.resource, "area": session.goal.area})
        result = self.result(session)
        self.assertTrue(result["strict_success"], result["issues"])
        self.assertEqual(len(result["effects"]), 1)
        changed = RecoverySession("facility-access")
        args = access_args(changed, acquire(changed, 0))
        changed.call("set_facility_access", {**args, "expires_at": "2026-11-20T18:00:00Z"})
        changed.call("set_facility_access", args)
        changed.call("get_effective_access", {"person_id": changed.goal.resource, "area": changed.goal.area})
        self.assertFalse(self.result(changed)["strict_success"])
        self.assertEqual(len(changed.effects), 2)

    def test_diagnostics_are_scoped_paid_and_do_not_fabricate_state(self):
        release = RecoverySession("artifact-release", "write_response_lost", diagnosis_available=False)
        self.assertIn("error", release.call("inspect_project_release", {
            "project": release.goal.project, "version": release.goal.version,
        }))
        self.assertIn("error", release.call("inspect_project_release", {"project": "other", "version": "1.4.2"}))
        result = self.result(release)
        self.assertEqual(result["diagnostic_fee"], 2)
        self.assertFalse(result["effects"])
        streams = []
        for fault in ("transient", "persistent"):
            session = RecoverySession("artifact-release", fault)
            view = session.public()
            self.assertEqual(acquire(session, 0), TIMEOUT)
            status = session.call("read_service_status", {"resource_id": session.goal.resource})
            streams.append((view, status))
            self.result(session)
        self.assertEqual(*streams)

    def test_lineage_is_development_only_and_derivatives_do_not_add_bases(self):
        self.assertEqual(set(DEVELOPMENT), set(LINEAGE))
        self.assertEqual(LINEAGE["stock-reservation"], LINEAGE["stock-write-recovery"])
        self.assertEqual(len({entry[0] for entry in LINEAGE.values()}), 5)
        self.assertEqual(len({entry[1] for entry in LINEAGE.values()}), 4)

    def test_assisted_query_forces_only_first_sdk_tool_and_model_binds_args(self):
        for condition in ("write_not_committed", "write_response_lost"):
            native = VLLMAgent("cpu", "http://127.0.0.1:1/v1")
            requests = []
            def create(**kwargs):
                requests.append(deepcopy(kwargs))
                previous = json.loads(kwargs["messages"][-1]["content"])
                if len(requests) == 1:
                    tool, args = "lookup_reservations_by_request", {"request_ref": "HOLD-2702"}
                elif previous.get("status") == "not_found":
                    prefix = next(m for m in kwargs["messages"] if m.get("tool_calls")
                                  and m["tool_calls"][0]["function"]["name"] == "reserve_stock")
                    tool, args = "reserve_stock", json.loads(prefix["tool_calls"][0]["function"]["arguments"])
                elif previous.get("status") != "active":
                    ref = previous.get("reservation_id") or previous["reservation_ids"][0]
                    tool, args = "get_reservation_status", {"reservation_id": ref}
                message = {"role": "assistant", "content": "Finished."}
                if previous.get("status") != "active":
                    message["tool_calls"] = [{"id": f"cpu_{len(requests)}", "type": "function",
                                             "function": {"name": tool, "arguments": json.dumps(args)}}]
                return ChatCompletion(id="cpu", created=0, model="cpu",
                                      choices=[{"index": 0, "message": message, "finish_reason": "stop"}],
                                      usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
            native.client = SimpleNamespace(with_options=lambda **_: SimpleNamespace(
                chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
            with TemporaryDirectory() as directory, patch(
                "extensions.toolmaze_recovery.run.VLLMAgent", return_value=native
            ):
                output = Path(directory) / "episode"
                smoke(output, "stock-write-recovery", condition, "http://127.0.0.1:1/v1",
                      start_mode="write-checkpoint", seed=2901, first_tool="lookup_reservations_by_request")
                result = json.loads((output / "episode.json").read_text())
                self.traces.append({"condition": condition, "requests": requests, **result})
            self.assertTrue(result["strict_success"], result["issues"])
            self.assertEqual(requests[0]["tool_choice"]["function"]["name"], "lookup_reservations_by_request")
            self.assertTrue(all("tool_choice" not in request for request in requests[1:]))
