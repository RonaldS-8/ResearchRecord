"""Engineering preflight for the fixed 2_009 batch."""

from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from . import gate_2_009 as protocol
from .audit_2_009 import grade
from .run_2_009 import ToolSession, comparable, guard, make_agent, public_scope


class LaunchChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cards = protocol.public_contracts()
        cls.task_root = protocol.ROOT / "benchmarks/ToolMaze/data/perturbed_tasks/c3"

    def session(self, task):
        return ToolSession(task, self.task_root / (task.identifier + ".json"))

    def test_prompt_factorization(self):
        self.assertEqual(len(self.cards), 28)
        for task in protocol.TASKS:
            receipt = {"error": task.error}
            routes = [("read_example", "write_example")]
            prompts = [protocol.message(task, receipt, arm, routes) for arm in protocol.ARMS]
            r00, r10, r01, r11 = prompts
            self.assertTrue(r10.startswith(r00))
            self.assertTrue(r01.startswith(r00))
            self.assertEqual(r11, r10 + r01[len(r00):])
            agents = [make_agent(prompt, self.cards) for prompt in prompts]
            for agent in agents[1:]:
                self.assertEqual(agent.messages[0], agents[0].messages[0])
                self.assertEqual(agent.tools, agents[0].tools)
            for public in self.cards.values():
                spec = public["paradigms"]["function_call"]["spec"]
                self.assertIn("Public output schema:", spec["description"])
                self.assertFalse({"substitutes", "domain", "category"} & public.keys())

    def test_blocked_policy_reads(self):
        with public_scope():
            for name in ("benchmarks/ToolMaze/tools/definitions/alternatives.yaml",
                         "benchmarks/ToolMaze/data/perturbed_tasks/c3/test.json",
                         "benchmarks/ToolMaze/tools/plugins/example.py"):
                with self.assertRaises(PermissionError):
                    guard("open", (name, "r", 0))

    def test_four_first_touch_and_isolation(self):
        for task in protocol.TASKS:
            session = self.session(task)
            fresh = self.session(task)
            self.assertEqual(comparable(session.initial), comparable(fresh.initial))
            session.call(task.failed_tool, task.failed_arguments)
            self.assertEqual(session.events[-1]["perturbation"], "perturbed")
            self.assertEqual(session.events[-1]["output"], {"error": task.error})
            self.assertEqual(fresh.events, [])
            self.assertEqual(len(fresh.engine.context.history), 1)

    def test_tokenization_preserves_nested_sdk_key_order(self):
        from io import BytesIO
        from .run_2_009 import count_tokens

        def tokenize(request, timeout):
            payload = json.loads(request.data)
            schema = payload["tools"][0]["function"]["parameters"]["properties"]
            self.assertEqual(list(schema), ["title", "data"])
            self.assertEqual(list(schema["title"]), ["type", "description"])
            return BytesIO(b'{"max_model_len": 32768, "count": 2, "tokens": [1, 2]}')

        tools = [{"type": "function", "function": {"name": "archive", "parameters": {
            "type": "object",
            "properties": {"title": {"type": "string", "description": "Title"}, "data": {}},
        }}}]
        with patch("extensions.route_recovery.run_2_009.urlopen", side_effect=tokenize):
            self.assertEqual(count_tokens([{"role": "user", "content": "Archive data"}], tools), 2)

    def test_synthetic_protocol_and_budget(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from .run_2_009 import RequestLog

        def unexpected(**request):
            self.fail(f"SDK unexpectedly called: {request}")

        with TemporaryDirectory() as directory:
            log = RequestLog(Path(directory), unexpected, 200901, ("hash", 1))
            log.count = protocol.MAX_REQUESTS
            with self.assertRaisesRegex(RuntimeError, "Frozen episode"):
                log(messages=[], tools=[])
            self.assertEqual(log.status, "request_budget")
            log.status = None
            log.count = 0
            with patch("extensions.route_recovery.run_2_009.count_tokens", return_value=protocol.CONTEXT):
                with self.assertRaises(RuntimeError):
                    log(messages=[], tools=[])
            self.assertEqual(log.status, "context_budget")
            log.status = None
            with patch("extensions.route_recovery.run_2_009.count_tokens", side_effect=OSError):
                with self.assertRaises(RuntimeError):
                    log(messages=[], tools=[])
            self.assertEqual(log.status, "service_error")
            self.assertEqual(log.count, 0)

    def test_generic_equivalence_and_observable_bindings(self):
        # Trusted acceptance fixture only. The two paths are never policy inputs.
        task = protocol.TASKS[0]
        observed = {"user_id": task.target, "account_type": "investment",
                    "balance": 700, "currency": "USD"}
        read = {"tool": "get_account_balance", "arguments": {"user_id": task.target},
                "output": observed, "plugins": [], "coerced": False}
        write = {"tool": "create_document_and_alert_from_data", "arguments": {},
                 "output": {"note_id": "N", "notification_id": "M"}, "coerced": False,
                 "plugins": [
                     {"tool": "create_document",
                      "arguments": {"title": task.title, "content": json.dumps(observed)},
                      "output": {"note_id": "N"}},
                     {"tool": "push_alert",
                      "arguments": {"user_id": task.recipient, "message": task.title,
                                    "priority": task.priority, "channel": task.channel},
                      "output": {"notification_id": "M"}},
                 ]}
        episode = {"answer": "I checked the successful receipts: N and M.", "status": "answered",
                   "events": [read, write]}
        positive = grade(task, self.cards, episode)
        self.assertTrue(positive["strict"])
        self.assertTrue(positive["visible_check"])
        self.assertFalse(grade(task, self.cards, episode | {"events": [write]})["business"])
        self.assertFalse(grade(task, self.cards, episode | {"events": [read, write, write]})["business"])
        self.assertFalse(grade(task, self.cards, episode | {"answer": "I verified it."})["strict"])
        modified = deepcopy(episode)
        modified["events"][1]["plugins"][1]["arguments"]["user_id"] = "wrong"
        self.assertFalse(grade(task, self.cards, modified)["business"])
        modified = deepcopy(episode)
        modified["events"][1]["plugins"][0]["arguments"]["content"] = json.dumps(observed | {"balance": 701})
        self.assertFalse(grade(task, self.cards, modified)["business"])

    def test_native_plugin_representation_and_replay(self):
        task = protocol.TASKS[0]
        one = self.session(task)
        two = self.session(task)
        # Test wrapper and native plugin behavior, without running the model or D policy.
        for session in (one, two):
            source = session.call("get_account_balance", task.failed_arguments)
            out = session.call("create_document_and_alert_from_data", task.values | {"data": source})
            self.assertIn("note_id", out)
            self.assertIn("notification_id", out)
            episode = {"answer": f"Checked successful receipts {out['note_id']} and {out['notification_id']}.",
                       "status": "answered", "events": session.events}
            self.assertTrue(grade(task, self.cards, episode)["strict"])
        self.assertEqual(list(map(comparable, one.events)), list(map(comparable, two.events)))
