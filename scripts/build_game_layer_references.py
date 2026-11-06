"""Build source-isolated layer references from existing extracted table manifests."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.game_layer_references import (load_archive_variants, load_resource_group_variants,
                                       build_layer_references, save_layer_references)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, action="append", default=[])
    parser.add_argument("--resource-group", type=Path, action="append", default=[])
    parser.add_argument("--probe-dir", type=Path, default=ROOT / "artifacts/unpack_probe_20261025")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.manifest and not args.resource_group:
        parser.error("At least one --manifest or --resource-group is required")
    variants = load_archive_variants(args.manifest, args.probe_dir) if args.manifest else {}
    variants.update(load_resource_group_variants(args.resource_group, args.probe_dir))
    print(json.dumps(save_layer_references(build_layer_references(variants), args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
