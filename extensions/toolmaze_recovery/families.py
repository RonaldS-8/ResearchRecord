"""Business state and independent outcome checks for release and facility tasks."""

from copy import deepcopy
from secrets import token_hex

from .environment import RELEASE_TIMEOUT, invalid

EXPIRED = {"error": "The facility credential has expired.", "code": "credential_expired"}
DENIED = {"error": "Access approval was denied for this person and area.", "code": "authorization_denied"}


def issue(session, tool, field, payload):
    reference = token_hex(12)
    result = {field: reference, **payload}
    session.acquisitions[reference] = {
        "call": len(session.events) + 1, "tool": tool, "resource": session.goal.resource,
        "result": deepcopy(result),
    }
    return result


def source(session, reference, tools, *, before=None):
    receipt = session.acquisitions.get(reference)
    if receipt is None or receipt["tool"] not in tools:
        return None
    if before is not None and receipt["call"] >= before:
        return None
    event = session.events[receipt["call"] - 1]
    if (event["illegal"] or event["tool"] != receipt["tool"] or "error" in event["result"]
            or event["result"] != receipt["result"] or reference not in event["result"].values()):
        return None
    return receipt["result"]


def visible_release_id(session, release_id, before):
    for event in session.events[:before - 1]:
        if event["illegal"] or "error" in event["result"]:
            continue
        if (event["tool"] == "publish_release" and event["result"].get("release_id") == release_id
                or event["tool"] == "inspect_project_release"
                and release_id in event["result"].get("release_ids", [])):
            return True
    return False


class ReleaseBackend:
    def __init__(self, session):
        self.session = session
        self.records = {}
        self.checks = []

    def operations(self):
        return {
            "get_project_publish_permission": self.permission,
            "publish_release": self.publish, "inspect_project_release": self.inspect,
            "get_release_status": self.status,
        }

    def acquire(self, tool):
        goal = self.session.goal
        manifest = {"build_id": goal.resource, "project": goal.project,
                    "version": goal.version, "sha256": goal.digest}
        key = "build_ref" if tool == "get_build_manifest" else "mirror_ref"
        shape = "manifest" if tool == "get_build_manifest" else "artifact"
        return issue(self.session, tool, key, {shape: manifest})

    def permission(self, project):
        return issue(self.session, "get_project_publish_permission", "permission_ref", {
            "project": project, "version": self.session.goal.version, "allowed": True,
        })

    def publish(self, project, version, sha256, build_ref, permission_ref):
        session = self.session
        build = source(session, build_ref, session.read_tools)
        permission = source(session, permission_ref, ("get_project_publish_permission",))
        if build is None or permission is None:
            return invalid("Actual build and project permission references are required.")
        manifest = build.get("manifest", build.get("artifact"))
        if ((manifest["project"], manifest["version"], manifest["sha256"]) != (project, version, sha256)
                or (permission["project"], permission["version"], permission["allowed"])
                != (project, version, True)):
            return invalid("The build digest or project grant does not authorize this publication.")
        ambiguous = session.fault in ("write_not_committed", "write_response_lost") and not session.write_timeout_used
        if ambiguous:
            session.write_timeout_used = True
            if session.fault == "write_not_committed":
                return RELEASE_TIMEOUT
        record = {
            "release_id": token_hex(12), "project": project, "version": version, "sha256": sha256,
            "build_ref": build_ref, "permission_ref": permission_ref, "status": "active",
        }
        self.records[record["release_id"]] = record
        session.record_effect("publish_release", record)
        return RELEASE_TIMEOUT if ambiguous else {"release_id": record["release_id"]}

    def inspect(self, project, version):
        if not self.session.diagnosis_available:
            return {"error": "The release registry query did not respond."}
        ids = [key for key, row in self.records.items() if (row["project"], row["version"]) == (project, version)]
        return {"project": project, "version": version, "release_ids": ids}

    def status(self, release_id):
        session = self.session
        if release_id not in self.records or not visible_release_id(session, release_id, len(session.events) + 1):
            return invalid("Use a release ID from an actual publication receipt or authorized query.")
        result = {k: v for k, v in self.records[release_id].items() if not k.endswith("_ref")}
        self.checks.append({"call": len(session.events) + 1, "result": deepcopy(result)})
        return result

    def issues(self):
        session, goal = self.session, self.session.goal
        if len(self.records) != 1 or [e["operation"] for e in session.effects] != ["publish_release"]:
            return ["Expected exactly one release publication."]
        row = next(iter(self.records.values()))
        effect = session.effects[0]
        if row != effect["state"] or (row["project"], row["version"], row["sha256"], row["status"]) != (
                goal.project, goal.version, goal.digest, "active"):
            return ["Release object, version or digest does not satisfy the request."]
        build = source(session, row["build_ref"], session.read_tools, before=effect["call"])
        permission = source(session, row["permission_ref"], ("get_project_publish_permission",), before=effect["call"])
        if build is None or permission is None:
            return ["Release evidence lacks actual causal receipts."]
        if (build.get("manifest", build.get("artifact")) != {
                "build_id": goal.resource, "project": goal.project, "version": goal.version, "sha256": goal.digest}
                or (permission["project"], permission["version"], permission["allowed"])
                != (goal.project, goal.version, True)):
            return ["Release evidence identifies the wrong build or publication permission."]
        expected = {k: v for k, v in row.items() if not k.endswith("_ref")}
        if not any(
            check["call"] > effect["call"] and check["result"] == expected
            and session.events[check["call"] - 1]["tool"] == "get_release_status"
            and session.events[check["call"] - 1]["result"] == expected
            and visible_release_id(session, row["release_id"], check["call"])
            for check in self.checks
        ):
            return ["Missing actual release read-back."]
        return []

    def denied(self):
        return False

    def report(self):
        return {"releases": self.records, "release_checks": self.checks}


class AccessBackend:
    def __init__(self, session):
        self.session = session
        self.credentials = {}
        self.permission = None
        self.checks = []

    def operations(self):
        return {
            "get_access_approval": self.approval, "get_facility_credential": self.credential,
            "inspect_facility_credential": self.inspect, "refresh_facility_credential": self.refresh,
            "set_facility_access": self.grant, "get_effective_access": self.effective,
        }

    def acquire(self, tool):
        goal = self.session.goal
        field = "qualification_ref" if tool == "get_person_qualification" else "clearance_ref"
        return issue(self.session, tool, field, {"person_id": goal.resource, "qualified": True})

    def approval(self, person_id, area):
        return issue(self.session, "get_access_approval", "approval_ref", {
            "person_id": person_id, "area": area, "expires_at": self.session.goal.expires_at,
            "decision": "denied" if self.session.fault == "authorization_denied" else "approved",
        })

    def credential(self, area):
        result = issue(self.session, "get_facility_credential", "credential_ref", {"area": area})
        self.credentials[result["credential_ref"]] = {
            "area": area, "status": "expired" if self.session.fault == "credential_expired" else "valid",
        }
        return result

    def inspect(self, credential_ref):
        if credential_ref not in self.credentials:
            return invalid("An actually issued credential is required.")
        if not self.session.diagnosis_available:
            return {"error": "Credential inspection did not respond."}
        return {"credential_ref": credential_ref, **self.credentials[credential_ref]}

    def refresh(self, expired_credential_ref):
        previous = self.credentials.get(expired_credential_ref)
        if previous is None or previous["status"] != "expired":
            return invalid("Only an issued expired credential can be refreshed.")
        result = issue(self.session, "refresh_facility_credential", "credential_ref", {"area": previous["area"]})
        self.credentials[result["credential_ref"]] = {"area": previous["area"], "status": "valid"}
        previous["status"] = "replaced"
        self.session.record_effect("refresh_facility_credential", {
            "expired_credential_ref": expired_credential_ref, **result,
        })
        return result

    def grant(self, person_id, area, expires_at, qualification_ref, approval_ref, credential_ref):
        session = self.session
        qualification = source(session, qualification_ref, session.read_tools)
        approval = source(session, approval_ref, ("get_access_approval",))
        credential = self.credentials.get(credential_ref)
        if qualification is None or approval is None or credential is None:
            return invalid("Actual qualification, approval and credential references are required.")
        if (qualification["person_id"] != person_id or not qualification["qualified"]
                or (approval["person_id"], approval["area"]) != (person_id, area)
                or credential["area"] != area or not expires_at or expires_at > approval["expires_at"]):
            return invalid("Evidence or requested scope/expiry exceeds the grant.")
        if approval["decision"] != "approved":
            return DENIED
        if credential["status"] != "valid":
            return EXPIRED
        if self.permission is not None and (
                self.permission["person_id"], self.permission["area"], self.permission["expires_at"]
        ) == (person_id, area, expires_at):
            return {"permission_id": self.permission["permission_id"], "status": "active"}
        self.permission = {
            "permission_id": token_hex(12), "person_id": person_id, "area": area, "expires_at": expires_at,
            "qualification_ref": qualification_ref, "approval_ref": approval_ref,
            "credential_ref": credential_ref, "status": "active",
        }
        session.record_effect("set_facility_access", self.permission)
        return {"permission_id": self.permission["permission_id"], "status": "active"}

    def effective(self, person_id, area):
        result = {"person_id": person_id, "area": area, "status": "absent"}
        if self.permission is not None:
            result = {k: v for k, v in self.permission.items() if not k.endswith("_ref")}
        self.checks.append({"call": len(self.session.events) + 1, "result": deepcopy(result)})
        return result

    def denied(self):
        goal = self.session.goal
        return any(
            e["tool"] == "get_access_approval" and not e["illegal"]
            and e["result"].get("decision") == "denied"
            and (e["result"].get("person_id"), e["result"].get("area")) == (goal.resource, goal.area)
            for e in self.session.events
        )

    def issues(self):
        session, goal = self.session, self.session.goal
        grants = [e for e in session.effects if e["operation"] == "set_facility_access"]
        if self.permission is None or len(grants) != 1:
            return ["Expected one effective authorization change."]
        if any(e["operation"] not in ("set_facility_access", "refresh_facility_credential") for e in session.effects):
            return ["Unexpected side effects in authorization task."]
        row, effect = self.permission, grants[0]
        if row != effect["state"] or (row["person_id"], row["area"], row["expires_at"], row["status"]) != (
                goal.resource, goal.area, goal.expires_at, "active"):
            return ["Effective access has the wrong subject, scope or expiry."]
        qualification = source(session, row["qualification_ref"], session.read_tools, before=effect["call"])
        approval = source(session, row["approval_ref"], ("get_access_approval",), before=effect["call"])
        credential = source(session, row["credential_ref"],
                            ("get_facility_credential", "refresh_facility_credential"), before=effect["call"])
        if qualification is None or approval is None or credential is None:
            return ["Authorization lacks actual causal receipts."]
        if (qualification["person_id"] != goal.resource or not qualification["qualified"]
                or (approval["person_id"], approval["area"], approval["decision"], approval["expires_at"])
                != (goal.resource, goal.area, "approved", goal.expires_at)
                or credential["area"] != goal.area):
            return ["Authorization evidence does not cover the requested scope."]
        expected = {k: v for k, v in row.items() if not k.endswith("_ref")}
        if not any(
            check["call"] > effect["call"] and check["result"] == expected
            and session.events[check["call"] - 1]["tool"] == "get_effective_access"
            and session.events[check["call"] - 1]["result"] == expected for check in self.checks
        ):
            return ["Missing actual effective-access read-back."]
        return []

    def report(self):
        return {"effective_access": self.permission, "access_checks": self.checks,
                "credential_states": self.credentials}
