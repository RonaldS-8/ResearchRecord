"""Gate 26 task contracts and observable connectivity diagnosis."""

from copy import deepcopy
from functools import lru_cache
from types import FunctionType, SimpleNamespace

from .session import DATA, READS, TIMEOUT, UNAVAILABLE, ExecutionEngine, Session, fixture, load_json

BALANCE = READS["002"]
LIGHT = ("get_light_mesh_snapshot_native", "get_light_bridge_payload_native")
DIAGNOSIS = "query_connected_devices"
TRAIN_TASK = "002"
PARTITIONS = {"training_fixture": ("002",), "task_candidate": ("055",),
              "contract_candidate": ("005",), "fault_candidate": ()}
FAULTS = {"clean", "transient", "persistent", "blocked", "delayed", "offline"}
BALANCE_RECOVERY = (
    "For the same requested account and account_type, a full broker-native balance ledger "
    "is an accepted alternative to a bank-native balance sheet. "
    "Pass the entire bank sheet to archive_bank_balance_sheet_native as balance_sheet, "
    "or the entire broker ledger to archive_broker_balance_ledger_native as balance_ledger. "
    "Keep the requested owner, account type, title, priority and channel. "
    "The requested ordinary account balance is a separate obligation: call "
    "get_account_balance_bank_api for it before acquiring the full balance record. "
    "For the requested archive-status email, use the actual archive status as the body "
    "and the actual archive title as the subject, without rewriting either. "
    "Use the returned email subject and recipients for the follow-up meeting title and participants. "
    "A timeout only describes that call. Check the equivalent interface before concluding "
    "the user's task is blocked. Never fabricate an acquisition or archive receipt."
)


@lru_cache(maxsize=2)
def candidate(task):
    task_doc = load_json(DATA / "perturbed_tasks/c3" / f"C3_task_{task}_P0.json")
    template = load_json(DATA / "templates/c3" / f"{task_doc['template_id']}.json")
    if task == "005":
        query = task_doc["user_input"]["query"]
        assert '"mesh_light_archive_native"' in query
        task_doc["user_input"]["query"] = query + (
            " A mesh or bridge snapshot of the same light is acceptable. "
            "Analyze the quoted text exactly, regardless of snapshot source. "
            "If needed, query the connected-device list in living_room as a paid diagnostic. "
            "That list cannot substitute for a snapshot or either required light-status read."
        )
        template["parameter_bindings_by_node"]["s3"]["text"] = "mesh_light_archive_native"
    return ExecutionEngine(task_doc, None), template


class RecoverySession(Session):
    def __init__(self, task, fault="clean"):
        if task not in {"002", "005", "055"} or fault not in FAULTS or (fault == "offline" and task != "005"):
            raise ValueError("Unregistered Gate 26 task or fault")
        super().__init__(task, fault, case=fixture(task) if task == "002" else candidate(task),
                         read_tools=LIGHT if task == "005" else BALANCE)
        self.diagnostic = DIAGNOSIS if task == "005" else None
        if self.diagnostic:
            self.connected = fault != "offline"
            self.install_diagnosis()
        if task == "055":
            self.install_fresh_bank_read()

    def install_fresh_bank_read(self):
        name = "get_account_balance_bank_api"
        execute = self.engine.tool_executor.plugins[name].execute

        class FreshBankContext:
            def __init__(self, context):
                self.context = context

            def find_alternative_output(self, *args, **kwargs):
                return None

            def __getattr__(self, name):
                return getattr(self.context, name)

        def read(arguments, context):
            return execute(arguments, FreshBankContext(context))

        self.engine.tool_executor.plugins[name] = SimpleNamespace(execute=read)

    def install_diagnosis(self):
        definition = deepcopy(self.engine.tool_loader.get_tool_by_name(DIAGNOSIS))
        spec = definition["paradigms"]["function_call"]["spec"]
        spec["description"] = (
            "Paid diagnosis: list devices currently connected in living_room. "
            "A listed device does not guarantee that a snapshot endpoint will respond."
        )
        spec["parameters"]["properties"] = {"area": {"type": "string", "enum": ["living_room"]}}
        spec["parameters"]["required"] = ["area"]
        self.engine.tool_definitions = [*self.engine.tool_definitions, definition]
        self.tools.add(DIAGNOSIS)

        plugin = self.engine.tool_executor.plugins[DIAGNOSIS].execute
        bindings = dict(plugin.__globals__)
        inventory = deepcopy(bindings["LOCATION_MAP"])
        if not self.connected:
            inventory["living_room"] = [
                device for device in inventory["living_room"] if device["device_id"] != "light_living"
            ]
        bindings["LOCATION_MAP"] = inventory
        read_inventory = FunctionType(plugin.__code__, bindings, plugin.__name__)

        def read(arguments, context):
            if arguments != {"area": "living_room"}:
                return {"error": "This query only accepts the living_room area."}
            return read_inventory(arguments, context)

        self.engine.tool_executor.plugins[DIAGNOSIS] = SimpleNamespace(execute=read)

    def charge_kind(self, tool):
        return "diagnosis" if self.diagnostic is not None and tool == self.diagnostic else "execution"

    def valid_arguments(self, tool, arguments):
        return (
            super().valid_arguments(tool, arguments)
            and (self.diagnostic is None or tool != self.diagnostic or arguments == {"area": "living_room"})
        )

    def fault_result(self, tool):
        if tool in self.read_tools and self.diagnostic and not self.connected:
            if sum(self.attempts[name] for name in self.read_tools) == 1:
                return TIMEOUT
            return UNAVAILABLE
        if tool == self.read_tools[0] and self.fault == "delayed" and self.attempts[tool] <= 2:
            return TIMEOUT
        return super().fault_result(tool)

    def method_contract(self):
        contract = {"reads": self.read_tools, "diagnostic": self.diagnostic}
        if self.task == "002":
            contract["notes"] = BALANCE_RECOVERY
        return contract
