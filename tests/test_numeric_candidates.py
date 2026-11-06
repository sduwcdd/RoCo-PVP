"""Formula-expression regression tests, not real-game calibration fixtures."""
from copy import deepcopy
import json
import math
from pathlib import Path
import unittest

from lab.numeric_candidates import (
    CANDIDATE_IDS, arena_stat60, showdown_non_hp_stat60,
    arena_documented_damage60, showdown_documented_damage60,
    evaluate_candidate, _js_round_nonnegative,
)


class NumericCandidateTests(unittest.TestCase):
    def test_published_stat_discriminator_retains_float32_intermediate(self):
        arena = arena_stat60(105, 0, 1, "patk")
        showdown = showdown_non_hp_stat60(105, 0, 1, "patk")
        self.assertEqual((arena["stat_value"], showdown["stat_value"]), (175, 176))
        self.assertEqual(arena["trace"]["core_f32"], 125.49999237060547)
        self.assertEqual(arena["trace"]["float32_casts"], ["base_growth", "core_unrounded"])
        self.assertEqual(showdown["trace"]["float32_casts"], [])

    def test_arena_hp_has_its_own_growth_constant_and_bonus(self):
        self.assertEqual(arena_stat60(105, 0, 1, "hp")["stat_value"], 348)
        self.assertEqual(arena_stat60(105, 60, 1, "hp")["stat_value"], 400)
        self.assertEqual(arena_stat60(105, 60, 1, "patk")["stat_value"], 209)
        hp = arena_stat60(105, 60, 1.2, "hp")
        self.assertEqual(hp["trace"]["growth_factor"], 170)
        self.assertEqual(hp["trace"]["starting_constant"], 70)
        self.assertEqual(hp["trace"]["five_star_bonus"], 100)
        self.assertEqual(hp["stat_value"], 460)

    def test_showdown_guide_panel_examples(self):
        self.assertEqual(showdown_non_hp_stat60(128, 10, 1, "patk")["stat_value"], 234)
        self.assertEqual(showdown_non_hp_stat60(121, 10, 1, "pdef")["stat_value"], 226)
        # The source display rounds the 142.5 * 1.25 * 2 result to 356.
        damage = showdown_documented_damage60(234, 226, 142.5, 2.5)
        self.assertEqual(damage["trace"]["display_power"], 356)
        self.assertEqual(damage["nominal_damage"], 332)

    def test_documented_damage_discriminator_keeps_different_rounding_stage(self):
        arena = arena_documented_damage60(100, 102, 75, 1.25)
        showdown = showdown_documented_damage60(100, 102, 75, 1.25)
        self.assertEqual((arena["nominal_damage"], showdown["nominal_damage"]), (82, 83))
        self.assertEqual(showdown["trace"]["display_power_unrounded"], 93.75)
        self.assertEqual(showdown["trace"]["display_power"], 94)
        self.assertFalse(arena["trace"]["intermediate_power_rounding"])
        self.assertTrue(showdown["trace"]["intermediate_power_rounding"])
        self.assertNotEqual(arena["trace"]["numerator_rounded"], showdown["trace"]["numerator_rounded"])

    def test_zero_power_or_multiplier_remains_zero_no_damage_floor(self):
        for function in (arena_documented_damage60, showdown_documented_damage60):
            for power, multiplier in ((0, 1), (100, 0), (0, 0), (.01, .01)):
                with self.subTest(function=function.__name__, power=power, multiplier=multiplier):
                    result = function(100, 102, power, multiplier)
                    self.assertEqual(result["nominal_damage"], 0)
                    self.assertFalse(result["trace"]["minimum_damage_applied"])

    def test_rounding_half_up_and_large_odd_integer_are_not_python_round_or_add_half(self):
        self.assertEqual(_js_round_nonnegative(2.5), 3)
        self.assertEqual(round(2.5), 2)
        self.assertEqual(_js_round_nonnegative(math.nextafter(2.5, 0)), 2)
        self.assertEqual(_js_round_nonnegative(math.nextafter(2.5, 3)), 3)
        self.assertEqual(_js_round_nonnegative(float(2**53-1)), 2**53-1)
        self.assertEqual(_js_round_nonnegative(-0.0), 0)

    def test_stat_candidates_do_not_convert_or_clamp_iv_encodings(self):
        a = arena_stat60(105, 1, 1, "patk")
        b = showdown_non_hp_stat60(105, 1, 1, "patk")
        self.assertEqual(a["inputs"]["raw_iv"], 1)
        self.assertEqual(b["inputs"]["display_iv"], 1)
        self.assertNotIn("display_iv", a["inputs"])
        self.assertNotIn("raw_iv", b["inputs"])
        self.assertNotEqual(a["stat_value"], b["stat_value"])
        with self.assertRaises(ValueError):
            arena_stat60(105, 61, 1, "patk")
        with self.assertRaises(ValueError):
            showdown_non_hp_stat60(105, 60, 1, "patk")
        with self.assertRaises(ValueError):
            showdown_non_hp_stat60(105, 0, 1, "hp")

    def test_invalid_stat_inputs_are_rejected_not_normalized(self):
        changes = [(0, 0, 1, "patk"), (10001, 0, 1, "patk"), (100.0, 0, 1, "patk"),
                   (True, 0, 1, "patk"), (100, False, 1, "patk"), (100, 1.0, 1, "patk"),
                   (100, -1, 1, "patk"), (100, 0, True, "patk"), (100, 0, "1", "patk"),
                   (100, 0, float("nan"), "patk"), (100, 0, 1.1, "patk"),
                   (100, 0, float("inf"), "patk"), (100, 0, 1, "attack"), (100, 0, 1, [])]
        for function in (arena_stat60, showdown_non_hp_stat60):
            for inputs in changes:
                with self.subTest(function=function.__name__, inputs=inputs):
                    with self.assertRaises(ValueError):
                        function(*inputs)

    def test_all_six_stat_keys_and_explicit_nature_choices(self):
        for stat in ("hp", "patk", "matk", "pdef", "mdef", "spd"):
            values = [arena_stat60(100, 60, nature, stat)["stat_value"] for nature in (.9, 1, 1.2)]
            self.assertLess(values[0], values[1])
            self.assertLess(values[1], values[2])

    def test_damage_inputs_must_be_finite_bounded_explicit_numbers(self):
        for function in (arena_documented_damage60, showdown_documented_damage60):
            for slot in range(4):
                for bad in (True, "100", None, -1, float("nan"), float("inf"), 1_000_001, 10**1000):
                    values = [100, 102, 75, 1.25]
                    values[slot] = bad
                    with self.subTest(function=function.__name__, slot=slot, type=type(bad).__name__):
                        with self.assertRaises(ValueError):
                            function(*values)
            for values in ((0, 100, 10, 1), (100, 0, 10, 1)):
                with self.assertRaises(ValueError):
                    function(*values)

    def test_intermediate_overflow_and_tiny_defense_do_not_return_false_precision(self):
        for function in (arena_documented_damage60, showdown_documented_damage60):
            for values in ((1e6, 1, 1e6, 1e6), (1e6, 5e-324, 1, 1), (1e6, 1e-10, 1e6, 1)):
                with self.subTest(function=function.__name__, values=values):
                    with self.assertRaises(ValueError):
                        function(*values)

    def test_source_identities_match_archived_metadata_and_never_claim_game_verification(self):
        source_rows = json.loads((Path(__file__).resolve().parents[1] /
                                 "data/reference/mechanics-20261025/evidence.json").read_text(encoding="utf-8"))["sources"]
        known = {(s["url"], s["sha256"]) for s in source_rows}
        results = [arena_stat60(105, 0, 1, "patk"), showdown_non_hp_stat60(105, 0, 1, "patk"),
                   arena_documented_damage60(100, 102, 75, 1.25), showdown_documented_damage60(100, 102, 75, 1.25)]
        self.assertEqual({r["candidate_id"] for r in results}, set(CANDIDATE_IDS))
        for result in results:
            self.assertIn((result["source"]["url"], result["source"]["sha256"]), known)
            self.assertFalse(result["calibrated"])
            self.assertFalse(result["real_game_verified"])
            self.assertFalse(result["training_eligible"])
            self.assertNotIn("actual_hp_loss", result)
            if "nominal_damage" in result:
                self.assertFalse(result["source"]["implementation_parity_claimed"])
                self.assertFalse(result["trace"]["hp_clipping_applied"])
                self.assertFalse(result["trace"]["final_multiplier_applied"])
                self.assertTrue(result["trace"]["coefficient_evaluated_before_multiplication"])

    def test_explicit_dispatch_has_no_default_and_preserves_inputs_and_result_isolation(self):
        inputs = {"base_stat": 105, "raw_iv": 0, "nature_multiplier": 1, "stat": "patk"}
        before = deepcopy(inputs)
        result = evaluate_candidate("arena_stat60_v1", inputs)
        self.assertEqual(result, arena_stat60(**inputs))
        result["source"]["sha256"] = "changed"
        result["inputs"]["raw_iv"] = 60
        self.assertEqual(inputs, before)
        self.assertNotEqual(evaluate_candidate("arena_stat60_v1", inputs)["source"]["sha256"], "changed")
        for candidate, data in ((None, inputs), ("default", inputs), ([], inputs), ("arena_stat60_v1", None),
                                ("arena_stat60_v1", {}), ("arena_stat60_v1", {**inputs, "level": 50}),
                                ("arena_stat60_v1", {**inputs, "offset": 1})):
            with self.assertRaises(ValueError):
                evaluate_candidate(candidate, data)


if __name__ == "__main__":
    unittest.main()
