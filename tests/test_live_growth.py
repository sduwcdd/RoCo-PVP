from copy import deepcopy
import unittest

from lab import live_growth
from lab.live_damage import _rules, panel_values
from tests.test_live_power import pet, quote


def late_pet(sid):
    return pet(side=0, petId=1, level=60, carriedSkillIds=[sid, 0, 0, 0],
        skillUseHistoryComplete=False, entryHistoryComplete=False, historyStartRound=10,
        skillUseCounts={str(sid): 0}, conditionalPowerCounts={str(sid): 0},
        observedFirstActions=[0, 0], observedEntryCount=1, responseSuccessCount=0,
        liveContext={'turn': 10}, lastMoveRound=None, observedAttackRounds=[9])


def full_history(sid, count):
    attacker = late_pet(sid)
    attacker.update(skillUseHistoryComplete=True, entryHistoryComplete=True)
    trigger = live_growth.descriptor(sid)['when']
    if trigger == 'after.use':
        attacker['skillUseCounts'][str(sid)] = count
    elif trigger == 'after.use.no_previous_attack':
        attacker['conditionalPowerCounts'][str(sid)] = count
    elif trigger == 'member.enter':
        attacker['entryCount'] = count
    elif trigger == 'carried.action.first':
        attacker['battleBuffs'] = [{'id': 20641660, 'layers': count}]
    elif trigger == 'carried.response.success':
        attacker['responseSuccessCount'] = count
        attacker['responseHistoryComplete'] = True
    else:
        attacker['skillTypeUseCounts'] = {'7030010': {'草系': count}}
    return attacker


def per_hit(result):
    return result.get('perHit', result['perHitMin'])


class LiveGrowthTests(unittest.TestCase):
    def test_known_panels_recover_supported_linear_histories_through_the_shared_formula(self):
        target = pet(side=1, petId=401, level=60)
        for sid, count in [(7040200, 3), (7020400, 3), (7100260, 4), (7110230, 3), (7150350, 4),
                           (7020570, 2), (7030210, 2)]:
            with self.subTest(skill=sid):
                before = late_pet(sid)
                current = deepcopy(before)
                truth = full_history(sid, count)
                damage = per_hit(quote(sid, attacker=truth, defender=target))
                if sid in (7040200, 7020400):
                    current['skillUseCounts'][str(sid)] = 1
                elif sid == 7150350:
                    current['observedFirstActions'] = [1, 0]
                anchor = live_growth.recover(before, target, current, sid, damage)
                self.assertEqual(anchor['damage_counts'], [count, count])
                self.assertFalse(before.get('powerHistoryInference'))
                self.assertFalse(anchor['calibrated'])
                current['powerHistoryInference'] = {str(sid): anchor}
                current.update(lastMoveRound=10, observedAttackRounds=[9, 10])
                next_count = count + (sid in (7040200, 7020400, 7150350))
                expected = per_hit(quote(sid, attacker=full_history(sid, next_count), defender=target))
                recovered = quote(sid, attacker=current, defender=target)
                self.assertEqual((recovered['normalMin'], recovered['normalMax']), (expected, expected))

    def test_unknown_defense_keeps_multiple_compatible_counts(self):
        sid = 7040200
        target = pet(side=1, petId=401, level=60)
        unknown = deepcopy(target)
        unknown['battleStats'].pop('phyDef')
        values, _ = panel_values(unknown, 'phyDef')
        target['battleStats']['phyDef'] = values[len(values)//2]
        damage = per_hit(quote(sid, attacker=full_history(sid, 4), defender=target))
        before = late_pet(sid)
        anchor = live_growth.recover(before, unknown, before, sid, damage)
        self.assertLessEqual(anchor['counts'][0], 4)
        self.assertGreaterEqual(anchor['counts'][1], 4)
        self.assertLess(anchor['counts'][0], anchor['counts'][1])

    def test_recovery_keeps_weather_stats_and_supported_weather_trait_context(self):
        from lab.weather_runtime import observed_weather
        sid = 7110230
        before = late_pet(sid)
        before.update(petBaseId=3343, effectiveTraitId=200311,
            battleBuffs=[{'id': 20010020, 'layers': 2}],
            liveContext={'turn': 10, 'weather': observed_weather(5, 12, 10), 'weatherId': 5})
        target = pet(side=1, level=60, battleBuffs=[{'id': 20010060, 'layers': 3}])
        truth = {**before, 'entryCount': 3, 'entryHistoryComplete': True, 'skillUseHistoryComplete': True}
        damage = per_hit(quote(sid, attacker=truth, defender=target))
        frozen = deepcopy((before, target))
        anchor = live_growth.recover(before, target, before, sid, damage)
        self.assertEqual(anchor['counts'], [3, 3])
        self.assertEqual((before, target), frozen)

    def test_reentry_advances_only_the_observed_increment_and_preserves_missing_origin(self):
        sid, target = 7110230, pet(side=1, level=60)
        before = late_pet(sid)
        damage = per_hit(quote(sid, attacker=full_history(sid, 3), defender=target))
        anchor = live_growth.recover(before, target, before, sid, damage)
        reentered = {**before, 'powerHistoryInference': {str(sid): anchor}, 'observedEntryCount': 2}
        actual = quote(sid, attacker=reentered, defender=target)
        expected = quote(sid, attacker=full_history(sid, 4), defender=target)
        self.assertEqual(actual['normal'], expected['normal'])
        self.assertFalse(reentered['entryHistoryComplete'])
        self.assertNotIn('entryCount', before)

    def test_native_journey_marker_has_priority_over_inferred_history(self):
        sid = 7150350
        attacker = late_pet(sid)
        attacker['battleBuffs'] = [{'id': 20641660, 'layers': 6}]
        result = quote(sid, attacker=attacker)
        self.assertEqual(result['effects'][0]['intrinsic_power_range'], [200, 200])
        self.assertIsNone(live_growth.recover(attacker, pet(), attacker, sid, per_hit(result)))

    def test_zero_conflicting_and_tampered_evidence_does_not_overwrite_an_anchor(self):
        sid, target = 7040200, pet(side=1, level=60)
        before = late_pet(sid)
        damage = per_hit(quote(sid, attacker=full_history(sid, 3), defender=target))
        anchor = live_growth.recover(before, target, before, sid, damage)
        current = {**before, 'powerHistoryInference': {str(sid): anchor}}
        original = deepcopy(current)
        for bad in (0, 1):
            with self.assertRaises(ValueError):
                live_growth.recover(before, target, current, sid, bad)
        self.assertEqual(current, original)
        current = deepcopy(current)
        current['powerHistoryInference'][str(sid)]['binding']['history_hash'] = 'changed'
        result = quote(sid, attacker=current, defender=target)
        self.assertIn('来源已变化', result['reason'])
        query = {**live_growth.descriptor(sid), 'counts': [3, 3], 'history_hash': 'changed'}
        result = quote(sid, attacker={**before, '_growthQuery': query}, defender=target)
        self.assertIn('规则来源已变化', result['reason'])

    def test_tracker_learns_from_a_real_per_hit_notification_and_keeps_next_use_growth(self):
        from lab.live_battle import BattleTracker
        from lab.live_stat_model import stat_candidates
        sid = 7040200
        race = _rules()[1].form(3080)['stats']
        model = {'petBaseId': 3080, 'level': 60}
        stats = [stat_candidates(model, race, dim, 10 if dim in ('hp', 'pdef', 'mdef') else 0,
                                'patk', 'matk', 5)[0] for dim in ('hp','patk','matk','pdef','mdef','spd')]
        def record(pid, enemy):
            return {'battle_inside_pet_info': {'pet_id': pid, 'base_conf_id': 3080, 'conf_id': 3080,
                'pos': 1, 'is_player_enemy': enemy, 'battle_attr': [0, *stats],
                'skill_round_data': [{'pos': 1, 'skill_id': sid}]},
                'battle_common_pet_info': {'level': 60, 'nature': 2, 'energy': 10,
                    'changed_nature_pos_attr_type': 0, 'changed_nature_neg_attr_type': 0}}
        enter = {'round': 10, 'init_info': {'battle_id': 8201, 'observe_battle': {'is_observer': True},
            'player_team': [{'base': {'role_uin': 1}, 'pets': [record(1, False)]}],
            'enemy_team': [{'base': {'role_uin': 2}, 'pets': [record(401, True)]}]}}
        tracker = BattleTracker()
        tracker.handle_event('0x1316', enter)
        attacker = tracker._pet_by_id['1'].to_payload(hide_unobserved=False, observed={})
        target = tracker._pet_by_id['401'].to_payload(hide_unobserved=True, observed={})
        truth = {**attacker, 'skillUseHistoryComplete': True, 'skillUseCounts': {str(sid): 3}}
        damage = per_hit(quote(sid, attacker=truth, defender=target))
        performed = {'perform_cmd': {'round': 10, 'seq_num': 1, 'perform_info': [
            {'type': 1, 'exec_index': 0, 'cast_moment': 0, 'is_group_head': True, 'group_ref': 0,
             'skill_cast': {'caster_id': 1, 'skill_id': sid*100, 'skill_name': '吹火', 'type': 1}},
            {'type': 4, 'exec_index': 1, 'damage_info': {'caster_id': 1, 'target_id': 401,
                'source_id': sid*100, 'is_hit': True, 'is_critical': [False]},
             'sync_data': {'pet_sync_info': [{'pet_id': 401, 'original_damage': damage,
                'damage_result': damage, 'hp_result': stats[0]-damage}]}}]}}
        tracker.handle_event('0x1324', performed)
        owned = tracker._pet_by_id['1']
        self.assertIn(str(sid), owned.power_history_inference, owned.power_history_issues)
        self.assertEqual(owned.power_history_inference[str(sid)]['counts'], [4, 4])
        snapshot = tracker.snapshot()['runtime']
        move = snapshot['myTeam'][0]['moves'][0]
        expected = per_hit(quote(sid, attacker={**truth, 'skillUseCounts': {str(sid): 4}}, defender=target))
        self.assertEqual(move.get('damageNormal', move.get('damageNormalMin')), expected)
        tracker.handle_event('0x1324', deepcopy(performed))
        self.assertEqual(owned.skill_use_counts[str(sid)], 1)
        self.assertEqual(owned.power_history_inference[str(sid)]['counts'], [4, 4])
        tracker.handle_event('0x131A', {'state_info': {'round': 11}})
        self.assertEqual(tracker._pet_by_id['1'].power_history_inference[str(sid)]['counts'], [4, 4])
        tracker.handle_event('0x1316', {**enter, 'init_info': {**enter['init_info'], 'battle_id': 8202}})
        self.assertEqual(tracker._pet_by_id['1'].power_history_inference, {})


if __name__ == '__main__':
    unittest.main()
