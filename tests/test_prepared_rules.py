"""Rule reuse equivalence/isolation; timings are measured outside unit tests."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from lab.action_runtime import execute_joint_actions
from lab.prepared_rules import PreparedRules
from lab.server import load_catalog
from lab.effect_runtime import HOOKS
from lab.turn_plan import plan_joint_actions


class PreparedRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]

    def setUp(self):
        self.prepared = PreparedRules(self.catalog)
        self.state = {"snapshot_id": self.catalog["snapshot_id"], "turn": 2, "teams": {}}
        for side in ("a", "b"):
            actor = {"member_id": side, "form_id": 3001, "hp": 100, "max_hp": 100,
                     "energy": 10, "max_energy": 20, "speed": 100, "entered_turn": 1,
                     "rooted": False, "charge": None, "skill_slots": [0, 7030220, 0, 0],
                     "statuses": {}, "stat_modifiers": {}}
            self.state["teams"][side] = {"active_slot": 0, "members": [actor],
                                          "marks": {"positive": None, "negative": None}}
        self.actions = {s: {"kind": "skill", "slot": 1, "effective_cost": 2,
                            "effective_priority": int(s == "a")} for s in ("a", "b")}
        program = self.prepared.skill_plan(7030220)["program"]
        fragment = {"mode": "isolated_skill_experiment", "snapshot_id": self.catalog["snapshot_id"],
                    "source_hash": program["source_hash"], "operation_order": "source_text_order_experiment",
                    "excluded_hooks": sorted(HOOKS), "unresolved_dependencies": [],
                    "energy_policy": "clamp_to_declared_max"}
        self.context = {"mode": "isolated_joint_action_experiment", "excluded_hooks": sorted(HOOKS),
                        "fragments": {s: deepcopy(fragment) for s in ("a", "b")}}

    def run_pair(self, rules=None):
        return execute_joint_actions(self.prepared if rules is None else rules,
                                     self.state, self.actions, self.context)

    def test_semantic_parity_with_saved_pre_optimization_execution(self):
        report = json.loads((Path(__file__).resolve().parents[1]/"docs/verification/rule-reuse-before-20261025.json").read_text(encoding="utf-8"))
        p = report["payload"]
        result = self.prepared.execute(p["state"], p["actions"], p["context"])
        def semantic(value):
            value = deepcopy(value)
            # This historical fixture predates compiler v3. Only these hashes
            # include the intentionally bumped compiler version. Same-version
            # fresh/prepared equality including ALL hashes is checked below.
            value.pop("plan_hash")
            for event in value["events"]:
                event.pop("program_hash")
            return value
        self.assertEqual(semantic(result), semantic(report["result"]))

    def test_fresh_and_prepared_paths_match_both_action_orders_and_all_hashes(self):
        for priority in (0, 2):
            self.actions["b"]["effective_priority"] = priority
            self.assertEqual(self.run_pair(), self.run_pair(self.catalog))
            self.assertEqual(self.prepared.plan(self.state, self.actions),
                             plan_joint_actions(self.catalog, self.state, self.actions))

    def test_invalid_action_is_equivalent_and_does_not_poison_next_execution(self):
        expected = self.run_pair()
        self.actions["b"]["slot"] = 0
        bad = self.run_pair()
        self.assertEqual(bad, self.run_pair(self.catalog))
        self.assertEqual(bad["status"], "blocked")
        self.actions["b"]["slot"] = 1
        self.assertEqual(self.run_pair(), expected)

    def test_mutating_returned_results_and_skill_plans_cannot_change_next_call(self):
        expected = self.run_pair()
        changed = self.run_pair()
        changed["state"]["teams"]["a"]["members"][0]["energy"] = 0
        changed["events"].clear()
        changed["assumptions"]["fragments"]["a"]["excluded_hooks"].clear()
        plan = self.prepared.skill_plan(7030220)
        plan["program"]["operations"][0]["params"]["amount"] = 999
        plan["skill"]["desc"]["zh"] = "changed"
        self.assertEqual(self.run_pair(), expected)

    def test_source_mutation_same_snapshot_id_is_pinned_and_new_object_rechecks_source(self):
        source = deepcopy(self.catalog)
        old = PreparedRules(source)
        expected = self.run_pair(old)
        source["moves"]["7030220"]["desc"]["zh"] = "自己回复9能量。"
        new = PreparedRules(source)
        self.assertEqual(old.snapshot_id, new.snapshot_id)
        self.assertNotEqual(old.catalog_content_hash, new.catalog_content_hash)
        self.assertEqual(self.run_pair(old), expected)
        rejected = self.run_pair(new)
        self.assertEqual(rejected["status"], "blocked")
        self.assertTrue(any("source fingerprint changed" in issue for issue in rejected["blockers"]))

    def test_another_snapshot_cannot_execute_old_state(self):
        source = deepcopy(self.catalog)
        source["snapshot_id"] += "-other"
        result = self.run_pair(PreparedRules(source))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["state"], self.state)
        self.assertEqual(result["events"], [])

    def test_components_and_programs_initialize_once_under_concurrent_calls(self):
        import lab.prepared_rules as module
        import lab.rule_config as compiler
        with patch.object(module, "BwikiRuleset", wraps=module.BwikiRuleset) as base, \
             patch.object(module, "ActionRules", wraps=module.ActionRules) as phases, \
             patch.object(module, "SwitchRules", wraps=module.SwitchRules) as switches, \
             patch.object(compiler, "load_config", wraps=compiler.load_config) as compile_call:
            prepared = PreparedRules(self.catalog)
            states = [deepcopy(self.state) for _ in range(8)]
            for i, state in enumerate(states):
                state["teams"]["a"]["members"][0]["energy"] = 4+i
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda s: prepared.execute(s, self.actions, self.context), states))
            self.assertEqual([r["state"]["teams"]["a"]["members"][0]["energy"] for r in results], list(range(12, 20)))
            self.assertTrue(all(r["status"] == "applied" for r in results))
            self.assertEqual((base.call_count, phases.call_count, switches.call_count, compile_call.call_count), (1, 1, 1, 1))
            results[0]["state"]["teams"]["b"]["members"][0]["energy"] = 0
            self.assertEqual(results[1]["state"]["teams"]["b"]["members"][0]["energy"], 18)
            self.assertEqual(states[0]["teams"]["a"]["members"][0]["energy"], 4)

    def test_invalid_context_still_precedes_phase_source_checks(self):
        source = deepcopy(self.catalog)
        source["provenance"]["Terms"]["content_sha256"] = "0"*64
        prepared = PreparedRules(source)
        bad_context = {"mode": "not_an_experiment"}
        a = execute_joint_actions(source, self.state, self.actions, bad_context)
        b = prepared.execute(self.state, self.actions, bad_context)
        self.assertEqual(a, b)
        self.assertIsNone(a["plan_hash"])
        self.assertIn("explicitly requested", a["blockers"][0])
        self.assertEqual(prepared.plan(self.state, self.actions)["status"], "blocked")

    def test_concurrent_damage_resolvers_and_results_are_never_cached_across_calls(self):
        state, context = deepcopy(self.state), deepcopy(self.context)
        source_hash = self.prepared.skill_plan(7020360)["program"]["source_hash"]
        for side in ("a", "b"):
            state["teams"][side]["members"][0]["skill_slots"][1] = 7020360
            context["fragments"][side].update(source_hash=source_hash,
                                             damage_policy="resolver_returns_actual_integer_hp_loss")
        def execute(damage):
            def resolver(params, relative, caller_context):
                relative["self"]["energy"] = 999
                caller_context["excluded_hooks"].clear()
                return damage
            return self.prepared.execute(state, self.actions, context, damage_resolver=resolver)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(execute, (1, 2, 3, 4)))
        for damage, result in enumerate(results, 1):
            self.assertEqual(result["status"], "applied", result["blockers"])
            self.assertEqual([result["state"]["teams"][s]["members"][0]["hp"] for s in ("a", "b")], [100-damage]*2)
            self.assertEqual([result["state"]["teams"][s]["members"][0]["energy"] for s in ("a", "b")], [9, 9])
            self.assertEqual([e["damage"] for e in result["events"] if e["op"] == "damage"], [damage, damage])
        self.assertEqual(state["teams"]["a"]["members"][0]["hp"], 100)
        self.assertEqual(context["fragments"]["a"]["excluded_hooks"], sorted(HOOKS))


if __name__ == "__main__":
    unittest.main()
