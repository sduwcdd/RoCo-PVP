"""Joint phase planning regressions, not evidence of complete game fidelity."""
from copy import deepcopy
import unittest

from lab.action_rules import ActionRules
from lab.server import load_catalog
from lab.turn_plan import plan_joint_actions


def actor(mid, form=3001):
    return {"member_id": mid, "form_id": form, "hp": 300, "energy": 10,
            "speed": 100, "entered_turn": 1, "rooted": False, "charge": None,
            "skill_slots": [7020360, 0, 7020780, 0]}


class JointPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]

    def setUp(self):
        self.state = {"snapshot_id": self.catalog["snapshot_id"], "turn": 2,
                      "teams": {side: {"active_slot": 0, "members": [actor(side+"1"), actor(side+"2", 3016)],
                                        "marks": {"positive": None, "negative": None}} for side in ("a", "b")}}
        self.actions = {side: {"kind": "skill", "slot": 0, "effective_cost": 0,
                               "effective_priority": 0} for side in ("a", "b")}

    def plan(self):
        return plan_joint_actions(self.catalog, self.state, self.actions)

    def test_exactly_both_actions_are_required(self):
        del self.actions["b"]
        result = self.plan()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["plans"], {})

    def test_invalid_second_action_never_returns_a_partial_first_plan(self):
        original = deepcopy(self.state)
        self.actions["b"]["slot"] = 1
        result = self.plan()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["plans"], {})
        self.assertEqual(self.state, original)

    def test_order_uses_explicit_priority_and_never_mutates_inputs(self):
        self.actions["a"]["effective_priority"] = 1
        original = deepcopy((self.state, self.actions))
        result = self.plan()
        self.assertEqual(result["status"], "planned", result["blockers"])
        self.assertEqual(result["ordering"]["possible_orders"], [["a", "b"]])
        self.assertFalse(result["battle_executable"])
        self.assertFalse(result["training_eligible"])
        self.assertEqual((self.state, self.actions), original)
        result["plans"]["a"]["program"]["operations"].clear()
        self.assertTrue(self.plan()["plans"]["a"]["program"]["operations"])

    def test_same_priority_does_not_invent_speed_or_random_tie_rules(self):
        self.state["teams"]["a"]["members"][0]["speed"] = 999
        ordering = self.plan()["ordering"]
        self.assertEqual(ordering["status"], "unresolved")
        self.assertEqual(len(ordering["possible_orders"]), 2)
        self.assertNotIn("probabilities", ordering)

    def test_defense_counter_beats_supplied_attack_priority(self):
        self.actions["a"].update(slot=2, effective_priority=-1)
        self.actions["b"]["effective_priority"] = 10
        result = self.plan()
        self.assertEqual(result["ordering"]["possible_orders"], [["a", "b"]])

    def test_unsupported_skill_prevents_false_determined_order(self):
        # 触底强击 now has an explicit experimental energy predicate. The
        # previous-turn state condition of 见招拆招 is still unsupported.
        self.state["teams"]["a"]["members"][0]["skill_slots"][0] = 7020430
        self.actions["a"]["effective_priority"] = 10
        result = self.plan()
        self.assertEqual(result["status"], "planned")
        self.assertEqual(result["ordering"]["status"], "unresolved")
        self.assertTrue(result["unresolved"])

    def test_declared_unresolved_priority_modifier_is_not_discarded(self):
        self.actions["a"].update(effective_priority=10, unresolved_modifiers=["未确认特性修正"])
        self.assertEqual(self.plan()["ordering"]["status"], "unresolved")

    def test_switch_keeps_field_marks_and_does_not_apply_cleanup(self):
        marks = {"positive": {"id": 1018, "stacks": 2, "source": "test"}, "negative": None}
        self.state["teams"]["a"]["marks"] = marks
        self.actions["a"] = {"kind": "switch", "target_slot": 1}
        result = self.plan()
        self.assertEqual(result["status"], "planned", result["blockers"])
        self.assertEqual(result["plans"]["a"]["inherited_marks"]["marks"], marks)
        self.assertEqual(result["ordering"]["status"], "unresolved")
        self.assertEqual(self.state["teams"]["a"]["active_slot"], 0)

    def test_rooted_switch_and_fainted_replacement_reject_ordinary_turn(self):
        self.actions["a"] = {"kind": "switch", "target_slot": 1}
        self.state["teams"]["a"]["members"][0]["rooted"] = True
        self.assertEqual(self.plan()["status"], "blocked")
        self.state["teams"]["a"]["members"][0]["rooted"] = False
        self.state["teams"]["a"]["members"][1]["hp"] = 0
        self.assertEqual(self.plan()["status"], "blocked")

    def test_charge_setup_is_not_attack_release(self):
        self.state["teams"]["a"]["members"][0]["skill_slots"][0] = 7100150
        self.state["teams"]["a"]["members"][0]["energy"] = 0
        plan = self.plan()["plans"]["a"]
        self.assertEqual(plan["execution_phase"], "charge_setup_not_attack_release")
        self.assertEqual(plan["charge_start"]["release_turn"], 3)
        self.assertIsNone(self.state["teams"]["a"]["members"][0]["charge"])
        self.assertEqual(plan["energy_cost_scope"], "current_action_phase")

    def test_source_token_bypasses_setup_without_fabricating_or_consuming_charge(self):
        from lab import duration_runtime as duration
        from lab.research_phases import _fragment
        from lab.turn_plan import charge_admission
        from tests.test_defense_runtime import member
        program = duration.programs(self.catalog)[7100180]
        granted = duration.execute_duration_skill(program, {"self": member(), "opponent": member()},
            {**_fragment(program), **duration.research_context(), "turn": 2, "resolved_energy_cost": 2})
        self.assertEqual(granted["status"], "applied", granted["blockers"])
        actor = self.state["teams"]["a"]["members"][0]
        actor["skill_slots"][0] = 7100150
        actor["timed_effects"] = granted["state"]["self"]["timed_effects"]
        original = deepcopy(actor)
        plan = self.plan()["plans"]["a"]
        self.assertEqual(plan["execution_phase"], "bypass_charge_pending_execution")
        self.assertNotIn("charge_start", plan)
        self.assertNotIn("charge_transition", plan)
        self.assertEqual(actor, original)
        self.assertEqual(charge_admission(self.catalog, actor, 7100150, slot=None, turn=2)["execution_phase"],
                         "bypass_charge_pending_execution")
        self.assertEqual(charge_admission(self.catalog, actor, 7100150, slot=0, turn=4)["execution_phase"],
                         "charge_setup_not_attack_release")
        self.assertEqual(plan["energy_cost_scope"], "execution_cost_without_charge_setup")

    def test_entry_swift_preserves_empty_slots_and_requires_matching_ids(self):
        self.actions["a"] = {"kind": "switch", "target_slot": 1}
        incoming = self.state["teams"]["a"]["members"][1]
        incoming["swift_candidates"] = [
            {"skill_id": 7020360, "swift": False, "effective_cost": 0}, None,
            {"skill_id": 7020780, "swift": True, "effective_cost": 1}, None]
        result = self.plan()
        self.assertEqual(result["status"], "planned", result["blockers"])
        self.assertEqual(result["plans"]["a"]["entry_swift"]["slot"], 2)
        incoming["swift_candidates"][2]["skill_id"] = 7020360
        self.assertEqual(self.plan()["status"], "blocked")

    def test_ready_charge_stays_until_actual_release_commit(self):
        a = self.state["teams"]["a"]["members"][0]
        a["skill_slots"][0] = 7100150
        a["charge"] = ActionRules(self.catalog).charge_state(0, 7100150, 1)
        result = self.plan()
        self.assertEqual(result["status"], "planned", result["blockers"])
        transition = result["plans"]["a"]["charge_transition"]
        self.assertEqual(transition["status"], "ready")
        self.assertEqual(transition["next_charge"], a["charge"])
        self.assertTrue(transition["release_commit_required"])

    def test_invalid_explicit_cost_snapshot_and_identity_are_rejected(self):
        self.actions["a"]["effective_cost"] = True
        self.assertEqual(self.plan()["status"], "blocked")
        self.actions["a"]["effective_cost"] = 0
        self.state["snapshot_id"] = "wrong-version"
        self.assertEqual(self.plan()["status"], "blocked")
        self.state["snapshot_id"] = self.catalog["snapshot_id"]
        self.state["teams"]["a"]["members"][0]["member_id"] = "b1"
        self.assertEqual(self.plan()["status"], "blocked")

    def test_switch_cannot_smuggle_unbound_charge_record(self):
        self.actions["a"] = {"kind": "switch", "target_slot": 1}
        self.state["teams"]["a"]["members"][0]["charge"] = {}
        self.assertEqual(self.plan()["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
