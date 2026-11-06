"""Paired fragment regression tests; synthetic inputs, not game calibration."""
from copy import deepcopy
import unittest

from lab.action_runtime import execute_joint_actions
from lab.effect_runtime import HOOKS
from lab.prepared_rules import PreparedRules
from lab.server import load_catalog
from lab.skill_programs import compile_catalog


def member(mid, form=3001):
    return {"member_id": mid, "form_id": form, "hp": 300, "max_hp": 350,
            "energy": 10, "max_energy": 20, "speed": 100, "entered_turn": 1,
            "rooted": False, "charge": None, "skill_slots": [0, 7020360, 0, 7020780],
            "statuses": {}, "stat_modifiers": {}}


class JointActionRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.programs = compile_catalog(cls.catalog)["skills"]

    def setUp(self):
        self.state = {"snapshot_id": self.catalog["snapshot_id"], "turn": 2,
                      "teams": {s: {"active_slot": 1, "members": [member(s+"-reserve", 3016), member(s+"-active")],
                                    "marks": {"positive": None, "negative": None}} for s in ("a", "b")}}
        self.actions = {s: {"kind": "skill", "slot": 1, "effective_cost": 2,
                            "effective_priority": int(s == "a")} for s in ("a", "b")}
        self.context = {"mode": "isolated_joint_action_experiment", "excluded_hooks": sorted(HOOKS),
                        "fragments": {s: self.fragment(7020360) for s in ("a", "b")}}

    def fragment(self, mid):
        p = self.programs[str(mid)]
        return {"mode": "isolated_skill_experiment", "snapshot_id": p["snapshot_id"],
                "source_hash": p["source_hash"], "operation_order": "source_text_order_experiment",
                "unresolved_dependencies": [], "excluded_hooks": sorted(HOOKS),
                "energy_policy": "clamp_to_declared_max", "stat_policy": "record_signed_percentage_terms",
                "damage_policy": "resolver_returns_actual_integer_hp_loss"}

    def run_pair(self, resolver=None):
        return execute_joint_actions(self.catalog, self.state, self.actions, self.context,
                                     damage_resolver=resolver)

    def assert_rollback(self, result):
        self.assertEqual(result["status"], "blocked", result)
        self.assertEqual(result["state"], self.state)
        self.assertEqual(result["events"], [])
        self.assertIsNone(result["order"])
        self.assertFalse(result["training_eligible"])

    def use_fixed_hits(self):
        for side, skill_id in (("a", 7020480), ("b", 7020920)):
            self.state["teams"][side]["members"][1]["skill_slots"][1] = skill_id
            self.context["fragments"][side] = self.fragment(skill_id)
            self.context["fragments"][side]["multi_hit_policy"] = {
                "power_basis": "source_power_per_hit", "timing": "sequential_experiment"}

    def use_energy_condition(self, side, skill_id):
        self.state["teams"][side]["members"][1]["skill_slots"][1] = skill_id
        self.context["fragments"][side] = self.fragment(skill_id)
        self.context["fragments"][side]["conditional_policy"] = {
            "timing": "after_payment_before_damage_experiment"}

    def use_energy_reduction(self):
        self.state["teams"]["a"]["members"][1]["skill_slots"][1] = 7170280
        self.context["fragments"]["a"] = self.fragment(7170280)
        self.context["fragments"]["a"]["energy_reduction_policy"] = "clamp_to_zero_experiment"

    def test_first_energy_reduction_makes_second_cost_unaffordable_and_rolls_back_pair(self):
        self.use_energy_reduction()
        self.state["teams"]["b"]["members"][1]["energy"] = 4
        before = deepcopy((self.state, self.actions, self.context))
        calls = []
        result = self.run_pair(lambda *args: calls.append(args) or 7)
        self.assert_rollback(result)
        self.assertEqual(calls, [])
        self.assertTrue(any("insufficient energy" in text.lower() for text in result["blockers"]))
        # A's payment, B's magic-defense term, and energy reduction must ALL
        # disappear when B cannot pay its already submitted cost of two.
        self.assertEqual((self.state, self.actions, self.context), before)
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["energy"], 10)
        self.assertEqual(result["state"]["teams"]["b"]["members"][1]["stat_modifiers"], {})

    def test_second_action_pays_from_reduced_energy_and_does_not_transfer_it_to_first(self):
        self.use_energy_reduction()
        self.state["teams"]["b"]["members"][1]["energy"] = 5
        seen = []
        def resolver(params, state, context):
            seen.append((context["actor_side"], state["self"]["energy"],
                         state["opponent"]["energy"], deepcopy(state["self"]["stat_modifiers"])))
            return 7
        result = self.run_pair(resolver)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(seen, [("b", 0, 8, {"mdef": [{"numerator": -50, "denominator": 100}]})])
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["energy"], 8)
        # B loses three, pays two, then its own 抓挠 independently restores one.
        self.assertEqual(result["state"]["teams"]["b"]["members"][1]["energy"], 1)
        reduced = next(event for event in result["events"] if event["op"] == "energy.reduce")
        self.assertEqual((reduced["requested_amount"], reduced["actual_amount"]), (3, 3))
        self.assertEqual((reduced["actor_member_id"], reduced["target_member_id"], reduced["skill_slot"]),
                         ("a-active", "b-active", 1))
        self.assertEqual(reduced["source_hash"], self.programs["7170280"]["source_hash"])
        self.assertFalse(result["full_turn_executed"])
        self.assertFalse(result["training_eligible"])

    def test_energy_reduction_clamp_preserves_requested_vs_actual_with_zero_cost_response(self):
        self.use_energy_reduction()
        self.actions["b"]["effective_cost"] = 0
        for available in (0, 2):
            self.state["teams"]["b"]["members"][1]["energy"] = available
            result = self.run_pair(lambda *args: 7)
            self.assertEqual(result["status"], "applied", result["blockers"])
            reduced = next(event for event in result["events"] if event["op"] == "energy.reduce")
            self.assertEqual((reduced["requested_amount"], reduced["actual_amount"]), (3, available))
            self.assertEqual(result["state"]["teams"]["a"]["members"][1]["energy"], 8)
            self.assertEqual(result["state"]["teams"]["b"]["members"][1]["energy"], 1)

    def test_missing_energy_reduction_policy_blocks_both_before_damage_callbacks(self):
        self.use_energy_reduction()
        del self.context["fragments"]["a"]["energy_reduction_policy"]
        calls = []
        self.assert_rollback(self.run_pair(lambda *args: calls.append(args) or 7))
        self.assertEqual(calls, [])

    def test_energy_reduction_prepared_and_direct_match_on_commit_and_rollback(self):
        self.use_energy_reduction()
        prepared = PreparedRules(self.catalog)
        for available, expected in ((5, "applied"), (4, "blocked")):
            self.state["teams"]["b"]["members"][1]["energy"] = available
            resolver = lambda *args: 7
            direct = self.run_pair(resolver)
            reused = execute_joint_actions(prepared, self.state, self.actions, self.context,
                                            damage_resolver=resolver)
            self.assertEqual(direct["status"], expected, direct["blockers"])
            self.assertEqual(direct, reused)
            self.assertEqual(reused, prepared.execute(self.state, self.actions, self.context,
                                                      damage_resolver=resolver))

    def test_second_energy_predicate_reads_first_action_payment_and_refund(self):
        self.use_energy_condition("b", 7020530)
        self.state["teams"]["a"]["members"][1]["energy"] = 3
        for cost, observed, factor, final_hp in ((2, 2, 5, 290), (1, 3, 1, 298)):
            self.actions["a"]["effective_cost"] = cost
            seen = []
            def resolver(params, state, context):
                if context["actor_side"] == "a":
                    return 7
                seen.append((params["condition_observed"], params["power"], params["damage_multiplier"]))
                return 2 * params["damage_multiplier"]["numerator"]
            result = self.run_pair(resolver)
            self.assertEqual(result["status"], "applied", result["blockers"])
            self.assertEqual(seen, [(observed, 65, {"numerator": factor, "denominator": 1})])
            self.assertEqual(result["state"]["teams"]["a"]["members"][1]["hp"], final_hp)
            self.assertEqual(result["state"]["teams"]["b"]["members"][1]["hp"], 293)
            event = next(e for e in result["events"] if e.get("source_op") == "damage.conditional")
            self.assertEqual((event["actor_member_id"], event["target_member_id"], event["skill_slot"]), ("b-active", "a-active", 1))
            self.assertEqual(self.state["teams"]["a"]["members"][1]["energy"], 3)

    def test_previous_energy_restore_prevents_stale_zero_energy_condition(self):
        self.use_energy_condition("b", 7170110)
        self.state["teams"]["a"]["members"][1]["skill_slots"][1] = 7030220
        self.state["teams"]["a"]["members"][1]["energy"] = 0
        self.actions["a"]["effective_cost"] = 0
        self.context["fragments"]["a"] = self.fragment(7030220)
        seen = []
        def resolver(params, state, context):
            seen.append((params["condition_observed"], params["condition_matched"], params["damage_multiplier"]["numerator"]))
            return 5
        result = self.run_pair(resolver)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(seen, [(10, False, 1)])

    def test_source_power_addition_is_not_reapplied_as_damage_multiplier(self):
        self.use_energy_condition("a", 7020440)
        self.state["teams"]["a"]["members"][1]["energy"] = 5
        self.actions["a"]["effective_cost"] = 5
        seen = []
        def resolver(params, state, context):
            if context["actor_side"] == "b":
                return 3
            seen.append((params["base_power"], params["power"], params["condition_observed"], params["damage_multiplier"]["numerator"]))
            return params["power"]  # Explicit synthetic resolver, not game damage.
        result = self.run_pair(resolver)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(seen, [(95, 215, 0, 1)])
        self.assertEqual(result["state"]["teams"]["b"]["members"][1]["hp"], 85)
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["energy"], 0)

    def test_missing_second_condition_timing_blocks_before_first_damage(self):
        self.use_energy_condition("b", 7020530)
        del self.context["fragments"]["b"]["conditional_policy"]
        calls = []
        self.assert_rollback(self.run_pair(lambda *args: calls.append(True)))
        self.assertEqual(calls, [])

    def test_two_sequences_keep_each_hit_identity_and_second_action_current_state(self):
        self.use_fixed_hits()
        observed = []
        def resolver(params, state, context):
            observed.append((context["actor_side"], params["hit_index"], state["self"]["hp"], state["opponent"]["hp"]))
            return params["hit_index"] + (1 if context["actor_side"] == "a" else 4)
        result = self.run_pair(resolver)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(observed, [("a", 0, 300, 300), ("a", 1, 300, 299), ("a", 2, 300, 297),
                                    ("b", 0, 294, 300), ("b", 1, 294, 296)])
        hits = [e for e in result["events"] if e["op"] == "damage"]
        self.assertEqual([(e["actor_member_id"], e["target_member_id"], e["hit_index"], e["skill_slot"]) for e in hits],
                         [("a-active", "b-active", i, 1) for i in range(3)] + [("b-active", "a-active", i, 1) for i in range(2)])
        self.assertEqual(len([e for e in result["events"] if e["op"] == "energy.pay"]), 2)
        self.assertEqual([result["state"]["teams"][s]["members"][1]["energy"] for s in ("a", "b")], [8, 8])
        self.assertEqual([result["state"]["teams"][s]["members"][1]["hp"] for s in ("a", "b")], [291, 294])

    def test_sequence_exhaustion_never_executes_another_hit_or_opponent_action(self):
        for damages in ([200, 100], [100, 100, 100]):
            self.use_fixed_hits()
            called = []
            def resolver(params, state, context):
                called.append((context["actor_side"], params["hit_index"]))
                return damages[params["hit_index"]]
            result = self.run_pair(resolver)
            self.assert_rollback(result)
            self.assertEqual(called, [("a", i) for i in range(len(damages))])
            self.assertTrue(any("Exhaustion" in s for s in result["blockers"]))

    def test_second_sequence_failure_or_missing_policy_rolls_back_whole_pair(self):
        self.use_fixed_hits()
        called = []
        def resolver(params, state, context):
            called.append((context["actor_side"], params["hit_index"]))
            if context["actor_side"] == "b" and params["hit_index"] == 1:
                raise RuntimeError("last hit failed")
            return 5
        self.assert_rollback(self.run_pair(resolver))
        self.assertEqual(called, [("a", 0), ("a", 1), ("a", 2), ("b", 0), ("b", 1)])
        del self.context["fragments"]["b"]["multi_hit_policy"]
        called.clear()
        self.assert_rollback(self.run_pair(resolver))
        self.assertEqual(called, [])

    def test_second_heal_uses_hp_after_first_attack_and_fraction_failure_rolls_back_both(self):
        self.state["teams"]["b"]["members"][1]["skill_slots"][1] = 7020640
        self.context["fragments"]["b"] = self.fragment(7020640)
        self.context["fragments"]["b"]["hp_policy"] = {
            "percentage_basis": "current_hp", "rounding": "exact", "cap": "clamp_to_declared_max"}
        result = self.run_pair(lambda *args: 10)
        self.assertEqual(result["status"], "applied", result["blockers"])
        heal = next(e for e in result["events"] if e["op"] == "hp.restore")
        self.assertEqual((heal["before"], heal["basis_value"], heal["requested"], heal["restored"]), (290, 290, 87, 60))
        self.assertEqual((heal["actor_member_id"], heal["target_member_id"]), ("b-active", "b-active"))
        self.assertEqual(result["state"]["teams"]["b"]["members"][1]["hp"], 350)
        self.assertEqual(self.state["teams"]["b"]["members"][1]["hp"], 300)
        # 291 * 30% is fractional; the missing rounding decision must undo A too.
        self.assert_rollback(self.run_pair(lambda *args: 9))

    def test_both_attacks_pay_cost_and_second_observes_updated_front_state(self):
        observed = []
        def damage(params, state, context):
            observed.append((context["actor_side"], state["self"]["hp"], state["opponent"]["energy"]))
            return 7 if context["actor_side"] == "a" else 11
        result = self.run_pair(damage)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(observed, [("a", 300, 10), ("b", 293, 9)])
        self.assertEqual(result["order"], ["a", "b"])
        self.assertEqual([result["state"]["teams"][s]["members"][1]["hp"] for s in ("a", "b")], [289, 293])
        self.assertEqual([result["state"]["teams"][s]["members"][1]["energy"] for s in ("a", "b")], [9, 9])
        self.assertEqual(result["state"]["turn"], 2)
        self.assertFalse(result["full_turn_executed"])
        self.assertFalse(result["battle_executable"])
        self.assertFalse(result["calibrated"])
        self.assertFalse(result["training_eligible"])

    def test_reversed_order_maps_targets_and_payments_to_actual_members(self):
        self.actions["b"]["effective_priority"] = 2
        result = self.run_pair(lambda *args: 7)
        self.assertEqual(result["order"], ["b", "a"])
        self.assertEqual([(e["actor_member_id"], e["target_member_id"], e["skill_slot"])
                          for e in result["events"] if e["op"] == "damage"],
                         [("b-active", "a-active", 1), ("a-active", "b-active", 1)])
        self.assertEqual([(e["target_side"], e["amount"]) for e in result["events"] if e["op"] == "energy.pay"],
                         [("b", 2), ("a", 2)])
        self.assertTrue(all(e["source_hash"] == self.programs["7020360"]["source_hash"] for e in result["events"]))

    def test_sparse_slots_reserves_and_metadata_are_preserved(self):
        self.state["teams"]["a"]["members"][1]["provenance"] = {"raw": [80, 80, 80]}
        result = self.run_pair(lambda *args: 7)
        for side in ("a", "b"):
            team = result["state"]["teams"][side]
            self.assertEqual(team["active_slot"], 1)
            self.assertEqual(team["members"][0], self.state["teams"][side]["members"][0])
            self.assertEqual(team["members"][1]["skill_slots"], [0, 7020360, 0, 7020780])
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["provenance"], {"raw": [80, 80, 80]})

    def test_all_inputs_callback_arguments_and_outputs_are_isolated(self):
        before = deepcopy((self.state, self.actions, self.context))
        def damage(params, state, context):
            state["self"]["skill_slots"][1] = 9
            context["excluded_hooks"].clear()
            params["power"] = 999
            return 3
        result = self.run_pair(damage)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual((self.state, self.actions, self.context), before)
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["skill_slots"][1], 7020360)
        result["assumptions"]["fragments"]["a"]["excluded_hooks"].clear()
        result["state"]["teams"]["a"]["members"][1]["skill_slots"].clear()
        self.assertEqual((self.state, self.actions, self.context), before)

    def test_second_resolver_failure_rolls_back_first_damage_refund_and_both_costs(self):
        seen = []
        def damage(params, state, context):
            seen.append(context["actor_side"])
            if context["actor_side"] == "b":
                raise RuntimeError("second resolver fails")
            return 7
        result = self.run_pair(damage)
        self.assertEqual(seen, ["a", "b"])
        self.assert_rollback(result)
        self.assertIn("second resolver fails", result["blockers"][0])

    def test_unknown_order_never_uses_speed_guess_or_random_choice(self):
        self.actions["a"]["effective_priority"] = 0
        self.state["teams"]["a"]["members"][1]["speed"] = 10000
        calls = []
        self.assert_rollback(self.run_pair(lambda *a: calls.append(1)))
        self.assertEqual(calls, [])

    def test_invalid_second_fragment_rejected_before_first_callback(self):
        calls = []
        del self.context["fragments"]["b"]["energy_policy"]
        self.assert_rollback(self.run_pair(lambda *a: calls.append(1)))
        self.assertEqual(calls, [])

    def test_missing_declared_maximum_or_damage_resolver_never_infers_one(self):
        self.assert_rollback(self.run_pair())
        del self.state["teams"]["b"]["members"][1]["max_hp"]
        self.assert_rollback(self.run_pair(lambda *a: 7))

    def test_conflicting_cost_including_boolean_is_not_silently_overridden(self):
        for cost in (3, True, 2.0):
            with self.subTest(cost=cost):
                self.context["fragments"]["b"]["resolved_energy_cost"] = cost
                self.assert_rollback(self.run_pair(lambda *a: 7))

    def test_form_types_are_source_derived_and_conflict_is_rejected(self):
        result = self.run_pair(lambda *a: 7)
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["types"], ["草系"])
        self.state["teams"]["a"]["members"][1]["types"] = ["火系"]
        self.assert_rollback(self.run_pair(lambda *a: 7))

    def test_defense_switch_and_charge_are_not_misexecuted_as_plain_attacks(self):
        original_state, original_actions, original_context = deepcopy((self.state, self.actions, self.context))
        for kind in ("defense", "switch", "charge"):
            with self.subTest(kind=kind):
                self.state, self.actions, self.context = deepcopy((original_state, original_actions, original_context))
                if kind == "defense":
                    self.actions["a"]["slot"] = 3
                    self.context["fragments"]["a"] = self.fragment(7020780)
                elif kind == "switch":
                    self.actions["a"] = {"kind": "switch", "target_slot": 0}
                else:
                    self.state["teams"]["a"]["members"][1]["skill_slots"][1] = 7100150
                self.assert_rollback(self.run_pair(lambda *a: 7))

    def test_exhaustion_on_either_action_blocks_entire_pair(self):
        for lethal_side in ("a", "b"):
            with self.subTest(side=lethal_side):
                def damage(params, state, context):
                    return state["opponent"]["hp"] if context["actor_side"] == lethal_side else 7
                result = self.run_pair(damage)
                self.assert_rollback(result)
                self.assertIn("Exhaustion", result["blockers"][0])

    def test_source_change_unknown_hooks_or_unacknowledged_mode_blocks(self):
        original = deepcopy(self.context)
        for mutation in ("source", "hooks", "mode"):
            self.context = deepcopy(original)
            if mutation == "source":
                self.context["fragments"]["b"]["source_hash"] = "unverified"
            elif mutation == "hooks":
                self.context["excluded_hooks"].pop()
            else:
                self.context["mode"] = "full_battle"
            self.assert_rollback(self.run_pair(lambda *a: 7))

    def test_invalid_second_action_never_partially_pays_first(self):
        self.actions["b"]["slot"] = 0
        self.assert_rollback(self.run_pair(lambda *a: 7))

    def test_two_energy_skills_execute_without_any_damage_formula(self):
        for side in ("a", "b"):
            self.state["teams"][side]["members"][1]["skill_slots"][1] = 7030220
            self.context["fragments"][side] = self.fragment(7030220)
        result = self.run_pair()
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual([result["state"]["teams"][s]["members"][1]["energy"] for s in ("a", "b")], [18, 18])
        self.assertEqual([event["op"] for event in result["events"]],
                         ["energy.pay", "energy.restore", "energy.pay", "energy.restore"])

    def test_second_damage_resolver_receives_first_stat_effect_as_separate_terms(self):
        self.state["teams"]["a"]["members"][1]["skill_slots"][1] = 7020630
        self.context["fragments"]["a"] = self.fragment(7020630)
        observed = []
        def damage(params, state, context):
            observed.append(deepcopy(state["opponent"]["stat_modifiers"]))
            return 5
        result = self.run_pair(damage)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(observed, [{"matk": [{"numerator": 70, "denominator": 100}]}])

    def test_existing_freeze_cannot_act_based_only_on_positive_hp(self):
        frozen = self.state["teams"]["b"]["members"][1]
        frozen.update(hp=170, max_hp=350, statuses={"freeze": 10})
        calls = []
        def damage(*args):
            calls.append(1)
            return 10
        result = self.run_pair(damage)
        self.assert_rollback(result)
        self.assertIn("Existing freeze", result["blockers"][0])
        self.assertEqual(calls, [])

    def test_damage_must_not_cross_unresolved_freeze_threshold_and_then_execute_second(self):
        frozen = self.state["teams"]["b"]["members"][1]
        frozen.update(hp=180, max_hp=350, statuses={"freeze": 10})
        # These values straddle 50% of max HP. No threshold formula is assumed
        # by the runtime: all nonzero freeze must await its bound resolver.
        calls = []
        def damage(params, state, context):
            calls.append(context["actor_side"])
            return 10
        result = self.run_pair(damage)
        self.assert_rollback(result)
        self.assertEqual(calls, [])

    def test_explicit_zero_freeze_does_not_block_supported_pair(self):
        self.state["teams"]["b"]["members"][1]["statuses"]["freeze"] = 0
        result = self.run_pair(lambda *args: 10)
        self.assertEqual(result["status"], "applied", result["blockers"])

    def test_existing_leech_is_preserved_as_unresolved_without_fabricated_transfer(self):
        self.state["teams"]["b"]["members"][1]["statuses"]["leech"] = 3
        result = self.run_pair(lambda *args: 10)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["teams"]["b"]["members"][1]["statuses"]["leech"], 3)
        self.assertEqual(result["state"]["teams"]["b"]["members"][1]["hp"], 290)
        self.assertTrue(any(x["side"] == "b" and "leech" in x["reason"] for x in result["unresolved"]))


if __name__ == "__main__":
    unittest.main()
