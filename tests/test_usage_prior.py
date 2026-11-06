"""Ladder usage snapshot -> builds, priors and complete roster records."""
from __future__ import annotations

import unittest

from lab import server
from lab.usage_prior import UsageError, UsageTable


class UsagePriorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog, _, _ = server.load_catalog()[:3]
        cls.table = UsageTable()

    def learnset(self, form_id):
        detail = (self.catalog.get("details") or {}).get(str(form_id)) or {}
        return {int(x) for x in (detail.get("learnset") or {}).get("pool") or []}

    def test_build_matches_snapshot_and_stays_inside_learnset(self):
        build = self.table.build(3001, 3001, self.catalog)
        self.assertEqual(build["pet_name"], "喵喵")
        self.assertEqual(build["nature"]["id"], 30)
        self.assertEqual(build["nature"]["name"], "踏实")
        self.assertTrue(build["nature"]["matched_catalog"])
        self.assertEqual(build["bloodline"]["name"], "草")
        self.assertEqual(build["bloodline"]["id"], 2)
        self.assertEqual(len(build["moves"]), 4)
        pool = self.learnset(3001)
        for move_id in build["moves"]:
            self.assertIn(move_id, pool, "填充的技能必须在该形态学习池内")
        for skipped in build["skipped"]:
            if skipped["id"]:
                self.assertNotIn(skipped["id"], pool)

    def test_individuals_take_top_three_and_leave_the_rest_unknown(self):
        build = self.table.build(3001, 3001, self.catalog)
        chosen = [d for d, v in build["talents"].items() if v == 10]
        self.assertEqual(len(chosen), 3)
        self.assertEqual(chosen, ["hp", "patk", "pdef"])
        self.assertEqual([row["dimension"] for row in build["talent_ranking"][:3]], chosen)

    def test_pet_without_data_fails_closed(self):
        with self.assertRaises(UsageError):
            self.table.build(3009, 3009, self.catalog)

    def test_provenance_is_marked_as_population_statistics(self):
        build = self.table.build(3001, 3001, self.catalog)
        self.assertTrue(build["provenance"]["population_statistics"])
        self.assertFalse(build["provenance"]["joint_distribution"])
        self.assertEqual(build["provenance"]["mode"], "pvp")
        self.assertTrue(build["provenance"]["collected_at"].startswith("2026-09-28"))

    def test_prior_candidates_use_nature_share_as_weight(self):
        rows = self.table.prior_candidates(3001, 3001, self.catalog, nature_limit=3)
        self.assertEqual(rows[0]["nature_id"], 30)
        self.assertAlmostEqual(rows[0]["prior"], 62.86, places=2)
        self.assertEqual(rows[0]["prior_basis"], "ladder_nature_share")
        for row in rows:
            self.assertEqual(len(row["moves"]), 4)
            self.assertEqual(set(row["talents"]), {"hp", "patk", "matk", "pdef", "mdef", "spd"})
            for value in row["talents"].values():
                self.assertIsInstance(value, int)

    def test_roster_member_is_env_shaped(self):
        member = self.table.roster_member(3001, 3001, self.catalog)
        self.assertEqual(member["form_id"], 3001)
        self.assertEqual(member["nature_id"], 30)
        self.assertEqual(len(member["move_ids"]), 4)
        selection = member["talent_selection"]
        self.assertEqual(len(selection["selected"]), 3)
        for dim in selection["selected"]:
            self.assertEqual(selection["values"][dim], 10)
        for marker in member["team_code"]["raw_markers"]:
            self.assertTrue(79 <= marker <= 84)
        self.assertEqual(member["usage_provenance"]["base_id"], 3001)

    def test_roster_rejects_empty_input_by_building_each_member(self):
        roster = self.table.roster([3001, 3002], self.catalog)
        self.assertEqual([m["form_id"] for m in roster], [3001, 3002])

    def test_find_returns_named_rows(self):
        rows = self.table.find("喵喵")
        self.assertEqual(rows[0]["base_id"], 3001)
        self.assertEqual(rows[0]["top_skill"]["name"], "藤绞")


if __name__ == "__main__":
    unittest.main()
