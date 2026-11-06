"""BWIKI partial precedence/charge timing tests, not game calibration."""
from copy import deepcopy
import unittest

from lab.action_rules import ActionRules
from lab.server import load_catalog


def action(kind="physical", priority=0, speed=100, responses=None):
    return {"kind": kind, "priority": priority, "speed": speed,
            "responses": [] if responses is None else responses}


class ActionRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.rules = ActionRules(cls.catalog)

    def test_hash_and_definition_drift_require_reinspection(self):
        c = deepcopy(self.catalog)
        c["provenance"]["Terms"]["content_sha256"] = "f" * 64
        with self.assertRaises(ValueError):
            ActionRules(c)
        c = deepcopy(self.catalog)
        next(t for t in c["glossary"] if t["key"] == 1020)["definition"] = "先手必定随机"
        with self.assertRaises(ValueError):
            ActionRules(c)

    def test_all_counter_categories_and_rejected_unknown(self):
        for kind in ("physical", "magical", "status", "defense"):
            self.assertEqual(self.rules.counter_matches("attack", kind), kind in ("physical", "magical"))
            self.assertEqual(self.rules.counter_matches("status", kind), kind == "status")
            self.assertEqual(self.rules.counter_matches("defense", kind), kind == "defense")
        with self.assertRaises(ValueError):
            self.rules.counter_matches("attack", "charge")

    def test_higher_priority_beats_speed_and_does_not_require_known_speed(self):
        r = self.rules.order_candidates(action(priority=1, speed=None), action(speed=99999))
        self.assertEqual(r["status"], "determined")
        self.assertEqual(r["possible_orders"], [["a", "b"]])

    def test_signed_priority_not_coerced_to_zero(self):
        r = self.rules.order_candidates(action(priority=-2), action(priority=-1))
        self.assertEqual(r["possible_orders"], [["b", "a"]])

    def test_single_successful_counter_is_first(self):
        r = self.rules.order_candidates(action("defense", -5, 1, ["attack"]), action(priority=9))
        self.assertEqual(r["counter_success"], {"a": True, "b": False})
        self.assertEqual(r["possible_orders"], [["a", "b"]])
        self.assertIn(1016, r["evidence"]["terms"])

    def test_counter_failure_does_not_grant_priority(self):
        r = self.rules.order_candidates(action("defense", -5, 1, ["attack"]), action("status", 0))
        self.assertEqual(r["counter_success"], {"a": False, "b": False})
        self.assertEqual(r["possible_orders"], [["b", "a"]])

    def test_both_counters_do_not_silently_use_priority_or_fair_coin(self):
        r = self.rules.order_candidates(action("status", 9, 999, ["defense"]), action("defense", 0, 1, ["status"]))
        self.assertEqual(r["status"], "unresolved")
        self.assertEqual(r["possible_orders"], [["a", "b"], ["b", "a"]])
        self.assertNotIn("probabilities", r)

    def test_equal_priority_does_not_invent_speed_rule(self):
        for speed in (None, 1, 999, 100):
            r = self.rules.order_candidates(action(speed=speed), action(speed=100))
            self.assertEqual(r["status"], "unresolved")
            self.assertEqual(len(r["possible_orders"]), 2)

    def test_non_skill_categories_require_separate_order_evidence(self):
        for kind in ("switch", "charge", "unknown"):
            r = self.rules.order_candidates(action(kind, 99), action())
            self.assertEqual(r["status"], "unresolved")
            self.assertIsNone(r["counter_success"]["a"])

    def test_pending_modifiers_block_apparent_priority(self):
        a = action(priority=100)
        a["unresolved_modifiers"] = ["未处理特性"]
        self.assertEqual(self.rules.order_candidates(a, action())["status"], "unresolved")

    def test_strict_inputs_not_bool_or_nan_or_duplicate_responses(self):
        for key, value in [("priority", True), ("priority", 1.5), ("speed", float("nan")),
                           ("speed", True), ("responses", None), ("responses", ["attack", "attack"])]:
            a = action()
            a[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.rules.order_candidates(a, action())
        a = action()
        del a["speed"]
        with self.assertRaises(ValueError):
            self.rules.order_candidates(a, action())

    def test_charge_is_one_turn_readiness_not_automatic_execution(self):
        state = self.rules.charge_state(3, 7100150, 7)
        self.assertEqual(state["release_turn"], 8)
        waiting = self.rules.charge_transition(state, current_turn=7, slot=3, skill_id=7100150)
        self.assertEqual(waiting["status"], "waiting")
        self.assertFalse(waiting["release_allowed"])
        ready = self.rules.charge_transition(state, current_turn=8, slot=3, skill_id=7100150)
        self.assertEqual(ready["status"], "ready")
        self.assertTrue(ready["release_allowed"])
        self.assertFalse(ready["execute_skill"])
        self.assertEqual(ready["next_charge"], state)
        self.assertTrue(ready["release_commit_required"])
        self.assertEqual(state["slot"], 3)
        self.assertNotIn("energy", ready)

    def test_charge_not_inferred_from_skip_charge_mentions(self):
        for mid in (7100180, 7100200, 7100250, 7100300, 7020360, 999):
            with self.subTest(skill=mid), self.assertRaises(ValueError):
                self.rules.charge_state(0, mid, 1)

    def test_charge_changed_slot_or_skill_and_expired_turn_are_blocked(self):
        state = self.rules.charge_state(2, 7100150, 4)
        original = deepcopy(state)
        for turn, slot, skill in [(5, 1, 7100150), (5, 2, 7100140), (6, 2, 7100150), (3, 2, 7100150)]:
            result = self.rules.charge_transition(state, current_turn=turn, slot=slot, skill_id=skill)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["next_charge"], original)
        self.assertEqual(state, original)

    def test_tampered_charge_source_or_timing_is_blocked(self):
        for key, value in [("snapshot_id", "new"), ("release_turn", 99), ("started_turn", True),
                           ("source_skill_hash", "fake"), ("term_source_hash", "fake")]:
            state = self.rules.charge_state(0, 7100150, 1)
            state[key] = value
            r = self.rules.charge_transition(state, current_turn=2, slot=0, skill_id=7100150)
            self.assertEqual(r["status"], "blocked")

    def test_charge_slot_and_turn_boundaries(self):
        for slot, turn in [(-1, 1), (4, 1), (True, 1), (0, 0), (0, True)]:
            with self.subTest(slot=slot, turn=turn), self.assertRaises(ValueError):
                self.rules.charge_state(slot, 7100150, turn)

    def test_no_input_aliasing_or_training_claim(self):
        a, b = action(priority=2), action()
        result = self.rules.order_candidates(a, b)
        result["actions"]["a"]["responses"].append("attack")
        result["evidence"]["source"]["content_sha256"] = "changed"
        self.assertEqual(a["responses"], [])
        self.assertFalse(result["training_eligible"])
        self.assertFalse(result["calibrated"])
        self.assertFalse(result["full_turn_executed"])
        self.assertNotEqual(self.rules.order_candidates(a, b)["evidence"]["source"]["content_sha256"], "changed")


if __name__ == "__main__":
    unittest.main()
