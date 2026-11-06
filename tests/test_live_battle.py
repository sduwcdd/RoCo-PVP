"""Battle-local evidence isolation and single-segment damage regression tests."""
import unittest
import json
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch

from lab.live_battle import BattleTracker, LiveBattleFeed, _Pet, _execution_order


class PhysicalDisplayTests(unittest.TestCase):
    def test_captured_whale_units_prediction_and_confirmed_medal(self):
        from lab.battle_data import physical_info
        result = physical_info(3381, height=201, weight=645412, voice=48)
        self.assertEqual(result['height']['text'], '2.01米')
        self.assertEqual(result['weight']['text'], '645.41千克')
        self.assertEqual(result['voice']['text'], '+48')
        self.assertEqual([(m['name'], m['status']) for m in result['medals']], [('小不点', 'predicted')])
        confirmed = physical_info(3381, height=201, weight=645412, voice=48, worn_medal_id=1002)
        self.assertEqual(confirmed['medals'][0]['status'], 'confirmed')
        self.assertEqual(len(confirmed['medals']), 1)

    def test_voice_sign_boundary_and_absent_data(self):
        from lab.battle_data import physical_info
        result = physical_info(None, voice=str(2**64 - 98))
        self.assertEqual(result['voice']['text'], '-98')
        self.assertEqual(result['medals'][0]['name'], '粗嗓门')
        self.assertEqual(physical_info(None, voice=96)['medals'][0]['status'], 'boundary')
        self.assertEqual(physical_info(None, voice=97)['medals'][0]['status'], 'predicted')
        with patch('lab.battle_data._pet_record', return_value={'height_low': 200, 'height_high': 300}):
            self.assertEqual(physical_info(3381, height=202)['medals'][0]['status'], 'boundary')
            self.assertEqual(physical_info(3381, height=301)['medals'], [])
        self.assertEqual(physical_info(None, height=True, weight=-1, voice='bad'), {'medals': []})
        self.assertEqual(physical_info(None, voice=0)['voice']['text'], '0')

    def test_partial_update_preserves_physical_fields_without_cross_pet_leakage(self):
        record = pet_record(401, 3381, enemy=True)
        pet = _Pet(side=1, roster_index=0, inside=record['battle_inside_pet_info'],
                   common={'height': 201, 'weight': 645412, 'voice': 48})
        pet.refresh_stats({}, {})
        first = pet.to_payload(hide_unobserved=True, observed={})['physical']
        first['medals'].clear()
        self.assertEqual(len(pet.to_payload(hide_unobserved=True, observed={})['physical']['medals']), 1)
        pet.refresh_stats({}, {'voice': 0})
        self.assertEqual(pet.to_payload(hide_unobserved=True, observed={})['physical']['voice']['text'], '0')
        other = _Pet(side=0, roster_index=0, inside=record['battle_inside_pet_info'], common={})
        self.assertEqual(other.to_payload(hide_unobserved=False, observed={})['physical'], {'medals': []})


class SpecialityDisplayTests(unittest.TestCase):
    def test_protocol_speciality_survives_partial_updates_and_is_isolated(self):
        record = pet_record(401, 3002, enemy=True)
        common = {**record['battle_common_pet_info'], 'speciality_id': 104,
                  'real_speciality_ids': [105, 106]}
        pet = _Pet(side=1, roster_index=0, inside=record['battle_inside_pet_info'], common=common)
        common['real_speciality_ids'].append(401)
        pet.refresh_stats({}, {})
        first = pet.to_payload(hide_unobserved=True, observed={})['speciality']
        self.assertEqual((first['name'], first['realIds']), ('灵巧', [105, 106]))
        first['realIds'].append(402)
        self.assertEqual(pet.real_speciality_ids, [105, 106])
        pet.refresh_stats({}, {'speciality_id': 402})
        updated = pet.to_payload(hide_unobserved=True, observed={})['speciality']
        self.assertEqual(updated['name'], '同乘')
        self.assertIsNone(updated['realIds'])
        other = _Pet(side=0, roster_index=0, inside=record['battle_inside_pet_info'], common={})
        self.assertFalse(other.to_payload(hide_unobserved=False, observed={})['speciality'].get('confirmed'))
        pet.refresh_stats({}, {'speciality_id': 0})
        self.assertFalse(pet.to_payload(hide_unobserved=True, observed={})['speciality'].get('confirmed'))

    def test_definition_ids_and_unknown_values_do_not_invent_none(self):
        from lab import battle_data
        for value in (None, 0, -1, True, '101'):
            self.assertEqual(battle_data.speciality_info(value), {})
        for value, name in ((1, '无'), (101, '奇袭'), (401, '疾行'), (402, '同乘')):
            self.assertEqual(battle_data.speciality_info(value)['name'], name)
        self.assertIsNone(battle_data.speciality_info(999999)['name'])
        with patch('lab.battle_data._specialities', side_effect=ValueError('changed source')):
            self.assertIn('mappingIssue', battle_data.speciality_info(101))


def pet_record(pet_id, base, *, enemy=False):
    return {"battle_inside_pet_info": {
        "pet_id": pet_id, "base_conf_id": base, "conf_id": base,
        "is_player_enemy": enemy, "battle_attr": [0, 454, 0, 0, 0, 0, 0],
        "skill_round_data": [{"pos": 1, "skill_id": 7040370, "skill_name": "火焰箭"}],
    }, "battle_common_pet_info": {"level": 60, "energy": 10}}


def enter(tracker, battle_id, base=3602):
    return tracker.handle_event("0x1316", {"init_info": {
        "battle_id": battle_id,
        "player_team": [{"base": {"role_uin": 1}, "pets": [pet_record(1, 3463)]}],
        "enemy_team": [{"base": {"role_uin": 2}, "pets": [pet_record(401, base, enemy=True)]}],
    }})


def cast(tracker, pet_id=401, skill=704037000, name="火焰箭"):
    tracker.handle_event("0x1324", {"perform_cmd": {"round": 1, "perform_info": [
        {"skill_cast": {"caster_id": pet_id, "skill_id": skill, "skill_name": name}},
    ]}})


class LiveBattleEvidenceTests(unittest.TestCase):
    def test_knockout_keeps_both_last_live_forecasts_without_reusing_other_matchups(self):
        tracker = BattleTracker()
        enter(tracker, 918)
        cast(tracker)
        for member in tracker._pet_by_id.values():
            member.attr_stats.update(phyAtk=200, magAtk=200, phyDef=100, magDef=100)
        before = tracker.snapshot()['runtime']
        quotes = [before[key][0]['moves'][0]['damageNormalMin'] if 'damageNormalMin' in before[key][0]['moves'][0]
                  else before[key][0]['moves'][0]['damageNormal'] for key in ('myTeam', 'enemyTeam')]
        tracker._pet_by_id['1'].apply_hp(0, 'test knockout')
        after = tracker.snapshot()['runtime']
        for key, expected in zip(('myTeam', 'enemyTeam'), quotes):
            move = after[key][0]['moves'][0]
            self.assertTrue(move['damageBeforeKnockout'])
            self.assertEqual(move.get('damageNormalMin', move.get('damageNormal')), expected)
            self.assertNotIn('damageNote', move)
            self.assertNotIn('oneShot', move)
        self.assertEqual(tracker.snapshot()['runtime']['myTeam'][0]['moves'][0], after['myTeam'][0]['moves'][0])
        tracker._pet_by_id['401'].base_conf_id = 3001
        changed = tracker.snapshot()['runtime']['myTeam'][0]['moves'][0]
        self.assertNotIn('damageBeforeKnockout', changed)
        tracker.reset()
        self.assertIsNone(tracker._last_live_damage_preview)

    def test_consumed_heat_up_belongs_to_one_observation_not_future_state(self):
        for method in ("_on_perform", "_on_round_start"):
            for triggered in (True, False):
                with self.subTest(method=method, triggered=triggered):
                    tracker = BattleTracker()
                    enter(tracker, 901)
                    attacker = tracker._pet_by_id["1"]
                    attacker.set_buff(20230350, 1, "热身")
                    hit = {"type": 4, "damage_info": {"caster_id": 1, "target_id": 401,
                        "source_id": 715021000, "is_hit": True, "is_critical": [False]},
                        "sync_data": {"pet_sync_info": [{"pet_id": 401, "original_damage": 100}]}}
                    items = [
                        {"skill_cast": {"caster_id": 1, "skill_id": 715021000, "skill_name": "风矢", "target_id": [401]}},
                        {"buff_change": {"target_id": 1, "buff_id": 20230350, "type": 3}},
                        {"buff_change": {"target_id": 1, "buff_id": 20010010, "type": 1, "buff_info": {"stack": 2}}},
                        hit, deepcopy(hit)]
                    if triggered:
                        items.append({"buff_trigger": {"caster_id": 1, "buff_id": 20230350}})
                    with patch.object(tracker, "_learn_panel") as learned:
                        getattr(tracker, method)({"perform_cmd": {"round": 1, "perform_info": items}})
                    contexts = [call.kwargs["observation_context"] for call in learned.call_args_list]
                    first = {b["id"] for b in contexts[0]["attacker"]["battleBuffs"]}
                    self.assertEqual(20230350 in first, triggered)
                    self.assertIn(20010010, first)  # Newly applied effects still use current state.
                    self.assertNotIn(20230350, {b["id"] for b in contexts[1]["attacker"]["battleBuffs"]})
                    self.assertNotIn(20230350, {b["id"] for b in attacker.buffs})
                    event = next(e for e in tracker.timeline if e["kind"] == "damage")
                    self.assertNotIn("castEstimate", event)  # Deliberately incompatible test panels cannot invent a quote.

    def test_frozen_hp_uses_server_threshold_preserves_partial_updates_and_clears_zero(self):
        tracker = BattleTracker()
        own, enemy = pet_record(1, 3001), pet_record(401, 3002, enemy=True)
        own['battle_inside_pet_info'].update(kill_info={'kill_at_hp': 138},
            battle_attr=[0, 461] + [0] * 23 + [337])
        tracker.handle_event('0x1316', {'init_info': {'battle_id': 10,
            'player_team': [{'pets': [own]}], 'enemy_team': [{'pets': [enemy]}]}})
        member = tracker._pet_by_id['1']
        self.assertEqual(member.to_payload(hide_unobserved=False, observed={})['frozenHp'], 138)
        self.assertEqual(tracker._pet_by_id['401'].frozen_hp, 0)
        member.refresh_stats({'battle_attr': [0, 500]}, {})
        self.assertEqual(member.frozen_hp, 138)  # Missing fields do not clear a known threshold.
        tracker._apply_perform_item({'data_update': {'pet': {'battle_inside_pet_info': {
            'pet_id': 1, 'kill_info': {'kill_at_hp': 137}}}}})
        self.assertEqual(member.frozen_hp, 137)  # Never recompute from BUFF layers.
        tracker._apply_perform_item({'sync_data': {'pet_sync_info': [
            {'pet_id': 1, 'kill_info': {'kill_at_hp': 0}}]}})
        self.assertEqual(member.frozen_hp, 0)
        tracker.handle_event('0x1316', {'init_info': {'battle_id': 11,
            'player_team': [{'pets': [pet_record(1, 3001)]}]}})
        self.assertEqual(tracker._pet_by_id['1'].frozen_hp, 0)

    def test_execution_indices_order_nested_effects_without_guessing_missing_indices(self):
        items = [{"exec_index": 255}, {"exec_index": 41}, {"exec_index": 62}]
        self.assertEqual([i["exec_index"] for i in _execution_order(items)], [41, 62, 255])
        self.assertEqual(items[0]["exec_index"], 255)  # Preserve the captured packet.
        for incomplete in ([{}, {"exec_index": 1}], [{"exec_index": 1}, {"exec_index": 1}]):
            self.assertIs(_execution_order(incomplete), incomplete)

    def test_real_chase_keeps_magic_buff_until_after_six_hits_then_dispels_it(self):
        from lab.live_inference import infer_configuration
        from lab.live_damage import estimate_moves
        fixture = json.loads((Path(__file__).resolve().parents[1] /
                              "data/reference/live-chase-20261029.json").read_text(encoding="utf-8"))
        for method in ("_on_perform", "_on_round_start"):
            with self.subTest(method=method):
                tracker = BattleTracker()
                context = fixture["ordered_context"]
                def record(side):
                    p = context[side]
                    stats = p["battleStats"]
                    return {"battle_inside_pet_info": {
                        "pet_id": p["petId"], "base_conf_id": p["petBaseId"],
                        "battle_attr": [0] + [stats[k] for k in ("hp", "phyAtk", "magAtk", "phyDef", "magDef", "spd")]
                    }, "battle_common_pet_info": {"level": 60, "nature": p["nature"]}}
                tracker.handle_event("0x1316", {"init_info": {"battle_id": 1,
                    "player_team": [{"pets": [record("defender")]}],
                    "enemy_team": [{"pets": [record("attacker")]}]}})
                for side in ("attacker", "defender"):
                    tracker._pet_by_id[str(context[side]["petId"])].buffs = deepcopy(fixture["before_buffs"][side])
                getattr(tracker, method)({"perform_cmd": {"round": 5, "perform_info": deepcopy(fixture["perform_info"])}})
                enemy = tracker._pet_by_id["406"]
                events = tracker.damage_evidence["406"]
                self.assertTrue(events)
                self.assertTrue(all(e["damage"] == 59 for e in events))
                captured = events[0]["calculation"]
                buffs = {b["id"]: b["layers"] for b in captured["attacker"]["battleBuffs"]}
                self.assertEqual((buffs[20010020], buffs[20230440]), (4, 2))
                self.assertNotIn(20010020, {b["id"] for b in enemy.buffs})
                result = infer_configuration(enemy.to_payload(hide_unobserved=True, observed={}), events)
                self.assertEqual(result["status"], "conditional")
                self.assertEqual(result["panel_ranges"]["magAtk"], [214, 214])
                attacker = deepcopy(captured["attacker"])
                attacker["battleStats"]["magAtk"] = 214
                attacker["battleStatsBasis"] = "natured_base"
                attacker["moves"] = [{"slot": 1, "skillId": 7020470}]
                preview = estimate_moves(attacker, captured["defender"])[0]
                self.assertEqual(preview["perHit"], 59)
                self.assertEqual(preview["branches"][0]["powerRange"], [95, 95])

    def test_spectator_current_hp_uses_attr25_not_max_hp(self):
        record=pet_record(405,3080,enemy=True)
        record["battle_inside_pet_info"]["battle_attr"]=[0,354]+[0]*23+[1]
        tracker=BattleTracker()
        tracker.handle_event("0x1316",{"round":17,"init_info":{"battle_id":900,"observe_battle":{"is_observer":True},
            "enemy_team":[{"pets":[record]}]}})
        p=tracker._pet_by_id["405"]
        self.assertEqual((p.hp,p.max_hp,p.hp_percent()),(1,354,1))
        self.assertEqual(p.hp_source,"battle_attr[25]")

    def test_known_switch_refreshes_hp_from_full_record_and_missing_field_keeps_last_hp(self):
        tracker=BattleTracker();enter(tracker,100)
        record=pet_record(401,3080,enemy=True)
        record["battle_inside_pet_info"]["battle_attr"]=[0,354]+[0]*23+[1]
        tracker._apply_perform_item({"change_pet":{"battle_pet_id":401,"battle_pet_info":record}})
        p=tracker._pet_by_id["401"]
        self.assertEqual((p.hp,p.max_hp),(1,354))
        p.refresh_stats({"battle_attr":[0,354,0,0,0,0,0]}, {})
        self.assertEqual(p.hp,1)
        record["battle_inside_pet_info"]["battle_attr"][25]=0
        tracker._apply_perform_item({"supply_pet":{"pet_infos":[{"pet_id":401,"pet_pos":1,"pet_info":record}]}})
        self.assertEqual(p.hp,0)
        self.assertFalse(p.alive)

    def test_missing_mid_battle_hp_stays_unknown_and_full_round_header_refreshes_it(self):
        tracker=BattleTracker();enter(tracker,100)
        record=pet_record(402,3080,enemy=True)
        tracker._absorb_pets(record)
        p=tracker._pet_by_id["402"]
        self.assertIsNone(p.hp)
        self.assertIsNone(p.hp_percent())
        record["battle_inside_pet_info"]["battle_attr"]=[0,354]+[0]*23+[73]
        tracker._on_round_start({"state_info":{"round":2},"pet_infos":[record]})
        self.assertEqual((p.hp,p.max_hp),(73,354))

    def test_redacted_next_round_panels_do_not_erase_revealed_base_stat_evidence(self):
        record=pet_record(401,3080,enemy=True)
        inside=record["battle_inside_pet_info"]
        inside["battle_attr"]=[0,400,200,120,150,170,180]
        p=_Pet(side=1,roster_index=0,inside=inside,common={"level":60,"nature":2})
        p.refresh_stats({"battle_attr":[0,400,0,0,0,0,0]}, {})
        data=p.to_payload(hide_unobserved=True,observed={})
        self.assertEqual(data["battleStats"]["magDef"],0)  # Raw hidden fields stay raw.
        self.assertEqual(data["revealedBaseStats"]["magDef"],170)
        p.refresh_stats({}, {"nature":21})
        self.assertNotIn("magDef",p.to_payload(hide_unobserved=True,observed={})["revealedBaseStats"])

    def test_own_resolved_variant_uses_normal_name_without_mutating_captured_slot(self):
        tracker = BattleTracker(); enter(tracker, 100)
        own = tracker._pet_by_id["1"]
        own.skills[0].update(skill_id=7080331, skillId=7080331, skillName="应对！地陷", name="应对！地陷")
        payload = own.to_payload(hide_unobserved=False, observed={})
        self.assertEqual(payload["moves"][0]["skillId"], 7080330)
        self.assertEqual(payload["moves"][0]["skillName"], "地陷")
        self.assertEqual(own.skills[0]["skill_id"], 7080331)

    def test_response_variants_share_one_observed_slot_and_keep_raw_cast_evidence(self):
        tracker = BattleTracker(); enter(tracker, 100)
        cast(tracker, 401, 708033100, "应对！地陷")
        cast(tracker, 401, 708033000, "地陷")
        cast(tracker, 401, 704037000, "火焰箭")
        cast(tracker, 401, 706020000, "虹光冲击")
        cast(tracker, 401, 708046000, "沙石阵")
        moves = tracker.snapshot()["runtime"]["enemyTeam"][0]["moves"]
        self.assertEqual(len(moves), 4)
        ground = next(m for m in moves if m["name"] == "地陷")
        self.assertEqual(ground["skillId"], 7080330)
        self.assertEqual(set(ground["observedVariants"]), {708033100, 708033000})
        self.assertIn("沙石阵", [m["name"] for m in moves])
        self.assertTrue(any(r.get("skillId") == 708033100 and r.get("skillName") == "应对！地陷" for r in tracker.timeline))

    def test_weather_cast_updates_both_preview_contexts_and_ticks_once_per_round(self):
        tracker = BattleTracker(); enter(tracker, 100)
        cast(tracker, 1, 705025000, "降雨")
        self.assertEqual(tracker.live_weather["kind"], "rain")
        tracker.handle_event("0x131A", {"state_info": {"battle_id": 100, "round": 2}})
        tracker.handle_event("0x1324", {"perform_cmd": {"round": 2, "perform_info": []}})
        self.assertEqual(tracker.live_weather["remaining_rounds"], 7)
        for key in ("myTeam", "enemyTeam"):
            self.assertEqual(tracker.snapshot()["runtime"][key][0]["liveContext"]["weather"]["kind"], "rain")

    def test_knockout_supply_updates_both_sides_without_casts_or_skill_leaks(self):
        tracker = BattleTracker(); enter(tracker, 100)
        own = pet_record(2, 3225)
        pet = _Pet(side=0, roster_index=1, inside=own["battle_inside_pet_info"], common=own["battle_common_pet_info"])
        tracker.teams[0].append(pet); tracker._pet_by_id["2"] = pet
        tracker.handle_event("0x1324", {"perform_cmd": {"round": 2, "perform_info": [
            {"type": 37, "supply_pet": {"player_id": 1, "pet_infos": [{"pet_id": 2, "pet_pos": 1, "pet_info": own}]}},
            {"type": 37, "supply_pet": {"player_id": 2, "pet_infos": [{"pet_id": 402, "pet_pos": 1,
                "pet_info": pet_record(402, 3011, enemy=True)}]}},
        ]}})
        self.assertEqual(tracker.active, {0: 1, 1: 1})
        self.assertEqual(tracker.snapshot()["runtime"]["enemyTeam"][1]["moves"], [])
        cast(tracker, 1)
        self.assertEqual(tracker.active[0], 1)

    def test_full_server_data_update_moves_known_pet_and_ignores_reserve_positions(self):
        tracker = BattleTracker(); enter(tracker, 100)
        tracker._absorb_pets(pet_record(402, 3011, enemy=True))
        active, reserve = pet_record(402, 3011, enemy=True), pet_record(401, 3602, enemy=True)
        active["battle_inside_pet_info"]["pos"] = 1
        reserve["battle_inside_pet_info"]["pos"] = "18446744073709551615"
        tracker._apply_perform_item({"data_update": {"battler": {"pets": [active, reserve]}}})
        self.assertEqual(tracker.active[1], 1)
        active["battle_inside_pet_info"]["pos"] = "18446744073709551615"
        reserve["battle_inside_pet_info"]["pos"] = 1
        tracker._apply_perform_item({"sync_data": {"pet_info": [active, reserve]}})
        self.assertEqual(tracker.active[1], 0)

    def test_restart_replays_retained_entry_before_mid_battle_events(self):
        # Feed retains a complete entry plus a later replacement in the same history window.
        record = pet_record(401, 3602, enemy=True)
        entry = {"init_info": {"battle_id": 100, "enemy_team": [{"pets": [record]}]}}
        supply = {"perform_cmd": {"perform_info": [{"supply_pet": {"pet_infos": [
            {"pet_id": 402, "pet_pos": 1, "pet_info": pet_record(402, 3011, enemy=True)}]}}]}}
        feed = LiveBattleFeed()
        with patch.object(feed, "_get", side_effect=[[
            {"_relay_event_id": 1001, "opencode": "0x1316", "content": entry},
            {"_relay_event_id": 1002, "opencode": "0x1324", "content": supply},
        ], []]) as get:
            self.assertIsNotNone(feed.poll_once())
            feed.poll_once()
        with patch.object(feed.tracker, "snapshot", side_effect=AssertionError("HTTP reads must not recompute")):
            published = feed.snapshot()
            for _ in range(100):
                self.assertIs(feed.snapshot(), published)
        old_hp = published["runtime"]["enemyTeam"][1]["currentHp"]
        feed.tracker._pet_by_id["402"].hp = 1
        self.assertEqual(feed.snapshot()["runtime"]["enemyTeam"][1]["currentHp"], old_hp)
        self.assertGreaterEqual(feed.processing_ms, 0)
        self.assertEqual(feed.tracker.active[1], 1)
        self.assertIn("limit=5000&after=0", get.call_args_list[0].args[0])
        self.assertIn("limit=200&after=1002", get.call_args_list[1].args[0])

    def test_read_query_scope_verifies_sources_once_but_rechecks_the_next_query(self):
        from lab import trait_runtime
        with patch.object(trait_runtime, "_source_hash", wraps=trait_runtime._source_hash) as verify:
            with trait_runtime.query_scope():
                initial = verify.call_count
                self.assertGreater(initial, 0)
                rows = trait_runtime._rows()
                for _ in range(8):
                    self.assertIs(trait_runtime._rows(), rows)
                with trait_runtime.query_scope():
                    self.assertIs(trait_runtime._rows(), rows)
                self.assertEqual(verify.call_count, initial)
            with trait_runtime.query_scope():
                self.assertGreater(verify.call_count, initial)

    def test_entry_uses_field_position_instead_of_first_roster_member(self):
        tracker = BattleTracker()
        first, second = pet_record(1, 3463), pet_record(2, 3225)
        first["battle_inside_pet_info"]["pos"] = "18446744073709551615"
        second["battle_inside_pet_info"]["pos"] = 1
        tracker.handle_event("0x1316", {"init_info": {"battle_id": 100,
            "player_team": [{"pets": [first, second]}]}})
        self.assertEqual(tracker.active[0], 1)
        self.assertEqual(tracker.snapshot()["runtime"]["myTeam"][1]["name"], "古钟蛇")

    def test_known_own_pet_switches_before_it_casts_without_resetting_hp(self):
        tracker = BattleTracker()
        enter(tracker, 100)
        record = pet_record(2, 3225)
        snake = _Pet(side=0, roster_index=1, inside=record["battle_inside_pet_info"], common=record["battle_common_pet_info"])
        snake.apply_hp(366)
        tracker.teams[0].append(snake); tracker._pet_by_id["2"] = snake
        # Client request uses rest_pet_id for the selected reserve; it is not a resolved switch.
        tracker.handle_event("0x1322", {"req": {"change_pet": {"rest_pet_id": 2, "battle_pet_id": 1}}})
        self.assertEqual(tracker.active[0], 0)
        # Resolved notification uses battle_pet_id for New (BattleChangePetPlayer line 27).
        tracker.handle_event("0x1324", {"perform_cmd": {"round": 2, "perform_info": [{"type": 13,
            "change_pet": {"rest_pet_id": "1", "battle_pet_id": "2", "battle_pet_info": record}}]}})
        self.assertEqual(tracker.active[0], 1)
        self.assertEqual(snake.hp, 366)
        self.assertTrue(any(row.get("kind") == "switch" and row.get("petId") == 2 for row in tracker.timeline))
        cast(tracker, 1)  # A late cast by the departed pet must not undo the confirmed switch.
        self.assertEqual(tracker.active[0], 1)

    def test_known_enemy_return_switch_updates_active_and_preserves_its_observations(self):
        tracker = BattleTracker(); enter(tracker, 100); cast(tracker)
        tracker._absorb_pets(pet_record(402, 3011, enemy=True))
        cast(tracker, 402, 705022000, "水泡")
        tracker.handle_event("0x131A", {"state_info": {"battle_id": 100, "round": 2},
            "perform_cmd": {"perform_info": [{"type": 13, "change_pet": {"rest_pet_id": 402, "battle_pet_id": 401}}]}})
        snapshot = tracker.snapshot()["runtime"]
        self.assertEqual(snapshot["active"]["enemy"]["rosterIndex"], 0)
        self.assertEqual(snapshot["observedEnemyMoves"], ["火焰箭"])

    def test_resolved_switches_are_processed_in_order_even_if_new_pets_were_preabsorbed(self):
        tracker = BattleTracker(); enter(tracker, 100)
        tracker.handle_event("0x1324", {"perform_cmd": {"round": 2, "perform_info": [
            {"type": 13, "change_pet": {"rest_pet_id": 401, "battle_pet_id": 402,
                "battle_pet_info": pet_record(402, 3011, enemy=True)}},
            {"type": 13, "change_pet": {"rest_pet_id": 402, "battle_pet_id": 401}},
        ]}})
        self.assertEqual(tracker.active[1], 0)
        self.assertEqual([r["petId"] for r in tracker.timeline if r.get("kind") == "switch"], [402, 401])

    def test_authoritative_position_sync_updates_active_but_reserve_sentinel_does_not(self):
        tracker = BattleTracker(); enter(tracker, 100)
        tracker._absorb_pets(pet_record(402, 3011, enemy=True))
        tracker._apply_perform_item({"sync_data": {"pet_sync_info": [{"pet_id": 402, "pos": 1},
            {"pet_id": 401, "pos": "18446744073709551615"}]}})
        self.assertEqual(tracker.active[1], 1)
        tracker._apply_perform_item({"sync_data": {"pet_sync_info": [{"pet_id": 401, "pos": 1}]}})
        self.assertEqual(tracker.active[1], 0)

    def test_conflicting_switch_ids_are_not_silently_resolved(self):
        tracker = BattleTracker(); enter(tracker, 100)
        tracker.handle_event("0x1324", {"perform_cmd": {"perform_info": [{"change_pet": {
            "battle_pet_id": 401, "battle_pet_info": pet_record(402, 3011, enemy=True)}}]}})
        self.assertFalse(tracker._active_confirmed[1])
        self.assertIn("冲突", tracker.pending_pets[-1]["reason"])

    def test_reused_pet_id_in_new_battle_has_no_old_skills_panels_or_finish(self):
        tracker = BattleTracker()
        enter(tracker, 100)
        cast(tracker)
        tracker._record_panel(401, "magAtk", 764, 760, 770)
        tracker.finished, tracker.result = True, 1
        tracker.active[1] = 4
        tracker._pre_casts.add((1, 401, 704037000, "火焰箭"))
        tracker.buff_names["old"] = "旧状态"
        tracker.damage_evidence["401"] = [{"form_id": 3602, "damage": 50}]
        enter(tracker, 101, base=3011)
        snapshot = tracker.snapshot()["runtime"]
        self.assertEqual(snapshot["enemyTeam"][0]["moves"], [])
        self.assertEqual(snapshot["observedEnemyMoves"], [])
        self.assertEqual(tracker.learned_panels, {})
        self.assertEqual(tracker.learned_panel_ranges, {})
        self.assertEqual(tracker.buff_names, {})
        self.assertEqual(tracker.damage_evidence, {})
        self.assertEqual(tracker._pre_casts, set())
        self.assertFalse(snapshot["finished"])
        self.assertIsNone(snapshot["result"])
        self.assertEqual(snapshot["active"]["enemy"]["rosterIndex"], 0)

    def test_switch_keeps_only_each_pets_own_observed_moves(self):
        tracker = BattleTracker()
        enter(tracker, 100)
        cast(tracker)
        tracker._absorb_pets(pet_record(402, 3011, enemy=True))
        team = tracker.snapshot()["runtime"]["enemyTeam"]
        self.assertEqual(len(team[0]["moves"]), 1)
        self.assertEqual(team[1]["moves"], [])
        cast(tracker, 402, 705022000, "水泡")
        cast(tracker)
        team = tracker.snapshot()["runtime"]["enemyTeam"]
        self.assertEqual([m["name"] for m in team[0]["moves"]], ["火焰箭"])
        self.assertEqual([m["name"] for m in team[1]["moves"]], ["水泡"])

    def test_unobserved_feature_move_does_not_replace_an_enemy_observation(self):
        tracker = BattleTracker()
        enter(tracker, 100)
        pet = tracker._pet_by_id["401"]
        pet.feature_will_type = 4
        cast(tracker)
        with patch.object(pet, "will_impact_slot", return_value={"skill_id": 7700004, "skillId": 7700004, "name": "愿力冲击"}):
            payload = pet.to_payload(hide_unobserved=True, observed=tracker.observed_enemy_skills["401"])
        self.assertEqual(payload["moves"][0]["name"], "火焰箭")

    def test_passive_cast_does_not_become_a_move_or_change_active_pet(self):
        tracker = BattleTracker()
        enter(tracker, 100)
        tracker._absorb_pets(pet_record(402, 3011, enemy=True))
        tracker.active[1] = 1
        cast(tracker, 401, 20014000, "")
        self.assertEqual(tracker.observed_enemy_skills, {})
        self.assertEqual(tracker.active[1], 1)
        self.assertTrue(any(row.get("kind") == "skill_cast" for row in tracker.timeline))

    def test_other_battle_round_is_rejected_before_absorbing_pets(self):
        tracker = BattleTracker()
        enter(tracker, 100)
        self.assertFalse(tracker.handle_event("0x131A", {
            "state_info": {"battle_id": 99, "round": 8}, "pet": pet_record(402, 3011, enemy=True),
        }))
        self.assertEqual(tracker.round, 1)
        self.assertNotIn("402", tracker._pet_by_id)

    def test_unverified_inverse_is_not_used_as_a_live_panel(self):
        tracker = BattleTracker()
        enter(tracker, 100)
        tracker._record_panel(401, "magAtk", 764, 760, 770)
        enemy = tracker.snapshot()["runtime"]["enemyTeam"][0]
        self.assertEqual(enemy["battleStats"]["magAtk"], 0)
        self.assertNotIn("battleStatsEstimated", enemy)
        self.assertEqual(enemy["panelInference"]["ranges"]["magAtk"], [760, 770])
        self.assertFalse(enemy["panelInference"]["calibrated"])

    def test_inverse_uses_damage_segment_once_without_dividing_hit_count(self):
        tracker = BattleTracker()
        enter(tracker, 100)
        mine, enemy = tracker._pet_by_id["1"], tracker._pet_by_id["401"]
        mine.attr_stats["phyAtk"] = 200
        profile = {"kind": "physical", "hits": 3, "power": 40, "combined": 1.25}
        with patch("lab.live_damage.skill_math", return_value=profile), patch("lab.live_damage.panel_from_hit", return_value={}) as inverse:
            tracker._learn_panel(caster=mine, target=enemy, skill_id=7040370, damage=30, critical=False)
        self.assertEqual(inverse.call_args.kwargs["damage"], 30)


if __name__ == "__main__":
    unittest.main()
