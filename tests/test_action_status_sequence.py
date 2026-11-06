"""Synthetic phase composition; not current-version battle calibration."""
from copy import deepcopy
import unittest

from lab.action_runtime import execute_action_status_sequence
from lab.effect_runtime import HOOKS
from lab.prepared_rules import PreparedRules
from lab.server import load_catalog, import_request
from tests.test_action_runtime import member


class ActionStatusSequenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.rules = PreparedRules(cls.catalog)

    def setUp(self):
        self.state = {"snapshot_id": self.rules.snapshot_id, "turn": 2,
                      "teams": {s: {"active_slot": 0, "members": [member(s)],
                                    "marks": {"positive": None, "negative": None}} for s in ("a", "b")}}
        self.actions = {s: {"kind": "skill", "slot": 1, "effective_cost": 2,
                            "effective_priority": int(s == "a")} for s in ("a", "b")}
        self.context = {"mode": "isolated_action_status_sequence",
                        "phase_order": "actions_then_status_experiment",
                        "actions_context": {"mode": "isolated_joint_action_experiment",
                                            "excluded_hooks": sorted(HOOKS), "fragments": {}},
                        "status_context": {"mode": "isolated_status_phase_experiment",
                                           "snapshot_id": self.rules.snapshot_id,
                                           "catalog_content_hash": self.rules.catalog_content_hash,
                                           "operation_order": "damage_then_decay_experiment",
                                           "excluded_hooks": sorted(HOOKS), "unresolved_dependencies": [],
                                           "schedule": [],
                                           "status_policy": {"immunity": "reject_existing_immune_status",
                                                             "burn_decay_rounding": "exact"}}}
        self.use_skill("a", 7040260)  # Source burn 10; no damage formula needed for assignment.
        self.use_skill("b", 7030220)  # Source energy restore.
        self.context["status_context"]["schedule"] = [{"side": "b", "status": "burn"}]

    def use_skill(self, side, skill):
        self.state["teams"][side]["members"][0]["skill_slots"] = [0, skill, 0, 0]
        p = self.rules.skill_plan(skill)["program"]
        self.context["actions_context"]["fragments"][side] = {
            "mode": "isolated_skill_experiment", "snapshot_id": self.rules.snapshot_id,
            "source_hash": p["source_hash"], "operation_order": "source_text_order_experiment",
            "excluded_hooks": sorted(HOOKS), "unresolved_dependencies": [],
            "energy_policy": "clamp_to_declared_max",
            "damage_policy": "resolver_returns_actual_integer_hp_loss",
            "status_policies": {"burn": {"stacking": "add_to_declared_count", "cap": None,
                                         "immunity_type": "火系"}}}

    def run_sequence(self, **kwargs):
        return self.rules.execute_action_status_sequence(self.state, self.actions, self.context, **kwargs)

    def assert_rollback(self, result):
        self.assertEqual(result["status"], "blocked", result["blockers"])
        self.assertEqual(result["state"], self.state)
        self.assertEqual(result["events"], [])
        self.assertIsNone(result["final_state_hash"])
        self.assertFalse(result["training_eligible"])

    def test_newly_assigned_burn_ticks_after_both_actions_and_preserves_turn(self):
        before = deepcopy((self.state, self.actions, self.context))
        calls = []
        def resolver(descriptor, state, context):
            actor = state["teams"]["b"]["members"][0]
            calls.append((actor["statuses"]["burn"], actor["energy"], actor["hp"]))
            return 17  # Explicit arbitrary actual HP loss, not inferred 2% formula.
        result = self.run_sequence(status_damage_resolver=resolver)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(calls, [(10, 18, 300)])
        self.assertEqual(result["state"]["teams"]["b"]["members"][0]["hp"], 283)
        self.assertEqual(result["state"]["teams"]["b"]["members"][0]["statuses"]["burn"], 5)
        self.assertEqual(result["state"]["turn"], 2)
        phases = [e["sequence_phase"] for e in result["events"]]
        self.assertEqual(phases, sorted(phases))
        self.assertFalse(result["full_turn_executed"])
        self.assertFalse(result["end_of_turn_executed"])
        self.assertEqual((self.state, self.actions, self.context), before)

    def test_missing_post_action_status_rolls_back_both_skills_and_costs(self):
        self.context["status_context"]["schedule"] = []
        calls = []
        result = self.run_sequence(status_damage_resolver=lambda *args: calls.append(args) or 1)
        self.assert_rollback(result)
        self.assertEqual(calls, [])

    def test_status_failure_discards_successful_skill_damage_and_payments(self):
        self.use_skill("a", 7020360)
        self.state["teams"]["b"]["members"][0]["statuses"]["burn"] = 2
        skill_calls = []
        def broken(*args):
            raise ValueError("synthetic status resolver failure")
        result = self.run_sequence(damage_resolver=lambda *args: skill_calls.append(args) or 9,
                                   status_damage_resolver=broken)
        self.assertTrue(skill_calls)
        self.assert_rollback(result)

    def test_status_faint_discards_stack_assignment_and_energy_restore(self):
        self.assert_rollback(self.run_sequence(status_damage_resolver=lambda *args: 300))

    def test_no_phase_order_is_inferred_and_mutated_context_does_not_change_inputs(self):
        self.context["phase_order"] = "status_then_actions"
        self.assert_rollback(self.run_sequence())
        self.context["phase_order"] = "actions_then_status_experiment"
        before = deepcopy((self.state, self.context))
        def mutate(descriptor, state, context):
            state["teams"]["b"]["members"][0]["hp"] = 1
            context.clear()
            descriptor.clear()
            return 7
        result = self.run_sequence(status_damage_resolver=mutate)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["teams"]["b"]["members"][0]["hp"], 293)
        self.assertEqual((self.state, self.context), before)

    def test_fresh_and_prepared_results_match_and_repeated_runs_do_not_accumulate(self):
        callback = lambda *args: 7
        expected = self.run_sequence(status_damage_resolver=callback)
        fresh = execute_action_status_sequence(self.catalog, self.state, self.actions, self.context,
                                               status_damage_resolver=callback)
        self.assertEqual(expected, fresh)
        self.assertEqual(expected, self.run_sequence(status_damage_resolver=callback))

    def test_http_does_not_accept_supplied_status_damage_or_partial_result(self):
        result = import_request("/api/rules/execute-action-status-sequence",
                                {"state": self.state, "actions": self.actions, "context": self.context,
                                 "status_damage": 7, "predicted_damage": 7})
        self.assert_rollback(result)
        self.assertTrue(any("resolver" in x for x in result["blockers"]))

    def test_http_empty_status_fragment_does_not_advance_turn_or_train(self):
        self.context["status_context"]["schedule"] = []
        result = import_request("/api/rules/execute-statuses",
                                {"state": self.state, "context": self.context["status_context"]})
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["turn"], 2)
        self.assertEqual(result["events"], [])
        self.assertFalse(result["training_eligible"])


if __name__ == "__main__":
    unittest.main()
