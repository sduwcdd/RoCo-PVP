from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from lab import live_inference, live_modifiers
from lab.live_damage import _damage_case, _rules
from lab.live_battle import _Pet, BattleTracker
from lab.live_stat_model import stat_candidates


ROOT = Path(__file__).resolve().parents[1]


def pet(tid=0, **changes):
    return {"petBaseId": 3001, "effectiveTraitId": tid, **changes}


class S5HUDGateTests(unittest.TestCase):
    def test_captured_abu_panels_at_four_effective_levels(self):
        source = json.loads((ROOT / "data/reference/live-abu-levels-20261121.json").read_bytes())
        for row in source["panels"]:
            subject = {"level": row["level"], "petBaseId": row["form"]}
            for index, dim in enumerate(source["stat_order"]):
                with self.subTest(packet=row["packet"], stat=dim):
                    values = stat_candidates(subject, source["species"][index], dim, source["raw_talents"][index] // 6,
                                             row["up"], row["down"], 5)
                    self.assertEqual(values, [row["values"][index]])

    def test_guardian_level_delta_full_panel_and_incremental_buffs(self):
        attrs = [0] * 96
        attrs[1], attrs[2], attrs[29] = 534, 279, 12000
        common = {"level": 60, "base_conf_id": 3168, "attribute_info": {"attack": {"base_value": 198, "talent": 60}}}
        subject = _Pet(side=0, roster_index=0, common=common, inside={
            "pet_id": 1, "base_conf_id": 5068, "field_91": 84, "battle_attr": attrs,
            "buffs": [{"buff_id": 23000030, "stack": 24}]})
        tracker = BattleTracker()
        tracker._pet_by_id["1"] = subject
        tracker._record_panel(1, "phyAtk", 279, 278, 280)
        tracker._apply_perform_item({"sync_data": {"pet_sync_info": [
            {"pet_id": 1, "attr_type": 1, "attr_result": 493}, {"pet_id": 1, "field_40": 74}]}})
        self.assertEqual((subject.level, subject.common_level, subject.max_hp), (74, 60, 493))
        self.assertEqual(tracker._learned_for(1), {})
        self.assertNotIn("phyAtk", subject.revealed_base_stats)
        self.assertEqual(subject.panel_stats, {})
        self.assertEqual(subject.talent_evidence["dimensions"]["phyAtk"], {"talent": 60})
        attrs[1], attrs[2], attrs[29] = 493, 262, 11000
        subject.refresh_stats({"battle_attr": attrs, "buffs": [{"buff_id": 23000030, "stack": 14},
                              {"buff_id": 20010010, "stack": 4}]}, common)
        payload = lambda: subject.to_payload(hide_unobserved=False, observed={})
        self.assertEqual(payload()["levelSource"], "pet_sync_info.field_40")
        self.assertEqual(payload()["commonLevel"], 60)
        self.assertEqual(payload()["guardianAttackPercent"], 110)
        self.assertAlmostEqual(live_modifiers.panel_candidates(payload(), "phyAtk", pet())[0][0], 550.2)
        subject.set_buff(20010010, 3)
        self.assertIsNone(payload()["guardianAttackPercent"])
        self.assertEqual(live_modifiers.panel_candidates(payload(), "phyAtk", pet())[0], [524])
        attrs[29] = 0
        subject.refresh_stats({"battle_attr": attrs}, common)
        self.assertEqual(payload()["guardianAttackPercent"], 0)
        subject.refresh_stats({"battle_attr": attrs[:7]}, common)
        self.assertIsNone(payload()["guardianAttackPercent"])
        attrs[2] = 0
        subject.refresh_stats({"battle_attr": attrs}, common)
        self.assertIsNone(payload()["guardianAttackPercent"])

    def test_shared_decoder_preserves_the_observed_battle_level_fields(self):
        import sys
        sys.path.insert(0, str(ROOT / "vendor/rkpp"))
        import rkpp_analysis as decoder
        import rkpp_proto_core as proto
        fixture = json.loads((ROOT / "tests/fixtures/abu-level-fields-20261121.json").read_text(encoding="utf8"))
        record = decoder.decode_record({**fixture, "root": proto.parse_proto_message(bytes.fromhex(fixture["payload_hex"]))})
        self.assertTrue(record["schema_found"])
        events = record["decoded"]["perform_cmd"]["perform_info"]
        self.assertEqual(events[0]["change_model"]["pet_info"]["battle_inside_pet_info"]["field_91"], 84)
        self.assertEqual(events[1]["sync_data"]["pet_sync_info"][0]["field_40"], 74)

    @classmethod
    def setUpClass(cls):
        cls.catalog = _rules()[0]
        cls.gates = json.loads(live_modifiers.S5_HUD_GATES.read_text(encoding="utf8"))

    def test_missing_required_state_blocks_all_eleven_traits(self):
        self.assertEqual(len(self.gates["traits"]), 11)
        for tid, row in self.gates["traits"].items():
            for role in row["damage_roles"]:
                for kind in (set(row["damage_kinds"]) - {"higher"}):
                    pair = (pet(int(tid)), pet()) if role == "attacker" else (pet(), pet(int(tid)))
                    with self.subTest(tid=tid, role=role, kind=kind), self.assertRaisesRegex(ValueError, row["reason"]):
                        live_modifiers.damage_profile(*pair, 7040370, {"kind": kind})

    def test_reported_level_drives_damage_and_the_strict_defender_threshold(self):
        panels = {"phyAtk": 200, "phyDef": 100, "magAtk": 200, "magDef": 100}
        source = pet(200327, petBaseId=3798, level=99, battleStats=panels)
        target = pet(level=60, battleStats=panels)
        move = {"skillId": 7040370, "kind": "physical", "power": 80, "skillType": "普通系",
                "stab": 1, "multiplier": 1, "combined": 1}
        self.assertEqual(_damage_case(source, target, move, "physical")["minimum"], 212)
        for tid, form, percent in ((200327, 3798, 40), (200328, 3168, 30), (280041, 5068, 30)):
            for level in (79, 80):
                with self.subTest(tid=tid, level=level):
                    defender = pet(tid, petBaseId=form, level=level, battleStats=panels)
                    result = _damage_case(source, defender, move, "physical")
                    factor = 100 + percent if level == 79 else 100
                    self.assertEqual(result["minimum"], 212 * factor // 100)
                    self.assertEqual(result["effects"]["reported_level_traits"]["defender"]["level"], level)
        guardian = pet(280041, petBaseId=5068, level=99, battleStats=panels)
        with self.assertRaisesRegex(ValueError, "圣龙的守护层数"):
            _damage_case(guardian, target, move, "physical")
        magical = _damage_case(guardian, target, {**move, "kind": "magical"}, "magical")
        self.assertEqual(magical["minimum"], 212)
        dragon = pet(200327, petBaseId=3798, level=79, battleStats=panels)
        rounded = _damage_case(target, dragon, {**move, "power": 50}, "physical")
        self.assertEqual(rounded["minimum"], 126)  # 90 × 1.4 is just below 126 in binary64.

    def test_only_damage_relevant_roles_and_kinds_are_blocked(self):
        safe = [(pet(200329), pet(), "physical"), (pet(), pet(200329), "magical"),
                (pet(200332), pet(), "physical"), (pet(200330), pet(), "magical")]
        safe.extend((pet(tid), pet(), "physical") for tid in (200333, 200334, 200335, 200336, 280039, 200001))
        for attacker, defender, kind in safe:
            with self.subTest(attacker=attacker, defender=defender, kind=kind):
                live_modifiers.validate_damage_support(attacker, defender, 7040370, {"kind": kind})

    def test_new_move_gates_do_not_block_plain_two_hit_move(self):
        self.assertEqual(len(self.gates["moves"]), 5)
        for sid, row in self.gates["moves"].items():
            with self.subTest(sid=sid), self.assertRaisesRegex(ValueError, row["reason"]):
                live_modifiers.damage_profile(pet(), pet(), int(sid), {"kind": "physical"})
        live_modifiers.validate_damage_support(pet(), pet(), 7030640, {"kind": "magical"})

    def test_current_catalog_form_and_explicit_trait_override(self):
        form = next(f for f in self.catalog["forms"] if f.get("trait_id") == 200327)
        native = {"petBaseId": form["id"]}
        with patch("lab.live_modifiers.battle_data.pet_form", return_value={}):
            with self.assertRaisesRegex(ValueError, "恶龙的奢望"):
                live_modifiers.validate_damage_support(native, pet(), 7040370, {"kind": "physical"})
            live_modifiers.validate_damage_support({**native, "effectiveTraitId": 0}, pet(), 7040370, {"kind": "physical"})
        with self.assertRaisesRegex(ValueError, "恶龙的奢望"):
            live_modifiers.validate_damage_support({"_simulation_actor": {"trait_id": 200327}}, pet(), 7040370, {"kind": "physical"})

    def test_changed_source_cannot_reuse_an_old_mechanics_gate(self):
        changed = deepcopy(self.catalog)
        changed["traits"]["280040"]["desc"]["zh"] = "changed source"
        with patch("lab.live_damage._rules", return_value=(changed, None)), self.assertRaisesRegex(ValueError, "来源不符"):
            live_modifiers.damage_profile(pet(280040), pet(), 7040370, {"kind": "physical"})

    def test_damage_observation_keeps_a_blocker_before_panel_queries(self):
        caster = SimpleNamespace(side=0, base_conf_id=3001, pet_id=1, lowered_form=lambda: None)
        target = SimpleNamespace(side=1, base_conf_id=3001, pet_id=2, lowered_form=lambda: None)
        context = {"attacker": pet(280040), "defender": pet()}
        with patch("lab.live_damage.skill_math", return_value={"kind": "physical"}), \
                patch("lab.live_modifiers.panel_candidates", side_effect=AssertionError("unreviewed equation reached panels")):
            identity, event = live_inference.damage_observation(caster, target, 7040370, 100, False, 1, context=context)
        self.assertEqual(identity, 2)
        self.assertIn("烈冰钻", event["blocker"])
        self.assertNotIn("calculation", event)

    def test_known_hp_configuration_inference_does_not_need_a_damage_equation(self):
        known = {"petBaseId": 3412, "effectiveTraitId": 280040, "level": 60,
                 "nature": 10, "maxHp": 411, "natureOverrideKnown": {"up": False, "down": False}}
        with patch("lab.live_modifiers.validate_damage_support", side_effect=AssertionError("no damage observation")):
            result = live_inference.infer_configuration(known, [])
        self.assertTrue(result["groups"])
        self.assertEqual(result["panel_ranges"]["hp"], [411, 411])
        self.assertEqual(result["used_observations"], 0)


if __name__ == "__main__":
    unittest.main()
