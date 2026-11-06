"""Layer operands, archive isolation, source bytes and unresolved runtime semantics."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from lab.game_rule_candidates import digest, read_json, file_hash
from lab.game_layer_references import (TABLES, field_operand, load_archive_variants,
    load_resource_group_variants, build_layer_references, validate_layer_references, save_layer_references)

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "artifacts/unpack_probe_20261025"
MANIFESTS = [ROOT / "artifacts/strength_buff_probe_20261025/historical_table_manifest.json",
             ROOT / "artifacts/layer_reference_probe_20261025/manifest.json"]


def fixture(source_id="base", declare_layers=True):
    descriptors = [{"Name": "effect_id", "Type": "EUint32"}, {"Name": "cast_moment", "Type": "EInt32"}]
    if declare_layers:
        descriptors += [{"Name": "buff_group_level", "Type": "EUint32"},
                        {"Name": "buff_level_rule", "Type": "EInt32"}]
    references = [{"effect_id": 10, "buff_group_level": 5, "buff_level_rule": 2}, {},
                  {"effect_id": 0}, {"effect_id": 10, "buff_group_level": 0}, {"effect_id": 999}]
    if not declare_layers:
        references = [{k: v for k, v in r.items() if k not in ("buff_group_level", "buff_level_rule")} for r in references]
    tables = {"SKILL_CONF": {"1": {"id": 1, "skill_result": references}},
              "BUFF_CONF": {"10": {"id": 10, "buff_base_ids": [20, 0, 20], "add_max": 99}},
              "BUFFBASE_CONF": {"20": {"id": 20, "buffbase_param": [{"params": [1000]}]}},
              "EFFECT_CONF": {}}
    sources = {name: {"rows_content_sha256": digest(rows), "schema": {"UniqueKey": "id", "Properties": []}}
               for name, rows in tables.items()}
    sources["SKILL_CONF"]["schema"]["Properties"] = [{"Name": "skill_result", "Type": "EStruct",
                                                          "Struct": {"Properties": descriptors}}]
    return {"source_id": source_id, "archive": source_id + ".pak", "tables": tables,
            "table_sources": sources, "result_field_spans": {}}


class LayerUnitTests(unittest.TestCase):
    def test_schema_absence_record_absence_and_explicit_zero_are_different(self):
        descriptor = {"buff_group_level": {"Name": "buff_group_level", "Type": "EUint32"}}
        self.assertEqual(field_operand({}, {}, "buff_group_level")["state"], "not_in_schema")
        self.assertEqual(field_operand({}, descriptor, "buff_group_level")["state"], "absent_in_record")
        zero = field_operand({"buff_group_level": 0}, descriptor, "buff_group_level")
        self.assertEqual((zero["state"], zero["value"]), ("explicit", 0))
        with self.assertRaisesRegex(ValueError, "own schema"):
            field_operand({"buff_group_level": 10}, {}, "buff_group_level")

    def test_order_empty_slots_zero_and_repeated_references_preserved(self):
        b = build_layer_references({"base": fixture()})
        apps = list(b["applications"].values())
        self.assertEqual([a["slot"] for a in apps], list(range(5)))
        self.assertEqual([a["status"] for a in apps], ["resolved", "absent_id", "explicit_zero", "resolved", "missing"])
        self.assertEqual([r["raw_id"] for r in apps[0]["base_references"]], [20, 0, 20])
        self.assertEqual(apps[3]["operands"]["buff_group_level"]["value"], 0)
        self.assertEqual(validate_layer_references(b), [])

    def test_archive_isolation_no_historical_fallback_or_guessed_layer_formula(self):
        base, patch = fixture(), fixture("patch", False)
        patch["tables"]["BUFFBASE_CONF"]["20"]["buffbase_param"] = [{"params": [2000]}]
        patch["table_sources"]["BUFFBASE_CONF"]["rows_content_sha256"] = digest(patch["tables"]["BUFFBASE_CONF"])
        b = build_layer_references({"base": base, "patch": patch})
        a = b["applications"]["base/SKILL_CONF:1/skill_result:0"]
        p = b["applications"]["patch/SKILL_CONF:1/skill_result:0"]
        self.assertEqual(a["operands"]["buff_level_rule"]["value"], 2)
        self.assertIsNone(a["effective_stack_count"])
        self.assertIsNone(a["per_stack_formula"])
        self.assertFalse(a["historical_fallback_applied"])
        self.assertEqual(p["operands"]["buff_group_level"]["state"], "not_in_schema")
        self.assertEqual(p["base_references"][0]["targets"], ["patch/BUFFBASE_CONF:20"])
        self.assertEqual(len(b["skills_by_version"]["1"]), 2)

    def test_missing_base_table_and_cross_table_ambiguity_stay_unresolved(self):
        v = fixture(); del v["tables"]["BUFFBASE_CONF"]; del v["table_sources"]["BUFFBASE_CONF"]
        b = build_layer_references({"base": v})
        self.assertEqual(next(iter(b["applications"].values()))["base_references"][0]["status"], "table_unavailable")
        v["tables"]["EFFECT_CONF"]["10"] = {"id": 10}
        v["table_sources"]["EFFECT_CONF"]["rows_content_sha256"] = digest(v["tables"]["EFFECT_CONF"])
        b = build_layer_references({"base": v})
        self.assertEqual(next(iter(b["applications"].values()))["status"], "ambiguous")
        self.assertEqual(next(iter(b["applications"].values()))["base_references"], [])

    def test_determinism_state_isolation_and_derived_graph_tampering(self):
        v = {"base": fixture()}; original = deepcopy(v)
        b = build_layer_references(v)
        self.assertEqual(b, build_layer_references(v))
        app = "base/SKILL_CONF:1/skill_result:0"
        for mutate in (
            lambda x: x["applications"][app]["operands"]["buff_group_level"].update(value=50),
            lambda x: x["applications"][app].update(effective_stack_count=5),
            lambda x: x["applications"][app].update(targets=["patch/BUFF_CONF:10"]),
            lambda x: x["applications"][app].update(training_eligible=True),
            lambda x: x["applications"][app]["base_references"].reverse(),
            lambda x: x["counts"]["base"].update(explicit_layer_operands=True),
            lambda x: x["applications"]["base/SKILL_CONF:1/skill_result:3"]["operands"]["buff_group_level"].update(value=False),
        ):
            changed = deepcopy(b); mutate(changed)
            self.assertTrue(validate_layer_references(changed))
        b["nodes"]["base/BUFF_CONF:10"]["raw"]["add_max"] = 1
        self.assertEqual(v, original)


class LayerFileEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.variants = load_archive_variants(MANIFESTS, PROBE)
        cls.bundle = build_layer_references(cls.variants)
        cls.base = next(v for v in cls.variants.values() if v["archive"] == "pakchunk4-WindowsNoEditor.pak")
        cls.patch = next(v for v in cls.variants.values() if v["archive"] == "pakchunk4-WindowsNoEditor_3_P.pak")

    def application(self, variant, skill, slot=0):
        return self.bundle["applications"][f"{variant['source_id']}/SKILL_CONF:{skill}/skill_result:{slot}"]

    def test_strength_exact_byte_span_and_same_archive_chain(self):
        a = self.application(self.base, 7020620)
        self.assertEqual(a["operands"]["buff_group_level"]["value"], 10)
        span = next(s for s in a["operand_byte_spans"] if s["field"] == "buff_group_level")
        expected = read_json(ROOT / "artifacts/strength_buff_probe_20261025/strength_binary_evidence.json")
        proof = next(s for s in expected["fields"] if s["field"] == "buff_group_level")
        self.assertEqual((span["offset"], span["raw_hex"], span["value"]), (253703, "0a000000", 10))
        self.assertEqual({k: span[k] for k in proof}, proof)
        prefix = self.base["source_id"]
        self.assertEqual(a["targets"], [prefix + "/BUFF_CONF:20010010"])
        self.assertEqual(a["base_references"][0]["targets"], [prefix + "/BUFFBASE_CONF:2001001"])

    def test_magic_boost_seven_is_base_binary_evidence_not_inferred_ratio(self):
        a = self.application(self.base, 7020630)
        self.assertEqual(a["operands"]["buff_group_level"]["value"], 7)
        span = next(s for s in a["operand_byte_spans"] if s["field"] == "buff_group_level")
        self.assertEqual(span["raw_hex"], "07000000")
        self.assertEqual(a["targets"], [self.base["source_id"] + "/BUFF_CONF:20010020"])

    def test_patch_schema_not_filled_and_missing_historical_skills_not_created(self):
        self.assertNotIn("7170280", self.base["tables"]["SKILL_CONF"])
        self.assertNotIn("7880001", self.base["tables"]["SKILL_CONF"])
        for key in (7020620, 7020630, 7170280, 7880001):
            app = self.application(self.patch, key)
            self.assertEqual(app["operands"]["buff_group_level"]["state"], "not_in_schema")
            self.assertNotIn("value", app["operands"]["buff_group_level"])
            self.assertIsNone(app["effective_stack_count"])
        self.assertEqual(self.application(self.patch, 7170280, 1)["kind"], "result_reference")

    def test_full_inventory_counts_and_source_reverification(self):
        b = self.bundle
        self.assertEqual(b["counts"][self.base["source_id"]]["explicit_layer_operands"], 1257)
        self.assertEqual(b["counts"][self.base["source_id"]]["buff_refs_with_explicit_layer_operand"], 1117)
        self.assertEqual(b["counts"][self.patch["source_id"]]["result_slots"], 6485)
        self.assertEqual(validate_layer_references(b, verify_sources=True), [])
        self.assertFalse(b["training_eligible"])

    def test_forged_byte_offset_or_schema_evidence_cannot_be_published(self):
        changed = deepcopy(self.bundle)
        source = changed["variants"][self.base["source_id"]]
        source["result_field_spans"]["7020620"][-1]["offset"] += 1
        forged = build_layer_references(changed["variants"])
        self.assertTrue(validate_layer_references(forged, verify_sources=True))

    def test_source_payload_hash_and_mixed_archive_pair_rejected(self):
        import json
        original = read_json(MANIFESTS[0])[0]
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            raw = folder / "wrong.non"; raw.write_text("{}")
            original["output"] = raw.name
            manifest = folder / "manifest.json"
            manifest.write_text(json.dumps([original]))
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                load_archive_variants([manifest], PROBE)
            original["payload_sha256"] = file_hash(raw)
            manifest.write_text(json.dumps([original]))
            with self.assertRaisesRegex(ValueError, "own skill and buff"):
                load_archive_variants([manifest], PROBE)

    def test_artifact_save_is_idempotent_without_replacing_existing_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "layers.json"
            first = save_layer_references(self.bundle, path)
            self.assertEqual(save_layer_references(self.bundle, path), first)
            path.write_text("existing unrelated contents")
            with self.assertRaisesRegex(ValueError, "new revision"):
                save_layer_references(self.bundle, path)
            self.assertEqual(path.read_text(), "existing unrelated contents")


class MirrorPatch2EvidenceTests(unittest.TestCase):
    GROUP = ROOT / "docs/verification/game-mirror-patch2-20261025.resources.json"

    @classmethod
    def setUpClass(cls):
        cls.variants = load_resource_group_variants([cls.GROUP], PROBE)
        cls.variant = next(iter(cls.variants.values()))
        cls.bundle = build_layer_references(cls.variants)

    def application(self, slot):
        return self.bundle["applications"][f"{self.variant['source_id']}/SKILL_CONF:7170280/skill_result:{slot}"]

    def test_patch2_mirror_slot_zero_has_direct_five_and_base_chain(self):
        app = self.application(0)
        original = read_json(ROOT / "artifacts/strength_buff_probe_20261025/mirror/versions/pakchunk4-WindowsNoEditor_2_P/mirror.json")
        self.assertEqual(app["raw_reference"], original["matches"][0]["record"]["skill_result"][0])
        self.assertEqual(app["kind"], "state_application_reference")
        self.assertEqual(app["targets"], [self.variant["source_id"] + "/BUFF_CONF:20010080"])
        self.assertEqual(app["base_references"][0]["targets"], [self.variant["source_id"] + "/BUFFBASE_CONF:2001008"])
        span = next(s for s in app["operand_byte_spans"] if s["field"] == "buff_group_level")
        self.assertEqual((span["offset"], span["length"], span["raw_hex"], span["value"]), (333410, 4, "05000000", 5))
        binary = self.variant["table_sources"]["SKILL_CONF"]["files"]["binary"]
        self.assertEqual(Path(binary["path"]).read_bytes()[333410:333414], bytes.fromhex("05000000"))
        self.assertEqual(app["operands"]["buff_level_rule"]["state"], "absent_in_record")
        self.assertIsNone(app["effective_stack_count"])
        self.assertIsNone(app["per_stack_formula"])

    def test_energy_effect_slot_one_is_not_a_buff_despite_group_operand(self):
        app = self.application(1)
        self.assertEqual(app["kind"], "result_reference")
        self.assertEqual(app["targets"], [self.variant["source_id"] + "/EFFECT_CONF:1019013"])
        self.assertEqual(app["operands"]["buff_group_level"]["value"], 1)
        self.assertEqual(app["base_references"], [])
        self.assertEqual(self.variant["tables"]["EFFECT_CONF"]["1019013"]["effect_param"][0]["params"], [-3])
        self.assertFalse(app["training_eligible"])
        self.assertFalse(app["runtime_executable"])

    def test_each_role_keeps_hash_archive_and_explicit_schema_selection(self):
        for name, source in self.variant["table_sources"].items():
            for role, evidence in source["files"].items():
                self.assertEqual(file_hash(evidence["path"]), evidence["extraction"]["payload_sha256"])
                self.assertEqual(file_hash(evidence["manifest"]), evidence["manifest_sha256"])
                self.assertTrue(evidence["selection_basis"])
                expected_patch = 0 if role == "schema" and name in ("BUFF_CONF", "BUFFBASE_CONF") else 2
                self.assertEqual(evidence["extraction"]["pak"], f"pakchunk4-WindowsNoEditor_{expected_patch}_P.pak")
            self.assertEqual(source["same_archive_schema_data"], name in ("SKILL_CONF", "EFFECT_CONF"))
            self.assertTrue(source["all_row_lengths_verified"])
        self.assertFalse(self.variant["runtime_precedence_verified"])
        self.assertFalse(self.variant["online_applicability_verified"])
        self.assertEqual(validate_layer_references(self.bundle, verify_sources=True), [])

    def test_strict_loader_still_rejects_incomplete_mixed_archive_pairs(self):
        mirror = ROOT / "artifacts/strength_buff_probe_20261025/mirror"
        with self.assertRaisesRegex(ValueError, "Incomplete same-archive|own skill and buff"):
            load_archive_variants([mirror / "manifest.json", mirror / "status_chain_manifest.json"], PROBE)

    def test_explicit_group_cannot_fallback_or_claim_runtime_verification(self):
        import json
        original = read_json(self.GROUP)
        for resources in original["tables"].values():
            for selection in resources.values():
                selection["manifest"] = str((self.GROUP.parent / selection["manifest"]).resolve())
        mutations = (
            (lambda g: g.update(runtime_precedence_verified=True), "unverified runtime"),
            (lambda g: g["tables"]["BUFF_CONF"]["schema"].update(archive="pakchunk4-WindowsNoEditor_1_P.pak"), "one manifest entry"),
            (lambda g: g["tables"]["BUFF_CONF"]["binary"].update(archive="pakchunk4-WindowsNoEditor_0_P.pak"), "Only explicit schema"),
            (lambda g: g["tables"]["BUFF_CONF"]["schema"].update(payload_sha256="0" * 64), "one manifest entry"),
            (lambda g: g["tables"]["BUFF_CONF"]["schema"].update(manifest_sha256="0" * 64), "manifest hash mismatch"),
            (lambda g: g["tables"]["BUFF_CONF"]["schema"].update(selection_basis=""), "explicit basis"),
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "group.json"
            for mutate, message in mutations:
                group = deepcopy(original); mutate(group)
                path.write_text(json.dumps(group), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    load_resource_group_variants([path], PROBE)

    def test_representative_group_source_forgery_fails_reverification(self):
        changed = deepcopy(self.variants)
        source = next(iter(changed.values()))
        source["result_field_spans"]["7170280"][4]["offset"] += 1
        self.assertTrue(validate_layer_references(build_layer_references(changed), verify_sources=True))


if __name__ == "__main__":
    unittest.main()
