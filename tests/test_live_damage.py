import unittest
from unittest.mock import patch

from lab.live_damage import panel_from_hit, estimate_incoming, estimate_moves, panel_values, stat_summary
from lab.numeric_candidates import arena_documented_damage60, arena_stat60


class LiveDamageTests(unittest.TestCase):
    def listening_fixture(self):
        from tests.test_live_power import pet
        own = pet(petId=1, rosterIndex=0, moves=[{'slot': 4, 'skillId': 7140190}])
        enemy = pet(petId=401, rosterIndex=0, moves=[{'slot': 1, 'skillId': 7020410},
                    {'slot': 2, 'skillId': 7020570}, {'slot': 3, 'skillId': 7020690}],
                    responseSuccessCount=2, responseHistoryComplete=True,
                    carriedSkillIds=[7020410, 7020570, 7020690, 0])
        snapshot = {'runtime': {'sessionId': 'bridge', 'snapshotToken': 'now',
            'myTeam': [own], 'enemyTeam': [enemy],
            'active': {'my': {'rosterIndex': 0}, 'enemy': {'rosterIndex': 0}}}}
        request = {'sessionId': 'bridge', 'snapshotToken': 'now', 'side': 'my', 'actorPetId': 1,
                   'targetPetId': 401, 'skillId': 7140190, 'slot': 4, 'previewMode': 'listening'}
        return snapshot, request

    def test_listening_uses_selected_dynamic_power_and_own_physical_panel_without_mutating_snapshot(self):
        from copy import deepcopy
        from lab.live_damage import preview_target
        snapshot, request = self.listening_fixture()
        before = deepcopy(snapshot)
        self.assertTrue(estimate_moves(snapshot['runtime']['myTeam'][0], snapshot['runtime']['enemyTeam'][0])[0]['counterPreview'])
        for sid, power in ((7020410, 130), (7020570, 260)):
            result = preview_target(snapshot, {**request, 'counterSkillId': sid})
            estimate = result['estimate']
            from lab.live_damage import _skill_math_one
            ratio = _skill_math_one(7140191, 3001, 3001, preview_power=power)
            expected = arena_documented_damage60(200, 100, power, ratio['combined'])['nominal_damage']
            self.assertEqual(result['copiedPowerRange'], [power, power])
            self.assertEqual(estimate['normal'], expected)
            self.assertEqual(estimate['branches'][0]['attackStat'], 'phyAtk')
            self.assertEqual(estimate['branches'][0]['defenseStat'], 'phyDef')
            self.assertEqual(estimate['hits'], 1)
        self.assertEqual(snapshot, before)
        snapshot['runtime']['enemyTeam'][0]['responseHistoryComplete'] = False
        snapshot['runtime']['enemyTeam'][0]['historyIncompleteReason'] = '中途观战（第10回合接入）'
        with self.assertRaisesRegex(ValueError, '应对历史不完整'):
            preview_target(snapshot, {**request, 'counterSkillId': 7020570})

    def test_listening_options_reject_hidden_skills_stale_states_and_inapplicable_wish_groups(self):
        from lab.live_damage import preview_target
        snapshot, request = self.listening_fixture()
        menu = preview_target(snapshot, request)
        self.assertEqual(len(menu['counterOptions']), 7)
        self.assertEqual([r['label'] for r in menu['counterOptions'] if r['value'].startswith('wish:')],
                         ['愿力冲击·抵抗', '愿力冲击·正常', '愿力冲击·克制', '愿力冲击·3倍克制'])
        for option in menu['counterOptions']:
            if not option['value'].startswith('wish:'):
                continue
            group = option['value'][5:]
            if option['disabled']:
                with self.assertRaisesRegex(ValueError, '没有该档'):
                    preview_target(snapshot, {**request, 'counterWishGroup': group})
            else:
                result = preview_target(snapshot, {**request, 'counterWishGroup': group})
                self.assertEqual(result['copiedPowerRange'], [80, 80])
        for changes, error in (({'counterSkillId': 7060200}, '已经携带或观测'),
                               ({'snapshotToken': 'old'}, '状态已更新'),
                               ({'counterSkillId': 7020690}, '攻击技能')):
            with self.assertRaisesRegex(ValueError, error):
                preview_target(snapshot, {**request, **changes})

    def test_tailwind_scenarios_are_separate_on_both_hud_sides_and_keep_existing_bounds(self):
        from copy import deepcopy
        from tests.test_live_power import pet
        from lab.live_battle import BattleTracker
        own = pet(petBaseId=3037, effectiveTraitId=200124, moves=[{'slot': 1, 'skillId': 7020410}])
        before = deepcopy(own)
        for native_buffs in ([], [{'id': 20210050, 'layers': 1}]):
            result = estimate_moves({**own, 'battleBuffs': native_buffs}, pet())[0]
            low, high = result['traitScenarios']
            self.assertEqual([low['triggered'], high['triggered']], [False, True])
            self.assertEqual(low['branches'][0]['powerRange'], [130, 130])
            self.assertEqual(high['branches'][0]['powerRange'], [195, 195])
            self.assertEqual((result['normalMin'], result['normalMax']), (low['normalMin'], high['normalMax']))
            self.assertNotIn('traitScenarios', low)
        self.assertEqual(own, before)
        def record(pid, form):
            return {'battle_inside_pet_info': {'pet_id': pid, 'base_conf_id': form, 'pos': 1,
                'battle_attr': [0, 400, 200, 200, 100, 100, 200],
                'skill_round_data': [{'pos': 1, 'skill_id': 7020410}]}, 'battle_common_pet_info': {'level': 60}}
        tracker = BattleTracker()
        tracker.handle_event('0x1316', {'init_info': {'battle_id': 1,
            'player_team': [{'pets': [record(1, 3037)]}], 'enemy_team': [{'pets': [record(401, 3285)]}]}})
        tracker._apply_perform_item({'skill_cast': {'caster_id': 401, 'skill_id': 702041000}})
        runtime = tracker.snapshot()['runtime']
        for side in ('myTeam', 'enemyTeam'):
            branches = runtime[side][0]['moves'][0]['damageTraitScenarios']
            self.assertEqual([b['label'] for b in branches], ['未触发顺风', '触发顺风'])

    def test_conflicting_configuration_blocks_unknown_panel_but_preserves_server_panel(self):
        pet = {"petBaseId": 3412, "level": 60, "nature": 10,
               "configurationInference": {"status": "model_mismatch"}}
        with self.assertRaisesRegex(ValueError, "冲突"):
            panel_values(pet, "phyDef")
        values, source = panel_values({**pet, "battleStats": {"phyDef": 136}}, "phyDef")
        self.assertEqual(values, [136])
        self.assertEqual(source, "实时面板")

    def test_enemy_summary_keeps_species_values_separate_from_all_six_panel_ranges(self):
        race = {"hp": 100, "patk": 90, "matk": 80, "pdef": 70, "mdef": 60, "spd": 50}
        pet = {"petBaseId": 3001, "level": 60, "natureUp": "patk", "natureDown": "matk"}
        with patch("lab.live_damage._race_stats", return_value=(race, "BWIKI种族值")), patch("lab.live_damage.nature_info", return_value={}):
            result = stat_summary(pet)
        self.assertEqual(len(result["raceStats"]), 6)
        self.assertEqual(result["raceStats"]["phyAtk"], 90)
        self.assertEqual(len(result["panelStatRanges"]), 6)
        for lo, hi in result["panelStatRanges"].values():
            self.assertGreater(lo, 0); self.assertLess(lo, hi)
        self.assertEqual(pet.get("battleStats"), None)
        self.assertEqual(result["panelStatRanges"]["phyAtk"], [arena_stat60(90, 0, 1.2, "patk")["stat_value"], arena_stat60(90, 60, 1.2, "patk")["stat_value"]])

    def test_enemy_summary_keeps_unknown_lower_level_panels_unresolved(self):
        with patch("lab.live_damage._race_stats", return_value=({"hp": 100}, "BWIKI种族值")), patch("lab.live_damage.nature_info", return_value={}):
            result = stat_summary({"petBaseId": 3001, "level": 30})
        self.assertEqual(result["raceStats"], {"hp": 100})
        self.assertEqual(result["panelStatRanges"], {})
        self.assertEqual(len(result["panelStatIssues"]), 6)

    def test_resolved_response_and_dynamic_power_are_not_reused_for_next_turn(self):
        attacker = {"battleStats": {"phyAtk": 200}, "moves": [{"slot": 1, "skillId": 123}]}
        defender = {"battleStats": {"phyDef": 150}}
        for extra, reason in (({"resolvedVariant": True}, "应对"), ({"damageRule": 12}, "动态伤害规则")):
            profile = {"kind": "physical", "power": 160, "combined": 1.25, "hits": 1, **extra}
            with self.subTest(extra=extra), patch("lab.live_damage._skill_damage_profile", return_value=profile):
                result = estimate_incoming(attacker, defender)[0]
            self.assertIn(reason, result["reason"])
            self.assertNotIn("normal", result)
            self.assertNotIn("normalMax", result)

    def test_both_unknown_panels_include_all_nature_and_talent_extrema(self):
        profile = {"kind": "physical", "power": 80, "combined": 1.25, "multiplier": 1, "stab": 1.25, "hits": 3}
        attacker = {"petBaseId": 3001, "level": 60, "moves": [{"slot": 1, "skillId": 123}]}
        defender = {"petBaseId": 3002, "level": 60}
        with patch("lab.live_damage._skill_damage_profile", return_value=profile), patch("lab.live_damage._race_stats", return_value=({"patk": 100, "pdef": 100}, "BWIKI种族值")), patch("lab.live_damage.nature_info", return_value={}):
            result = estimate_moves(attacker, defender)[0]
        lower = arena_stat60(100, 0, .9, "patk")["stat_value"]
        upper = arena_stat60(100, 60, 1.2, "patk")["stat_value"]
        self.assertEqual(result["normalMin"], arena_documented_damage60(lower, upper, 80, 1.25)["nominal_damage"] * 3)
        self.assertEqual(result["normalMax"], arena_documented_damage60(upper, lower, 80, 1.25)["nominal_damage"] * 3)
        self.assertFalse(result["exact"])
        self.assertNotIn("normal", result)

    def test_known_direction_and_individual_collapse_species_calculation(self):
        pet = {"petBaseId": 3001, "level": 60, "natureUp": "patk", "natureDown": "matk",
               "talent_selection": {"selected": ["hp", "patk", "spd"], "values": {"hp": 10, "patk": 7, "spd": 10}}}
        with patch("lab.live_damage._race_stats", return_value=({"patk": 100, "pdef": 100}, "BWIKI种族值")), patch("lab.live_damage.nature_info", return_value={}):
            values, _ = panel_values(pet, "phyAtk")
            defense, _ = panel_values(pet, "phyDef")
        self.assertEqual(values, [arena_stat60(100, 42, 1.2, "patk")["stat_value"]])
        self.assertEqual(defense, [arena_stat60(100, 0, 1, "pdef")["stat_value"]])

    def test_inferred_midpoint_does_not_become_an_exact_panel(self):
        pet = {"battleStats": {"phyDef": 150}, "battleStatsEstimated": {"phyDef": 150}, "battleStatsRanges": {"phyDef": [140, 160]}}
        values, _ = panel_values(pet, "phyDef")
        self.assertEqual(values, [140, 160])

    def test_higher_attack_uses_corresponding_defense(self):
        profile = {"kind": "higher", "power": 80, "combined": 1.25, "multiplier": 1, "stab": 1.25, "hits": 1}
        attacker = {"battleStats": {"phyAtk": 100, "magAtk": 200}, "moves": [{"slot": 1, "skillId": 123}]}
        defender = {"battleStats": {"phyDef": 400, "magDef": 100}}
        with patch("lab.live_damage._skill_damage_profile", return_value=profile):
            result = estimate_moves(attacker, defender)[0]
        self.assertTrue(result["exact"])
        self.assertEqual(result["normal"], arena_documented_damage60(200, 100, 80, 1.25)["nominal_damage"])

    def test_inverse_integer_attack_interval_matches_forward_rounding(self):
        for attack, defense, power, combined in [(213, 149, 80, 1.25), (75, 259, 30, 2), (501, 111, 50, .5)]:
            damage = arena_documented_damage60(attack, defense, power, combined)["nominal_damage"]
            result = panel_from_hit(defense=defense, power=power, combined=combined, damage=damage)
            self.assertLessEqual(result["attackLow"], attack)
            self.assertGreaterEqual(result["attackHigh"], attack)
            for value in range(result["attackLow"], result["attackHigh"] + 1):
                self.assertEqual(arena_documented_damage60(value, defense, power, combined)["nominal_damage"], damage)

    def test_live_preview_has_critical_field_and_marks_uncalibrated(self):
        profile = {"kind": "physical", "power": 80, "combined": 1.25, "multiplier": 1, "stab": 1.25, "hits": 2}
        attacker = {"petBaseId": 3001, "battleStats": {"phyAtk": 213}, "moves": [{"slot": 1, "skillId": 123}]}
        defender = {"petBaseId": 3002, "battleStats": {"phyDef": 149}, "maxHp": 400, "currentHp": 300}
        with patch("lab.live_damage._skill_damage_profile", return_value=profile):
            result = estimate_incoming(attacker, defender)[0]
        self.assertIn("critical", result)
        self.assertGreaterEqual(result["critical"], result["normal"])
        self.assertFalse(result["calibrated"])


if __name__ == "__main__":
    unittest.main()
