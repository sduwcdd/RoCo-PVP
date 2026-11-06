"""Marks reach real v2 turn/cost/damage/switch paths under named research policy."""
from copy import deepcopy
from fractions import Fraction
import unittest
from unittest.mock import patch

from lab import mark_runtime as marks
from lab.core_magic_runtime import (core_magic_policy, initialize_core_magic,
    execute_core_magic, validate_core_magic)
from lab.dynamic_skills import refresh_round
from lab.prepared_rules import PreparedRules
from lab.research_damage import make_research_damage_resolver
from lab.research_phases import (build_research_context_v2, execute_research_turn_v2,
                                choose_research_replacements_v2)
from tests import test_action_runtime as action_fixture


class MarkIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        action_fixture.JointActionRuntimeTests.setUpClass()
        cls.catalog = action_fixture.JointActionRuntimeTests.catalog
        cls.prepared = PreparedRules(cls.catalog)

    def setUp(self):
        fixture = action_fixture.JointActionRuntimeTests()
        fixture.setUp()
        self.state = fixture.state
        self.actions = {"a": {"kind": "skill", "slot": 1, "effective_cost": 1, "effective_priority": 0},
                        "b": {"kind": "recharge", "effective_cost": 0, "effective_priority": 0}}
        self.actor()["skill_slots"][1] = 7020370
        self.overrides = {}

    def actor(self, side="a", slot=1):
        return self.state["teams"][side]["members"][slot]

    def put(self, side, mark_id, count=1):
        self.state["teams"][side]["marks"], _ = marks.change_marks(self.state["teams"][side]["marks"],
            mark_id, count, context=marks.research_context(), source={"test": "explicit mark input"})

    def turn(self, resolver=None):
        context = build_research_context_v2(self.prepared, self.state, self.actions, program_overrides=self.overrides)
        return execute_research_turn_v2(self.prepared, self.state, self.actions, context,
            program_overrides=self.overrides, damage_resolver=resolver or (lambda *args: 5),
            status_damage_resolver=lambda *args: 3)

    def real_resolver(self, traces):
        for team in self.state["teams"].values():
            for member in team["members"]:
                member["stats"] = {key: 100 for key in ("patk", "matk", "pdef", "mdef", "spd")}
        resolver = make_research_damage_resolver(self.catalog, {"candidate_id": "arena_documented_damage60_v1",
            "same_type_multiplier": 1, "stat_modifier_policy": "linear_signed_terms_experiment"})
        def resolve(params, state, context):
            trace = resolver.explain(params, state, context)
            traces.append(trace)
            return trace["actual_hp_loss"]
        return resolve

    def test_setter_native_attack_damage_and_team_field_authority(self):
        self.actor()["skill_slots"][1] = 7020710
        self.actions["a"]["effective_cost"] = 3
        before = deepcopy(self.state)
        first = self.turn()
        self.assertEqual(first["status"], "applied", first["blockers"])
        self.assertEqual(first["state"]["teams"]["a"]["marks"]["positive"]["id"], 1018)
        self.assertEqual(first["state"]["teams"]["a"]["members"][1]["mark_entry_actions"], 1)
        self.assertEqual(self.state, before)
        self.state = first["state"]
        self.actor()["skill_slots"][1] = 7020370
        self.actions["a"]["effective_cost"] = 1
        traces = []
        second = self.turn(self.real_resolver(traces))
        self.assertEqual(second["status"], "applied", second["blockers"])
        self.assertEqual(traces[0]["effective_power_this_hit"], 71.5)
        self.assertNotIn("field_marks", second["state"]["teams"]["a"]["members"][1])
        self.assertNotIn("team_devotion", second["state"]["teams"]["a"]["members"][1])

    def test_wet_cost_and_slow_speed_are_used_by_actual_planner_and_payment(self):
        self.put("a", 1022, 2)
        self.put("a", 1032, 2)
        self.actions["a"]["effective_cost"] = 4
        result = self.turn()
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["effective_speeds"], {"a": 80, "b": 100})
        self.assertEqual(result["action_order"], ["b", "a"])
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["energy"], 8)

    def test_poison_and_photosynthesis_round_end_run_once_with_source_rates(self):
        self.put("a", 1021, 2)
        self.put("b", 1014, 2)
        result = self.turn()
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["energy"], 11)
        self.assertEqual(result["state"]["teams"]["b"]["members"][1]["hp"], 274)
        poison = [e for e in result["events"] if e.get("op") == "mark.trigger" and e.get("mark_id") == 1014]
        self.assertEqual(len(poison), 1)
        self.assertEqual(poison[0]["damage"], 21)

    def test_burst_first_action_counter_persists_and_never_repeats_on_second_turn(self):
        self.put("a", 1023, 2)
        traces = []
        first = self.turn(self.real_resolver(traces))
        self.assertEqual(first["status"], "applied", first["blockers"])
        self.assertEqual(traces[0]["effective_power_this_hit"], 85)
        self.state = first["state"]
        traces = []
        second = self.turn(self.real_resolver(traces))
        self.assertEqual(second["status"], "applied", second["blockers"])
        self.assertEqual(traces[0]["effective_power_this_hit"], 65)
        self.assertEqual(second["state"]["teams"]["a"]["members"][1]["mark_entry_actions"], 2)

    def test_wind_mark_uses_first_committed_action_position(self):
        self.put("a", 1027, 1)
        self.actor()["speed"] = 101
        traces = []
        first = self.turn(self.real_resolver(traces))
        self.assertEqual(first["status"], "applied", first["blockers"])
        self.assertEqual(traces[0]["effective_power_this_hit"], 78)
        self.actor()["speed"] = 99
        traces = []
        second = self.turn(self.real_resolver(traces))
        self.assertEqual(second["status"], "applied", second["blockers"])
        self.assertEqual(traces[0]["effective_power_this_hit"], 65)

    def test_sprout_uses_shared_effect_stat_layer_path(self):
        self.put("a", 3012, 2)
        p = deepcopy(self.prepared._rules.program(7020370))
        p["operations"] = [{"op": "stat.modify", "params": {"target": "self", "attributes": ["patk"],
                           "percent": {"numerator": 50, "denominator": 100}}}]
        p["source_hash"] = "constructed-stat-layer-integration"
        self.overrides[7020370] = p
        result = self.turn()
        self.assertEqual(result["status"], "applied", result["blockers"])
        term = result["state"]["teams"]["a"]["members"][1]["stat_modifiers"]["patk"][0]
        self.assertEqual(Fraction(term["numerator"], term["denominator"]), Fraction(7, 10))

    def test_star_mark_settles_after_non_illusion_attack(self):
        self.put("b", 1035, 2)
        calls, powers = [], []
        def resolve(*args):
            calls.append(True)
            return 5
        def star(descriptor, state, context):
            powers.append(descriptor['power'])
            return 7
        resolve.mark_damage = star
        result = self.turn(resolve)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(calls, [True])
        self.assertEqual(powers, [40])
        self.assertEqual(result["state"]["teams"]["b"]["members"][1]["hp"], 300 - 5 - 7)
        self.assertIsNone(result["state"]["teams"]["b"]["marks"]["negative"])
        trigger = [e for e in result["events"] if e.get("op") == "mark.trigger"]
        self.assertEqual(len(trigger), 1)
        self.assertEqual(trigger[0]["mark_id"], 1035)
        self.assertEqual(trigger[0]["damage"], 7)

    def test_star_mark_blocks_when_the_attack_type_is_unresolved(self):
        # 保留"绝不静默放行"的守卫：判不出技能属性时必须在伤害回调之前阻断。
        # 实际拦在伤害层（blockers=["invalid damage kind or type"]），而不是印记层；
        # 这里只要求"被阻断 + 回调没跑 + 有可读原因"，不锁定具体文案。
        self.put("b", 1035, 1)
        program = deepcopy(self.prepared._rules.program(7020370))
        for operation in program["operations"]:
            operation.get("params", {}).pop("type", None)
        self.overrides[7020370] = program
        calls = []
        result = self.turn(lambda *args: (calls.append(True) or 5))
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(result["blockers"], "阻断必须给出原因")
        self.assertTrue(any("invalid damage" in blocker.lower() or "star" in blocker.lower()
                            for blocker in result["blockers"]), result["blockers"])
        self.assertEqual(calls, [])

    def test_transmission_requires_preselection_phase_and_rotates_next_round_once(self):
        self.actor()["skill_slots"] = [7070010, 7020370, 0, 0]
        self.actions["a"]["slot"] = 0
        result = self.turn()
        self.assertEqual(result["status"], "blocked")
        self.assertIn("before skill selection", result["blockers"][0])
        first_events = marks.prepare_battle_transmission(self.state)
        self.assertEqual(len(first_events), 1)
        self.assertEqual(self.actor()["skill_slots"], [7020370, 7070010, 0, 0])
        self.actions["a"]["slot"] = 1
        result = self.turn()
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["skill_slots"], [7020370, 0, 7070010, 0])
        self.assertEqual(marks.prepare_battle_transmission(result["state"]), [])
        mixed = deepcopy(self.state)
        mixed["dynamic_skills"] = {}
        before = deepcopy(mixed)
        with self.assertRaisesRegex(ValueError, "dynamic-skill PRNG"):
            marks.validate_battle_transmission(mixed)
        self.assertEqual(mixed, before)

    def test_factory_incoming_cost_includes_each_dynamic_slot_delta(self):
        self.actor("a", 0)["skill_slots"] = [7020850, 0, 0, 0]
        self.actor("b")["skill_slots"] = [7150150, 0, 0, 0]
        refresh_round(self.prepared, self.state)
        self.actions["a"] = {"kind": "switch", "target_slot": 0}
        context = build_research_context_v2(self.prepared, self.state, self.actions)
        self.assertEqual(context["switches"]["a"]["incoming_effective_costs"], [0, None, None, None])
        self.put("a", 1030, 1)
        context = build_research_context_v2(self.prepared, self.state, self.actions)
        # Wind wall is a defense skill, so the attack-only mark cannot add cost.
        self.assertEqual(context["switches"]["a"]["incoming_effective_costs"][0], 0)

    def test_non_swift_charge_skill_in_incoming_slots_does_not_start_charge_during_cost_query(self):
        self.actor("a", 0)["skill_slots"] = [7100150, 0, 0, 0]
        self.actions["a"] = {"kind": "switch", "target_slot": 0}
        context = build_research_context_v2(self.prepared, self.state, self.actions)
        self.assertEqual(context["switches"]["a"]["incoming_effective_costs"][0], self.prepared._rules.skill(7100150)["energy"])
        self.assertIsNone(self.actor("a", 0)["charge"])

    def test_water_magic_zero_cost_is_last_modifier_and_expires_before_turn_advance(self):
        self.state["turn"] = 1
        for side, team in self.state["teams"].items():
            team["core_magic"] = {"id": 104004 if side == "a" else None}
            for member in team["members"]:
                member["entered_turn"] = 0
                member["magic_target_states"] = {"drill": False, "static": False, "mimic": False}
        self.actor()["form_id"] = 3002
        initialize_core_magic(self.state, policy=core_magic_policy())
        cast = execute_core_magic(self.state, {"kind": "core_magic", "item_id": 104004, "side": "a", "target_slot": 1},
                                  {"policy": core_magic_policy()}, catalog=self.catalog)
        self.assertEqual(cast["status"], "applied", cast["blockers"])
        self.state = cast["state"]
        self.put("a", 1030, 2)
        result = self.turn()
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["energy"], 10)
        self.assertEqual(result["state"]["core_magic_runtime"]["effects"], [])
        self.assertEqual(result["state"]["core_magic_runtime"]["closed_turn"], 1)
        validate_core_magic(result["state"])
        ops = [e["op"] for e in result["events"]]
        self.assertLess(ops.index("core_magic.expire"), ops.index("research.turn_advanced"))

    def test_manual_replacement_inherits_marks_and_resets_action_counter(self):
        self.put("a", 1019, 2)
        self.actor()["hp"] = 0
        context = build_research_context_v2(self.prepared, self.state, self.actions)
        pending = execute_research_turn_v2(self.prepared, self.state, self.actions, context)
        self.assertEqual(pending["status"], "awaiting_replacement", pending["blockers"])
        result = choose_research_replacements_v2(self.prepared, pending["state"], {"a": 0}, context)
        self.assertEqual(result["status"], "applied", result["blockers"])
        incoming = result["state"]["teams"]["a"]["members"][0]
        self.assertEqual(incoming["hp"], 258)
        self.assertEqual(incoming["mark_entry_actions"], 0)
        self.assertEqual(result["state"]["teams"]["a"]["marks"]["negative"]["stacks"], 2)

    def test_failed_trait_after_first_action_retains_payment_damage_and_base_events(self):
        def fail(prepared, state, event, **kwargs):
            if event == "skill.after":
                state["teams"]["a"]["members"][1]["hp"] = 0
                raise ValueError("trait hook failed after base commit")
            return []
        with patch("lab.research_phases.traits.run_event", side_effect=fail):
            result = self.turn()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["committed_actions"], ["a"])
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["energy"], 9)
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["hp"], 300)
        self.assertEqual(result["state"]["teams"]["b"]["members"][1]["hp"], 295)
        self.assertEqual(len([e for e in result["events"] if e["op"] == "damage"]), 1)
        self.assertEqual(result["post_action_stage"], "trait.skill.after")

    def test_failed_trait_after_second_action_keeps_both_commits_and_rolls_back_only_hook(self):
        self.actor("b")["skill_slots"][1] = 7020370
        self.actions["a"]["effective_priority"] = 1
        self.actions["b"] = {"kind": "skill", "slot": 1, "effective_cost": 1, "effective_priority": 0}
        def fail(prepared, state, event, **kwargs):
            if event == "skill.after" and kwargs.get("side") == "b":
                state["teams"]["b"]["members"][1]["energy"] = 0
                raise ValueError("second post action hook failed")
            return []
        with patch("lab.research_phases.traits.run_event", side_effect=fail):
            result = self.turn()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["committed_actions"], ["a", "b"])
        for side in ("a", "b"):
            member = result["state"]["teams"][side]["members"][1]
            self.assertEqual((member["energy"], member["hp"]), (9, 295))
        self.assertEqual(len([e for e in result["events"] if e["op"] == "energy.pay"]), 2)
        self.assertEqual(len([e for e in result["events"] if e["op"] == "damage"]), 2)

    def test_next_round_preparation_failure_reports_completed_boundary_without_replay(self):
        self.actor()["skill_slots"] = [7021220, 0, 0, 0]
        self.actor("b")["skill_slots"] = [7020370, 7070010, 0, 0]
        self.actions["a"]["slot"] = 0
        self.actions["b"] = {"kind": "skill", "slot": 0, "effective_cost": 1, "effective_priority": 0}
        marks.prepare_battle_transmission(self.state)
        original_prepare = marks.prepare_battle_transmission
        def fail_next(state):
            if state["turn"] == 3:
                raise ValueError("explicit next-round preparation failure")
            return original_prepare(state)
        with patch.object(marks, "prepare_battle_transmission", side_effect=fail_next):
            result = self.turn()
        self.assertEqual(result["status"], "blocked", result["blockers"])
        self.assertEqual(result["committed_actions"], ["a", "b"])
        self.assertTrue(result["turn_advanced"])
        self.assertEqual(result["state"]["turn"], 3)
        self.assertEqual(result["state"]["research_battle"]["phase"], "blocked")
        self.assertFalse(result["state"]["research_battle"]["turn_pending"])
        self.assertEqual(result["next_round_preparation"]["stage"], "transmission")
        self.assertEqual(len([e for e in result["events"] if e["op"] == "research.turn_advanced"]), 1)

    def test_public_api_combines_transmission_with_other_members_clever_change(self):
        from lab.simulation import DEFAULT_SETTINGS, simulation_request
        from tests.test_simulation import member
        settings = {**DEFAULT_SETTINGS, "source_mode": "bwiki_only"}
        teams = {"my": [member(moves=[7021220, 0, 0, 0]), member()],
                 "opponent": [member(moves=[7020370, 7070010, 0, 0]), member()]}
        prepared = simulation_request("/api/simulation/prepare", {"teams": teams, "settings": settings}, self.catalog)
        state = prepared["state"]
        # The preselection phase is normally called by simulation preparation.
        marks.prepare_battle_transmission(state)
        result = simulation_request("/api/simulation/act", {"state": state, "settings": settings,
            "actions": {"a": {"kind": "skill", "slot": 0}, "b": {"kind": "skill", "slot": 0}}}, self.catalog)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertTrue(result["turn_advanced"])
        self.assertCountEqual(result["committed_actions"], ["a", "b"])
        self.assertFalse(result["state"]["research_battle"]["turn_pending"])
        self.assertNotIn("blocked_stage", result["state"]["research_battle"])
        self.assertIn("transmission.move", [e["op"] for e in result["events"]])
        snapshot = deepcopy(result["state"])
        self.assertEqual(marks.prepare_battle_transmission(result["state"]), [])
        self.assertEqual(result["state"], snapshot)
        self.assertIn("transformation.slot_changed", [e["op"] for e in result["events"]])

    def test_transmission_keeps_unrelated_charge_and_rejects_mismatched_owner_atomically(self):
        self.actor()["skill_slots"] = [7070010, 0, 0, 0]
        self.actor("b")["charge"] = {"skill_id": 7100150, "slot": 1}
        untouched = deepcopy(self.actor("b"))
        marks.prepare_battle_transmission(self.state)
        self.assertEqual(self.actor("b"), untouched)
        self.assertEqual(self.actor()["skill_slots"], [0, 7070010, 0, 0])
        self.state["turn"] += 1
        self.actor()["charge"] = {"skill_id": 7100150, "slot": 2}
        before = deepcopy(self.state)
        with self.assertRaisesRegex(ValueError, "Charging skill must match"):
            marks.prepare_battle_transmission(self.state)
        self.assertEqual(self.state, before)


if __name__ == "__main__":
    unittest.main()
