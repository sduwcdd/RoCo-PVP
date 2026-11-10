import json
from pathlib import Path
import tempfile
import unittest

from scripts.release_resources import collect_licenses, discover


class ReleaseResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) if isinstance(value, (dict, list)) else value, encoding="utf8")
        return path

    def seed(self):
        self.write("data/bwiki/latest.json", {"snapshot_id": "snapshot1"})
        self.write("data/bwiki/snapshot1/catalog.json", {})
        self.write("lab/server.py", "from lab.runtime import VALUE\n")

    def test_follows_json_and_static_constants_but_does_not_sweep_trees(self):
        self.seed()
        self.write("lab/runtime.py", "from pathlib import Path\nROOT=Path(__file__).resolve().parents[1]\nBASE='artifacts/evidence/'\nVALUE={BASE+'manifest.json':'hash'}\n")
        self.write("artifacts/evidence/manifest.json", {"sources": [{"local_path": "raw/table.bin"}]})
        self.write("artifacts/evidence/raw/table.bin", "data")
        self.write("artifacts/evidence/unreferenced.json", {"private": True})
        self.write("vendor/private.json", {})
        self.write("web/hud.html", '<script src="extra.js"></script>')
        self.write("web/extra.js", "console.log('ui')")
        result = discover(self.root)
        self.assertIn("artifacts/evidence/manifest.json", result["resources"])
        self.assertIn("artifacts/evidence/raw/table.bin", result["resources"])
        self.assertIn("web/extra.js", result["resources"])
        self.assertNotIn("artifacts/evidence/unreferenced.json", result["resources"])
        self.assertNotIn("vendor/private.json", result["resources"])

    def test_source_hash_manifest_and_reviewed_rule_glob_are_followed(self):
        self.seed()
        self.write("lab/runtime.py", "VALUE=1\n")
        self.write("data/rules/reviewed-test.json", {"source_files": {
            "docs/verification/resource-group.json": "hash"},
            "reviewed_components": "data/rules/reviewed-*.json"})
        self.write("docs/verification/resource-group.json", {"path": "artifacts/evidence/table.bytes"})
        self.write("artifacts/evidence/table.bytes", "data")
        result = discover(self.root)
        self.assertIn("docs/verification/resource-group.json", result["resources"])
        self.assertIn("artifacts/evidence/table.bytes", result["resources"])
        self.assertFalse(any("*" in row["path"] for row in result["missing"]))

    def test_private_sources_missing_and_escape_are_reported_without_reading(self):
        self.seed()
        self.write("lab/runtime.py", "VALUE=1\n")
        forbidden = ["vendor/rkpp/Key/latest.key", "data/replays/human-battles.sqlite3",
                     "data/external/user-teams-1/team-codes.txt", "artifacts/evidence/parser.py",
                     "artifacts/evidence/live_capture.pcap", "../../../outside.json"]
        self.write("data/rules/reviewed-test.json", {"sources": forbidden + ["artifacts/evidence/missing.json"]})
        for item in forbidden[:-1]:
            self.write(item, "not JSON, must not be opened")
        result = discover(self.root)
        denied = {row["path"] for row in result["forbidden"]}
        self.assertTrue(set(forbidden[:-1]).issubset(denied))
        self.assertTrue(any(row["reason"] == "outside_project" for row in result["forbidden"]))
        self.assertIn("artifacts/evidence/missing.json", {row["path"] for row in result["missing"]})
        self.assertFalse(set(forbidden) & set(result["resources"]))

    def test_rejects_snapshot_traversal_and_reports_file_not_directory(self):
        self.write("data/bwiki/latest.json", {"snapshot_id": "../private"})
        self.write("lab/server.py", "VALUE=1\n")
        result = discover(self.root)
        self.assertTrue(any(row["reason"] == "invalid_snapshot_id" for row in result["forbidden"]))
        self.assertFalse(any("../" in name for name in result["resources"]))

    def test_collects_only_known_license_locations(self):
        self.write("LICENSE", "MIT")
        self.write(".venv-rkpp/Lib/site-packages/scapy-2.dist-info/licenses/LICENSE", "GPL")
        self.write("vendor/private/LICENSE", "private")
        paths = {row["path"] for row in collect_licenses(self.root)}
        self.assertEqual(paths, {"LICENSE", ".venv-rkpp/Lib/site-packages/scapy-2.dist-info/licenses/LICENSE"})

    def test_nested_extraction_uses_manifest_directory_and_ignores_archive_names(self):
        self.seed()
        self.write("lab/runtime.py", "VALUE=1\n")
        self.write("data/rules/reviewed-test.json", {"sources": [{
            "manifest": "artifacts/original/manifest.json",
            "extraction": {"path": "../../../NRC/member.bytes", "output": "raw/table.bytes"},
            "probe_dir": "artifacts/probe"}]})
        self.write("artifacts/original/manifest.json", {"matches": [
            {"pak": "game.pak", "path": "../../../Engine/member.uasset"}]})
        self.write("artifacts/original/raw/table.bytes", "data")
        self.write("artifacts/probe/battle_analysis/provenance.json", {})
        self.write("artifacts/probe/parse_roco_tables.py", "raise RuntimeError('never execute')")
        result = discover(self.root)
        self.assertIn("artifacts/original/raw/table.bytes", result["resources"])
        self.assertIn("artifacts/probe/battle_analysis/provenance.json", result["resources"])
        self.assertIn("artifacts/probe/parse_roco_tables.py", {r["path"] for r in result["forbidden"]})
        self.assertFalse(any("member." in r["path"] for r in result["missing"] + result["forbidden"]))

    def test_invalid_pointer_shape_and_invalid_reference_are_reported(self):
        self.write("data/bwiki/latest.json", [])
        self.write("lab/server.py", "VALUE=1\n")
        self.write("data/rules/reviewed-test.json", {"path": "artifacts/null\0.json"})
        result = discover(self.root)
        self.assertTrue(any(r["reason"] == "ValueError" for r in result["missing"]))
        self.assertTrue(any(r["reason"] == "invalid_path" for r in result["forbidden"]))

    def test_old_checkout_paths_relocate_extraction_under_its_real_manifest(self):
        self.seed()
        self.write("lab/runtime.py", "VALUE=1\n")
        self.write("data/rules/reviewed-test.json", {"sources": [{
            "manifest": r"D:\old\roco_pvp\artifacts\original\manifest.json",
            "path": r"D:\old\roco_pvp\artifacts\original\raw\table.bytes",
            "extraction": {"path": "../../../NRC/member.bytes", "output": "raw/table.bytes"},
        }]})
        self.write("artifacts/original/manifest.json", {})
        self.write("artifacts/original/raw/table.bytes", "data")
        result = discover(self.root)
        self.assertIn("artifacts/original/raw/table.bytes", result["resources"])
        self.assertFalse(any("data/rules/raw" in row["path"] for row in result["missing"]))
        self.assertFalse(any("D:" in row["path"] for row in result["forbidden"]))


if __name__ == "__main__":
    unittest.main()
