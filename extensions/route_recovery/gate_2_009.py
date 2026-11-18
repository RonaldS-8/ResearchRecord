"""Public task projection and deterministic policy for experiment 2_009."""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

from extensions.toolmaze_recovery.route_discovery import Deriver, tokens


ROOT = Path(__file__).resolve().parents[2]
DEFINITIONS = ROOT / "benchmarks/ToolMaze/tools/definitions"
ARMS = ("00", "10", "01", "11")
ORDERS = tuple(ARMS[i:] + ARMS[:i] for i in range(4))
MODEL = "Qwen3-4B-Thinking-2507"
REVISION = "768f209d9ea81521153ed38c47d515654e938aea"
MAX_REQUESTS = 8
MAX_CALLS = 12
MAX_OUTPUT = 6144
CONTEXT = 32768


@dataclass(frozen=True)
class Task:
    number: int
    target: str
    failed_tool: str
    failed_arguments: dict
    error: str
    objective: str
    keys: tuple
    title: str
    recipient: str
    channel: str
    priority: str

    @property
    def identifier(self):
        return f"C3_task_{self.number:03d}_P2"

    @property
    def values(self):
        return self.failed_arguments | {
            "title": self.title, "user_id": self.recipient,
            "channel": self.channel, "priority": self.priority,
        }

    def statements(self):
        return (
            self.objective,
            f'Save that data as a document titled "{self.title}" and send one simulated '
            f"{self.channel} notification containing the document title to {self.recipient} "
            f"with {self.priority} priority. Save and notify exactly once.",
            "Check the actual save and notification receipts and report both receipt IDs "
            "from this run in your final answer.",
        )


TASKS = (
    Task(2, "user_01", "get_bank_balance_sheet_native",
         {"user_id": "user_01", "account_type": "investment"}, "Tool Not Found",
         "Retrieve the investment account data for user_01, including the account "
         "identifier, account type, balance and currency.",
         ("account", "type", "balance", "currency"), "Q3 Portfolio Balance", "user_01", "email", "high"),
    Task(5, "light_living", "get_light_mesh_snapshot_native",
         {"light_id": "light_living"}, "Account Quota Exhausted",
         "Retrieve the state of light_living, including the device identifier, "
         "power state, brightness and color.",
         ("device", "power", "brightness", "color"), "System Light State Archive", "user_1234", "app", "medium"),
    Task(11, "CA1234", "get_aviationstack_gate_board_native",
         {"flight_number": "CA1234"}, "Unavailable For Legal Reasons",
         "Retrieve the details of flight CA1234, including the flight number, "
         "departure, arrival, gate and status.",
         ("flight", "departure", "arrival", "gate", "status"), "Hilton Tokyo", "user_889", "email", "high"),
    Task(26, "London", "get_weatherapi_alert_card_native",
         {"city": "London"}, "Not Implemented",
         "Retrieve London weather data, including the city, temperature in Celsius, "
         "conditions and advisory level.",
         ("city", "temperature", "conditions", "advisory"), "Trip Weather Archive", "user_1234", "app", "medium"),
)

SOURCES = (
    "get_bank_balance_sheet_native", "get_broker_balance_ledger_native",
    "get_account_balance", "get_account_balance_bank_api", "get_account_balance_broker_api",
    "get_light_mesh_snapshot_native", "get_light_bridge_payload_native",
    "get_iot_device_status", "get_light_status",
    "get_aviationstack_gate_board_native", "get_flightaware_trip_timeline_native",
    "get_flight_info", "get_flight_info_aviationstack", "get_flight_info_flightaware",
    "get_weatherapi_alert_card_native", "get_visualcrossing_forecast_chip_native",
    "get_weather_openweather", "get_weather_weatherapi", "get_weather_visualcrossing",
)
ARCHIVE = (
    "bank_balance_sheet", "broker_balance_ledger", "light_mesh_snapshot", "light_bridge_payload",
    "aviationstack_gate_board", "flightaware_trip_timeline", "weatherapi_alert_card",
    "visualcrossing_forecast_chip",
)
TOOLS = tuple(sorted((*SOURCES, *(f"archive_{name}_native" for name in ARCHIVE),
                      "create_document_and_alert_from_data")))


def public_contracts():
    """One projection for model cards, route search and the rule; omit internal metadata."""
    public = {}
    for filename in ("source", "processor", "action"):
        for tool in yaml.safe_load((DEFINITIONS / f"{filename}.yaml").read_text())["tools"]:
            name = tool["name"]
            if name not in TOOLS:
                continue
            paradigms = tool["paradigms"]
            spec = paradigms["function_call"]["spec"]
            mcp = paradigms["mcp"]
            outputs = mcp["output_schema"]
            spec["description"] = (
                f"{spec['description']}\n{mcp['prompt_description']}\n"
                f"Public output schema: {yaml.safe_dump(outputs, default_flow_style=True, width=10000).strip()}"
            )
            public[name] = {"paradigms": {"function_call": {"spec": spec}}, "outputs": outputs}
    if set(public) != set(TOOLS):
        raise ValueError("Fixed public tool pool is incomplete")
    return {name: public[name] for name in TOOLS}


def candidates(task, cards):
    projected = {}
    for name, card in cards.items():
        spec = card["paradigms"]["function_call"]["spec"]
        parameters = spec["parameters"]
        projected[name] = {
            "name": name, "description": spec["description"],
            "params": {key: {"description": value.get("description", ""), "enum": bool(value.get("enum"))}
                       for key, value in parameters["properties"].items()},
            "required": parameters.get("required", []), "outputs": list(card["outputs"]),
        }
    search = Deriver(projected, {"beam": 200})
    goal = search.bag[task.failed_tool] + Counter(tokens(" ".join(task.statements())))
    fields = list(task.values)
    if "light_id" in task.values:
        fields.append("device_id")  # two public schema names for the same user-specified object
    chains = search.chains(fields, goal, avoid=(task.failed_tool,))
    eligible = {
        chain for chain in chains
        if 2 <= len(chain) <= 4 and task.failed_tool not in chain
        and {"note_id", "notification_id"} <= cards[chain[-1]]["outputs"].keys()
    }
    return sorted(eligible, key=lambda chain: (
        -search.cos(sum((search.bag[tool] for tool in chain), Counter()), goal), len(chain), chain,
    ))


def message(task, receipt, arm, routes):
    objectives = task.statements()
    prompt = (
        "Continue this simulated task after the failed tool call. "
        + " ".join(objectives)
        + f"\nFailed call: {task.failed_tool}({task.failed_arguments!r})"
        + f"\nObserved error receipt: {receipt!r}"
    )
    if arm[0] == "1":
        prompt += "\n\nUnverified candidate tool sequences (you may use or skip them):"
        prompt += "".join("\n- " + " → ".join(route) for route in routes[:5]) or "\n- None found."
    if arm[1] == "1":
        prompt += "\n\nRemaining obligations:"
        for label, text in zip(("Object and contents", "Archive and notify", "Check and report"), objectives):
            prompt += f"\n- {label}: {text}"
    return prompt


# Public vocabulary used by the rule, separated from the independent outcome rubric.
TERMS = {
    "account": ("user", "owner", "principal"), "type": ("type", "bucket"),
    "balance": ("balance", "equity"), "currency": ("currency", "denomination"),
    "device": ("device", "light", "node"), "power": ("power", "state"),
    "brightness": ("brightness", "dimmer", "level"), "color": ("color", "colour", "hue", "tone"),
    "flight": ("flight",), "departure": ("dep", "departure", "route"),
    "arrival": ("arr", "arrival", "route"), "gate": ("gate",), "status": ("status", "state"),
    "city": ("city", "locality"), "temperature": ("temp", "temperature", "celsius"),
    "conditions": ("sky", "condition", "conditions"), "advisory": ("advice", "advisory"),
}


def has_public_content(task, data):
    keys = [set(tokens(key)) for key, value in data.items() if value is not None and value != ""]
    return (
        any(isinstance(value, str) and value.casefold() == task.target.casefold() for value in data.values())
        and all(any(set(TERMS[concept]) & key for key in keys) for concept in task.keys)
    )


def bind(task, contract, prior, writing):
    spec = contract["paradigms"]["function_call"]["spec"]["parameters"]
    values = task.values
    if "light_id" in values:
        values = values | {"device_id": values["light_id"]}
    arguments = {key: value for key, value in values.items() if key in spec["properties"]}
    for key in spec.get("required", ()):
        if key in arguments:
            continue
        matches = [result[key] for result in prior if key in result]
        if matches and all(value == matches[0] for value in matches):
            arguments[key] = matches[0]
            continue
        # A whole-object input is legal when a unique current source response can fill it.
        prop = spec["properties"][key]
        sources = [result for result in prior if has_public_content(task, result)]
        if writing and len(sources) == 1 and prop.get("type") in (None, "object"):
            arguments[key] = sources[0]
            continue
        return None
    return arguments


def deterministic(task, cards, routes, call):
    """Try public candidates within the call cap; never repeat a possible write."""
    reads = {}
    attempts = 0
    for route in routes:
        prior = []
        for index, tool in enumerate(route):
            writing = {"note_id", "notification_id"} <= cards[tool]["outputs"].keys()
            if writing != (index == len(route) - 1):
                break
            arguments = bind(task, cards[tool], prior, writing)
            if arguments is None or (writing and not any(has_public_content(task, value) for value in prior)):
                break
            key = (tool, repr(sorted(arguments.items())))
            if not writing and key in reads:
                result = reads[key]
            else:
                if attempts == MAX_CALLS:
                    return None, "tool_budget"
                attempts += 1
                result = call(tool, arguments)
            if writing:
                if result.get("title") == task.title and result.get("note_id") and result.get("notification_id"):
                    return (f"Checked the archive and notification receipts for {task.title}. "
                            f"Note ID: {result['note_id']}. Notification ID: {result['notification_id']}."), "answered"
                return None, "write_receipt_unknown"
            reads[key] = result
            if "error" in result:
                break
            prior.append(result)
    return None, "no_bound_route"
