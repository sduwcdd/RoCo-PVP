"""Offline migration from preserved v6 programs. Does not invoke the prose compiler."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.rule_config import build_config, SCHEMA_VERSION
from lab.server import load_catalog


def write_once(path, raw):
    if path.exists():
        if path.read_bytes() != raw:
            raise SystemExit("Immutable configuration differs; create a reviewed new schema/version instead")
    else:
        with path.open("xb") as stream: stream.write(raw)


def main():
    catalog = load_catalog()[0]
    folder = ROOT / "data" / "rules" / catalog["snapshot_id"]
    source = folder / "bwiki-declarative-6.json"
    source_raw = source.read_bytes()
    artifact = json.loads(source_raw)
    bundle = build_config(catalog, artifact)
    raw = (json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    target = folder / "rule-config-1.json"
    manifest = {"schema_version": SCHEMA_VERSION, "snapshot_id": catalog["snapshot_id"],
                "sha256": hashlib.sha256(raw).hexdigest(), "source_artifact": source.name,
                "source_sha256": hashlib.sha256(source_raw).hexdigest(),
                "method": "lossless_components_no_nlp", "real_game_calibrated": False}
    write_once(target, raw)
    write_once(folder / "rule-config-1.manifest.json",
               (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
    print(json.dumps({"path": str(target), "sha256": manifest["sha256"],
        "records": {key: len(value) for key, value in bundle["records"].items()},
        "structured": sum(r["capabilities"]["description_structured"] for r in bundle["records"]["skills"].values()),
        "component_supported": sum(r["capabilities"]["isolated_components_supported"] for r in bundle["records"]["skills"].values())}, ensure_ascii=False))


if __name__ == "__main__": main()
