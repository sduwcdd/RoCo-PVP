"""Offline classification migration, preserving the former reviewed behavior exactly."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.offline_phase_config import OfflineSwiftClassifier
from lab.phase_config import SCHEMA_VERSION, fingerprint, source_payload
from lab.server import load_catalog
from scripts.build_rule_config import write_once


def build_phase_config(catalog):
    classifier = OfflineSwiftClassifier(catalog)
    skills = {}
    for record in catalog["moves"].values():
        key = record["id"]
        desc = record.get("desc", {})
        desc = desc.get("zh") if isinstance(desc, dict) else desc
        skills[str(key)] = {"swift_metadata": classifier.skill_swift_metadata(key),
                           "charge": {"declared": isinstance(desc, str) and desc.startswith("蓄力，"),
                                      "skill_record_hash": fingerprint(record), "raw_text": desc}}
    return {"schema_version": SCHEMA_VERSION, "snapshot_id": catalog["snapshot_id"],
            "source_content_hash": fingerprint(source_payload(catalog)), "skills": skills,
            "method": "offline_migration_of_reviewed_intrinsic_swift_and_charge_classifier",
            "full_battle_executable": False, "real_game_calibrated": False}


def main():
    catalog = load_catalog()[0]
    config = build_phase_config(catalog)
    folder = ROOT / "data" / "rules" / catalog["snapshot_id"]
    raw = (json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    digest = hashlib.sha256(raw).hexdigest()
    write_once(folder / "phase-config-1.json", raw)
    manifest = {"schema_version": SCHEMA_VERSION, "snapshot_id": catalog["snapshot_id"],
                "sha256": digest, "method": config["method"], "real_game_calibrated": False}
    write_once(folder / "phase-config-1.manifest.json", (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode())
    print(json.dumps({"skills": len(config["skills"]), "charge_declared": sum(x["charge"]["declared"] for x in config["skills"].values()),
                      "sha256": digest}))


if __name__ == "__main__": main()
