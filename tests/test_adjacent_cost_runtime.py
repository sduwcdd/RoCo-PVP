"""Source records plus constructed phases; these are not real-game calibration."""
import unittest

from lab import adjacent_cost_runtime as adj
from lab.prepared_rules import PreparedRules
from lab.research_phases import _fragment
from lab.server import load_catalog

MID = 7070060
BEARING = 7070060


def member(slots=None):
    return {"member_id": "a", "hp": 100, "max_hp": 200, "energy": 10, "max_energy": 10,
            "types": ["机械系"], "form_id": 3001, "statuses": {}, "stat_modifiers": {},
            "skill_slots": list(slots if slots is not None else [None, BEARING, 7050330, None])}


def state_with(row):
    return {"turn": 3, "teams": {"a": {"members": [row], "active_slot": 0},
                                 "b": {"members": [member([None, None, None, None])], "active_slot": 0}}}


class AdjacentCostRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.prepared = PreparedRules(cls.catalog)
        cls.programs = adj.programs(cls.prepared)

    def test_source_bound_whole_description_and_components(self):
        program = self.programs[MID]
        self.assertEqual(program["source_description"], "主动：本技能被动永久额外-1能耗，被动：两侧技能能耗-1，传动1。")
        components = program["adjacent_cost_components"]
        self.assertEqual(components["base_cost"], 6)
        self.assertEqual(components["own_cost"], {"per_use": -1, "permanent": True, "floor": 0,
                                                  "scope": "this_skill_only"})
        self.assertEqual(components["adjacent_cost"], {"amount": -1, "targets": "both_immediate_slots_without_wrap"})
        self.assertEqual(components["transmission"], 1)
        note = program["adjacent_cost_evidence"]["installation_evidence"]["cost_version_note"]
        self.assertEqual(note["parsed_and_catalog"], 6)
        self.assertEqual(note["older_mirror_build"], 3)

    def test_aura_discounts_both_neighbours_only(self):
        row = member()
        state = state_with(row)
        # Slot 2 (7050330) has neighbours 1 (轴承支撑) and 3 (empty) -> cost 1 less.
        self.assertEqual(adj.resolved_cost(state, "a", 7050330, 2, 4), 3)
        # Slot 1 (轴承支撑 itself) keeps its own cost; its neighbours' aura is for them.
        self.assertEqual(adj.resolved_cost(state, "a", MID, 1, 6), 6)
        # Empty neighbour contributes nothing.
        self.assertEqual(adj.resolved_cost(state, "a", 7050330, 3, 4), 4)

    def test_edge_slot_uses_existing_neighbour(self):
        row = member([BEARING, 7050330, None, None])
        state = state_with(row)
        self.assertEqual(adj.resolved_cost(state, "a", 7050330, 1, 4), 3)
        self.assertEqual(adj.neighbours(0), [1])
        self.assertEqual(adj.neighbours(3), [2])

    def test_permanent_own_discount_accumulates_and_floors(self):
        row = member()
        state = state_with(row)
        adj.record_use(row, "a", MID, turn=2, token="u1")
        self.assertEqual(adj.own_discount(row, MID), -1)
        state["teams"]["a"]["members"][0] = row
        self.assertEqual(adj.resolved_cost(state, "a", MID, 1, 6), 5)
        adj.record_use(row, "a", MID, turn=2, token="u1")
        self.assertEqual(adj.own_discount(row, MID), -1)
        for index in range(2, 8):
            adj.record_use(row, "a", MID, turn=2 + index, token=f"u{index}")
        self.assertEqual(adj.own_discount(row, MID), -7)
        self.assertEqual(adj.resolved_cost(state, "a", MID, 1, 6), 0)

    def test_aura_and_own_discount_combine(self):
        row = member([None, MID, MID, None])
        state = state_with(row)
        adj.record_use(row, "a", MID, turn=2, token="u1")
        state["teams"]["a"]["members"][0] = row
        # Slot 2 holds a bearing: own -1 and a neighbour aura -1 -> 6 - 2 = 4.
        self.assertEqual(adj.resolved_cost(state, "a", MID, 2, 6), 4)

    def test_transmission_tag_is_recorded_only(self):
        row = member()
        self.assertEqual(adj.transmission(row), {1: {"skill_id": MID, "transmission": 1}})

    def test_tampered_ledger_is_rejected(self):
        row = member()
        adj.record_use(row, "a", MID, turn=2, token="u1")
        row["adjacent_cost_ledgers"][str(MID)]["discount"] = -5
        with self.assertRaises(ValueError):
            adj.validate_member(row)

    def test_isolated_preflight(self):
        program = self.programs[MID]
        context = _fragment(program)
        context.update(adj.research_context())
        self.assertEqual(adj.preflight(program, {"self": member(), "opponent": member()},
                                       context)["status"], "preflight")


if __name__ == "__main__":
    unittest.main()
