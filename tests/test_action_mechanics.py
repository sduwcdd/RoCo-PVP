"""Candidate scope and source limitations remain visible to the action recorder."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from lab.action_mechanics import CLEVER_TERM, build_action_mechanics
from lab.bwiki import load_catalog


def move(sid, desc, kind="status", type_name="普通系", name="测试"):
    return {"id": sid, "name": {"zh": name}, "desc": {"zh": desc},
            "kind": kind, "type": type_name, "source_url": "https://example.invalid/source"}


def catalog(*moves):
    return {"snapshot_id": "test-snapshot", "source_version": "test-version", "moves": list(moves),
            "glossary": [{"key": 3011, "definition": CLEVER_TERM}]}


class ActionMechanicsTests(unittest.TestCase):
    def test_generator_scopes_are_distinct_and_preserve_entire_source(self):
        c = load_catalog()
        r = build_action_mechanics(c)
        self.assertEqual(r["generators"]["7020840"]["scope"], "other_allies_carried")
        self.assertEqual(r["generators"]["7020850"]["scope"], "opponent_team_learnsets")
        self.assertEqual(r["generators"]["7020860"]["scope"], "self_learnset_minus_carried")
        self.assertEqual(r["generators"]["7020860"]["raw"], c["moves"]["7020860"])
        self.assertFalse(r["server_semantics_verified"])
        json.dumps(r, ensure_ascii=False, allow_nan=False)

    def test_type_and_kind_filter_excludes_unrelated_moves_and_retains_other_clauses(self):
        source = move(7050510, "驱散自己的减益，自己每有1层减益，本技能能耗-1，巧变：水系攻击技能。", type_name="水系")
        c = catalog(source, move(1, "造成物伤。", "physical", "水系"),
                    move(2, "造成魔伤。", "magical", "水系"), move(3, "防御。", "defense", "水系"),
                    move(4, "造成魔伤。", "magical", "火系"))
        r = build_action_mechanics(c)["transformations"]["7050510"]
        self.assertEqual(r["pool_ids"], [1, 2])
        self.assertEqual(r["pool_basis"], "catalog_metadata_candidates")
        self.assertEqual(r["raw"], source)
        self.assertTrue(r["uncertainty"])
        self.assertEqual(r["trigger"], {"event": "after_use"})
        self.assertTrue(r["temporary_return"])
        self.assertEqual(r["return_trigger"]["event"], "after_generated_skill_use")

    def test_new_description_or_missing_term_cannot_claim_same_support(self):
        for c in [catalog(move(7021220, "造成魔法伤害，巧变：魔攻技能。额外条件。")),
                  {"moves": [move(7021220, "造成魔法伤害，巧变：魔攻技能。")]}]:
            r = build_action_mechanics(c)["transformations"]["7021220"]
            self.assertEqual(r["status"], "blocked")
            self.assertEqual(r["pool_ids"], [])
            self.assertTrue(r["blockers"])

    def test_related_pools_use_bounded_historical_evidence_not_all_skills(self):
        r = build_action_mechanics(load_catalog())["transformations"]
        for sid in ("7090440", "7180430"):
            self.assertEqual(r[sid]["status"], "supported")
            self.assertEqual(r[sid]["pool_ids"], r[sid]["historical_pool_ids"])
            self.assertIn("_3_P", " ".join(r[sid]["uncertainty"]))
            self.assertEqual(r[sid]["pool_authority"], "historical_game_file_candidates")
            self.assertGreater(len(r[sid]["historical_pool_ids"]), 0)
            self.assertIn("_2_P", r[sid]["historical_pool"]["binary_pak"])
            self.assertEqual(r[sid]["historical_pool"]["raw"]["id"], 21 if sid == "7090440" else 24)
            self.assertEqual(len(r[sid]["pool_ids"]), 10 if sid == "7090440" else 8)

    def test_missing_game_evidence_retains_specific_blocker(self):
        with patch("lab.action_mechanics._evidence", return_value=None):
            r = build_action_mechanics(load_catalog())["transformations"]["7180430"]
        self.assertEqual(r["pool_ids"], [])
        self.assertEqual(r["status"], "blocked")
        self.assertNotIn("historical_pool_ids", r)

    def test_response_replacements_require_success_and_choice_not_selection_alone(self):
        r = build_action_mechanics(load_catalog())["transformations"]
        mirror, lens = r["7060150"], r["7060260"]
        self.assertEqual(mirror["trigger"], {"event": "response_success", "response_kind": "attack", "choice_required": False})
        self.assertEqual(mirror["scope"], "self_slot")
        self.assertEqual(mirror["replacement_source"], "opponent_selected_skill")
        self.assertEqual(lens["scope"], "opponent_slot")
        self.assertTrue(lens["trigger"]["choice_required"])
        self.assertEqual(lens["trigger"]["response_kind"], "status")
        self.assertEqual(lens["replacement_id"], 7060230)
        self.assertEqual(lens["permanence"], "not_explicitly_stated")
        self.assertIn("battleCard.skillRoundData[key] = info.skill_data", lens["slot_update_source"]["raw"])

    def test_named_target_must_exist_unambiguously(self):
        m = move(7060260, "造成物伤，选择：敌方携带光系技能时威力+50或应对状态时被应对的技能变为透射。")
        r = build_action_mechanics(catalog(m))["transformations"]["7060260"]
        self.assertEqual(r["status"], "blocked")
        self.assertNotIn("replacement_id", r)

    def test_weather_records_only_exact_unconditional_duration(self):
        c = catalog(move(1, "将天气改为雨天，持续8回合。"),
                    move(2, "将天气改为雨天，持续8回合。仅在成功时。"),
                    move(3, "造成物伤，天气为雨天时，本技能能耗-2。"))
        r = build_action_mechanics(c)["weather"]
        self.assertEqual((r["1"]["kind"], r["1"]["duration"]), ("rain", 8))
        self.assertEqual(r["2"]["status"], "blocked")
        self.assertIsNone(r["2"]["duration"])
        self.assertNotIn("3", r)

    def test_reviewed_response_energy_is_exposed_without_reparsing_prose(self):
        row = build_action_mechanics(load_catalog())["response_energy"]["7170100"]
        self.assertEqual(row["name"], "惊吓盒子")
        self.assertEqual(row["response_kinds"], ["status"])
        self.assertEqual(row["effects"], [{"op": "energy.reduce", "target": "opponent", "amount": 6,
                                           "event": "after.damage", "when": "response.success"}])
        self.assertTrue(row["record_hash"])

    def test_result_cannot_mutate_catalog_source_or_other_build(self):
        c = catalog(move(7020840, "每回合随机变成己方队伍中其他精灵的技能。"))
        before = deepcopy(c)
        a = build_action_mechanics(c)
        a["generators"]["7020840"]["raw"]["name"]["zh"] = "changed"
        self.assertEqual(c, before)
        self.assertEqual(build_action_mechanics(c)["generators"]["7020840"]["name"], "测试")


if __name__ == "__main__":
    unittest.main()
