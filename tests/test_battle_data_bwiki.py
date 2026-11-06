from copy import deepcopy
import unittest
from unittest.mock import patch

from lab import battle_data


class BattleDataBwikiTests(unittest.TestCase):
    def setUp(self):
        battle_data._cache.clear()
        self.addCleanup(battle_data._cache.clear)
        self.pets = {
            "3001": {"name": "旧名字", "unit_type": [3], "stage": 1,
                     "pet_feature": 200001, "hp_max_race": 60,
                     "phy_attack_race": 70, "ai_group_info_id": 3001,
                     "evolution_pet_id": [3002], "legal_petbase": 1},
            "3002": {"name": "旧进化", "stage": 2, "hp_max_race": 80},
            "3999": {"name": "历史精灵", "unit_type": [3], "stage": 1,
                     "hp_max_race": 40},
        }
        self.skills = {
            "7000001": {"name": "旧技能", "dam_para": [80], "energy_cost": [2],
                        "damage_type": 2, "skill_dam_type": 3, "type": 1,
                        "damage_rule": 15, "desc": "旧描述", "skill_result": [{"effect_id": 1}]},
            "200001": {"name": "旧特性", "desc": "旧特性描述", "type": 2},
            "7000999": {"name": "历史技能", "dam_para": [45], "damage_type": 3,
                        "skill_dam_type": 4, "type": 1},
            "7700002": {"name": "愿力冲击", "dam_para": [80], "energy_cost": [2],
                        "damage_type": 4, "skill_dam_type": 3, "type": 1, "cd_round": [1]},
        }
        self.catalog = {
            "snapshot_id": "current-test",
            "forms": [
                {"id": 3001, "name": {"zh": "当前名字"}, "types": ["火系", "水系"],
                 "stats": {"hp": 101, "patk": 102, "matk": 103, "pdef": 104,
                           "mdef": 105, "spd": 106}, "stage": 2, "trait_id": 200002},
                {"id": 3002, "name": {"zh": "当前进化"}, "stats": {"hp": 150}, "stage": 3},
                {"id": 3998, "name": {"zh": "新增精灵"}, "types": ["水系"],
                 "stats": {"hp": 90}, "stage": 1, "trait_id": 200002},
            ],
            "moves": {
                "7000001": {"id": 7000001, "name": {"zh": "当前技能"}, "power": 120,
                            "kind": "magical", "type": "水系", "energy": 0,
                            "desc": {"zh": "当前描述"}},
                "7000002": {"id": 7000002, "name": {"zh": "新增技能"}, "power": 50,
                            "kind": "physical", "type": "火系", "energy": 1},
                "7700002": {"id": 7700002, "name": {"zh": "愿力冲击"}, "power": 99,
                            "kind": "higher", "type": "草系", "energy": 3},
            },
            "traits": {"200002": {"id": 200002, "name": {"zh": "当前特性"},
                                  "desc": {"zh": "当前特性描述"}, "kind": "trait"}},
        }
        for name, value in (("_petbase", self.pets), ("_skills", self.skills),
                            ("runtime_catalog", (self.catalog, "digest", None))):
            mock = patch.object(battle_data, name, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    def test_current_form_values_and_new_ids_override_history_without_mutation(self):
        before = deepcopy((self.catalog, self.pets, self.skills))
        form = battle_data.pet_form(3001)
        self.assertEqual((form["name"], form["feature_id"], form["feature_name"], form["feature_desc"]),
                         ("当前名字", 200002, "当前特性", "当前特性描述"))
        self.assertEqual(form["data_source"], "BWIKI")
        self.assertEqual(battle_data.pet_unit_types(3001), (4, 5))
        self.assertEqual(battle_data.pet_race_stats(3001), self.catalog["forms"][0]["stats"])
        stage = battle_data.pet_stage_info(3001)
        self.assertEqual((stage["stage"], stage["family"]), (2, "3001"))
        self.assertEqual(stage["historical_fields"], ["family"])
        self.assertEqual(battle_data.pet_form(3998)["name"], "新增精灵")
        self.assertEqual(battle_data.pet_unit_types(3998), (5,))
        self.assertEqual(battle_data.pet_race_stats(3998), {"hp": 90})
        projection = battle_data.lower_stage_form(3002)
        self.assertEqual((projection["name"], projection["stage"], projection["stats"]["hp"]),
                         ("当前名字", 2, 101))
        self.assertEqual((self.catalog, self.pets, self.skills), before)

    def test_missing_current_form_fields_stay_unknown(self):
        self.catalog["forms"][0] = {"id": 3001}
        self.assertEqual(battle_data.pet_race_stats(3001), {})
        self.assertEqual(battle_data.pet_unit_types(3001), ())
        self.assertEqual(battle_data.pet_form(3001)["name"], "")
        self.assertNotIn("feature_id", battle_data.pet_form(3001))
        self.assertIsNone(battle_data.pet_stage_info(3001)["stage"])

    def test_current_skill_values_new_ids_and_raw_evidence_are_preserved(self):
        before = deepcopy((self.catalog, self.pets, self.skills))
        info = battle_data.skill_info("7000001")
        self.assertEqual((info["name"], info["power"], info["type_code"], info["energy"],
                          info["kind"], info["damage_type"], info["desc"]),
                         ("当前技能", 120, 5, 0, "magical", 3, "当前描述"))
        self.assertEqual((info["category"], info["damage_rule"], info["historical_fields"]),
                         (1, 15, ["damage_rule"]))
        self.assertEqual(info["snapshot_id"], "current-test")
        self.assertEqual(battle_data.skill_info(7000002)["power"], 50)
        self.assertEqual(battle_data.skill_info(7000002)["category"], 1)
        wish = battle_data.will_impact_skill(3)
        self.assertEqual((wish["power"], wish["energy_cost"], wish["cd"]), (99, 3, 1))
        self.assertEqual(wish["historical_fields"], ["cd"])
        self.assertEqual((self.catalog, self.pets, self.skills), before)

    def test_missing_or_dynamic_skill_values_never_reuse_historical_static_values(self):
        for power in (None, "随生命变化", False):
            with self.subTest(power=power):
                battle_data._cache.clear()
                self.catalog["moves"]["7000001"] = {"id": 7000001, "power": power}
                info = battle_data.skill_info(7000001)
                for field in ("power", "type_code", "energy", "kind", "damage_type"):
                    self.assertIsNone(info[field])
                self.assertEqual((info["name"], info["desc"]), ("", ""))
                self.assertEqual(info["damage_rule"], 15)

    def test_missing_ids_use_explicit_historical_fallback_and_unknown_ids_are_empty(self):
        self.assertEqual(battle_data.pet_form(3999)["data_source"], "historical_external")
        self.assertEqual(battle_data.pet_race_stats(3999), {"hp": 40})
        info = battle_data.skill_info(7000999)
        self.assertEqual((info["power"], info["data_source"]), (45, "historical_external"))
        for value in (99999, None, "unknown"):
            self.assertEqual(battle_data.skill_info(value), {})
            self.assertEqual(battle_data.pet_form(value), {})


if __name__ == "__main__":
    unittest.main()
