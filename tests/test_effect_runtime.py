"""Primitive experiment checks, not real-game calibration evidence."""
from copy import deepcopy
import unittest

from lab.effect_runtime import HOOKS, execute_effects
from lab.server import load_catalog
from lab.skill_programs import compile_catalog, compile_skill


def actor(**overrides):
    result = {"hp": 100, "max_hp": 150, "energy": 5, "max_energy": 12,
              "types": ["普通系"], "statuses": {}, "stat_modifiers": {},
              "move_ids": [7020360, 0, 7030220, 0]}
    result.update(overrides)
    return result


class EffectRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.programs = compile_catalog(cls.catalog)["skills"]

    def state(self):
        return {"self": actor(), "opponent": actor(), "turn_context": {"note": "explicit experiment"}}

    def context(self, program):
        return {"mode": "isolated_skill_experiment", "snapshot_id": program["snapshot_id"],
                "source_hash": program["source_hash"], "operation_order": "source_text_order_experiment",
                "unresolved_dependencies": [], "excluded_hooks": sorted(HOOKS),
                "energy_policy": "clamp_to_declared_max", "stat_policy": "record_signed_percentage_terms"}

    def program(self, name):
        return next(p for p in self.programs.values() if p["name"] == name)

    def test_mirror_reduces_energy_without_transferring_and_retains_both_effects(self):
        p = self.program("魔镜")
        for energy in (0, 1, 2, 3, 4, 12):
            with self.subTest(energy=energy):
                s, c = self.state(), self.context(p)
                s["opponent"]["energy"] = energy
                c.update(resolved_energy_cost=2, energy_reduction_policy="clamp_to_zero_experiment")
                before = deepcopy((s, c, p))
                r = execute_effects(p, s, c)
                self.assertEqual(r["status"], "applied", r["blockers"])
                self.assertEqual(r["state"]["self"]["energy"], 3)
                self.assertEqual(r["state"]["opponent"]["energy"], max(0, energy - 3))
                self.assertEqual(r["state"]["opponent"]["stat_modifiers"]["mdef"],
                                 [{"numerator": -50, "denominator": 100}])
                self.assertEqual([e["op"] for e in r["events"]], ["energy.pay", "stat.modify", "energy.reduce"])
                event = r["events"][-1]
                self.assertEqual((event["requested_amount"], event["actual_amount"]), (3, min(energy, 3)))
                self.assertEqual(event["policy"], "clamp_to_zero_experiment")
                self.assertEqual((s, c, p), before)
                self.assertFalse(r["calibrated"])
                self.assertFalse(r["training_eligible"])

    def test_energy_reduction_requires_separate_explicit_floor_policy(self):
        p, s = self.program("魔镜"), self.state()
        for policy in (None, "clamp_to_zero", "allow_negative", True):
            c = self.context(p)
            c.update(resolved_energy_cost=2, energy_reduction_policy=policy)
            r = execute_effects(p, s, c)
            self.assertEqual(r["status"], "blocked")
            self.assertEqual(r["state"], s)
            self.assertEqual(r["events"], [])

    def test_energy_reduction_invalid_amount_rejects_entire_skill(self):
        for amount in (0, -1, True, 1.5, "3", None):
            p, s = deepcopy(self.program("魔镜")), self.state()
            p["operations"][1]["params"]["amount"] = amount
            c = self.context(p)
            c.update(resolved_energy_cost=2, energy_reduction_policy="clamp_to_zero_experiment")
            r = execute_effects(p, s, c)
            self.assertEqual(r["status"], "blocked")
            self.assertEqual(r["state"], s)
            self.assertEqual(r["events"], [])

    def test_later_resolver_failure_rolls_back_reduction_stat_and_payment(self):
        p, s = deepcopy(self.program("魔镜")), self.state()
        # Synthetic compound checks interpreter atomicity, not an actual skill.
        p["operations"].append({"op": "damage", "params": {
            "target": "opponent", "kind": "magical", "power": 40, "type": "幽系"}})
        c = self.context(p)
        c.update(resolved_energy_cost=2, energy_reduction_policy="clamp_to_zero_experiment",
                 damage_policy="resolver_returns_actual_integer_hp_loss")
        seen = []
        def fail(params, state, context):
            seen.append(state["opponent"]["energy"])
            raise ValueError("experimental resolver failed")
        r = execute_effects(p, s, c, damage_resolver=fail)
        self.assertEqual(seen, [2])
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(r["state"], s)
        self.assertEqual(r["events"], [])

    def test_energy_condition_reads_reduced_energy_in_synthetic_sequence(self):
        for energy, matched in ((3, True), (4, False)):
            p, s = deepcopy(self.program("背袭")), self.state()
            p["operations"].insert(0, {"op": "energy.reduce", "params": {"target": "opponent", "amount": 3}})
            s["opponent"]["energy"] = energy
            c = self.conditional_context(p)
            c["energy_reduction_policy"] = "clamp_to_zero_experiment"
            seen = []
            r = execute_effects(p, s, c, damage_resolver=lambda params, *_: seen.append(
                (params["condition_observed"], params["condition_matched"])) or 7)
            self.assertEqual(r["status"], "applied", r["blockers"])
            self.assertEqual(seen, [(energy - 3, matched)])

    def hp_context(self, program, basis="declared_max_hp", rounding="exact"):
        context = self.context(program)
        context["hp_policy"] = {"percentage_basis": basis, "rounding": rounding,
                                "cap": "clamp_to_declared_max"}
        return context

    def sequence_context(self, program, power_basis="source_power_per_hit"):
        context = self.context(program)
        context.update(resolved_energy_cost=2, damage_policy="resolver_returns_actual_integer_hp_loss",
                       multi_hit_policy={"power_basis": power_basis, "timing": "sequential_experiment"})
        return context

    def conditional_context(self, program, cost=0):
        context = self.context(program)
        context.update(resolved_energy_cost=cost, damage_policy="resolver_returns_actual_integer_hp_loss",
                       conditional_policy={"timing": "after_payment_before_damage_experiment"})
        return context

    def test_manual_swift_attack_executes_once_without_inventing_an_entry(self):
        program, state = self.program("翼击"), self.state()
        context = self.context(program)
        context.update(resolved_energy_cost=3, damage_policy="resolver_returns_actual_integer_hp_loss")
        calls = []
        result = execute_effects(program, state, context,
                                 damage_resolver=lambda *args: calls.append(args) or 7)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["state"]["self"]["energy"], 2)
        self.assertEqual(result["state"]["opponent"]["hp"], 93)
        self.assertEqual(sum(e["op"] == "damage" for e in result["events"]), 1)
        self.assertTrue(all(e["op"] != "switch.voluntary" for e in result["events"]))
        self.assertEqual(state, self.state())

    def test_swift_source_dependency_cannot_be_removed_or_forged(self):
        original = self.program("翼击")
        changes = [lambda p: p.update(intrinsic_swift=False),
                   lambda p: p.update(dependency_ids=[]),
                   lambda p: p.update(entry_trigger={"kind": "every_turn", "term_id": 1005}),
                   lambda p: p.pop("swift_term"),
                   lambda p: p["swift_term"].update(definition="unknown"),
                   lambda p: p["term_source"].update(content_sha256="changed")]
        for change in changes:
            program, state = deepcopy(original), self.state()
            change(program)
            context = self.context(program)
            context.update(resolved_energy_cost=3, damage_policy="resolver_returns_actual_integer_hp_loss")
            calls = []
            result = execute_effects(program, state, context,
                                     damage_resolver=lambda *args: calls.append(args) or 7)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["state"], state)
            self.assertEqual(result["events"], [])
            self.assertEqual(calls, [])

    def test_opponent_energy_conditions_keep_exact_boundaries_and_damage_not_power_multiplier(self):
        for name, values, source_power, factor in (("穿膛", [(1, True), (2, True), (3, False)], 65, 5),
                                                   ("背袭", [(0, True), (1, False)], 40, 20)):
            for energy, matched in values:
                with self.subTest(name=name, energy=energy):
                    p, s, observed = self.program(name), self.state(), []
                    s["opponent"]["energy"] = energy
                    def resolver(params, current, context):
                        observed.append(deepcopy(params))
                        return 7  # Already-final actual loss; never multiply it again.
                    r = execute_effects(p, s, self.conditional_context(p), damage_resolver=resolver)
                    self.assertEqual(r["status"], "applied", r["blockers"])
                    resolved = observed[0]
                    self.assertEqual((resolved["base_power"], resolved["power"]), (source_power, source_power))
                    self.assertEqual(resolved["condition_observed"], energy)
                    self.assertEqual(resolved["condition_matched"], matched)
                    self.assertEqual(resolved["damage_multiplier"], {"numerator": factor if matched else 1, "denominator": 1})
                    self.assertEqual(r["state"]["opponent"]["hp"], 93)
                    event = r["events"][1]
                    self.assertEqual(event["source_op"], "damage.conditional")
                    self.assertEqual(event["condition"], p["operations"][0]["params"]["condition"])
                    self.assertEqual(event["resolved_params"], resolved)

    def test_after_use_source_keeps_timing_uncertain_but_explicit_experiment_reads_paid_energy(self):
        p = self.program("触底强击")
        for cost, power, remaining in ((5, 215, 0), (4, 95, 1)):
            s, seen = self.state(), []
            def resolver(params, current, context):
                seen.append((params["base_power"], params["power"], params["condition_observed"], current["self"]["energy"]))
                return 7
            r = execute_effects(p, s, self.conditional_context(p, cost), damage_resolver=resolver)
            self.assertEqual(r["status"], "applied", r["blockers"])
            self.assertEqual(seen, [(95, power, remaining, remaining)])
            self.assertEqual(r["events"][1]["damage_multiplier"], {"numerator": 1, "denominator": 1})
            self.assertEqual(r["events"][1]["condition"]["source_timing"], "after_use")
            self.assertFalse(r["calibrated"])
            self.assertFalse(r["training_eligible"])
            self.assertEqual(s["self"]["energy"], 5)

    def test_conditional_missing_or_unknown_timing_and_missing_cost_reject_before_callback(self):
        p, s = self.program("触底强击"), self.state()
        for change in (lambda c: c.pop("resolved_energy_cost"), lambda c: c.pop("conditional_policy"),
                       lambda c: c.update(conditional_policy={"timing": "after_use"}),
                       lambda c: c["conditional_policy"].update(verified=True)):
            c, called = self.conditional_context(p, 5), []
            change(c)
            r = execute_effects(p, s, c, damage_resolver=lambda *args: called.append(True))
            self.assertEqual(r["status"], "blocked")
            self.assertEqual(called, [])
            self.assertEqual(r["state"], s)
            self.assertEqual(r["events"], [])

    def test_condition_reads_prior_effect_state_in_synthetic_compound_without_caching(self):
        p, s = deepcopy(self.program("触底强击")), self.state()
        # Synthetic compound probes the interpreter boundary, not a BWIKI skill.
        p["operations"].insert(0, {"op": "energy.restore", "params": {"target": "self", "amount": 2}})
        seen = []
        def resolver(params, current, context):
            seen.append((params["condition_observed"], params["condition_matched"], params["power"]))
            return 7
        r = execute_effects(p, s, self.conditional_context(p, 5), damage_resolver=resolver)
        self.assertEqual(r["status"], "applied", r["blockers"])
        self.assertEqual(seen, [(2, False, 95)])
        self.assertEqual([e["op"] for e in r["events"]], ["energy.pay", "energy.restore", "damage"])

    def test_unsupported_conditional_schema_is_not_evaluated_or_silently_repaired(self):
        mutations = [lambda p: p["condition"].update(attribute="hp"),
                     lambda p: p["condition"].update(comparison="lt"),
                     lambda p: p["condition"].update(target="enemy"),
                     lambda p: p["condition"].update(source_timing="pre_turn"),
                     lambda p: p["condition"].update(value=True),
                     lambda p: p["condition"].update(expression="1+1"),
                     lambda p: p["modifier"].update(kind="power_multiply"),
                     lambda p: p["modifier"].update(amount=0),
                     lambda p: p["modifier"].update(amount=True)]
        for mutate in mutations:
            p, s, called = deepcopy(self.program("穿膛")), self.state(), []
            mutate(p["operations"][0]["params"])
            r = execute_effects(p, s, self.conditional_context(p, 2), damage_resolver=lambda *args: called.append(True))
            self.assertEqual(r["status"], "blocked")
            self.assertEqual(called, [])
            self.assertEqual(r["state"], s)
            self.assertEqual(r["events"], [])

    def test_conditional_resolver_failures_undo_payment_and_leave_no_partial_events(self):
        p, s = self.program("触底强击"), self.state()
        def failing(*args):
            raise RuntimeError("conditional resolver failed")
        for resolver in (lambda *args: True, lambda *args: -1, lambda *args: .5,
                         lambda *args: 101, failing):
            r = execute_effects(p, s, self.conditional_context(p, 5), damage_resolver=resolver)
            self.assertEqual(r["status"], "blocked")
            self.assertEqual(r["state"], s)
            self.assertEqual(r["events"], [])

    def test_conditional_callback_cannot_mutate_recorded_predicate_or_multiplier(self):
        p, s = self.program("穿膛"), self.state()
        s["opponent"]["energy"] = 2
        c = self.conditional_context(p, 2)
        original = deepcopy((p, s, c))
        def resolver(params, current, context):
            params["condition"]["value"] = 999
            params["damage_multiplier"]["numerator"] = 999
            current["opponent"]["energy"] = 999
            context["conditional_policy"]["timing"] = "tampered"
            return 7
        r = execute_effects(p, s, c, damage_resolver=resolver)
        self.assertEqual(r["status"], "applied", r["blockers"])
        event = r["events"][1]
        self.assertEqual(event["condition"]["value"], 2)
        self.assertEqual(event["condition_observed"], 2)
        self.assertEqual(event["damage_multiplier"]["numerator"], 5)
        self.assertEqual(event["conditional_policy"], {"timing": "after_payment_before_damage_experiment"})
        self.assertEqual((p, s, c), original)

    def test_real_fixed_sequences_keep_each_hit_order_and_pay_energy_once(self):
        for name, count, power, expected_hp in (("音波弹", 1, 60, 99), ("刺藤", 2, 45, 97),
                                                ("旋转突击", 3, 35, 94), ("乱打", 5, 25, 85)):
            with self.subTest(name=name):
                p, s, observed = self.program(name), self.state(), []
                c = self.sequence_context(p)
                def resolver(params, current, context):
                    observed.append((params["hit_index"], params["hit_count"], params["power"], current["opponent"]["hp"], current["self"]["energy"]))
                    return params["hit_index"] + 1
                r = execute_effects(p, s, c, damage_resolver=resolver)
                self.assertEqual(r["status"], "applied", r["blockers"])
                self.assertEqual(observed, [(i, count, power, hp, 3) for i, hp in enumerate([100, 99, 97, 94, 90][:count])])
                self.assertEqual([e["op"] for e in r["events"]], ["energy.pay"] + ["damage"]*count)
                self.assertEqual(r["state"]["opponent"]["hp"], expected_hp)
                self.assertEqual(r["state"]["self"]["energy"], 3)
                for i, event in enumerate(r["events"][1:]):
                    self.assertEqual((event["hit_index"], event["hit_count"], event["sequence_operation_index"]), (i, count, 0))
                    self.assertEqual(event["source_op"], "damage.sequence")
                    self.assertEqual(event["before"]-event["after"], i+1)
                    self.assertEqual(event["program_hash"], r["program_hash"])
                self.assertEqual(s["opponent"]["hp"], 100)
                self.assertEqual(s["self"]["energy"], 5)
                self.assertFalse(r["training_eligible"])
                self.assertFalse(r["full_turn_executed"])

    def test_sequences_require_explicit_power_basis_and_sequential_timing_before_any_hit(self):
        p, s, calls = self.program("旋转突击"), self.state(), []
        for policy in (None, {}, {"power_basis": "source_power_per_hit"},
                       {"power_basis": "source_power_per_hit", "timing": "real_game"},
                       {"power_basis": "guessed", "timing": "sequential_experiment"},
                       {"power_basis": "source_power_per_hit", "timing": "sequential_experiment", "hits": 99}):
            c = self.sequence_context(p)
            c["multi_hit_policy"] = policy
            def resolver(*args):
                calls.append(True)
                return 1
            r = execute_effects(p, s, c, damage_resolver=resolver)
            self.assertEqual(r["status"], "blocked")
            self.assertEqual(r["state"], s)
            self.assertEqual(r["events"], [])
        self.assertEqual(calls, [])

    def test_both_power_policies_pass_unchanged_source_power_and_isolated_hit_arguments(self):
        p, s = self.program("旋转突击"), self.state()
        before = deepcopy((p, s))
        for basis in ("source_power_per_hit", "source_power_total"):
            c, seen = self.sequence_context(p, basis), []
            original_context = deepcopy(c)
            def resolver(params, current, context):
                seen.append((params["power"], params["hit_index"], params["power_basis"], current["opponent"]["hp"]))
                params["power"] = 999
                params["hits"] = 999
                current["opponent"]["hp"] = 0
                context["multi_hit_policy"].clear()
                return 2
            r = execute_effects(p, s, c, damage_resolver=resolver)
            self.assertEqual(r["status"], "applied", r["blockers"])
            self.assertEqual(seen, [(35, 0, basis, 100), (35, 1, basis, 98), (35, 2, basis, 96)])
            self.assertEqual([e["params"]["power"] for e in r["events"][1:]], [35, 35, 35])
            self.assertEqual([e["power_basis"] for e in r["events"][1:]], [basis]*3)
            self.assertEqual(c, original_context)
        self.assertEqual((p, s), before)

    def test_second_hit_failure_rolls_back_first_hit_and_payment(self):
        p, s = self.program("旋转突击"), self.state()
        for bad in (True, 1.5, -1, 1000, RuntimeError("hit callback failed")):
            calls = []
            def resolver(params, *args):
                calls.append(params["hit_index"])
                if params["hit_index"] == 0:
                    return 7
                if isinstance(bad, Exception):
                    raise bad
                return bad
            r = execute_effects(p, s, self.sequence_context(p), damage_resolver=resolver)
            self.assertEqual(r["status"], "blocked")
            self.assertEqual(calls, [0, 1])
            self.assertEqual(r["state"], s)
            self.assertEqual(r["events"], [])

    def test_early_exhaustion_stops_before_next_hit_and_rejects_the_whole_sequence(self):
        p, s, calls = self.program("旋转突击"), self.state(), []
        def resolver(params, current, context):
            calls.append(params["hit_index"])
            return current["opponent"]["hp"]
        r = execute_effects(p, s, self.sequence_context(p), damage_resolver=resolver)
        self.assertEqual(r["status"], "blocked")
        self.assertIn("Exhaustion", r["blockers"][0])
        self.assertEqual(calls, [0])
        self.assertEqual(r["state"], s)
        self.assertEqual(r["events"], [])

    def test_last_hit_exhaustion_is_only_an_isolated_result_and_followup_still_blocks(self):
        p, s = self.program("刺藤"), self.state()
        s["opponent"]["hp"] = 10
        def resolver(params, *args):
            return (4, 6)[params["hit_index"]]
        r = execute_effects(p, s, self.sequence_context(p), damage_resolver=resolver)
        self.assertEqual(r["status"], "applied", r["blockers"])
        self.assertEqual(r["state"]["opponent"]["hp"], 0)
        self.assertEqual([e["after"] for e in r["events"] if e["op"] == "damage"], [6, 0])
        self.assertFalse(r["full_turn_executed"])
        modified = deepcopy(p)
        modified["operations"].append({"op": "energy.restore", "params": {"target": "self", "amount": 1}})
        r = execute_effects(modified, s, self.sequence_context(modified), damage_resolver=resolver)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(r["state"], s)
        self.assertEqual(r["events"], [])

    def test_sequence_source_and_hit_count_validation_precedes_payment(self):
        source, s = self.program("旋转突击"), self.state()
        variants = []
        for count in (True, 0, -1, 2.5):
            p = deepcopy(source)
            p["operations"][0]["params"]["hits"] = count
            variants.append(p)
        p = deepcopy(source)
        p["term_source"]["content_sha256"] = "0"*64
        variants.append(p)
        p = deepcopy(source)
        p["dependency_ids"] = []
        variants.append(p)
        for p in variants:
            calls = []
            def resolver(*args):
                calls.append(True)
                return 1
            r = execute_effects(p, s, self.sequence_context(p), damage_resolver=resolver)
            self.assertEqual(r["status"], "blocked")
            self.assertEqual(r["state"], s)
            self.assertEqual(r["events"], [])
            self.assertEqual(calls, [])

    def test_healing_requires_explicit_basis_rounding_and_cap(self):
        p, s = self.program("休息回复"), self.state()
        for policy in (None, {}, {"percentage_basis": "declared_max_hp"},
                       {"percentage_basis": "declared_max_hp", "rounding": "floor"}):
            c = self.context(p)
            c.update(hp_policy=policy, resolved_energy_cost=2)
            r = execute_effects(p, s, c)
            self.assertEqual(r["status"], "blocked")
            self.assertEqual(r["state"], s)
            self.assertEqual(r["events"], [])

    def test_source_percent_heal_respects_two_explicit_experiment_bases(self):
        p, s = self.program("休息回复"), self.state()
        for basis, expected in (("declared_max_hp", 145), ("current_hp", 130)):
            r = execute_effects(p, s, self.hp_context(p, basis))
            self.assertEqual(r["status"], "applied", r["blockers"])
            self.assertEqual(r["state"]["self"]["hp"], expected)
            self.assertFalse(r["calibrated"])
            self.assertFalse(r["training_eligible"])
        self.assertEqual(s["self"]["hp"], 100)

    def test_healing_overflow_keeps_requested_amount_and_actual_hp_gain(self):
        p, s = self.program("休息回复"), self.state()
        s["self"]["hp"] = 145
        r = execute_effects(p, s, self.hp_context(p))
        self.assertEqual(r["state"]["self"]["hp"], 150)
        e = r["events"][0]
        self.assertEqual((e["requested"], e["restored"], e["overflow"]), (45, 5, 40))
        self.assertEqual(e["requested_unrounded"], {"numerator": 45, "denominator": 1})
        r["events"][0]["policy"]["rounding"] = "tampered"
        self.assertEqual(r["assumptions"]["hp_policy"]["rounding"], "exact")

    def test_fractional_healing_has_no_implicit_rounding_and_retains_exact_fraction(self):
        p, s = self.program("休息回复"), self.state()
        s["self"]["max_hp"] = 155  # 30% is exactly 46.5.
        for rule, expected in (("floor", 146), ("ceil", 147), ("half_up", 147)):
            r = execute_effects(p, s, self.hp_context(p, rounding=rule))
            self.assertEqual(r["state"]["self"]["hp"], expected)
            self.assertEqual(r["events"][0]["requested_unrounded"], {"numerator": 93, "denominator": 2})
        c = self.hp_context(p)
        c["resolved_energy_cost"] = 2
        r = execute_effects(p, s, c)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(r["state"], s)
        self.assertEqual(r["events"], [])

    def test_attack_then_poison_applies_in_order_without_dropping_status_dependency(self):
        p, s = self.program("毒针"), self.state()
        c = self.context(p)
        c.update(damage_policy="resolver_returns_actual_integer_hp_loss",
                 status_policies={"poison": {"stacking": "add_to_declared_count", "cap": None,
                                              "immunity_type": "毒系"}})
        r = execute_effects(p, s, c, damage_resolver=lambda *args: 7)
        self.assertEqual(r["status"], "applied", r["blockers"])
        self.assertEqual([e["op"] for e in r["events"]], ["damage", "status.add"])
        self.assertEqual(r["state"]["opponent"]["hp"], 93)
        self.assertEqual(r["state"]["opponent"]["statuses"]["poison"], 1)
        s["opponent"]["types"] = ["毒系"]
        r = execute_effects(p, s, c, damage_resolver=lambda *args: 7)
        self.assertEqual(r["state"]["opponent"]["hp"], 93)
        self.assertEqual(r["state"]["opponent"]["statuses"]["poison"], 0)

    def test_damage_then_heal_uses_current_state_and_rolls_back_on_fractional_failure(self):
        p, s = self.program("丰收"), self.state()
        c = self.hp_context(p)
        c["damage_policy"] = "resolver_returns_actual_integer_hp_loss"
        r = execute_effects(p, s, c, damage_resolver=lambda *args: 7)
        self.assertEqual(r["status"], "applied", r["blockers"])
        self.assertEqual([e["op"] for e in r["events"]], ["damage", "hp.restore"])
        self.assertEqual((r["state"]["self"]["hp"], r["state"]["opponent"]["hp"]), (130, 93))
        s["self"]["max_hp"] = 151
        r = execute_effects(p, s, c, damage_resolver=lambda *args: 7)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(r["state"], s)
        self.assertEqual(r["events"], [])

    def test_fatal_damage_never_runs_followup_status_heal_or_energy_refund(self):
        for name in ("毒针", "丰收", "抓挠"):
            p, s = self.program(name), self.state()
            c = self.hp_context(p)
            c.update(damage_policy="resolver_returns_actual_integer_hp_loss", resolved_energy_cost=2,
                     status_policies={"poison": {"stacking": "add_to_declared_count", "cap": None,
                                                  "immunity_type": "毒系"}})
            r = execute_effects(p, s, c, damage_resolver=lambda *args: 100)
            self.assertEqual(r["status"], "blocked", name)
            self.assertTrue(any("Exhaustion" in issue for issue in r["blockers"]), r["blockers"])
            self.assertEqual(r["state"], s)
            self.assertEqual(r["events"], [])

    def test_real_bwiki_energy_primitive_uses_explicit_cost_and_cap(self):
        program, state = self.program("徒长"), self.state()
        context = self.context(program)
        context["resolved_energy_cost"] = 2
        before = deepcopy(state)
        result = execute_effects(program, state, context)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["state"]["self"]["energy"], 12)
        self.assertEqual([e["op"] for e in result["events"]], ["energy.pay", "energy.restore"])
        self.assertEqual(state, before)
        self.assertFalse(result["full_turn_executed"])
        self.assertFalse(result["training_eligible"])
        self.assertTrue(result["implementation_unvalidated"])
        self.assertTrue(all(e["program_hash"] == result["program_hash"] for e in result["events"]))

    def test_base_skill_cost_is_not_silently_charged_as_final_cost(self):
        program, state = self.program("徒长"), self.state()
        state["self"]["max_energy"] = 50
        r = execute_effects(program, state, self.context(program))
        self.assertEqual(r["state"]["self"]["energy"], 15)
        self.assertFalse(r["energy_cost_applied"])
        self.assertEqual([e["op"] for e in r["events"]], ["energy.restore"])

    def test_missing_cap_policy_never_assumes_default(self):
        p, s = self.program("徒长"), self.state()
        c = self.context(p)
        del c["energy_policy"]
        r = execute_effects(p, s, c)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(r["state"], s)

    def test_stat_terms_retained_without_guessing_effective_panel(self):
        p, s = self.program("魔法增效"), self.state()
        r = execute_effects(p, s, self.context(p))
        self.assertEqual(r["status"], "applied")
        self.assertEqual(r["state"]["self"]["stat_modifiers"]["matk"], [{"numerator": 70, "denominator": 100}])
        self.assertFalse(r["events"][0]["effective_panel_recomputed"])

    def test_damage_without_resolver_rejects_whole_skill_including_refund_and_payment(self):
        p, s = self.program("抓挠"), self.state()
        c = self.context(p)
        c["resolved_energy_cost"] = 2
        r = execute_effects(p, s, c)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(r["state"], s)
        self.assertEqual(r["events"], [])

    def test_explicit_damage_experiment_keeps_resolver_isolated(self):
        p, s = self.program("抓挠"), self.state()
        c = self.context(p)
        c["damage_policy"] = "resolver_returns_actual_integer_hp_loss"
        before = deepcopy(s)
        def resolver(params, copied_state, copied_context):
            copied_state["self"]["move_ids"][0] = 999
            copied_context["unresolved_dependencies"].append("tampered")
            params["power"] = 999
            return 7
        r = execute_effects(p, s, c, damage_resolver=resolver)
        self.assertEqual(r["status"], "applied")
        self.assertEqual(r["state"]["opponent"]["hp"], 93)
        self.assertEqual(r["state"]["self"]["energy"], 6)
        self.assertEqual(r["state"]["self"]["move_ids"], [7020360, 0, 7030220, 0])
        self.assertEqual(s, before)
        self.assertEqual(c["unresolved_dependencies"], [])
        self.assertEqual(p["operations"][0]["params"]["power"], 35)
        self.assertFalse(r["training_eligible"])

    def test_bad_or_throwing_resolver_rolls_back_payment_and_all_effects(self):
        p, s = self.program("抓挠"), self.state()
        c = self.context(p)
        c.update(resolved_energy_cost=2, damage_policy="resolver_returns_actual_integer_hp_loss")
        def broken(*args):
            raise RuntimeError("explicit resolver failed")
        for resolver in (lambda *a: 1.2, lambda *a: True, lambda *a: -1, lambda *a: 1000, broken):
            with self.subTest(resolver=resolver):
                r = execute_effects(p, s, c, damage_resolver=resolver)
                self.assertEqual(r["status"], "blocked")
                self.assertEqual(r["state"], s)
                self.assertEqual(r["events"], [])

    def test_status_addition_requires_explicit_stack_policy_and_obeys_term_immunity(self):
        p = next(p for p in self.programs.values() if p["status"] == "compiled" and any(o["op"] == "status.add" and o["params"]["status"] == "burn" for o in p["operations"]))
        s, c = self.state(), self.context(p)
        self.assertEqual(execute_effects(p, s, c)["status"], "blocked")
        c["status_policies"] = {"burn": {"stacking": "add_to_declared_count", "cap": None, "immunity_type": "火系"}}
        r = execute_effects(p, s, c)
        self.assertEqual(r["status"], "applied")
        self.assertEqual(r["state"]["opponent"]["statuses"]["burn"], p["operations"][0]["params"]["stacks"])
        self.assertFalse(r["events"][0]["end_of_turn_resolved"])
        s["opponent"]["types"] = ["火系", "翼系"]
        immune = execute_effects(p, s, c)
        self.assertEqual(immune["state"]["opponent"]["statuses"]["burn"], 0)
        self.assertTrue(immune["events"][0]["immune"])

    def test_unknown_hooks_and_snapshot_drift_block(self):
        p, s = self.program("徒长"), self.state()
        for key, value in (("unresolved_dependencies", ["trait:200076"]), ("excluded_hooks", []), ("snapshot_id", "old"), ("source_hash", "changed"), ("operation_order", "verified_battle_order")):
            c = self.context(p)
            c[key] = value
            with self.subTest(key=key):
                r = execute_effects(p, s, c)
                self.assertEqual(r["status"], "blocked")
                self.assertEqual(r["state"], s)

    def test_empty_unknown_duplicate_or_excessive_types_cannot_bypass_immunity(self):
        p = self.program("徒长")
        for types in ([], ["不存在系"], ["火系", "火系"], ["火系", "水系", "草系"], [True]):
            s = self.state()
            s["opponent"]["types"] = types
            with self.subTest(types=types):
                r = execute_effects(p, s, self.context(p))
                self.assertEqual(r["status"], "blocked")
                self.assertEqual(r["events"], [])

    def test_changed_terms_revision_cannot_reuse_hardcoded_immunity(self):
        p = deepcopy(next(p for p in self.programs.values() if p["status"] == "compiled" and any(o["op"] == "status.add" and o["params"]["status"] == "burn" for o in p["operations"])))
        s, c = self.state(), self.context(p)
        c["status_policies"] = {"burn": {"stacking": "add_to_declared_count", "cap": None, "immunity_type": "火系"}}
        p["term_source"]["content_sha256"] = "0" * 64
        r = execute_effects(p, s, c)
        self.assertEqual(r["status"], "blocked")
        self.assertIn("changed terms", r["blockers"][0])
        self.assertEqual(r["state"], s)

    def test_freeze_threshold_and_leech_source_dependencies_block_before_payment(self):
        for status, immune_type in (("freeze", "冰系"), ("leech", "草系")):
            p = next(p for p in self.programs.values() if p["status"] == "compiled" and len(p["operations"]) == 1 and any(o["op"] == "status.add" and o["params"]["status"] == status for o in p["operations"]))
            s, c = self.state(), self.context(p)
            c["resolved_energy_cost"] = 3
            c["status_policies"] = {status: {"stacking": "add_to_declared_count", "cap": None, "immunity_type": immune_type}}
            with self.subTest(status=status):
                r = execute_effects(p, s, c)
                self.assertEqual(r["status"], "blocked")
                self.assertEqual(r["state"], s)
                self.assertEqual(r["events"], [])
                self.assertTrue(status in r["blockers"][0])

    def test_compound_attack_freeze_is_rejected_before_any_damage_or_payment(self):
        p = next(p for p in self.programs.values() if p["status"] == "compiled"
                 and len(p["operations"]) > 1 and any(o["op"] == "status.add" and o["params"]["status"] == "freeze" for o in p["operations"]))
        s, c, calls = self.state(), self.context(p), []
        c.update(resolved_energy_cost=2, damage_policy="resolver_returns_actual_integer_hp_loss")
        def resolver(*args):
            calls.append(True)
            return 7
        r = execute_effects(p, s, c, damage_resolver=resolver)
        self.assertEqual(r["status"], "blocked")
        self.assertIn("freeze", r["blockers"][0])
        self.assertEqual(calls, [])
        self.assertEqual(r["state"], s)
        self.assertEqual(r["events"], [])

    def test_unsupported_appended_clause_has_no_partial_application(self):
        skill = deepcopy(self.catalog["moves"]["7030220"])
        skill["desc"]["zh"] += "随后随机复制敌方技能。"
        p = compile_skill(skill)
        p["snapshot_id"] = self.catalog["snapshot_id"]
        s, c = self.state(), self.context(p)
        c["resolved_energy_cost"] = 2
        r = execute_effects(p, s, c)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(r["state"], s)

    def test_supported_first_operation_never_partially_commits_before_unknown_second(self):
        p, s = deepcopy(self.program("徒长")), self.state()
        p["operations"].append({"op": "future.unknown", "params": {"target": "self"}})
        c = self.context(p)
        c["resolved_energy_cost"] = 2
        r = execute_effects(p, s, c)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(r["state"], s)
        self.assertEqual(r["events"], [])

    def test_result_state_has_no_aliases_and_keeps_all_four_slots(self):
        p, s = self.program("徒长"), self.state()
        r = execute_effects(p, s, self.context(p))
        r["state"]["self"]["move_ids"][1] = 888
        r["state"]["turn_context"]["note"] = "changed"
        self.assertEqual(s["self"]["move_ids"], [7020360, 0, 7030220, 0])
        self.assertEqual(s["turn_context"]["note"], "explicit experiment")

    def test_invalid_resource_state_and_zero_hp_actor_do_not_execute(self):
        p = self.program("徒长")
        for patch in ({"hp": 0}, {"hp": 151}, {"energy": 13}, {"energy": True}, {"hp": float("nan")}):
            s = self.state()
            s["self"].update(patch)
            self.assertEqual(execute_effects(p, s, self.context(p))["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
