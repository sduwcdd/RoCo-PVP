"""Synthetic, disk-free payload checks for the release resource mount."""
import builtins
import hashlib
import io
import os
from pathlib import Path
import stat
import tempfile
import unittest
import warnings
import zipfile
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from lab import release_runtime as runtime


KEY = bytes(range(32))


def archive(entries):
    buffer = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        warnings.simplefilter("ignore", UserWarning)
        for name, content in entries:
            if isinstance(name, str) and "\\" in name:
                raw_name = zipfile.ZipInfo()
                raw_name.filename = raw_name.orig_filename = name
                name = raw_name
            package.writestr(name, content)
    nonce = bytes(range(12))
    return b"ROCORPK1" + nonce + AESGCM(KEY).encrypt(nonce, buffer.getvalue(), b"roco-pvp-resources-v1")


class ReleaseRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "app"
        self.root.mkdir()
        self.mount = None
        self.originals = (builtins.open, io.open, Path.open, Path.read_bytes, Path.stat, Path.glob)

    def tearDown(self):
        if self.mount:
            self.mount.uninstall()
        elif runtime._ACTIVE is not None:
            runtime._ACTIVE.uninstall()
        self.assertEqual((builtins.open, io.open, Path.open, Path.read_bytes, Path.stat, Path.glob), self.originals)
        self.temp.cleanup()

    def install(self, entries=None, **kwargs):
        payload = archive(entries or [("web/index.html", "首页\r\nnext"), ("data/a.json", '{"a":1}'),
                                      ("data/nested/b.json", "{}"), ("empty/", "")])
        self.mount = runtime.install(self.root, payload, KEY, **kwargs)
        return self.mount

    def test_read_open_metadata_and_no_extraction(self):
        self.install()
        page = self.root / "web/index.html"
        expected = "首页\r\nnext".encode()
        self.assertEqual(page.read_bytes(), expected)
        self.assertEqual(page.read_text(encoding="utf-8"), "首页\nnext")
        self.assertEqual(page.read_text(encoding="utf-8", newline=""), "首页\r\nnext")
        for opener in (builtins.open, io.open):
            for path in (page, str(page)):
                with opener(path, "rb") as stream:
                    self.assertEqual(stream.read(3), expected[:3])
                    stream.seek(0)
                    self.assertEqual(stream.read(), expected)
                with opener(path, encoding="utf-8") as stream:
                    self.assertEqual(stream.read(), "首页\nnext")
                    self.assertEqual(stream.mode, "r")
        with page.open("rb") as stream:
            self.assertEqual(stream.read(), expected)
        self.assertTrue(page.exists())
        self.assertTrue(page.is_file())
        self.assertFalse(page.is_dir())
        self.assertTrue(page.parent.is_dir())
        self.assertFalse(page.parent.is_file())
        self.assertTrue((self.root / "empty").is_dir())
        self.assertFalse((self.root / "missing").exists())
        self.assertEqual(page.stat().st_size, len(expected))
        self.assertIsInstance(page.stat().st_mtime_ns, int)
        self.assertEqual(page.stat().st_mtime_ns, page.stat().st_mtime_ns)
        self.assertTrue(stat.S_ISREG(page.stat().st_mode))
        self.assertFalse(os.path.exists(page))
        self.assertEqual(os.listdir(self.root), [])
        with self.assertRaises(IsADirectoryError):
            page.parent.read_bytes()

    def test_glob_rglob_iterdir_merge_virtual_and_existing_files(self):
        (self.root / "disk.txt").write_text("disk")
        self.install()
        self.assertEqual({p.name for p in self.root.iterdir()}, {"disk.txt", "web", "data", "empty"})
        data = self.root / "data"
        self.assertEqual({p.name for p in data.iterdir()}, {"a.json", "nested"})
        self.assertEqual({p.name for p in data.glob("*.json")}, {"a.json"})
        self.assertEqual({p.name for p in data.rglob("*.json")}, {"a.json", "b.json"})
        self.assertEqual({p.name for p in data.glob("**/*.json")}, {"a.json", "b.json"})
        self.assertEqual({p.name for p in self.root.glob("*/")}, {"web", "data", "empty"})
        self.assertEqual({p.name for p in self.root.glob("disk.*")}, {"disk.txt"})
        self.assertEqual({p.name for p in data.glob("*.JSON", case_sensitive=False)}, {"a.json"})
        self.assertEqual(list(data.glob("*.JSON", case_sensitive=True)), [])

    def test_write_modes_and_path_writers_fail(self):
        self.install()
        target = self.root / "web/index.html"
        for opener in (builtins.open, io.open, lambda path, mode: path.open(mode)):
            for mode in ("w", "wb", "a", "x", "r+", "rb+"):
                with self.subTest(mode=mode), self.assertRaises(PermissionError):
                    opener(target, mode)
        with self.assertRaises(PermissionError):
            target.write_text("replace")
        with self.assertRaises(PermissionError):
            target.write_bytes(b"replace")
        self.assertFalse(os.path.exists(target))

    def test_external_paths_and_uninstall_restore_original_behavior(self):
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_text("before")
        self.install()
        with io.open(outside, "w") as stream:
            stream.write("after")
        self.assertEqual(outside.read_text(), "after")
        self.assertTrue(outside.exists())
        self.assertEqual(outside.stat().st_size, 5)
        self.assertIn(outside, list(outside.parent.glob("outside.*")))
        outside.write_bytes(b"reset")
        self.assertEqual(outside.read_bytes(), b"reset")
        self.mount.uninstall()
        self.assertFalse((self.root / "web/index.html").exists())
        with self.assertRaises(FileNotFoundError):
            (self.root / "web/index.html").read_bytes()

    def test_source_hashes_are_manifest_only_and_map_compiled_module_names(self):
        digest = hashlib.sha256(b"original source").hexdigest()
        self.assertIsNone(runtime.frozen_source_hash(self.root / "lab/module.py"))
        self.install(source_hashes={"lab/module.py": digest})
        for name in ("module.py", "module.pyd", "module.cp313-win_amd64.pyd"):
            self.assertEqual(runtime.frozen_source_hash(self.root / "lab" / name), digest)
        self.assertIsNone(runtime.frozen_source_hash(self.root / "lab/missing.pyd"))
        self.assertIsNone(runtime.frozen_source_hash(Path(self.temp.name) / "lab/module.py"))
        self.mount.uninstall()
        self.assertIsNone(runtime.frozen_source_hash(self.root / "lab/module.py"))

    def test_tampering_wrong_key_and_invalid_header_fail_before_patch(self):
        payload = archive([("a", "value")])
        for bad, key in ((payload[:-1] + bytes([payload[-1] ^ 1]), KEY), (payload, bytes(32)), (b"invalid", KEY)):
            with self.assertRaises(ValueError):
                runtime.install(self.root, bad, key)
            self.assertIs(builtins.open, self.originals[0])
            self.assertIsNone(runtime._ACTIVE)

    def test_zip_path_traversal_duplicates_links_and_collisions_fail_closed(self):
        link = zipfile.ZipInfo("link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        invalid = [[(name, "x")] for name in ("/absolute", "../escape", "a/../escape", "a//b", "./a", "C:/escape", "a\\b")]
        invalid.extend([[("a", "x"), ("a", "y")], [(link, "target")],
                        [("a", "x"), ("a/b", "y")], [("a/b", "x"), ("a", "y")]])
        for entries in invalid:
            with self.subTest(names=[str(name) for name, _ in entries]), self.assertRaises(ValueError):
                runtime.install(self.root, archive(entries), KEY)
            self.assertIs(builtins.open, self.originals[0])
            self.assertIsNone(runtime._ACTIVE)

    def test_archive_path_install_and_no_nested_mount(self):
        package = Path(self.temp.name) / "resources.rpk"
        package.write_bytes(archive([("a", "x")]))
        self.mount = runtime.install(self.root, package, KEY)
        self.assertEqual((self.root / "a").read_text(), "x")
        with self.assertRaises(RuntimeError):
            runtime.install(self.root, package, KEY)

    def test_malformed_source_manifest_fails_before_patch(self):
        for manifest in ({"../outside.py": "a" * 64}, {"lab/module.pyd": "b" * 64}, {"lab/module.py": "invalid"}):
            with self.assertRaises(ValueError):
                runtime.install(self.root, archive([("a", "x")]), KEY, manifest)
            self.assertIsNone(runtime._ACTIVE)
            self.assertIs(builtins.open, self.originals[0])

    def test_cache_is_bounded_and_oversized_files_are_not_cached(self):
        with patch.object(runtime, "_CACHE_LIMIT", 8):
            mount = self.install([("a", b"aaaaa"), ("b", b"bbbbb"), ("large", b"x" * 9)])
            for name in ("a", "b", "large"):
                (self.root / name).read_bytes()
                self.assertLessEqual(mount._cache_size, 8)
            self.assertNotIn(os.path.normcase("large"), mount._cache)
            self.assertNotIn(os.path.normcase("a"), mount._cache)
            self.assertIn(os.path.normcase("b"), mount._cache)

    def test_plain_mount_preserves_manifest_readonly_and_external_state(self):
        payload = archive([('data/rules.json', '{}')])
        plain = AESGCM(KEY).decrypt(payload[8:20], payload[20:], b'roco-pvp-resources-v1')
        self.mount = runtime.install_plain(self.root, plain, {'lab/module.py': 'a' * 64})
        self.assertEqual((self.root / 'data/rules.json').read_text(), '{}')
        self.assertEqual(runtime.frozen_source_hash(self.root / 'lab/module.pyc'), 'a' * 64)
        with self.assertRaises(PermissionError):
            (self.root / 'data/rules.json').write_text('changed')
        state = Path(self.temp.name) / 'user-state.json'
        state.write_text('state')
        self.assertEqual(state.read_text(), 'state')
        self.assertFalse(os.path.exists(self.root / 'data/rules.json'))
        with self.assertRaises(RuntimeError):
            runtime.install_plain(self.root, plain)

    def test_plain_mount_rejects_paths_and_manifest_before_patching(self):
        for name, manifest in (('../escape', {}), ('safe', {'lab/module.py': 'invalid'})):
            payload = archive([(name, 'value')])
            plain = AESGCM(KEY).decrypt(payload[8:20], payload[20:], b'roco-pvp-resources-v1')
            with self.assertRaises(ValueError):
                runtime.install_plain(self.root, plain, manifest)
            self.assertIsNone(runtime._ACTIVE)
            self.assertIs(builtins.open, self.originals[0])
            with self.assertRaises(ValueError):
                runtime.install(self.root, plain, KEY)


if __name__ == "__main__":
    unittest.main()
