import json
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from lab.live_damage import estimate_moves, skill_math
from lab.live_power import specification
from lab.numeric_candidates import arena_documented_damage60


def pet(**changes):
    return {"petBaseId": 3001, "level": 60, "effectiveTraitId": 0, "energy": 10,
            "currentHp": 400, "maxHp": 400, "battleBuffs": [],
            "battleStats": {"phyAtk": 200, "magAtk": 200, "phyDef": 100, "magDef": 100}, **changes}


def quote(sid, attacker=None, defender=None, **move):
    return estimate_moves({**(attacker or pet()), "moves": [{"slot": 1, "skillId": sid, **move}]}, defender or pet())[0]


def nominal(sid, power):
    p = skill_math(sid, 3001, 3001)
    return arena_documented_damage60(200, 100, power, p["combined"])["nominal_damage"]


class LivePowerTests(unittest.TestCase):
    def test_overexposure_reuses_distinct_type_history_and_bounds_late_spectators(self):
        from lab.live_modifiers import damage_profile
        p = pet(carriedSkillIds=[7060120, 7030440, 7040370, 0], skillUseHistoryComplete=True,
                skillTypeUseCounts={'7040370': {'火系': 3}, '7030440': {'草系': 2},
                                    '7060120': {'光系': 5}})
        before = deepcopy(p)
        profile = {**skill_math(7060120, 3001, 3001), 'skillId': 7060120}
        result = damage_profile(p, pet(), 7060120, profile)
        self.assertEqual(result['powerRange'], [120, 120])
        self.assertEqual(quote(7060120, attacker=p)['normal'], nominal(7060120, 120))
        self.assertEqual(p, before)
        hidden = damage_profile({**p, 'carriedSkillIds': None}, pet(), 7060120, profile)
        self.assertEqual(hidden['powerRange'], [60, 120])
        late = quote(7060120, attacker={**p, 'skillUseHistoryComplete': False})
        self.assertNotIn('reason', late)
        self.assertEqual(late['effects'][0]['intrinsic_power_range'], [120, 120])
        self.assertIn('中途观战', late['effects'][0]['intrinsic_power_uncertainty'])

    def test_overexposure_incomplete_history_bounds_only_current_carried_types(self):
        p = pet(carriedSkillIds=[7040370,7030440,7110200,7060120],skillUseHistoryComplete=False,
                skillTypeUseCounts={'7040370':{'火系':2},'7110200':{'电系':2},'7060120':{'光系':1}})
        before=deepcopy(p)
        result=quote(7060120,attacker=p)
        self.assertEqual(result['effects'][0]['intrinsic_power_range'],[120,150])
        self.assertEqual(p,before)
        p['carriedSkillIds']=[7040370,7040370,7060120,0]
        p['skillTypeUseCounts']={'7040370':{'火系':3}}
        self.assertEqual(quote(7060120,attacker=p)['effects'][0]['intrinsic_power_range'],[90,90])

    def test_overexposure_unknown_slots_and_conflicting_history_are_not_silently_filled(self):
        result=quote(7060120,attacker=pet(skillUseHistoryComplete=False))
        self.assertIn('真实四槽',result['reason'])
        p=pet(carriedSkillIds=[7060120,7040370,0,0],skillUseHistoryComplete=False,
              skillTypeUseCounts={'7050180':{'水系':1}})
        self.assertIn('不能用当前配招覆盖',quote(7060120,attacker=p)['reason'])

    def test_response_growth_matches_shared_ledger_without_double_application_or_hidden_slots(self):
        from lab import skill_history_runtime as history
        from lab.live_modifiers import damage_profile
        from lab.live_damage import _rules
        from lab.prepared_rules import PreparedRules
        from tests.test_carried_skill_history import CarriedSkillHistoryTests
        fixture = CarriedSkillHistoryTests()
        fixture.prepared = PreparedRules(_rules()[0])
        fixture.programs = history.programs(fixture.prepared)
        state = fixture.fixture([7020570, 7020780, 0, 0])
        for count in range(3):
            if count:
                state['turn'] = count
                fixture.commit(state, 1, 'response:' + str(count), successful=True)
            expected = fixture.power(state, 0)
            self.assertEqual(expected, 80 + 90 * count)
            native = pet(responseSuccessCount=count, responseHistoryComplete=True,
                         carriedSkillIds=[7020570, 7020780, 0, 0])
            before = deepcopy(native)
            self.assertEqual(quote(7020570, attacker=native)['normal'], nominal(7020570, expected))
            self.assertEqual(native, before)
            binding = history.bind_action(fixture.prepared, state, 'a', fixture.action(state, 0))
            simulated = {**native, '_simulation_actor': state['teams']['a']['members'][0],
                         '_execution_context': {'skill_history_power': history.power_terms(state, binding)}}
            profile = {**skill_math(7020570, 3001, 3001), 'skillId': 7020570}
            self.assertEqual(damage_profile(simulated, pet(), 7020570, profile)['powerRange'], [expected, expected])
            hidden = quote(7020570, attacker={**native, 'carriedSkillIds': None})
            self.assertEqual(hidden.get('normalMin', hidden.get('normal')), nominal(7020570, 80))
            self.assertEqual(hidden.get('normalMax', hidden.get('normal')), nominal(7020570, expected))
        for count in (None, True, -1):
            blocked = quote(7020570, attacker=pet(responseSuccessCount=count, responseHistoryComplete=True))
            self.assertIn('应对历史不完整', blocked['reason'])
            self.assertNotIn('normal', blocked)

    def test_tracker_counts_owned_responses_once_keeps_them_across_switches_and_labels_late_observation(self):
        from lab.live_battle import BattleTracker
        def record(pid, pos=1):
            return {'battle_inside_pet_info': {'pet_id': pid, 'base_conf_id': 3001, 'pos': pos,
                'battle_attr': [0, 400, 200, 200, 100, 100, 200],
                'skill_round_data': [{'pos': 1, 'skill_id': 7020570}, {'pos': 2, 'skill_id': 7110230}]},
                'battle_common_pet_info': {'level': 60}}
        init = {'init_info': {'battle_id': 1, 'player_team': [{'pets': [record(1), record(2, 0)]}],
                             'enemy_team': [{'pets': [record(401)]}]}}
        tracker = BattleTracker()
        tracker.handle_event('0x1316', init)
        own = tracker._pet_by_id['1']
        response = {'skill_cast': {'caster_id': 1, 'skill_id': 702045100, 'skill_name': '应对！突袭'}}
        command = {'perform_cmd': {'round': 1, 'perform_info': [response]}}
        tracker._on_round_start(command)
        tracker._on_perform(command)
        self.assertEqual(own.response_success_count, 1)
        tracker._apply_perform_item({'skill_cast': {'caster_id': 401, 'skill_id': 702045100}})
        tracker._apply_perform_item({'skill_cast': {'caster_id': 2, 'skill_id': 702045100}})
        tracker._apply_perform_item({'skill_cast': {'caster_id': 1, 'skill_id': 702045000}})
        self.assertEqual(own.response_success_count, 1)
        tracker._confirm_active(tracker._pet_by_id['2'])
        tracker._confirm_active(own)
        self.assertEqual(own.response_success_count, 1)
        self.assertEqual(own.entry_count, 2)
        tracker._apply_perform_item(response)  # Another real cast may have the same round and ID.
        self.assertEqual(own.response_success_count, 2)
        payload = {**own.to_payload(hide_unobserved=False, observed={}), 'effectiveTraitId': 0}
        self.assertEqual(quote(7020570, attacker=payload)['normal'], nominal(7020570, 260))
        own.refresh_stats({'skill_round_data': [{'pos': 2, 'skill_id': 7040200}]}, {})
        changed = quote(7020570, attacker={**own.to_payload(hide_unobserved=False, observed={}), 'effectiveTraitId': 0})
        self.assertIn('技能槽发生变化', changed['reason'])
        late = deepcopy(init)
        late['round'] = 10
        late['init_info']['observe_battle'] = {'is_observer': True}
        tracker.handle_event('0x1316', late)
        tracker._apply_perform_item(response)
        payload = {**tracker._pet_by_id['1'].to_payload(hide_unobserved=False, observed={}), 'effectiveTraitId': 0}
        for sid in (7020570, 7110230):
            blocked = quote(sid, attacker=payload)
            self.assertIn('中途观战（第10回合接入）', blocked['reason'])
            self.assertNotIn('normal', blocked)
        self.assertIn('已记录1次应对成功', quote(7020570, attacker=payload)['reason'])
        tracker.handle_event('0x1316', init)
        self.assertEqual(tracker._pet_by_id['1'].response_success_count, 0)

    def test_other_grass_skill_growth_is_local_permanent_deduplicated_and_not_self_triggered(self):
        from lab.live_battle import BattleTracker
        def record(pid):
            return {'battle_inside_pet_info': {'pet_id': pid, 'base_conf_id': 3001, 'pos': 1,
                'battle_attr': [0, 400, 200, 200, 100, 100, 200],
                'skill_round_data': [{'pos': 1, 'skill_id': 7030210}, {'pos': 2, 'skill_id': 7030440}]},
                'battle_common_pet_info': {'level': 60}}
        tracker = BattleTracker()
        entry = {'init_info': {'battle_id': 1, 'player_team': [{'pets': [record(1)]}],
                              'enemy_team': [{'pets': [record(401)]}]}}
        tracker.handle_event('0x1316', entry)
        own = tracker._pet_by_id['1']
        def damage():
            return quote(7030210, attacker={**own.to_payload(hide_unobserved=False, observed={}), 'effectiveTraitId': 0})
        self.assertEqual(damage()['normal'], nominal(7030210, 100))
        grass = {'skill_cast': {'caster_id': 1, 'skill_id': 703044000, 'skill_name': '草系技能'}}
        tracker._apply_perform_item(grass, from_round_start=True)
        tracker._apply_perform_item(grass)
        self.assertEqual(damage()['normal'], nominal(7030210, 160))
        tracker._apply_perform_item({'skill_cast': {'caster_id': 401, 'skill_id': 703044000}})
        tracker._apply_perform_item({'skill_cast': {'caster_id': 1, 'skill_id': 703021000}})
        tracker._apply_perform_item({'skill_cast': {'caster_id': 1, 'skill_id': 702036000}})
        self.assertEqual(damage()['normal'], nominal(7030210, 160))
        tracker._apply_perform_item(grass)
        self.assertEqual(damage()['normal'], nominal(7030210, 220))
        tracker.handle_event('0x1316', {**entry, 'round': 8})
        own = tracker._pet_by_id['1']
        self.assertIn('历史不完整', damage()['reason'])

    def test_choice_damage_uses_shared_options_and_strict_hp_threshold(self):
        for hp, dark_power in ((201, 85), (200, 85), (199, 185)):
            original = pet(currentHp=hp)
            before = deepcopy(original)
            result = quote(7180420, attacker=original)
            first, second = result['choices']
            self.assertEqual(first['normal'], nominal(7180420, 125))
            self.assertEqual(second['normal'], nominal(7180420, dark_power))
            self.assertIn('10%', first['note'])
            self.assertEqual(original, before)
        unknown = quote(7180420, attacker=pet(currentHp=None, maxHp=None))['choices'][1]
        self.assertEqual((unknown['normalMin'], unknown['normalMax']),
                         (nominal(7180420, 85), nominal(7180420, 185)))

    def test_other_choice_damage_handles_hp_slot_response_and_hidden_carried_types(self):
        self.assertEqual(quote(7030580, attacker=pet(currentHp=321))['choices'][0]['normal'], nominal(7030580, 145))
        self.assertNotIn('choices', quote(7030580, attacker=pet(currentHp=320)))
        self.assertEqual(quote(7070220, slot=1)['choices'][0]['normal'], nominal(7070220, 135))
        self.assertNotIn('choices', quote(7070220, slot=2))
        drive = quote(7140340)['choices']
        self.assertEqual(drive[0]['normal'], nominal(7140340, 90))
        self.assertEqual(drive[1]['normal'], nominal(7140340, 70))
        self.assertEqual(drive[1]['response']['normal'], nominal(7140340, 210))
        hidden = quote(7060260)['choices'][0]
        self.assertEqual((hidden['normalMin'], hidden['normalMax']), (nominal(7060260, 115), nominal(7060260, 165)))
        self.assertNotIn('choices', quote(7090450))
        self.assertIn('累计威力', quote(7150360)['choices'][0]['reason'])

    def test_choice_execution_uses_the_same_resolved_power_as_native_preview(self):
        from lab.hud_damage_runtime import HUDDamageResolver
        from lab.live_damage import _rules
        from tests.test_hud_damage_runtime import member
        catalog, _ = _rules()
        resolver = HUDDamageResolver(catalog)
        state = {'self': member(3001, 'a:0'), 'opponent': member(3002, 'b:0')}
        state['self']['skill_slots'][0] = 7180420
        state['self']['hp'] = 200
        context = {'snapshot_id': catalog['snapshot_id'], 'turn': 1, 'weather': None,
                   'weather_skill_id': 7180420, 'selected_skill_slot': 0,
                   'mark_first_attack': False, 'mark_first_action': True, 'response_success': False}
        for option, power in ((0, 125), (1, 185)):
            result = resolver.explain({'target': 'opponent', 'kind': 'physical', 'type': '恶系', 'power': power},
                                      state, {**context, 'choice_option': option})
            self.assertEqual(result['hud_case']['powerRange'], [power, power])

    def test_tracker_publishes_both_choice_branches_without_extra_skill_slots(self):
        from lab.live_battle import BattleTracker
        def record(pid):
            return {'battle_inside_pet_info': {'pet_id': pid, 'base_conf_id': 3001, 'pos': 1,
                'battle_attr': [0, 400, 200, 200, 100, 100, 200],
                'skill_round_data': [{'pos': 1, 'skill_id': 7180420}]}, 'battle_common_pet_info': {'level': 60}}
        tracker = BattleTracker()
        tracker.handle_event('0x1316', {'init_info': {'battle_id': 1,
            'player_team': [{'pets': [record(1)]}], 'enemy_team': [{'pets': [record(401)]}]}})
        tracker._apply_perform_item({'skill_cast': {'caster_id': 401, 'skill_id': 718042000, 'skill_name': '下注'}})
        runtime = tracker.snapshot()['runtime']
        for team in ('myTeam', 'enemyTeam'):
            moves = runtime[team][0]['moves']
            self.assertEqual(len(moves), 1)
            self.assertEqual([b['option'] for b in moves[0]['damageChoices']], [0, 1])

    def test_entry_growth_matches_shared_history_and_keeps_hidden_carrying_uncertain(self):
        from lab import skill_history_runtime as history
        from tests.test_skill_history_runtime import SkillHistoryTests
        from lab.prepared_rules import PreparedRules
        from lab.live_damage import _rules
        from lab.live_modifiers import damage_profile
        fixture = SkillHistoryTests()
        fixture.prepared = PreparedRules(_rules()[0])
        fixture.programs = history.programs(fixture.prepared)
        state = fixture.fixture([7110230, 0, 0, 0])
        history.initialize(fixture.prepared, state)
        binding = history.bind_action(fixture.prepared, state, 'a', fixture.action(7110230))
        for count in (1, 2):
            if count == 2:
                state['turn'] = 2
                state['teams']['a']['members'][0]['entered_turn'] = 2
                history.on_entry(fixture.prepared, state, 'a', event_token='entry:2')
            terms = history.power_terms(state, binding)
            native = pet(entryCount=count, entryHistoryComplete=True, carriedSkillIds=[7110230, 0, 0, 0])
            expected = history.modify_power(35, terms)
            self.assertEqual(quote(7110230, attacker=native)['normal'], nominal(7110230, expected))
            simulated = {**native, '_simulation_actor': state['teams']['a']['members'][0],
                         '_execution_context': {'skill_history_power': terms}}
            profile = {**skill_math(7110230, 3001, 3001), 'skillId': 7110230}
            self.assertEqual(damage_profile(simulated, pet(), 7110230, profile)['powerRange'], [expected, expected])
            for attacker in (native, simulated):
                with patch('lab.live_modifiers._damage_buff_terms', return_value=(10, 20, [0, 0])):
                    combined = damage_profile({**attacker, 'battleBuffs': [{'id': 20230440, 'layers': 1}]},
                                              pet(), 7110230, profile)
                self.assertEqual(combined['powerRange'], [(expected + 10) * 1.2] * 2)
            enemy = quote(7110230, attacker={**native, 'carriedSkillIds': None})
            self.assertEqual((enemy['normalMin'], enemy['normalMax']),
                             (nominal(7110230, 35), nominal(7110230, expected)))
        for value in (None, True, -1):
            result = quote(7110230, attacker=pet(entryCount=value, entryHistoryComplete=True))
            self.assertIn('入场历史不完整', result['reason'])
            self.assertNotIn('normal', result)

    def test_tracker_entry_counts_initial_switch_dedup_reentry_and_incomplete_history(self):
        from lab.live_battle import BattleTracker
        def record(pid, pos):
            return {'battle_inside_pet_info': {'pet_id': pid, 'base_conf_id': 3001, 'pos': pos,
                'battle_attr': [0, 400, 200, 200, 100, 100, 200],
                'skill_round_data': [{'pos': 1, 'skill_id': 7110230}]},
                'battle_common_pet_info': {'level': 60}}
        tracker = BattleTracker()
        init = {'init_info': {'battle_id': 1, 'player_team': [{'pets': [record(1, 1), record(2, 0)]}],
                             'enemy_team': [{'pets': [record(401, 1)]}]}}
        tracker.handle_event('0x1316', init)
        own, reserve = tracker._pet_by_id['1'], tracker._pet_by_id['2']
        tracker._confirm_active(own)
        self.assertEqual(own.entry_count, 1)
        tracker._confirm_active(own)
        self.assertEqual(own.entry_count, 1)
        tracker._confirm_active(reserve)
        tracker._confirm_active(own)
        self.assertEqual(own.entry_count, 2)
        self.assertEqual(quote(7110230, attacker={**own.to_payload(hide_unobserved=False, observed={}), 'effectiveTraitId': 0})['normal'],
                         nominal(7110230, 115))
        own.refresh_stats({'skill_round_data': [{'pos': 1, 'skill_id': 7040200}]}, {})
        self.assertIsNone(own.entry_count)
        tracker.handle_event('0x1316', {**init, 'round': 8})
        tracker._confirm_active(tracker._pet_by_id['1'])
        self.assertIsNone(tracker._pet_by_id['1'].entry_count)
        tracker.handle_event('0x1316', init)
        tracker._confirm_active(tracker._pet_by_id['1'])
        self.assertEqual(tracker._pet_by_id['1'].entry_count, 1)

    def test_all_reviewed_bindings_match_native_and_wiki_sources(self):
        config = json.loads((Path(__file__).resolve().parents[1] /
                             "data/rules/reviewed-live-power-1.json").read_text(encoding="utf-8"))
        for sid, row in config["skills"].items():
            self.assertEqual(specification(int(sid)), row)
            if row.get("response"):
                self.assertEqual(specification(row["response"]["id"]), row["response"])

    def test_poison_layers_and_response_use_distinct_native_coefficients(self):
        for count in (0, 1, 3, 20):
            target = pet(battleBuffs=[{"id": 20070010, "layers": count}])
            original = deepcopy(target)
            result = quote(7120220, defender=target)
            self.assertEqual(result["normal"], nominal(7120220, 75 + 10 * count))
            self.assertEqual(result["response"]["normal"], nominal(7120221, 75 + 40 * count))
            self.assertEqual(target, original)
        self.assertIn("状态列表", quote(7120220, defender={k: v for k, v in pet().items() if k != "battleBuffs"})["reason"])

    def test_hp_steps_use_current_target_hp_and_exact_boundaries(self):
        for current, power in ((400, 155), (381, 155), (380, 150), (200, 105), (1, 60)):
            result = quote(7040460, defender=pet(currentHp=current))
            self.assertEqual(result["normal"], nominal(7040460, power))
        bounded = quote(7040460, defender=pet(currentHp=None, hpPercent=50))
        self.assertLess(bounded["normalMin"], bounded["normalMax"])
        self.assertFalse(bounded["exact"])
        self.assertIn("当前生命", quote(7040460, defender=pet(currentHp=None))["reason"])

    def test_magnetic_burst_reads_real_slot_not_opponent_observation_order(self):
        self.assertEqual(quote(7070140, slot=1)["normal"], nominal(7070140, 100))
        self.assertEqual(quote(7070140, slot=2)["normal"], nominal(7070140, 70))
        bounded = quote(7070140, observedOnly=True)
        self.assertEqual([bounded["normalMin"], bounded["normalMax"]], [nominal(7070140, 70), nominal(7070140, 100)])
        self.assertFalse(bounded["exact"])

    def test_response_power_is_not_global_50_percent_and_bonuses_are_not_doubled(self):
        result = quote(7150110, attacker=pet(battleBuffs=[{"id": 20230440, "layers": 2}]))
        self.assertEqual(result["normal"], nominal(7150110, 70 + 20))
        self.assertEqual(result["response"]["normal"], nominal(7150111, 105 + 20))
        self.assertNotEqual(result["response"]["normal"], result["normal"] * 1.5)
        self.assertNotIn("response", quote(7060200))
        self.assertEqual(quote(7080330)["response"]["normal"], nominal(7080331, 160))
        self.assertEqual(skill_math(7140080, 3001, 3013)["multiplier"], .5)
        self.assertEqual(skill_math(7140081, 3001, 3013)["multiplier"], 1)

    def test_response_multihit_stays_one_skill_with_per_hit_damage(self):
        normal = quote(7020470)
        observed = quote(702047100)
        self.assertEqual(normal["hits"], 1)
        self.assertEqual(normal["response"]["hits"], 3)
        self.assertEqual(normal["response"]["normal"], normal["perHit"] * 3)
        self.assertEqual(normal["response"], observed["response"])
        self.assertEqual(normal["normal"], observed["normal"])

    def test_other_conditions_and_missing_inputs_are_not_silently_zeroed(self):
        frozen = quote(7090310, defender=pet(battleBuffs=[{"id": 20580010, "layers": 4}]))
        self.assertEqual(frozen["normal"], nominal(7090310, 40 + 80))
        energy = quote(7030570, attacker=pet(energy=3))
        self.assertEqual(energy["normal"], nominal(7030570, 50 + 30))
        self.assertIn("当前能量", quote(7030570, attacker=pet(energy=None))["reason"])
        self.assertIn("四槽当前能耗", quote(7090360)["reason"])
        self.assertEqual(quote(7090360, defender=pet(carriedSkillCosts=[1, 2, 3, 4]))["normal"], nominal(7090360, 100))

    def test_energy_burst_uses_source_bound_vendor_tiers_and_shared_inverse(self):
        from lab.live_inference import _predicted_range
        from lab.live_power import source_power
        tiers = [46, 71, 91, 111, 136, 156, 166, 181, 191, 201, 211]
        for sid in (7020550, 7880058):
            for energy, power in enumerate(tiers):
                attacker = pet(energy=energy)
                before = deepcopy(attacker)
                result = quote(sid, attacker=attacker)
                self.assertEqual(result["normal"], nominal(sid, power))
                self.assertFalse(result["calibrated"])
                self.assertIn("用户已确认", result["effects"][0]["intrinsic_power_uncertainty"])
                self.assertEqual(attacker, before)
            overflow = quote(sid, attacker=pet(energy=20))
            self.assertEqual(overflow["normal"], nominal(sid, tiers[-1]))
            self.assertIn("当前能量", quote(sid, attacker=pet(energy=None))["reason"])
            self.assertIn("整数能量", quote(sid, attacker=pet(energy=1.5))["reason"])
            self.assertIn("当前能量", quote(sid, attacker=pet(energy=True))["reason"])
        profile = {**skill_math(7020550, 3001, 3001), "skillId": 7020550}
        attacker = pet(energy=8)
        event = {"calculation": {"attacker": attacker, "defender": pet(), "profile": profile},
                 "role": "attacker", "dimension": "matk"}
        actual = nominal(7020550, tiers[8])
        self.assertEqual(_predicted_range(event, 200), (actual, actual))
        self.assertEqual(source_power(attacker, pet(), 702055000, profile)[0], [tiers[8]])
        event["calculation"]["attacker"] = pet(energy=0, energyBeforeCast=7)
        before_payment = nominal(7020550, 181)
        self.assertEqual(_predicted_range(event, 200), (before_payment, before_payment))
        self.assertEqual(quote(7020550, attacker=pet(energy=0, energyBeforeCast=7))["normal"], before_payment)
        self.assertIn("当前能量", quote(7020550, attacker=pet(energy=7, energyBeforeCast=None))["reason"])
        self.assertIn("当前能量", quote(7020550, attacker=pet(energy=7, energyBeforeCast=True))["reason"])

    def test_tracker_publishes_response_branch_to_both_hud_sides(self):
        from lab.live_battle import BattleTracker
        def record(pid):
            return {"battle_inside_pet_info": {"pet_id": pid, "base_conf_id": 3001,
                "battle_attr": [0, 400, 200, 200, 100, 100, 200],
                "skill_round_data": [{"pos": 1, "skill_id": 7120220}]},
                "battle_common_pet_info": {"level": 60}}
        tracker = BattleTracker()
        tracker.handle_event("0x1316", {"init_info": {"battle_id": 1,
            "player_team": [{"pets": [record(1)]}], "enemy_team": [{"pets": [record(401)]}]}})
        for member in tracker._pet_by_id.values():
            member.set_buff(20070010, 3)
        tracker._apply_perform_item({"skill_cast": {"caster_id": 401, "skill_id": 712022100, "skill_name": "应对！鸩毒"}})
        runtime = tracker.snapshot()["runtime"]
        for team in ("myTeam", "enemyTeam"):
            moves = runtime[team][0]["moves"]
            self.assertEqual(len(moves), 1)
            self.assertEqual(moves[0]["damageResponse"]["normal"], nominal(7120221, 195))
        own = tracker._pet_by_id["1"]
        own.skills = [{"slot": i, "skill_id": 7120220, "energy_cost": i} for i in range(1, 5)]
        self.assertEqual(own.to_payload(hide_unobserved=False, observed={})["carriedSkillCosts"], [1, 2, 3, 4])
        self.assertIsNone(runtime["enemyTeam"][0]["carriedSkillCosts"])

    def test_captured_energy_burst_context_preserves_payment_and_covers_real_hits(self):
        evidence = json.loads((Path(__file__).resolve().parents[1] /
                               "data/reference/live-energy-burst-20261029.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["battle_id"], "90000000000000001")
        observed = evidence["observations"]
        self.assertEqual([row["context"]["attacker"]["energyBeforeCast"] for row in observed], [8, 0])
        self.assertEqual([row["context"]["attacker"]["energy"] for row in observed], [0, 0])
        self.assertEqual([row["energy_payment"]["change_signed"] for row in observed], [-8, 0])
        self.assertEqual([row["damage"] for row in observed], [536, 52])
        for row in observed:
            context = row["context"]
            self.assertNotIn("configurationInference", context["defender"])
            result = quote(7020550, attacker=context["attacker"], defender=context["defender"], slot=3)
            self.assertLessEqual(result["normalMin"], row["damage"])
            self.assertGreaterEqual(result["normalMax"], row["damage"])
            self.assertFalse(result["calibrated"])

    def test_actual_response_damage_inversion_uses_the_same_poison_expression(self):
        from lab.live_battle import _Pet
        from lab.live_inference import damage_observation, _predicted_range
        inside = {"pet_id": 1, "base_conf_id": 3001, "battle_attr": [0, 400, 200, 200, 100, 100, 200]}
        ally = _Pet(side=0, roster_index=0, inside=inside, common={"level": 60})
        enemy = _Pet(side=1, roster_index=0, inside={**inside, "pet_id": 401}, common={"level": 60})
        context = {"attacker": pet(), "defender": pet(battleBuffs=[{"id": 20070010, "layers": 3}])}
        actual = nominal(7120221, 195)
        _, event = damage_observation(enemy, ally, 712022100, actual, False, 1, context=context)
        self.assertNotIn("blocker", event)
        self.assertEqual(_predicted_range(event, 200), (actual, actual))

    def test_per_use_growth_counts_after_attack_survives_switch_and_resets_next_battle(self):
        from lab.live_battle import BattleTracker
        from lab.live_power import source_power
        def record(pid):
            return {"battle_inside_pet_info": {"pet_id": pid, "base_conf_id": 3003,
                "battle_attr": [0, 400, 200, 200, 100, 100, 200],
                "skill_round_data": [{"pos": 1, "skill_id": 7040200}]}, "battle_common_pet_info": {"level": 60}}
        tracker = BattleTracker()
        init = {"init_info": {"battle_id": 1, "player_team": [{"pets": [record(1), record(2)]}],
                              "enemy_team": [{"pets": [record(401)]}]}}
        tracker.handle_event("0x1316", init)
        p = tracker._pet_by_id["1"]
        def power(payload):
            return source_power(payload, pet(), 7040200, {"power": 50, "damageRule": 4})[0]
        self.assertEqual(power(p.to_payload(hide_unobserved=False, observed={})), [50])
        cmd = {"round": 1, "seq_num": 1, "perform_info": [
            {"type": 1, "exec_index": 1, "skill_cast": {"caster_id": 1, "skill_id": 704020000, "skill_name": "吹火"}},
            {"type": 4, "exec_index": 2, "damage_info": {"caster_id": 1, "target_id": 401, "source_id": 704020000},
             "sync_data": {"pet_sync_info": [{"pet_id": 401, "original_damage": 20, "damage_result": 20, "hp_result": 380}]}}]}
        tracker._on_round_start({"state_info": {"round": 1}, "perform_cmd": cmd})
        frozen = tracker.damage_evidence["401"][0]["calculation"]["attacker"]
        self.assertEqual(power(frozen), [50])
        tracker._on_perform({"perform_cmd": cmd})
        self.assertEqual(p.skill_use_counts["7040200"], 1)
        self.assertEqual(len([e for e in tracker.timeline if e["kind"] == "damage"]), 1)
        self.assertEqual(power(p.to_payload(hide_unobserved=False, observed={})), [70])
        tracker._confirm_active(tracker._pet_by_id["2"])
        tracker._confirm_active(p)
        self.assertEqual(power(p.to_payload(hide_unobserved=False, observed={})), [70])
        tracker._on_perform({"perform_cmd": {**cmd, "round": 2, "seq_num": 2}})
        self.assertEqual(power(p.to_payload(hide_unobserved=False, observed={})), [90])
        self.assertEqual(tracker._pet_by_id["401"].skill_use_counts, {})
        tracker.handle_event("0x1316", init)
        self.assertEqual(power(tracker._pet_by_id["1"].to_payload(hide_unobserved=False, observed={})), [50])
        tracker.handle_event("0x1316", {**init, "round": 8})
        with self.assertRaisesRegex(ValueError, "历史不完整"):
            power(tracker._pet_by_id["1"].to_payload(hide_unobserved=False, observed={}))

    def test_history_retains_full_battle_and_attaches_damage_to_hit_not_buff(self):
        from tests.test_live_battle import enter
        from lab.live_battle import BattleTracker
        tracker = BattleTracker(); enter(tracker, 100)
        tracker.timeline.extend({"round": i, "kind": "switch", "side": 1, "petName": "敌方精灵"} for i in range(1, 46))
        tracker._apply_perform_item({"type": 4, "damage_info": {"caster_id": 1, "target_id": 401, "source_id": 704020000},
            "sync_data": {"pet_sync_info": [{"pet_id": 401, "buff_id": 20070010, "buff_stack_result": 1,
                                             "original_damage": 50, "damage_result": 10, "hp_result": 0}]}})
        runtime = tracker.snapshot()["runtime"]
        self.assertGreater(len(runtime["battleHistory"]), 40)
        hit = next(e for e in runtime["battleHistory"] if e["kind"] == "damage")
        self.assertEqual((hit["damage"], hit["damageFinal"], hit["skillName"]), (50, 10, "吹火"))
        self.assertNotIn("damage", next(e for e in tracker.timeline if e["kind"] == "buff"))

    def test_skill_pool_includes_learning_conditions_without_mutating_equipped_skills(self):
        from lab.server import form_skill_pool
        from lab.live_damage import _rules
        catalog, _ = _rules()
        before = deepcopy(catalog["details"]["3003"]["learnset"])
        pool = form_skill_pool(catalog, 3003)
        ids = [s["skillId"] for s in pool["skills"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn(7040200, ids)
        self.assertTrue(any(source.get("bloodline") and source.get("level") is not None
                            for skill in pool["skills"] for source in skill["sources"]))
        self.assertEqual(before, catalog["details"]["3003"]["learnset"])
        with self.assertRaises(ValueError):
            form_skill_pool(catalog, 999999999)


if __name__ == "__main__":
    unittest.main()
