"""Versioned source-bound rules; these are not real-game calibration tests."""
from copy import deepcopy
from fractions import Fraction
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
import unittest
from unittest.mock import patch

from lab.ruleset import BwikiRuleset, RuleUnavailable
from lab.server import load_catalog
from lab.rule_config import load_config


class BwikiRulesetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.rules = BwikiRuleset(cls.catalog)

    def test_explicit_dual_weakness_is_three_not_four(self):
        match = self.rules.type_multiplier("武系", 3016)  # 罗隐: 地系|恶系
        self.assertEqual(match["multiplier"], {"numerator": 3, "denominator": 1})
        self.assertEqual(match["relation_key"], "地系|恶系")
        self.assertEqual(match["evidence"]["revision_id"], 7079)
        self.assertFalse(match["real_game_verified"])

    def test_skill_game_id_uses_current_bwiki_numbers(self):
        skill = self.rules.skill(7020440)
        self.assertEqual(skill["power"], 95)  # 触底强击; legacy 65 is not used.
        self.assertEqual(skill["energy"], 4)
        self.assertEqual(skill["kind"], "magical")
        with self.assertRaises(RuleUnavailable):
            self.rules.skill(1)  # Historical SQLite auto IDs are not game IDs.

    def test_attack_energy_recovery_is_not_lost_in_source(self):
        skill = self.rules.skill(7020360)
        self.assertEqual(skill["energy"], 0)
        self.assertEqual(skill["power"], 35)
        self.assertIn("回复1能量", skill["desc"]["zh"])

    def test_every_form_and_attacking_type_has_a_source_bound_match(self):
        total = 0
        for form in self.catalog["forms"]:
            for attacking in self.catalog["types"]:
                value = self.rules.type_multiplier(attacking, form["id"])
                ratio = value["multiplier"]
                self.assertGreaterEqual(Fraction(ratio["numerator"], ratio["denominator"]), 0)
                self.assertEqual(value["relation_key"], form["relation_key"])
                total += 1
        self.assertEqual(total, 633 * 18)

    def test_no_unknown_type_or_form_defaults_to_neutral(self):
        for attacking, form in [("无系别", 3016), ("武", 3016), ("武系", 999999), ("武系", True)]:
            with self.subTest(attacking=attacking, form=form), self.assertRaises(RuleUnavailable):
                self.rules.type_multiplier(attacking, form)

    def test_missing_combination_does_not_multiply_single_type_tables(self):
        c = deepcopy(self.catalog)
        c["chart"].pop("地系|恶系")
        with self.assertRaisesRegex(RuleUnavailable, "不会拼乘"):
            BwikiRuleset(c).type_multiplier("武系", 3016)

    def test_duplicate_or_invalid_chart_entries_rejected(self):
        for value in (True, float("nan"), -2, 1):
            c = deepcopy(self.catalog)
            c["chart"]["地系|恶系"]["weak"][0]["multiplier"] = value
            with self.subTest(value=value), self.assertRaises(RuleUnavailable):
                BwikiRuleset(c).type_multiplier("武系", 3016)
        c = deepcopy(self.catalog)
        c["chart"]["地系|恶系"]["weak"].append({"type": "武系", "multiplier": 2})
        with self.assertRaises(RuleUnavailable):
            BwikiRuleset(c).type_multiplier("武系", 3016)

    def test_source_and_return_values_cannot_mutate_rules(self):
        c = deepcopy(self.catalog)
        rules = BwikiRuleset(c)
        c["moves"]["7020360"]["power"] = 999
        returned = rules.skill(7020360)
        returned["desc"]["zh"] = "changed"
        self.assertEqual(rules.skill(7020360)["power"], 35)
        self.assertIn("回复1能量", rules.skill(7020360)["desc"]["zh"])

    def test_indices_and_identity_use_owned_snapshot_after_source_copy(self):
        source = deepcopy(self.catalog)
        def copy_then_change_source(value):
            copied = deepcopy(value)
            if value is source:
                source["snapshot_id"] = "changed-after-copy"
                source["types"] = []
                source["moves"]["7020360"]["power"] = 999
                source["chart_schema"] = "changed-after-copy"
            return copied
        with patch("lab.ruleset.deepcopy", side_effect=copy_then_change_source):
            rules = BwikiRuleset(source)
        self.assertEqual(rules.snapshot_id, self.catalog["snapshot_id"])
        self.assertEqual(rules.skill(7020360)["power"], 35)
        self.assertEqual(rules.type_multiplier("武系", 3016)["multiplier"], {"numerator": 3, "denominator": 1})
        self.assertEqual(rules.program(7020360)["snapshot_id"], self.catalog["snapshot_id"])

    def test_terms_retain_raw_text_not_unproven_rounding(self):
        burn = self.rules.term(1002)
        self.assertIn("2%", burn["definition"])
        self.assertIn("衰减一半层数", burn["definition"])
        self.assertNotIn("floor", burn)
        with self.assertRaises(RuleUnavailable):
            self.rules.term(999999)

    def test_missing_revision_is_an_error(self):
        c = deepcopy(self.catalog)
        del c["provenance"]["Types"]
        with self.assertRaises(RuleUnavailable):
            BwikiRuleset(c).type_multiplier("武系", 3016)

    def test_programs_are_not_executable_or_training_ready(self):
        p = self.rules.plan(7020360, 3016)
        self.assertFalse(p["battle_executable"])
        self.assertFalse(p["training_eligible"])
        self.assertFalse(p["program"]["executable"])
        self.assertEqual(p["skill"]["id"], 7020360)

    def test_repeated_single_program_plans_compile_once_without_copying_full_artifact(self):
        rules = BwikiRuleset(self.catalog)
        with patch("lab.rule_config.load_config", wraps=load_config) as compile_spy:
            with patch.object(rules, "programs", side_effect=AssertionError("full artifact must not be copied by plan")):
                first = rules.plan(7020360)
                second = rules.plan(7020360)
                another = rules.program(7020640)
            self.assertEqual(first, second)
            self.assertEqual(another["game_id"], 7020640)
            self.assertEqual(compile_spy.call_count, 1)
            self.assertEqual(rules.programs()["skills"]["7020360"], first["program"])
            self.assertEqual(compile_spy.call_count, 1)

    def test_program_and_full_artifact_outputs_cannot_poison_each_other(self):
        rules = BwikiRuleset(self.catalog)
        expected = rules.program(7020360)
        returned = rules.program(7020360)
        returned["operations"][0]["params"]["power"] = 999
        returned["skill_source"]["revision_id"] = -1
        all_programs = rules.programs()
        all_programs["skills"]["7020360"]["operations"].clear()
        all_programs["skills"].clear()
        self.assertEqual(rules.program(7020360), expected)
        self.assertEqual(rules.plan(7020360)["program"], expected)

    def test_program_lookup_rejects_unknown_or_invalid_ids_before_compiling(self):
        rules = BwikiRuleset(self.catalog)
        with patch("lab.rule_config.load_config", wraps=load_config) as compile_spy:
            for key in (0, True, "", "not-an-id", 999999):
                with self.subTest(key=key), self.assertRaises(RuleUnavailable):
                    rules.program(key)
            self.assertEqual(compile_spy.call_count, 0)

    def test_concurrent_first_lookups_publish_one_complete_detached_cache(self):
        rules = BwikiRuleset(self.catalog)
        barrier, started, release = Barrier(6), Event(), Event()
        def compile_once(catalog):
            started.set()
            if not release.wait(15):
                raise RuntimeError("test did not release first compilation")
            return load_config(catalog)
        def lookup(_):
            barrier.wait(timeout=15)
            return rules.program(7020360)
        with patch("lab.rule_config.load_config", side_effect=compile_once) as compile_spy:
            with ThreadPoolExecutor(max_workers=6) as executor:
                futures = [executor.submit(lookup, i) for i in range(6)]
                try:
                    self.assertTrue(started.wait(15))
                finally:
                    release.set()
                results = [f.result(timeout=15) for f in futures]
            self.assertEqual(compile_spy.call_count, 1)
        self.assertTrue(all(p == results[0] for p in results))
        results[0]["operations"].clear()
        self.assertTrue(results[1]["operations"])
        self.assertEqual(rules.program(7020360), results[1])

    def test_failed_compilation_is_not_published_and_can_retry(self):
        rules = BwikiRuleset(self.catalog)
        with patch("lab.rule_config.load_config", side_effect=ValueError("synthetic compile failure")):
            with self.assertRaisesRegex(ValueError, "synthetic compile failure"):
                rules.program(7020360)
        self.assertEqual(rules.program(7020360)["game_id"], 7020360)


if __name__ == "__main__":
    unittest.main()
