"""Composition probes are explicitly synthetic; not observed game configs."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from lab.effect_runtime import HOOKS, execute_effects
from lab.rule_config import load_bundle, rule_to_program, execution_program
from lab.server import load_catalog
from lab.skill_execution import execute_rule, execute_skill
from lab.prepared_rules import PreparedRules


class SkillExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.rules = load_bundle(cls.catalog)["records"]["skills"]

    def state(self):
        return {side: {"hp": 100, "max_hp": 200, "energy": 5, "max_energy": 20,
                       "types": ["普通系"], "statuses": {}, "stat_modifiers": {}} for side in ("self", "opponent")}

    def context(self, rule):
        p = rule["program"]
        return {"mode": "isolated_skill_experiment", "snapshot_id": p["snapshot_id"],
                "source_hash": p["source_hash"], "operation_order": "source_text_order_experiment",
                "unresolved_dependencies": [], "excluded_hooks": sorted(HOOKS), "resolved_energy_cost": 2,
                "energy_policy": "clamp_to_declared_max", "stat_policy": "record_signed_percentage_terms",
                "energy_reduction_policy": "clamp_to_zero_experiment",
                "component_evaluation_policy": "after_payment_before_each_component_experiment",
                "damage_policy": "resolver_returns_actual_integer_hp_loss"}

    def test_all_migrated_configs_keep_legacy_state_and_effect_events(self):
        counts = {"applied": 0, "blocked": 0}
        for key, rule in self.rules.items():
            with self.subTest(skill=key):
                program, state, context = rule_to_program(rule), self.state(), self.context(rule)
                old = execute_effects(program, state, context, damage_resolver=lambda *_: 1)
                new = execute_rule(rule, state, context, damage_resolver=lambda *_: 1)
                counts[new["status"]] += 1
                self.assertEqual(new["status"], old["status"])
                self.assertEqual(new["state"], old["state"])
                self.assertEqual(new["events"], old["events"])
                self.assertFalse(new["training_eligible"])
        self.assertEqual(sum(counts.values()), 579)
        self.assertGreater(counts["applied"], 130)

    def test_runtime_lookup_does_not_call_natural_language_parser(self):
        with patch("lab.skill_programs.compile_catalog", side_effect=AssertionError("NLP ran at runtime")):
            prepared = PreparedRules(self.catalog)
            rule = self.rules["7170280"]
            r = prepared.execute_skill(7170280, self.state(), self.context(rule))
            self.assertEqual(r["status"], "applied", r["blockers"])

    def test_data_predicate_and_amount_expression_read_paid_current_state(self):
        rule = deepcopy(self.rules["7170280"])
        # Synthetic configurable condition, no new Python skill-ID branch.
        rule["components"][1]["when"] = {"compare": "eq", "left": {"read": {"target": "self", "field": "energy"}}, "right": {"const": 3}}
        rule["components"][1]["params"]["amount"] = {"expr": {"op": "min", "args": [
            {"const": 4}, {"read": {"target": "opponent", "field": "energy"}}]}}
        state, context = self.state(), self.context(rule)
        original = deepcopy((rule, state, context))
        r = execute_rule(rule, state, context)
        self.assertEqual(r["status"], "applied", r["blockers"])
        self.assertEqual(r["state"]["opponent"]["energy"], 1)
        self.assertEqual(r["state"]["self"]["energy"], 3)
        self.assertEqual(r["component_observations"][1]["resolved_params"]["amount"], 4)
        self.assertEqual((rule, state, context), original)
        context["resolved_energy_cost"] = 1
        r = execute_rule(rule, state, context)
        self.assertEqual(r["state"]["opponent"]["energy"], 5)
        self.assertFalse(r["component_observations"][1]["selected"])

    def test_fractional_amount_and_later_missing_policy_roll_back_prior_effects(self):
        rule = deepcopy(self.rules["7170280"])
        rule["components"][1]["params"]["amount"] = {"expr": {"const": {"numerator": 1, "denominator": 2}}}
        state, context = self.state(), self.context(rule)
        r = execute_rule(rule, state, context)
        self.assertEqual(r["status"], "blocked")
        self.assertIn("rounding", str(r["blockers"]))
        self.assertEqual(r["state"], state)
        self.assertEqual(r["events"], [])
        rule["components"][1]["params"]["amount"] = {"expr": {"const": 3}}
        del context["energy_reduction_policy"]
        r = execute_rule(rule, state, context)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(r["state"], state)
        self.assertEqual(r["events"], [])

    def test_missing_dynamic_timing_and_source_conflict_block(self):
        rule = deepcopy(self.rules["7170280"])
        rule["components"][1]["params"]["amount"] = {"expr": {"const": 3}}
        c = self.context(rule)
        del c["component_evaluation_policy"]
        self.assertEqual(execute_rule(rule, self.state(), c)["status"], "blocked")
        c = self.context(rule); c["source_hash"] = "conflict"
        self.assertEqual(execute_rule(rule, self.state(), c)["status"], "blocked")
        c = self.context(rule); del c["resolved_energy_cost"]
        self.assertEqual(execute_rule(rule, self.state(), c)["status"], "blocked")

    def test_shared_dispatch_is_deterministic_and_carries_entry_origin(self):
        rule = self.rules["7150080"]
        state, context = self.state(), self.context(rule)
        context["entry_origin"] = "voluntary_switch"
        a = execute_rule(rule, state, context, damage_resolver=lambda *_: 7)
        b = execute_skill(rule_to_program(rule), state, context, damage_resolver=lambda *_: 7)
        self.assertEqual(a, b)
        self.assertEqual(a["state"]["self"]["energy"], 3)
        self.assertEqual(a["state"]["opponent"]["hp"], 93)
        self.assertTrue(a["dispatch_trace_is_diagnostic"])
        self.assertIn("skill:7150080", str(a["dispatch_trace"]))

    def test_conditional_damage_composes_with_predicate_without_double_payment(self):
        rule = deepcopy(self.rules["7020440"])
        rule["components"][0]["when"] = {"compare": "eq", "left": {"const": 1}, "right": {"const": 1}}
        state, context = self.state(), self.context(rule)
        context.update(resolved_energy_cost=5, conditional_policy={"timing": "after_payment_before_damage_experiment"})
        observed = []
        def resolver(params, current, supplied):
            observed.append((params["power"], current["self"]["energy"], supplied["component_sequence_paid_cost"]))
            return 7
        r = execute_rule(rule, state, context, damage_resolver=resolver)
        self.assertEqual(r["status"], "applied", r["blockers"])
        self.assertEqual(observed, [(215, 0, 5)])
        self.assertEqual([e["op"] for e in r["events"]], ["energy.pay", "damage"])
        self.assertEqual(r["events"][0]["amount"], 5)

    def test_callback_mutating_original_program_cannot_add_unvalidated_effect(self):
        rule = self.rules["7150080"]
        program, state, context = rule_to_program(rule), self.state(), self.context(rule)
        context.pop("energy_policy")
        def resolver(*args):
            program["operations"].append({"op": "energy.restore", "params": {"target": "self", "amount": 10}})
            context["resolved_energy_cost"] = 0
            return 7
        r = execute_skill(program, state, context, damage_resolver=resolver)
        self.assertEqual(r["status"], "applied", r["blockers"])
        self.assertEqual(r["state"]["self"]["energy"], 3)
        self.assertEqual([e["op"] for e in r["events"]], ["energy.pay", "damage"])

    def test_later_predicate_reads_prior_reduction_in_same_configuration(self):
        rule = deepcopy(self.rules["7170280"])
        rule["components"] = list(reversed(rule["components"]))
        for i, component in enumerate(rule["components"]): component["id"] = f"effect:{i}"
        rule["components"][1]["when"] = {"compare": "lte", "left": {"read": {"target": "opponent", "field": "energy"}}, "right": {"const": 2}}
        r = execute_rule(rule, self.state(), self.context(rule))
        self.assertEqual(r["status"], "applied", r["blockers"])
        self.assertTrue(r["component_observations"][1]["selected"])
        self.assertEqual(r["state"]["opponent"]["stat_modifiers"]["mdef"], [{"numerator": -50, "denominator": 100}])

    def test_native_data_condition_survives_joint_action_pipeline(self):
        from tests.test_lab_server import LocalServiceTests
        from lab.action_runtime import execute_joint_actions
        from lab.skill_execution import preflight_skill
        rule = deepcopy(self.rules["7170280"])
        rule["components"][1]["when"] = {"compare": "eq", "left": {"const": 1}, "right": {"const": 0}}
        program = execution_program(rule)
        self.assertIn("native_rule", program)
        with self.assertRaises(ValueError): rule_to_program(rule)
        payload = LocalServiceTests().joint_request(7170280)
        for f in payload["context"]["fragments"].values():
            f.update(stat_policy="record_signed_percentage_terms", energy_reduction_policy="clamp_to_zero_experiment",
                     component_evaluation_policy="after_payment_before_each_component_experiment")
        prepared = PreparedRules(self.catalog)
        with patch.object(prepared._rules, "program", return_value=program):
            r = execute_joint_actions(prepared, **payload)
        self.assertEqual(r["status"], "applied", r["blockers"])
        for side in ("a", "b"):
            actor = r["state"]["teams"][side]["members"][0]
            self.assertEqual(actor["energy"], 8)  # Payment only; false condition cannot be dropped.
            self.assertEqual(actor["stat_modifiers"]["mdef"], [{"numerator": -50, "denominator": 100}])

    def test_native_envelope_must_match_inner_source_identity_and_operations(self):
        from lab.skill_execution import preflight_skill
        rule = deepcopy(self.rules["7170280"])
        rule["components"][1]["when"] = {"compare": "eq", "left": {"const": 1}, "right": {"const": 0}}
        for key, value in (("game_id", 999999), ("source_hash", "forged"), ("operations", [{"op": "damage"}]), ("unknown", True)):
            program = execution_program(rule)
            program[key] = value
            state, context = self.state(), self.context(rule)
            with self.assertRaisesRegex(ValueError, "envelope"):
                preflight_skill(program, state, context)
            calls = []
            r = execute_skill(program, state, context, damage_resolver=lambda *_: calls.append(True) or 7)
            self.assertEqual(r["status"], "blocked")
            self.assertEqual(r["state"], state)
            self.assertEqual(r["events"], [])
            self.assertEqual(calls, [])

    def test_native_defense_cannot_erase_response_order_even_under_false_condition(self):
        from tests.test_lab_server import LocalServiceTests
        from lab.action_runtime import execute_joint_actions
        rule = deepcopy(self.rules["7020780"])
        rule["components"][0]["when"] = {"compare": "eq", "left": {"const": 1}, "right": {"const": 0}}
        payload = LocalServiceTests().joint_request(7020780)
        for fragment in payload["context"]["fragments"].values():
            fragment["component_evaluation_policy"] = "after_payment_before_each_component_experiment"
        prepared = PreparedRules(self.catalog)
        with patch.object(prepared._rules, "program", return_value=execution_program(rule)):
            plan = prepared.plan(payload["state"], payload["actions"])
            result = execute_joint_actions(prepared, **payload)
        self.assertEqual(plan["status"], "blocked")
        self.assertIn("response ordering", str(plan["blockers"]))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["state"], payload["state"])
        self.assertEqual(result["events"], [])
