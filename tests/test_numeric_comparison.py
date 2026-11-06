"""Discrimination reports are arithmetic fixtures, not observations."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest

from scripts.compare_numeric_candidates import compare_cases, main


def document():
    return {"schema_version": 1, "cases": [
        {"id": "damage-rounding", "kind": "damage60", "inputs": {
            "attack": 100, "defense": 102, "effective_power": 75, "multiplier": 1.25}},
        {"id": "stat-float32", "kind": "non_hp_stat60", "inputs": {
            "base_stat": 105, "stat": "patk", "nature_multiplier": 1,
            "raw_iv": 0, "display_iv": 0, "iv_mapping_assumption": "raw_iv_equals_six_display_iv"}}]}


class NumericComparisonTests(unittest.TestCase):
    def test_differences_preserve_full_traces_without_claiming_game_evidence(self):
        payload = document()
        before = deepcopy(payload)
        report = compare_cases(payload)
        self.assertEqual(report["disagreement_cases"], 2)
        self.assertEqual([p["nominal_damage"] for p in report["cases"][0]["predictions"]], [82, 83])
        self.assertEqual([p["stat_value"] for p in report["cases"][1]["predictions"]], [175, 176])
        self.assertFalse(report["training_eligible"])
        for case in report["cases"]:
            self.assertFalse(case["is_real_game_observation"])
            for prediction in case["predictions"]:
                self.assertTrue(prediction["trace"])
                self.assertTrue(prediction["source"])
        self.assertEqual(payload, before)

    def test_no_silent_conversion_defaults_duplicate_ids_or_observation_claims(self):
        mutations = [lambda d: d["cases"][1]["inputs"].pop("iv_mapping_assumption"),
                     lambda d: d["cases"][1]["inputs"].update(raw_iv=6),
                     lambda d: d["cases"][1]["inputs"].update(raw_iv=False),
                     lambda d: d["cases"][0]["inputs"].pop("multiplier"),
                     lambda d: d["cases"][1].update(id="damage-rounding"),
                     lambda d: d["cases"][0].update(observed=82),
                     lambda d: d.update(schema_version=True)]
        for mutation in mutations:
            payload = document()
            mutation(payload)
            with self.assertRaises(ValueError):
                compare_cases(payload)

    def test_model_agreement_still_cannot_enable_training(self):
        payload = document()
        payload["cases"] = payload["cases"][:1]
        payload["cases"][0]["inputs"]["multiplier"] = 1
        report = compare_cases(payload)
        self.assertEqual(report["disagreement_cases"], 0)
        self.assertFalse(report["real_game_verified"])
        self.assertFalse(report["calibrated"])

    def test_cli_preserves_prior_evidence_and_rejects_partial_bad_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder)/"input.json", Path(folder)/"report.json"
            source.write_text(json.dumps(document()), encoding="utf-8")
            main(["--input", str(source), "--output", str(target)])
            raw = target.read_bytes()
            main(["--input", str(source), "--output", str(target)])
            changed = document()
            changed["cases"][0]["inputs"]["attack"] = 101
            source.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(ValueError):
                main(["--input", str(source), "--output", str(target)])
            self.assertEqual(target.read_bytes(), raw)
            changed["cases"][1]["kind"] = "unknown"
            source.write_text(json.dumps(changed), encoding="utf-8")
            other = Path(folder)/"partial.json"
            with self.assertRaises(ValueError):
                main(["--input", str(source), "--output", str(other)])
            self.assertFalse(other.exists())


if __name__ == "__main__":
    unittest.main()
