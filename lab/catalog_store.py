"""One validated BWIKI revision per process, shared by the web and HUD.

Maintenance publishes the pointer only after preparing matching rules. Existing
processes stay pinned until restart, so all derived caches share one revision.
"""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from threading import Lock

DATA = Path(__file__).resolve().parents[1] / "data/bwiki"
_PIN_LOCK = Lock()
_PINNED = None
_LEASE = None


def _read_catalog(data_root, relative=None, expected=None):
    data_root = Path(data_root).resolve()
    if relative is None:
        pointer = json.loads((data_root / "latest.json").read_text(encoding="utf-8"))
        relative = pointer.get("path") or pointer.get("snapshot_id") or pointer.get("directory")
        expected = pointer.get("catalog_sha256")
    if not isinstance(relative, str) or not relative or any(c in relative for c in "\\/:") or relative in (".", ".."):
        raise ValueError("Invalid snapshot identifier")
    folder = (data_root / relative).resolve()
    if not folder.is_relative_to(data_root):
        raise ValueError("Snapshot path leaves its data directory")
    path = folder / "catalog.json"
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected != digest:
        raise ValueError("Catalog checksum does not match its published snapshot")
    catalog = json.loads(raw)
    if catalog.get("snapshot_id") != relative:
        raise ValueError("Catalog identity does not match its snapshot directory")
    if catalog.get("validation", {}).get("complete") is not True:
        raise ValueError("Snapshot has not passed data integrity checks")
    if not isinstance(catalog.get("forms"), list) or not catalog["forms"]:
        raise ValueError("No catalog forms")
    if not isinstance(catalog.get("details"), dict) or not isinstance(catalog.get("moves"), dict):
        raise ValueError("Invalid catalog structure")
    if len({str(f["id"]) for f in catalog["forms"]}) != len(catalog["forms"]):
        raise ValueError("Duplicate form IDs")
    return catalog, digest, path
def load_catalog(data_root=DATA):
    """Default runtime is pinned. Explicit other roots remain isolated for tools."""
    global _PINNED, _LEASE
    data_root = Path(data_root).resolve()
    if data_root != DATA.resolve():
        return _read_catalog(data_root)
    with _PIN_LOCK:
        if _PINNED is None:
            from lab.release_paths import build_identity
            if not build_identity():
                from lab.bwiki_update_lock import acquire
                _LEASE = acquire(DATA.parent.parent, updating=False)
            try:
                if (DATA.parent / ".bwiki-update.json").exists():
                    raise ValueError("上次 BWIKI 更新中断，请重新运行更新脚本完成恢复后再启动 APP。")
                catalog, digest, path = _read_catalog(data_root)
            except Exception:
                if _LEASE is not None:
                    _LEASE.close()
                    _LEASE = None
                raise
            _PINNED = (path.parent.name, digest)
            return catalog, digest, path
        relative, digest = _PINNED
    return _read_catalog(data_root, relative, digest)


@lru_cache(maxsize=1)
def runtime_catalog():
    """Internal read-only shared catalog. Mutating callers must copy it first."""
    return load_catalog()
