import unittest
from extensions.route_recovery.parameter_order import goat_question, order_edge, rule_supply


class EdgeTests(unittest.TestCase):
    def test_single_field_combines_with_existing_binding(self):
        needs = {'record_id', 'pending_ref'}
        supplies = rule_supply({'pending_ref'}, 'pending_ref')
        self.assertEqual(order_edge(supplies, 'pending_ref', needs, {'record_id'}), 'enables_target')
        self.assertEqual(order_edge(supplies, 'pending_ref', needs, set()), 'partial_supply')

    def test_echo_and_unknown_alias(self):
        self.assertEqual(order_edge(True, 'id', {'id'}, {'id'}), 'already_available')
        self.assertEqual(order_edge(rule_supply({'ref'}, 'id'), 'id', {'id'}, set()), 'unknown')
        self.assertEqual(order_edge(False, 'id', {'id'}, set()), 'unsupported')

    def test_judgment_names_one_parameter(self):
        self.assertIn("parameter 'pending_ref'", goat_question('source', 'target', 'pending_ref'))
