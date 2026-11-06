"""Source records plus constructed phases; these are not real-game calibration."""
from copy import deepcopy
import unittest

from lab import response_cost_runtime as rc
from lab.prepared_rules import PreparedRules
from lab.research_phases import _fragment
from lab.server import load_catalog

MID = 7140170


def member(member_id="a", slots=None):
    return {"member_id": member_id, "hp": 40, "max_hp": 200, "energy": 10, "max_energy": 10,
            "types": ["普通系"], "form_id": 3001, "statuses": {}, "stat_modifiers": {},
            "skill_slots": list(slots if slots is not None else [MID, None, None, None])}


def state_with(row):
    return {"turn": 3, "teams": {"a": {"members": [row], "active_slot": 0},
                                 "b": {"members": [member("b", [None, None, None, None])], "active_slot": 0}}}


class ResponseCostRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.prepared = PreparedRules(cls.catalog)
        cls.programs = rc.programs(cls.prepared)

    def test_source_bound_whole_description_and_layer_count(self):
        program = self.programs[MID]
        self.assertEqual(program["source_description"],
                         "自己回复60%生命，获得物攻+130%，每次应对后本技能能耗-3，使用后能耗重置。")
        components = program["response_cost_components"]
        self.assertEqual(components["heal"]["percent"], {"numerator": 60, "denominator": 100})
        self.assertEqual(components["stat"]["layers"], 13)
        self.assertEqual(components["cost"], {"per_response": -3, "floor": 0, "reset": "on_use", "energy_rule": 9})
        stat_op = [op for op in program["operations"] if op["op"] == "stat.modify"][0]
        self.assertEqual(stat_op["params"]["percent"], {"numerator": 130, "denominator": 100})
        self.assertEqual(stat_op["params"]["attributes"], ["patk"])
        full = program["response_cost_evidence"]["installation_evidence"]["skill_full"]["skill_result"]
        self.assertEqual([row["buff_group_level"] for row in full], [1, 13])

    def test_cost_is_discounted_per_response_and_floored(self):
        row = member()
        state = state_with(row)
        self.assertEqual(rc.resolved_cost(state, "a", MID, 10), 10)
        rc.record_response(row, "a", turn=2, token="r1")
        self.assertEqual(rc.discount(row, MID), -3)
        state["teams"]["a"]["members"][0] = row
        self.assertEqual(rc.resolved_cost(state, "a", MID, 10), 7)
        for index in range(2, 6):
            rc.record_response(row, "a", turn=2 + index, token=f"r{index}")
        self.assertEqual(rc.discount(row, MID), -15)
        self.assertEqual(rc.resolved_cost(state, "a", MID, 10), 0)

    def test_record_only_owned_skill_and_duplicate_token_is_idempotent(self):
        row = member(slots=[None, None, None, None])
        self.assertEqual(rc.record_response(row, "a", turn=2, token="r1"), [])
        self.assertNotIn("response_cost_ledgers", row)
        row = member()
        first = rc.record_response(row, "a", turn=2, token="r1")
        self.assertEqual(first[0]["entries"], 1)
        self.assertEqual(rc.record_response(row, "a", turn=2, token="r1"), [])
        self.assertEqual(len(row["response_cost_ledgers"][str(MID)]["entries"]), 1)

    def test_consume_resets_after_use(self):
        row = member()
        rc.record_response(row, "a", turn=2, token="r1")
        rc.record_response(row, "a", turn=3, token="r2")
        events = rc.consume(row, "a", MID, token="use1")
        self.assertEqual(events[0]["op"], "response_cost.reset")
        self.assertEqual(events[0]["cleared_entries"], 2)
        self.assertNotIn("response_cost_ledgers", row)
        self.assertEqual(rc.consume(row, "a", MID, token="use2"), [])

    def test_execute_heals_and_raises_patk(self):
        row = member()
        program = self.programs[MID]
        context = _fragment(program)
        context.update(rc.research_context(), resolved_energy_cost=10, component_sequence_paid_cost=10,
                       turn=3, response_success=False)
        state = {"self": row, "opponent": member("b", [None, None, None, None])}
        result = rc.execute(program, state, context)
        self.assertEqual(result["status"], "applied", result.get("blockers"))
        self.assertEqual(result["state"]["self"]["hp"], 40 + 120)
        modifiers = result["state"]["self"]["stat_modifiers"].get("patk")
        self.assertTrue(modifiers)
        heal = [event for event in result["events"] if event["op"] == "hp.restore"][0]
        self.assertEqual(heal["hp_policy"], rc.HP_POLICY)

    def test_tampered_ledger_is_rejected(self):
        row = member()
        rc.record_response(row, "a", turn=2, token="r1")
        row["response_cost_ledgers"][str(MID)]["discount"] = -6
        with self.assertRaises(ValueError):
            rc.validate_member(row)


if __name__ == "__main__":
    unittest.main()
