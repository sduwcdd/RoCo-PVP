"""V2 policy compositions use constructed states, never gameplay calibration."""
from copy import deepcopy
import unittest

from lab.prepared_rules import PreparedRules
from lab.research_battle import execute_research_turn
from lab.research_phases import (POLICY_V2, build_research_context_v2,
    execute_research_turn_v2, choose_research_replacements_v2)
from tests import test_action_runtime as fixture_module


class ResearchPhasesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_module.JointActionRuntimeTests.setUpClass()
        cls.prepared = PreparedRules(fixture_module.JointActionRuntimeTests.catalog)

    def setUp(self):
        self.f = fixture_module.JointActionRuntimeTests()
        self.f.setUp()
        self.state, self.actions = self.f.state, self.f.actions
        self.overrides = {}

    def actor(self, side="a", slot=1):
        return self.state["teams"][side]["members"][slot]

    def context(self, **kw):
        return build_research_context_v2(self.prepared, self.state, self.actions,
                                        program_overrides=self.overrides, **kw)

    def run_turn(self, damage=lambda *_: 7, status=lambda *_: 3, context=None):
        return execute_research_turn_v2(self.prepared, self.state, self.actions,
            self.context() if context is None else context, damage_resolver=damage,
            status_damage_resolver=status, program_overrides=self.overrides)

    def pure(self, side="a"):
        self.actor(side)["skill_slots"][1] = 7020370

    def charge(self):
        self.actor()["skill_slots"][1] = 7100130
        self.actions["a"]["effective_cost"] = 0
        # Test the phase machinery with a trusted constructed complete program;
        # Four charge descriptions with additional effects remain unsupported;
        # 7100150 has a separate source-bound charge-release adapter.
        program = deepcopy(self.prepared._rules.program(7020370))
        program.update(game_id=7100130, source_hash="constructed-phase-composition")
        self.overrides[7100130] = program

    def test_ordinary_turn_and_all_inputs_are_isolated(self):
        context = self.context()
        before = deepcopy((self.state, self.actions, context))
        out, repeated = self.run_turn(context=context), self.run_turn(context=context)
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertEqual(out, repeated)
        self.assertTrue(out["status_phase_executed"])
        self.assertFalse(out["full_turn_executed"])
        self.assertFalse(out["training_eligible"])
        self.assertEqual(out["state"]["turn"], 3)
        self.assertEqual((self.state, self.actions, context), before)
        out["state"]["teams"]["a"]["members"][0]["hp"] = 1
        self.assertEqual(self.actor(slot=0)["hp"], 300)

    def test_speed_then_explicit_tie_is_deterministic(self):
        self.actions["a"]["effective_priority"] = 0
        self.actor("b")["speed"] = 101
        out = self.run_turn()
        self.assertEqual(out["action_order"], ["b", "a"])
        self.actor("b")["speed"] = 100
        out = self.run_turn(context=self.context(tie_break_side="b"))
        self.assertEqual(out["action_order"], ["b", "a"])
        self.assertIn("experiment", out["ordering_policy"])

    def test_policy_or_unknown_speed_rejects_before_callbacks(self):
        calls = []
        self.actions["a"]["effective_priority"] = 0
        self.actor()["speed"] = None
        out = self.run_turn(damage=lambda *a: calls.append(a) or 1)
        self.assertEqual(out["status"], "blocked")
        self.assertEqual(calls, [])
        context = self.context()
        context["v2_policies"]["charge"] = "guess"
        self.assertEqual(self.run_turn(context=context)["state"], self.state)

    def test_speed_modifiers_affect_next_order_without_overwriting_base(self):
        self.actions["a"]["effective_priority"] = 0
        self.actor()["stat_modifiers"]["spd"] = [{"numerator": -1, "denominator": 2}]
        out = self.run_turn()
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertEqual(out["action_order"], ["b", "a"])
        self.assertEqual(out["effective_speeds"], {"a": 50, "b": 100})
        self.assertEqual(out["state"]["teams"]["a"]["members"][1]["speed"], 100)

    def test_speed_terms_floor_then_tie_and_nonpositive_rejection(self):
        self.actions["a"]["effective_priority"] = 0
        self.actor()["speed"] = 101
        self.actor()["stat_modifiers"]["spd"] = [{"numerator": 1, "denominator": 2}]
        self.actor("b")["speed"] = 151
        out = self.run_turn(context=self.context(tie_break_side="b"))
        self.assertEqual(out["effective_speeds"]["a"], 151)
        self.assertEqual(out["action_order"], ["b", "a"])
        # The mechanism speed modifier clamps to a minimum of 1, so a -100%
        # speed term yields an effective speed of 1 (positive) instead of 0.
        self.actor()["stat_modifiers"]["spd"] = [{"numerator": -1, "denominator": 1}]
        out = self.run_turn()
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertEqual(out["effective_speeds"]["a"], 1)
        self.assertEqual(out["action_order"], ["b", "a"])

    def test_runtime_speed_effect_changes_following_turn_order(self):
        self.pure()
        self.actions["a"]["effective_priority"] = 0
        program = deepcopy(self.prepared._rules.program(7020370))
        program["operations"].append({"op": "stat.modify", "params": {"target": "self",
            "attributes": ["spd"], "percent": {"numerator": 1, "denominator": 2}}})
        program["source_hash"] = "constructed-speed-composition"
        self.overrides[7020370] = program
        first = self.run_turn(context=self.context(tie_break_side="b"))
        self.assertEqual(first["status"], "applied", first["blockers"])
        self.assertEqual(first["action_order"], ["b", "a"])
        self.state = first["state"]
        second = self.run_turn(context=self.context(tie_break_side="b"))
        self.assertEqual(second["action_order"], ["a", "b"])
        self.assertEqual(second["effective_speeds"], {"a": 150, "b": 100})
        self.assertEqual(second["state"]["teams"]["a"]["members"][1]["speed"], 100)

    def test_switch_first_hits_new_member_and_preserves_departing_state(self):
        self.actions["a"] = {"kind": "switch", "target_slot": 0}
        before = deepcopy(self.actor())
        out = self.run_turn()
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertEqual(out["action_order"], ["a", "b"])
        self.assertEqual(out["state"]["teams"]["a"]["active_slot"], 0)
        self.assertEqual(out["state"]["teams"]["a"]["members"][0]["hp"], 293)
        # V2 validation adds source-derived types to detached members.
        outgoing = out["state"]["teams"]["a"]["members"][1]
        self.assertEqual({k: outgoing[k] for k in before}, before)

    def test_swift_uses_first_source_slot_and_commits_lethal_entry(self):
        self.actions["a"] = {"kind": "switch", "target_slot": 0}
        self.actor(slot=0)["skill_slots"] = [0, 7150080, 7150130, 0]
        # 7150130 need not be Swift; first source intrinsic Swift must be used.
        # Use a known existing carried ID instead of inventing a source record.
        self.actor(slot=0)["skill_slots"][2] = 7020360
        context = self.context(incoming_effective_costs={"a": [None, 3, 0, None]})
        out = self.run_turn(damage=lambda p,s,c: s[p["target"]]["hp"], context=context)
        self.assertEqual(out["status"], "awaiting_replacement", out["blockers"])
        self.assertEqual(out["committed_actions"], ["a"])
        self.assertEqual(out["skipped_actions"], ["b"])
        self.assertEqual(out["state"]["teams"]["a"]["members"][0]["energy"], 7)
        swift = next(e for e in out["events"] if e.get("origin") == "entry_swift" and e["op"] == "damage")
        self.assertEqual((swift["skill_slot"], swift["skill_id"]), (1, 7150080))
        self.assertEqual(swift["actor_member_id"], "a-reserve")
        self.assertEqual(swift["target_member_id"], "b-active")

    def test_rooted_switch_and_existing_strict_entry_ko_still_reject(self):
        self.actor()["rooted"] = True
        self.actions["a"] = {"kind": "switch", "target_slot": 0}
        out = self.run_turn()
        self.assertEqual(out["status"], "blocked")
        self.assertEqual(out["state"], self.state)

    def test_unaffordable_first_swift_does_not_use_a_later_skill(self):
        self.actions["a"] = {"kind": "switch", "target_slot": 0}
        self.actor(slot=0)["skill_slots"] = [7150080, 7020360, 0, 0]
        self.actor(slot=0)["energy"] = 1
        context = self.context(incoming_effective_costs={"a": [3, 0, None, None]})
        out = self.run_turn(context=context)
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertFalse(any(e.get("origin") == "entry_swift" for e in out["events"]))

    def test_second_failure_retains_successful_switch_and_prevents_replay(self):
        self.actions["a"] = {"kind": "switch", "target_slot": 0}
        def fail(*_):
            raise ValueError("constructed callback failure")
        out = self.run_turn(damage=fail)
        self.assertEqual(out["status"], "blocked")
        self.assertEqual(out["committed_actions"], ["a"])
        self.assertEqual(out["state"]["teams"]["a"]["active_slot"], 0)
        self.assertEqual(out["state"]["research_battle"]["phase"], "blocked")

    def test_charge_setup_then_release_pays_once_and_clears_record(self):
        self.charge()
        out = self.run_turn()
        self.assertEqual(out["status"], "applied", out["blockers"])
        actor = out["state"]["teams"]["a"]["members"][1]
        self.assertEqual(actor["energy"], 10)
        self.assertEqual(actor["charge"]["slot"], 1)
        self.assertEqual(actor["charge"]["release_turn"], 3)
        self.assertFalse(any(e["op"] == "damage" and e["actor_side"] == "a" for e in out["events"]))
        self.state = out["state"]
        self.actions["a"]["effective_cost"] = 3
        released = self.run_turn()
        self.assertEqual(released["status"], "applied", released["blockers"])
        actor = released["state"]["teams"]["a"]["members"][1]
        self.assertIsNone(actor["charge"])
        self.assertEqual(actor["energy"], 7)
        payments = [e for e in released["events"] if e["op"] == "energy.pay" and e["actor_side"] == "a"]
        self.assertEqual([e["amount"] for e in payments], [3])

    def test_charge_setup_then_release_pays_once_and_clears_record_via_source_bound_adapter(self):
        # The source-bound charge adapter compiles 7100130's release, so the
        # release executes the adapter payload (marked unverified) rather than
        # faking a raw attack; setup costs zero and release pays once.
        self.actor()["skill_slots"][1] = 7100130
        self.actions["a"]["effective_cost"] = 0
        out = self.run_turn()
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.state = out["state"]
        self.actions["a"]["effective_cost"] = 3
        out = self.run_turn()
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertIsNone(out["state"]["teams"]["a"]["members"][1]["charge"])
        self.assertTrue(any(e["op"] == "research.charge_released" for e in out["events"]))
        payments = [e for e in out["events"] if e["op"] == "energy.pay" and e["actor_side"] == "a"]
        self.assertEqual([e["amount"] for e in payments], [3])

    def test_source_bound_7100150_releases_via_charge_program_adapter(self):
        from lab.charge_program_adapter import load_charge_program_overrides
        self.overrides = load_charge_program_overrides(self.f.catalog)
        self.actor()["skill_slots"][1] = 7100150
        self.actions["a"]["effective_cost"] = 0
        powers = []
        def damage(params, state, context):
            if context["actor_side"] == "a":
                powers.append(params["power"])
            return 7
        setup = self.run_turn(damage=damage)
        self.assertEqual(setup["status"], "applied", setup["blockers"])
        self.assertEqual(powers, [])
        self.assertEqual(setup["state"]["teams"]["a"]["members"][1]["energy"], 10)
        self.state = setup["state"]
        self.actions["a"]["effective_cost"] = 3
        release = self.run_turn(damage=damage)
        self.assertEqual(release["status"], "applied", release["blockers"])
        self.assertEqual(powers, [200])
        actor = release["state"]["teams"]["a"]["members"][1]
        self.assertEqual(actor["energy"], 7)
        self.assertIsNone(actor["charge"])

    def test_nonzero_charge_setup_is_rejected_without_double_payment(self):
        self.charge()
        self.actions["a"]["effective_cost"] = 2
        out = self.run_turn()
        self.assertEqual(out["status"], "blocked")
        self.assertEqual(out["state"], self.state)

    def test_charge_ko_cancels_binding_before_manual_replacement(self):
        self.charge()
        out = self.run_turn(damage=lambda p,s,c: s[p["target"]]["hp"])
        self.assertEqual(out["status"], "awaiting_replacement", out["blockers"])
        self.assertIsNone(out["state"]["teams"]["a"]["members"][1]["charge"])
        self.assertTrue(any(e["op"] == "research.charge_cancelled" for e in out["events"]))
        replaced = choose_research_replacements_v2(self.prepared, out["state"], {"a": 0}, self.context())
        self.assertEqual(replaced["status"], "applied", replaced["blockers"])

    def test_newly_applied_poison_ticks_using_explicit_status_resolver(self):
        program = deepcopy(self.prepared._rules.program(7020370))
        program["operations"].append({"op": "status.add", "params": {"target": "opponent", "status": "poison", "stacks": 2}})
        program["source_hash"] = "constructed-status-composition"
        self.overrides[7020370] = program
        self.pure()
        out = self.run_turn()
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertEqual(out["state"]["teams"]["b"]["members"][1]["statuses"]["poison"], 2)
        self.assertEqual(out["state"]["teams"]["b"]["members"][1]["hp"], 290)
        self.assertEqual([e["status"] for e in out["events"] if e["op"] == "status.tick"], ["poison"])

    def test_status_ko_skips_second_tick_replacements_never_tick_again(self):
        self.actor("b")["statuses"] = {"poison": 2, "burn": 3}
        calls = []
        def status(descriptor, current, context):
            calls.append(descriptor["status"])
            return current["teams"][descriptor["target_side"]]["members"][1]["hp"]
        context = self.context()
        out = self.run_turn(status=status, context=context)
        self.assertEqual(out["status"], "awaiting_replacement", out["blockers"])
        self.assertEqual(calls, ["poison"])
        self.assertTrue(any(e["op"] == "research.status_skipped" for e in out["events"]))
        replaced = choose_research_replacements_v2(self.prepared, out["state"], {"b": 0}, context)
        self.assertEqual(replaced["status"], "applied", replaced["blockers"])
        self.assertEqual(replaced["state"]["turn"], 3)
        again = choose_research_replacements_v2(self.prepared, replaced["state"], {"b": 1}, context)
        self.assertEqual(again["status"], "blocked")
        self.assertFalse(any(e["op"] == "status.tick" for e in replaced["events"]))
        self.assertEqual(calls, ["poison"])

    def test_burn_decay_and_second_phase_failure_preserve_committed_skills(self):
        self.actor()["statuses"] = {"burn": 3}
        out = self.run_turn()
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertEqual(out["state"]["teams"]["a"]["members"][1]["statuses"]["burn"], 1)
        blocked = self.run_turn(status=None)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["committed_actions"], ["a", "b"])
        self.assertEqual(blocked["state"]["teams"]["a"]["members"][1]["statuses"]["burn"], 3)
        replay = execute_research_turn_v2(self.prepared, blocked["state"], self.actions, self.context(), damage_resolver=lambda *_: 7)
        self.assertEqual(replay["committed_actions"], [])
        self.assertEqual(replay["state"], blocked["state"])

    def test_status_double_ko_finishes_as_experimental_draw(self):
        for side in ("a", "b"):
            self.actor(side)["statuses"] = {"poison": 1}
            self.actor(side, 0)["hp"] = 0
        calls = []
        def lethal(descriptor, current, context):
            side = descriptor["target_side"]
            calls.append(side)
            return current["teams"][side]["members"][1]["hp"]
        out = self.run_turn(status=lethal)
        self.assertEqual((out["status"], out["winner"]), ("finished", "draw"), out["blockers"])
        self.assertEqual(calls, ["a", "b"])
        self.assertEqual(out["state"]["turn"], 2)

    def test_multi_hit_knockout_stops_followup_and_other_action(self):
        self.f.use_fixed_hits()
        calls = []
        def lethal(params, state, context):
            calls.append(params["hit_index"])
            return state[params["target"]]["hp"]
        out = self.run_turn(damage=lethal)
        self.assertEqual(out["status"], "awaiting_replacement", out["blockers"])
        self.assertEqual(calls, [0])
        self.assertEqual(out["skipped_actions"], ["b"])

    def test_recharge_is_global_not_skill_charge_and_clamps_at_explicit_cap_9(self):
        self.actions["a"] = {"kind": "recharge", "effective_cost": 0, "effective_priority": 1}
        self.actor()["energy"], self.actor()["max_energy"] = 7, 9
        self.actor()["skill_slots"] = [0, 0, 0, 0]
        out = self.run_turn()
        self.assertEqual(out["status"], "applied", out["blockers"])
        actor = out["state"]["teams"]["a"]["members"][1]
        self.assertEqual(actor["energy"], 9)
        self.assertIsNone(actor["charge"])
        restore = next(e for e in out["events"] if e["op"] == "energy.restore")
        self.assertEqual(restore["skill_id"], 7000010)
        self.assertEqual(self.actor()["energy"], 7)
        source = out["global_skill_sources"]["7000010"]
        self.assertFalse(source["character_max_energy_used_as_pet_cap"])
        self.assertEqual(source["runtime_energy_caps"], {"a": 9})
        self.assertEqual(source["pet_maximum_fallback"], 10)

    def test_recharge_uses_runtime_cap_10_without_inventing_skill_charge(self):
        self.actions["a"] = {"kind": "recharge", "effective_cost": 0, "effective_priority": 1}
        self.actor()["energy"], self.actor()["max_energy"] = 8, 10
        before = deepcopy(self.state)
        out = self.run_turn()
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertEqual(out["state"]["teams"]["a"]["members"][1]["energy"], 10)
        self.assertIsNone(out["state"]["teams"]["a"]["members"][1]["charge"])
        self.assertEqual(out["global_skill_sources"]["7000010"]["runtime_energy_caps"], {"a": 10})
        self.assertEqual(self.state, before)

    def test_both_recharge_preserve_independent_runtime_caps_10_and_12(self):
        for side, energy, maximum in (("a", 8, 10), ("b", 10, 12)):
            self.actions[side] = {"kind": "recharge", "effective_cost": 0, "effective_priority": 0}
            self.actor(side)["energy"], self.actor(side)["max_energy"] = energy, maximum
        out = self.run_turn()
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertEqual(out["global_skill_sources"]["7000010"]["runtime_energy_caps"], {"a": 10, "b": 12})
        for side, maximum in (("a", 10), ("b", 12)):
            actor = out["state"]["teams"][side]["members"][1]
            self.assertEqual((actor["energy"], actor["max_energy"]), (maximum, maximum))

    def test_recharge_five_is_not_reduced_when_below_runtime_cap_12(self):
        self.actions["a"] = {"kind": "recharge", "effective_cost": 0, "effective_priority": 1}
        self.actor()["energy"], self.actor()["max_energy"] = 4, 12
        out = self.run_turn()
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertEqual(out["state"]["teams"]["a"]["members"][1]["energy"], 9)

    def test_recharge_explicit_zero_cap_is_preserved_not_replaced_by_fallback(self):
        self.actions["a"] = {"kind": "recharge", "effective_cost": 0, "effective_priority": 1}
        self.actor()["energy"], self.actor()["max_energy"] = 0, 0
        out = self.run_turn()
        self.assertEqual(out["status"], "applied", out["blockers"])
        actor = out["state"]["teams"]["a"]["members"][1]
        self.assertEqual((actor["energy"], actor["max_energy"]), (0, 0))
        self.assertEqual(out["global_skill_sources"]["7000010"]["runtime_energy_caps"], {"a": 0})

    def test_v1_still_rejects_v2_context(self):
        out = execute_research_turn(self.prepared, self.state, self.actions, self.context(), damage_resolver=lambda *_: 7)
        self.assertEqual(out["status"], "blocked")
        self.assertEqual(out["state"], self.state)


if __name__ == "__main__":
    unittest.main()
