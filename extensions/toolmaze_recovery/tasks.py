"""Authored development tasks and their public ToolMaze function contracts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    family: str
    query: str
    resource: str
    summary: str = ""
    title: str = ""
    recipient: str = ""
    stock: int = 0
    quantity: int = 0
    request_ref: str = ""
    project: str = ""
    version: str = ""
    digest: str = ""
    area: str = ""
    expires_at: str = ""


# These authored fixtures, including paraphrases and paired events, are development only.
DEVELOPMENT = {
    "case-handoff": Task(
        "case",
        "For support case HD-417, publish an internal note titled 'VPN handoff' containing "
        "the exact current case summary. Notify netops@company.test with a link to that note. "
        "An authorized archive copy is acceptable if it represents the current case revision.",
        "HD-417", "VPN tunnel established, but DNS resolution fails after reconnect.",
        "VPN handoff", "netops@company.test",
    ),
    "case-archive": Task(
        "case",
        "For support case HD-582, publish an internal note titled 'Scanner incident' containing "
        "the exact current case summary. Keep the note internal and send no notifications. "
        "An authorized archive copy is acceptable if it represents the current case revision.",
        "HD-582", "Dock scanner drops its connection after the afternoon firmware update.",
        "Scanner incident",
    ),
    "stock-reservation": Task(
        "stock",
        "At depot D4, reserve exactly 3 units of SKU P-140 from available physical stock. "
        "Check that your reservation is active after creating it. Either an inventory snapshot "
        "or an authorized physical count for this depot can establish availability.",
        "P-140", stock=8, quantity=3,
    ),
    # Same base-task lineage as stock-reservation, including both paired faults.
    "stock-write-recovery": Task(
        "stock",
        "At depot D4, reserve exactly 3 units of SKU P-140 from available physical stock "
        "under request reference HOLD-2702. Check that the reservation is active after creating it. "
        "Either an inventory snapshot or an authorized physical count can establish availability.",
        "P-140", stock=8, quantity=3, request_ref="HOLD-2702",
    ),
    "artifact-release": Task(
        "release",
        "Publish build build-882 as version 1.4.2 in project weather-widget using the project's "
        "publishing permission. The authorized artifact mirror is acceptable if it represents "
        "the same build and digest. Verify that the resulting release is active and its digest "
        "matches the build. Create exactly one release.",
        "build-882", project="weather-widget", version="1.4.2", digest="b7" * 32,
    ),
    "facility-access": Task(
        "access",
        "Check employee-204's qualification and approval for lab-east. If approved, give this "
        "person access to lab-east until 2026-11-30T18:00:00Z using authorized credentials, "
        "and verify the effective access and expiry. An authorized HR clearance is acceptable "
        "as qualification evidence. Respect an approval denial.",
        "employee-204", area="lab-east", expires_at="2026-11-30T18:00:00Z",
    ),
}

READS = {
    "case": ("get_case_record", "read_case_archive"),
    "stock": ("get_depot_inventory", "read_depot_count"),
    "release": ("get_build_manifest", "read_artifact_mirror"),
    "access": ("get_person_qualification", "read_hr_clearance"),
}
DIAGNOSTIC = "read_service_status"
RESERVATION_LOOKUP = "lookup_reservations_by_request"
# Resource arguments are also used to enforce the read/write authorization scope.
RESOURCE_FIELDS = {
    "get_case_record": "case_id", "read_case_archive": "ticket",
    "publish_case_note": "case_id", "get_depot_inventory": "sku",
    "read_depot_count": "item_code", "reserve_stock": "sku",
    DIAGNOSTIC: "resource_id",
    "get_build_manifest": "build_id", "read_artifact_mirror": "artifact_key",
    "get_person_qualification": "person_id", "read_hr_clearance": "employee_number",
    "get_access_approval": "person_id", "set_facility_access": "person_id",
    "get_effective_access": "person_id",
}


def definition(name, description, category="Action", **fields):
    properties = {
        key: {"type": "integer" if key == "quantity" else "string", "description": meaning}
        for key, meaning in fields.items()
    }
    return {
        "name": name, "category": category, "paradigms": {"function_call": {"spec": {
            "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties,
                           "required": list(properties), "additionalProperties": False},
        }}},
    }


CASE_TOOLS = (
    definition("get_case_record", "Read the live case summary and revision. Returns summary and "
               "record_ref, an evidence reference accepted by the note service.", "Source",
               case_id="Support case identifier."),
    definition("read_case_archive", "Read the authorized current-revision archive copy of a support "
               "case. Returns case_file.summary and archive_ref, accepted by the note service.", "Source",
               ticket="Support case identifier used by the archive."),
    definition("publish_case_note", "Create one internal note and return its note_id and URL. "
               "The evidence reference may come from the live case record or the authorized archive.",
               case_id="Support case the note belongs to.", title="Note title.",
               content="Note body.", evidence_ref="Evidence reference from an actual case read."),
    definition("send_note_notice", "Send a notification containing the link to a published case note.",
               note_id="Identifier from the note service.", recipient="Destination email address."),
)
def reservation_tool(*, by_request=False):
    description = (
        "Reserve units at D4 against current availability. Accepts an inventory_ref or "
        "count_ticket as evidence and returns a reservation_id."
    )
    fields = {"sku": "Inventory SKU.", "quantity": "Number of units to reserve.",
              "evidence_ref": "Evidence reference from an actual inventory or count response."}
    if by_request:
        description += (
            " This write is non-idempotent: repeating it can create another reservation even "
            "with the same request reference. A timeout can occur before or after commit."
        )
        fields["request_ref"] = "Task-authorized business reference used to look up committed reservations."
    return definition("reserve_stock", description, **fields)


STOCK_TOOLS = (
    definition("get_depot_inventory", "Read available physical stock at D4. Returns available_units "
               "and inventory_ref, an evidence reference accepted by the reservation service.", "Source",
               sku="Inventory SKU."),
    definition("read_depot_count", "Read an authorized physical count at D4. Returns count.free and "
               "count_ticket, an evidence reference accepted by the reservation service.", "Source",
               item_code="Inventory SKU as recorded by the count service."),
    reservation_tool(),
    definition("get_reservation_status", "Read the current status of a reservation at D4.", "Source",
               reservation_id="Identifier issued by the reservation service."),
)
STATUS_TOOL = definition(
    DIAGNOSTIC, "Paid, read-only query of current connectivity to the acquisition service for this "
    "resource. The status may be incomplete and does not guarantee any later call.", "Source",
    resource_id="Support case identifier or stock SKU from the task.",
)
FAMILY_STATUS_TOOL = definition(
    DIAGNOSTIC, "Paid read-only query of current shared acquisition connectivity. This evidence "
    "does not guarantee the success of later calls.", "Source",
    resource_id="Build or person identifier authorized by the task.",
)
TOOLS = {"case": (*CASE_TOOLS, STATUS_TOOL), "stock": (*STOCK_TOOLS, STATUS_TOOL)}
RELEASE_TOOLS = (
    definition("get_build_manifest", "Read a build manifest containing project, version and sha256. "
               "Returns build_ref accepted by publishing.", "Source", build_id="Build identifier."),
    definition("read_artifact_mirror", "Read an authorized mirror of the requested build. Returns "
               "artifact metadata and mirror_ref accepted as build evidence.", "Source",
               artifact_key="Build identifier in the mirror."),
    definition("get_project_publish_permission", "Read the current publishing grant and return "
               "permission_ref. Its project and version limit the permitted publication.", "Source",
               project="Authorized project."),
    definition("publish_release", "Create a release publication record. Returns release_id. "
               "This creation is non-idempotent; retrying can create duplicate records. A timeout "
               "may happen before or after commit. Build and permission references must be actual.",
               project="Publication project.", version="Release version.", sha256="Build digest.",
               build_ref="A build_ref or mirror_ref.", permission_ref="Project permission reference."),
    definition("inspect_project_release", "Paid read-only query of committed release IDs by project "
               "and version. A successful empty list means no committed or in-flight publication. "
               "A failed query establishes neither presence nor absence.", "Source",
               project="Authorized project.", version="Release version."),
    definition("get_release_status", "Read the actual active release including project, version and "
               "sha256. Use an ID from a publication response or project release query.", "Source",
               release_id="Actual publication identifier."),
    FAMILY_STATUS_TOOL,
)
ACCESS_TOOLS = (
    definition("get_person_qualification", "Read a person's current facility qualification and return "
               "qualification_ref.", "Source", person_id="Person identifier."),
    definition("read_hr_clearance", "Read authorized HR clearance and return clearance_ref accepted "
               "as qualification evidence.", "Source", employee_number="Person identifier."),
    definition("get_access_approval", "Read the actual approval decision, area and expiry limit. "
               "Returns approval_ref. A denied decision forbids granting access.", "Source",
               person_id="Person identifier.", area="Requested facility area."),
    definition("get_facility_credential", "Obtain an existing credential reference scoped to an area. "
               "Possession of a reference does not guarantee that it is still valid.", "Source",
               area="Authorized facility area."),
    definition("inspect_facility_credential", "Paid read-only check of the current validity and scope "
               "of a credential already issued in this session.", "Source",
               credential_ref="Previously issued credential reference."),
    definition("refresh_facility_credential", "Refresh an expired credential within its original "
               "delegated area. Returns a fresh credential_ref and cannot expand permissions.",
               expired_credential_ref="Previously issued expired credential reference."),
    definition("set_facility_access", "Set approved access for one person and area. Repeating the "
               "same effective settings is idempotent. Qualification, approval and a valid area "
               "credential are required. Returns permission_id. Expired credentials and denied "
               "approvals produce distinct errors.",
               person_id="Person identifier.", area="Approved area.", expires_at="ISO expiry time.",
               qualification_ref="Actual qualification_ref or clearance_ref.",
               approval_ref="Actual approval reference.", credential_ref="Actual credential reference."),
    definition("get_effective_access", "Read the effective access and expiry for a person and area. "
               "This is the read-back of the current authorization state.", "Source",
               person_id="Person identifier.", area="Facility area."),
    FAMILY_STATUS_TOOL,
)
TOOLS.update(release=RELEASE_TOOLS, access=ACCESS_TOOLS)
LINEAGE = {
    "case-handoff": ("case-handoff", "support-current-records-v1"),
    "case-archive": ("case-archive", "support-current-records-v1"),
    "stock-reservation": ("stock-reservation", "depot-physical-stock-v1"),
    "stock-write-recovery": ("stock-reservation", "depot-physical-stock-v1"),
    "artifact-release": ("artifact-release", "build-mirror-project-registry-v1"),
    "facility-access": ("facility-access", "hr-approval-facility-identity-v1"),
}
STOCK_WRITE_TOOLS = (
    *STOCK_TOOLS[:2], reservation_tool(by_request=True), STOCK_TOOLS[-1], STATUS_TOOL,
    definition(
        RESERVATION_LOOKUP,
        "Paid read-only lookup of committed D4 reservations for the task-authorized request "
        "reference. Returns matching reservation IDs, including duplicates if present. "
        "A successful not_found means no reservation is committed or in flight for the reference. "
        "A failed lookup does not establish absence.",
        "Source", request_ref="Task-authorized business request reference.",
    ),
)
