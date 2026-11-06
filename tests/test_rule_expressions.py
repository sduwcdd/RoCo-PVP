from fractions import Fraction
import unittest

from lab.rule_expressions import evaluate_expression, evaluate_condition, validate_expression, validate_condition


class RuleExpressionTests(unittest.TestCase):
    def test_exact_arithmetic_and_current_resource_reads(self):
        expr = {"op": "mul", "args": [{"read": {"target": "opponent", "field": "energy"}},
                                      {"const": {"numerator": 1, "denominator": 3}}]}
        self.assertEqual(evaluate_expression(expr, {"opponent": {"energy": 2}}), Fraction(2, 3))
        self.assertEqual(evaluate_expression(expr, {"opponent": {"energy": 6}}), 2)

    def test_generic_conditions_are_distinct_from_response_and_order_events(self):
        condition = {"all": [{"compare": "lte", "left": {"read": {"target": "self", "field": "energy"}},
                              "right": {"const": 2}}, {"not": {"compare": "eq", "left": {"const": 1}, "right": {"const": 0}}}]}
        self.assertTrue(evaluate_condition(condition, {"self": {"energy": 2}}))
        self.assertFalse(evaluate_condition(condition, {"self": {"energy": 3}}))
        for bad in ({"response": "attack"}, {"priority": 1}, {"first": True}, {"entry": "swift"}):
            with self.assertRaises(ValueError): validate_condition(bad)

    def test_invalid_numbers_reads_and_code_are_not_coerced(self):
        bad = [{"const": True}, {"const": 0.5}, {"const": {"numerator": 1, "denominator": 0}},
               {"const": 2**257}, {"eval": "1+1"}, {"read": {"target": "self", "field": "speed"}},
               {"op": "divide", "args": [{"const": 1}, {"const": 2}]}]
        for item in bad:
            with self.subTest(item=item), self.assertRaises(ValueError): validate_expression(item)
        with self.assertRaises(ValueError): evaluate_expression({"read": {"target": "self", "field": "energy"}}, {})

    def test_depth_numeric_and_empty_condition_limits(self):
        node = {"const": 1}
        for _ in range(18): node = {"op": "add", "args": [node, {"const": 1}]}
        with self.assertRaises(ValueError): validate_expression(node)
        with self.assertRaises(ValueError): evaluate_expression({"op": "mul", "args": [{"const": 2**200}, {"const": 2**200}]}, {})
        for node in ({"all": []}, {"any": []}):
            with self.assertRaises(ValueError): validate_condition(node)

    def test_invalid_hidden_condition_branch_does_not_short_circuit(self):
        condition = {"any": [{"compare": "eq", "left": {"const": 1}, "right": {"const": 1}},
                             {"compare": "eq", "left": {"read": {"target": "self", "field": "energy"}}, "right": {"const": 0}}]}
        with self.assertRaises(ValueError): evaluate_condition(condition, {})
