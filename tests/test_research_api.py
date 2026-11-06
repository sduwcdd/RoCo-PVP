"""Service wiring regressions using constructed panels, never calibration."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from lab.research_battle import POLICY
from lab.server import import_request
from tests import test_action_runtime as fixtures


class ResearchApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.JointActionRuntimeTests.setUpClass()

    def setUp(self):
        fixture = fixtures.JointActionRuntimeTests()
        fixture.setUp()
        self.payload = {"state": fixture.state, "actions": fixture.actions,
                        "context": deepcopy(fixture.context), "numeric_policy": {
            "candidate_id": "arena_documented_damage60_v1", "same_type_multiplier": 1,
            "stat_modifier_policy": "linear_signed_terms_experiment"}}
        self.payload["context"].update(mode="research_battle_experiment", policy=POLICY)
        for side in ("a", "b"):
            for member in fixture.state["teams"][side]["members"]:
                member["stats"] = {"patk": 100, "matk": 150, "pdef": 100, "mdef": 150}

    def test_server_owned_formula_runs_deterministically_without_input_changes(self):
        before = deepcopy(self.payload)
        first = import_request("/api/research/turn", self.payload)
        again = import_request("/api/research/turn", self.payload)
        self.assertEqual(first, again)
        self.assertEqual(first["status"], "applied", first["blockers"])
        self.assertEqual(first["state"]["turn"], 3)
        self.assertLess(first["state"]["teams"]["b"]["members"][1]["hp"], 300)
        self.assertIsNotNone(first["numeric_policy"])
        self.assertFalse(first["training_eligible"])
        self.assertFalse(first["real_game_verified"])
        self.assertEqual(before, self.payload)

    def test_lethal_http_path_to_manual_replacement(self):
        self.payload["state"]["teams"]["b"]["members"][1]["hp"] = 1
        result = import_request("/api/research/turn", self.payload)
        self.assertEqual(result["status"], "awaiting_replacement", result["blockers"])
        self.assertEqual(result["committed_actions"], ["a"])
        self.assertEqual(result["skipped_actions"], ["b"])
        resumed = import_request("/api/research/replace", {
            "state": result["state"], "selections": {"b": 0}, "context": self.payload["context"]})
        self.assertEqual(resumed["status"], "applied", resumed["blockers"])
        self.assertEqual(resumed["state"]["turn"], 3)
        self.assertEqual(resumed["state"]["teams"]["b"]["members"][1]["hp"], 0)

    def test_missing_formula_and_malformed_policy_do_not_invent_damage(self):
        self.payload.pop("numeric_policy")
        result = import_request("/api/research/turn", self.payload)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["state"], self.payload["state"])
        self.payload["numeric_policy"] = {"candidate_id": "official_game_formula"}
        with self.assertRaises(ValueError):
            import_request("/api/research/turn", self.payload)

    def test_client_cannot_supply_program_or_observed_damage(self):
        for field in ("program", "program_overrides", "damage_resolver", "predicted_damage"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                import_request("/api/research/turn", {**self.payload, field: {}})

    def test_malformed_game_binding_action_is_a_validation_error(self):
        self.payload["game_sources"] = {"7170280": {"source_id": "test", "policy_version": "test"}}
        self.payload["actions"]["a"] = []
        # Do not load a large real artifact to test this independent HTTP boundary.
        with patch("lab.research_api._program", return_value={}), self.assertRaises(ValueError):
            import_request("/api/research/turn", self.payload)

    def test_verified_patch2_effects_execute_in_research_turn_without_replacing_active_rules(self):
        from lab.game_skill_adapter import VERSION
        self.payload["state"]["teams"]["a"]["members"][1]["skill_slots"][1] = 7170280
        self.payload["game_sources"] = {"7170280": {
            "source_id": "resource-group-c40d72d37c3c43a12b3f", "policy_version": VERSION}}
        before = deepcopy(self.payload)
        result = import_request("/api/research/turn", self.payload)
        self.assertEqual(result["status"], "applied", result["blockers"])
        target = result["state"]["teams"]["b"]["members"][1]
        self.assertEqual(target["stat_modifiers"]["mdef"], [{"numerator": -5000, "denominator": 10000}])
        self.assertEqual(target["energy"], 6)  # 10 - file effect3 - explicit cost2 + scratch1.
        self.assertTrue(result["game_file_bindings"]["7170280"]["source_hash"])
        self.assertFalse(result["training_eligible"])
        self.assertEqual(self.payload, before)

    def test_file_effect_endpoint_preserves_raw_five_layers_and_source_identity(self):
        from lab.game_skill_adapter import VERSION
        from lab.ruleset import BwikiRuleset
        rules = BwikiRuleset(fixtures.JointActionRuntimeTests.catalog)
        state = {relative: deepcopy(self.payload["state"]["teams"][side]["members"][1])
                 for relative, side in (("self", "a"), ("opponent", "b"))}
        for actor in state.values():
            actor["types"] = rules.form(actor["form_id"])["types"]
        result = import_request("/api/research/game-skill", {
            "source_id": "resource-group-c40d72d37c3c43a12b3f", "skill_id": 7170280,
            "policy_version": VERSION, "state": state, "resolved_energy_cost": 2})
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["opponent"]["energy"], 7)
        program = result["program"]
        self.assertEqual(program["snapshot_id"], "game-file:resource-group-c40d72d37c3c43a12b3f")
        self.assertFalse(program["whole_skill_verified"])
        skill_record = next(v["raw"] for k, v in program["game_file_evidence"]["records"].items()
                            if k.endswith("/SKILL_CONF:7170280"))
        self.assertEqual(skill_record["skill_result"][0]["buff_group_level"], 5)


if __name__ == "__main__":
    unittest.main()
