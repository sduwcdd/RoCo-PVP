"""Source binding and atomic research component checks; no live calibration."""
from copy import deepcopy
from fractions import Fraction
import unittest

from lab.effect_runtime import HOOKS
from lab import mark_runtime as marks
from lab.server import load_catalog


def actor(**overrides):
    result = {"member_id": "fixture-member", "hp": 100, "max_hp": 200, "energy": 12, "max_energy": 12,
        "types": ["普通系"], "statuses": {}, "stat_modifiers": {},
        "skill_slots": [7020710, 0, 0, 0], "field_marks": deepcopy(marks.EMPTY),
        "team_devotion": {}}
    result.update(overrides)
    return result


class MarkRuntimeTests(unittest.TestCase):
    def test_independent_mark_layers_energy_and_ratio_damage_are_separate_not_merged(self):
        state = self.state()
        state['self'].update(max_hp=150, hp=100, energy=0)
        self.put(state, 'self', 1021, 1)
        self.put(state, 'self', 1014, 1)
        source = {'granting_trait_id': 200225,
                  'granting_trait_hash': marks._identities(marks.IDENTITIES.stat().st_mtime_ns)['trait_hash']}
        marks._mark_add(state['self'], 1021, 1, source)
        marks._mark_add(state['self'], 1022, 2, source)
        marks._mark_add(state['self'], 1014, 1, source)
        before = deepcopy(state)
        self.assertEqual(state['self']['field_marks']['positive']['id'], 1021)
        self.assertEqual(len(state['self']['independent_field_marks']), 3)
        result = marks.mark_phase(state, 'round_end', context=marks.research_context())
        self.assertEqual(result['status'], 'applied', result['blockers'])
        energy = [e for e in result['events'] if e.get('mark_id') == 1021]
        self.assertEqual(len(energy), 2)
        self.assertEqual([e['after'] - e['before'] for e in energy], [1, 1])
        poison = [e for e in result['events'] if e.get('mark_id') == 1014]
        self.assertEqual([e['damage'] for e in poison], [4, 4])
        self.assertEqual(result['state']['self']['hp'], 92)  # floor(150*.03) twice, not floor(150*.06).
        self.assertEqual(state, before)

    def test_normal_and_independent_stars_trigger_and_consume_separately(self):
        state = self.state()
        self.put(state, 'opponent', 1035, 1)
        source = {'granting_trait_id': 200225,
                  'granting_trait_hash': marks._identities(marks.IDENTITIES.stat().st_mtime_ns)['trait_hash']}
        marks._mark_add(state['opponent'], 1035, 2, source)
        seen = []
        def resolve(descriptor, relative, context):
            seen.append(descriptor['power'])
            return 5
        result = marks.mark_phase(state, 'after_attack',
            context={**marks.research_context(), 'skill_kind': 'physical', 'skill_type': '普通系'},
            damage_resolver=resolve)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual(seen, [20, 40])
        self.assertIsNone(result['state']['opponent']['field_marks']['negative'])
        self.assertEqual(result['state']['opponent']['independent_field_marks'], [])
        self.assertEqual(result['state']['opponent']['hp'], 90)

    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.programs = marks.mark_programs(cls.catalog)

    def state(self):
        return {"self": actor(), "opponent": actor()}

    def context(self, program):
        return {"mode": "isolated_skill_experiment", "snapshot_id": program["snapshot_id"],
            "source_hash": program["source_hash"], "operation_order": "source_text_order_experiment",
            "unresolved_dependencies": [], "excluded_hooks": sorted(HOOKS), "resolved_energy_cost": 2,
            "energy_policy": "clamp_to_declared_max", "energy_reduction_policy": "clamp_to_zero_experiment",
            "stat_policy": "record_signed_percentage_terms", "damage_policy": "resolver_returns_actual_integer_hp_loss",
            "multi_hit_policy": {"power_basis": "source_power_per_hit", "timing": "sequential_experiment"},
            "hp_policy": {"percentage_basis": "declared_max_hp", "rounding": "floor", "cap": "clamp_to_declared_max"},
            "status_policies": {key: {"stacking": "add_to_declared_count", "cap": None,
                "immunity_type": element} for key, element in (("poison", "毒系"), ("burn", "火系"))},
            "response_success": False, **marks.research_context()}

    def run_skill(self, skill_id, state=None, resolver=None, **context):
        program = self.programs[skill_id]
        state = self.state() if state is None else state
        return marks.execute_mark_skill(program, state, {**self.context(program), **context},
            damage_resolver=resolver or (lambda p, s, c: min(3, s["opponent"]["hp"])))

    def put(self, state, side, mark_id, count):
        value, _ = marks.change_marks(state[side]["field_marks"], mark_id, count,
            context=marks.research_context(), source={"fixture": True})
        state[side]["field_marks"] = value

    def test_every_reviewed_whole_skill_executes_and_partial_skills_remain_absent(self):
        for skill_id in self.programs:
            with self.subTest(skill_id=skill_id):
                state = self.state()
                state["self"]["skill_slots"] = [skill_id, 0, 0, 0]
                result = self.run_skill(skill_id, state)
                self.assertEqual(result["status"], "applied", result["blockers"])
                self.assertFalse(result["training_eligible"])
                self.assertFalse(result["calibrated"])
        for skill_id in (7130200, 7130320, 7130360, 7130370, 7190450, 7070060, 7070220, 7050420):
            self.assertNotIn(skill_id, self.programs)
        blocked = marks.blocked_mark_programs(self.catalog)
        self.assertEqual(len(self.programs), 33)
        self.assertEqual(len(blocked), 10)
        for skill_id in (7190280, 7190260, 7190310):
            self.assertNotIn(skill_id, self.programs)
            self.assertTrue(blocked[skill_id]["mark_component_blockers"])

    def test_add_cap_replacement_source_consume_and_no_input_mutation(self):
        initial = deepcopy(marks.EMPTY)
        source = {"skill_id": 7020710, "member_id": "a1"}
        value, events = marks.change_marks(initial, 1018, 120, context=marks.research_context(), source=source)
        self.assertEqual(value["positive"]["stacks"], 99)
        self.assertEqual(events[0]["cap"], 99)
        self.assertEqual(value["positive"]["sources"][0]["member_id"], "a1")
        value, _ = marks.change_marks(value, 1022, 2, context=marks.research_context(), source=source)
        self.assertEqual((value["positive"]["id"], value["positive"]["stacks"]), (1022, 2))
        value, events = marks.change_marks(value, 1022, -8, context=marks.research_context(), source=source)
        self.assertIsNone(value["positive"])
        self.assertEqual(events[0]["consumed"], 2)
        self.assertEqual(initial, marks.EMPTY)
        self.assertEqual(source, {"skill_id": 7020710, "member_id": "a1"})
        for count in (True, -1, 100, "1"):
            bad = {"positive": {"id": 1018, "stacks": count}, "negative": None}
            with self.assertRaises(ValueError):
                marks.validate_marks(bad)

    def test_different_battles_and_detached_configuration_do_not_leak(self):
        one = self.run_skill(7020710)
        two = self.run_skill(7050240)
        self.assertEqual(one["state"]["self"]["field_marks"]["positive"]["id"], 1018)
        self.assertEqual(two["state"]["self"]["field_marks"]["positive"]["id"], 1022)
        marks.rules()["marks"]["1018"]["cap"] = 1
        self.assertEqual(marks.rules()["marks"]["1018"]["cap"], 99)

    def test_dispel_rewards_count_both_polarities_and_clear_before_reward(self):
        state = self.state()
        self.put(state, "self", 1018, 2)
        self.put(state, "opponent", 1014, 3)
        self.put(state, "opponent", 1021, 1)
        original = deepcopy(state)
        burn = self.run_skill(7040500, state)
        self.assertEqual(burn["status"], "applied", burn["blockers"])
        self.assertEqual(burn["state"]["opponent"]["statuses"]["burn"], 30)
        self.assertEqual(burn["state"]["self"]["field_marks"], marks.EMPTY)
        self.assertEqual(burn["state"]["opponent"]["field_marks"], marks.EMPTY)
        attack = self.run_skill(7040470, state)
        self.assertEqual(attack["status"], "applied", attack["blockers"])
        self.assertEqual(attack["state"]["self"]["stat_modifiers"]["patk"], [{"numerator": 80, "denominator": 100}])
        heal = self.run_skill(7130310, state)
        self.assertEqual(heal["state"]["self"]["hp"], 180)
        self.assertEqual(state, original)

    def test_failure_after_damage_rolls_back_payment_hp_and_marks(self):
        state = self.state()
        self.put(state, "opponent", 1018, 1)
        p = self.programs[7040470]
        context = self.context(p)
        context["stat_policy"] = "unsupported"
        result = marks.execute_mark_skill(p, state, context, damage_resolver=lambda *args: 4)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["state"], state)
        self.assertEqual(result["events"], [])

    def test_source_component_tampering_and_missing_policy_are_rejected(self):
        program = deepcopy(self.programs[7020710])
        program["mark_components"][0]["amount"] = 5
        result = marks.execute_mark_skill(program, self.state(), self.context(program))
        self.assertEqual(result["status"], "blocked")
        context = self.context(self.programs[7020710])
        context.pop("mark_policies")
        result = marks.execute_mark_skill(self.programs[7020710], self.state(), context)
        self.assertEqual(result["status"], "blocked")
        altered = deepcopy(self.catalog)
        altered["glossary"][0]["definition"] = "changed"
        # Bind a known mark term explicitly; unrelated terms are base-rule review concerns.
        next(x for x in altered["glossary"] if x["key"] == 3010)["definition"] = "changed"
        with self.assertRaises(ValueError):
            marks.mark_programs(altered)

    def test_confirmed_star_components_compile_while_generic_mark_cost_is_supported(self):
        state = self.state()
        self.put(state, "opponent", 1035, 3)
        self.assertEqual(marks.modify_cost(state["self"], 7, 7190240, state["opponent"]), 4)
        programs = marks.mark_programs(self.catalog)
        self.assertTrue(programs[7190260]["mark_components"][0]["hits_per_star_layer"])
        self.assertEqual(programs[7190310]["mark_components"][0]["per_use_increment"], 1)
        self.assertNotIn(7190260, marks.blocked_mark_programs(self.catalog))

    def test_mark_power_cost_speed_budding_and_first_action_burst(self):
        state = self.state()
        self.put(state, "self", 1030, 2)
        self.assertEqual(marks.modify_cost(state["self"], 2, skill_kind="physical"), 4)
        self.assertEqual(marks.modify_cost(state["self"], 2, skill_kind="status"), 2)
        self.assertEqual(marks.modify_power(state["self"], 100, "physical"), 160)
        self.put(state, "self", 1023, 2)
        with self.assertRaises(ValueError):
            marks.modify_power(state["self"], 30, "physical")
        self.assertEqual(marks.modify_power(state["self"], 30, "physical", first_action=True), 50)
        self.assertEqual(marks.modify_power(state["self"], 30, "physical", first_action=False), 30)
        self.put(state, "self", 3012, 3)
        self.assertEqual(marks.extra_buff_layers(state["self"], 2), 5)
        self.put(state, "self", 1032, 2)
        self.assertEqual(marks.modify_speed(state["self"], 17), 0)

    def test_round_end_switch_and_skill_phase_boundaries(self):
        state = self.state()
        self.put(state, "self", 1021, 2)
        state["self"]["energy"] = 11
        self.put(state, "opponent", 1014, 3)
        seen = []
        def poison(descriptor, current, context):
            seen.append(descriptor)
            return descriptor["stacks"] * 6
        result = marks.mark_phase(state, "round_end", context=marks.research_context(), damage_resolver=poison)
        self.assertEqual(result["state"]["self"]["energy"], 12)
        self.assertEqual(result["state"]["opponent"]["hp"], 82)
        self.assertEqual(seen[0]["rate"], [3, 100])
        self.put(state, "self", 1019, 2)
        result = marks.mark_phase(state, "after_switch", context=marks.research_context())
        self.assertEqual(result["state"]["self"]["hp"], 76)
        self.put(state, "self", 1031, 2)
        result = marks.mark_phase(state, "after_skill", context={**marks.research_context(), "resolved_energy_cost": 3})
        self.assertEqual(result["state"]["self"]["stat_modifiers"]["matk"], [{"numerator": 80, "denominator": 100}])

    def test_stars_consume_once_using_explicit_power_damage_resolver(self):
        state = self.state()
        self.put(state, "opponent", 1035, 4)
        context = {**marks.research_context(), "skill_kind": "physical", "skill_type": "普通系"}
        seen = []
        def resolve(descriptor, relative, ctx):
            seen.append(descriptor["power"])
            return 17
        missing = marks.mark_phase(state, "after_attack", context=context)
        self.assertEqual(missing["status"], "blocked")
        result = marks.mark_phase(state, "after_attack", context=context, damage_resolver=resolve)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(seen, [80])
        self.assertEqual(result["state"]["opponent"]["hp"], 83)
        self.assertIsNone(result["state"]["opponent"]["field_marks"]["negative"])
        excluded = marks.mark_phase(state, "after_attack", context={**context, "skill_type": "幻系"})
        self.assertEqual(excluded["status"], "applied")
        self.assertEqual(excluded["state"], state)
        again = marks.mark_phase(result["state"], "after_attack", context=context, damage_resolver=resolve)
        self.assertEqual(again["events"], [])

    def test_dark_surge_resolver_is_explicit_atomic_and_isolated(self):
        state = self.state()
        self.put(state, "self", 3020, 1)
        def invalid(d, s, c):
            s["self"]["hp"] = 0
            return [{"stat": "patk", "numerator": -1, "denominator": 10}]
        blocked = marks.mark_phase(state, "after_switch", context=marks.research_context(), random_debuff_resolver=invalid)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["state"], state)
        result = marks.mark_phase(state, "after_switch", context=marks.research_context(),
            random_debuff_resolver=lambda *args: [{"stat": "patk", "numerator": -1, "denominator": 10}] * 5)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(len(result["state"]["self"]["stat_modifiers"]["patk"]), 5)

    def test_devotion_fixed_enhancements_affect_only_consumers_and_keep_team_state(self):
        state = self.state()
        state["self"]["team_devotion"] = {"power": 2, "hits": 1, "poison": 1, "cost": 1, "lifesteal": 1}
        self.assertEqual(marks.modify_cost(state["self"], 0, 7130100), 4)
        self.assertEqual(marks.modify_cost(state["self"], 7, 7130130), 5)
        seen = []
        result = self.run_skill(7130100, state, resolver=lambda p, s, c: (seen.append(p) or 10))
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0]["power"], 80)
        self.assertEqual(result["state"]["opponent"]["statuses"]["poison"], 2)
        self.assertEqual(result["state"]["self"]["hp"], 102)
        self.assertEqual(result["state"]["self"]["team_devotion"], state["self"]["team_devotion"])
        producer = self.run_skill(7130180, state)
        self.assertEqual(producer["state"]["self"]["team_devotion"]["cost"], 2)

    def test_transmission_preserves_four_slots_and_explicit_collision_order(self):
        original = actor(skill_slots=[7070010, 7070040, 0, 7020710])
        member, events = marks.advance_transmission(original, context=marks.research_context())
        self.assertEqual(member["skill_slots"], [7070010, 0, 7070040, 7020710])
        self.assertEqual([e["distance"] for e in events], [1, 2])
        self.assertEqual(original["skill_slots"], [7070010, 7070040, 0, 7020710])
        wrap, _ = marks.advance_transmission(actor(skill_slots=[0, 0, 0, 7070010]), context=marks.research_context())
        self.assertEqual(wrap["skill_slots"], [7070010, 0, 0, 0])

    def test_team_marks_are_authoritative_during_relative_attach_and_commit(self):
        current = {"teams": {side: {"active_slot": 0, "members": [actor()], "marks": deepcopy(marks.EMPTY)} for side in ("a", "b")}}
        before = deepcopy(current)
        relative = marks.attach_relative_marks(current, "b")
        result = self.run_skill(7020710, relative)
        self.assertEqual(current, before)
        marks.commit_marks(current, "b", result)
        self.assertEqual(current["teams"]["b"]["marks"]["positive"]["id"], 1018)
        self.assertNotIn("field_marks", result["state"]["self"])
        self.assertNotIn("team_devotion", result["state"]["opponent"])
        # Entry can swap members without copying marks; the next fragment sees the team field.
        current["teams"]["b"]["members"] = [actor()]
        attached = marks.attach_relative_marks(current, "b")
        self.assertEqual(attached["self"]["field_marks"]["positive"]["stacks"], 1)

    def test_unified_dispatch_star_consume_uses_reviewed_amount_and_runs_after_skill(self):
        state = self.state()
        self.put(state, "opponent", 1035, 1)
        program = self.programs[7040470]
        seen = []
        result = marks.execute_with_marks(program, state,
            {**self.context(program), "skill_kind": "physical", "skill_type": "普通系"},
            damage_resolver=lambda *args: (seen.append(True) or 1), mark_damage_resolver=lambda *args: 7)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["opponent"]["hp"], 92)
        self.assertIsNone(result["state"]["opponent"]["field_marks"]["negative"])
        state = self.state()
        self.put(state, "self", 1031, 1)
        result = marks.execute_with_marks(program, state, {**self.context(program), "resolved_energy_cost": 3},
            damage_resolver=lambda *args: 3)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["self"]["stat_modifiers"]["patk"], [{"numerator": 40, "denominator": 100}])

    def test_battle_phase_applies_only_requested_side_and_preserves_team_authority(self):
        current = {"turn": 3, "teams": {side: {"active_slot": 0, "members": [actor()], "marks": deepcopy(marks.EMPTY)} for side in ("a", "b")}}
        for side in ("a", "b"):
            current["teams"][side]["marks"]["negative"] = {"id": 1014, "stacks": 1}
        original = deepcopy(current)
        result = marks.apply_battle_phase(current, "b", "round_end", context=marks.research_context())
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["teams"]["a"]["members"][0]["hp"], 100)
        self.assertEqual(result["state"]["teams"]["b"]["members"][0]["hp"], 94)
        self.assertEqual(result["events"][0]["target_side"], "b")
        self.assertNotIn("field_marks", result["state"]["teams"]["b"]["members"][0])
        self.assertEqual(current, original)


if __name__ == "__main__":
    unittest.main()
