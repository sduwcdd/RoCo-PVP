import unittest
import json
from pathlib import Path
from unittest.mock import patch

from lab.live_inference import infer_configuration
from lab.live_damage import _rules, panel_values, skill_math
from lab.live_battle import BattleTracker
from lab.numeric_candidates import arena_stat60, arena_documented_damage60


class LiveConfigurationTests(unittest.TestCase):
    def test_missing_enemy_nature_rewrites_keep_pre_hit_configuration_candidates(self):
        # R7 capture: HP is known before the hit; neither rewrite field was sent.
        pet = {"petBaseId": 3412, "level": 60, "nature": 10, "maxHp": 411,
               "natureOverrideKnown": {"up": False, "down": False}}
        result = infer_configuration(pet, [])
        self.assertEqual(result["status"], "conditional")
        self.assertEqual(result["original_nature_id"], 10)
        self.assertEqual(result["panel_ranges"]["hp"], [411, 411])
        lo, hi = result["panel_ranges"]["phyDef"]
        self.assertLessEqual(lo, 136)
        self.assertGreaterEqual(hi, 136)
        self.assertGreater(len(result["groups"]), 1)
        self.assertEqual(pet["nature"], 10)

        # R14 target's earlier R12 hit constrains magical defense,
        # but do not prove its physical defense talent is zero.
        pet = {"petBaseId": 3615, "level": 60, "nature": 29, "maxHp": 435,
               "natureOverrideKnown": {"up": False, "down": False}}
        common = {"turn": 12, "form_id": 3615, "stat_factor": 1, "modifier_percent": 0}
        evidence = [{**common, "skill_id": 717017000, "dimension": "mdef", "role": "defender",
                     "fixed_values": [271], "power": 140, "combined": 1, "damage": 172}]
        result = infer_configuration(pet, evidence)
        self.assertEqual(result["status"], "conditional")
        self.assertEqual(result["panel_ranges"]["magDef"], [198, 198])
        self.assertEqual(result["panel_ranges"]["phyDef"], [129, 171])
        self.assertGreater(result["combination_count"], 1)

    def test_explicit_zero_rewrites_preserve_known_configuration(self):
        original = infer_configuration(self.pet, [])
        confirmed = infer_configuration({**self.pet, "naturePosOverride": 0, "natureNegOverride": 0,
                                        "natureOverrideKnown": {"up": True, "down": True}}, [])
        self.assertEqual(confirmed, original)

    def test_capture_distinguishes_missing_rewrites_from_explicit_zero_and_partial_updates(self):
        from lab.live_battle import _Pet
        inside = {"pet_id": 1, "base_conf_id": 3412}
        pet = _Pet(side=1, roster_index=0, inside=inside, common={"level": 60, "nature": 10})
        self.assertEqual(pet.to_payload(hide_unobserved=True, observed={})["natureOverrideKnown"],
                         {"up": False, "down": False})
        pet.refresh_stats(inside, {"changed_nature_pos_attr_type": 0})
        self.assertEqual(pet.nature_override_known, {"up": True, "down": False})
        pet.refresh_stats(inside, {"energy": 7})
        self.assertEqual(pet.nature_override_known, {"up": True, "down": False})
        pet.refresh_stats(inside, {"changed_nature_neg_attr_type": 3})
        self.assertEqual(pet.nature_override_known, {"up": True, "down": True})
        self.assertEqual(pet.nature_neg_override, 3)

    def setUp(self):
        catalog, rules = _rules()
        self.race = rules.form(3080)["stats"]
        self.pet = {"petBaseId": 3080, "level": 60, "nature": 2,
                    "maxHp": arena_stat60(self.race["hp"], 60, 1, "hp")["stat_value"]}

    def event(self, dim, talent, role, percent=0):
        panel = arena_stat60(self.race[dim], talent * 6, .9 if dim == "matk" else 1, dim)["stat_value"]
        current = panel * (1 + percent / 100)
        fixed = 180
        attack, defense = (current, fixed) if role == "attacker" else (fixed, current)
        return {"turn": 1, "form_id": 3080, "skill_id": 7060200, "dimension": dim, "role": role,
                "fixed_values": [fixed], "power": 1000, "combined": 1.25,
                "damage": arena_documented_damage60(attack, defense, 1000, 1.25)["nominal_damage"],
                "stat_factor": 1 + percent / 100, "modifier_percent": percent}

    def test_both_damage_directions_yield_joint_three_talent_configuration_and_all_six_panels(self):
        result = infer_configuration(self.pet, [self.event("matk", 7, "attacker"), self.event("mdef", 5, "defender")])
        self.assertEqual(result["status"], "conditional")
        self.assertEqual(result["used_observations"], 2)
        self.assertEqual(result["nature_source"], "protocol")
        self.assertEqual(len(result["panel_ranges"]), 6)
        cases = [c for g in result["groups"] for c in g["selection_cases"]]
        self.assertTrue(all(len(c["selected"]) == 3 for c in cases))
        true = next(c for c in cases if set(c["selected"]) == {"hp", "matk", "mdef"})
        self.assertIn(10, true["value_options"]["hp"])
        self.assertIn(7, true["value_options"]["matk"])
        self.assertIn(5, true["value_options"]["mdef"])
        self.assertFalse(result["calibrated"])
        self.assertFalse(result["probability_available"])
        values, source = panel_values({**self.pet, "configurationInference": result}, "magAtk")
        self.assertEqual(values, result["panel_ranges"]["magAtk"])
        self.assertIn("实战伤害约束", source)

    def test_multiple_unknown_natures_are_retained_and_no_true_nature_is_overwritten(self):
        pet = {**self.pet, "nature": None}
        result = infer_configuration(pet, [self.event("mdef", 5, "defender")])
        self.assertGreater(len(result["groups"]), 1)
        self.assertIn(2, [g["nature_id"] for g in result["groups"]])
        self.assertIsNone(pet["nature"])

    def test_known_modifier_layers_are_inverted_before_base_talent_matching(self):
        result = infer_configuration(self.pet, [self.event("matk", 7, "attacker", 50)])
        self.assertEqual(result["status"], "conditional")
        self.assertIn(7, result["talent_value_options"]["matk"])

    def test_new_conflicting_hit_preserves_previously_narrowed_stat_and_talents(self):
        hit=self.event("mdef",5,"defender")
        first=infer_configuration(self.pet,[hit])
        conflicting={**hit,"turn":2,"damage":999999}
        later=infer_configuration(self.pet,[hit,conflicting])
        self.assertEqual(later["status"],"damage_conflict")
        self.assertEqual(later["panel_ranges"],first["panel_ranges"])
        self.assertEqual(later["talent_value_options"],first["talent_value_options"])
        self.assertEqual(later["known_talents"],first["known_talents"])
        self.assertEqual(later["used_observations"],1)
        self.assertEqual(later["damage_conflicts"][0]["turn"],2)

    def test_mismatched_damage_and_unknown_skill_are_visible_not_silently_corrected(self):
        event = self.event("matk", 7, "attacker"); event["damage"] = 999999
        result = infer_configuration(self.pet, [event])
        self.assertEqual(result["status"], "damage_conflict")
        self.assertTrue(result["groups"])
        self.assertEqual(result["used_observations"], 0)
        self.assertEqual(result["damage_conflicts"][0]["damage"], 999999)
        result = infer_configuration(self.pet, [{"form_id": 3080, "blocker": "未知技能999"}])
        self.assertEqual(result["issues"], ["未知技能999"])

    def test_real_damage_sync_updates_hud_candidates_and_caches_repeated_snapshots(self):
        tracker = BattleTracker()
        def record(pid, base, nature, attrs):
            return {"battle_inside_pet_info": {"pet_id": pid, "base_conf_id": base, "conf_id": base, "pos": 1, "battle_attr": attrs},
                    "battle_common_pet_info": {"level": 60, "nature": nature}}
        tracker.handle_event("0x1316", {"init_info": {"battle_id": 100,
            "player_team": [{"pets": [record(1, 3001, 2, [0, 400, 200, 200, 200, 200, 200])]}],
            "enemy_team": [{"pets": [record(401, 3080, 2, [0, self.pet["maxHp"], 0, 0, 0, 0, 0])]}]}})
        profile = skill_math(706020000, 3001, 3080)
        defense = arena_stat60(self.race["mdef"], 5 * 6, 1, "mdef")["stat_value"]
        damage = arena_documented_damage60(200, defense, profile["power"], profile["combined"])["nominal_damage"]
        tracker.handle_event("0x1324", {"perform_cmd": {"round": 1, "perform_info": [{"type": 4,
            "damage_info": {"caster_id": 1, "target_id": 401, "source_id": 706020000, "is_critical": [False], "is_hit": True, "dam_type": 3},
            "sync_data": {"pet_sync_info": [{"pet_id": 401, "original_damage": damage, "damage_result": damage}]}}]}})
        with patch("lab.live_inference.infer_configuration", wraps=infer_configuration) as infer:
            first = tracker.snapshot()["runtime"]["enemyTeam"][0]
            tracker.snapshot()
        self.assertEqual(infer.call_count, 2)  # Both sides once; the second snapshot reuses each cache.
        self.assertEqual(first["configurationInference"]["status"], "conditional")
        self.assertIn(5, first["configurationInference"]["talent_value_options"]["mdef"])
        self.assertEqual(first["panelStatRanges"]["magDef"], first["configurationInference"]["panel_ranges"]["magDef"])
        self.assertEqual(first["battleStats"]["magDef"], 0)

    def test_full_stat_sync_replaces_stale_ally_panel_before_the_next_hit(self):
        tracker = BattleTracker()
        tracker.handle_event("0x1316", {"init_info": {"battle_id": 1, "player_team": [{"pets": [{
            "battle_inside_pet_info": {"pet_id": 1, "base_conf_id": 3001, "battle_attr": [0, 400, 100, 100, 100, 100, 100]},
            "battle_common_pet_info": {"level": 60}}]}]}})
        tracker._apply_perform_item({"type": 35, "data_update": {"pet": {
            "battle_inside_pet_info": {"pet_id": 1, "battle_attr": [0, 400, 200, 300, 100, 100, 100]}}}})
        self.assertEqual(tracker._pet_by_id["1"].attr_stats["magAtk"], 300)

    def test_preserved_pvp_owned_protocol_talents_and_all_36_panels(self):
        from lab.live_battle import _Pet
        path = Path(__file__).resolve().parents[1] / "data/reference/live-panel-20261029.json"
        samples = json.loads(path.read_text(encoding="utf-8"))["samples"]
        keys = {"hp":"hp","patk":"phyAtk","matk":"magAtk","pdef":"phyDef","mdef":"magDef","spd":"spd"}
        total = 0
        for row in samples:
            source_keys={"hp":"hp","patk":"attack","matk":"special_attack","pdef":"defense","mdef":"special_defense","spd":"speed"}
            common={"level":60,"nature":row["nature"],"changed_nature_pos_attr_type":row["nature_pos_override"],
                    "changed_nature_neg_attr_type":row["nature_neg_override"],"attribute_info":{
                        **{source_keys[d]:r for d,r in row["dimensions"].items()},"break_enhance_enum":row["break_enhance_enum"]}}
            raw=_Pet(side=0,roster_index=0,inside={"pet_id":1,"base_conf_id":row["form_id"],"battle_attr":row["battle_attr"]},common=common)
            raw.refresh_stats({}, {"attribute_info":{"hp":{"base_value":row["dimensions"]["hp"]["base_value"]}}})
            pet=raw.to_payload(hide_unobserved=False,observed={})
            result = infer_configuration(pet, [])
            self.assertEqual(result["status"], "protocol")
            self.assertEqual(len(result["protocol_selection"]["selected"]), 3)
            self.assertEqual(result["combination_count"], 1)
            self.assertTrue(all(r["matches"] for r in result["panel_fit"]), (row["form_id"], result["panel_fit"]))
            self.assertFalse(result["issues"])
            total += len(result["panel_fit"])
        self.assertEqual(total, 36)

    def test_opponent_max_hp_alone_produces_three_talent_candidates_before_any_hit(self):
        result = infer_configuration({**self.pet, "battleStats":{"hp":self.pet["maxHp"], "phyAtk":0}}, [])
        self.assertEqual(result["status"], "conditional")
        self.assertEqual(result["used_panels"], 1)
        self.assertEqual(result["used_observations"], 0)
        self.assertTrue(result["groups"])
        self.assertTrue(all(len(c["selected"])==3 for g in result["groups"] for c in g["selection_cases"]))

    def test_real_damage_constraints_reuse_current_status_weather_and_trait_queries(self):
        from lab.live_battle import _Pet
        from lab.live_inference import damage_observation
        from lab.live_damage import _damage_case
        from lab.weather_runtime import set_weather
        target = _Pet(side=1, roster_index=0, inside={"pet_id":401,"base_conf_id":3080,
            "battle_attr":[0,self.pet["maxHp"],0,0,0,0,0]}, common={"level":60,"nature":2})
        ally = _Pet(side=0, roster_index=0, inside={"pet_id":1,"base_conf_id":3001,
            "battle_attr":[0,400,200,200,200,200,200]}, common={"level":60})
        ally.feature_id, target.feature_id = 200075, 0
        ally.set_buff(20010020,5)
        target.set_buff(20010060,5)
        weather,_ = set_weather(None,7050250,1)
        context = {"attacker":ally.to_payload(hide_unobserved=False,observed={}),"defender":target.to_payload(hide_unobserved=True,observed={})}
        for p in context.values():p["liveContext"]={"turn":1,"weather":weather}
        profile = {**skill_math(7050200,3001,3080), "skillId":7050200}
        defense = arena_stat60(self.race["mdef"],30,1,"mdef")["stat_value"]
        target_with_panel = {**context["defender"],"battleStats":{**context["defender"]["battleStats"],"magDef":defense}}
        case = _damage_case(context["attacker"],target_with_panel,profile,profile["kind"])
        _,event = damage_observation(ally,target,705020000,case["minimum"],False,1,5,context)
        result = infer_configuration(self.pet,[event])
        self.assertEqual(result["status"],"conditional")
        self.assertIn(5,result["talent_value_options"]["mdef"])
        self.assertNotIn("calculation",result["observations"][0])
        context["attacker"]["currentHp"]=1
        self.assertEqual(event["calculation"]["attacker"]["currentHp"],400)

    def test_damage_sync_freezes_hp_before_sync_and_does_not_confuse_element_with_kind(self):
        from lab.live_battle import _Pet
        from lab.live_inference import damage_observation
        tracker=BattleTracker()
        ally=_Pet(side=0,roster_index=0,inside={"pet_id":1,"base_conf_id":3001,"battle_attr":[0,400,200,100,100,100,100]},common={"level":60})
        enemy=_Pet(side=1,roster_index=0,inside={"pet_id":401,"base_conf_id":3080,"battle_attr":[0,self.pet["maxHp"],0,0,0,0,0]},common={"level":60,"nature":2})
        ally.feature_id=enemy.feature_id=0
        tracker.teams={0:[ally],1:[enemy]};tracker._pet_by_id={"1":ally,"401":enemy}
        tracker._apply_perform_item({"type":4,"damage_info":{"caster_id":1,"target_id":401,"source_id":706020000,"is_critical":[False],"dam_type":6},
            "sync_data":{"pet_sync_info":[{"pet_id":401,"hp_result":1,"original_damage":20,"damage_result":20}]}})
        event=tracker.damage_evidence["401"][0]
        self.assertEqual(event["calculation"]["defender"]["currentHp"],self.pet["maxHp"])
        self.assertEqual(enemy.hp,1)
        _,higher=damage_observation(ally,enemy,7700017,20,False,1,3)
        self.assertEqual(higher["dimension"],"pdef")  # 3 is grass, never a magical-branch assertion.


if __name__ == "__main__":
    unittest.main()
