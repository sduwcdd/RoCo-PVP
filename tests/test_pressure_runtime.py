"""Source records plus constructed phases; these are not real-game calibration."""
from copy import deepcopy
from fractions import Fraction
import unittest

from lab import pressure_runtime as pressure
from lab.prepared_rules import PreparedRules
from lab.research_phases import _fragment
from lab.server import load_catalog

WATER_PHYSICAL = 7050330  # 水系 physical 60; resisted 1/2 by form 3001 (草系)
GRASS_FORM = 3001


def member(member_id):
    return {"member_id": member_id, "hp": 100, "max_hp": 200, "energy": 5, "max_energy": 10,
            "types": ["草系"], "form_id": GRASS_FORM, "statuses": {}, "stat_modifiers": {}}


def battle_state(turn=3):
    return {"turn": turn, "teams": {"a": {"members": [member("a")], "active_slot": 0},
                                    "b": {"members": [member("b")], "active_slot": 0}}}


def packet(kind="damage", before=12, attack_type="水系", ignore=False):
    return {"op": kind, "target": "opponent", "before": before,
            "resolved_params": {"type": attack_type, "ignore_type_resistance": ignore}}


class PressureRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.prepared = PreparedRules(cls.catalog)
        cls.programs = pressure.programs(cls.prepared)

    def context(self):
        return pressure.research_context()

    def install(self, state, token="t1"):
        """Side a uses 排气: side b carries the suppression, side a carries the listener."""
        return pressure.install(state, "a", context=self.context(), turn=state["turn"],
                                token=token, skill_id=7070260)

    def attack(self, state, token="t1", events=None):
        """Side b attacks side a, so the listener armed on side a observes the packet."""
        action = {"kind": "skill", "skill_id": WATER_PHYSICAL, "actor_member_id": "b"}
        return pressure.observe_received_attack(self.prepared, state, "a", action,
                                               events if events is not None else [packet()],
                                               action_token=token, context=self.context())

    def test_source_bound_whole_description_and_reviewed_amounts(self):
        program = self.programs[7070260]
        self.assertEqual(program["source_description"], "敌方获得威力-20，自己每受到1次抵抗伤害（不含连击），敌方额外获得威力-20，使用后重置。")
        self.assertEqual(program["operations"], [{"op": "pressure.plan", "params": {}}])
        components = program["pressure_components"]
        self.assertEqual(components["install"]["amount"], -20)
        self.assertEqual(components["install"]["stacks"], 2)
        self.assertEqual(components["escalation"]["per_resisted_packet"], -20)
        evidence = program["pressure_evidence"]["installation_evidence"]
        self.assertEqual(evidence["buff_bases"]["2064138"]["buffbase_param"][4]["params"], [20230750, 20230750])
        self.assertEqual(evidence["buff_bases"]["2064139"]["buffbase_param"][4]["params"], [1004116])
        self.assertEqual(evidence["effects"]["1004116"]["effect_param"][1]["params"], [20641380])
        self.assertEqual(evidence["buffs"]["20230750"]["desc"], "技能威力-10")

    def test_install_debuffs_opponent_outgoing_power_and_floors_at_zero(self):
        state = battle_state()
        events = self.install(state)
        self.assertEqual(events[0]["op"], "pressure.installed")
        self.assertEqual(events[0]["amount"], -20)
        opponent, actor = state["teams"]["b"]["members"][0], state["teams"]["a"]["members"][0]
        self.assertEqual(pressure.total(opponent), -20)
        self.assertEqual(pressure.modify_power(opponent, 100), 80)
        self.assertEqual(pressure.modify_power(opponent, 15), 0)
        self.assertEqual(pressure.modify_power(actor, 100), 100)
        self.assertEqual(actor["pressure_listeners"][0]["armed"], True)
        self.assertEqual(opponent["pressure_ledger"]["source_skill_id"], 7070260)

    def test_resisted_packet_escalates_once_per_packet(self):
        state = battle_state()
        self.install(state)
        events = self.attack(state, "t1")
        self.assertEqual(events[0]["op"], "pressure.escalated")
        self.assertEqual(pressure.total(state["teams"]["b"]["members"][0]), -40)
        # Same action token must not double count, including a combo sharing the packet.
        combo = [packet(), packet(before=6)]
        self.assertEqual(self.attack(state, "t1", combo), [])
        third = self.attack(state, "t2")
        self.assertEqual(third[0]["op"], "pressure.escalated")
        attacker = state["teams"]["b"]["members"][0]
        self.assertEqual(pressure.total(attacker), -60)
        self.assertEqual(pressure.modify_power(attacker, 100), 40)

    def test_non_resisted_or_empty_packet_does_not_escalate(self):
        state = battle_state()
        self.install(state)
        self.assertEqual(self.attack(state, "t1", [packet(attack_type="普通系")]), [])
        self.assertEqual(self.attack(state, "t2", []), [])
        self.assertEqual(self.attack(state, "t3", [packet(before=0)]), [])
        self.assertEqual(pressure.total(state["teams"]["b"]["members"][0]), -20)

    def test_ignored_resistance_does_not_escalate(self):
        state = battle_state()
        self.install(state)
        self.assertEqual(self.attack(state, "t1", [packet(ignore=True)]), [])

    def test_without_listener_no_escalation(self):
        state = battle_state()
        self.assertEqual(self.attack(state, "t1"), [])
        self.assertNotIn("pressure_ledger", state["teams"]["b"]["members"][0])

    def test_second_install_resets_accumulated_entries(self):
        state = battle_state()
        self.install(state, "t1")
        self.attack(state, "t2")
        self.attack(state, "t3")
        self.assertEqual(pressure.total(state["teams"]["b"]["members"][0]), -60)
        state["turn"] = 4
        self.install(state, "t4")
        attacker = state["teams"]["b"]["members"][0]
        self.assertEqual(len(attacker["pressure_ledger"]["entries"]), 1)
        self.assertEqual(pressure.total(attacker), -20)
        self.assertEqual(pressure.total(state["teams"]["a"]["members"][0]), 0)
        self.assertEqual(len(state["teams"]["a"]["members"][0]["pressure_listeners"]), 1)

    def test_tampered_ledger_is_rejected(self):
        state = battle_state()
        self.install(state)
        ledger = state["teams"]["b"]["members"][0]["pressure_ledger"]
        ledger["entries"][0]["amount"] = -30
        with self.assertRaises(ValueError):
            pressure.validate_member(state["teams"]["b"]["members"][0])
        with self.assertRaises(ValueError):
            pressure.modify_power(state["teams"]["b"]["members"][0], 100)

    def test_resistance_gate_and_isolated_preflight(self):
        matchup = self.prepared._rules.type_multiplier("水系", GRASS_FORM)["multiplier"]
        self.assertEqual(Fraction(matchup["numerator"], matchup["denominator"]), Fraction(1, 2))
        program = self.programs[7070260]
        context = _fragment(program)
        context.update(self.context())
        self.assertEqual(pressure.preflight(program, {"self": member("a"), "opponent": member("b")},
                                            context)["status"], "preflight")


if __name__ == "__main__":
    unittest.main()
