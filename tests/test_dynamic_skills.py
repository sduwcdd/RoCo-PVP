"""Deterministic generator mechanics; server timing/RNG remain experimental."""
from copy import deepcopy
import json
import unittest

from lab.action_mechanics import GENERATORS
from lab.dynamic_skills import (POLICY, cost_delta, duplicate_slots_allowed,
                                initialize_dynamic_skills, refresh_round)
from lab.turn_plan import _validate_state


BORROW, MIND, REWRITE = 7020840, 7020850, 7020860


def catalog():
    moves = {str(sid): {"id": sid, "name": {"zh": str(sid)}, "desc": {"zh": spec[3]},
                        "kind": "status", "type": "普通系"} for sid, spec in GENERATORS.items()}
    for sid in (101, 102, 103, 104, 999):
        moves[str(sid)] = {"id": sid, "name": {"zh": str(sid)}, "desc": {"zh": "未支持的额外机制。"},
                           "kind": "status", "type": "普通系"}
    return {"snapshot_id": "dynamic-test", "moves": moves, "details": {
        "1": {"learnset": {"pool": [REWRITE, 101, 102], "stones": [103],
                             "legacy": [{"move": 104}], "legendary": [102]}},
        "2": {"learnset": {"pool": [999]}}}}


def member(mid, slots, form_id=1):
    return {"member_id": mid, "skill_slots": list(slots), "form_id": form_id, "charge": None,
            "hp": 100, "energy": 10, "speed": 100, "entered_turn": 0, "rooted": False}


def battle(*allies, opponent=None):
    return {"snapshot_id": "dynamic-test", "turn": 1, "teams": {
        "a": {"active_slot": 0, "members": list(allies)},
        "b": {"active_slot": 0, "members": [opponent or member("b", [101, 0, 0, 0], 2)]}}}


class DynamicSkillsTests(unittest.TestCase):
    def setUp(self):
        self.catalog = catalog()

    def test_borrow_replaces_slot_and_keeps_original_and_every_source(self):
        state = battle(member("a", [BORROW, 101, 0, 0]), member("reserve", [101, 0, 0, 0]))
        events = refresh_round(self.catalog, state)
        actor = state["teams"]["a"]["members"][0]
        row = actor["dynamic_skill_origins"]["0"]
        self.assertEqual(actor["skill_slots"], [101, 101, 0, 0])
        self.assertEqual(row["origin_skill_id"], BORROW)
        self.assertEqual(row["original_slots"], [BORROW, 101, 0, 0])
        self.assertEqual(row["pool_sources"]["101"][0]["member_id"], "reserve")
        self.assertEqual(cost_delta(actor, 0), 0)
        self.assertEqual(cost_delta(actor, 1), 0)
        self.assertTrue(duplicate_slots_allowed(actor))
        self.assertEqual(events[0]["status"], "generated")
        self.assertEqual(state["dynamic_skills"]["policy"], POLICY)
        json.dumps(state, allow_nan=False)

    def test_planner_only_accepts_traced_dynamic_duplicates(self):
        state = battle(member("a", [BORROW, 101, 0, 0]), member("reserve", [101, 0, 0, 0]))
        refresh_round(self.catalog, state)
        class Rules:
            snapshot_id = "dynamic-test"
            def form(self, sid):
                return {}
            def skill(self, sid):
                return {}
        _validate_state(Rules(), None, state)
        plain = battle(member("a", [101, 101, 0, 0]))
        with self.assertRaisesRegex(ValueError, "source-tracked"):
            _validate_state(Rules(), None, plain)
        state["teams"]["a"]["members"][0]["dynamic_skill_origins"]["0"]["origin_skill_id"] = REWRITE
        with self.assertRaisesRegex(ValueError, "source-tracked"):
            _validate_state(Rules(), None, state)

    def test_rewrite_excludes_original_carried_slots_and_cost_is_minus_two(self):
        state = battle(member("a", [REWRITE, 101, 103, 104]))
        state["teams"]["a"]["members"][0]["original_configuration"] = {"legendary_unlocked_ids": [102]}
        events = refresh_round(self.catalog, state)
        actor = state["teams"]["a"]["members"][0]
        self.assertEqual(events[0]["pool_ids"], [102])
        self.assertEqual(actor["skill_slots"][0], 102)
        self.assertEqual(cost_delta(actor, 0), -2)
        state["turn"] = 2
        refresh_round(self.catalog, state)
        self.assertEqual(actor["dynamic_skill_origins"]["0"]["original_slots"], [REWRITE, 101, 103, 104])
        self.assertEqual(state["teams"]["a"]["members"][0]["skill_slots"][0], 102)

    def test_mind_read_keeps_unsupported_skill_in_distribution_and_actual_slot(self):
        state = battle(member("a", [MIND, 0, 0, 0]))
        events = refresh_round(self.catalog, state)
        actor = state["teams"]["a"]["members"][0]
        self.assertEqual(events[0]["pool_ids"], [999])
        self.assertEqual(actor["skill_slots"][0], 999)
        self.assertEqual(cost_delta(actor, 0), -2)
        # Compile/execution support is intentionally delegated to the caller;
        # no pool filtering or sampling again occurs here.
        self.assertEqual(state["dynamic_skills"]["prng"]["counter"], 1)

    def test_same_seed_replay_same_round_retry_and_rollback_do_not_reroll(self):
        original = battle(member("a", [REWRITE, 0, 0, 0]))
        initialize_dynamic_skills(original, seed=34)
        a, b = deepcopy(original), deepcopy(original)
        first = refresh_round(self.catalog, a)
        self.assertEqual(first, refresh_round(self.catalog, b))
        self.assertEqual(a, b)
        after = deepcopy(a)
        self.assertEqual(refresh_round(self.catalog, a), [])
        self.assertEqual(a, after)
        rolled_back = deepcopy(original)
        self.assertEqual(refresh_round(self.catalog, rolled_back), first)
        self.assertEqual(rolled_back, after)
        with self.assertRaisesRegex(ValueError, "cannot change"):
            initialize_dynamic_skills(a, seed=35)

    def test_next_round_refreshes_again_but_preserves_real_generator_identity(self):
        state = battle(member("a", [REWRITE, 0, 0, 0]))
        refresh_round(self.catalog, state)
        state["turn"] = 2
        events = refresh_round(self.catalog, state)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["origin_skill_id"], REWRITE)
        self.assertEqual(state["dynamic_skills"]["prng"]["counter"], 2)

    def test_both_sides_draw_from_one_frozen_pre_round_snapshot(self):
        state = battle(member("a", [BORROW, 101, 0, 0]), member("reserve", [BORROW, 102, 0, 0]),
                       opponent=member("b", [MIND, 0, 0, 0], 1))
        events = refresh_round(self.catalog, state)
        rows = {e["member_id"]: e for e in events}
        self.assertEqual(rows["a"]["pool_ids"], [102, BORROW])
        self.assertEqual(rows["reserve"]["pool_ids"], [101, BORROW])
        self.assertEqual(rows["b"]["pool_ids"], [101, 102, 103, 104, REWRITE])
        self.assertEqual(state["dynamic_skills"]["frozen_slots"]["a"], [BORROW, 101, 0, 0])

    def test_empty_pool_blocks_specifically_without_spending_rng_or_rerolling(self):
        state = battle(member("a", [BORROW, 0, 0, 0]))
        events = refresh_round(self.catalog, state)
        self.assertEqual(events[0]["blocker_code"], "empty_pool")
        self.assertIn("a slot 0", state["dynamic_skills"]["blockers"][0])
        self.assertEqual(state["dynamic_skills"]["prng"]["counter"], 0)
        after = deepcopy(state)
        self.assertEqual(refresh_round(self.catalog, state), [])
        self.assertEqual(state, after)
        with self.assertRaisesRegex(ValueError, "candidate pool is empty"):
            cost_delta(state["teams"]["a"]["members"][0], 0)

    def test_sampled_generator_recursion_is_committed_as_a_blocked_actual_result(self):
        state = battle(member("a", [BORROW, 0, 0, 0]), member("reserve", [REWRITE, 0, 0, 0]))
        events = refresh_round(self.catalog, state)
        row = next(e for e in events if e["member_id"] == "a")
        self.assertEqual(row["skill_id"], REWRITE)
        self.assertEqual(row["blocker_code"], "recursive_generator")
        self.assertEqual(state["teams"]["a"]["members"][0]["skill_slots"][0], REWRITE)
        self.assertTrue(state["dynamic_skills"]["blockers"])
        after = deepcopy(state)
        self.assertEqual(refresh_round(self.catalog, state), [])
        self.assertEqual(state, after)

    def test_missing_catalog_candidate_is_not_silently_removed(self):
        self.catalog["details"]["2"]["learnset"]["pool"] = [123456]
        state = battle(member("a", [MIND, 0, 0, 0]))
        events = refresh_round(self.catalog, state)
        self.assertEqual(events[0]["pool_ids"], [123456])
        self.assertEqual(events[0]["skill_id"], 123456)
        self.assertEqual(events[0]["blocker_code"], "missing_candidate_record")

    def test_charge_holds_generated_slot_and_skips_draw_until_release(self):
        state = battle(member("a", [REWRITE, 0, 0, 0]))
        refresh_round(self.catalog, state)
        before_id = state["teams"]["a"]["members"][0]["skill_slots"][0]
        before_counter = state["dynamic_skills"]["prng"]["counter"]
        state["teams"]["a"]["members"][0]["charge"] = {"slot": 0, "skill_id": before_id}
        state["turn"] = 2
        events = refresh_round(self.catalog, state)
        self.assertEqual(events[0]["status"], "held_charge")
        self.assertEqual(state["teams"]["a"]["members"][0]["skill_slots"][0], before_id)
        self.assertEqual(state["dynamic_skills"]["prng"]["counter"], before_counter)
        state["teams"]["a"]["members"][0]["charge"] = None
        state["turn"] = 3
        events = refresh_round(self.catalog, state)
        self.assertEqual(events[0]["status"], "generated")
        self.assertEqual(state["dynamic_skills"]["prng"]["counter"], before_counter + 1)

    def test_changed_source_or_invalid_original_is_atomic_and_explicit(self):
        state = battle(member("a", [REWRITE, 0, 0, 0]))
        before = deepcopy(state)
        self.catalog["moves"][str(REWRITE)]["desc"]["zh"] += "额外条件。"
        with self.assertRaisesRegex(ValueError, "source description"):
            refresh_round(self.catalog, state)
        self.assertEqual(state, before)
        invalid = battle(member("a", [101, 101, 0, 0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            refresh_round(catalog(), invalid)


if __name__ == "__main__":
    unittest.main()
