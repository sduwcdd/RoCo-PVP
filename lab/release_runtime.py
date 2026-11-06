"""Opt-in, read-only in-memory resources for the frozen desktop release.

Only the listed pathlib/open interfaces are virtualized. Streams have no OS file
descriptor; os.open, os.scandir and custom openers are intentionally not emulated.
"""
import builtins
import calendar
import io
import os
from pathlib import Path, PurePosixPath
import re
import stat
import threading
import zipfile
from collections import OrderedDict


_MAGIC = b"ROCORPK1"
_AAD = b"roco-pvp-resources-v1"
_CACHE_LIMIT = 32 * 1024 * 1024
_ACTIVE = None
_INSTALL_LOCK = threading.RLock()


def _absolute(path):
    return os.path.normcase(os.path.abspath(os.fsdecode(os.fspath(path))))


def _safe_name(name):
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name or ":" in name:
        raise ValueError("Invalid resource path")
    trimmed = name[:-1] if name.endswith("/") else name
    if not trimmed or any(part in ("", ".", "..") for part in trimmed.split("/")):
        raise ValueError("Resource paths must be relative POSIX paths without traversal")
    return trimmed


class _Mount:
    def __init__(self, root, payload, source_hashes):
        self.root = Path(_absolute(root))
        self._zip_buffer = io.BytesIO(payload)
        self._zip = zipfile.ZipFile(self._zip_buffer)
        self._entries = {"": None}
        self._names = {"": ""}
        self._cache = OrderedDict()
        self._cache_size = 0
        self._lock = threading.RLock()
        self._patches = []
        self._hashes = {}
        try:
            explicit = set()
            for info in self._zip.infolist():
                name = _safe_name(info.orig_filename)
                key = os.path.normcase(name)
                kind = stat.S_IFMT(info.external_attr >> 16)
                if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or (kind == stat.S_IFDIR and not info.is_dir()):
                    raise ValueError("Only regular files and directories are allowed in resources")
                if key in explicit:
                    raise ValueError("Duplicate resource path")
                explicit.add(key)
                if info.is_dir():
                    if key in self._entries and self._entries[key] is not None:
                        raise ValueError("Resource file/directory collision")
                    self._entries[key] = None
                else:
                    if key in self._entries:
                        raise ValueError("Resource file/directory collision")
                    self._entries[key] = info
                self._names[key] = name
                parent = PurePosixPath(name).parent
                while str(parent) != ".":
                    parent_name = str(parent)
                    parent_key = os.path.normcase(parent_name)
                    if self._entries.get(parent_key) is not None:
                        raise ValueError("Resource file is also a parent directory")
                    self._entries[parent_key] = None
                    self._names.setdefault(parent_key, parent_name)
                    parent = parent.parent
            for name, digest in (source_hashes or {}).items():
                name = _safe_name(name)
                key = os.path.normcase(name)
                if not name.endswith(".py") or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
                    raise ValueError("Source manifest requires .py paths and SHA-256 digests")
                if key in self._hashes:
                    raise ValueError("Duplicate source manifest path")
                self._hashes[key] = digest.lower()
        except BaseException:
            self._zip.close()
            self._zip_buffer.close()
            raise

    def _relative(self, path):
        if isinstance(path, int):
            return None
        try:
            absolute = _absolute(path)
            if os.path.commonpath((str(self.root), absolute)) != str(self.root):
                return None
            relative = os.path.relpath(absolute, self.root).replace("\\", "/")
            return "" if relative == "." else os.path.normcase(relative)
        except (TypeError, ValueError, OSError):
            return None

    def _key(self, path):
        key = self._relative(path)
        return key if key in self._entries else None

    def _read(self, key):
        info = self._entries[key]
        if info is None:
            raise IsADirectoryError(str(self.root / self._names[key]))
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            data = self._zip.read(info)
            if len(data) <= _CACHE_LIMIT:
                while self._cache and self._cache_size + len(data) > _CACHE_LIMIT:
                    _, evicted = self._cache.popitem(last=False)
                    self._cache_size -= len(evicted)
                self._cache[key] = data
                self._cache_size += len(data)
            return data

    def _open(self, file, mode="r", buffering=-1, encoding=None, errors=None, newline=None, closefd=True, opener=None):
        key = self._key(file)
        if key is None:
            return self._original_open(file, mode, buffering, encoding, errors, newline, closefd, opener)
        if any(flag in mode for flag in "wax+"):
            raise PermissionError("Release resources are read-only")
        if mode not in ("r", "rb", "br", "rt", "tr"):
            raise ValueError("Invalid read mode")
        if not closefd or opener is not None:
            raise ValueError("Virtual resources do not support closefd=False or a custom opener")
        if "b" in mode and any(value is not None for value in (encoding, errors, newline)):
            raise ValueError("Binary mode does not accept encoding, errors or newline")
        if buffering == 0 and "b" not in mode:
            raise ValueError("Unbuffered text I/O is not supported")
        stream = io.BytesIO(self._read(key))
        stream.name = os.fspath(file)
        stream.mode = mode
        if "b" in mode:
            return stream
        text = io.TextIOWrapper(stream, encoding=io.text_encoding(encoding), errors=errors, newline=newline)
        text.mode = mode
        return text

    def _stat(self, key):
        info = self._entries[key]
        stamp = calendar.timegm(info.date_time + (0, 0, 0)) if info else 315532800
        mode = (stat.S_IFREG | 0o444) if info else (stat.S_IFDIR | 0o555)
        return os.stat_result((mode, 0, 0, 1, 0, 0, info.file_size if info else 0, stamp, stamp, stamp),
                              {"st_atime_ns": stamp * 10**9, "st_mtime_ns": stamp * 10**9, "st_ctime_ns": stamp * 10**9})

    def _children(self, path, key, original):
        if self._entries[key] is not None:
            raise NotADirectoryError(os.fspath(path))
        seen = set()
        if os.path.isdir(path):
            for child in original(path):
                seen.add(_absolute(child))
                yield child
        prefix = key + os.sep if key else ""
        for candidate in sorted(self._entries):
            if candidate != key and candidate.startswith(prefix) and os.sep not in candidate[len(prefix):]:
                child = Path(path) / PurePosixPath(self._names[candidate]).name
                if _absolute(child) not in seen:
                    yield child

    def _glob(self, path, key, pattern, original, case_sensitive, recurse_symlinks):
        pattern = os.fspath(pattern)
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("A nonempty string glob pattern is required")
        pattern = pattern.replace("\\", "/")
        if PurePosixPath(pattern).is_absolute() or ":" in pattern:
            raise NotImplementedError("Non-relative patterns are unsupported")
        if self._entries[key] is not None:
            return
        seen = set()
        if os.path.isdir(path):
            for child in original(path, pattern, case_sensitive=case_sensitive, recurse_symlinks=recurse_symlinks):
                seen.add(_absolute(child))
                yield child
        directory_only = pattern.endswith("/")
        pattern = pattern.rstrip("/")
        base_name = self._names[key]
        prefix = base_name + "/" if base_name else ""
        for candidate, name in sorted(self._names.items()):
            if candidate == key:
                relative = "."
            elif os.path.normcase(name).startswith(os.path.normcase(prefix)):
                relative = name[len(prefix):]
            else:
                continue
            if directory_only and self._entries[candidate] is not None:
                continue
            if PurePosixPath(relative).full_match(pattern, case_sensitive=(os.name != "nt" if case_sensitive is None else case_sensitive)):
                child = Path(path) / relative
                if _absolute(child) not in seen:
                    yield child

    def _patch(self, owner, name, replacement):
        original = getattr(owner, name)
        self._patches.append((owner, name, original, replacement))
        setattr(owner, name, replacement)

    def _activate(self):
        self._original_open = builtins.open
        originals = {name: getattr(Path, name) for name in
                     ("read_bytes", "read_text", "open", "exists", "is_file", "is_dir", "stat", "glob", "rglob", "iterdir")}
        mount = self

        def path_open(path, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
            if mount._key(path) is None:
                return originals["open"](path, mode, buffering, encoding, errors, newline)
            return mount._open(path, mode, buffering, encoding, errors, newline)

        def read_bytes(path):
            key = mount._key(path)
            return originals["read_bytes"](path) if key is None else mount._read(key)

        def read_text(path, encoding=None, errors=None, newline=None):
            if mount._key(path) is None:
                return originals["read_text"](path, encoding=encoding, errors=errors, newline=newline)
            with mount._open(path, encoding=encoding, errors=errors, newline=newline) as stream:
                return stream.read()

        def predicate(name):
            def check(path, *, follow_symlinks=True):
                key = mount._key(path)
                if key is None:
                    return originals[name](path, follow_symlinks=follow_symlinks)
                return name == "exists" or ((mount._entries[key] is None) == (name == "is_dir"))
            return check

        def path_stat(path, *, follow_symlinks=True):
            key = mount._key(path)
            return originals["stat"](path, follow_symlinks=follow_symlinks) if key is None else mount._stat(key)

        def iterdir(path):
            key = mount._key(path)
            return originals["iterdir"](path) if key is None else mount._children(path, key, originals["iterdir"])

        def glob(path, pattern, *, case_sensitive=None, recurse_symlinks=False):
            key = mount._key(path)
            if key is None:
                return originals["glob"](path, pattern, case_sensitive=case_sensitive, recurse_symlinks=recurse_symlinks)
            return mount._glob(path, key, pattern, originals["glob"], case_sensitive, recurse_symlinks)

        def rglob(path, pattern, *, case_sensitive=None, recurse_symlinks=False):
            key = mount._key(path)
            if key is None:
                return originals["rglob"](path, pattern, case_sensitive=case_sensitive, recurse_symlinks=recurse_symlinks)
            return glob(path, "**/" + os.fspath(pattern), case_sensitive=case_sensitive, recurse_symlinks=recurse_symlinks)

        for name, replacement in (("open", path_open), ("read_bytes", read_bytes), ("read_text", read_text),
                                  ("stat", path_stat), ("iterdir", iterdir), ("glob", glob), ("rglob", rglob)):
            self._patch(Path, name, replacement)
        for name in ("exists", "is_file", "is_dir"):
            self._patch(Path, name, predicate(name))
        self._patch(builtins, "open", self._open)
        self._patch(io, "open", self._open)

    def uninstall(self):
        global _ACTIVE
        with _INSTALL_LOCK:
            for owner, name, original, replacement in reversed(self._patches):
                if getattr(owner, name) is replacement:
                    setattr(owner, name, original)
            self._patches.clear()
            if _ACTIVE is self:
                _ACTIVE = None
            with self._lock:
                self._cache.clear()
                self._cache_size = 0
                self._zip.close()
                self._zip_buffer.close()


def install(root, archive, key, source_hashes=None):
    """Mount encrypted archive bytes (or a path); return an uninstallable mount.

    source_hashes maps root-relative .py paths to their original source SHA-256.
    Authentication and path validation finish before any global patch is applied.
    """
    global _ACTIVE
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    with _INSTALL_LOCK:
        if _ACTIVE is not None:
            raise RuntimeError("A release resource mount is already installed")
        if not isinstance(archive, bytes):
            with builtins.open(archive, "rb") as stream:
                archive = stream.read()
        if len(archive) < len(_MAGIC) + 12 + 16 or not archive.startswith(_MAGIC):
            raise ValueError("Invalid encrypted resource archive")
        try:
            payload = AESGCM(key).decrypt(archive[8:20], archive[20:], _AAD)
        except Exception as exc:
            raise ValueError("Resource archive authentication failed") from exc
        mount = _Mount(root, payload, source_hashes)
        try:
            mount._activate()
        except BaseException:
            mount.uninstall()
            raise
        _ACTIVE = mount
        return mount


def install_plain(root, archive, source_hashes=None):
    """Explicitly mount an unencrypted ZIP using the same read-only validation.

    This is not an authentication boundary; the caller verifies its build hash.
    It never falls back from a failed encrypted archive to plaintext.
    """
    global _ACTIVE
    with _INSTALL_LOCK:
        if _ACTIVE is not None:
            raise RuntimeError("A release resource mount is already installed")
        if not isinstance(archive, bytes):
            with builtins.open(archive, "rb") as stream:
                archive = stream.read()
        mount = _Mount(root, archive, source_hashes)
        try:
            mount._activate()
        except BaseException:
            mount.uninstall()
            raise
        _ACTIVE = mount
        return mount


def frozen_source_hash(path):
    """Return a manifest's original .py digest, never a hash of compiled bytes."""
    mount = _ACTIVE
    if mount is None:
        return None
    relative = mount._relative(path)
    if relative is None:
        return None
    if relative.endswith(".pyd"):
        directory, name = os.path.split(relative)
        relative = os.path.join(directory, name.split(".", 1)[0] + ".py")
    elif relative.endswith((".pyc", ".pyo")):
        relative = relative[:-1]
    return mount._hashes.get(relative)
