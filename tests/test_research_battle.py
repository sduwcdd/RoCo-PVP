"""Constructed policy regression; no current-game consistency is asserted."""
from copy import deepcopy
import unittest

from lab.action_runtime import execute_joint_actions
from lab.prepared_rules import PreparedRules
from lab.research_battle import (POLICY, execute_research_turn,
                                 choose_research_replacements)
from tests import test_action_runtime as fixture_module


class ResearchBattleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_module.JointActionRuntimeTests.setUpClass()
        cls.prepared = PreparedRules(fixture_module.JointActionRuntimeTests.catalog)

    def setUp(self):
        self.f = fixture_module.JointActionRuntimeTests()
        self.f.setUp()
        self.state, self.actions = self.f.state, self.f.actions
        self.context = deepcopy(self.f.context)
        self.context.update(mode="research_battle_experiment", policy=POLICY)

    def run_turn(self, resolver=lambda p,s,c: 7, **kwargs):
        return execute_research_turn(self.prepared, self.state, self.actions, self.context,
                                     damage_resolver=resolver, **kwargs)

    def pure_first(self):
        self.state["teams"]["a"]["members"][1]["skill_slots"][1] = 7020370
        self.context["fragments"]["a"] = self.f.fragment(7020370)

    def test_explicit_policy_and_resolver_required_without_input_mutation(self):
        before = deepcopy((self.state, self.actions, self.context))
        out = self.run_turn(None)
        self.assertEqual(out["status"], "blocked")
        self.assertEqual(out["committed_actions"], [])
        self.assertEqual(out["state"], self.state)
        self.assertEqual((self.state, self.actions, self.context), before)
        self.context.pop("policy")
        self.assertIn("policy", self.run_turn()["blockers"][0])

    def test_deterministic_ordinary_turn_and_branch_isolation(self):
        before = deepcopy((self.state, self.actions, self.context))
        out, repeat = self.run_turn(), self.run_turn()
        self.assertEqual(out, repeat)
        self.assertEqual(out["status"], "applied")
        self.assertEqual(out["committed_actions"], ["a", "b"])
        self.assertEqual(out["state"]["turn"], 3)
        self.assertTrue(out["turn_advanced"])
        self.assertEqual(out["state"]["teams"]["b"]["members"][1]["hp"], 293)
        self.assertEqual(out["state"]["teams"]["a"]["members"][1]["energy"], 9)
        self.assertFalse(out["training_eligible"])
        self.assertFalse(out["full_turn_executed"])
        self.assertTrue(out["unresolved"])
        out["state"]["teams"]["a"]["members"][0]["hp"] = 1
        self.assertEqual((self.state, self.actions, self.context), before)
        self.assertEqual(repeat["state"]["teams"]["a"]["members"][0]["hp"], 300)

    def test_ko_commits_cost_skips_later_action_and_stops_followup(self):
        calls = []
        def lethal(params, current, context):
            calls.append(context["actor_side"])
            return current[params["target"]]["hp"]
        out = self.run_turn(lethal)
        self.assertEqual(out["status"], "awaiting_replacement", out["blockers"])
        self.assertEqual(calls, ["a"])
        self.assertEqual(out["committed_actions"], ["a"])
        self.assertEqual(out["skipped_actions"], ["b"])
        self.assertEqual(out["pending_replacements"], {"b": [0]})
        self.assertEqual(out["state"]["teams"]["a"]["members"][1]["energy"], 8)
        self.assertEqual(out["state"]["teams"]["b"]["members"][1]["energy"], 10)
        self.assertEqual(out["state"]["turn"], 2)
        self.assertTrue(any(e["op"] == "research.skill_stopped" for e in out["events"]))
        rejected = execute_research_turn(self.prepared, out["state"], self.actions, self.context,
                                         damage_resolver=lethal)
        self.assertEqual(rejected["status"], "blocked")
        self.assertEqual(calls, ["a"])

    def test_manual_replacement_preserves_reserves_marks_and_advances_once(self):
        self.pure_first()
        out = self.run_turn(lambda p,s,c: s[p["target"]]["hp"])
        before = deepcopy(out["state"])
        invalid = choose_research_replacements(self.prepared, out["state"], {"b": 1}, self.context)
        self.assertEqual(invalid["status"], "blocked")
        self.assertEqual(invalid["state"], before)
        replaced = choose_research_replacements(self.prepared, out["state"], {"b": 0}, self.context)
        self.assertEqual(replaced["status"], "applied", replaced["blockers"])
        self.assertEqual(replaced["state"]["turn"], 3)
        self.assertEqual(replaced["state"]["teams"]["b"]["active_slot"], 0)
        self.assertEqual(replaced["state"]["teams"]["b"]["members"][0]["entered_turn"], 2)
        self.assertEqual(replaced["state"]["teams"]["b"]["marks"], before["teams"]["b"]["marks"])
        again = choose_research_replacements(self.prepared, replaced["state"], {"b": 1}, self.context)
        self.assertEqual(again["status"], "blocked")
        self.assertEqual(out["state"], before)

    def test_both_pending_from_imported_state_require_both_valid_choices(self):
        for side in ("a", "b"):
            self.state["teams"][side]["members"][1]["hp"] = 0
        out = self.run_turn()
        self.assertEqual(out["pending_replacements"], {"a": [0], "b": [0]})
        self.assertEqual(out["committed_actions"], [])
        partial = choose_research_replacements(self.prepared, out["state"], {"a": 0}, self.context)
        self.assertEqual(partial["status"], "blocked")
        replaced = choose_research_replacements(self.prepared, out["state"], {"a": 0, "b": 0}, self.context)
        self.assertEqual(replaced["status"], "applied")
        self.assertEqual(replaced["state"]["turn"], 2)
        self.assertFalse(replaced["turn_advanced"])

    def test_last_member_ko_finishes_and_imported_double_exhaustion_draws(self):
        self.pure_first()
        self.state["teams"]["b"]["members"][0]["hp"] = 0
        out = self.run_turn(lambda p,s,c: s[p["target"]]["hp"])
        self.assertEqual((out["status"], out["winner"]), ("finished", "a"))
        self.assertEqual(out["pending_replacements"], {})
        self.assertEqual(out["state"]["turn"], 2)
        for side in ("a", "b"):
            for member in self.state["teams"][side]["members"]:
                member["hp"] = 0
        draw = self.run_turn()
        self.assertEqual((draw["status"], draw["winner"]), ("finished", "draw"))

    def test_second_failure_retains_first_damage_payment_and_prevents_replay(self):
        def resolver(params, current, context):
            if context["actor_side"] == "b":
                raise ValueError("constructed second callback failure")
            return 7
        out = self.run_turn(resolver)
        self.assertEqual(out["status"], "blocked")
        self.assertEqual(out["committed_actions"], ["a"])
        self.assertEqual(out["state"]["teams"]["b"]["members"][1]["hp"], 293)
        self.assertEqual(out["state"]["teams"]["a"]["members"][1]["energy"], 9)
        self.assertEqual(out["state"]["teams"]["b"]["members"][1]["energy"], 10)
        self.assertIn("constructed second callback failure", out["blockers"][0])
        replay = execute_research_turn(self.prepared, out["state"], self.actions, self.context,
                                       damage_resolver=resolver)
        self.assertEqual(replay["committed_actions"], [])
        self.assertEqual(replay["state"], out["state"])

    def test_second_cost_failure_retains_first_magic_mirror_effects(self):
        self.state["teams"]["a"]["members"][1]["skill_slots"][1] = 7170280
        self.context["fragments"]["a"] = self.f.fragment(7170280)
        self.context["fragments"]["a"]["energy_reduction_policy"] = "clamp_to_zero_experiment"
        self.state["teams"]["b"]["members"][1]["energy"] = 4
        calls = []
        out = self.run_turn(lambda *args: calls.append(args) or 7)
        self.assertEqual(out["status"], "blocked")
        self.assertEqual(out["committed_actions"], ["a"])
        self.assertEqual(calls, [])
        self.assertEqual(out["state"]["teams"]["b"]["members"][1]["energy"], 1)
        self.assertEqual(out["state"]["teams"]["a"]["members"][1]["energy"], 8)
        self.assertEqual(out["state"]["teams"]["b"]["members"][1]["stat_modifiers"]["mdef"],
                         [{"numerator": -50, "denominator": 100}])

    def test_multi_hit_stops_after_lethal_hit(self):
        self.f.use_fixed_hits()
        self.context["fragments"] = deepcopy(self.f.context["fragments"])
        calls = []
        def resolver(params, current, context):
            calls.append((context["actor_side"], params["hit_index"]))
            return current[params["target"]]["hp"]
        out = self.run_turn(resolver)
        self.assertEqual(out["status"], "awaiting_replacement", out["blockers"])
        self.assertEqual(calls, [("a", 0)])
        self.assertTrue(any(e["op"] == "research.hits_stopped" for e in out["events"]))

    def test_callbacks_and_return_values_are_isolated(self):
        def resolver(params, current, context):
            current["self"]["hp"] = 0
            params["power"] = 99999
            context["actor_side"] = "mutated"
            return 7
        out = self.run_turn(resolver)
        self.assertEqual(out["status"], "applied")
        self.assertEqual(out["state"]["teams"]["a"]["members"][1]["hp"], 293)
        self.assertEqual(self.state["teams"]["a"]["members"][1]["hp"], 300)

    def test_trusted_program_override_uses_its_source_and_does_not_mutate_inputs(self):
        program = deepcopy(self.f.programs["7020360"])
        program["source_hash"] = "trusted-adapter-constructed-hash"
        program["operations"][0]["params"]["power"] = 77
        overrides = {7020360: program}
        original = deepcopy(overrides)
        seen = []
        def resolver(params, current, context):
            seen.append((params["power"], context["source_hash"]))
            return 7
        out = self.run_turn(resolver, program_overrides=overrides)
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertEqual(seen, [(77, program["source_hash"])] * 2)
        self.assertEqual(overrides, original)
        overrides[7020360]["game_id"] = 7020370
        self.assertEqual(self.run_turn(program_overrides=overrides)["status"], "blocked")

    def test_existing_strict_joint_api_still_rolls_back_ko(self):
        self.pure_first()
        strict_context = deepcopy(self.context)
        strict_context["mode"] = "isolated_joint_action_experiment"
        strict_context.pop("policy")
        strict = execute_joint_actions(self.prepared, self.state, self.actions, strict_context,
                                        damage_resolver=lambda p,s,c:s[p["target"]]["hp"])
        self.assertEqual(strict["status"], "blocked")
        self.assertEqual(strict["state"], self.state)
        self.assertEqual(strict["events"], [])

    def test_native_components_honor_research_stop_without_changing_strict_default(self):
        from lab.rule_config import execution_program
        from lab.skill_execution import execute_skill
        rule = self.prepared._rules.configuration(7020360)
        rule["components"][1]["when"] = {"compare": "eq", "left": {"const": 1}, "right": {"const": 1}}
        program = execution_program(rule)
        for side in ("a", "b"):
            self.context["fragments"][side]["component_evaluation_policy"] = "after_payment_before_each_component_experiment"
        result = self.run_turn(lambda p,s,c:s[p["target"]]["hp"], program_overrides={7020360: program})
        self.assertEqual(result["status"], "awaiting_replacement", result["blockers"])
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["energy"], 8)
        self.assertTrue(any(e["op"] == "research.skill_stopped" for e in result["events"]))
        state = {"self": deepcopy(self.state["teams"]["a"]["members"][1]),
                 "opponent": deepcopy(self.state["teams"]["b"]["members"][1])}
        for actor in state.values():
            actor["types"] = self.prepared._rules.form(actor["form_id"])["types"]
        context = deepcopy(self.context["fragments"]["a"])
        context["resolved_energy_cost"] = 2
        strict = execute_skill(program, state, context, damage_resolver=lambda p,s,c:s[p["target"]]["hp"])
        self.assertEqual(strict["status"], "blocked")
        self.assertEqual(strict["state"], state)

    def test_game_file_override_keeps_distinct_snapshot_and_rejects_changed_hash(self):
        from lab.game_rule_candidates import digest
        program = deepcopy(self.f.programs["7020360"])
        # Constructed trusted-adapter protocol fixture, not extracted evidence.
        evidence = {"source_id": "constructed-source", "policy": {"name": "constructed-policy"}}
        program.update(snapshot_id="game-file:constructed-source", game_file_evidence=evidence,
                       source_hash=digest(evidence), research_skill_override_allowed=True,
                       whole_skill_verified=False)
        program["game_file_program_sha256"] = digest(program)
        for context in self.context["fragments"].values():
            context["game_file_policy"] = deepcopy(evidence["policy"])
        result = self.run_turn(program_overrides={7020360: program})
        self.assertEqual(result["status"], "applied", result["blockers"])
        damage = next(e for e in result["events"] if e["op"] == "damage")
        self.assertEqual(damage["snapshot_id"], "game-file:constructed-source")
        self.assertEqual(result["state"]["snapshot_id"], self.state["snapshot_id"])
        program["operations"][0]["params"]["power"] += 1
        rejected = self.run_turn(program_overrides={7020360: program})
        self.assertEqual(rejected["status"], "blocked")
        self.assertEqual(rejected["committed_actions"], [])
        self.assertIn("hash", rejected["blockers"][0])


if __name__ == "__main__":
    unittest.main()
