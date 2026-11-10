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
}

READS = {
    "case": ("get_case_record", "read_case_archive"),
    "stock": ("get_depot_inventory", "read_depot_count"),
}
DIAGNOSTIC = "read_service_status"
RESERVATION_LOOKUP = "lookup_reservations_by_request"
# Resource arguments are also used to enforce the read/write authorization scope.
RESOURCE_FIELDS = {
    "get_case_record": "case_id", "read_case_archive": "ticket",
    "publish_case_note": "case_id", "get_depot_inventory": "sku",
    "read_depot_count": "item_code", "reserve_stock": "sku",
    DIAGNOSTIC: "resource_id",
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
TOOLS = {"case": (*CASE_TOOLS, STATUS_TOOL), "stock": (*STOCK_TOOLS, STATUS_TOOL)}
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
