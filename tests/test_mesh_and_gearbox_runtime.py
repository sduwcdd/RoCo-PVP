"""Source records plus constructed phases; these are not real-game calibration."""
import unittest

from lab import adjacent_power_aura_runtime as aura
from lab import slot_stat_runtime as slot_stat
from lab.prepared_rules import PreparedRules
from lab.research_phases import _fragment
from lab.server import load_catalog

MESH = 7070170   # 啮合传递
GEARBOX = 7070070  # 联动装置
ATTACK = 7050330


def member(slots=None):
    return {"member_id": "a", "hp": 100, "max_hp": 200, "energy": 10, "max_energy": 10,
            "types": ["机械系"], "form_id": 3001, "statuses": {}, "stat_modifiers": {},
            "skill_slots": list(slots if slots is not None else [MESH, ATTACK, None, None])}


class MeshTransmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.prepared = PreparedRules(cls.catalog)
        cls.programs = slot_stat.programs(cls.prepared)

    def test_source_bound_whole_description(self):
        program = self.programs[MESH]
        self.assertEqual(program["source_description"], "自己获得速度+30，本技能位于1号或3号位时额外获得物攻+80%，传动1。")
        components = program["slot_stat_components"]
        self.assertEqual(components["base_stats"], [{"attribute": "spd", "percent": None, "layers": 3,
                                                     "per_layer": 10, "buff_id": 20010100}])
        self.assertEqual(components["positional_stats"], {"slots": [0, 2], "attribute": "patk", "layers": 8,
                                                          "per_layer": 10, "buff_id": 20010010})
        self.assertEqual(components["transmission"], 1)
        speeds = [op for op in program["operations"] if op["op"] == "stat.modify"]
        self.assertEqual(speeds[0]["params"]["percent"], {"numerator": 30, "denominator": 100})

    def execute(self, slot):
        program = self.programs[MESH]
        context = _fragment(program)
        context.update(slot_stat.research_context(), resolved_energy_cost=1, component_sequence_paid_cost=1,
                       turn=3, response_success=False, selected_skill_slot=slot)
        state = {"self": member(), "opponent": member([None, None, None, None])}
        return slot_stat.execute(program, state, context)

    def test_slot_one_and_three_get_the_positional_patk(self):
        for slot in (0, 2):
            result = self.execute(slot)
            self.assertEqual(result["status"], "applied", result.get("blockers"))
            self.assertEqual(result["state"]["self"]["stat_modifiers"]["spd"],
                             [{"numerator": 30, "denominator": 100}])
            self.assertTrue(result["state"]["self"]["stat_modifiers"]["patk"])
            self.assertEqual([e["op"] for e in result["events"]].count("slot_stat.positional_applied"), 1)

    def test_slot_two_and_four_do_not_get_the_positional_patk(self):
        for slot in (1, 3):
            result = self.execute(slot)
            self.assertEqual(result["status"], "applied", result.get("blockers"))
            self.assertNotIn("patk", result["state"]["self"]["stat_modifiers"])
            self.assertEqual(result["events"][-1]["op"], "slot_stat.positional_skipped")

    def test_unknown_slot_skips_positional_without_guessing(self):
        result = self.execute(None)
        self.assertEqual(result["status"], "applied", result.get("blockers"))
        self.assertNotIn("patk", result["state"]["self"]["stat_modifiers"])
        self.assertEqual(result["events"][-1]["reason"], "unknown_or_non_matching_slot")

    def test_isolated_preflight(self):
        program = self.programs[MESH]
        context = _fragment(program)
        context.update(slot_stat.research_context())
        self.assertEqual(slot_stat.preflight(program, {"self": member(), "opponent": member()},
                                             context)["status"], "preflight")


class GearboxGrantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.prepared = PreparedRules(cls.catalog)
        cls.programs = aura.programs(cls.prepared)

    def test_source_bound_whole_description(self):
        program = self.programs[GEARBOX]
        self.assertEqual(program["source_description"], "使用后两侧技能的威力永久+20，应对防御：变为威力永久+30。")
        grant = program["adjacent_power_components"]["neighbor_grant"]
        self.assertEqual(grant["amount"], 20)
        self.assertEqual(grant["response_amount"], 30)
        self.assertEqual(grant["targets"], "both_immediate_slots_without_wrap")

    def test_grant_raises_both_neighbours_permanently(self):
        row = member([ATTACK, GEARBOX, ATTACK, None])
        events = aura.grant(row, "a", GEARBOX, 1, response_success=False, turn=3, token="g1")
        self.assertEqual([event["target_slot"] for event in events], [0, 2])
        self.assertEqual(aura.grant_total(row, 0), 20)
        self.assertEqual(aura.modify_power(row, 60, 0), 80)
        self.assertEqual(aura.modify_power(row, 60, 2), 80)
        self.assertEqual(aura.modify_power(row, 60, 1), 60)
        self.assertEqual(aura.modify_power(row, 60, 3), 60)

    def test_response_defense_grant_is_thirty_and_stacks(self):
        row = member([ATTACK, GEARBOX, None, None])
        aura.grant(row, "a", GEARBOX, 1, response_success=True, turn=3, token="g1")
        self.assertEqual(aura.grant_total(row, 0), 30)
        aura.grant(row, "a", GEARBOX, 1, response_success=False, turn=4, token="g2")
        self.assertEqual(aura.grant_total(row, 0), 50)
        self.assertEqual(aura.grant(row, "a", GEARBOX, 1, response_success=True, turn=4, token="g1"), [])

    def test_grant_requires_explicit_classification(self):
        row = member([ATTACK, GEARBOX, None, None])
        with self.assertRaises(ValueError):
            aura.grant(row, "a", GEARBOX, 1, response_success=None, turn=3, token="g1")

    def test_tampered_grant_is_rejected(self):
        row = member([ATTACK, GEARBOX, None, None])
        aura.grant(row, "a", GEARBOX, 1, response_success=False, turn=3, token="g1")
        row["adjacent_power_grants"]["0"]["total"] = 99
        with self.assertRaises(ValueError):
            aura.validate_member(row)

    def test_aura_and_grant_and_growth_combine(self):
        row = member([ATTACK, 7070250, GEARBOX, None])
        aura.record_use(row, 7070250, turn=3, token="u1")
        aura.grant(row, "a", GEARBOX, 2, response_success=False, turn=3, token="g1")
        # slot 1 holds 减压阀: own growth +20; its left neighbour is a plain attack (no aura)
        # and its right neighbour 联动装置 granted +20 to this slot -> 40.
        self.assertEqual(aura.modify_power(row, 0, 1), 40)
        # adding a real power aura on the left makes all three sources stack.
        row["skill_slots"][0] = 7070250
        self.assertEqual(aura.modify_power(row, 0, 1), 50)


if __name__ == "__main__":
    unittest.main()
