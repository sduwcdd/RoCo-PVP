"""NPC growth candidates and attacker-level damage, independent of private captures."""
import unittest
from unittest.mock import patch
from lab.live_stat_model import stat_candidates, damage_value, world_npc_rules
from lab.numeric_candidates import arena_documented_damage60
from lab.trait_runtime import query_scope
from lab.live_inference import infer_configuration


class WorldNpcDamageTests(unittest.TestCase):
    def pet(self):
        return {"confId":410451,"petBaseId":3455,"level":24,"battleMode":"world","worldNpc":True}

    def test_native_growth_is_added_outside_nature_without_forcing_unique_talents(self):
        with query_scope():
            self.assertEqual(stat_candidates(self.pet(),89,"hp",7,"hp","spd",0),[158])
            self.assertEqual(stat_candidates(self.pet(),89,"hp",8,"hp","spd",0),[158])
            self.assertEqual(stat_candidates(self.pet(),94,"patk",0,"hp","spd",0),[90])
            self.assertEqual(stat_candidates(self.pet(),105,"mdef",9,"hp","spd",0),[101])

    def test_observed_14_129_258_share_one_damage_expression(self):
        with query_scope():
            self.assertEqual(damage_value(self.pet(),90,175,55,1),14)
            own={"battleMode":"world","level":60}
            self.assertEqual(damage_value(own,181,101,80,1),129)
            self.assertEqual(damage_value(own,181,101,80,2),258)
            pvp={"battleMode":"pvp","level":60}
            self.assertEqual(damage_value(pvp,181,101,80,1),arena_documented_damage60(181,101,80,1)["nominal_damage"])

    def test_unreviewed_npc_or_level_is_blocked(self):
        for extra in ({"confId":999999},{"level":25},{"petBaseId":3021}):
            with self.assertRaises(ValueError),query_scope():
                stat_candidates({**self.pet(),**extra},89,"hp",8,"hp","spd",0)

    def test_source_hash_is_checked_and_tampering_rejected(self):
        with patch("lab.live_stat_model.NPC_CONFIG_SHA256","0"*64):
            with self.assertRaises(ValueError):world_npc_rules()

    def test_world_protocol_talents_survive_unexplained_live_panel_change(self):
        pet={"petBaseId":1,"level":60,"battleMode":"world","nature":11,"battleStats":{"spd":999},
             "natureStatsPolicy":{"stars":0},"talentEvidence":{"selected_ids":[1,4,5],"dimensions":{
                 key:{"talent_add_value":10,"talent":10,"base_value":100,"effort_add":0}
                 for key in ("hp","phyDef","magDef")}}}
        catalog={"snapshot_id":"test","natures":[{"id":11,"name":{"zh":"聪明"},"up":"matk","down":"patk"}]}
        with patch("lab.live_damage._race_stats",return_value=({d:100 for d in ("hp","patk","matk","pdef","mdef","spd")},"test")),patch("lab.live_damage._rules",return_value=(catalog,None)):
            result=infer_configuration(pet,[])
        self.assertEqual(result["status"],"protocol_model_mismatch")
        self.assertEqual(set(result["known_talents"]),{"hp","pdef","mdef"})
        self.assertTrue(all(v["source"]=="protocol" for v in result["known_talents"].values()))
