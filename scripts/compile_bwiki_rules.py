"""Materialize a reproducible declarative rule artifact; never enables training."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lab.server import load_catalog
from lab.ruleset import BwikiRuleset


def main():
    catalog, digest, _ = load_catalog()
    artifact = BwikiRuleset(catalog).programs()
    artifact["snapshot_sha256"] = digest
    folder = ROOT / "data" / "rules" / artifact["snapshot_id"]
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (artifact["compiler_version"] + ".json")
    raw = (json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    if target.exists() and target.read_bytes() != raw:
        raise SystemExit("Existing compiled rules differ. Bump compiler version; do not overwrite evidence.")
    if not target.exists():
        with target.open("xb") as stream:
            stream.write(raw)
    print(json.dumps({"artifact": str(target), "counts": artifact["counts"], "training_allowed": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
