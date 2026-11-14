import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor/rkpp"))
import unittest

from lab.catalog_store import load_catalog
from lab.mobile_pve import PveMetadata
from lab import battle_data
from tests.test_live_battle import pet_record


class MobilePveTests(unittest.TestCase):
    def setUp(self):
        self.catalog, _, _ = load_catalog()
        self.pve = PveMetadata(self.catalog)

    def enter(self, battle=1, pet=401, base=3602, common=None):
        enemy = pet_record(pet, base, enemy=True)
        enemy["battle_inside_pet_info"]["pos"] = 1
        enemy["battle_common_pet_info"].update(common or {})
        self.pve.handle(0x1316, {"init_info": {"battle_id": battle,
            "player_team": [{"pets": [pet_record(1, 3463)]}], "enemy_team": [{"pets": [enemy]}]}})

    def test_metadata_matches_existing_nature_and_physical_mappings(self):
        self.enter(common={"nature": 2, "weight": 123456, "voice": 99, "height": 200, "wear_medal_conf_id": 1026})
        result = self.pve.snapshot()
        self.assertTrue(result["ready"])
        enemy = result["enemy"]
        self.assertEqual((enemy["natureName"], enemy["natureUp"], enemy["natureDown"]), ("固执", "物攻", "魔攻"))
        physical = battle_data.physical_info(3602, weight=123456, voice=99, height=200, worn_medal_id=1026)
        self.assertEqual(enemy["weightText"], physical["weight"]["text"])
        self.assertEqual(enemy["voiceText"], physical["voice"]["text"])
        self.assertIn("婉转声", enemy["medals"])
        self.assertFalse({"hp", "stats", "skills", "energy"} & set(enemy))

    def test_new_encounter_and_finish_do_not_reuse_previous_creature(self):
        self.enter(common={"nature": 2, "weight": 123456, "voice": 99})
        first = self.pve.snapshot()["generation"]
        self.enter(battle=2, base=3463)
        result = self.pve.snapshot()
        self.assertGreater(result["generation"], first)
        self.assertEqual(result["enemy"]["weightText"], "未下发")
        self.assertEqual(result["enemy"]["natureName"], "性格未下发")
        self.pve.handle(0x132C, {"settle_info": {"battle_id": 1}})
        self.assertTrue(self.pve.snapshot()["ready"])
        self.pve.handle(0x132C, {"settle_info": {"battle_id": 2}})
        self.assertFalse(self.pve.snapshot()["ready"])
        self.assertIsNone(self.pve.snapshot()["enemy"])

    def test_switch_identity_is_authoritative_and_unknown_target_clears_view(self):
        self.enter()
        next_pet = pet_record(402, 3463, enemy=True)
        self.pve.handle(0x1324, {"perform_cmd": {"perform_info": [
            {"exec_index": 0, "change_pet": {"battle_pet_id": 402, "battle_pet_info": next_pet}}]}})
        self.assertEqual(self.pve.active_id, "402")
        self.pve.handle(0x1324, {"perform_cmd": {"perform_info": [
            {"exec_index": 0, "change_pet": {"battle_pet_id": 499}}]}})
        self.assertFalse(self.pve.snapshot()["ready"])

    def test_catching_up_hides_old_enemy_without_destroying_current_metadata(self):
        self.enter()
        self.assertFalse(self.pve.snapshot(ready=False)["ready"])
        self.assertIsNone(self.pve.snapshot(ready=False)["enemy"])
        self.assertTrue(self.pve.snapshot()["ready"])

    def test_wire_projection_omits_skills_but_keeps_required_metadata(self):
        import Data
        import rkpp_analysis as analysis
        import rkpp_codec as codec
        messages = Data.get_proto_schema()["messages"]
        resolve = lambda name: analysis._codec_schema_for_message(messages, name)
        value = {"init_info": {"battle_id": 1, "enemy_team": [{"pets": [{
            "battle_inside_pet_info": {"pet_id": 401, "base_conf_id": 3602, "pos": 1,
                "skill_round_data": [{"pos": 1, "skill_id": 7040370}]},
            "battle_common_pet_info": {"nature": 2, "weight": 123456, "voice": 99}}]}]}}
        payload = codec.encode_payload(resolve("ZoneBattleEnterNotify"), value, resolve_message=resolve)
        decoded = self.pve.decode({"opcode": 0x1316, "payload_hex": payload.hex()})
        pet = decoded["init_info"]["enemy_team"][0]["pets"][0]
        self.assertNotIn("skill_round_data", pet["battle_inside_pet_info"])
        self.assertEqual(pet["battle_common_pet_info"]["weight"], 123456)
        self.pve.handle(0x1316, decoded)
        self.assertTrue(self.pve.snapshot()["ready"])

    def test_projected_known_field_type_changes_are_rejected(self):
        from unittest.mock import patch
        schema = {"fields": [{"no": 1, "name": "weight", "type": "uint32"}]}
        with patch.object(self.pve, "_schema", return_value=schema):
            for raw in (b"\x0a\x01x", b"\x08\x80"):
                with self.subTest(raw=raw), self.assertRaises(ValueError):
                    self.pve.decode({"opcode": 0x1316, "payload_hex": raw.hex()})

    def test_packet_name_survives_projection_for_unlisted_pve_creature(self):
        import Data
        import rkpp_analysis as analysis
        import rkpp_codec as codec
        messages = Data.get_proto_schema()["messages"]
        resolve = lambda name: analysis._codec_schema_for_message(messages, name)
        # Identity fields from a saved encounter, with player/battle identifiers removed.
        enemy = pet_record(401, 9006, enemy=True)
        enemy["battle_inside_pet_info"].pop("skill_round_data")
        enemy["battle_inside_pet_info"].update(pos=1, conf_id=1646)
        enemy["battle_common_pet_info"].update(base_conf_id=9006, conf_id=1646,
            name="龙棋士".encode("utf8").hex(), nature=2)
        value = {"init_info": {"battle_id": 1, "enemy_team": [{"pets": [enemy]}]}}
        payload = codec.encode_payload(resolve("ZoneBattleEnterNotify"), value, resolve_message=resolve)
        decoded = self.pve.decode({"opcode": 0x1316, "payload_hex": payload.hex()})
        self.pve.handle(0x1316, decoded)
        result = self.pve.snapshot()["enemy"]
        self.assertEqual(result["name"], "龙棋士")
        self.assertEqual(result["formId"], 9006)
        self.assertEqual(result["identitySource"], "reported_name")
        self.assertEqual(result["natureName"], "固执")
        self.pve.handle(0x1324, {"perform_cmd": {"perform_info": []}})
        self.assertEqual(self.pve.snapshot()["enemy"]["name"], "龙棋士")

    def test_native_form_lookup_preserves_raw_id_without_bwiki_entry(self):
        self.enter(base=9004, common={"nature": 2, "name": "昵称".encode("utf8").hex()})
        enemy = self.pve.snapshot()["enemy"]
        self.assertEqual(enemy["name"], "金月陨星")
        self.assertEqual(enemy["formId"], 9004)
        self.assertEqual(enemy["identitySource"], "historical_external")

    def test_known_form_precedes_nickname_and_unknown_id_is_explicit(self):
        self.enter(common={"name": "其他昵称".encode("utf8").hex()})
        expected = self.pve.forms["3602"]["name"]["zh"]
        self.assertEqual(self.pve.snapshot()["enemy"]["name"], expected)
        self.enter(battle=2, base=987654321)
        enemy = self.pve.snapshot()["enemy"]
        self.assertEqual(enemy["name"], "未收录精灵（ID 987654321）")
        self.assertEqual(enemy["identitySource"], "unresolved")

    def test_catalog_portraits_are_local_pngs(self):
        folder = Path(__file__).resolve().parents[1] / "web/assets/roco/pet-avatars"
        for form in self.catalog["forms"]:
            with self.subTest(form_id=form["id"]):
                with (folder / f"{form['id']}.png").open("rb") as image:
                    self.assertEqual(image.read(8), b"\x89PNG\r\n\x1a\n")
