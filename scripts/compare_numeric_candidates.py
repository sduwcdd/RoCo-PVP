"""Compare explicitly requested community formulas; never calibrate an engine.

Input cases are synthetic or caller-provided numerical conditions, NOT game
observations. No result from this command can qualify the RL calibration gate.
"""
from copy import deepcopy
from pathlib import Path
import argparse
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lab.numeric_candidates import (arena_stat60, showdown_non_hp_stat60,
                                    arena_documented_damage60, showdown_documented_damage60)


def compare_cases(document):
    serialized = json.dumps(document, ensure_ascii=False, sort_keys=True, allow_nan=False)
    if (not isinstance(document, dict) or set(document) != {"schema_version", "cases"}
            or type(document["schema_version"]) is not int or document["schema_version"] != 1
            or not isinstance(document["cases"], list) or not 1 <= len(document["cases"]) <= 1000):
        raise ValueError("Expected schema_version=1 and 1..1000 explicit comparison cases")
    rows, ids = [], set()
    for case in document["cases"]:
        if (not isinstance(case, dict) or set(case) != {"id", "kind", "inputs"}
                or not isinstance(case["id"], str) or not case["id"].strip() or case["id"] in ids
                or not isinstance(case["inputs"], dict)):
            raise ValueError("Each case needs a unique ID, comparison kind and explicit inputs")
        ids.add(case["id"])
        inputs = deepcopy(case["inputs"])
        if case["kind"] == "damage60":
            if set(inputs) != {"attack", "defense", "effective_power", "multiplier"}:
                raise ValueError("Damage comparison needs identical explicit panels, effective power and multiplier")
            predictions = [arena_documented_damage60(**inputs), showdown_documented_damage60(**inputs)]
            quantity = "nominal_damage"
        elif case["kind"] == "non_hp_stat60":
            if set(inputs) != {"base_stat", "stat", "nature_multiplier", "raw_iv", "display_iv", "iv_mapping_assumption"}:
                raise ValueError("Stat comparison needs both IV encodings and an explicit mapping assumption")
            if (inputs["iv_mapping_assumption"] != "raw_iv_equals_six_display_iv"
                    or type(inputs["raw_iv"]) is not int or type(inputs["display_iv"]) is not int
                    or inputs["raw_iv"] != 6 * inputs["display_iv"]):
                raise ValueError("No silent IV conversion: supply both values and acknowledge the proposed mapping")
            shared = {key: inputs[key] for key in ("base_stat", "stat", "nature_multiplier")}
            predictions = [arena_stat60(**shared, raw_iv=inputs["raw_iv"]),
                           showdown_non_hp_stat60(**shared, display_iv=inputs["display_iv"])]
            quantity = "stat_value"
        else:
            raise ValueError("Unknown comparison kind; no default formula will be chosen")
        values = [prediction[quantity] for prediction in predictions]
        rows.append({"id": case["id"], "kind": case["kind"], "inputs": inputs,
                     "quantity": quantity, "predictions": predictions,
                     "models_disagree": len(set(values)) > 1,
                     "difference_second_minus_first": values[1] - values[0],
                     "is_real_game_observation": False})
    return {"schema_version": 1, "scope": "community_formula_discrimination",
            "input_sha256": hashlib.sha256(serialized.encode()).hexdigest(),
            "cases": rows, "disagreement_cases": sum(row["models_disagree"] for row in rows),
            "calibrated": False, "training_eligible": False, "real_game_verified": False,
            "warning": "Agreement only compares candidate arithmetic; disagreement identifies a possible measurement condition. Neither certifies a game rule."}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare explicit community numeric candidates; no default battle formula")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.input.stat().st_size > 2_000_000:
        raise ValueError("Comparison input exceeds 2 MB")
    result = compare_cases(json.loads(args.input.read_text(encoding="utf-8-sig")))
    result["implementation_sha256"] = hashlib.sha256((ROOT / "lab/numeric_candidates.py").read_bytes()).hexdigest()
    raw = (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    # Preserve existing evidence. Repeating an identical calculation is a no-op.
    if args.output.exists():
        if args.output.read_bytes() != raw:
            raise ValueError("Output already contains different evidence; choose a new path")
    else:
        with args.output.open("xb") as stream:
            stream.write(raw)
    print(json.dumps({"cases": len(result["cases"]), "disagreements": result["disagreement_cases"],
                      "output": str(args.output), "training_eligible": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
