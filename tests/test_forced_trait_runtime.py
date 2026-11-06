"""Opt-in boundaries and deferred/after-action departure triggers."""
import unittest

from lab import forced_trait_runtime as forced_traits, trait_runtime
from lab.prepared_rules import prepare_rules
from tests import test_action_runtime as fixtures


class ForcedTraitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.JointActionRuntimeTests.setUpClass()
        cls.catalog = fixtures.JointActionRuntimeTests.catalog
        cls.rules = prepare_rules(cls.catalog)._rules

    def state(self, tid):
        fixture = fixtures.JointActionRuntimeTests()
        fixture.setUp()
        state = fixture.state
        fid = next(row["id"] for row in self.catalog["forms"] if self.rules.form(row["id"]).get("trait_id") == tid)
        state["teams"]["a"]["members"][1]["form_id"] = fid
        return state

    def test_opt_in_and_choice_scope(self):
        state = self.state(200105)
        actor = state["teams"]["a"]["members"][1]
        self.assertIsNone(forced_traits.evidence(self.catalog, state, actor))
        state["trait_policy"] = trait_runtime.POLICY
        self.assertEqual(forced_traits.evidence(self.catalog, state, actor)["trait_id"], 200105)
        forced_traits.preflight_selection(self.catalog, state, "a", None, {"kind": "recharge"})
        forced_traits.preflight_selection(self.catalog, state, "a", None, {"kind": "switch", "target_slot": 0})
        with self.assertRaises(ValueError):
            forced_traits.preflight_selection(self.catalog, state, "a", None, {"kind": "skill", "skill_id": 7021130})

    def test_watchful_binds_even_without_action_and_protection_after_action(self):
        state = self.state(200092)
        state["trait_policy"] = trait_runtime.POLICY
        state["teams"]["a"]["members"][1]["energy"] = 0
        forced_traits.bind_round_choices(self.catalog, state,
            {"a": {"kind": "recharge", "replacement_slot": 0}, "b": {"kind": "recharge"}})
        result = forced_traits.end_round(self.catalog, state, context={})
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["teams"]["a"]["active_slot"], 0)
        state = self.state(200165)
        state["trait_policy"] = trait_runtime.POLICY
        result = forced_traits.after_action(self.catalog, state, "a", {"kind": "recharge",
            "actor_member_id": "a-active"}, replacement_slot=0, context={})
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["teams"]["a"]["active_slot"], 0)


if __name__ == "__main__":
    unittest.main()
