"""File evidence, opaque parameter and candidate gating regressions."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import tempfile
import unittest

from lab.game_rule_candidates import (TABLES, load_evidence, build_candidates, validate_candidates,
    digest, fields, reference, bounded_reader, publish_candidates, load_field_bindings)
from lab.server import load_catalog
from lab.rule_config import validate_config

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "artifacts/unpack_probe_20261025/battle_analysis"


def synthetic():
    tables = {name: {} for name in TABLES}
    tables["SKILL_CONF"]["1"] = {"id": 1, "energy_cost": [0], "skill_priority": 5,
        "skill_result": [{"effect_id": 10, "cast_moment": 7}, {}, {"effect_id": 0}, {"effect_id": 10, "cast_moment": 7}]}
    tables["EFFECT_CONF"]["10"] = {"id": 10, "effect_order": 19, "effect_param": [{"params": [-3, 0]}, {}, {"params": [1]}]}
    return {"source_id": "synthetic-not-game", "tables": tables, "provenance": {}, "validation": {},
            "table_sources": {name: {"schema": {"UniqueKey": "id"}, "rows_content_sha256": digest(rows)}
                             for name, rows in tables.items()}}


class CandidateUnitTests(unittest.TestCase):
    def test_missing_zero_null_and_empty_array_remain_distinct(self):
        self.assertEqual(fields({"zero": 0, "null": None, "empty": []}, ["absent", "zero", "null", "empty"]),
                         {"absent": {"present": False}, "zero": {"present": True, "value": 0},
                          "null": {"present": True, "value": None}, "empty": {"present": True, "value": []}})

    def test_slots_duplicates_negative_parameters_and_domains_are_preserved(self):
        evidence = synthetic()
        result = build_candidates(evidence, {"moves": {}})
        self.assertEqual(validate_candidates(result), [])
        components = result["skills"]["1"]["components"]
        refs = [c for c in components if c["role"] == "result_reference"]
        self.assertEqual([c["reference"]["index"] for c in refs], [0, 1, 2, 3])
        self.assertEqual([c["reference"]["status"] for c in refs], ["resolved", "absent_id", "explicit_zero", "resolved"])
        self.assertEqual(refs[0]["trigger_domain"], "SKILL_CONF.skill_result.cast_moment")
        self.assertEqual(result["nodes"]["EFFECT_CONF:10"]["raw"], evidence["tables"]["EFFECT_CONF"]["10"])
        self.assertEqual(components[0]["raw_fields"]["energy_rule"], {"present": False})
        self.assertEqual(components[3]["raw_fields"]["skill_priority"], {"present": True, "value": 5})
        self.assertIsNone(components[3]["params"])
        self.assertFalse(result["skills"]["1"]["capabilities"]["components_executable"])

    def test_id_collisions_missing_references_and_bool_ids_do_not_silently_resolve(self):
        e = synthetic()
        e["tables"]["BUFF_CONF"]["10"] = {"id": 10}
        self.assertEqual(reference(e["tables"], ("EFFECT_CONF", "BUFF_CONF"), 10)["status"], "ambiguous")
        self.assertEqual(reference(e["tables"], ("EFFECT_CONF",), 100)["status"], "missing")
        self.assertEqual(reference(e["tables"], ("EFFECT_CONF",), True)["status"], "invalid_id")

    def test_input_and_result_are_isolated_and_generation_is_deterministic(self):
        e = synthetic(); before = deepcopy(e)
        a = build_candidates(e, {"moves": {}}); b = build_candidates(e, {"moves": {}})
        self.assertEqual(a, b)
        a["nodes"]["EFFECT_CONF:10"]["raw"]["effect_param"][0]["params"].clear()
        self.assertEqual(e, before)
        self.assertEqual(b, build_candidates(e, {"moves": {}}))
        self.assertTrue(validate_candidates(a))

    def test_raw_value_mutation_domain_change_and_false_execution_claim_rejected(self):
        original = build_candidates(synthetic(), {"moves": {}})
        for mutation in (lambda b: b.update(training_eligible=True),
                         lambda b: b["skills"]["1"]["components"][0]["raw_fields"]["energy_rule"].update(present=True, value=0),
                         lambda b: b["skills"]["1"]["components"][5].update(trigger_domain="BUFFBASE_CONF.trigger_type"),
                         lambda b: b["skills"]["1"]["capabilities"].update(runtime_rule_validated=True),
                         lambda b: b["skills"]["1"]["components"].reverse()):
            b = deepcopy(original); mutation(b)
            self.assertTrue(validate_candidates(b))

    def test_publication_is_idempotent_but_never_overwrites_different_candidate(self):
        bundle = build_candidates(synthetic(), {"moves": {}})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "candidate.json"
            self.assertEqual(publish_candidates(bundle, path), publish_candidates(bundle, path))
            before = path.read_bytes()
            bundle["source_provenance"]["different_review"] = True
            with self.assertRaisesRegex(ValueError, "revision"): publish_candidates(bundle, path)
            self.assertEqual(path.read_bytes(), before)

    def test_multiskill_reference_validation_and_graph_tampering(self):
        evidence = synthetic()
        evidence["tables"]["SKILL_CONF"]["2"] = {"id": 2, "skill_result": [{}]}
        evidence["table_sources"]["SKILL_CONF"]["rows_content_sha256"] = digest(evidence["tables"]["SKILL_CONF"])
        original = build_candidates(evidence, {})
        self.assertEqual(validate_candidates(original), [])
        mutations = [
            lambda b: b["nodes"]["SKILL_CONF:1"]["references"][0].update(targets=["SKILL_CONF:2"]),
            lambda b: b["nodes"]["SKILL_CONF:1"]["references"].clear(),
            lambda b: b["reference_counts"].update({"SKILL_CONF.references.resolved": 900}),
            lambda b: b["skills"]["1"]["components"][0]["raw_fields"].pop("energy_cost"),
            lambda b: b["skills"]["1"]["components"][5]["reference"].update(id_present=False),
            lambda b: b["skills"]["1"]["components"][5].update(role="forged"),
            lambda b: b["skills"]["1"]["components"][0].update(params={"guessed": 1}),
            lambda b: b["skills"]["1"]["capabilities"].update(references_resolved=True),
        ]
        for index, mutation in enumerate(mutations):
            with self.subTest(mutation=index):
                changed = deepcopy(original); mutation(changed)
                self.assertTrue(validate_candidates(changed))

    def test_json_number_bool_float_types_cannot_be_substituted(self):
        original = build_candidates(synthetic(), {})
        for value in (False, 0.0):
            with self.subTest(value_type=type(value).__name__):
                b = deepcopy(original)
                b["skills"]["1"]["components"][0]["raw_fields"]["energy_cost"]["value"] = [value]
                self.assertTrue(validate_candidates(b))

    def test_bwiki_trait_ids_are_not_mislabeled_as_moves(self):
        e = synthetic()
        catalog = {"traits": {"1": {"id": 1, "name": "synthetic-trait"}}}
        b = build_candidates(e, catalog)
        self.assertEqual(b["skills"]["1"]["bwiki_comparison"]["record_kind"], "traits")
        catalog["moves"] = catalog["traits"]
        b = build_candidates(e, catalog)
        self.assertEqual(b["skills"]["1"]["bwiki_comparison"]["status"], "ambiguous_bwiki_record_kind")

    def test_bound_reader_rejects_negative_cursor_and_directory_offsets(self):
        path = ANALYSIS.parent / "parse_roco_tables.py"
        spec = importlib.util.spec_from_file_location("test_pinned_bin_probe", path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        cls = bounded_reader(module.Bin)
        reader = cls.__new__(cls); reader.b = bytes(range(16)); reader.p = -2
        with self.assertRaises(ValueError): reader.read(1)
        for offset, count in ((-1, 1), (0, -1), (1, 1), (17, 0)):
            with self.assertRaises(ValueError): reader.entries(offset, count)

    def test_bwiki_numeric_comparison_does_not_establish_semantic_equivalence(self):
        e = synthetic()
        b = build_candidates(e, {"snapshot_id": "wiki", "moves": {"1": {"id": 1, "energy": 0, "power": 1}}})
        comparison = b["skills"]["1"]["bwiki_comparison"]
        self.assertEqual(comparison["fields"]["energy_cost"]["status"], "numeric_equal")
        self.assertFalse(comparison["fields"]["energy_cost"]["semantic_equivalence_verified"])
        self.assertEqual(comparison["fields"]["dam_para"]["status"], "not_comparable")

    def test_field_binding_rejects_cross_domain_and_unverified_code(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "binding.json"
            path.write_text(json.dumps({"field_bindings": {"SKILL_CONF.skill_result.cast_moment": {}}}))
            with self.assertRaisesRegex(ValueError, "domain"): load_field_bindings(path, folder)
            path.write_text(json.dumps({"field_bindings": {"EFFECT_CONF.effect_order": {"mapping": {}}}}))
            with self.assertRaisesRegex(ValueError, "evidence"): load_field_bindings(path, folder)


class ActualGameEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = load_evidence(ANALYSIS)
        cls.catalog = load_catalog()[0]
        cls.bundle = build_candidates(cls.evidence, cls.catalog)

    def test_eight_tables_reparse_and_all_nonzero_references_resolve(self):
        b = self.bundle
        self.assertEqual(len(b["nodes"]), 17578)
        self.assertEqual(len(b["skills"]), 1988)
        self.assertTrue(self.evidence["validation"]["binary_json_parity"])
        self.assertEqual(b["reference_counts"]["SKILL_CONF.references.resolved"], 3445)
        self.assertEqual(b["reference_counts"]["SKILL_CONF.targets.EFFECT_CONF"], 1457)
        self.assertEqual(b["reference_counts"]["SKILL_CONF.targets.BUFF_CONF"], 1988)
        self.assertEqual(b["reference_counts"]["SKILL_CONF.references.absent_id"], 3041)
        self.assertEqual(b["reference_counts"]["BUFF_CONF.references.resolved"], 4603)
        self.assertEqual(b["reference_counts"]["BUFF_CONF.references.explicit_zero"], 1)
        self.assertEqual(validate_candidates(b), [])

    def test_representative_skills_preserve_source_values_and_nested_effect_order(self):
        b = self.bundle
        self.assertEqual(b["nodes"]["SKILL_CONF:7060200"]["raw"]["dam_para"], [100])
        self.assertEqual(b["nodes"]["SKILL_CONF:7150080"]["raw"]["energy_cost"], [3])
        self.assertEqual(b["nodes"]["SKILL_CONF:7170280"]["raw"]["skill_result"],
                         [{"effect_id": 20010080, "cast_moment": 11}, {"effect_id": 1019013, "cast_moment": 11}])
        self.assertEqual(b["nodes"]["EFFECT_CONF:1019013"]["raw"]["effect_param"][0]["params"], [-3])
        self.assertNotIn("energy_rule", b["nodes"]["SKILL_CONF:7150080"]["raw"])

    def test_candidate_schema_cannot_enter_current_active_rules(self):
        self.assertTrue(validate_config(self.bundle, self.catalog))
        self.assertFalse(self.bundle["training_eligible"])
        self.assertFalse(self.bundle["active_rules_modified"])
        self.assertEqual(self.bundle["capability_counts"]["runtime_rules_validated"], 0)

    def test_all_bwiki_skill_ids_match_without_asserting_all_game_skills_are_pvp(self):
        matches = [r for r in self.bundle["skills"].values() if r["bwiki_comparison"]["status"] == "same_game_id"]
        self.assertEqual(sum(r["bwiki_comparison"]["record_kind"] == "moves" for r in matches), 579)
        self.assertEqual(sum(r["bwiki_comparison"]["record_kind"] == "traits" for r in matches), 246)
        self.assertTrue(all(r["bwiki_comparison"]["active_pvp_eligibility"] == "unknown" for r in self.bundle["skills"].values()))

    def test_hash_verified_handler_bindings_do_not_promote_parameter_semantics(self):
        bindings = load_field_bindings(ROOT / "docs/verification/game-config-semantics-20261025.json", ROOT)
        b = build_candidates(self.evidence, self.catalog, bindings)
        self.assertEqual(validate_candidates(b), [])
        energy = b["nodes"]["EFFECT_CONF:1019013"]["handler_annotation"]
        self.assertEqual(energy["symbol"], "ET_CHANGE_ENERGY")
        self.assertFalse(energy["parameter_semantics_verified"])
        attr = b["nodes"]["BUFFBASE_CONF:2001008"]["handler_annotation"]
        self.assertEqual(attr["symbol"], "BFT_ATTR_CHANGE")
        self.assertFalse(attr["execution_order_verified"])
        self.assertNotIn("BUFFBASE_CONF.trigger_type", bindings)
