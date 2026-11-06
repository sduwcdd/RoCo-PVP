"""Research adapter checks; these do not validate damage against the game."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import unittest

from lab.effect_runtime import HOOKS, REVIEWED_TERMS_SHA256, execute_effects
from lab.numeric_candidates import arena_documented_damage60, showdown_documented_damage60
from lab.research_damage import make_research_damage_resolver


def catalog():
    return {"snapshot_id": "research-fixture", "types": ["火系", "武系", "水系", "地系", "恶系"],
            "chart_schema": "defender_type_combination_to_attacker_weak_resist; explicit double-type multiplier",
            "forms": [{"id": 1, "types": ["火系"], "relation_key": "火系"},
                      {"id": 2, "types": ["地系", "恶系"], "relation_key": "地系|恶系"}],
            "moves": {}, "traits": {}, "provenance": {"Types": {"revision_id": 1}},
            "chart": {"火系": {"weak": [], "resist": []},
                      "地系|恶系": {"weak": [{"type": "武系", "multiplier": 3}],
                                 "resist": [{"type": "火系", "multiplier": .5}]}}}


def policy(candidate="arena_documented_damage60_v1", same_type=2):
    return {"candidate_id": candidate, "same_type_multiplier": same_type,
            "stat_modifier_policy": "linear_signed_terms_experiment"}


def state():
    common = {"hp": 10000, "max_hp": 10000, "energy": 5, "max_energy": 12,
              "statuses": {}, "stat_modifiers": {}}
    return {"self": {**deepcopy(common), "form_id": 1, "types": ["火系"],
                     "stats": {"patk": 100, "matk": 300, "pdef": 200, "mdef": 400}},
            "opponent": {**deepcopy(common), "form_id": 2, "types": ["地系", "恶系"],
                         "stats": {"patk": 500, "matk": 600, "pdef": 50, "mdef": 200}}}


def params(**overrides):
    return {"target": "opponent", "kind": "physical", "type": "火系", "power": 100, **overrides}


class ResearchDamageTests(unittest.TestCase):
    def setUp(self):
        self.resolver = make_research_damage_resolver(catalog(), policy())
        self.context = {"snapshot_id": "research-fixture"}

    def test_physical_and_magical_use_attackers_attack_and_defenders_matching_defense(self):
        for kind, attack, defense in [("physical", 100, 50), ("magical", 300, 200)]:
            trace = self.resolver.explain(params(kind=kind), state(), self.context)
            expected = arena_documented_damage60(attack, defense, 100, 1)["nominal_damage"]
            self.assertEqual(trace["actual_hp_loss"], expected)
            self.assertEqual(trace["attack"]["effective_panel"], attack)
            self.assertEqual(trace["defense"]["effective_panel"], defense)
        self.assertNotEqual(self.resolver(params(), state(), self.context),
                            self.resolver(params(kind="magical"), state(), self.context))

    def test_combination_chart_and_explicit_same_type_bonus_are_applied_once(self):
        trace = self.resolver.explain(params(type="武系"), state(), self.context)
        self.assertEqual(trace["type_matchup"]["multiplier"], {"numerator": 3, "denominator": 1})
        self.assertEqual(trace["same_type_multiplier_applied"], 1)
        self.assertEqual(trace["actual_hp_loss"], arena_documented_damage60(100, 50, 100, 3)["nominal_damage"])
        trace = self.resolver.explain(params(), state(), self.context)
        self.assertEqual(trace["same_type_multiplier_applied"], 2)
        self.assertEqual(trace["prediction"]["inputs"]["multiplier"], 1)
        resolver = make_research_damage_resolver(catalog(), policy(same_type=1.2))
        self.assertEqual(resolver(params(), state(), self.context), arena_documented_damage60(100, 50, 100, .6)["nominal_damage"])

    def test_signed_modifier_terms_stack_linearly_not_multiplicatively(self):
        s = state()
        s["self"]["stat_modifiers"]["patk"] = [{"numerator": 50, "denominator": 100}] * 2
        s["opponent"]["stat_modifiers"]["pdef"] = [{"numerator": -25, "denominator": 100}]
        trace = self.resolver.explain(params(), s, self.context)
        self.assertEqual(trace["attack"]["effective_panel"], 200)
        self.assertEqual(trace["defense"]["effective_panel"], 37.5)
        self.assertEqual(trace["actual_hp_loss"], arena_documented_damage60(200, 37.5, 100, 1)["nominal_damage"])

    def test_both_named_documented_candidates_are_preserved(self):
        for candidate, formula in [("arena_documented_damage60_v1", arena_documented_damage60),
                                   ("showdown_documented_damage60_v1", showdown_documented_damage60)]:
            resolver = make_research_damage_resolver(catalog(), policy(candidate, 1.3))
            self.assertEqual(resolver(params(power=51), state(), self.context), formula(100, 50, 51, .65)["nominal_damage"])
            self.assertEqual(resolver.metadata["policy"]["candidate_id"], candidate)
            self.assertEqual(resolver.metadata["source"]["kind"], "community_documented_expression")
            for flag in ("calibrated", "real_game_verified", "training_eligible"):
                self.assertFalse(resolver.metadata[flag])

    def test_conditional_multiplier_is_final_once_and_overkill_clips_to_current_hp(self):
        p = params(damage_multiplier={"numerator": 3, "denominator": 2})
        trace = self.resolver.explain(p, state(), self.context)
        self.assertEqual(trace["final_unclipped_damage"], trace["nominal_damage"] * 3 // 2)
        s = state();s["opponent"]["hp"] = 7
        self.assertEqual(self.resolver(p, s, self.context), 7)
        s["opponent"]["hp"] = 0
        self.assertEqual(self.resolver(p, s, self.context), 0)
        self.assertEqual(self.resolver(params(damage_multiplier={"numerator": 0, "denominator": 1}), state(), self.context), 0)

    def test_zero_damage_is_not_forced_to_one(self):
        s = state();s["self"]["stats"]["patk"] = 1;s["opponent"]["stats"]["pdef"] = 10000
        self.assertEqual(self.resolver(params(power=1), s, self.context), 0)
        c = catalog();c["chart"]["地系|恶系"]["resist"][0]["multiplier"] = 0
        self.assertEqual(make_research_damage_resolver(c, policy())(params(), state(), self.context), 0)

    def test_each_multihit_callback_divides_total_power_once_and_never_multiplies_hit_count(self):
        for basis, power in [("source_power_total", 100 / 3), ("source_power_per_hit", 100)]:
            s = state();before = deepcopy(s)
            losses = []
            for index in range(3):
                p = params(hits=3, hit_count=3, hit_index=index, power_basis=basis)
                trace = self.resolver.explain(p, s, self.context)
                self.assertEqual(trace["effective_power_this_hit"], power)
                losses.append(trace["actual_hp_loss"]);s["opponent"]["hp"] -= losses[-1]
            expected = arena_documented_damage60(100, 50, power, 1)["nominal_damage"]
            self.assertEqual(losses, [expected] * 3)
            self.assertEqual(before["opponent"]["hp"] - s["opponent"]["hp"], expected * 3)
        for p in [params(hits=3), params(hit_count=0, hit_index=0, power_basis="source_power_total"),
                  params(hit_count=3, hit_index=3, power_basis="source_power_total"),
                  params(hit_count=3, hit_index=0, power_basis="unknown")]:
            with self.assertRaises(ValueError):
                self.resolver(p, state(), self.context)

    def test_real_fragment_runtime_applies_sequence_without_repeating_total_power(self):
        program = {"category": "skill", "status": "compiled", "snapshot_id": "research-fixture",
                   "source_hash": "synthetic-sequence-fixture", "blockers": [], "dependency_ids": [3005],
                   "term_source": {"content_sha256": REVIEWED_TERMS_SHA256},
                   "operations": [{"op": "damage.sequence", "params": params(hits=3)}]}
        context = {**self.context, "mode": "isolated_skill_experiment", "source_hash": program["source_hash"],
                   "operation_order": "source_text_order_experiment", "unresolved_dependencies": [],
                   "excluded_hooks": sorted(HOOKS), "damage_policy": "resolver_returns_actual_integer_hp_loss",
                   "multi_hit_policy": {"power_basis": "source_power_total", "timing": "sequential_experiment"}}
        original = state();result = execute_effects(program, original, context, damage_resolver=self.resolver)
        self.assertEqual(result["status"], "applied", result["blockers"])
        expected = arena_documented_damage60(100, 50, 100 / 3, 1)["nominal_damage"]
        self.assertEqual([e["damage"] for e in result["events"]], [expected] * 3)
        self.assertEqual(result["state"]["opponent"]["hp"], 10000 - expected * 3)
        self.assertEqual(original, state())

    def test_policy_has_no_implicit_candidate_or_same_type_value(self):
        invalid = [{}, {"candidate_id": "old_0.9_formula"}, {**policy(), "same_type_multiplier": None},
                   {**policy(), "same_type_multiplier": True}, {**policy(), "same_type_multiplier": float("nan")},
                   {**policy(), "same_type_multiplier": 0}, {**policy(), "stat_modifier_policy": "game_verified"}]
        for p in invalid:
            with self.subTest(policy=p), self.assertRaises(ValueError):
                make_research_damage_resolver(catalog(), p)

    def test_real_conditional_runtime_passes_the_final_multiplier_without_double_application(self):
        program = {"category": "skill", "status": "compiled", "snapshot_id": "research-fixture",
                   "source_hash": "synthetic-conditional-fixture", "blockers": [],
                   "operations": [{"op": "damage.conditional", "params": params(
                       condition={"target": "self", "attribute": "energy", "comparison": "eq",
                                  "value": 0, "source_timing": "after_use"},
                       modifier={"kind": "damage_multiply", "amount": 2})}]}
        context = {**self.context, "mode": "isolated_skill_experiment", "source_hash": program["source_hash"],
                   "operation_order": "source_text_order_experiment", "unresolved_dependencies": [],
                   "excluded_hooks": sorted(HOOKS), "damage_policy": "resolver_returns_actual_integer_hp_loss",
                   "resolved_energy_cost": 5, "energy_policy": "clamp_to_declared_max",
                   "conditional_policy": {"timing": "after_payment_before_damage_experiment"}}
        result = execute_effects(program, state(), context, damage_resolver=self.resolver)
        self.assertEqual(result["status"], "applied", result["blockers"])
        expected = arena_documented_damage60(100, 50, 100, 1)["nominal_damage"] * 2
        self.assertEqual(result["state"]["self"]["energy"], 0)
        self.assertEqual(result["events"][-1]["damage"], expected)
        self.assertEqual(result["state"]["opponent"]["hp"], 10000 - expected)

    def test_missing_nonfinite_mismatched_or_special_inputs_fail_without_guessing(self):
        changes = [lambda s: s["self"]["stats"].pop("matk"),
                   lambda s: s["self"]["stats"].update(patk=float("inf")),
                   lambda s: s["self"]["stats"].update(patk=True),
                   lambda s: s["opponent"]["stats"].update(pdef=0),
                   lambda s: s["opponent"].update(types=["水系"]),
                   lambda s: s["opponent"].update(form_id=999),
                   lambda s: s["self"]["stat_modifiers"].update(patk=[{"numerator": -1, "denominator": 1}]),
                   lambda s: s["opponent"]["stat_modifiers"].update(pdef=[{"numerator": -2, "denominator": 1}]),
                   lambda s: s["self"]["stat_modifiers"].update(patk=[{"numerator": 1, "denominator": 0}])]
        for change in changes:
            s = state();change(s);before = deepcopy(s)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.resolver(params(), s, self.context)
            self.assertEqual(s, before)
        for p in [params(target="random_enemy"), params(kind="special"), params(type="未知系"),
                  params(power=float("nan")), params(power=0), params(damage_multiplier={"numerator": -1, "denominator": 1})]:
            with self.subTest(params=p), self.assertRaises(ValueError):
                self.resolver(p, state(), self.context)
        with self.assertRaises(ValueError):
            self.resolver(params(), state(), {"snapshot_id": "other-snapshot"})

    def test_repeatability_parallel_calls_and_owned_source_state_policy_and_trace(self):
        c, p, s, operation = catalog(), policy(), state(), params()
        resolver = make_research_damage_resolver(c, p);before = deepcopy((s, operation, self.context))
        expected = resolver(operation, s, self.context)
        c["forms"][0]["types"] = ["水系"];p["same_type_multiplier"] = 999
        metadata = resolver.metadata;metadata["policy"]["candidate_id"] = "mutated"
        trace = resolver.explain(operation, s, self.context);trace["attack"]["base_panel"] = -1
        with ThreadPoolExecutor(max_workers=4) as executor:
            values = list(executor.map(lambda _: resolver(operation, s, self.context), range(12)))
        self.assertEqual(values, [expected] * 12)
        self.assertEqual((s, operation, self.context), before)
        self.assertEqual(resolver.metadata["policy"], policy())
        self.assertEqual(resolver.explain(operation, s, self.context)["attack"]["base_panel"], 100)


if __name__ == "__main__":
    unittest.main()


class PeriodicAndResistanceAdapterTests(unittest.TestCase):
    def test_explicit_periodic_trigger_and_resistance_override(self):
        resolver=make_research_damage_resolver(catalog(),policy())
        ctx={'snapshot_id':'research-fixture'}
        actors=state();actors['opponent']['hp']=3;actors['opponent']['statuses']['burn']=2
        trigger={'op':'status.trigger','target':'opponent','status':'burn','stacks':2,
            'rate':{'numerator':2,'denominator':100},'damage_type':'火系',
            'policy':'immediate_existing_status_damage_no_decay_experiment_v1'}
        result=resolver.explain(trigger,actors,ctx)
        self.assertEqual(result['actual_hp_loss'],3)
        self.assertFalse(result['decay_applied'])
        self.assertEqual(actors['opponent']['statuses']['burn'],2)
        normal=resolver.explain(params(),state(),ctx)
        ignored=resolver.explain(params(ignore_type_resistance=True),state(),ctx)
        self.assertEqual(normal['type_matchup']['multiplier'],{'numerator':1,'denominator':2})
        self.assertEqual(ignored['type_matchup']['multiplier'],{'numerator':1,'denominator':1})
        self.assertEqual(ignored['type_matchup']['original_multiplier'],normal['type_matchup']['multiplier'])
