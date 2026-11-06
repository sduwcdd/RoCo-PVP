"""Phase metadata migration parity; no new game timing assumptions."""
from copy import deepcopy
import inspect
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from lab.action_rules import ActionRules
from lab.offline_phase_config import OfflineSwiftClassifier
from lab.phase_config import ROOT, load_phase_config
from lab.server import load_catalog
from lab.switch_rules import SwitchRules
from lab.turn_plan import plan_joint_actions
from scripts.build_phase_config import build_phase_config


class PhaseConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.config = load_phase_config(cls.catalog)

    def test_every_swift_metadata_record_preserves_exact_former_output(self):
        old, new = OfflineSwiftClassifier(self.catalog), SwitchRules(self.catalog)
        counts = {True: 0, False: 0, None: 0}
        for record in self.catalog["moves"].values():
            mid = record["id"]
            expected = old.skill_swift_metadata(mid)
            self.assertEqual(new.skill_swift_metadata(mid), expected)
            counts[expected["swift"]] += 1
        self.assertEqual(counts, {True: 6, False: 572, None: 1})

    def test_all_charge_classifications_match_old_prefix_without_full_execution(self):
        rules, charges = ActionRules(self.catalog), []
        for record in self.catalog["moves"].values():
            desc = record.get("desc", {})
            desc = desc.get("zh") if isinstance(desc, dict) else desc
            expected = isinstance(desc, str) and desc.startswith("蓄力，")
            self.assertEqual(rules.requires_charge(record["id"]), expected)
            if expected:
                charges.append(record["id"])
                result = rules.charge_state(3, record["id"], 7)
                self.assertEqual(result["release_turn"], 8)
                self.assertEqual(result["source_skill_hash"], self.config["skills"][str(record["id"])]["charge"]["skill_record_hash"])
                self.assertFalse(result["training_eligible"])
        self.assertEqual(len(charges), 5)
        self.assertFalse(rules.requires_charge(999999))

    def test_runtime_helpers_do_not_classify_natural_language(self):
        for fn in (SwitchRules.skill_swift_metadata, ActionRules.requires_charge, ActionRules.charge_state, plan_joint_actions):
            source = inspect.getsource(fn)
            self.assertNotIn('.startswith("蓄力，")', source)
            self.assertNotIn('"迅捷" in', source)
        with patch.object(OfflineSwiftClassifier, "skill_swift_metadata", side_effect=AssertionError("offline classifier used at runtime")):
            self.assertTrue(SwitchRules(self.catalog).skill_swift_metadata(7150080)["swift"])
            self.assertTrue(ActionRules(self.catalog).requires_charge(7100150))

    def test_offline_rebuild_has_identical_immutable_payload(self):
        self.assertEqual(build_phase_config(self.catalog), self.config)

    def test_changed_source_cannot_be_reinterpreted_on_the_fly(self):
        for mutate in (lambda c: c["moves"]["7150080"]["desc"].update(zh="造成魔伤。"),
                       lambda c: c["moves"]["7100150"]["desc"].update(zh="造成物伤。"),
                       lambda c: c["provenance"]["Skills"].update(content_sha256="changed")):
            catalog = deepcopy(self.catalog)
            mutate(catalog)
            with self.assertRaisesRegex(ValueError, "review"):
                SwitchRules(catalog).skill_swift_metadata(7150080)
            with self.assertRaisesRegex(ValueError, "review"):
                ActionRules(catalog).requires_charge(7100150)

    def test_returned_metadata_and_later_caller_source_changes_are_isolated(self):
        catalog = deepcopy(self.catalog)
        rules = SwitchRules(catalog)
        catalog["moves"]["7150080"]["desc"]["zh"] = "caller change"
        one = rules.skill_swift_metadata(7150080)
        one["source_record"]["desc"]["zh"] = "result change"
        self.assertEqual(rules.skill_swift_metadata(7150080), self.config["skills"]["7150080"]["swift_metadata"])
        config = load_phase_config(self.catalog)
        config["skills"]["7100150"]["charge"]["declared"] = False
        self.assertTrue(ActionRules(self.catalog).requires_charge(7100150))

    def test_missing_or_tampered_published_configuration_does_not_fallback(self):
        folder = ROOT / "data" / "rules" / self.catalog["snapshot_id"]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            dest = root / "data" / "rules" / self.catalog["snapshot_id"]
            dest.mkdir(parents=True)
            with patch("lab.phase_config.ROOT", root):
                with self.assertRaisesRegex(ValueError, "unavailable"):
                    load_phase_config(self.catalog)
                for name in ("phase-config-1.json", "phase-config-1.manifest.json"):
                    (dest / name).write_bytes((folder / name).read_bytes())
                self.assertEqual(load_phase_config(self.catalog), self.config)
                (dest / "phase-config-1.json").write_text("{}", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "checksum"):
                    load_phase_config(self.catalog)


if __name__ == "__main__": unittest.main()
