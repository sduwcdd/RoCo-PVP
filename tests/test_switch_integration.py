"""Source-bound switch fragments compose with state consumers, not full turns."""
from copy import deepcopy
import unittest

from lab.effect_runtime import HOOKS
from lab.prepared_rules import PreparedRules
from lab.server import load_catalog, import_request
from tests.test_action_runtime import member


class SwitchIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = PreparedRules(load_catalog()[0])

    def setUp(self):
        self.state = {"snapshot_id": self.rules.snapshot_id, "turn": 5,
                      "teams": {s: {"active_slot": 0,
                                    "members": [member(s+"-out"), member(s+"-in")],
                                    "marks": {"positive": None, "negative": None}} for s in ("a", "b")}}
        for side in ("a", "b"):
            for actor in self.state["teams"][side]["members"]:
                actor["skill_slots"] = [0, 0, 7030220, 0]
            self.state["teams"][side]["members"][1]["energy"] = 9
        self.context = {"mode": "isolated_voluntary_switch_experiment",
                        "snapshot_id": self.rules.snapshot_id,
                        "catalog_content_hash": self.rules.catalog_content_hash,
                        "excluded_hooks": sorted(HOOKS), "unresolved_dependencies": [],
                        "cleanup_policy": "retain_member_fields_experiment",
                        "swift_policy": "intrinsic_source_only_experiment",
                        "incoming_effective_costs": [None, None, 2, None]}

    def use_wing_entry(self):
        self.state["teams"]["a"]["members"][1]["skill_slots"] = [0, 0, 7150080, 0]
        self.context["incoming_effective_costs"] = [None, None, 3, None]
        program = self.rules.skill_plan(7150080)["program"]
        self.context["entry_timing"] = "after_position_change_experiment"
        self.context["entry_skill_context"] = {
            "mode": "isolated_skill_experiment", "snapshot_id": self.rules.snapshot_id,
            "source_hash": program["source_hash"], "operation_order": "source_text_order_experiment",
            "excluded_hooks": sorted(HOOKS), "unresolved_dependencies": [],
            "damage_policy": "resolver_returns_actual_integer_hp_loss"}

    def test_prepared_entry_executes_selected_slot_with_new_identity_and_paid_energy(self):
        self.use_wing_entry()
        before = deepcopy(self.state)
        calls = []
        def damage(params, state, context):
            calls.append((state["self"]["member_id"], state["self"]["entered_turn"],
                          state["self"]["energy"], context["actor_member_id"],
                          context["opponent_member_id"]))
            return 13
        result = self.rules.execute_switch_fragment(self.state, "a", 1, self.context,
                                                      damage_resolver=damage)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(calls, [("a-in", 5, 6, "a-in", "b-out")])
        self.assertEqual(result["state"]["teams"]["b"]["members"][0]["hp"], 287)
        self.assertEqual(result["state"]["teams"]["a"]["members"][0], before["teams"]["a"]["members"][0])
        self.assertEqual(result["entry_swift"]["slot"], 2)
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["skill_slots"], [0, 0, 7150080, 0])
        self.assertEqual(self.state, before)
        self.assertFalse(result["full_switch_executed"])
        self.assertFalse(result["training_eligible"])

    def test_http_entry_context_cannot_turn_supplied_damage_into_a_formula(self):
        self.use_wing_entry()
        result = import_request("/api/rules/execute-switch", {
            "state": self.state, "side": "a", "target_slot": 1, "context": self.context,
            "predicted_damage": 13, "damage_resolver": 13})
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["state"], self.state)
        self.assertEqual(result["events"], [])
        self.assertTrue(any("resolver" in issue for issue in result["blockers"]))

    def test_new_active_identity_and_ordered_slots_are_used_by_following_fragment(self):
        original = deepcopy(self.state)
        switched = self.rules.execute_switch_fragment(self.state, "a", 1, self.context)
        self.assertEqual(switched["status"], "applied", switched["blockers"])
        actions = {s: {"kind": "skill", "slot": 2, "effective_cost": 2,
                       "effective_priority": int(s == "a")} for s in ("a", "b")}
        program = self.rules.skill_plan(7030220)["program"]
        fragment = {"mode": "isolated_skill_experiment", "snapshot_id": self.rules.snapshot_id,
                    "source_hash": program["source_hash"], "operation_order": "source_text_order_experiment",
                    "excluded_hooks": sorted(HOOKS), "unresolved_dependencies": [],
                    "energy_policy": "clamp_to_declared_max"}
        context = {"mode": "isolated_joint_action_experiment", "excluded_hooks": sorted(HOOKS),
                   "fragments": {s: deepcopy(fragment) for s in ("a", "b")}}
        result = self.rules.execute(switched["state"], actions, context)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["energy"], 17)
        self.assertEqual(result["state"]["teams"]["a"]["members"][0], original["teams"]["a"]["members"][0])
        self.assertTrue(all(e["actor_member_id"] == "a-in" and e["skill_slot"] == 2
                            for e in result["events"] if e["actor_side"] == "a"))
        self.assertEqual(self.state, original)
        self.assertFalse(result["full_turn_executed"])
        # This is state-consumer interoperability, not permission to switch and
        # then take an extra ordinary action during the same real game turn.

    def test_entry_turn_flows_into_departure_effect_immunity_for_both_sides(self):
        for side in ("a", "b"):
            result = self.rules.execute_switch_fragment(self.state, side, 1, self.context)
            self.assertEqual(result["status"], "applied", result["blockers"])
            actor = result["state"]["teams"][side]["members"][1]
            self.assertEqual(actor["entered_turn"], 5)
            switch_rules = self.rules._components()[2]
            departure = switch_rules.departure("detach", actor["entered_turn"], 5, False)
            self.assertEqual(departure["status"], "immune")
            voluntary = switch_rules.departure("voluntary", actor["entered_turn"], 5, False)
            self.assertEqual(voluntary["status"], "allowed")

    def test_http_uses_source_swift_even_if_member_claims_false(self):
        incoming = self.state["teams"]["a"]["members"][1]
        incoming["skill_slots"] = [0, 7150080, 0, 0]
        incoming["swift_candidates"] = [None, {"skill_id": 7150080, "swift": False,
                                               "effective_cost": 0}, None, None]
        self.context["incoming_effective_costs"] = [None, 3, None, None]
        result = import_request("/api/rules/execute-switch",
                                {"state": self.state, "side": "a", "target_slot": 1,
                                 "context": self.context})
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["state"], self.state)
        self.assertEqual(result["events"], [])
        self.assertFalse(result["training_eligible"])

    def test_http_success_retains_marks_and_does_not_spend_resources_or_advance_turn(self):
        self.state["teams"]["a"]["marks"] = {
            "positive": {"id": 1021, "stacks": 1, "source": {"note": "synthetic fixture"}},
            "negative": {"id": 1014, "stacks": 3}}
        result = import_request("/api/rules/execute-switch",
                                {"state": self.state, "side": "a", "target_slot": 1,
                                 "context": self.context})
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["turn"], self.state["turn"])
        self.assertEqual(result["state"]["teams"]["a"]["marks"], self.state["teams"]["a"]["marks"])
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["energy"], 9)
        self.assertFalse(result["full_switch_executed"])
        result["state"]["teams"]["a"]["marks"]["positive"]["source"]["note"] = "changed"
        self.assertEqual(self.state["teams"]["a"]["marks"]["positive"]["source"]["note"], "synthetic fixture")


if __name__ == "__main__":
    unittest.main()
