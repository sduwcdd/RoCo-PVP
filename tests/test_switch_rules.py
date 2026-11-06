"""BWIKI switch component regressions; not complete-battle calibration."""
from copy import deepcopy
import unittest

from lab.server import load_catalog
from lab.switch_rules import SwitchRules


def skill(skill_id, swift=True, cost=2):
    return {"skill_id": skill_id, "swift": swift, "effective_cost": cost}


class SwitchRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.rules = SwitchRules(cls.catalog)

    def test_same_turn_entry_blocks_each_exit_effect_but_not_voluntary(self):
        for cause in ("detach", "return", "emergency"):
            r = self.rules.departure(cause, 5, 5, False)
            self.assertEqual(r["status"], "immune")
            self.assertFalse(r["emits_departure"])
        self.assertEqual(self.rules.departure("voluntary", 5, 5, False)["status"], "allowed")

    def test_old_entry_can_depart_without_claiming_complete_switch(self):
        r = self.rules.departure("detach", 3, 5, False)
        self.assertEqual(r["status"], "allowed")
        self.assertTrue(r["emits_departure"])
        self.assertFalse(r["full_switch_executed"])
        self.assertFalse(r["training_eligible"])
        self.assertEqual(r["evidence"]["revision_id"], 7078)

    def test_unknown_entry_turn_is_not_assumed_old(self):
        self.assertEqual(self.rules.departure("detach", None, 5, False)["status"], "unresolved")
        self.assertIsNone(self.rules.departure("detach", None, 5, False)["emits_departure"])

    def test_charge_immunity_does_not_guess_voluntary_cancellation(self):
        for cause in ("detach", "return", "emergency"):
            self.assertEqual(self.rules.departure(cause, None, 5, True)["status"], "immune")
        self.assertEqual(self.rules.departure("voluntary", 2, 5, True)["status"], "unresolved")

    def test_faint_is_not_a_departure_even_when_rooted_charging_or_new(self):
        r = self.rules.departure("faint", 5, 5, True, rooted=True)
        self.assertEqual(r["status"], "allowed")
        self.assertFalse(r["emits_departure"])
        self.assertEqual(r["term_ids"], [3009])

    def test_rooted_blocks_nonfaint_departure(self):
        for cause in ("voluntary", "detach", "return", "emergency"):
            r = self.rules.departure(cause, 1, 5, False, rooted=True)
            self.assertEqual(r["status"], "immune")
            self.assertIn(3023, r["term_ids"])

    def test_invalid_clock_flags_and_cause_are_rejected(self):
        for args in [("detach", 6, 5, False), ("detach", True, 5, False),
                     ("detach", 1, float("nan"), False), ("detach", 1, 5, 1),
                     ("unknown", 1, 5, False)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.rules.departure(*args)

    def test_source_hash_and_actual_definition_drift_require_review(self):
        c = deepcopy(self.catalog)
        c["provenance"]["Terms"]["content_sha256"] = "changed"
        with self.assertRaises(ValueError):
            SwitchRules(c)
        c = deepcopy(self.catalog)
        next(t for t in c["glossary"] if t["key"] == 1005)["definition"] += "changed"
        with self.assertRaises(ValueError):
            SwitchRules(c)

    def test_mark_transfer_preserves_both_slots_and_ownership_metadata(self):
        marks = {"positive": {"id": 1018, "stacks": 3, "source": {"member": "a1"}},
                 "negative": {"id": 1032, "stacks": 2}}
        r = self.rules.transfer_field_marks(marks)
        self.assertEqual(r["marks"], marks)
        r["marks"]["positive"]["source"]["member"] = "mutated"
        self.assertEqual(marks["positive"]["source"]["member"], "a1")
        self.assertFalse(r["mark_effects_resolved"])

    def test_mark_polarity_and_stack_limit_are_never_inferred(self):
        marks = {"positive": None, "negative": None}
        for kwargs in ({}, {"polarity": "positive"}):
            r = self.rules.apply_mark(marks, 1018, 1, **kwargs)
            self.assertEqual(r["status"], "unresolved")
            self.assertEqual(r["marks"], marks)

    def test_explicit_stack_experiment_respects_cap_and_preserves_original(self):
        marks = {"positive": {"id": 1018, "stacks": 3, "source": "a1"}, "negative": None}
        r = self.rules.apply_mark(marks, 1018, 4, "positive", {"mode": "add", "cap": 5})
        self.assertEqual(r["status"], "applied")
        self.assertEqual(r["marks"]["positive"]["stacks"], 5)
        self.assertEqual(r["marks"]["positive"]["source"], "a1")
        self.assertEqual(marks["positive"]["stacks"], 3)
        self.assertFalse(r["polarity_and_stacking_verified"])

    def test_different_mark_does_not_silently_replace_same_polarity(self):
        marks = {"positive": {"id": 1018, "stacks": 1}, "negative": None}
        r = self.rules.apply_mark(marks, 1021, 1, "positive", {"mode": "add", "cap": None})
        self.assertEqual(r["status"], "unresolved")
        self.assertEqual(r["marks"], marks)

    def test_positive_and_negative_slots_can_coexist(self):
        marks = {"positive": {"id": 1018, "stacks": 1}, "negative": None}
        r = self.rules.apply_mark(marks, 1032, 1, "negative", {"mode": "add", "cap": None})
        self.assertEqual(r["marks"]["positive"], marks["positive"])
        self.assertEqual(r["marks"]["negative"], {"id": 1032, "stacks": 1})

    def test_invalid_mark_states_and_numeric_inputs_rejected(self):
        for marks in [{"positive": [], "negative": None},
                      {"positive": {"id": 1018, "stacks": True}, "negative": None},
                      {"positive": {"id": 1018, "stacks": 1}, "negative": {"id": 1018, "stacks": 1}},
                      {"positive": {"id": 99999, "stacks": 1}, "negative": None}]:
            with self.subTest(marks=marks), self.assertRaises(ValueError):
                self.rules.transfer_field_marks(marks)
        with self.assertRaises(ValueError):
            self.rules.apply_mark({"positive": None, "negative": None}, 1018, 1, "positive", {"mode": "add", "cap": float("nan")})

    def test_swift_selects_first_affordable_slot_and_preserves_gaps(self):
        slots = [None, skill(7020360, cost=9), skill(7020370, cost=2), skill(7020380, cost=0)]
        original = deepcopy(slots)
        r = self.rules.swift_first_slot(slots, 3)
        self.assertEqual((r["slot"], r["skill_id"]), (2, 7020370))
        self.assertEqual(slots, original)
        self.assertFalse(r["skill_executed"])

    def test_unknown_potentially_eligible_prior_slot_blocks_later_pick(self):
        for first in [skill(1, swift=None, cost=1), skill(1, swift=True, cost=None)]:
            r = self.rules.swift_first_slot([first, None, skill(2), None], 3)
            self.assertEqual(r["status"], "unresolved")
            self.assertEqual(r["blocking_slot"], 0)
            self.assertIsNone(r["skill_id"])

    def test_known_unaffordable_or_non_swift_slot_can_be_safely_skipped(self):
        slots = [skill(1, swift=None, cost=8), skill(2, swift=False, cost=None), None, skill(3, cost=2)]
        r = self.rules.swift_first_slot(slots, 3)
        self.assertEqual((r["status"], r["slot"]), ("selected", 3))

    def test_no_eligible_swift_does_not_invent_action(self):
        r = self.rules.swift_first_slot([None, skill(1, swift=False), skill(2, cost=9), None], 3)
        self.assertEqual(r["status"], "none")
        self.assertIsNone(r["slot"])

    def test_swift_rejects_malformed_slot_count_and_numeric_flags(self):
        for slots, energy in [([None] * 3, 3), ([skill(1, swift=1), None, None, None], 3),
                              ([skill(1, cost=True), None, None, None], 3), ([None] * 4, True),
                              ([None] * 4, float("nan"))]:
            with self.subTest(slots=slots, energy=energy), self.assertRaises(ValueError):
                self.rules.swift_first_slot(slots, energy)

    def test_intrinsic_swift_comes_from_six_complete_source_records(self):
        for skill_id in (7150080, 7150110, 7150150, 7150260, 7150300, 7150410):
            with self.subTest(skill_id=skill_id):
                result = self.rules.skill_swift_metadata(skill_id)
                self.assertEqual(result["status"], "known")
                self.assertIs(result["swift"], True)
                self.assertEqual(result["source_record"], self.catalog["moves"][str(skill_id)])
                self.assertEqual(result["metadata_scope"], "intrinsic_source_only")
                self.assertFalse(result["external_swift_modifiers_resolved"])
                self.assertFalse(result["training_eligible"])
                self.assertEqual(result["skills_evidence"]["revision_id"], 18764)

    def test_history_grant_and_replayed_swift_are_not_substring_flags(self):
        conditional = self.rules.skill_swift_metadata(7150400)
        self.assertEqual(conditional["status"], "unknown")
        self.assertIsNone(conditional["swift"])
        replay = self.rules.skill_swift_metadata(7150320)
        self.assertEqual(replay["status"], "known")
        self.assertIs(replay["swift"], False)
        ordinary = self.rules.skill_swift_metadata(7020360)
        self.assertEqual(ordinary["status"], "known")
        self.assertIs(ordinary["swift"], False)

    def test_intrinsic_slots_keep_empty_order_and_effective_costs(self):
        ids = [0, 7150110, 7020360, 7150080]
        costs = [None, 8, None, 2]
        before = deepcopy((ids, costs))
        slots = self.rules.swift_candidates(ids, costs)
        self.assertIsNone(slots[0])
        self.assertEqual([x["skill_id"] if x else 0 for x in slots], ids)
        self.assertEqual([x["effective_cost"] if x else None for x in slots], costs)
        selected = self.rules.swift_first_slot(slots, 3)
        self.assertEqual((selected["status"], selected["slot"], selected["skill_id"]),
                         ("selected", 3, 7150080))
        # Source base energy 3 must not replace caller's effective cost 2.
        self.assertEqual(slots[3]["source_metadata"]["source_record"]["energy"], 3)
        self.assertEqual(selected["effective_cost"], 2)
        self.assertEqual((ids, costs), before)

    def test_intrinsic_unknown_ahead_of_known_swift_still_blocks(self):
        for ids, costs in (([7150400, 7150080, 0, 0], [2, 2, None, None]),
                           ([7150080, 7150110, 0, 0], [None, 2, None, None])):
            slots = self.rules.swift_candidates(ids, costs)
            result = self.rules.swift_first_slot(slots, 3)
            self.assertEqual(result["status"], "unresolved")
            self.assertEqual(result["blocking_slot"], 0)

    def test_intrinsic_source_drift_never_falls_back_to_no_swift(self):
        changes = [lambda c: c["provenance"]["Skills"].update(content_sha256="changed"),
                   lambda c: c["moves"]["7150080"]["desc"].update(zh="造成魔伤。"),
                   lambda c: c["moves"]["7020360"].update(desc_notes=[1005]),
                   lambda c: c["moves"]["7020360"].update(effect_details="本技能获得迅捷"),
                   lambda c: c["moves"].pop("7150080")]
        for change in changes:
            catalog = deepcopy(self.catalog)
            change(catalog)
            rules = SwitchRules(catalog)
            # Lazy Skills validation does not disable unrelated old helpers.
            self.assertEqual(rules.departure("voluntary", 1, 3, False)["status"], "allowed")
            with self.assertRaises(ValueError):
                rules.skill_swift_metadata(7150080)

    def test_intrinsic_records_and_source_results_are_owned_copies(self):
        catalog = deepcopy(self.catalog)
        rules = SwitchRules(catalog)
        catalog["moves"]["7150080"]["desc"]["zh"] = "changed after construction"
        result = rules.skill_swift_metadata(7150080)
        self.assertIs(result["swift"], True)
        result["source_record"]["desc"]["zh"] = "changed returned record"
        result["skills_evidence"]["content_sha256"] = "changed returned source"
        slots = rules.swift_candidates([7150080, 0, 0, 0], [3, None, None, None])
        self.assertEqual(slots[0]["source_metadata"]["source_record"]["desc"]["zh"], "造成魔伤，迅捷。")
        self.assertIs(slots[0]["swift"], True)

    def test_intrinsic_candidates_reject_malformed_ids_costs_and_duplicates(self):
        pairs = [([7150080]*3, [3]*4), ([7150080, 0, 0, 0], [3]*3),
                 ([7150080, 0, 0, 0], [3, 0, None, None]),
                 ([7150080, 0, 0, 0], [True, None, None, None]),
                 ([7150080, 0, 0, 0], [-1, None, None, None]),
                 ([7150080, 7150080, 0, 0], [3, 4, None, None]),
                 ([True, 0, 0, 0], [3, None, None, None]),
                 ([9999999, 0, 0, 0], [3, None, None, None])]
        for ids, costs in pairs:
            with self.subTest(ids=ids, costs=costs), self.assertRaises(ValueError):
                self.rules.swift_candidates(ids, costs)
        for value in (False, 0, "7150080", {}, 9999999):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.rules.skill_swift_metadata(value)


if __name__ == "__main__":
    unittest.main()
