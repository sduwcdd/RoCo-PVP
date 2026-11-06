"""Meaningful inference invariants, independent of unverified game mechanics."""

import json
import math
from copy import deepcopy
import unittest

from lab.belief import BeliefFilter


def candidates():
    return [
        dict(id="a", nature_id=1, talents={"atk": 10, "def": 0}, moves=[1, 2], prior=3),
        dict(id="b", nature_id=2, talents={"atk": 20, "def": 0}, moves=[1, 3], prior=1),
    ]


class TestBeliefFilter(unittest.TestCase):
    def test_unestablished_prior_does_not_invent_probabilities(self):
        b = BeliefFilter()
        self.assertEqual(b.status, "prior_not_established")
        self.assertEqual(b.summary()["candidates"], [])
        self.assertIsNone(b.summary()["probability_source"])
        with self.assertRaisesRegex(ValueError, "prior_not_established"):
            b.observe_revealed_move("first", 1)
        self.assertEqual(BeliefFilter.from_dict(b.to_dict()).summary(), b.summary())

    def test_joint_and_marginals_preserve_correlations(self):
        b = BeliefFilter(candidates())
        s = b.summary()
        self.assertEqual([c["posterior"] for c in s["candidates"]], [0.75, 0.25])
        self.assertEqual(s["move_marginals"], [
            dict(move_id=1, probability=1.0), dict(move_id=2, probability=.75),
            dict(move_id=3, probability=.25)])
        self.assertEqual(s["talent_marginals"]["def"], [dict(value=0, probability=1.0)])
        after = b.observe_revealed_move("move", 3)
        self.assertEqual([c["id"] for c in after.summary()["candidates"]], ["b"])
        self.assertEqual(after.summary()["nature_marginal"], [dict(nature_id=2, probability=1.0)])
        self.assertEqual(len(b.summary()["events"]), 0)

    def test_exact_uniform_damage_updates_by_likelihood_not_boolean_match(self):
        b = BeliefFilter(candidates()).observe_damage("hit", 10, {"a": [10, 12], "b": [10, 10]})
        self.assertAlmostEqual(b.summary()["candidates"][0]["posterior"], .5)
        self.assertAlmostEqual(b.summary()["candidates"][1]["posterior"], .5)

    def test_explicit_tolerance_integrates_uniform_mass(self):
        b = BeliefFilter(candidates()).observe_damage("hit", 10, {"a": [9, 12], "b": [11, 11]}, 1)
        self.assertAlmostEqual(b.summary()["candidates"][0]["posterior"], 9 / 13)
        exact = BeliefFilter(candidates()).observe_damage("hit", 10, {"a": [9, 12], "b": [11, 11]})
        self.assertEqual([c["id"] for c in exact.summary()["candidates"]], ["a"])

    def test_empty_intersection_preserves_last_posterior_and_evidence(self):
        original = BeliefFilter(candidates()).observe_revealed_move("a-only", 2)
        mismatch = original.observe_revealed_move("b-only", 3)
        self.assertEqual(mismatch.status, "model_mismatch")
        self.assertEqual(mismatch.summary()["candidates"], original.summary()["candidates"])
        self.assertEqual(mismatch.summary()["unresolved_event_id"], "b-only")
        self.assertEqual(len(mismatch.summary()["events"]), 2)
        self.assertEqual(original.status, "ok")
        with self.assertRaisesRegex(ValueError, "model_mismatch"):
            mismatch.observe_revealed_move("next", 1)
        self.assertIs(mismatch.observe_revealed_move("b-only", 3), mismatch)

    def test_zero_probability_candidate_is_not_revived(self):
        cs = candidates()
        cs[1]["prior"] = 0
        b = BeliefFilter(cs).observe_damage("hit", 20, {"a": [10, 10], "b": [20, 20]})
        self.assertEqual(b.status, "model_mismatch")
        self.assertEqual([c["id"] for c in b.summary()["candidates"]], ["a"])

    def test_event_id_deduplication_and_conflicting_reuse(self):
        b = BeliefFilter(candidates())
        once = b.observe_damage("hit", 10, {"a": [10, 12], "b": [10, 10]})
        twice = once.observe_damage("hit", 10, {"b": [10, 10], "a": [10, 12]})
        self.assertIs(once, twice)
        self.assertEqual(len(twice.summary()["events"]), 1)
        with self.assertRaisesRegex(ValueError, "different evidence"):
            once.observe_damage("hit", 11, {"a": [10, 12], "b": [10, 10]})

    def test_validation_is_transactional(self):
        b = BeliefFilter(candidates())
        before = b.to_dict()
        invalid = [
            (-1, {"a": [0, 1], "b": [0, 1]}, 0),
            (1.0, {"a": [0, 1], "b": [0, 1]}, 0),
            (True, {"a": [0, 1], "b": [0, 1]}, 0),
            (1, {"a": [0, 1]}, 0),
            (1, {"a": [2, 1], "b": [0, 1]}, 0),
            (1, {"a": [0, math.nan], "b": [0, 1]}, 0),
            (1, {"a": [0, 1], "b": [0, 1]}, -1),
        ]
        for damage, predictions, tolerance in invalid:
            with self.subTest(damage=damage, predictions=predictions, tolerance=tolerance):
                with self.assertRaises(ValueError):
                    b.observe_damage("bad", damage, predictions, tolerance)
                self.assertEqual(b.to_dict(), before)

    def test_candidate_validation(self):
        for bad in [math.nan, math.inf, -1, True]:
            cs = candidates()
            cs[0]["prior"] = bad
            with self.assertRaises(ValueError):
                BeliefFilter(cs)
        cs = candidates()
        cs[0]["prior"] = cs[1]["prior"] = 0
        with self.assertRaises(ValueError):
            BeliefFilter(cs)
        cs = candidates()
        cs[1]["id"] = "a"
        with self.assertRaises(ValueError):
            BeliefFilter(cs)
        cs = candidates()
        del cs[0]["prior"]
        with self.assertRaises(ValueError):
            BeliefFilter(cs)

    def test_slot_validation_never_truncates_deduplicates_or_coerces(self):
        invalid = ([1, 2, 3, 4, 5], [1, 1], [0, 1, 0, 1], [True], [-1], [1.0], ["1"])
        for moves in invalid:
            with self.subTest(moves=moves):
                cs = candidates()
                cs[0]["moves"] = moves
                with self.assertRaises(ValueError):
                    BeliefFilter(cs)

    def test_four_ordered_slots_and_empty_slots_survive_roundtrip(self):
        cs = candidates()
        cs[0]["moves"] = [3, 0, 1, 0]
        cs[1]["moves"] = [1, 0, 3, 0]
        b = BeliefFilter(cs)
        saved = json.loads(json.dumps(b.to_dict()))
        self.assertEqual(saved["schema_version"], 3)
        self.assertEqual([c["moves"] for c in saved["candidates"]], [[3, 0, 1, 0], [1, 0, 3, 0]])
        restored = BeliefFilter.from_dict(saved)
        self.assertEqual(restored.summary(), b.summary())
        self.assertEqual(b.summary()["move_marginals"], [
            dict(move_id=1, probability=1.0), dict(move_id=3, probability=1.0)])
        self.assertEqual(b.summary()["move_slot_marginals"][0], {
            "slot": 0, "options": [dict(move_id=1, probability=.25), dict(move_id=3, probability=.75)]})
        self.assertEqual(b.summary()["move_slot_marginals"][1], {
            "slot": 1, "options": [dict(move_id=0, probability=1.0)]})
        # Membership evidence cannot tell these two different slot orders apart.
        after = b.observe_revealed_move("carried", 3)
        for candidate, expected in zip(after.summary()["candidates"], [.75, .25]):
            self.assertAlmostEqual(candidate["posterior"], expected)
        cs[0]["moves"][0] = 999
        saved["candidates"][0]["moves"][0] = 888
        self.assertEqual(b.summary()["candidates"][0]["moves"], [3, 0, 1, 0])

    def test_empty_slots_have_slot_mass_but_are_never_revealed_skills(self):
        cs = candidates()[:1]
        cs[0]["moves"] = [0, 0, 0, 0]
        b = BeliefFilter(cs)
        self.assertEqual(b.summary()["move_marginals"], [])
        self.assertTrue(b.summary()["move_slots_known"])
        self.assertEqual(len(b.summary()["move_slot_marginals"]), 4)
        for slot in b.summary()["move_slot_marginals"]:
            self.assertEqual(slot["options"], [dict(move_id=0, probability=1.0)])
        before = b.to_dict()
        with self.assertRaisesRegex(ValueError, "empty slot"):
            b.observe_revealed_move("not-a-skill", 0)
        self.assertEqual(b.to_dict(), before)

    def test_short_lists_are_preserved_without_claiming_slot_positions(self):
        cs = candidates()
        cs[0]["moves"] = [2, 0, 1]
        b = BeliefFilter(cs)
        self.assertEqual(b.to_dict()["candidates"][0]["moves"], [2, 0, 1])
        self.assertFalse(b.summary()["move_slots_known"])
        self.assertIsNone(b.summary()["move_slot_marginals"])
        cs[0]["move_slots_known"] = True
        with self.assertRaisesRegex(ValueError, "four slots"):
            BeliefFilter(cs)

    def test_unknown_order_is_not_fabricated_for_legacy_saved_beliefs(self):
        cs = candidates()
        cs[0]["moves"] = [0, 1, 2, 3]
        cs[1]["moves"] = [0, 1, 3, 4]
        legacy = {"schema_version": 1, "candidates": cs, "events": []}
        b = BeliefFilter.from_dict(legacy)
        self.assertEqual([c["moves"] for c in b.to_dict()["candidates"]], [c["moves"] for c in cs])
        self.assertTrue(all(not c["move_slots_known"] for c in b.summary()["candidates"]))
        self.assertIsNone(b.summary()["move_slot_marginals"])
        self.assertNotIn("move_slots_known", legacy["candidates"][0])
        self.assertEqual(BeliefFilter.from_dict(b.to_dict()).summary(), b.summary())
        legacy["candidates"][0]["moves"] = [1, 2, 3, 4, 5]
        with self.assertRaisesRegex(ValueError, "four slots"):
            BeliefFilter.from_dict(legacy)

    def test_slot_marginals_require_known_positions_for_positive_mass(self):
        cs = candidates()
        cs[0]["moves"] = [2, 0, 1, 0]
        cs[1]["moves"] = [1, 3, 0, 0]
        cs[1]["move_slots_known"] = False
        b = BeliefFilter(cs)
        self.assertIsNone(b.summary()["move_slot_marginals"])
        b = b.observe_revealed_move("only-a", 2)
        self.assertTrue(b.summary()["move_slots_known"])
        self.assertEqual(b.summary()["move_slot_marginals"][0]["options"], [dict(move_id=2, probability=1.0)])
        for flag in (1, "true", None):
            cs[0]["move_slots_known"] = flag
            with self.assertRaises(ValueError):
                BeliefFilter(cs)

    def test_json_roundtrip_including_mismatch(self):
        b = BeliefFilter(candidates()).observe_damage("hit", 10, {"a": [10, 12], "b": [10, 10]})
        b = b.observe_revealed_move("impossible", 999)
        saved = json.loads(json.dumps(b.to_dict(), allow_nan=False))
        self.assertEqual(BeliefFilter.from_dict(saved).summary(), b.summary())
        saved["events"].append(dict(kind="unknown", event_id="x"))
        with self.assertRaises(ValueError):
            BeliefFilter.from_dict(saved)

    def test_detached_inputs_and_outputs_and_large_finite_priors(self):
        cs = candidates()
        cs[0]["prior"] = cs[1]["prior"] = 1e308
        b = BeliefFilter(cs)
        cs[0]["talents"]["atk"] = 999
        summary = b.summary()
        summary["candidates"][0]["talents"]["atk"] = 888
        self.assertEqual(b.summary()["candidates"][0]["talents"]["atk"], 10)
        self.assertEqual(b.summary()["candidates"][0]["posterior"], .5)

    def pmfs(self):
        return {"a": [{"damage": 10, "probability": .1}, {"damage": 20, "probability": .9}],
                "b": [{"damage": 10, "probability": .9}, {"damage": 20, "probability": .1}]}

    def observe_pmf(self, belief, event="hit", damage=10, predictions=None, tolerance=0, source=None):
        return belief.observe_damage_distribution(
            event, damage, self.pmfs() if predictions is None else predictions, tolerance,
            prediction_source={"id": "test-model", "snapshot_id": "test-snapshot"} if source is None else source)

    def test_pmf_bayes_uses_explicit_mass_not_uniform_support(self):
        b = self.observe_pmf(BeliefFilter(candidates()))
        self.assertAlmostEqual(b.summary()["candidates"][0]["posterior"], .25)
        uniform = BeliefFilter(candidates()).observe_damage("hit", 10, {"a": [10, 20], "b": [10, 20]})
        self.assertAlmostEqual(uniform.summary()["candidates"][0]["posterior"], .75)
        self.assertEqual(b.summary()["damage_likelihood_models"], ["explicit_discrete_pmf"])
        self.assertEqual(b.summary()["damage_prediction_sources"], [
            {"id": "test-model", "snapshot_id": "test-snapshot", "verified": False}])
        self.assertFalse(b.summary()["prediction_verified"])
        self.assertEqual(uniform.summary()["damage_likelihood_models"], ["uniform_integer_range"])

    def test_pmf_tolerance_integrates_sparse_mass_without_filling_gaps(self):
        p = {"a": [{"damage": 9, "probability": .1}, {"damage": 11, "probability": .4}, {"damage": 20, "probability": .5}],
             "b": [{"damage": 9, "probability": .2}, {"damage": 10, "probability": .1}, {"damage": 11, "probability": .1}, {"damage": 20, "probability": .6}]}
        b = self.observe_pmf(BeliefFilter(candidates()), predictions=p, tolerance=1)
        self.assertAlmostEqual(b.summary()["candidates"][0]["posterior"], 15/19)
        exact = self.observe_pmf(BeliefFilter(candidates()), predictions=p)
        self.assertEqual([c["id"] for c in exact.summary()["candidates"]], ["b"])

    def test_pmf_mismatch_preserves_last_posterior_and_blocks_more_updates(self):
        b = self.observe_pmf(BeliefFilter(candidates()))
        mismatch = self.observe_pmf(b, event="impossible", damage=999)
        self.assertEqual(mismatch.status, "model_mismatch")
        self.assertEqual(mismatch.summary()["candidates"], b.summary()["candidates"])
        self.assertEqual(mismatch.summary()["unresolved_event_id"], "impossible")
        self.assertIs(self.observe_pmf(mismatch, event="impossible", damage=999), mismatch)
        with self.assertRaisesRegex(ValueError, "model_mismatch"):
            self.observe_pmf(mismatch, event="later")

    def test_pmf_outcome_order_is_canonical_and_conflicting_reuse_is_rejected(self):
        b = self.observe_pmf(BeliefFilter(candidates()))
        p = {key: list(reversed(rows)) for key, rows in reversed(list(self.pmfs().items()))}
        self.assertIs(self.observe_pmf(b, predictions=p), b)
        with self.assertRaisesRegex(ValueError, "different evidence"):
            self.observe_pmf(b, damage=20)
        p["a"][0]["probability"] = .8
        p["a"][1]["probability"] = .2
        with self.assertRaisesRegex(ValueError, "different evidence"):
            self.observe_pmf(b, predictions=p)

    def test_pmf_validation_never_normalizes_merges_or_mutates_input(self):
        invalid_rows = [[], [{"damage": 10, "probability": 2}],
                        [{"damage": 10, "probability": .5}],
                        [{"damage": 10, "probability": .5}, {"damage": 10, "probability": .5}],
                        [{"damage": True, "probability": 1}], [{"damage": 1.5, "probability": 1}],
                        [{"damage": -1, "probability": 1}], [{"damage": 10, "probability": True}],
                        [{"damage": 10, "probability": math.nan}], [{"damage": 10, "probability": math.inf}],
                        [{"damage": 10, "probability": -1}], [{"damage": 10, "probability": 1, "guessed": True}]]
        b = BeliefFilter(candidates())
        saved = b.to_dict()
        for rows in invalid_rows:
            p = self.pmfs();p["a"] = rows
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.observe_pmf(b, predictions=p)
            self.assertEqual(b.to_dict(), saved)
        for p in ({"a": self.pmfs()["a"]}, {**self.pmfs(), "unknown": self.pmfs()["a"]}):
            with self.assertRaisesRegex(ValueError, "every candidate"):
                self.observe_pmf(b, predictions=p)
        for damage, tolerance in ((True, 0), (1.5, 0), (-1, 0), (10, -1), (10, True)):
            with self.assertRaises(ValueError):
                self.observe_pmf(b, damage=damage, tolerance=tolerance)

    def test_pmf_requires_zero_prior_candidates_and_never_revives_hard_zero(self):
        cs = candidates();cs[1]["prior"] = 0
        b = BeliefFilter(cs)
        with self.assertRaisesRegex(ValueError, "every candidate"):
            self.observe_pmf(b, predictions={"a": self.pmfs()["a"]})
        p = {"a": [{"damage": 10, "probability": 1}], "b": [{"damage": 20, "probability": 1}]}
        mismatch = self.observe_pmf(b, damage=20, predictions=p)
        self.assertEqual(mismatch.status, "model_mismatch")
        self.assertEqual(mismatch.summary()["underflowed_candidate_ids"], [])
        self.assertEqual([c["id"] for c in mismatch.summary()["candidates"]], ["a"])

    def test_pmf_source_is_unverified_and_snapshot_mixing_is_rejected(self):
        b = BeliefFilter(candidates())
        for source in ({}, {"id": "model"}, {"id": "", "snapshot_id": "snapshot"},
                       {"id": "model", "snapshot_id": "snapshot", "calibrated": True}):
            with self.assertRaises(ValueError):
                self.observe_pmf(b, source=source)
        b = self.observe_pmf(b)
        with self.assertRaisesRegex(ValueError, "snapshots differ"):
            self.observe_pmf(b, event="next", source={"id": "test-model", "snapshot_id": "other"})
        self.assertEqual(len(b.summary()["events"]), 1)
        self.assertFalse(b.summary()["events"][0]["prediction_verified"])

    def test_pmf_schema3_replays_and_old_schemas_cannot_claim_new_semantics(self):
        b = self.observe_pmf(BeliefFilter(candidates())).observe_damage("old-range", 10, {"a": [10, 10], "b": [10, 10]})
        saved = json.loads(json.dumps(b.to_dict(), allow_nan=False))
        self.assertEqual(saved["schema_version"], 3)
        self.assertEqual(BeliefFilter.from_dict(saved).summary(), b.summary())
        for version in (1, 2):
            old = deepcopy(saved);old["schema_version"] = version
            with self.assertRaisesRegex(ValueError, "requires belief schema_version 3"):
                BeliefFilter.from_dict(old)
        for key, value in (("prediction_verified", True), ("likelihood_model", "assumed_uniform")):
            forged = deepcopy(saved);forged["events"][0][key] = value
            with self.assertRaisesRegex(ValueError, "unverified likelihood"):
                BeliefFilter.from_dict(forged)
        legacy = BeliefFilter(candidates()).observe_damage("old-range", 10, {"a": [10, 10], "b": [10, 10]}).to_dict()
        legacy["schema_version"] = 2
        self.assertEqual(BeliefFilter.from_dict(legacy).to_dict()["schema_version"], 3)

    def test_pmf_input_output_provenance_and_probabilities_are_detached(self):
        p, source = self.pmfs(), {"id": "test-model", "snapshot_id": "test-snapshot"}
        b = self.observe_pmf(BeliefFilter(candidates()), predictions=p, source=source)
        expected = b.to_dict()
        p["a"][0]["probability"] = .5;source["snapshot_id"] = "changed"
        s = b.summary();s["events"][0]["predictions"]["a"][0]["damage"] = 999
        s["damage_prediction_sources"][0]["id"] = "changed"
        self.assertEqual(b.to_dict(), expected)

    def test_log_posterior_can_recover_after_display_underflow(self):
        cs = candidates();cs[0]["prior"] = cs[1]["prior"] = 1
        cs[0]["move_slots_known"] = False;cs[1]["moves"] = [1, 0, 3, 0]
        tiny = {"a": [{"damage": 0, "probability": 1e-200}, {"damage": 1, "probability": 1.0}],
                "b": [{"damage": 0, "probability": 1.0}]}
        b = self.observe_pmf(BeliefFilter(cs), "low-1", 0, tiny)
        b = self.observe_pmf(b, "low-2", 0, tiny)
        self.assertEqual(b.summary()["underflowed_candidate_ids"], ["a"])
        self.assertFalse(b.summary()["move_slots_known"])
        restored = BeliefFilter.from_dict(json.loads(json.dumps(b.to_dict(), allow_nan=False)))
        opposite = {"a": tiny["b"], "b": tiny["a"]}
        for value in (b, restored):
            value = self.observe_pmf(value, "recover-1", 0, opposite)
            value = self.observe_pmf(value, "recover-2", 0, opposite)
            self.assertEqual(value.status, "ok")
            self.assertEqual(value.summary()["underflowed_candidate_ids"], [])
            for candidate in value.summary()["candidates"]:
                self.assertAlmostEqual(candidate["posterior"], .5, places=12)

    def test_log_prior_retains_extreme_positive_mass_but_true_likelihood_zero_stays_zero(self):
        cs = candidates();cs[0]["prior"] = 1e-300;cs[1]["prior"] = 1e300
        b = BeliefFilter(cs)
        self.assertEqual(b.summary()["underflowed_candidate_ids"], ["a"])
        likelihoods = {"a": [{"damage": 0, "probability": 1.0}],
                       "b": [{"damage": 0, "probability": 1e-300}, {"damage": 1, "probability": 1.0}]}
        b = self.observe_pmf(b, "recover1", 0, likelihoods)
        b = self.observe_pmf(b, "recover2", 0, likelihoods)
        self.assertAlmostEqual(b.summary()["candidates"][0]["posterior"], .5, places=11)
        p = {"a": [{"damage": 0, "probability": 1}], "b": [{"damage": 1, "probability": 1}]}
        eliminated = self.observe_pmf(BeliefFilter(candidates()), "eliminate", 0, p)
        impossible = self.observe_pmf(eliminated, "cannot-revive", 1, p)
        self.assertEqual(impossible.status, "model_mismatch")
        self.assertEqual(impossible.summary()["underflowed_candidate_ids"], [])


if __name__ == "__main__":
    unittest.main()
