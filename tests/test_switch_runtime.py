"""Source-bound switch-fragment experiments, not real-game calibration."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from lab.effect_runtime import HOOKS
from lab.prepared_rules import PreparedRules
from lab.server import load_catalog
from lab.switch_runtime import execute_switch_fragment


def member(mid, form=3001):
    return {"member_id": mid, "form_id": form, "hp": 300, "max_hp": 350,
            "energy": 10, "max_energy": 20, "speed": 100, "entered_turn": 1,
            "rooted": False, "charge": None, "skill_slots": [0, 7020360, 0, 0],
            "statuses": {}, "stat_modifiers": {}}


class SwitchRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.prepared = PreparedRules(cls.catalog)

    def setUp(self):
        self.state = {"snapshot_id": self.prepared.snapshot_id, "turn": 4,
                      "teams": {side: {"active_slot": 0,
                                       "members": [member(side+"-active"), member(side+"-bench", 3016)],
                                       "marks": {"positive": None, "negative": None}}
                                for side in ("a", "b")}}
        self.context = {
            "mode": "isolated_voluntary_switch_experiment", "snapshot_id": self.prepared.snapshot_id,
            "catalog_content_hash": self.prepared.catalog_content_hash,
            "excluded_hooks": sorted(HOOKS), "unresolved_dependencies": [],
            "cleanup_policy": "retain_member_fields_experiment",
            "swift_policy": "intrinsic_source_only_experiment",
            "incoming_effective_costs": [None, 0, None, None],
        }

    def actor(self, slot=0, side="a"):
        return self.state["teams"][side]["members"][slot]

    def run_switch(self, side="a", target=1, rules=None, resolver=None):
        return execute_switch_fragment(self.prepared if rules is None else rules, self.state, side, target, self.context,
                                       damage_resolver=resolver)

    def enable_entry_attack(self, side="a", cost=3):
        self.actor(1, side)["skill_slots"] = [0, 0, 7150080, 0]
        self.context["incoming_effective_costs"] = [None, None, cost, None]
        self.context["entry_timing"] = "after_position_change_experiment"
        program = self.prepared.skill_plan(7150080)["program"]
        self.context["entry_skill_context"] = {
            "mode": "isolated_skill_experiment", "snapshot_id": self.prepared.snapshot_id,
            "source_hash": program["source_hash"], "operation_order": "source_text_order_experiment",
            "excluded_hooks": sorted(HOOKS), "unresolved_dependencies": [],
            "damage_policy": "resolver_returns_actual_integer_hp_loss",
        }

    def assert_blocked(self, result):
        self.assertEqual(result["status"], "blocked", result)
        self.assertEqual(result["state"], self.state)
        self.assertEqual(result["events"], [])
        self.assertIsNone(result["final_state_hash"])
        self.assertFalse(result["switch_fragment_executed"])
        self.assertFalse(result["full_switch_executed"])
        self.assertFalse(result["training_eligible"])

    def test_trait_swift_charge_bypass_keeps_real_token_and_pays_execution_cost(self):
        from lab import duration_runtime as duration, action_traits, trait_runtime
        from lab.research_phases import _fragment
        from lab.runtime_programs import reviewed_programs
        from lab.switch_runtime import _typed_actor
        self.state['trait_policy'] = trait_runtime.POLICY
        incoming = self.actor(1)
        incoming.update(form_id=3209, skill_slots=[0, 7100130, 0, 0])
        grant = duration.programs(self.catalog)[7100180]
        typed = _typed_actor(self.prepared._rules, incoming)
        granted = duration.execute_duration_skill(grant, {'self': typed, 'opponent': deepcopy(typed)},
            {**_fragment(grant), **duration.research_context(), 'turn': 4, 'resolved_energy_cost': 2})
        self.assertEqual(granted['status'], 'applied', granted['blockers'])
        incoming['timed_effects'] = granted['state']['self']['timed_effects']
        program = reviewed_programs(self.prepared)[7100130]
        self.context.update(swift_policy=action_traits.SWIFT_POLICY,
            incoming_effective_costs=[None, 3, None, None],
            entry_timing='after_position_change_experiment', entry_skill_context=_fragment(program))
        result = self.run_switch(resolver=lambda *_: 7)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual(result['entry_skill_assumptions']['execution_phase'], 'bypass_charge_pending_execution')
        self.assertEqual(result['state']['teams']['a']['members'][1]['energy'], 7)
        self.assertIsNone(result['state']['teams']['a']['members'][1]['charge'])
        incoming.pop('timed_effects')
        blocked = self.run_switch(resolver=lambda *_: 7)
        self.assertEqual(blocked['status'], 'blocked')
        self.assertEqual(blocked['state'], self.state)

    def test_client_change_gate_bit_layout_and_cooldown_boundaries(self):
        switches = self.prepared._components()[2]
        self.assertTrue(switches.change_pet_banned({"state_bits": [1 << 16]}))
        self.assertFalse(switches.change_pet_banned({"state_bits": [1 << 17]}))
        self.assertFalse(switches.change_pet_banned({"state_bits": []}))

        initial = switches.change_eligibility(current_round=3, exchange_initial_cold=3,
            exchange_cold=0, last_change_round_index=0, can_changepet=1,
            ban_change_pet=False)
        self.assertEqual((initial["status"], initial["remaining_rounds"]), ("blocked", 1))
        repeated = switches.change_eligibility(current_round=7, exchange_initial_cold=0,
            exchange_cold=2, last_change_round_index=5, can_changepet=1,
            ban_change_pet=False)
        self.assertEqual((repeated["status"], repeated["remaining_rounds"]), ("blocked", 1))
        ready = switches.change_eligibility(current_round=8, exchange_initial_cold=0,
            exchange_cold=2, last_change_round_index=5, can_changepet=1,
            ban_change_pet=False)
        self.assertEqual(ready["status"], "allowed")

    def test_client_change_gate_blocks_mode_and_ban_but_missing_cooldowns_stay_unknown(self):
        switches = self.prepared._components()[2]
        disabled = switches.change_eligibility(current_round=2, exchange_initial_cold=0,
            exchange_cold=0, can_changepet=0, ban_change_pet=False)
        self.assertEqual(disabled["reason"], "battle_mode_disallows_switch")
        banned = switches.change_eligibility(current_round=2, exchange_initial_cold=0,
            exchange_cold=0, can_changepet=1, ban_change_pet=True)
        self.assertEqual(banned["reason"], "pet_state_bans_switch")
        unknown = switches.change_eligibility(current_round=2, exchange_initial_cold=None,
            exchange_cold=None, last_change_round_index=None,
            can_changepet=1, ban_change_pet=False)
        self.assertEqual(unknown["status"], "unresolved")
        self.assertEqual(set(unknown["missing_inputs"]), {"exchange_initial_cold"})
        missing_mode_and_pet_state = switches.change_eligibility(current_round=2,
            exchange_initial_cold=0, exchange_cold=0, last_change_round_index=None)
        self.assertEqual(missing_mode_and_pet_state["status"], "unresolved")
        self.assertEqual(set(missing_mode_and_pet_state["missing_inputs"]),
                         {"can_changepet", "ban_change_pet"})
        first_switch = switches.change_eligibility(current_round=2, exchange_initial_cold=0,
            last_change_round_index=None, can_changepet=1, ban_change_pet=False)
        self.assertEqual(first_switch["status"], "allowed")
        unknown_repeat_cooldown = switches.change_eligibility(current_round=2,
            exchange_initial_cold=0, last_change_round_index=1,
            can_changepet=1, ban_change_pet=False)
        self.assertEqual(unknown_repeat_cooldown["status"], "unresolved")
        self.assertEqual(unknown_repeat_cooldown["missing_inputs"], ["exchange_cold"])

    def test_switch_gate_accepts_paired_round_notification_without_guessing_missing_fields(self):
        gate = {"state_info": {"round": self.state["turn"], "last_change_pet_round": 0},
                "exchange_initial_cold": 0, "can_changepet": 1, "ban_change_pet": False}
        self.context["switch_cooldown"] = gate
        result = self.run_switch()
        self.assertEqual(result["status"], "applied", result["blockers"])
        gate["state_info"]["round"] += 1
        self.assert_blocked(self.run_switch())
        gate["state_info"].pop("round")
        self.assertEqual(self.run_switch()["switch_cooldown"]["status"], "unresolved")
        self.context["switch_cooldown"] = None
        self.assert_blocked(self.run_switch())

    def test_switch_gate_does_not_infer_missing_live_runtime_values(self):
        self.context["switch_cooldown"] = {"exchange_initial_cold": 0, "exchange_cold": 0,
            "can_changepet": 1, "ban_change_pet": False}
        blocked = self.run_switch()
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["switch_cooldown"]["status"], "unresolved")
        self.assertEqual(set(blocked["switch_cooldown"]["missing_inputs"]),
                         {"current_round", "last_change_round_index"})
        self.assertEqual(blocked["state"], self.state)

        # A source-observed nil means there has not yet been a switch; it is
        # distinct from an omitted observation in the research state.
        self.context["switch_cooldown"].update(current_round=4, last_change_round_index=None)
        allowed = self.run_switch()
        self.assertEqual(allowed["status"], "applied", allowed["blockers"])
        self.assertEqual(allowed["events"][0]["switch_cooldown"]["status"], "allowed")

    def test_switch_gate_uses_packed_ban_bit_and_rejects_conflicting_override(self):
        self.context["switch_cooldown"] = {"current_round": 4, "can_changepet": 1,
            "exchange_initial_cold": 0, "exchange_cold": 0, "last_change_round_index": None,
            "battle_inside_pet_info": {"state_bits": [1 << 16]}}
        blocked = self.run_switch()
        self.assertEqual(blocked["status"], "blocked")
        self.assertIn("pet_state_bans_switch", blocked["blockers"][0])

        self.context["switch_cooldown"]["ban_change_pet"] = False
        conflict = self.run_switch()
        self.assertEqual(conflict["status"], "blocked")
        self.assertIn("conflicts with packed client state_bits", conflict["blockers"][0])
        self.assertEqual(conflict["state"], self.state)
        self.assertEqual(conflict["events"], [])

    def test_switch_runtime_applies_optional_client_gate_without_defaulting_cooldowns(self):
        self.context["switch_cooldown"] = {"current_round": 4, "can_changepet": 1,
            "exchange_initial_cold": 0, "exchange_cold": 0,
            "last_change_round_index": 0, "ban_change_pet": False}
        result = self.run_switch()
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["events"][0]["switch_cooldown"]["status"], "allowed")

        self.context["switch_cooldown"].update(exchange_cold=None, last_change_round_index=1)
        blocked = self.run_switch()
        self.assertEqual(blocked["status"], "blocked")
        self.assertIn("runtime_switch_cooldown_values_missing", blocked["blockers"][0])
        self.assertEqual(blocked["state"], self.state)

    def test_selected_swift_uses_shared_executor_for_composed_effects(self):
        self.enable_entry_attack(cost=3)
        self.context["entry_skill_context"]["energy_policy"] = "clamp_to_declared_max"
        program = self.prepared._rules.program(7150080)
        # Synthetic composition tests dispatch reuse, not a new BWIKI claim.
        program["operations"].append({"op": "energy.restore", "params": {"target": "self", "amount": 2}})
        with patch.object(self.prepared._rules, "program", return_value=program):
            result = self.run_switch(resolver=lambda *_: 7)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["energy"], 9)
        self.assertEqual([e["op"] for e in result["events"]],
                         ["switch.voluntary", "energy.pay", "damage", "energy.restore"])

    def test_only_active_slot_and_entry_turn_change(self):
        before = deepcopy((self.state, self.context))
        expected = deepcopy(self.state)
        expected["teams"]["a"]["active_slot"] = 1
        expected["teams"]["a"]["members"][1]["entered_turn"] = 4
        result = self.run_switch()
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"], expected)
        self.assertEqual((self.state, self.context), before)
        self.assertEqual(result["events"][0]["departing_member_id"], "a-active")
        self.assertEqual(result["events"][0]["entering_member_id"], "a-bench")
        self.assertEqual(result["entry_swift"]["status"], "none")
        self.assertFalse(result["full_turn_executed"])
        self.assertFalse(result["full_switch_executed"])
        self.assertFalse(result["calibrated"])

    def test_b_side_and_arbitrary_target_preserve_opponent(self):
        self.state["teams"]["b"]["members"].append(member("b-third"))
        result = self.run_switch("b", 2)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["teams"]["b"]["active_slot"], 2)
        self.assertEqual(result["state"]["teams"]["a"], self.state["teams"]["a"])

    def test_marks_statuses_modifiers_custom_fields_are_retained_only_by_explicit_policy(self):
        marks = {"positive": None, "negative": {"id": 1014, "stacks": 2, "source": {"event": ["recorded"]}}}
        self.state["teams"]["a"]["marks"] = deepcopy(marks)
        for slot in (0, 1):
            self.actor(slot)["statuses"] = {"poison": 2, "burn": 3}
            self.actor(slot)["stat_modifiers"] = {"patk": [{"numerator": 1, "denominator": 2}]}
            self.actor(slot)["custom"] = {"nested": [slot]}
        result = self.run_switch()
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["teams"]["a"]["marks"], marks)
        for slot in (0, 1):
            actor = deepcopy(result["state"]["teams"]["a"]["members"][slot])
            actor["entered_turn"] = self.actor(slot)["entered_turn"]
            self.assertEqual(actor, self.actor(slot))
        self.assertEqual(result["events"][0]["inherited_marks"]["term_ids"], [3010])
        result["state"]["teams"]["a"]["marks"]["negative"]["source"]["event"].append("mutated")
        self.assertEqual(self.state["teams"]["a"]["marks"], marks)
        self.assertEqual(result["events"][0]["inherited_marks"]["marks"], marks)

    def test_invalid_side_target_and_current_target_reject(self):
        for side, slot in (("c", 1), (None, 1), (True, 1), ("a", True), ("a", 1.0),
                           ("a", -1), ("a", 2), ("a", 0)):
            with self.subTest(side=side, slot=slot):
                self.assert_blocked(self.run_switch(side, slot))

    def test_exhausted_outgoing_incoming_or_opponent_reject_without_replacement(self):
        for slot, side in ((0, "a"), (1, "a"), (0, "b")):
            with self.subTest(slot=slot, side=side):
                self.actor(slot, side)["hp"] = 0
                self.assert_blocked(self.run_switch())
                self.actor(slot, side)["hp"] = 300

    def test_rooted_outgoing_rejects_but_same_turn_entry_does_not_invent_voluntary_immunity(self):
        self.actor()["rooted"] = True
        self.assert_blocked(self.run_switch())
        self.actor()["rooted"] = False
        self.actor()["entered_turn"] = self.state["turn"]
        self.assertEqual(self.run_switch()["status"], "applied")

    def test_charge_on_outgoing_or_incoming_cannot_be_silently_canceled(self):
        # A malformed/stale record already blocks in joint validation. A valid
        # bound record is also blocked at this fragment's unresolved boundary.
        _, phases, _ = self.prepared._components()
        for slot in (0, 1):
            self.actor(slot)["skill_slots"][1] = 7100150
            self.actor(slot)["charge"] = phases.charge_state(1, 7100150, 3)
            self.assert_blocked(self.run_switch())
            self.actor(slot)["charge"] = None
            self.actor(slot)["skill_slots"][1] = 7020360

    def test_freeze_leech_any_participant_rejects(self):
        for slot, side in ((0, "a"), (1, "a"), (0, "b")):
            for status in ("freeze", "leech"):
                with self.subTest(slot=slot, side=side, status=status):
                    self.actor(slot, side)["statuses"][status] = 1
                    self.assert_blocked(self.run_switch())
                    del self.actor(slot, side)["statuses"][status]

    def test_incoming_and_opponent_resources_statuses_and_types_validate(self):
        for slot, side in ((1, "a"), (0, "b")):
            before = deepcopy(self.actor(slot, side))
            for values in ({"hp": 351}, {"energy": 21}, {"types": ["火系"]},
                           {"statuses": {"unknown": 1}}, {"statuses": {"poison": True}},
                           {"max_hp": 0}, {"stat_modifiers": {"patk": [{"numerator": 1, "denominator": 0}]}}):
                self.actor(slot, side).update(deepcopy(values))
                self.assert_blocked(self.run_switch())
                self.state["teams"][side]["members"][slot] = deepcopy(before)

    def test_structural_unknown_form_duplicate_ids_and_slots_reject(self):
        before = deepcopy(self.state)
        mutations = [lambda: self.actor(1).update(form_id=999999999),
                     lambda: self.actor(1).update(member_id="b-active"),
                     lambda: self.actor(1).update(skill_slots=[7020360, 0, 7020360, 0]),
                     lambda: self.actor(1).update(skill_slots=[7020360]),
                     lambda: self.actor(1).update(entered_turn=5)]
        for mutate in mutations:
            mutate()
            self.assert_blocked(self.run_switch())
            self.state = deepcopy(before)

    def test_context_missing_or_conflicting_policies_never_default(self):
        original = deepcopy(self.context)
        for field, value in (("mode", "battle"), ("snapshot_id", "other"), ("catalog_content_hash", "stale"),
                             ("cleanup_policy", "clear_statuses"), ("swift_policy", "skip_swift"),
                             ("excluded_hooks", []), ("unresolved_dependencies", ["trait"]),
                             ("incoming_effective_costs", None)):
            self.context = {**deepcopy(original), field: value}
            self.assert_blocked(self.run_switch())
        self.context = deepcopy(original)
        del self.context["cleanup_policy"]
        self.assert_blocked(self.run_switch())

    def test_empty_slots_cannot_consume_cost_or_be_reordered(self):
        for costs in ([0, 0, None, None], [None, 0, None], [None, True, None, None], [None, -1, None, None]):
            self.context["incoming_effective_costs"] = costs
            self.assert_blocked(self.run_switch())

    def test_affordable_source_swift_blocks_even_if_caller_claims_false(self):
        self.actor(1)["skill_slots"] = [0, 7150080, 0, 0]
        self.actor(1)["swift_candidates"] = [None, {"skill_id": 7150080, "swift": False, "effective_cost": 999}, None, None]
        self.context["incoming_effective_costs"] = [None, 3, None, None]
        result = self.run_switch()
        self.assert_blocked(result)
        self.assertEqual(result["entry_swift"]["status"], "selected")
        self.assertEqual(result["entry_swift"]["slot"], 1)
        self.assertEqual(result["entry_swift"]["skill_id"], 7150080)

    def test_known_unaffordable_swift_allows_position_only_and_does_not_pay(self):
        self.actor(1)["skill_slots"] = [0, 7150080, 0, 0]
        self.context["incoming_effective_costs"] = [None, 11, None, None]
        result = self.run_switch()
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["energy"], 10)
        self.assertEqual(result["entry_swift"]["status"], "none")

    def test_swift_unknown_cost_and_history_condition_block_before_position_change(self):
        for skill, cost in ((7150080, None), (7150400, 2)):
            self.actor(1)["skill_slots"] = [0, skill, 0, 0]
            self.context["incoming_effective_costs"] = [None, cost, None, None]
            result = self.run_switch()
            self.assert_blocked(result)
            self.assertEqual(result["entry_swift"]["status"], "unresolved")

    def test_original_skill_order_is_preserved_for_swift_selection(self):
        self.actor(1)["skill_slots"] = [0, 7150080, 7150300, 0]
        self.context["incoming_effective_costs"] = [None, 11, 2, None]
        result = self.run_switch()
        self.assert_blocked(result)
        self.assertEqual(result["entry_swift"]["slot"], 2)
        self.context["incoming_effective_costs"][1] = 3
        result = self.run_switch()
        self.assert_blocked(result)
        self.assertEqual(result["entry_swift"]["slot"], 1)

    def test_unknown_earlier_swift_does_not_fall_through_to_later_affordable_one(self):
        self.actor(1)["skill_slots"] = [7150400, 0, 7150080, 0]
        self.context["incoming_effective_costs"] = [2, None, 3, None]
        result = self.run_switch()
        self.assert_blocked(result)
        self.assertEqual(result["entry_swift"]["status"], "unresolved")
        self.assertEqual(result["entry_swift"]["blocking_slot"], 0)

    def test_marks_malformed_or_unknown_reject(self):
        self.state["teams"]["a"]["marks"] = {"positive": None, "negative": {"id": 999999, "stacks": 1}}
        self.assert_blocked(self.run_switch())

    def test_source_change_even_with_context_rebound_blocks(self):
        catalog = deepcopy(self.catalog)
        catalog["provenance"]["Terms"]["content_sha256"] = "changed"
        rules = PreparedRules(catalog)
        self.context["catalog_content_hash"] = rules.catalog_content_hash
        self.assert_blocked(self.run_switch(rules=rules))

    def test_late_selector_failure_is_atomic(self):
        _, _, switches = self.prepared._components()
        with patch.object(switches, "swift_first_slot", side_effect=ValueError("synthetic late rejection")):
            self.assert_blocked(self.run_switch())

    def test_fresh_prepared_parity_and_repeated_experiments_do_not_accumulate(self):
        expected = self.run_switch()
        self.assertEqual(expected["status"], "applied", expected["blockers"])
        self.assertEqual(expected, self.run_switch(rules=self.catalog))
        self.assertEqual(expected, self.run_switch())
        expected["events"][0]["swift_candidates"][1]["source_metadata"].clear()
        self.assertTrue(self.run_switch()["events"][0]["swift_candidates"][1]["source_metadata"])

    def test_entry_attack_uses_new_member_paid_energy_and_original_slot_on_both_sides(self):
        for side, other in (("a", "b"), ("b", "a")):
            self.setUp()
            self.enable_entry_attack(side)
            before = deepcopy((self.state, self.context))
            calls = []
            def resolver(params, state, context):
                calls.append((state["self"]["member_id"], state["self"]["entered_turn"],
                              state["self"]["energy"], state["opponent"]["member_id"],
                              context["actor_side"], context["skill_slot"]))
                return 17
            result = self.run_switch(side=side, resolver=resolver)
            self.assertEqual(result["status"], "applied", result["blockers"])
            self.assertEqual(calls, [(side+"-bench", 4, 7, other+"-active", side, 2)])
            self.assertEqual(result["state"]["teams"][side]["active_slot"], 1)
            self.assertEqual(result["state"]["teams"][other]["members"][0]["hp"], 283)
            self.assertEqual(result["state"]["teams"][side]["members"][0], before[0]["teams"][side]["members"][0])
            self.assertEqual(result["state"]["turn"], 4)
            self.assertEqual(result["events"][0]["op"], "switch.voluntary")
            damage = next(event for event in result["events"] if event["op"] == "damage")
            self.assertEqual(damage["origin"], "entry_swift")
            self.assertEqual((damage["actor_member_id"], damage["target_member_id"], damage["skill_slot"]),
                             (side+"-bench", other+"-active", 2))
            self.assertEqual(damage["skill_id"], 7150080)
            self.assertTrue(damage["program_hash"])
            self.assertTrue(result["entry_skill_executed"])
            self.assertTrue(result["entry_swift"]["skill_executed"])
            self.assertFalse(result["full_switch_executed"])
            self.assertEqual((self.state, self.context), before)

    def test_entry_exact_energy_and_zero_cost_are_paid_once(self):
        for cost in (0, 10):
            self.enable_entry_attack(cost=cost)
            calls = []
            result = self.run_switch(resolver=lambda *args: calls.append(args) or 1)
            self.assertEqual(result["status"], "applied", result["blockers"])
            self.assertEqual(len(calls), 1)
            self.assertEqual(result["state"]["teams"]["a"]["members"][1]["energy"], 10-cost)

    def test_entry_requires_context_timing_source_and_matching_explicit_cost(self):
        self.enable_entry_attack()
        original = deepcopy(self.context)
        mutations = [lambda c: c.pop("entry_skill_context"), lambda c: c.pop("entry_timing"),
                     lambda c: c.update(entry_timing="before_switch"),
                     lambda c: c["entry_skill_context"].update(source_hash="other"),
                     lambda c: c["entry_skill_context"].update(snapshot_id="other"),
                     lambda c: c["entry_skill_context"].update(resolved_energy_cost=True),
                     lambda c: c["entry_skill_context"].update(resolved_energy_cost=0),
                     lambda c: c["entry_skill_context"].update(damage_policy="guess")]
        for mutate in mutations:
            self.context = deepcopy(original)
            mutate(self.context)
            calls = []
            self.assert_blocked(self.run_switch(resolver=lambda *args: calls.append(args) or 1))
            self.assertEqual(calls, [])
        self.context = original
        self.assert_blocked(self.run_switch())  # No implicit damage formula.

    def test_first_selected_unsupported_swift_cannot_skip_to_supported_wing_attack(self):
        self.enable_entry_attack()
        self.actor(1)["skill_slots"] = [7150300, 0, 7150080, 0]
        self.context["incoming_effective_costs"] = [2, None, 3, None]
        calls = []
        result = self.run_switch(resolver=lambda *args: calls.append(args) or 1)
        self.assert_blocked(result)
        self.assertEqual(result["entry_swift"]["skill_id"], 7150300)
        self.assertEqual(calls, [])

    def test_entry_callback_writes_cannot_mutate_state_context_or_event_source(self):
        self.enable_entry_attack()
        before = deepcopy((self.state, self.context))
        def mutate(params, state, context):
            params["power"] = 999
            state["self"]["energy"] = 999
            state["opponent"]["member_id"] = "forged"
            context.clear()
            return 7
        result = self.run_switch(resolver=mutate)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["energy"], 7)
        self.assertEqual(result["state"]["teams"]["b"]["members"][0]["hp"], 293)
        damage = next(e for e in result["events"] if e["op"] == "damage")
        self.assertEqual(damage["target_member_id"], "b-active")
        self.assertEqual((self.state, self.context), before)

    def test_entry_callback_failures_restore_position_cost_entry_clock_and_all_events(self):
        self.enable_entry_attack()
        for bad in (True, -1, 301, 1.0, None):
            with self.subTest(value=bad):
                self.assert_blocked(self.run_switch(resolver=lambda *args, bad=bad: bad))
        def broken(*args):
            raise RuntimeError("synthetic entry resolver failure")
        self.assert_blocked(self.run_switch(resolver=broken))

    def test_entry_exhaustion_does_not_publish_switch_or_payments(self):
        self.enable_entry_attack()
        self.assert_blocked(self.run_switch(resolver=lambda *args: 300))

    def test_entry_metadata_is_required_even_for_a_compiled_damage_program(self):
        self.enable_entry_attack()
        rules = self.prepared._components()[0]
        original = rules.program(7150080)
        for field, value in (("intrinsic_swift", False), ("entry_trigger", {"kind": "other", "term_id": 1005}),
                             ("dependency_ids", []), ("game_id", 7020360)):
            changed = {**deepcopy(original), field: value}
            calls = []
            with patch.object(rules, "program", return_value=changed):
                self.assert_blocked(self.run_switch(resolver=lambda *args: calls.append(args) or 1))
            self.assertEqual(calls, [])

    def test_entry_prepared_fresh_and_repeat_runs_are_equal_without_state_accumulation(self):
        self.enable_entry_attack()
        resolver = lambda *args: 7
        result = self.run_switch(resolver=resolver)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result, self.run_switch(resolver=resolver))
        self.assertEqual(result, self.run_switch(rules=self.catalog, resolver=resolver))

    def test_unaffordable_swift_does_not_run_supplied_entry_context_or_callback(self):
        self.enable_entry_attack(cost=11)
        calls = []
        result = self.run_switch(resolver=lambda *args: calls.append(args) or 1)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertFalse(result["entry_skill_executed"])
        self.assertEqual(calls, [])
        self.assertEqual(len(result["events"]), 1)


if __name__ == "__main__":
    unittest.main()
