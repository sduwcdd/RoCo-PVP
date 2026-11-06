"""Heal/fire source-bound experiments; no server-calibration claim."""
from copy import deepcopy
from fractions import Fraction
import unittest

from lab import core_magic_runtime as magic
from tests import test_action_runtime as fixtures


class CoreMagicAdditionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.JointActionRuntimeTests.setUpClass()
        cls.catalog = fixtures.JointActionRuntimeTests.catalog

    def state(self, item):
        fixture = fixtures.JointActionRuntimeTests()
        fixture.setUp()
        state = fixture.state
        state["turn"] = 1
        for side, team in state["teams"].items():
            team["core_magic"] = {"id": item if side == "a" else None}
            for member in team["members"]:
                member["magic_target_states"] = {"drill": False, "static": False, "mimic": False}
        magic.initialize_core_magic(state, policy=magic.core_magic_policy())
        return state

    def cast(self, state, item):
        return magic.execute_core_magic(state, {"kind": "core_magic", "item_id": item,
            "side": "a", "target_slot": 1}, {"policy": magic.core_magic_policy()}, catalog=self.catalog)

    def test_heal_immediate_three_endings_and_no_implicit_revival(self):
        state = self.state(104001)
        actor = state["teams"]["a"]["members"][1]
        actor.update(hp=1, max_hp=350)
        original = deepcopy(state)
        cast = self.cast(state, 104001)
        self.assertEqual(cast["status"], "applied", cast["blockers"])
        self.assertEqual(state, original)
        state = cast["state"]
        actor = state["teams"]["a"]["members"][1]
        self.assertEqual(actor["hp"], 53)
        for turn, hp in ((1, 105), (2, 157), (3, 209), (4, 209)):
            state["turn"] = turn
            magic.end_core_magic_round(state)
            self.assertEqual(actor["hp"], hp)
            self.assertEqual(magic.end_core_magic_round(state), [])
        self.assertEqual(self.cast(state, 104001)["status"], "blocked")
        exhausted = self.cast(self.state(104001), 104001)["state"]
        exhausted["teams"]["a"]["members"][1]["hp"] = 0
        events = magic.end_core_magic_round(exhausted)
        self.assertFalse(any(e["op"] == "core_magic.heal" for e in events))
        self.assertEqual(exhausted["teams"]["a"]["members"][1]["hp"], 0)

    def test_departure_cleans_heal_and_missing_max_hp_rolls_back(self):
        state = self.state(104001)
        del state["teams"]["a"]["members"][1]["max_hp"]
        blocked = self.cast(state, 104001)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["state"], state)
        state = self.cast(self.state(104001), 104001)["state"]
        events = magic.on_core_magic_departure(state, "a", "a-active")
        self.assertEqual(events[0]["reason"], "departure")
        state["teams"]["a"]["active_slot"] = 0
        self.assertEqual(magic.end_core_magic_round(state), [])

    def test_fire_exact_power_bound_target_expiry_and_type_failure(self):
        state = self.state(104003)
        self.assertEqual(self.cast(state, 104003)["status"], "blocked")
        from lab.prepared_rules import prepare_rules
        rules = prepare_rules(self.catalog)._rules
        forms = self.catalog["forms"]
        form_ids = [int(k) for k in forms] if isinstance(forms, dict) else [f["id"] for f in forms]
        fire = next(fid for fid in form_ids if "火系" in rules.form(fid)["types"])
        state["teams"]["a"]["members"][1]["form_id"] = fire
        cast = self.cast(state, 104003)
        self.assertEqual(cast["status"], "applied", cast["blockers"])
        state = cast["state"]
        self.assertEqual(magic.effective_skill_power(state, "a", 51), Fraction(255, 2))
        self.assertEqual(magic.effective_skill_cost(state, "a", 3), 3)
        state["teams"]["a"]["active_slot"] = 0
        self.assertEqual(magic.effective_skill_power(state, "a", 51), 51)
        state["teams"]["a"]["active_slot"] = 1
        magic.end_core_magic_round(state)
        self.assertEqual(magic.effective_skill_power(state, "a", 51), 51)


if __name__ == "__main__":
    unittest.main()
