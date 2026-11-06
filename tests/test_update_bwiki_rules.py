"""Offline BWIKI update regressions, without network or calibration claims."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from lab import phase_config, rule_config
from scripts.update_bwiki_rules import migrate_rules, plan_root_rebinding


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = "20261025T013619+0800"


class UpdateBwikiRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((ROOT / "data/bwiki" / SNAPSHOT / "catalog.json").read_text(encoding="utf-8"))

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        folder = self.root / "data/rules" / SNAPSHOT
        folder.mkdir(parents=True)
        for name in ("rule-config-1", "phase-config-1"):
            for suffix in (".json", ".manifest.json"):
                shutil.copyfile(ROOT / "data/rules" / SNAPSHOT / (name + suffix), folder / (name + suffix))
        self.next = deepcopy(self.catalog)
        self.next["snapshot_id"] = "updated-offline-test"
        self.next["provenance"]["Skills"]["content_sha256"] = "a" * 64

    def load(self):
        with patch.object(rule_config, "ROOT", self.root), patch.object(phase_config, "ROOT", self.root):
            return rule_config.load_bundle(self.next), phase_config.load_phase_config(self.next)

    def test_addition_preserves_old_rules_and_unknown_skill_is_locally_blocked(self):
        original = rule_config.load_bundle(self.catalog)
        source = deepcopy(self.next["moves"]["7020360"])
        source.update(id=7999999, desc={"zh": "未支持的新机制。"},
                      desc_notes=[["dc5t_opaque", "来源原文"]])
        self.next["moves"]["7999999"] = source
        migrate_rules(self.catalog, self.next, self.root)
        bundle, phase = self.load()
        old = original["records"]["skills"]["7020360"]
        carried = bundle["records"]["skills"]["7020360"]
        self.assertEqual(old["components"][0]["params"], carried["components"][0]["params"])
        self.assertEqual(carried["program"]["source_hash"], old["program"]["source_hash"])
        self.assertEqual(carried["program"]["snapshot_id"], self.next["snapshot_id"])
        self.assertEqual(bundle["records"]["skills"]["7999999"]["program"]["status"], "unsupported")
        self.assertFalse(phase["skills"]["7020360"]["swift_metadata"]["swift"])
        self.assertIsNone(phase["skills"]["7999999"]["swift_metadata"]["swift"])
        self.assertFalse(bundle["artifact_header"]["real_game_verified"])
        self.assertFalse(phase["real_game_calibrated"])
        with patch.object(rule_config, "ROOT", self.root):
            self.assertEqual(rule_config.load_bundle(self.catalog), original)
        migrate_rules(self.catalog, self.next, self.root)

    def test_changed_simple_power_is_recompiled_and_unknown_suffix_remains_blocked(self):
        self.next["moves"]["7020360"]["power"] = 42
        self.next["moves"]["7170280"]["desc"]["zh"] += "新未知条件。"
        migrate_rules(self.catalog, self.next, self.root)
        bundle, phase = self.load()
        known = bundle["records"]["skills"]["7020360"]
        self.assertEqual(known["components"][0]["params"]["power"], 42)
        self.assertEqual(known["program"]["status"], "compiled")
        self.assertEqual(bundle["records"]["skills"]["7170280"]["program"]["status"], "unsupported")
        self.assertFalse(phase["skills"]["7020360"]["swift_metadata"]["swift"])

    def test_changed_dependency_blocks_only_dependent_records(self):
        for term in self.next["glossary"]:
            if term["key"] == 3005:
                term["definition"] += " changed"
        migrate_rules(self.catalog, self.next, self.root)
        bundle, _ = self.load()
        dependent = [rule for rule in bundle["records"]["skills"].values()
                     if 3005 in rule["program"]["dependency_ids"]]
        self.assertTrue(dependent)
        self.assertTrue(all(rule["program"]["status"] == "unsupported" for rule in dependent))
        self.assertEqual(bundle["records"]["skills"]["7020360"]["program"]["status"], "compiled")

    def test_changed_catalog_cannot_overwrite_existing_snapshot(self):
        self.next["snapshot_id"] = SNAPSHOT
        with self.assertRaisesRegex(ValueError, "new immutable snapshot"):
            migrate_rules(self.catalog, self.next, self.root)

    def test_corrupt_predecessor_and_existing_conflict_fail_before_publication(self):
        folder = self.root / "data/rules" / self.next["snapshot_id"]
        folder.mkdir()
        target = folder / "phase-config-1.json"
        target.write_text("preserved", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "already differs"):
            migrate_rules(self.catalog, self.next, self.root)
        self.assertEqual(target.read_text(encoding="utf-8"), "preserved")
        self.assertFalse((folder / "rule-config-1.json").exists())
        source = self.root / "data/rules" / SNAPSHOT / "rule-config-1.json"
        source.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            migrate_rules(self.catalog, self.next, self.root)

    def test_root_plan_rebinds_metadata_hash_chain_and_exact_code_literals_without_writes(self):
        for catalog in (self.catalog, self.next):
            folder = self.root / "data/bwiki" / catalog["snapshot_id"]
            folder.mkdir(parents=True)
        self.next["forms"][0]["stats"]["hp"] += 1
        self.next["moves"]["7020360"]["power"] = 42
        self.next["moves"]["7020360"]["energy"] = 2
        self.next["provenance"]["Skills"]["revision_id"] += 1
        self.next["config"]["pet_count"] += 1
        for catalog in (self.catalog, self.next):
            (self.root / "data/bwiki" / catalog["snapshot_id"] / "catalog.json").write_text(
                json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
        old_catalog_raw = (self.root / "data/bwiki" / SNAPSHOT / "catalog.json").read_bytes()
        source = {"snapshot_id": SNAPSHOT, "skill_source": self.catalog["provenance"]["Skills"],
                  "catalog_path": "data/bwiki/" + SNAPSHOT + "/catalog.json",
                  "catalog_file_sha256": hashlib.sha256(old_catalog_raw).hexdigest(),
                  "catalog_content_hash": rule_config._hash(self.catalog),
                  "form_hash": rule_config._hash(self.catalog["forms"][0]),
                  "skills": {"7020360": {"raw": self.catalog["moves"]["7020360"],
                             "record_hash": rule_config._hash(self.catalog["moves"]["7020360"]),
                             "components": [{"op": "power.flat", "amount": 35}]}},
                  "calibrated": False, "policy": "original-policy"}
        raw = json.dumps(source, ensure_ascii=False).encode()
        source_path = self.root / "data/rules/reviewed-source-1.json"
        source_path.write_bytes(raw)
        dependent = {"source_sha256": hashlib.sha256(raw).hexdigest(),
                     "source_content_hash": rule_config._hash(source)}
        (self.root / "data/rules/reviewed-dependent-1.json").write_text(json.dumps(dependent), encoding="utf-8")
        lab = self.root / "lab"
        lab.mkdir()
        original = ("# 中文字节位置\nSOURCE_HASH = '" + rule_config._hash(source)
                    + "'\nSKILLS_HASH = '" + self.catalog["provenance"]["Skills"]["content_sha256"]
                    + "'\nFORMULA = 2 * 5\n").encode()
        (lab / "runtime.py").write_bytes(original)
        plan = plan_root_rebinding(self.catalog, self.next, self.root)
        rebound = json.loads(plan["data/rules/reviewed-source-1.json"])
        downstream = json.loads(plan["data/rules/reviewed-dependent-1.json"])
        self.assertEqual(rebound["snapshot_id"], self.next["snapshot_id"])
        self.assertEqual(rebound["skill_source"], self.next["provenance"]["Skills"])
        self.assertEqual(rebound["form_hash"], rule_config._hash(self.next["forms"][0]))
        self.assertEqual(rebound["skills"]["7020360"]["raw"], self.next["moves"]["7020360"])
        self.assertEqual(rebound["skills"]["7020360"]["record_hash"], rule_config._hash(self.next["moves"]["7020360"]))
        self.assertEqual(rebound["skills"]["7020360"]["components"], [{"op": "power.flat", "amount": 35}])
        self.assertFalse(rebound["calibrated"])
        self.assertEqual(rebound["policy"], "original-policy")
        self.assertEqual(downstream["source_sha256"], hashlib.sha256(plan["data/rules/reviewed-source-1.json"]).hexdigest())
        self.assertEqual(downstream["source_content_hash"], rule_config._hash(rebound))
        self.assertIn(rule_config._hash(rebound).encode(), plan["lab/runtime.py"])
        self.assertIn(b"FORMULA = 2 * 5", plan["lab/runtime.py"])
        self.assertEqual(source_path.read_bytes(), raw)
        self.assertEqual((lab / "runtime.py").read_bytes(), original)
        source["skills"]["7020360"]["operations"] = [{"op": "damage", "params": {"power": 35}}]
        source_path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "7020360.*baked reviewed damage"):
            plan_root_rebinding(self.catalog, self.next, self.root)

    def test_root_plan_blocks_changed_skill_and_term_with_precise_id(self):
        self.next["moves"]["7020360"]["desc"]["zh"] += " changed"
        with self.assertRaisesRegex(ValueError, "7020360"):
            plan_root_rebinding(self.catalog, self.next, self.root)
        self.next["moves"] = deepcopy(self.catalog["moves"])
        self.next["glossary"][0]["definition"] += " changed"
        with self.assertRaisesRegex(ValueError, str(self.next["glossary"][0]["key"])):
            plan_root_rebinding(self.catalog, self.next, self.root)

    def test_append_only_terms_and_chart_preserve_existing_semantics(self):
        self.next["glossary"].append({"key": "dc5t_append_only", "zh": "新术语", "definition": "新增定义。"})
        self.next["chart"]["毒系|幻系"] = {"resist": [], "weak": []}
        for catalog in (self.catalog, self.next):
            folder = self.root / "data/bwiki" / catalog["snapshot_id"]
            folder.mkdir(parents=True)
            (folder / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(plan_root_rebinding(self.catalog, self.next, self.root), {})
        self.next["glossary"][0]["definition"] += " changed"
        with self.assertRaisesRegex(ValueError, str(self.next["glossary"][0]["key"])):
            plan_root_rebinding(self.catalog, self.next, self.root)
        self.next["glossary"] = deepcopy(self.catalog["glossary"])
        self.next["chart"][next(iter(self.catalog["chart"]))] = {"resist": [], "weak": []}
        with self.assertRaisesRegex(ValueError, "chart requires targeted"):
            plan_root_rebinding(self.catalog, self.next, self.root)

    def test_reviewed_november_transition_updates_components_and_preserves_historical_evidence(self):
        transition_path = "data/rules/adaptations/bwiki-20261105.json"
        transition = json.loads((ROOT / transition_path).read_text(encoding="utf-8"))
        target = self.root / transition_path
        target.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / transition_path, target)
        self.next = json.loads((ROOT / "data/bwiki" / transition["to_snapshot"] / "catalog.json").read_text(encoding="utf-8"))
        original_description = self.next["moves"]["7040640"]["desc"]["zh"]
        for catalog in (self.catalog, self.next):
            folder = self.root / "data/bwiki" / catalog["snapshot_id"]
            folder.mkdir(parents=True)
            (folder / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
        paths = {str(path.relative_to(ROOT)).replace("\\", "/")
                 for path in (ROOT / "data/rules").glob("reviewed-*.json")}
        preserved = ROOT / "data/bwiki" / transition["to_snapshot"] / "previous-reviewed"
        originals = {}
        for relative in paths | set(transition["configs"]):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            baseline = preserved / Path(relative).name
            originals[relative] = (baseline if baseline.is_file() else ROOT / relative).read_bytes()
            target.write_bytes(originals[relative])
        lab = self.root / "lab"
        lab.mkdir()
        (lab / "runtime.py").write_text("CONFIG_HASH = '" + rule_config._hash(json.loads(
            originals["data/rules/reviewed-defense-components-1.json"])) + "'\n", encoding="utf-8")
        plan = plan_root_rebinding(self.catalog, self.next, self.root)
        for relative, recipe in transition["configs"].items():
            actual = json.loads(plan[relative])
            original = json.loads(originals[relative])
            for change in recipe["changes"]:
                value = actual
                for key in change["path"]:
                    value = value[key]
                self.assertEqual(value, change["after"])
            self.assertEqual((self.root / relative).read_bytes(), originals[relative])
            if relative.endswith("reviewed-defense-components-1.json"):
                self.assertEqual(actual["skills"]["7040640"]["installation_evidence"],
                                 original["skills"]["7040640"]["installation_evidence"])
                self.assertIn(rule_config._hash(actual).encode(), plan["lab/runtime.py"])
        from lab import weather_runtime
        weather_rules = json.loads(plan["artifacts/weather_rules_20261025/weather_rules.json"])
        actor = {"hp": 100, "max_hp": 1000, "weather_trait_id": 200144}
        with patch.object(weather_runtime, "rules", return_value=weather_rules), \
                patch("lab.trait_runtime.after_hp_restore", return_value=[]):
            rain, _ = weather_runtime.set_weather(None, 7050250, 1)
            events = weather_runtime.after_skill(rain, 7050490, actor, {"hp": 900},
                [{"op": "damage", "actual_hp_loss": 37}], side="a",
                type_multiplier=lambda *_: 1, skill_type="水系", turn=1)
        self.assertEqual(actor["hp"], 137)
        self.assertEqual(events[0]["amount"], 37)
        migrate_rules(self.catalog, self.next, self.root)
        bundle, phase = self.load()
        from lab import transformation_runtime
        transformation = json.loads(plan["data/rules/reviewed-transformation-components-1.json"])
        with patch.object(rule_config, "ROOT", self.root), patch.object(phase_config, "ROOT", self.root), \
                patch.object(transformation_runtime, "_configuration", return_value=transformation), \
                patch("lab.mechanism_runtime.programs", return_value={}):
            programs = transformation_runtime.programs(self.next)
            for program in programs.values():
                transformation_runtime._validate_program(program)
        self.assertIn(7190530, programs[7021220]["transformation_metadata"]["pool_ids"])
        self.assertEqual(bundle["records"]["skills"]["7190530"]["program"]["status"], "unsupported")
        self.assertFalse(bundle["artifact_header"]["real_game_verified"])
        for trait_id in ("200130", "200287"):
            self.assertEqual(bundle["records"]["traits"][trait_id]["program"]["status"], "unsupported")
        previous = json.loads((ROOT / "data/rules" / SNAPSHOT / "phase-config-1.json").read_text(encoding="utf-8"))
        for key in transition["records"]["moves"]:
            self.assertEqual(phase["skills"][key]["swift_metadata"]["swift"],
                             previous["skills"][key]["swift_metadata"]["swift"])
        original_energy = self.next["moves"]["7190530"]["energy"]
        self.next["moves"]["7190530"]["energy"] += 1
        with self.assertRaisesRegex(ValueError, "transition catalog mismatch: moves"):
            plan_root_rebinding(self.catalog, self.next, self.root)
        self.next["moves"]["7190530"]["energy"] = original_energy
        self.next["moves"]["7040640"]["desc"]["zh"] += "未知条件。"
        with self.assertRaisesRegex(ValueError, "transition source mismatch: 7040640"):
            plan_root_rebinding(self.catalog, self.next, self.root)
        self.next["moves"]["7040640"]["desc"]["zh"] = original_description
        target = self.root / "data/rules/reviewed-defense-components-1.json"
        changed = json.loads(target.read_text(encoding="utf-8"))
        changed["skills"]["7040640"]["components"]["reduction"]["numerator"] = 99
        target.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "transition config mismatch"):
            plan_root_rebinding(self.catalog, self.next, self.root)


if __name__ == "__main__":
    unittest.main()
