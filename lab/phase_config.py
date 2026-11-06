"""Read reviewed per-skill phase properties; no natural-language classification."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "roco-phase-config-1"


def source_payload(catalog):
    return {k: deepcopy(catalog.get(k)) for k in ("snapshot_id", "moves", "glossary", "provenance")}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def load_phase_config(catalog):
    snapshot = catalog.get("snapshot_id")
    if not isinstance(snapshot, str) or not snapshot or snapshot in (".", "..") or any(x in snapshot for x in "\\/:"):
        raise ValueError("Invalid phase snapshot; source review required")
    folder = ROOT / "data" / "rules" / snapshot
    try:
        raw = (folder / "phase-config-1.json").read_bytes()
        manifest = json.loads((folder / "phase-config-1.manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Reviewed phase configuration unavailable; source review required") from exc
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("Phase configuration checksum changed; source review required")
    config = json.loads(raw)
    if config.get("schema_version") != SCHEMA_VERSION or config.get("snapshot_id") != snapshot:
        raise ValueError("Phase configuration version mismatch; source review required")
    if config.get("source_content_hash") != fingerprint(source_payload(catalog)):
        raise ValueError("Owned skill records differ from reviewed snapshot; source review required")
    values = catalog["moves"].values() if isinstance(catalog["moves"], dict) else catalog["moves"]
    source = {str(r["id"]): r for r in values}
    records = config.get("skills")
    if not isinstance(records, dict) or set(records) != set(source):
        raise ValueError("Phase config skill IDs must uniquely match owned source snapshot")
    for key, entry in records.items():
        if not isinstance(entry, dict) or set(entry) != {"swift_metadata", "charge"}:
            raise ValueError("Unknown phase property configuration")
        charge, swift = entry["charge"], entry["swift_metadata"]
        if (not isinstance(charge, dict) or set(charge) != {"declared", "skill_record_hash", "raw_text"}
                or type(charge["declared"]) is not bool
                or charge["skill_record_hash"] != fingerprint(source[key])):
            raise ValueError("Invalid source-bound charge property")
        if (not isinstance(swift, dict) or swift.get("skill_id") != int(key)
                or swift.get("skill_record_hash") != charge["skill_record_hash"]
                or swift.get("source_record") != source[key]
                or not (swift.get("swift") is None or type(swift.get("swift")) is bool)
                or swift.get("external_swift_modifiers_resolved") is not False):
            raise ValueError("Invalid source-bound intrinsic Swift property")
    return config
