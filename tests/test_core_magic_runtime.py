"""Installed-file evidence is not a server-authoritative magic executor."""
from copy import deepcopy
import unittest

from lab.core_magic_runtime import (execute_core_magic, inspect_core_magic, load_core_magic_rules,
    core_magic_policy, initialize_core_magic, validate_core_magic, effective_skill_cost,
    end_core_magic_round, load_core_magic_subset)


class CoreMagicEvidenceTests(unittest.TestCase):
    def test_item_to_player_magic_to_skill_chain_is_verified_for_both_items(self):
        for item_id, player_id, skill_id in ((104002, 100002, 7010020), (104007, 100007, 7010070)):
            info = inspect_core_magic(item_id)
            self.assertEqual(info["player_magic_id"], player_id)
            self.assertEqual(info["skill_id"], skill_id)
            self.assertTrue(info["executable"])
            self.assertFalse(info["online_mount_verified"])
            self.assertEqual(info["blockers"], [])
            self.assertTrue(info["source_record"]["blockers"])

    def test_wish_use_and_cooldown_fields_remain_separate(self):
        row = inspect_core_magic(104002)["source_record"]
        self.assertEqual(row["item_row"]["initial_use_times"], 99)
        self.assertEqual(row["battle_item_row"]["use_time_in_battle"], 2)
        self.assertEqual(row["player_magic_row"]["round"], 3)
        self.assertEqual(row["skill_row"]["cd_round"], [4, 0])
        self.assertEqual(row["skill_row"]["energy_cost"], [0])
        self.assertEqual(row["effects"]["1039002"]["effect_order"], 39)
        self.assertIn("2126002", row["buff_bases"])
        self.assertIn("wish_conditional_buff", {b["code"] for b in row["blockers"]})

    def test_evolution_mapping_is_retained_without_inventing_stat_transfer(self):
        row = inspect_core_magic(104007)["source_record"]
        self.assertEqual(row["item_row"]["initial_use_times"], 1)
        self.assertEqual(row["battle_item_row"]["use_time_in_battle"], 99)
        self.assertEqual(row["skill_row"]["target_blood_limit"], [19])
        mapping = row["effects"]["1041001"]["effect_param"]
        self.assertEqual(len(mapping[0]["params"]), 223)
        self.assertEqual(len(mapping[1]["params"]), 223)
        self.assertEqual((mapping[0]["params"][0], mapping[1]["params"][0]), (3005, 5001))
        self.assertIn("boss_evolution_state_transfer", {b["code"] for b in row["blockers"]})

    def test_execute_gate_cannot_partially_spend_or_replace_even_with_explicit_cost(self):
        state = {"turn": 2, "teams": {"a": {"energy": 7, "core_magic": {"id": 104002},
                 "members": [{"skill_slots": [7020360, 0, 0, 0]}]}}}
        action = {"kind": "core_magic", "item_id": 104002, "target_slot": 0}
        context = {"resolved_energy_cost": 0, "cooldown": 3, "remaining_uses": 2}
        before = deepcopy((state, action, context))
        result = execute_core_magic(state, action, context)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["state"], state)
        self.assertEqual(result["events"], [])
        self.assertEqual((state, action, context), before)
        self.assertFalse(result["training_eligible"])
        result["state"]["teams"].clear()
        self.assertEqual((state, action, context), before)

    def test_inspection_returns_detached_source_records(self):
        info = inspect_core_magic(104002)
        info["source_record"]["skill_row"]["energy_cost"].clear()
        info["blockers"].clear()
        again = inspect_core_magic(104002)
        self.assertEqual(again["source_record"]["skill_row"]["energy_cost"], [0])
        self.assertEqual(again["blockers"], [])
        self.assertTrue(again["source_record"]["blockers"])

    def test_unreviewed_and_malformed_actions_are_not_silently_normalized(self):
        info = inspect_core_magic(104999)
        self.assertEqual(info["status"], "unsupported")
        self.assertFalse(info["executable"])
        for action in ({"kind": "skill", "item_id": 104002}, {"kind": "core_magic", "item_id": "104002"},
                       {"kind": "core_magic", "item_id": True}):
            result = execute_core_magic({}, action)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["state"], {})
            self.assertEqual(result["events"], [])

    def test_source_review_is_expressly_non_executable(self):
        rules = load_core_magic_rules()
        self.assertFalse(rules["battle_executable"])
        self.assertFalse(rules["online_mount_verified"])
        self.assertEqual(len(rules["records"]), 2)
        self.assertIn("magic_op_info.state", rules["observed_protocol_fields"])


class WaterMagicSubsetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_action_runtime import JointActionRuntimeTests
        JointActionRuntimeTests.setUpClass()
        cls.fixture_class = JointActionRuntimeTests

    def setUp(self):
        fixture = self.fixture_class()
        fixture.setUp()
        self.catalog, self.actions, self.context = fixture.catalog, fixture.actions, fixture.context
        self.state = fixture.state
        self.state["turn"] = 1
        for side, team in self.state["teams"].items():
            team["core_magic"] = {"id": 104004 if side == "a" else None}
            for member in team["members"]:
                member["entered_turn"] = 0
                member["magic_target_states"] = {"drill": False, "static": False, "mimic": False}
        self.state["teams"]["a"]["members"][1]["form_id"] = 3002
        initialize_core_magic(self.state, policy=core_magic_policy())
        self.action = {"kind": "core_magic", "item_id": 104004, "side": "a", "target_slot": 1}

    def cast(self, state=None, action=None):
        return execute_core_magic(self.state if state is None else state, self.action if action is None else action,
                                  {"policy": core_magic_policy()}, catalog=self.catalog)

    def test_full_chain_and_atomic_cast_separate_inventory_uses_cooldown(self):
        rules = load_core_magic_subset()
        self.assertEqual(rules["binary_review"]["row_count"], 34)
        self.assertEqual(rules["buff_bases"]["2032032"]["buffbase_order"], 32)
        before = deepcopy(self.state)
        result = self.cast()
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(before, self.state)
        ledger = result["state"]["core_magic_runtime"]["players"]["a"]
        self.assertEqual((ledger["inventory_remaining"], ledger["battle_uses_remaining"], ledger["next_ready_turn"]), (0, 98, 1000))
        self.assertEqual(result["events"][0]["buff_ids"], [20990010, 20990020])
        self.assertEqual(result["events"][1]["source"]["target_member_id"], "a-active")
        self.assertFalse(result["training_eligible"])
        self.assertFalse(result["online_mount_verified"])
        self.assertEqual(result["state"]["teams"], self.state["teams"])

    def test_zero_cost_reaches_existing_joint_executor_and_expires(self):
        from lab.action_runtime import execute_joint_actions
        state = self.cast()["state"]
        self.actions["a"]["effective_cost"] = effective_skill_cost(state, "a", 2)
        self.actions["b"]["effective_cost"] = effective_skill_cost(state, "b", 2)
        result = execute_joint_actions(self.catalog, state, self.actions, self.context,
                                       damage_resolver=lambda *_: 7)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["energy"], 11)
        self.assertEqual(result["state"]["teams"]["b"]["members"][1]["energy"], 9)
        after = result["state"]
        self.assertEqual(len(end_core_magic_round(after)), 1)
        self.assertEqual(end_core_magic_round(after), [])
        self.assertEqual(effective_skill_cost(after, "a", 2), 2)
        after["turn"] += 1
        validate_core_magic(after)
        self.assertEqual(effective_skill_cost(after, "a", 2), 2)

    def test_failed_type_target_counter_and_missing_state_roll_back(self):
        for mutation in ("type", "target", "cooldown", "inventory", "state", "snapshot", "buffs"):
            state, action = deepcopy(self.state), deepcopy(self.action)
            actor = state["teams"]["a"]["members"][1]
            if mutation == "type": actor["form_id"] = 3001
            if mutation == "target": action["target_slot"] = 0
            if mutation == "cooldown": state["core_magic_runtime"]["players"]["a"]["next_ready_turn"] = 2
            if mutation == "inventory": state["core_magic_runtime"]["players"]["a"]["inventory_remaining"] = 999
            if mutation == "state": actor.pop("magic_target_states")
            if mutation == "snapshot": state["snapshot_id"] = "wrong"
            if mutation == "buffs": actor["buffs"] = {"20990010": 1}
            before = deepcopy(state)
            result = self.cast(state, action)
            self.assertEqual(result["status"], "blocked", mutation)
            self.assertEqual(result["state"], before)
            self.assertEqual(result["events"], [])
            self.assertEqual(state, before)

    def test_duplicate_cast_missing_effect_rebound_and_skipped_round_reject(self):
        result = self.cast()
        state = result["state"]
        duplicate = self.cast(state)
        self.assertEqual(duplicate["status"], "blocked")
        self.assertEqual(duplicate["state"], state)
        for mutation in ("missing", "rebound", "skip"):
            current = deepcopy(state)
            if mutation == "missing": current["core_magic_runtime"]["effects"] = []
            if mutation == "rebound": current["core_magic_runtime"]["effects"][0]["target_member_id"] = "a-reserve"
            if mutation == "skip": current["turn"] += 1
            with self.assertRaises(ValueError, msg=mutation):
                effective_skill_cost(current, "a", 2)

    def test_effect_stays_bound_to_member_across_switch_and_round_expiry(self):
        state = self.cast()["state"]
        state["teams"]["a"]["active_slot"] = 0
        self.assertEqual(effective_skill_cost(state, "a", 2), 2)
        state["teams"]["a"]["active_slot"] = 1
        self.assertEqual(effective_skill_cost(state, "a", 2), 0)
        end_core_magic_round(state)
        self.assertEqual(effective_skill_cost(state, "a", 2), 2)

    def test_fresh_only_initialization_cannot_reset_spent_ledger(self):
        state = self.cast()["state"]
        before = deepcopy(state)
        initialize_core_magic(state, policy=core_magic_policy())
        self.assertEqual(state, before)
        state.pop("core_magic_runtime")
        state["turn"] = 2
        with self.assertRaises(ValueError):
            initialize_core_magic(state, policy=core_magic_policy())
        with self.assertRaises(ValueError):
            initialize_core_magic(deepcopy(self.state), policy={})


if __name__ == "__main__":
    unittest.main()
