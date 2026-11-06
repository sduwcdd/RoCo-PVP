"""Focused checks for incremental updates and failure-safe activation."""
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile
from unittest.mock import patch

from lab import catalog_store
from lab.bwiki_update_lock import acquire, maintenance
from scripts import snapshot_bwiki as snapshot


class BwikiUpdateFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "data/bwiki"
        self.base.mkdir(parents=True)

    def catalog(self, name):
        folder = self.base / name
        folder.mkdir()
        catalog = {"snapshot_id": name, "forms": [{"id": 1}], "details": {},
                   "moves": {}, "validation": {"complete": True}}
        snapshot.save(folder / "catalog.json", catalog)
        pointer = {"snapshot_id": name, "catalog_sha256": snapshot.sha((folder / "catalog.json").read_bytes())}
        return folder, catalog, pointer

    def test_runtime_stays_pinned_and_callers_receive_owned_data(self):
        _, _, first = self.catalog("old")
        _, _, second = self.catalog("new")
        snapshot.save(self.base / "latest.json", first)
        with patch.object(catalog_store, "DATA", self.base), patch.object(catalog_store, "_PINNED", None), \
                patch.object(catalog_store, "_LEASE", None):
            try:
                catalog = catalog_store.load_catalog(self.base)[0]
                catalog["forms"].clear()
                snapshot.save(self.base / "latest.json", second)
                self.assertEqual(catalog_store.load_catalog(self.base)[0]["snapshot_id"], "old")
                self.assertEqual(catalog_store.load_catalog(self.base)[0]["forms"], [{"id": 1}])
            finally:
                catalog_store._LEASE.close()

    def test_maintenance_refuses_a_running_service(self):
        lease = acquire(self.root, updating=False)
        try:
            with self.assertRaisesRegex(ValueError, "APP"):
                with maintenance(self.root):
                    self.fail("Maintenance acquired a live runtime lock")
        finally:
            lease.close()
        with maintenance(self.root):
            pass

    def test_unchanged_module_reuses_only_verified_exact_revision(self):
        old = self.base / "old"
        out = self.base / "new"
        (old / "raw").mkdir(parents=True)
        (out / "raw").mkdir(parents=True)
        raw = json.dumps({"query": {"pages": [{"revisions": [{"revid": 12,
            "slots": {"main": {"content": "return {}"}}}]}]}}).encode()
        (old / "raw/Skills.gz").write_bytes(gzip.compress(raw))
        entry = {"revision_id": 12, "sha256": snapshot.sha(raw),
                 "content_sha256": snapshot.sha(b"return {}")}
        previous = {"folder": old, "manifest": {"pages": {"Skills": entry}}}
        manifest = {"pages": {}}
        self.assertFalse(snapshot.reuse_module(previous, out, "Skills", {"revision_id": 13}, manifest))
        self.assertTrue(snapshot.reuse_module(previous, out, "Skills", {"revision_id": 12}, manifest))
        self.assertTrue(manifest["pages"]["Skills"]["reused"])
        previous["manifest"]["pages"]["Skills"]["sha256"] = "invalid"
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            snapshot.reuse_module(previous, out, "Skills", {"revision_id": 12}, manifest)

    def test_catalog_only_snapshot_requires_no_missing_raw_cache(self):
        previous = {"folder": self.base / "old", "manifest": {"pages": {
            "Skills": {"revision_id": 12, "content_sha256": "catalog-provenance"}}}}
        self.assertFalse(snapshot.reuse_module(previous, self.base, "Skills", {"revision_id": 12}, {"pages": {}}))

    def test_both_mediawiki_formats_and_batched_revisions_keep_original_content(self):
        older = {"pageid": 1, "revisions": [{"revid": 12, "slots": {"main": {"*": "return {}"}}}]}
        newer = {"pageid": 2, "revisions": [{"revid": 13, "slots": {"main": {"content": "return {x=1}"}}}]}
        for pages in ({"1": older, "2": newer}, [older, newer]):
            response = {"query": {"pages": pages}}
            page = snapshot.page_for_revision(response, 13)
            self.assertEqual(snapshot.revision_content(page["revisions"][0]), "return {x=1}")
            self.assertEqual(snapshot.revision_content(snapshot.page_for_revision(response, 12)["revisions"][0]), "return {}")
            with self.assertRaisesRegex(ValueError, "uniquely match"):
                snapshot.page_for_revision(response, 14)

    def test_revision_lookup_accepts_localized_namespace_titles(self):
        pages, normalized = [], []
        for index, short in enumerate(snapshot.MODULES):
            title = snapshot.title_of(short)
            local_title = title.replace("Module:", "模块:")
            normalized.append({"from": title, "to": local_title})
            pages.append({"title": local_title, "revisions": [{"revid": index + 1, "timestamp": "now"}]})
        response = json.dumps({"query": {"normalized": normalized, "pages": pages}}).encode()
        with patch.object(snapshot, "read_url", return_value=response) as request:
            heads = snapshot.revision_heads()
        request.assert_called_once()
        self.assertEqual(len(heads), 8)
        self.assertEqual(heads["Index"]["revision_id"], 1)

    def test_exception_restores_code_rules_and_active_pointer(self):
        old, old_catalog, first = self.catalog("old")
        out, new_catalog, _ = self.catalog("new")
        snapshot.save(self.base / "latest.json", first)
        (self.root / "lab").mkdir()
        (self.root / "lab/first.py").write_bytes(b"first-old")
        (self.root / "lab/second.py").write_bytes(b"second-old")
        original_replace = Path.replace

        def replace(path, target):
            if path.name == "second.py.bwiki-tmp":
                raise OSError("simulated failed write")
            return original_replace(path, target)

        changes = {"lab/first.py": b"first-new", "lab/second.py": b"second-new"}
        with patch("scripts.update_bwiki_rules.plan_root_rebinding", return_value=changes), \
                patch("scripts.update_bwiki_rules.migrate_rules"), patch.object(Path, "replace", replace):
            with self.assertRaisesRegex(OSError, "failed write"):
                snapshot.activate(self.base, out, new_catalog, {"catalog": old_catalog}, root=self.root)
        self.assertEqual((self.root / "lab/first.py").read_bytes(), b"first-old")
        self.assertEqual((self.root / "lab/second.py").read_bytes(), b"second-old")
        self.assertEqual(json.loads((self.base / "latest.json").read_bytes()), first)
        self.assertFalse((self.root / "data/.bwiki-update.json").exists())

    def test_unsupported_changes_never_activate_or_modify_rules(self):
        _, old_catalog, first = self.catalog("old")
        out, new_catalog, _ = self.catalog("new")
        snapshot.save(self.base / "latest.json", first)
        with patch("scripts.update_bwiki_rules.plan_root_rebinding", side_effect=ValueError("changed mechanism")), \
                patch("scripts.update_bwiki_rules.migrate_rules") as migrate:
            with self.assertRaisesRegex(ValueError, "changed mechanism"):
                snapshot.activate(self.base, out, new_catalog, {"catalog": old_catalog}, root=self.root)
            migrate.assert_not_called()
        self.assertEqual(json.loads((self.base / "latest.json").read_bytes()), first)

    def test_success_activates_only_after_fresh_rule_loading(self):
        _, old_catalog, first = self.catalog("old")
        out, new_catalog, second = self.catalog("new")
        snapshot.save(self.base / "latest.json", first)
        (self.root / "lab").mkdir()
        path = self.root / "lab/first.py"
        path.write_bytes(b"old")

        def verify(root, catalog):
            self.assertEqual(path.read_bytes(), b"new")
            self.assertEqual(json.loads((self.base / "latest.json").read_bytes()), first)

        with patch("scripts.update_bwiki_rules.plan_root_rebinding", return_value={"lab/first.py": b"new"}), \
                patch("scripts.update_bwiki_rules.migrate_rules"), patch.object(snapshot, "verify_activation", side_effect=verify):
            snapshot.activate(self.base, out, new_catalog, {"catalog": old_catalog}, root=self.root)
        self.assertEqual(json.loads((self.base / "latest.json").read_bytes()), second)
        self.assertFalse((self.root / "data/.bwiki-update.json").exists())

    def test_failed_fresh_loading_rolls_back_before_activation(self):
        _, old_catalog, first = self.catalog("old")
        out, new_catalog, _ = self.catalog("new")
        snapshot.save(self.base / "latest.json", first)
        (self.root / "lab").mkdir()
        path = self.root / "lab/first.py"
        path.write_bytes(b"old")
        with patch("scripts.update_bwiki_rules.plan_root_rebinding", return_value={"lab/first.py": b"new"}), \
                patch("scripts.update_bwiki_rules.migrate_rules"), \
                patch.object(snapshot, "verify_activation", side_effect=ValueError("source failed")):
            with self.assertRaisesRegex(ValueError, "source failed"):
                snapshot.activate(self.base, out, new_catalog, {"catalog": old_catalog}, root=self.root)
        self.assertEqual(path.read_bytes(), b"old")
        self.assertEqual(json.loads((self.base / "latest.json").read_bytes()), first)

    def test_historical_static_fields_cannot_override_current_bwiki(self):
        from lab.simulation import _file_static_matches
        program = {"research_action_fields": {"base_energy_cost": 3}, "operations": [
            {"op": "damage", "params": {"power": 100, "type": "水系", "kind": "physical"}}]}
        skill = {"energy": 3, "power": 100, "type": "水系", "kind": "physical"}
        self.assertTrue(_file_static_matches(program, skill))
        self.assertFalse(_file_static_matches(program, {**skill, "energy": 2}))
        self.assertFalse(_file_static_matches(program, {**skill, "power": 110}))
        self.assertEqual(program["operations"][0]["params"]["power"], 100)

    def test_plain_backend_must_bind_the_current_catalog(self):
        from scripts import build_updatable
        folder, catalog, pointer = self.catalog("new")
        catalog_path = folder / "catalog.json"
        raw = catalog_path.read_bytes()
        backend = self.root / "backend"
        (backend / "_internal").mkdir(parents=True)
        cases = [
            (pointer, raw, True),
            ({}, raw, False),
            ({**pointer, "snapshot_id": "old"}, raw, False),
            (pointer, b"{}", False),
        ]
        with patch.object(build_updatable, "ROOT", self.root), patch.object(
                catalog_store, "runtime_catalog", return_value=(catalog, pointer["catalog_sha256"], catalog_path)):
            for packaged_pointer, packaged_catalog, valid in cases:
                with self.subTest(pointer=packaged_pointer, valid=valid):
                    with zipfile.ZipFile(backend / "_internal/resources.zip", "w") as archive:
                        archive.writestr("data/bwiki/latest.json", json.dumps(packaged_pointer))
                        archive.writestr("data/bwiki/new/catalog.json", packaged_catalog)
                    if valid:
                        build_updatable.validate_backend_catalog(backend)
                    else:
                        with self.assertRaisesRegex(ValueError, "rebuild"):
                            build_updatable.validate_backend_catalog(backend)

    def test_plain_backend_rejects_missing_catalog_archive(self):
        from scripts import build_updatable
        folder, catalog, pointer = self.catalog("new")
        with patch.object(catalog_store, "runtime_catalog", return_value=(
                catalog, pointer["catalog_sha256"], folder / "catalog.json")):
            with self.assertRaisesRegex(ValueError, "rebuild"):
                build_updatable.validate_backend_catalog(self.root / "missing-backend")


if __name__ == "__main__":
    unittest.main()
