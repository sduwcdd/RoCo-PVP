"""Relocation never weakens source content verification or containment."""
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest

from lab.source_paths import evidence_path


class SourcePathTests(unittest.TestCase):
    def test_current_release_root_is_normalized_before_historical_windows_marker(self):
        from lab.source_paths import _canonical_locations
        for folder in (r'D:\roco_pvp\dist\release\_internal', r'C:\Apps\RocoPVP\_internal'):
            root = Path(folder)
            with patch('lab.source_paths.ROOT', root):
                self.assertEqual(_canonical_locations(str(root / 'artifacts/probe.json')),
                                 '$PROJECT/artifacts/probe.json')
                self.assertEqual(_canonical_locations(r'D:\roco_pvp\artifacts\probe.json'),
                                 '$PROJECT/artifacts/probe.json')

    def test_windows_recorded_project_relocates_and_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            self.assertEqual(evidence_path(r"D:\Users\86195\Desktop\workspace\roco_pvp\artifacts\probe.json", root),
                             root / "artifacts/probe.json")
            for bad in (r"D:\unrelated\private.txt", r"D:\roco_pvp\..\escape.txt", "../escape.txt"):
                with self.subTest(path=bad), self.assertRaises(ValueError):
                    evidence_path(bad, root)


if __name__ == "__main__":
    unittest.main()
