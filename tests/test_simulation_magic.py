"""Public water-magic item route, explicit setup and source-bound UI contracts."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from lab.server import load_catalog, import_request
from lab.simulation import DEFAULT_SETTINGS, simulation_request, build_research_context_v2
from lab.core_magic_runtime import effective_skill_cost
from tests.test_simulation import member


class SimulationMagicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]

    def setUp(self):
        self.settings = {**DEFAULT_SETTINGS, "source_mode": "bwiki_only"}
        self.teams = {side: [member(3002), member(3002)] for side in ("my", "opponent")}

    def call(self, operation, payload):
        return simulation_request("/api/simulation/" + operation,
                                  {"settings": self.settings, **payload}, self.catalog)

    def prepare(self, *, selected=True, assume=True):
        if selected:
            for record in self.teams["my"]:
                record["code_provenance"] = {"core_magic": {"id": 104004}}
        state = self.call("prepare", {"teams": self.teams})["state"]
        if assume:
            state["teams"]["a"]["core_magic_experiment"] = {
                "target_states": "assume_absent_drill_static_mimic_experiment"}
        return state

    def test_code_selection_is_retained_and_does_not_invent_target_states(self):
        state = self.prepare(assume=False)
        self.assertEqual(state["teams"]["a"]["core_magic"], {"id": 104004, "source": "code_provenance"})
        started = self.call("start", {"state": state})["state"]
        self.assertNotIn("magic_target_states", started["teams"]["a"]["members"][0])
        before = deepcopy(started)
        result = self.call("magic", {"state": started, "side": "a"})
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("drill/static/mimic" in text for text in result["blockers"]))
        self.assertEqual(result["state"], before)
        self.assertEqual(started, before)

    def test_explicit_assumption_commits_once_through_public_server_route(self):
        state = self.call("start", {"state": self.prepare()})["state"]
        before = deepcopy(state)
        result = import_request("/api/simulation/magic", {"state": state, "settings": self.settings, "side": "a"})
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["turn"], 1)
        self.assertEqual(result["committed_actions"], [])
        self.assertEqual(effective_skill_cost(result["state"], "a", 3), 0)
        self.assertEqual(state, before)
        self.assertEqual(state["teams"]["a"]["members"][0]["original_configuration"]["code_provenance"]["core_magic"]["id"], 104004)
        repeat = self.call("magic", {"state": result["state"], "side": "a"})
        self.assertEqual(repeat["status"], "blocked")
        self.assertEqual(repeat["state"], result["state"])

    def test_unselected_magic_is_not_granted_and_can_be_selected_in_local_copy(self):
        state = self.prepare(selected=False)
        self.assertIsNone(state["teams"]["a"]["core_magic"]["id"])
        started = self.call("start", {"state": state})["state"]
        self.assertNotIn("core_magic_runtime", started)
        self.assertEqual(self.call("magic", {"state": started, "side": "a"})["status"], "blocked")
        state["teams"]["a"]["core_magic"] = {"id": 104004, "source": "simulation_explicit_selection"}
        started = self.call("start", {"state": state})["state"]
        self.assertEqual(self.call("magic", {"state": started, "side": "a"})["status"], "applied")
        self.assertNotIn("code_provenance", self.teams["my"][0])

    def test_mixed_blocked_magic_is_preserved_and_returns_specific_evolution_reason(self):
        state = self.prepare()
        state["teams"]["b"]["core_magic"] = {"id": 104007, "source": "code_provenance"}
        started = self.call("start", {"state": state})["state"]
        result = self.call("magic", {"state": started, "side": "b"})
        self.assertEqual(result["status"], "blocked")
        self.assertIn("boss_evolution_state_transfer", {b["code"] for b in result["mechanism_blockers"]})
        self.assertEqual(result["state"], started)
        self.assertEqual(self.call("magic", {"state": started, "side": "a"})["status"], "applied")

    def test_magic_overrides_final_skill_payment_then_expires_before_next_round(self):
        state = self.call("start", {"state": self.prepare()})["state"]
        cast = self.call("magic", {"state": state, "side": "a"})
        result = self.call("act", {"state": cast["state"], "actions": {
            "a": {"kind": "skill", "slot": 0, "cost": 5}, "b": {"kind": "recharge"}}})
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["teams"]["a"]["members"][0]["energy"], 10)
        self.assertEqual(result["state"]["turn"], 2)
        self.assertEqual(result["state"]["core_magic_runtime"]["effects"], [])
        self.assertTrue(any(event["op"] == "core_magic.expire" for event in result["events"]))
        self.assertEqual(effective_skill_cost(result["state"], "a", 5), 5)

    def test_blocked_mark_program_overrides_a_historical_compiled_fallback(self):
        from lab.simulation import _programs
        from lab.prepared_rules import PreparedRules
        from lab.mark_runtime import blocked_mark_programs
        prepared = PreparedRules(self.catalog)
        mid, blocked = next(iter(blocked_mark_programs(prepared).items()))
        historical = {**deepcopy(blocked), "status": "compiled", "operations": [],
                      "research_action_fields": {"base_energy_cost": 2}}
        selected = {**self.settings, "source_mode": "patch2_components_then_bwiki"}
        with patch("lab.simulation._file_programs", return_value={mid: historical}):
            overrides, info = _programs(prepared, selected, [mid])
        self.assertFalse(info[str(mid)]["supported"])
        self.assertNotIn(mid, overrides)

    def test_blocked_carried_mark_does_not_block_other_moves_or_throw_on_selection(self):
        from lab.mark_runtime import blocked_mark_programs
        from lab.prepared_rules import PreparedRules
        mid = next(iter(blocked_mark_programs(PreparedRules(self.catalog))))
        self.teams["my"][0]["move_ids"] = [7020360, mid, 0, 0]
        state = self.call("start", {"state": self.prepare(selected=False)})["state"]
        before = deepcopy(state)
        denied = self.call("act", {"state": state, "actions": {
            "a": {"kind": "skill", "slot": 1}, "b": {"kind": "recharge"}}})
        self.assertEqual(denied["status"], "blocked")
        self.assertEqual(denied["state"], before)
        self.assertTrue(denied["blockers"])
        allowed = self.call("act", {"state": state, "actions": {
            "a": {"kind": "skill", "slot": 0}, "b": {"kind": "recharge"}}})
        self.assertEqual(allowed["status"], "applied", allowed["blockers"])

    def test_conflicting_code_magic_and_pending_turn_reject(self):
        for record, item in zip(self.teams["my"], (104002, 104007)):
            record["code_provenance"] = {"core_magic": {"id": item}}
        with self.assertRaisesRegex(ValueError, "冲突"):
            self.call("prepare", {"teams": self.teams})
        state = self.call("start", {"state": self.prepare()})["state"]
        state["research_battle"] = {"phase": "awaiting_replacement"}
        with self.assertRaisesRegex(ValueError, "替补"):
            self.call("magic", {"state": state, "side": "a"})

    def test_incoming_costs_use_each_incoming_slots_dynamic_delta(self):
        state = self.prepare(selected=False)
        actions = {"a": {"kind": "switch", "target_slot": 1}, "b": {"kind": "recharge"}}
        with patch("lab.dynamic_skills.cost_delta", side_effect=lambda m, slot: -2 if m["member_id"] == "a:1" else 0), \
                patch("lab.simulation.build_research_context_v2", wraps=build_research_context_v2) as builder:
            self.call("act", {"state": state, "actions": actions})
        costs = builder.call_args.kwargs["incoming_effective_costs"]["a"]
        self.assertEqual(costs[0], 0)
        self.assertTrue(all(value is None or value >= 0 for value in costs))


if __name__ == "__main__":
    unittest.main()
