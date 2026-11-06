"""Inventory current source records against the frozen pre-refactor v6 baseline."""
from pathlib import Path
import json
import sys
import hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lab.server import load_catalog
from lab.mechanism_audit import audit_catalog, markdown_report


def main():
    catalog, digest, _ = load_catalog()
    baseline_path = ROOT / "data" / "rules" / catalog["snapshot_id"] / "bwiki-declarative-6.json"
    raw = baseline_path.read_bytes()
    report = audit_catalog(catalog, json.loads(raw))
    report.update(catalog_file_sha256=digest, baseline_artifact=str(baseline_path.relative_to(ROOT)),
                  baseline_artifact_sha256=hashlib.sha256(raw).hexdigest())
    prefix = ROOT / "docs" / "verification" / "mechanism-audit-20261025"
    prefix.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prefix.with_suffix(".md").write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps({"total": report["total"], "baseline_structured": report["baseline_structured"],
                      "mechanisms": len(report["mechanisms"]), "report": str(prefix.with_suffix('.md'))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
