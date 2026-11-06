"""Stage the existing engine as Python 3.13 bytecode plus authenticated resources.

This is an internal mobile build input, not native code obfuscation or a signed
distribution. Personal capture files and team libraries never enter the pack.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import py_compile
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def mobile_source(relative, raw):
    if relative != "vendor/rkpp/Data.py":
        return raw
    text = raw.decode("utf8").replace("\r\n", "\n")
    old = "            if getattr(sys, 'frozen', False):\n                _sqlite_conn"
    if text.count(old) != 1:
        raise RuntimeError("Shared sqlite memory-loading branch changed; review mobile I/O adapter")
    text = text.replace(old, "            from lab.release_paths import build_identity\n"
                        "            if build_identity():\n                _sqlite_conn")
    return text.encode("utf8")


def stage(output=None, build_id=None, android_source_stage=False):
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError("Mobile bytecode must be built with Python 3.13")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from scripts.release_resources import discover
    from scripts.release_common import frozen_source, validate_inventory

    output = Path(output or ROOT / "mobile/build/generated").resolve()
    if output == ROOT or output.is_relative_to(ROOT / "lab") or output.is_relative_to(ROOT / "vendor"):
        raise ValueError("Mobile staging must not overwrite engine sources")
    python_root, assets = output / "python", output / "assets"
    python_root.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)
    if next(python_root.rglob("*.py"), None) is not None:
        raise RuntimeError("Plain Python sources found in mobile runtime staging")
    inventory = discover(ROOT)
    validate_inventory(inventory)
    ui_root = ROOT / "mobile/shared"
    ui = sorted(p for p in ui_root.rglob("*") if p.is_file())
    if not (ui_root / "index.html").is_file():
        raise RuntimeError("Shared mobile entry page is missing")
    allowed_ui = {".html", ".css", ".js", ".png", ".svg", ".webp", ".woff2"}
    if any(p.suffix.lower() not in allowed_ui or p.is_symlink() for p in ui):
        raise ValueError("Unexpected file in shared mobile browser assets")
    resource_names = sorted(set(inventory["resources"]) | {p.relative_to(ROOT).as_posix() for p in ui})
    source_hashes = {}
    excluded = {"metamon_policy", "metamon_features", "metamon_reward", "amago_bridge",
                "amago_training", "legacy_amago_opponent"}
    sources = [(p.relative_to(ROOT).as_posix(), p.relative_to(ROOT).as_posix(),
                frozen_source(p.relative_to(ROOT).as_posix(), p.read_bytes()))
               for p in sorted((ROOT / "lab").glob("*.py"))
               if not p.stem.startswith("rl_") and p.stem not in excluded]
    sources.extend((p.relative_to(ROOT).as_posix(), p.relative_to(ROOT).as_posix(),
                    mobile_source(p.relative_to(ROOT).as_posix(), p.read_bytes()))
                   for p in sorted((ROOT / "vendor/rkpp").glob("*.py")))
    parser = "artifacts/unpack_probe_20261025/parse_roco_tables.py"
    sources.append((parser, "_release_parser.py", (ROOT / parser).read_bytes()))
    sources.append(("mobile/python/roco_mobile.py", "roco_mobile.py", (ROOT / "mobile/python/roco_mobile.py").read_bytes()))
    for original, _, _ in sources:
        source_hashes[original] = hashlib.sha256((ROOT / original).read_bytes()).hexdigest()
    source_hash = hashlib.sha256(b"".join(p.name.encode("utf8") + b"\0" + p.read_bytes()
        for p in sorted((ROOT / "lab").glob("*.py")))).hexdigest()
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for relative in resource_names:
            archive.write(ROOT / relative, relative)
    key, nonce = os.urandom(32), os.urandom(12)
    encrypted = b"ROCORPK1" + nonce + AESGCM(key).encrypt(nonce, memory.getvalue(), b"roco-pvp-resources-v1")
    resource_hash = hashlib.sha256(encrypted).hexdigest()
    build_id = build_id or time.strftime("mobile-%Y%m%d-%H%M%S")
    secrets = {"BUILD_ID": build_id, "SOURCE_HASH": source_hash, "SOURCE_HASHES": source_hashes,
               "RESOURCE_HASH": resource_hash, "RESOURCE_KEY_HEX": key.hex()}
    sources.append((None, "_mobile_release.py", "\n".join(k + "=" + repr(v) for k, v in secrets.items()).encode()))
    with tempfile.TemporaryDirectory(prefix="roco-mobile-compile-") as work:
        for _, relative, raw in sources:
            temporary = Path(work) / relative
            temporary.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(raw)
            target = (python_root / relative).with_suffix(".pyc")
            target.parent.mkdir(parents=True, exist_ok=True)
            py_compile.compile(str(temporary), cfile=str(target), dfile=relative, doraise=True,
                invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
            if android_source_stage:
                compile_input = output / "android-python" / relative
                compile_input.parent.mkdir(parents=True, exist_ok=True)
                compile_input.write_bytes(raw)
    (assets / "resources.rpk").write_bytes(encrypted)
    report = {"build_id": build_id, "python": "3.13", "protection_mode": "bytecode+encryptedresources",
              "source_hash": source_hash, "source_hashes": source_hashes, "resource_sha256": resource_hash,
              "resource_count": len(resource_names), "resources": resource_names,
              "source_modules": len(sources), "private_exclusions": inventory["forbidden"],
              "android_private_compile_inputs": bool(android_source_stage)}
    (output / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--id")
    parser.add_argument("--android-source-stage", action="store_true",
                        help="Private Chaquopy compiler input; never ship this source directory")
    args = parser.parse_args()
    result = stage(args.out, args.id, args.android_source_stage)
    print(json.dumps({k: result[k] for k in ("build_id", "resource_count", "source_modules", "protection_mode")}))
