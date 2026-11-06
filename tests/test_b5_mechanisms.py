"""Tests for swift release, team rotation and neighbour cost grant (batch b5)."""
import unittest

from lab import swift_release_runtime as sw
from lab import team_rotation_runtime as tr
from lab import adjacent_cost_runtime as acr


def member(slots=None, **overrides):
    base = {"member_id": "m1", "hp": 100, "max_energy": 12, "energy": 12,
            "skill_slots": slots if slots is not None else [None, None, None, None],
            "stat_modifiers": {}, "field_marks": {}}
    base.update(overrides)
    return base


class SwiftReleaseStateTests(unittest.TestCase):
    def test_wing_charge_resets_after_three(self):
        state = {"teams": {"a": {"active_slot": 0, "members": [member()]}},
                 "swift_pending": {"a": []}}
        actor = state["teams"]["a"]["members"][0]

        class R:
            def skill(self, sid):
                return {"type": "翼系" if sid == 7000001 else "火系"}

        class P:
            _rules = R()

        prepared = P()
        sw.observe_after_skill(state, "a", 7000001, prepared=prepared, turn=1)
        sw.observe_after_skill(state, "a", 7000001, prepared=prepared, turn=2)
        events, queued = sw.observe_after_skill(state, "a", 7000001, prepared=prepared, turn=3)
        self.assertEqual(queued, [7150170])
        self.assertEqual(actor["swift_runtime"]["wing_uses"], 0)
        self.assertTrue(any(e["op"] == "swift.auto_queued" for e in events))

    def test_swift_released_recorded_once(self):
        state = {"teams": {"a": {"active_slot": 0, "members": [member()]}}, "swift_pending": {"a": []}}
        actor = state["teams"]["a"]["members"][0]

        class R:
            def skill(self, sid):
                return {"type": "翼系"}

        class P:
            _rules = R()

        events, _ = sw.observe_after_skill(state, "a", 7150080, prepared=P(), turn=1)
        self.assertEqual(actor["swift_runtime"]["swift_released"], [7150080])
        sw.observe_after_skill(state, "a", 7150080, prepared=P(), turn=2)
        self.assertEqual(actor["swift_runtime"]["swift_released"], [7150080])

    def test_swift_rerelease_cost_half_plus_uses(self):
        # cost = floor(sum of released swift skill costs / 2) + prior uses (0 here)
        actor = member()
        actor["swift_runtime"] = {"wing_uses": 0, "swift_released": [7150080, 7150110], "swift_uses": 0}
        state = {"teams": {"a": {"active_slot": 0, "members": [actor]}}}
        costs = sw._data()["swift_skills"]
        expected = (costs["7150080"]["energy_cost"][0] + costs["7150110"]["energy_cost"][0]) // 2
        cost = sw.swift_release_cost(state, "a", prepared=None, turn=1)
        self.assertEqual(cost, expected)
        # each prior use adds 1
        actor["swift_runtime"]["swift_uses"] = 2
        self.assertEqual(sw.swift_release_cost(state, "a", prepared=None, turn=1), expected + 2)

    def test_auto_skill_cannot_be_actively_used(self):
        program = {"game_id": 7150170}
        result = sw.preflight(program, {"self": member()}, {})
        self.assertEqual(result["status"], "blocked")


class TeamRotationTests(unittest.TestCase):
    def test_rotate_down_crosses_members_and_wraps(self):
        m1 = member([101, 102, 103, 104])
        m2 = member([201, 202, 203, 204])
        state = {"turn": 5, "teams": {"self": {"active_slot": 0, "members": [m1, m2]}}}
        events = tr.rotate_team_down([m1, m2], event_token="t")
        self.assertEqual(m1["skill_slots"], [204, 101, 102, 103])
        self.assertEqual(m2["skill_slots"], [104, 201, 202, 203])
        self.assertEqual(len(events), 2)


class NeighbourCostGrantTests(unittest.TestCase):
    def test_grant_lowers_both_neighbours(self):
        actor = member([100, 101, 102, 103])
        acr.grant(actor, "self", 7070080, 1, amount=-1, response_success=True, turn=2, token="g1")
        self.assertEqual(acr.grant_total(actor, 0), -1)
        self.assertEqual(acr.grant_total(actor, 2), -1)
        self.assertEqual(acr.grant_total(actor, 3), 0)

    def test_grant_stacks_and_is_idempotent_per_token(self):
        actor = member([100, 101, 102, 103])
        acr.grant(actor, "self", 7070080, 1, amount=-1, response_success=True, turn=2, token="g1")
        acr.grant(actor, "self", 7070080, 1, amount=-1, response_success=True, turn=3, token="g2")
        acr.grant(actor, "self", 7070080, 1, amount=-1, response_success=True, turn=3, token="g2")
        self.assertEqual(acr.grant_total(actor, 0), -2)
        acr.validate_member(actor)

    def test_grant_requires_explicit_response_flag(self):
        actor = member([100, 101, 102, 103])
        with self.assertRaises(ValueError):
            acr.grant(actor, "self", 7070080, 1, amount=-1, response_success=None, turn=2, token="g1")

    def test_resolved_cost_includes_grant(self):
        # skill 7070060 adjacent cost config: aura amount -1; slot 0 neighbours slot 1.
        actor = member([100, 7070060, 102, 103])
        acr.grant(actor, "self", 7070080, 1, amount=-1, response_success=True, turn=2, token="g1")
        state = {"teams": {"self": {"active_slot": 0, "members": [actor]}}}
        cost = acr.resolved_cost(state, "self", 100, 0, 3)
        self.assertLessEqual(cost, 3 - 1)  # neighbour grant applies to slot 0


if __name__ == "__main__":
    unittest.main()
