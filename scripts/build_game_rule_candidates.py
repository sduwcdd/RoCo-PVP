"""Verify existing extraction and publish inactive rule candidates."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.game_rule_candidates import load_evidence, load_field_bindings, build_candidates, publish_candidates
from lab.server import load_catalog


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis-dir", type=Path, default=ROOT / "artifacts/unpack_probe_20261025/battle_analysis")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--field-bindings", type=Path)
    args = parser.parse_args()
    evidence = load_evidence(args.analysis_dir)
    result = build_candidates(evidence, load_catalog()[0], load_field_bindings(args.field_bindings, ROOT))
    print(json.dumps(publish_candidates(result, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
