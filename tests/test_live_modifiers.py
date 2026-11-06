import unittest
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from lab.live_damage import estimate_moves, skill_math
from lab.live_modifiers import mark_damage, wish_move, snow_bear_trait_damage
from lab.numeric_candidates import arena_documented_damage60
from lab.weather_runtime import set_weather


def pet(**changes):
    return {"petBaseId": 3001, "level": 60, "effectiveTraitId": 0, "energy": 10,
            "currentHp": 400, "maxHp": 400, "entryActionCount": 1, "enteredTurn": 1,
            "battleStats": {"phyAtk": 200, "magAtk": 100, "phyDef": 100, "magDef": 100},
            "moves": [{"slot": 1, "skillId": 7040370}], **changes}


def quote(attacker, defender=None, **fields):
    profile = {"kind": "physical", "power": 100, "combined": 1, "multiplier": 1,
               "stab": 1, "skillType": "普通系", "hits": 1, **fields}
    with patch("lab.live_damage._skill_damage_profile", return_value=profile):
        return estimate_moves(attacker, defender or pet())[0]


def nominal(attack, defense, power):
    return arena_documented_damage60(attack, defense, power, 1)["nominal_damage"]


class CurrentEffectPreviewTests(unittest.TestCase):
    def test_enemy_pool_forecast_is_explicit_hypothesis_validates_form_and_leaves_moves_untouched(self):
        from lab.live_damage import preview_target, _rules
        from lab.server import form_skill_pool
        pool = form_skill_pool(_rules()[0], 3001)['skills']
        sid = next(s['skillId'] for s in pool if s['kind'] in ('physical', 'magical'))
        actor = pet(petId=401, moves=[])
        target = pet(petId=1)
        snapshot = {'runtime': {'sessionId': 'pool', 'snapshotToken': 'v1',
                    'myTeam': [target], 'enemyTeam': [actor],
                    'active': {'my': {'rosterIndex': 0}, 'enemy': {'rosterIndex': 0}}}}
        request = {'sessionId': 'pool', 'snapshotToken': 'v1', 'side': 'enemy',
                   'actorPetId': 401, 'targetPetId': 1, 'skillId': sid, 'slot': None, 'previewMode': 'skill-pool'}
        before = deepcopy(snapshot)
        result = preview_target(snapshot, request)
        self.assertTrue(result['hypothetical'])
        self.assertIn('未确认', result['note'])
        self.assertIn('normalMin', result['estimate'])
        self.assertEqual(snapshot, before)
        for changes in ({'skillId': 999999}, {'snapshotToken': 'old'}, {'previewMode': None}):
            with self.assertRaises(ValueError):
                preview_target(snapshot, {**request, **changes})

    def test_type_four_group_zero_listener_does_not_block_damage_or_occupy_mark_slots(self):
        from lab.live_modifiers import actor, _mark_specs
        listener = {'id': 20890110, 'layers': 1}
        baseline = pet()
        current = pet(battleBuffs=[listener, {'id': 20010838, 'layers': 1}])
        before = deepcopy(current)
        self.assertEqual(quote(current)['normal'], quote(baseline)['normal'])
        self.assertEqual(quote(baseline, current)['normal'], quote(baseline, baseline)['normal'])
        self.assertEqual(_mark_specs(current), {})
        self.assertEqual(actor(current)['field_marks'], {'positive': None, 'negative': None})
        self.assertEqual(current, before)
        mixed = {**current, 'battleBuffs': [*current['battleBuffs'], {'id': 20490030, 'layers': 2}]}
        self.assertEqual(actor(mixed)['field_marks']['negative']['id'], 1019)
        # A real field-mark group still fails closed until its identity is reviewed.
        with self.assertRaisesRegex(ValueError, '20490010.*身份映射'):
            actor(pet(battleBuffs=[{'id': 20490010, 'layers': 1}]))

    def test_captured_frozen_soil_count_narrows_hidden_initial_skills_without_exposing_them(self):
        p = pet(effectiveTraitId=200120, moves=[{'slot': 1, 'skillId': 7080130}],
                battleBuffs=[{'id': 20230571, 'layers': 3}])
        before = deepcopy(p)
        result = quote(p, skillType='地系')
        self.assertEqual(result['normal'], nominal(200, 100, 130))
        self.assertEqual(p, before)
        self.assertEqual(quote(p, skillType='火系')['normal'], nominal(200, 100, 100))
        with_bad_layers = {**p, 'battleBuffs': [{'id': 20230571, 'layers': 5}]}
        self.assertIn('超出四槽范围', quote(with_bad_layers, skillType='地系')['reason'])

    def test_marks_use_exact_native_identities_and_do_not_confuse_poison_or_slow_statuses(self):
        from lab.live_modifiers import actor, _mark_specs
        from lab.mark_runtime import mark_identity
        p = pet(battleBuffs=[{'id': 20490030, 'layers': 3}, {'id': 20070010, 'layers': 2},
                           {'id': 20010091, 'layers': 2}])
        before = deepcopy(p)
        member = actor(p)
        self.assertEqual(member['field_marks']['negative']['id'], 1019)
        self.assertEqual(list(_mark_specs(p)), ['1019'])
        self.assertEqual(p, before)
        row = mark_identity(20170012)
        row['independent'] = False
        self.assertTrue(mark_identity(20170012)['independent'])

    def test_ordered_normal_mark_replacement_preserves_statuses_and_independent_marks(self):
        from lab.live_battle import _Pet
        from lab.live_modifiers import actor
        p = _Pet(side=0, roster_index=0, inside={'pet_id': 1, 'base_conf_id': 3001}, common={})
        for bid, layers in ((20070010, 2), (20490030, 3), (20490031, 4), (20170011, 2),
                            (20170012, 3), (20320071, 4), (20010090, 2), (20320070, 5)):
            p.set_buff(bid, layers)
        data = {b['id']: b['layers'] for b in p.buffs}
        self.assertNotIn(20490030, data)
        self.assertNotIn(20170011, data)
        self.assertEqual(data[20070010], 2)
        self.assertEqual(data[20490031], 4)
        self.assertEqual(data[20170012], 3)
        p.set_buff(20490030, 0)  # Delayed removal of the old slot cannot remove its replacement.
        a = actor({**pet(), 'battleBuffs': p.buffs})
        self.assertEqual(a['field_marks']['negative']['id'], 1032)
        self.assertEqual(a['field_marks']['positive']['id'], 1022)
        self.assertEqual({m['id']: m['stacks'] for m in a['independent_field_marks']},
                         {1019: 4, 1021: 3, 1022: 4})

    def test_native_type_restricted_power_percent_uses_buff_layers_not_response_count(self):
        from lab.live_modifiers import calc_buff, _buff_bases, _simple_buff_base_fields
        self.assertEqual(calc_buff(20230480)["powerPercent"], 10)
        unsupported = deepcopy(_buff_bases()["2023048"])
        unsupported["buffbase_param"][6]["params"] = [20580010]
        self.assertIsNone(_simple_buff_base_fields(unsupported))
        seal = pet(petBaseId=3216, effectiveTraitId=200178,
                   battleBuffs=[{"id": 20230480, "layers": 4}])
        before = deepcopy(seal)
        for kind in ("水系", "武系"):
            self.assertEqual(quote(seal, skillType=kind)["normal"], nominal(200, 100, 140))
        for kind in ("火系", "普通系"):
            self.assertEqual(quote(seal, skillType=kind)["normal"], nominal(200, 100, 100))
        unknown = {**seal, "battleBuffs": [{"id": 20230480, "layers": None}]}
        self.assertIn("加成层数未确认", quote(unknown, skillType="水系")["reason"])
        self.assertEqual(quote(unknown, skillType="火系")["normal"], nominal(200, 100, 100))
        self.assertEqual(seal, before)

    def test_composite_native_buff_applies_power_and_defense_once_in_both_directions(self):
        from types import SimpleNamespace
        from lab.live_modifiers import calc_buff, panel_candidates
        from lab.live_inference import _modifier
        buff = calc_buff(20231310)
        self.assertEqual((buff["flatPowerBonus"], buff["phyDefPercent"]), (10, 5))
        steam = pet(petBaseId=5063, effectiveTraitId=280037, battleStatsBasis="base",
                    battleBuffs=[{"id": 20231310, "layers": 11}])
        before = deepcopy(steam)
        self.assertEqual(quote(steam)["normal"], nominal(200, 100, 210))
        self.assertEqual(panel_candidates(steam, "phyDef", pet())[0], [155])
        self.assertEqual(panel_candidates(steam, "magDef", pet())[0], [100])
        self.assertEqual(quote(pet(), steam)["normal"], nominal(200, 155, 100))
        self.assertEqual(_modifier(SimpleNamespace(buffs=steam["battleBuffs"]), "pdef"), (1.55, 55, []))
        self.assertEqual(steam, before)

    def test_lens_experiment_keeps_both_choice_estimates_with_observed_old_toy(self):
        toy = pet(petBaseId=3776, effectiveTraitId=200325, battleStatsBasis="base",
            battleStats={"phyAtk": 220, "magAtk": 99, "phyDef": 195, "magDef": 166},
            battleBuffs=[{"id": 20011629, "layers": 5}, {"id": 20010010, "layers": 1}],
            moves=[{"slot": 1, "skillId": 7060260}])
        before = deepcopy(toy)
        result = estimate_moves(toy, pet())[0]
        self.assertNotIn("reason", result)
        choices = result["choices"]
        self.assertEqual([c["option"] for c in choices], [0, 1])
        for choice in choices:
            self.assertNotIn("reason", choice)
            self.assertGreater(choice["normalMin"], 0)
            self.assertEqual(choice["branches"][0]["atkRange"], [352, 352])
        self.assertGreater(choices[0]["normalMax"], choices[1]["normalMax"])
        self.assertEqual(toy, before)

    def test_observed_entry_stat_buffs_are_used_once_without_rebuilding_history(self):
        from lab.live_modifiers import panel_candidates, actor
        toy = pet(effectiveTraitId=200325, battleStatsBasis="base", battleBuffs=[
            {"id": 20011629, "layers": 5}, {"id": 20010010, "layers": 1},
            {"id": 20010020, "layers": 3}])
        before = deepcopy(toy)
        self.assertEqual(panel_candidates(toy, "phyAtk", pet())[0], [320])
        self.assertEqual(panel_candidates(toy, "magAtk", pet())[0], [180])
        self.assertNotIn("reason", quote(toy))
        self.assertNotIn("confirmed_entry_history", actor(toy))
        self.assertEqual(toy, before)
        fire = pet(effectiveTraitId=200302, battleStatsBasis="base",
                   battleBuffs=[{"id": 20010039, "layers": 4}])
        self.assertEqual(panel_candidates(fire, "phyDef", pet())[0], [140])

    def test_observed_entry_power_is_not_counted_twice_and_missing_or_invalid_buffs_block(self):
        steam = pet(effectiveTraitId=200153, battleBuffs=[{"id": 20230446, "layers": 3}])
        self.assertEqual(quote(steam)["normal"], nominal(200, 100, 130))
        absent = pet(effectiveTraitId=200325, battleStatsBasis="base",
                     battleBuffs=[{"id": 20010010, "layers": 5}])
        self.assertIn("尚未观测到当前特性加成层数", quote(absent)["reason"])
        invalid = {**steam, "battleBuffs": [{"id": 20230446, "layers": 100}]}
        self.assertIn("超出来源范围", quote(invalid)["reason"])
        from lab.live_modifiers import _raw_buffs
        with patch.dict(_raw_buffs()["20230446"], {"add_max": 100}):
            self.assertIn("数值映射已变化", quote(steam)["reason"])

    def test_cost_only_entry_trait_does_not_hide_damage_and_status_moves_are_explicit(self):
        attacker = pet(petBaseId=3117, effectiveTraitId=200110,
            moves=[{"slot": i + 1, "skillId": sid} for i, sid in enumerate((7050210, 7150220, 7130210, 7020800))])
        defender = pet(petBaseId=5021, effectiveTraitId=280017,
                       moves=[{"slot": 1, "skillId": 7070340}])
        before = deepcopy((attacker, defender))
        rows = estimate_moves(attacker, defender)
        for row in rows[:2]:
            self.assertNotIn("reason", row)
            self.assertGreater(row["normalMin"], 0)
        for row in rows[2:]:
            self.assertTrue(row["nonDamaging"])
            self.assertNotIn("normalMin", row)
        self.assertNotIn("reason", estimate_moves(defender, attacker)[0])
        self.assertEqual((attacker, defender), before)

    def test_snow_bear_freeze_preview_uses_shared_star_damage_and_keeps_state(self):
        attacker = pet(petBaseId=3457, effectiveTraitId=200205, battleStatsBasis="base",
                       moves=[{"slot": 1, "skillId": 7090230}])
        target = pet(battleBuffs=[{"id": 20580010, "layers": 3}])
        before = deepcopy((attacker, target))
        row = snow_bear_trait_damage(attacker, target)
        self.assertEqual(row["power"], 60)
        self.assertEqual(set(row["damageByKind"]), {"physical"})
        self.assertEqual(row["damageMin"], row["damageMax"])
        expected = mark_damage({**target, "battleBuffs": [{"id": 20940011, "layers": 3}]}, attacker)[0]
        self.assertEqual(row["damageByKind"]["physical"], expected["damageByKind"]["physical"])
        boosted = {**attacker, "battleBuffs": [{"id": 20010010, "layers": 5}]}
        self.assertGreater(snow_bear_trait_damage(boosted, target)["damageMin"], row["damageMin"])
        self.assertEqual((attacker, target), before)

    def test_snow_bear_combines_existing_stars_once_and_checks_freeze_conditions(self):
        bear = pet(petBaseId=3457, effectiveTraitId=200205)
        target = pet(battleBuffs=[{"id": 28910337, "layers": 3}, {"id": 20940011, "layers": 98}])
        row = snow_bear_trait_damage(bear, target)
        self.assertEqual((row["freezeLayers"], row["addedStarLayers"], row["totalStarLayers"]), (3, 1, 99))
        self.assertIsNone(snow_bear_trait_damage(pet(), target))
        self.assertIsNone(snow_bear_trait_damage({**bear, "effectiveTraitId": 0}, target))
        self.assertIsNone(snow_bear_trait_damage(bear, pet(battleBuffs=[])))
        self.assertIn("reason", snow_bear_trait_damage(bear, pet()))
        self.assertIn("reason", snow_bear_trait_damage(bear, pet(battleBuffs=[{"id": 20580010, "layers": -1}])))

    def test_native_will_response_and_enemy_groups_use_actual_target_types(self):
        from lab.live_damage import wish_scenarios
        from lab.trait_runtime import query_scope
        a, target = pet(bloodId=2,coreMagicSkillId=7010020), pet()
        with query_scope():
            wish = wish_move(a)
            result = estimate_moves({**a,'moves':[wish]},target)[0]
            self.assertIn('response',result)
            self.assertGreater(result['response']['normalMin'],result['normalMax'])
            rows = wish_scenarios(a,target)['rows']
            self.assertEqual(rows[-1]['types'],[])
            self.assertIsNone(rows[-1]['normalMin'])
            dual = wish_scenarios(a,pet(petBaseId=3016))['rows'][-1]
            self.assertIn('武系',dual['types'])
            self.assertGreater(dual['response']['normalMin'],dual['normalMin'])

    def test_on_demand_target_forecast_rejects_stale_or_unobserved_skills(self):
        from lab.live_damage import preview_target
        move={'slot':1,'skillId':7040370}
        actor=pet(petId=1,moves=[move]);target=pet(petId=402,name='替补')
        snapshot={'runtime':{'sessionId':'test','snapshotToken':3,'myTeam':[actor],
            'enemyTeam':[pet(petId=401),target],'active':{'my':{'rosterIndex':0},'enemy':{'rosterIndex':0}}}}
        request={'sessionId':'test','snapshotToken':3,'side':'my','actorPetId':1,'targetPetId':402,'skillId':7040370,'slot':1}
        before=deepcopy(snapshot)
        result=preview_target(snapshot,request)
        self.assertEqual(result['targetName'],'替补')
        self.assertEqual(snapshot,before)
        with self.assertRaisesRegex(ValueError,'状态已更新'):
            preview_target(snapshot,{**request,'snapshotToken':2})
        with self.assertRaisesRegex(ValueError,'未携带'):
            preview_target(snapshot,{**request,'skillId':7060200})

    def test_stat_layers_affect_unknown_panels_but_do_not_double_count_live_panels(self):
        buffs = [{"id": 20010010, "layers": 5}]
        projected = pet(battleStats={}, naturedStats={"phyAtk": 200}, battleBuffs=buffs)
        self.assertEqual(quote(projected)["normal"], nominal(300, 100, 100))
        captured = pet(battleStats={"phyAtk": 300}, battleBuffs=buffs)
        self.assertEqual(quote(captured)["normal"], nominal(300, 100, 100))
        protocol_base = pet(battleStats={"phyAtk": 200}, battleStatsBasis="natured_base", battleBuffs=buffs)
        self.assertEqual(quote(protocol_base)["normal"], nominal(300, 100, 100))

    def test_defense_debuff_and_attack_mark_modify_separate_stages_once(self):
        defender = pet(battleStats={}, naturedStats={"phyDef": 100}, battleBuffs=[{"id": 20010070, "layers": 5}])
        attacker = pet(battleBuffs=[{"id": 20230020, "layers": 3}])
        self.assertEqual(quote(attacker, defender)["normal"], nominal(200, 50, 130))

    def test_passive_power_and_received_damage_traits_are_applied(self):
        attacker = pet(effectiveTraitId=200075)
        self.assertEqual(quote(attacker)["normal"], nominal(200, 100, 125))
        defender = pet(effectiveTraitId=200074, carriedSkillIds=[7040370, 0, 0, 0])
        self.assertEqual(quote(pet(), defender, skillType="火系")["normal"], int(nominal(200, 100, 100) * .6))
        unknown = quote(pet(), pet(effectiveTraitId=200074))
        self.assertEqual((unknown["normalMin"], unknown["normalMax"]), (108, 180))

    def test_weather_skill_bonus_and_rain_installation_are_not_counted_twice(self):
        snow, _ = set_weather(None, 7090370, 1)
        attacker = pet(liveContext={"weather": snow}, moves=[{"slot": 1, "skillId": 7090460}])
        self.assertEqual(quote(attacker)["normal"], nominal(200, 100, 150))
        rain, _ = set_weather(None, 7050250, 1)
        attacker = pet(liveContext={"weather": rain}, battleBuffs=[{"id": 20230030, "layers": 1}], moves=[{"slot": 1, "skillId": 7050200}])
        self.assertEqual(quote(attacker, skillType="水系")["normal"], nominal(200, 100, 175))

    def test_higher_attack_is_chosen_after_current_stat_modifiers(self):
        attacker = pet(battleStats={}, naturedStats={"phyAtk": 100, "magAtk": 200}, battleBuffs=[{"id": 20010010, "layers": 20}])
        defender = pet(battleStats={"phyDef": 100, "magDef": 400})
        result = quote(attacker, defender, kind="higher")
        self.assertEqual(result["normal"], nominal(300, 100, 100))
        self.assertEqual(result["branches"][0]["attackStat"], "phyAtk")

    def test_hidden_opponent_cost_trait_does_not_expand_unknown_cost_to_99(self):
        result = quote(pet(effectiveTraitId=200117))
        self.assertIn("缺少敌方四槽能耗或同步能耗层数", result["reason"])
        self.assertNotIn("normalMax", result)

    def test_cost_trait_uses_captured_costs_and_does_not_alias_nature_markers(self):
        attacker = pet(effectiveTraitId=200117)
        defender = pet(carriedSkillIds=[7040370] * 4, carriedSkillCosts=[1, 2, 3, 4])
        self.assertEqual(quote(attacker, defender)["normal"], nominal(200, 100, 200))
        defender["carriedSkillCosts"] = [0, 0, 0, 0]
        self.assertEqual(quote(attacker, defender)["normal"], nominal(200, 100, 100))
        nature_only = pet(battleBuffs=[{"id": 20010832, "layers": 1}])
        self.assertIn("缺少敌方四槽能耗", quote(attacker, nature_only)["reason"])
        invalid = pet(battleBuffs=[{"id": 20340060, "layers": 100}])
        self.assertIn("层数冲突或无效", quote(attacker, invalid)["reason"])

    def test_real_ice_marker_13_removes_the_spurious_tenfold_power_range(self):
        fixture = json.loads((Path(__file__).resolve().parents[1] /
                              "data/reference/live-ice-cost-20261029.json").read_text(encoding="utf-8"))
        before = deepcopy(fixture)
        results = estimate_moves(fixture["attacker"], fixture["defender"])
        self.assertEqual([(q["normalMin"], q["normalMax"]) for q in results if "normalMin" in q],
                         [(120, 147), (131, 160), (247, 301)])
        self.assertEqual(results[0]["branches"][0]["powerRange"], [126.5, 126.5])
        self.assertEqual(results[0]["defRange"], [182, 222])
        self.assertEqual(fixture, before)
        dead = {**fixture["attacker"], "currentHp": 0, "alive": False}
        self.assertTrue(all(q.get("reason") == "已倒下，不能使用技能" and "normalMax" not in q
                            for q in estimate_moves(dead, fixture["defender"])))

    def test_calendar_stat_trait_uses_explicit_date_and_remains_a_separate_stat_term(self):
        defender = pet(effectiveTraitId=200269, battleStats={}, naturedStats={"phyDef": 100},
                       liveContext={"gameDate": "2026-10-29", "turn": 1})
        self.assertEqual(quote(pet(), defender)["normal"], nominal(200, 140, 100))

    def test_fixed_multi_hit_keeps_per_hit_and_total_distinct(self):
        result = quote(pet(), hits=5)
        self.assertEqual(result["perHitMin"], nominal(200, 100, 100))
        self.assertEqual(result["normal"], result["perHitMin"] * 5)

    def test_one_shot_requires_minimum_damage_strictly_above_positive_remaining_hp(self):
        self.assertFalse(quote(pet(), pet(currentHp=180))["oneShot"])
        self.assertTrue(quote(pet(), pet(currentHp=179))["oneShot"])
        self.assertFalse(quote(pet(), pet(currentHp=0))["oneShot"])

    def test_response_history_forecasts_the_normal_skill_power(self):
        attacker = pet(moves=[{"slot": 1, "skillId": 708033100}])
        result = estimate_moves(attacker, pet())[0]
        normal = skill_math(7080330, 3001, 3001)
        expected = arena_documented_damage60(200, 100, normal["power"], normal["combined"])["nominal_damage"]
        self.assertEqual(result["normal"], expected)

    def test_type_restricted_state_does_not_increase_other_skill_types(self):
        attacker = pet(battleBuffs=[{"id": 20230790, "layers": 3}])
        self.assertEqual(quote(attacker, skillType="火系")["normal"], nominal(200, 100, 100))
        self.assertEqual(quote(attacker, skillType="毒系")["normal"], nominal(200, 100, 130))

    def test_stat_difference_uses_effective_panels_and_explicit_third_party_candidate(self):
        attacker = pet(moves=[{"slot": 1, "skillId": 7080320}], battleStats={},
                       naturedStats={"phyAtk": 200, "phyDef": 100}, battleBuffs=[{"id": 20010050, "layers": 10}])
        result = quote(attacker, pet(), damageRule=38)
        self.assertEqual(result['normal'], nominal(200, 100, 140))
        self.assertIn('第三方30点档位候选', result['effects'][0]['intrinsic_power_uncertainty'])
        from lab.power_rule_runtime import rule_power
        power = rule_power({"pdef": 200}, {"pdef": 100}, 7080320, 100)
        self.assertEqual(power, 140)  # Local HUD and execution call the same source-bound query.

    def test_conditional_damage_buffs_respect_hp_cost_and_matchup(self):
        healthy = pet(battleBuffs=[{"id": 20290020, "layers": 1}])
        self.assertEqual(quote(healthy)["normal"], int(nominal(200, 100, 100) * 1.2))
        hurt = pet(currentHp=100, battleBuffs=[{"id": 20290020, "layers": 1}])
        self.assertEqual(quote(hurt)["normal"], nominal(200, 100, 100))
        self.assertEqual(quote(pet(), hurt)["normal"], int(nominal(200, 100, 100) * .8))
        hurt["battleBuffs"].append({"id": 20110462, "layers": 1})
        self.assertEqual(quote(pet(), hurt)["normal"], int(nominal(200, 100, 100) * .8))
        self.assertEqual(quote(pet(), pet(battleBuffs=[{"id": 20400310, "layers": 1}]))["normal"], nominal(200, 100, 100))
        divine = pet(battleBuffs=[{"id": 20420010, "layers": 1}])
        self.assertEqual(quote(divine)["normal"], nominal(200, 100, 100))
        self.assertEqual(quote(divine, multiplier=2, combined=2)["normal"], nominal(200, 100, 100) * 4)
        natural = pet(battleBuffs=[{"id": 20530060, "layers": 1}])
        self.assertEqual(quote(natural)["normal"], nominal(200, 100, 100))
        natural["moves"] = [{"slot": 1, "skillId": 7080330}]
        natural["battleBuffs"] = [{"id": 28810028, "layers": 1}]
        self.assertEqual(quote(natural)["normal"], nominal(200, 100, 140))

    def test_native_power_parameters_override_stale_flat_mapping(self):
        attacker = pet(battleBuffs=[{"id": 28810016, "layers": 1}])
        self.assertEqual(quote(attacker)["normal"], nominal(200, 100, 130))
        attacker["battleBuffs"] = [{"id": 28810040, "layers": 1}]
        self.assertEqual(quote(attacker)["normal"], nominal(200, 100, 105))

    def test_star_explosion_and_periodic_marks_are_separate_source_bound_rows(self):
        star = mark_damage(pet(battleBuffs=[{"id": 20940011, "layers": 5}]), pet())
        self.assertEqual(star[0]["power"], 100)
        self.assertEqual(set(star[0]["damageByKind"]), {"physical", "magical"})
        self.assertNotEqual(star[0]["damageMin"], 100)
        self.assertEqual(star[0]["phase"], "after_attack")
        poison = mark_damage(pet(battleBuffs=[{"id": 20070011, "layers": 3}]), pet())
        self.assertEqual(poison[0]["damage"], 36)
        self.assertEqual(poison[0]["phase"], "round_end")

    def test_bloodline_wish_is_an_extra_preview_and_boss_blood_is_excluded(self):
        attacker = pet(bloodId=2)
        wish = wish_move(attacker)
        self.assertEqual(wish["slot"], 5)
        self.assertIn("草", wish["skillName"])
        result = estimate_moves({**attacker, "moves": [wish]}, pet())[0]
        self.assertNotIn("reason", result)
        self.assertIsNone(wish_move(pet(bloodId=19)))
        self.assertIsNone(wish_move(pet(bloodId=0)))
        self.assertIsNone(wish_move(pet(bloodId=2, coreMagicSkillId=7010070)))
        self.assertIsNotNone(wish_move(pet(bloodId=2, coreMagicSkillId=7010020)))


if __name__ == "__main__":
    unittest.main()
