"""Preserve public Rocoduel data with provenance and explicit completeness checks.

python scripts/snapshot_rocoduel.py --workers 4
python scripts/snapshot_rocoduel.py --resume SNAPSHOT_ID
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.dex import SnapshotError, decode_router_html

BASE = "https://rocoduel.com"
TZ = timezone(timedelta(hours=8))


def now():
    return datetime.now(TZ).isoformat(timespec="seconds")


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", help="Existing snapshot ID; never replaces a complete snapshot")
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--limit", type=int, default=0, help="Diagnostic subset; cannot become latest")
    args = parser.parse_args()
    base = ROOT / "data" / "rocoduel"
    base.mkdir(parents=True, exist_ok=True)
    snapshot_id = args.resume or datetime.now(TZ).strftime("%Y%m%dT%H%M%S%z")
    if not re.fullmatch(r"[A-Za-z0-9_+\-]+", snapshot_id):
        raise ValueError("Invalid snapshot identifier")
    out = base / snapshot_id
    out.mkdir(exist_ok=bool(args.resume))
    (out / "raw").mkdir(exist_ok=True)
    manifest_path = out / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("complete"):
            raise ValueError("Complete snapshots are immutable; create a new one")
    else:
        manifest = {"schema_version": 1, "snapshot_id": snapshot_id, "source": BASE,
                    "started_at": now(), "timezone": "Asia/Shanghai", "complete": False,
                    "source_version": "unverified", "pages": {}, "failures": {}}
    lock = threading.Lock()
    rate_lock = threading.Lock()
    next_start = [0.0]

    def fetch(path, key):
        url = BASE + path
        raw_path = out / "raw" / (key + ".html.gz")
        record = manifest["pages"].get(key)
        if record and raw_path.exists():
            content = gzip.decompress(raw_path.read_bytes())
            if sha(content) != record["sha256"]:
                raise SnapshotError(f"Hash mismatch in retained page {key}")
            return content.decode("utf-8")
        last = None
        for attempt in range(3):
            try:
                with rate_lock:
                    delay = next_start[0] - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                    next_start[0] = time.monotonic() + 0.18
                request = urllib.request.Request(url, headers={
                    "User-Agent": "RocoResearchSnapshot/0.1 (local research; public pages only)",
                    "Accept": "text/html", "Accept-Encoding": "identity"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    if response.status != 200:
                        raise SnapshotError(f"Unexpected HTTP {response.status}")
                    content = response.read(8_000_001)
                    if len(content) > 8_000_000:
                        raise SnapshotError("Page exceeds size limit")
                    final_url = response.url
                    modified = response.headers.get("Last-Modified")
                decoded = content.decode("utf-8")
                # Record only successfully downloaded text; data parsing is separate.
                raw_path.write_bytes(gzip.compress(content, mtime=0))
                with lock:
                    manifest["pages"][key] = {"url": url, "final_url": final_url,
                        "fetched_at": now(), "sha256": sha(content), "bytes": len(content),
                        "raw_file": str(raw_path.relative_to(out)).replace("\\", "/"),
                        "last_modified": modified}
                    manifest["failures"].pop(key, None)
                    write_json(manifest_path, manifest)
                return decoded
            except Exception as exc:
                last = exc
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
        with lock:
            manifest["failures"][key] = {"url": url, "error": str(last), "at": now()}
            write_json(manifest_path, manifest)
        raise SnapshotError(f"{url}: {last}")

    dex = decode_router_html(fetch("/zh/dex", "dex"))["zh:dex"]
    forms = dex["forms"]
    if len({x["id"] for x in forms}) != len(forms):
        raise SnapshotError("Duplicate form IDs in dex")
    if len({x["slug"] for x in forms}) != len(forms):
        raise SnapshotError("Duplicate form slugs in dex")
    if len(forms) != dex["counts"]["forms"]:
        raise SnapshotError("Source count does not match dex forms")
    for key, path in [("how-we-calculate", "/zh/how-we-calculate"), ("data", "/zh/data")]:
        try:
            fetch(path, key)
        except SnapshotError:
            pass
    targets = forms[:args.limit] if args.limit else forms
    details, moves, traits = {}, {}, {}
    consistency, failed = [], []
    globals_data = {}

    def get_detail(form):
        result = decode_router_html(fetch("/zh/jini/" + form["slug"], "form-" + str(form["id"])))
        detail = result["zh:jini"]
        if detail["form"]["id"] != form["id"]:
            raise SnapshotError(f"Detail identity mismatch for {form['id']}")
        detail.pop("build", None)  # Popularity is explicitly out of scope.
        return form, detail

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(get_detail, form): form for form in targets}
        for count, future in enumerate(as_completed(futures), 1):
            form = futures[future]
            try:
                _, detail = future.result()
                details[str(form["id"])] = detail
                for field in ["types", "stats", "slug", "name"]:
                    if detail["form"].get(field) != form.get(field):
                        consistency.append(f"dex/detail mismatch: {form['id']} {field}")
                for move in detail["moves"]:
                    key = str(move["id"])
                    if key in moves and moves[key] != move:
                        consistency.append(f"move definition conflict: {key}")
                    moves[key] = move
                if detail.get("trait"):
                    trait = detail["trait"]
                    key = str(trait["id"])
                    if key in traits and traits[key] != trait:
                        consistency.append(f"trait definition conflict: {key}")
                    traits[key] = trait
                for key in ["natures", "types", "chart", "glossary"]:
                    value = detail.get(key)
                    if key in globals_data and globals_data[key] != value:
                        consistency.append(f"shared {key} changed: {form['id']}")
                    globals_data[key] = value
            except Exception as exc:
                failed.append({"id": form["id"], "slug": form["slug"], "error": str(exc)})
            if count % 40 == 0 or count == len(targets):
                print(f"Fetched {count}/{len(targets)}; parsed {len(details)}; failures {len(failed)}", flush=True)

    unresolved = []
    unknown_learnset_keys = set()
    for key, detail in details.items():
        learnset = detail.get("learnset", {})
        unknown_learnset_keys.update(set(learnset) - {"pool", "stones", "legacy", "universal"})
        refs = list(learnset.get("pool", [])) + list(learnset.get("stones", []))
        refs += [entry["move"] for entry in learnset.get("legacy", [])]
        refs += list(learnset.get("universal", []))
        for move_id in refs:
            if str(move_id) not in moves:
                unresolved.append({"form_id": int(key), "move_id": move_id})
    complete = (len(details) == len(forms) and not failed and not consistency and not unresolved
                and not unknown_learnset_keys)
    validation = {"complete": complete, "expected_forms": len(forms), "parsed_forms": len(details),
                  "move_count": len(moves), "trait_count": len(traits), "failures": failed,
                  "consistency_errors": sorted(set(consistency)), "unresolved_moves": unresolved,
                  "unknown_learnset_keys": sorted(unknown_learnset_keys),
                  "mechanics_verified": False,
                  "note": "Source consistency only; text descriptions are not executable combat mechanics."}
    catalog = {"schema_version": 1, "source": BASE + "/zh/dex", "snapshot_id": snapshot_id,
               "forms": forms, "details": details, "moves": moves, "traits": traits,
               **globals_data, "validation": validation}
    write_json(out / "catalog.json", catalog)
    manifest.update({"completed_at": now(), "complete": complete, "validation": validation,
                     "catalog_sha256": sha((out / "catalog.json").read_bytes()),
                     "popular_builds_enabled": False})
    write_json(manifest_path, manifest)
    write_json(out / "report.json", validation)
    if complete:
        write_json(base / "latest.json", {"snapshot_id": snapshot_id,
                    "catalog_sha256": manifest["catalog_sha256"]})
    print(json.dumps({"snapshot_id": snapshot_id, **validation}, ensure_ascii=False), flush=True)
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
