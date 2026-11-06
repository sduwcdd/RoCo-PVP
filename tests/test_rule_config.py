"""Migration/schema regressions, not evidence of game calibration."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from lab.rule_config import (ROOT, ConfigError, build_config, load_bundle, load_config,
                             rule_to_program, validate_config, validate_effect, validate_rule)
from lab.server import load_catalog


class RuleConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.folder = ROOT / "data" / "rules" / cls.catalog["snapshot_id"]
        cls.legacy = json.loads((cls.folder / "bwiki-declarative-6.json").read_text(encoding="utf-8"))
        cls.bundle = load_bundle(cls.catalog)

    def test_all_825_configs_static_validate_and_keep_four_capability_levels(self):
        self.assertEqual(validate_config(self.bundle, self.catalog), [])
        records = self.bundle["records"]
        self.assertEqual([len(records[k]) for k in ("skills", "traits")], [579, 246])
        self.assertEqual(sum(x["capabilities"]["description_structured"] for x in records["skills"].values()), 172)
        self.assertEqual(sum(x["capabilities"]["isolated_components_supported"] for x in records["skills"].values()), 168)
        for rules in records.values():
            for rule in rules.values():
                self.assertFalse(rule["capabilities"]["full_battle_executable"])
                self.assertFalse(rule["capabilities"]["real_game_calibrated"])

    def test_all_legacy_programs_and_header_roundtrip_exactly(self):
        loaded = load_config(self.catalog)
        expected = deepcopy(self.legacy)
        expected.pop("snapshot_sha256")
        self.assertEqual(loaded, expected)
        for category in ("skills", "traits"):
            for key, program in self.legacy[category].items():
                self.assertEqual(rule_to_program(self.bundle["records"][category][key]), program)

    def test_offline_migration_is_deterministic_without_natural_language_compilation(self):
        with patch("lab.skill_programs.compile_catalog", side_effect=AssertionError("runtime NLP forbidden")):
            self.assertEqual(build_config(self.catalog, self.legacy), self.bundle)
            self.assertEqual(load_bundle(self.catalog), self.bundle)
            self.assertEqual(load_config(self.catalog)["skills"], self.legacy["skills"])

    def test_components_are_the_only_ordered_effect_source(self):
        rule = deepcopy(self.bundle["records"]["skills"]["7170280"])
        self.assertNotIn("operations", rule["program"])
        self.assertEqual([c["effect"] for c in rule["components"]], ["stat.modify", "energy.reduce"])
        self.assertEqual([c["target"] for c in rule["components"]], ["opponent", "opponent"])
        rule["components"][1]["params"]["amount"] = 4
        self.assertEqual(rule_to_program(rule)["operations"][1]["params"]["amount"], 4)
        # A syntactically valid edit is a candidate configuration, not evidence
        # that the original source says 4. Published checksums bind approved data.
        self.assertEqual(validate_rule(rule), [])

    def test_source_fields_and_component_uncertainty_cannot_disappear(self):
        for mutate in (lambda r: r["components"][0]["evidence"].update(raw_text="changed"),
                       lambda r: r["components"][0]["uncertainties"].clear(),
                       lambda r: r["constraints"].update(cooldown={"status": "known", "value": 0}),
                       lambda r: r["capabilities"].update(real_game_calibrated=True)):
            rule = deepcopy(self.bundle["records"]["skills"]["7170280"])
            mutate(rule)
            self.assertTrue(validate_rule(rule))

    def test_invalid_primitives_are_rejected_statically(self):
        for op, target, params in (("energy.reduce", "opponent", {"amount": True}),
                                  ("energy.reduce", "opponent", {"amount": -1}),
                                  ("energy.reduce", "opponent", {"amount": 2, "ignored": 9}),
                                  ("energy.reduce", "whole_team", {"amount": 2}),
                                  ("energy.steal", "opponent", {"amount": 2}),
                                  ("stat.modify", "opponent", {"attributes": ["mdef", "mdef"], "percent": {"numerator": -50, "denominator": 100}}),
                                  ("hp.restore", "self", {"percent": {"numerator": 10, "denominator": 0}})):
            with self.subTest(op=op, target=target, params=params), self.assertRaises(ConfigError):
                validate_effect(op, target, params)

    def test_unknown_fields_and_duplicate_component_identity_are_not_ignored(self):
        for mutate in (lambda r: r.update(unhandled=True),
                       lambda r: r["components"][0].update(unhandled=True),
                       lambda r: r["program"].update(operations=[]),
                       lambda r: r["components"][1].update(id="effect:0")):
            rule = deepcopy(self.bundle["records"]["skills"]["7170280"])
            mutate(rule)
            self.assertTrue(validate_rule(rule))

    def test_blocked_descriptions_never_expose_partial_executable_components(self):
        rule = next(deepcopy(r) for r in self.bundle["records"]["skills"].values() if r["program"]["status"] == "unsupported")
        self.assertEqual(rule["components"], [])
        self.assertFalse(rule["capabilities"]["description_structured"])
        rule["components"] = deepcopy(self.bundle["records"]["skills"]["7170280"]["components"])
        self.assertTrue(validate_rule(rule))

    def test_source_changes_require_republication_not_runtime_reparse(self):
        for mutate in (lambda c: c["moves"]["7170280"]["desc"].update(zh="changed"),
                       lambda c: c["moves"]["7170280"].update(energy=99),
                       lambda c: c["glossary"][0].update(definition="changed"),
                       lambda c: c["provenance"]["Terms"].update(revision_id=-1)):
            catalog = deepcopy(self.catalog)
            mutate(catalog)
            with patch("lab.skill_programs.compile_catalog", side_effect=AssertionError("no fallback")):
                with self.assertRaisesRegex(ConfigError, "source fingerprint"):
                    load_bundle(catalog)

    def test_forms_and_chart_changes_are_left_to_their_separate_validator(self):
        catalog = deepcopy(self.catalog)
        catalog["forms"][0]["stats"]["hp"] += 1
        catalog["chart"] = {}
        self.assertEqual(load_bundle(catalog), self.bundle)
        self.assertNotEqual(self.bundle["catalog_content_hash"], "")

    def test_whole_config_identity_missing_records_and_count_lies_rejected(self):
        for mutate in (lambda b: b["records"]["skills"].pop("7170280"),
                       lambda b: b["artifact_header"]["counts"]["skills"].update(compiled=579),
                       lambda b: b["records"]["skills"]["7170280"]["program"].update(game_id=1),
                       lambda b: b["records"]["skills"]["7170280"]["program"].update(source_description="fake")):
            bundle = deepcopy(self.bundle)
            mutate(bundle)
            self.assertTrue(validate_config(bundle, self.catalog))

    def test_loaded_data_and_compatibility_views_do_not_share_mutable_state(self):
        bundle = load_bundle(self.catalog)
        rule = bundle["records"]["skills"]["7170280"]
        program = rule_to_program(rule)
        program["operations"].clear()
        rule["components"][0]["params"]["attributes"].clear()
        self.assertEqual(load_bundle(self.catalog), self.bundle)
        self.assertEqual(load_config(self.catalog)["skills"]["7170280"], self.legacy["skills"]["7170280"])

    def test_published_checksum_missing_config_and_snapshot_path_are_fail_closed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "data" / "rules" / self.catalog["snapshot_id"]
            folder.mkdir(parents=True)
            for name in ("rule-config-1.json", "rule-config-1.manifest.json"):
                (folder / name).write_bytes((self.folder / name).read_bytes())
            with patch("lab.rule_config.ROOT", root):
                self.assertEqual(load_bundle(self.catalog), self.bundle)
                (folder / "rule-config-1.json").write_text("{}", encoding="utf-8")
                with self.assertRaisesRegex(ConfigError, "checksum"):
                    load_bundle(self.catalog)
                (folder / "rule-config-1.json").unlink()
                with self.assertRaisesRegex(ConfigError, "unavailable"):
                    load_bundle(self.catalog)
        for snapshot in ("../escape", "..\\escape", "D:escape", "", ".", ".."):
            catalog = deepcopy(self.catalog)
            catalog["snapshot_id"] = snapshot
            with self.assertRaisesRegex(ConfigError, "path identifier"):
                load_bundle(catalog)

    def test_dynamic_conditions_and_expressions_cannot_be_erased_by_legacy_adapter(self):
        rule = deepcopy(self.bundle["records"]["skills"]["7170280"])
        rule["components"][1]["when"] = {"compare": "lte", "left": {"read": {"target": "opponent", "field": "energy"}}, "right": {"const": 2}}
        with self.assertRaisesRegex(ConfigError, "cannot discard"):
            rule_to_program(rule)
        rule["components"][1].pop("when")
        rule["components"][1]["params"]["amount"] = {"expr": {"const": 3}}
        with self.assertRaisesRegex(ConfigError, "cannot discard"):
            rule_to_program(rule)

    def test_dynamic_component_condition_and_integer_expression_schema(self):
        rule = deepcopy(self.bundle["records"]["skills"]["7170280"])
        component = rule["components"][1]
        component["when"] = {"compare": "lte", "left": {"read": {"target": "opponent", "field": "energy"}}, "right": {"const": 2}}
        component["params"]["amount"] = {"expr": {"op": "add", "args": [{"const": 1}, {"const": 2}]}}
        self.assertEqual(validate_rule(rule), [])
        component["when"]["compare"] = "eval"
        self.assertTrue(validate_rule(rule))
        component.pop("when")
        component["params"]["amount"] = {"expr": {"read": {"target": "opponent", "field": "__class__"}}}
        self.assertTrue(validate_rule(rule))


if __name__ == "__main__": unittest.main()
