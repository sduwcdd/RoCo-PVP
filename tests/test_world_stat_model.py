import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from lab.live_damage import panel_values
from lab.live_inference import infer_configuration
from lab.live_stat_model import STAT_KEYS, WORLD_SOURCE_SHA256, star_candidates, stat_candidates
from lab.numeric_candidates import captured_stat60


ROOT = Path(__file__).resolve().parents[1]


class WorldStatModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((ROOT / "data/reference/world-panel-20261101.json").read_text(encoding="utf8"))
        cls.sample = next(s for s in cls.fixture["samples"] if s["level"] == 56)
        cls.race = {dim: row["race"] for dim, row in cls.sample["dimensions"].items()}
        cls.catalog = {"snapshot_id": "test-world", "natures": [
            {"id": 11, "name": {"zh": "聪明"}, "up": "matk", "down": "patk"},
            {"id": 1, "name": {"zh": "大胆"}, "up": "patk", "down": "pdef"}]}

    def pet(self, *, protocol=False):
        sample = self.sample
        pet = {"petBaseId": sample["form"], "level": 56, "battleMode": "world",
               "battleStats": {STAT_KEYS[d]: r["battle"] for d, r in sample["dimensions"].items()},
               "maxHp": sample["dimensions"]["hp"]["battle"]}
        if protocol:
            pet["talentEvidence"] = {"selected_ids": sample["selected_dimension_ids"], "dimensions": {
                STAT_KEYS[d]: {"talent": r["raw_talent"], "talent_add_value": r["display_talent"],
                               "base_value": r["base"], "effort_add": r["effort"]}
                for d, r in sample["dimensions"].items()}}
        return pet

    def infer(self, pet):
        with patch("lab.live_damage._race_stats", return_value=(self.race, "test-race")), \
                patch("lab.live_damage._rules", return_value=(self.catalog, None)):
            return infer_configuration(pet, [])

    def test_mode_boundaries_and_explicit_world_stars(self):
        self.assertEqual(star_candidates({"level": 60, "natureStatsPolicy": {"stars": 0}}), [5])
        self.assertEqual(star_candidates({"level": 56, "battleMode": "world",
                                          "natureStatsPolicy": {"stars": 8}}), [0])
        self.assertEqual(star_candidates({"level": 60, "natureStatsPolicy": {"source": "world-observed"}}), list(range(11)))
        self.assertEqual(star_candidates({"level": 60, "battleMode": "world",
                                          "natureStatsPolicy": {"stars": 10}}), [10])
        with self.assertRaises(ValueError):
            star_candidates({"level": 60, "battleMode": "world", "natureStatsPolicy": {"stars": True}})

    def test_all_24_captured_world_dimensions_keep_zero_star_talents(self):
        self.assertEqual(hashlib.sha256((ROOT / "data/reference/world-panel-20261101.json").read_bytes()).hexdigest(),
                         WORLD_SOURCE_SHA256)
        for sample in self.fixture["samples"]:
            pet = {"level": sample["level"], "battleMode": "world", "natureStatsPolicy": {"stars": 0}}
            up, down = {1: ("patk", "pdef"), 11: ("matk", "patk"),
                        28: ("hp", "matk"), 21: ("spd", "patk")}[sample["nature"]]
            for dim, row in sample["dimensions"].items():
                with self.subTest(form=sample["form"], dim=dim):
                    self.assertEqual(stat_candidates(pet, row["race"], dim, row["display_talent"], up, down, 0),
                                     [row["battle"]])

    def test_world_protocol_selection_does_not_require_raw_times_six(self):
        result = self.infer(self.pet(protocol=True))
        self.assertEqual(result["status"], "protocol")
        self.assertEqual(result["combination_count"], 1)
        self.assertEqual(set(result["known_talents"]), {"patk", "pdef", "mdef"})
        self.assertEqual(result["known_nature"]["up"], "matk")
        self.assertEqual(result["star_coverage"], {"requested": [0], "evaluated": [0], "blocked": []})

    def test_unknown_world_selection_matches_panels_with_exactly_three_dimensions(self):
        result = self.infer(self.pet())
        self.assertEqual(result["status"], "conditional")
        self.assertEqual(result["known_nature"]["up"], "matk")
        for group in result["groups"]:
            self.assertEqual(group["stars"], 0)
            for case in group["selection_cases"]:
                self.assertEqual(set(case["selected"]), {"patk", "pdef", "mdef"})
                for dim in case["selected"]:
                    self.assertIn(self.sample["dimensions"][dim]["display_talent"], case["value_options"][dim])

    def test_low_level_enemy_hp_alone_is_a_constraint_not_a_full_panel(self):
        pet = {"petBaseId": 1, "level": 10, "battleMode": "world", "maxHp": 94, "nature": 25}
        catalog = {"snapshot_id": "test", "natures": [{"id": 25, "name": {"zh": "热情"}, "up": "spd", "down": "hp"}]}
        with patch("lab.live_damage._race_stats", return_value=({d: 120 for d in STAT_KEYS}, "test")), \
                patch("lab.live_damage._rules", return_value=(catalog, None)):
            result = infer_configuration(pet, [])
        self.assertEqual(result["status"], "conditional")
        self.assertEqual(result["used_panels"], 1)
        self.assertEqual(result["panel_ranges"]["hp"], [94, 94])
        self.assertTrue(all(len(c["selected"]) == 3 for g in result["groups"] for c in g["selection_cases"]))

    def test_positive_star_uses_downlinked_base_and_effort_without_talent_scaling(self):
        pet = {"level": 60, "battleMode": "world", "talentEvidence": {"dimensions": {
            "phyAtk": {"talent": 77, "talent_add_value": 7, "base_value": 136, "effort_add": 20}}}}
        self.assertEqual(stat_candidates(pet, 115, "patk", 7, "patk", "matk", 10), [183])
        self.assertEqual(stat_candidates(pet, 115, "patk", 8, "patk", "matk", 10), [])
        with self.assertRaisesRegex(ValueError, "正星"):
            stat_candidates({"level": 60, "battleMode": "world"}, 115, "patk", 7, "patk", "matk", 10)

    def test_unknown_positive_star_scope_is_not_reported_as_complete_zero_star_range(self):
        pet = {"petBaseId": 1, "level": 60, "battleMode": "world", "maxHp": 260}
        result = self.infer(pet)
        self.assertEqual(result["status"], "unresolved")
        self.assertEqual(result["star_coverage"]["blocked"], list(range(1, 11)))
        self.assertEqual(result["panel_ranges"], {})
        self.assertEqual(result["known_talents"], {})
        with patch("lab.live_damage._race_stats", return_value=(self.race, "test")), \
                patch("lab.live_damage.nature_info", return_value={}):
            with self.assertRaisesRegex(ValueError, "完整范围"):
                panel_values(pet, "phyAtk")

    def test_stars_are_coupled_across_dimensions(self):
        pet = {"petBaseId": 1, "level": 60, "battleMode": "world", "nature": 11,
               "maxHp": 100, "battleStats": {"phyAtk": 101}}
        with patch("lab.live_inference.stat_candidates", side_effect=lambda p, r, d, t, u, dn, s: [100 + s]):
            result = self.infer(pet)
        self.assertEqual(result["groups"], [])
        self.assertEqual(result["status"], "model_mismatch")

    def test_pvp_keeps_captured_stat60_precision_candidates(self):
        for dim, race, talent in (("hp", 112, 10), ("patk", 131, 8), ("matk", 105, 0)):
            pet = {"level": 60, "battleMode": "pvp"}
            expected = captured_stat60(race, talent * 6, 1.2 if dim == "patk" else .9 if dim == "matk" else 1, dim)["stat_values"]
            self.assertEqual(stat_candidates(pet, race, dim, talent, "patk", "matk", 5), expected)


if __name__ == "__main__":
    unittest.main()
