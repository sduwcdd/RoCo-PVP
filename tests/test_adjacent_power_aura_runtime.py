"""Source records plus constructed phases; these are not real-game calibration."""
import unittest

from lab import adjacent_power_aura_runtime as aura
from lab.prepared_rules import PreparedRules
from lab.research_phases import _fragment
from lab.server import load_catalog

MID = 7070250
ATTACK = 7050330


def member(slots=None):
    return {"member_id": "a", "hp": 100, "max_hp": 200, "energy": 10, "max_energy": 10,
            "types": ["机械系"], "form_id": 3001, "statuses": {}, "stat_modifiers": {},
            "skill_slots": list(slots if slots is not None else [None, MID, ATTACK, None])}


class AdjacentPowerAuraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.prepared = PreparedRules(cls.catalog)
        cls.programs = aura.programs(cls.prepared)

    def test_source_bound_whole_description_and_components(self):
        program = self.programs[MID]
        self.assertEqual(program["source_description"], "主动：本技能被动永久额外+20威力，被动：两侧技能威力+10，传动1。")
        components = program["adjacent_power_components"]
        self.assertEqual(components["own_power"], {"per_use": 20, "permanent": True, "scope": "this_skill_only"})
        self.assertEqual(components["adjacent_power"], {"amount": 10, "targets": "both_immediate_slots_without_wrap"})
        self.assertEqual(components["transmission"], 1)

    def test_aura_boosts_both_neighbours(self):
        row = member([MID, ATTACK, MID, None])
        # Slot 1 sits between two sources -> +20; slot 3 has one source -> +10.
        self.assertEqual(aura.modify_power(row, 60, 1), 80)
        self.assertEqual(aura.modify_power(row, 60, 3), 70)
        # Slot 0's only neighbour is the attack itself -> no aura.
        self.assertEqual(aura.modify_power(row, 60, 0), 60)
        self.assertEqual(aura.modify_power(row, 60, None), 60)

    def test_own_growth_is_additive_and_idempotent(self):
        row = member([None, MID, None, None])
        self.assertEqual(aura.modify_power(row, 0, 1), 0)
        aura.record_use(row, MID, turn=2, token="u1")
        self.assertEqual(aura.own_bonus(row, MID), 20)
        self.assertEqual(aura.modify_power(row, 0, 1), 20)
        aura.record_use(row, MID, turn=2, token="u1")
        self.assertEqual(aura.own_bonus(row, MID), 20)
        aura.record_use(row, MID, turn=3, token="u2")
        self.assertEqual(aura.modify_power(row, 0, 1), 40)

    def test_aura_and_growth_combine_on_a_neighbour(self):
        row = member([None, ATTACK, MID, None])
        aura.record_use(row, MID, turn=2, token="u1")
        # Slot 1 holds the attack; its right neighbour is 减压阀 -> +10, own growth 0.
        self.assertEqual(aura.modify_power(row, 60, 1), 70)
        # The bearing itself keeps only its own growth (+20), never its own aura.
        self.assertEqual(aura.modify_power(row, 0, 2), 20)

    def test_tampered_ledger_is_rejected(self):
        row = member()
        aura.record_use(row, MID, turn=2, token="u1")
        row["adjacent_power_ledgers"][str(MID)]["bonus"] = 60
        with self.assertRaises(ValueError):
            aura.validate_member(row)
        with self.assertRaises(ValueError):
            aura.modify_power(row, 10, 1)

    def test_isolated_preflight(self):
        program = self.programs[MID]
        context = _fragment(program)
        context.update(aura.research_context())
        self.assertEqual(aura.preflight(program, {"self": member(), "opponent": member()},
                                        context)["status"], "preflight")


if __name__ == "__main__":
    unittest.main()
