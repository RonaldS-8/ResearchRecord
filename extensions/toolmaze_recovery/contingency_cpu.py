"""CPU check for contingency-program recovery (experiment cp01). No model is involved.

Two hand-written programs per development task, frozen before the grid is run:
- contingency: retries a read once after a timeout, switches to the authorized backup, looks up
  a non-idempotent write after an unknown outcome before rewriting, refreshes an expired
  credential, and stops with 'Blocked:' when no route remains or approval is denied;
- happy_path: the same task logic and conditionals stated in the task, no failure handling;
  it escalates on the first tool error.
Both were written by an author who has read the simulator. They show that the program
interface can express a complete recovery, not that a model can write one.
"""

import argparse
from collections import Counter
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

from .contingency import run_program
from .environment import FAULTS, RecoverySession, evaluate
from .tasks import DEVELOPMENT

STOPS = ("blocked", "backup_unavailable", "authorization_denied")

ACQUIRE = '''
def timed_out(result):
    return "timed out" in result.get("error", "")

def acquire(routes):
    # Retry a route once only after a timeout, then use the next authorized route.
    for tool, arguments in routes:
        result = call(tool, **arguments)
        if timed_out(result):
            result = call(tool, **arguments)
        if "error" not in result:
            return result
    return None
'''
FIRST = '''
def acquire(routes):
    tool, arguments = routes[0]
    result = call(tool, **arguments)
    if "error" in result:
        escalate(tool + " failed: " + result["error"])
    return result
'''

CASE = '''
record = acquire([("get_case_record", {{"case_id": "{case}"}}),
                  ("read_case_archive", {{"ticket": "{case}"}})])
if record is None:
    finish("Blocked: neither the live case record nor the authorized archive could be read.")
summary = record["summary"] if "summary" in record else record["case_file"]["summary"]
evidence = record.get("record_ref") or record.get("archive_ref")
note = call("publish_case_note", case_id="{case}", title="{title}", content=summary, evidence_ref=evidence)
if "error" in note:
    escalate("Publishing the note failed: " + note["error"])
'''
NOTICE = '''
notice = call("send_note_notice", note_id=note["note_id"], recipient="{recipient}")
if "error" in notice:
    escalate("Sending the notice failed: " + notice["error"])
finish("Published " + note["url"] + " and notified {recipient}.")
'''
STOCK = '''
stock = acquire([("get_depot_inventory", {"sku": "P-140"}), ("read_depot_count", {"item_code": "P-140"})])
if stock is None:
    finish("Blocked: neither the inventory snapshot nor the physical count could be read.")
if "inventory_ref" in stock:
    available, evidence = stock["available_units"], stock["inventory_ref"]
else:
    available, evidence = stock["count"]["free"], stock["count_ticket"]
if available < 3:
    finish("Blocked: only " + str(available) + " units of P-140 are available at D4.")
'''
RESERVE = '''
reservation = call("reserve_stock", sku="P-140", quantity=3, evidence_ref=evidence)
reservation_id = reservation.get("reservation_id")
if reservation_id is None:
    escalate("The reservation failed: " + reservation.get("error", ""))
'''
RESERVE_REQUEST = '''
def reserve():
    return call("reserve_stock", sku="P-140", quantity=3, evidence_ref=evidence, request_ref="HOLD-2702")

reservation = reserve()
reservation_id = reservation.get("reservation_id")
if reservation_id is None:
    if "outcome is unknown" not in reservation.get("error", ""):
        escalate("The reservation failed: " + reservation.get("error", ""))
    found = call("lookup_reservations_by_request", request_ref="HOLD-2702")
    if found.get("status") == "found":
        reservation_id = found["reservation_ids"][0]
    elif found.get("status") == "not_found":
        reservation_id = reserve().get("reservation_id")
        if reservation_id is None:
            escalate("The reservation failed again after a confirmed absence.")
    else:
        escalate("The reservation lookup failed, so a new write could duplicate the reservation.")
'''
RESERVE_REQUEST_HAPPY = '''
reservation = call("reserve_stock", sku="P-140", quantity=3, evidence_ref=evidence, request_ref="HOLD-2702")
reservation_id = reservation.get("reservation_id")
if reservation_id is None:
    escalate("The reservation failed: " + reservation.get("error", ""))
'''
CHECK_STOCK = '''
status = call("get_reservation_status", reservation_id=reservation_id)
if status.get("status") != "active":
    escalate("The reservation read-back is not active.")
finish("Reserved 3 units of P-140 at D4; reservation " + reservation_id + " is active.")
'''
RELEASE = '''
build = acquire([("get_build_manifest", {"build_id": "build-882"}),
                 ("read_artifact_mirror", {"artifact_key": "build-882"})])
if build is None:
    finish("Blocked: neither the build manifest nor the authorized mirror could be read.")
manifest = build.get("manifest") or build.get("artifact")
build_ref = build.get("build_ref") or build.get("mirror_ref")
if (manifest["project"], manifest["version"]) != ("weather-widget", "1.4.2"):
    escalate("The build does not describe weather-widget 1.4.2.")
permission = call("get_project_publish_permission", project="weather-widget")
if "error" in permission or not permission.get("allowed"):
    escalate("No usable publishing permission.")

def publish():
    return call("publish_release", project="weather-widget", version="1.4.2", sha256=manifest["sha256"],
                build_ref=build_ref, permission_ref=permission["permission_ref"])

release = publish()
release_id = release.get("release_id")
'''
RELEASE_UNKNOWN = '''
if release_id is None:
    if "outcome is unknown" not in release.get("error", ""):
        escalate("Publishing failed: " + release.get("error", ""))
    existing = call("inspect_project_release", project="weather-widget", version="1.4.2")
    if "error" in existing:
        escalate("The release registry query failed, so republishing could duplicate the release.")
    if existing["release_ids"]:
        release_id = existing["release_ids"][0]
    else:
        release_id = publish().get("release_id")
        if release_id is None:
            escalate("Publishing failed again after a confirmed absence.")
'''
RELEASE_HAPPY = '''
if release_id is None:
    escalate("Publishing failed: " + release.get("error", ""))
'''
CHECK_RELEASE = '''
status = call("get_release_status", release_id=release_id)
if status.get("status") != "active" or status.get("sha256") != manifest["sha256"]:
    escalate("The release read-back does not show the active build digest.")
finish("Release " + release_id + " of weather-widget 1.4.2 is active with the build digest.")
'''
ACCESS = '''
person, area, expiry = "employee-204", "lab-east", "2026-11-30T18:00:00Z"
qualification = acquire([("get_person_qualification", {"person_id": person}),
                         ("read_hr_clearance", {"employee_number": person})])
if qualification is None:
    finish("Blocked: neither the qualification record nor the HR clearance could be read.")
if not qualification.get("qualified"):
    finish("Blocked: employee-204 is not qualified for lab-east.")
qualification_ref = qualification.get("qualification_ref") or qualification.get("clearance_ref")
approval = call("get_access_approval", person_id=person, area=area)
if "error" in approval:
    escalate("The approval could not be read: " + approval["error"])
if approval.get("decision") != "approved":
    finish("Blocked: the access approval for employee-204 in lab-east is " + str(approval.get("decision")) + ".")
credential = call("get_facility_credential", area=area)
if "error" in credential:
    escalate("No area credential: " + credential["error"])

def grant(credential_ref):
    return call("set_facility_access", person_id=person, area=area, expires_at=expiry,
                qualification_ref=qualification_ref, approval_ref=approval["approval_ref"],
                credential_ref=credential_ref)

granted = grant(credential["credential_ref"])
'''
REFRESH = '''
if granted.get("code") == "credential_expired":
    fresh = call("refresh_facility_credential", expired_credential_ref=credential["credential_ref"])
    if "error" in fresh:
        escalate("The credential refresh failed: " + fresh["error"])
    granted = grant(fresh["credential_ref"])
'''
CHECK_ACCESS = '''
if "error" in granted:
    escalate("Granting access failed: " + granted["error"])
access = call("get_effective_access", person_id=person, area=area)
if access.get("status") != "active" or access.get("expires_at") != expiry:
    escalate("The effective-access read-back does not show the requested access.")
finish("employee-204 has active access to lab-east until " + expiry + ".")
'''


def case(case_id, title, recipient=""):
    body = CASE.format(case=case_id, title=title)
    tail = NOTICE.format(recipient=recipient) if recipient else (
        '\nfinish("Published internal note " + note["url"] + "; no notification sent.")\n')
    return body + tail


BODIES = {
    "case-handoff": (case("HD-417", "VPN handoff", "netops@company.test"),) * 2,
    "case-archive": (case("HD-582", "Scanner incident"),) * 2,
    "stock-reservation": (STOCK + RESERVE + CHECK_STOCK,) * 2,
    "stock-write-recovery": (STOCK + RESERVE_REQUEST + CHECK_STOCK, STOCK + RESERVE_REQUEST_HAPPY + CHECK_STOCK),
    "artifact-release": (RELEASE + RELEASE_UNKNOWN + CHECK_RELEASE, RELEASE + RELEASE_HAPPY + CHECK_RELEASE),
    "facility-access": (ACCESS + REFRESH + CHECK_ACCESS, ACCESS + CHECK_ACCESS),
}
PROGRAMS = {task: {"contingency": ACQUIRE + bodies[0], "happy_path": FIRST + bodies[1]}
            for task, bodies in BODIES.items()}


def cells():
    rows = []
    for task in DEVELOPMENT:
        for fault in FAULTS:
            try:
                RecoverySession(task, fault)
            except ValueError:
                continue
            rows.append((task, fault))
    return rows


@contextmanager
def deterministic_references():
    """Same reference stream for every run, so two programs' shared prefixes are identical."""
    counter = iter(range(1, 10_000))
    stream = lambda _=12: f"{next(counter):024x}"
    with patch("extensions.toolmaze_recovery.environment.token_hex", side_effect=stream), \
            patch("extensions.toolmaze_recovery.families.token_hex", side_effect=stream):
        yield


def execute(task, fault, style):
    session = RecoverySession(task, fault)
    with deterministic_references():
        program = run_program(session, PROGRAMS[task][style])
    scored = evaluate(session, program["answer"])
    trace = [(e["tool"], e["arguments"]) for e in session.events]
    return program, scored, trace


def summarize(task, fault, style, program, scored):
    expected = "correct_stop" if fault in STOPS else "strict_success"
    calls = len(scored["events"])
    return {
        "task": task, "fault": fault, "style": style, "status": program["status"],
        "expected": expected, "met": bool(program["status"] == "finished" and scored[expected]),
        "strict_success": scored["strict_success"], "correct_stop": scored["correct_stop"],
        "issues": scored["issues"], "illegal_calls": scored["illegal_calls"], "calls": calls,
        "tool_fee": scored["tool_fee"], "diagnostic_fee": scored["diagnostic_fee"],
        "answer": program["answer"], "escalation_reason": program["reason"], "error": program["error"],
        # One model decision per tool call plus the final reply, if the same actions are taken stepwise.
        "stepwise_decisions": calls + 1,
        "program_decisions": 1,
    }


def grid():
    rows = []
    for task, fault in cells():
        full, full_scored, full_trace = execute(task, fault, "contingency")
        happy, happy_scored, happy_trace = execute(task, fault, "happy_path")
        row = summarize(task, fault, "contingency", full, full_scored)
        other = summarize(task, fault, "happy_path", happy, happy_scored)
        if happy["status"] == "finished":
            other["hybrid_decisions"] = 1
            other["prefix_matches"] = happy_trace == full_trace
        else:
            # Lower bound: one program request, then a stepwise continuation that takes the
            # reference program's remaining actions, valid only when the two traces agree so far.
            k = len(happy_trace)
            other["prefix_matches"] = happy_trace == full_trace[:k]
            other["hybrid_decisions"] = 1 + (len(full_trace) - k) + 1 if other["prefix_matches"] else None
        rows += [row, other]
    return rows


def report(rows):
    out = {}
    for style in ("contingency", "happy_path"):
        part = [r for r in rows if r["style"] == style]
        out[style] = {
            "cells": len(part), "met": sum(r["met"] for r in part),
            "status": dict(Counter(r["status"] for r in part)),
            "illegal_calls": sum(r["illegal_calls"] for r in part),
            "tool_fee": sum(r["tool_fee"] for r in part), "diagnostic_fee": sum(r["diagnostic_fee"] for r in part),
            "stepwise_decisions": sum(r["stepwise_decisions"] for r in part),
            "program_decisions": sum(r["program_decisions"] for r in part),
        }
    hybrid = [r["hybrid_decisions"] for r in rows if r["style"] == "happy_path"]
    out["happy_path"]["hybrid_decisions"] = None if None in hybrid else sum(hybrid)
    out["happy_path"]["prefix_mismatches"] = sum(not r["prefix_matches"] for r in rows if r["style"] == "happy_path")
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True)
    rows = grid()
    summary = {
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "program_sha256": {task: {style: sha256(text.encode()).hexdigest() for style, text in styles.items()}
                           for task, styles in PROGRAMS.items()},
        "totals": report(rows),
    }
    (args.out / "cells.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary["totals"], indent=1))


if __name__ == "__main__":
    main()
