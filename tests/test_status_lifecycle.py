"""Research arithmetic, source identity, composability, and legacy safety gates."""
from copy import deepcopy
import unittest

from lab import status_lifecycle as lifecycle
from lab.effect_runtime import HOOKS, execute_effects
from lab.prepared_rules import PreparedRules
from lab.server import load_catalog
from lab.skill_programs import compile_catalog
from lab.status_runtime import execute_status_phase


def member(mid):
    return {"member_id": mid, "form_id": 3004, "hp": 300, "max_hp": 350,
            "energy": 10, "max_energy": 20, "speed": 100, "entered_turn": 1,
            "rooted": False, "charge": None, "skill_slots": [0, 7020360, 0, 7020780],
            "types": ["普通系"], "statuses": {}, "stat_modifiers": {}}


class LifecycleTests(unittest.TestCase):
    def test_stack_cap_refresh_decay_expiry_and_source_are_composable(self):
        actor, source = member("a"), {"id": "explicit-research-source"}
        lifecycle.apply_layers(actor, "poison", 8, cap=10, remaining_rounds=2,
                               decay="subtract_one", source=source)
        source["id"] = "mutated"
        lifecycle.apply_layers(actor, "poison", 9, cap=10, remaining_rounds=1, refresh="max",
                               decay="subtract_one", source={"id": "second"})
        self.assertEqual(actor["statuses"]["poison"], 10)
        self.assertEqual(actor["status_lifecycles"]["poison"]["remaining_rounds"], 2)
        lifecycle.advance_lifecycles(actor, "a")
        self.assertEqual(actor["statuses"]["poison"], 9)
        events = lifecycle.advance_lifecycles(actor, "a")
        self.assertEqual(actor["statuses"]["poison"], 0)
        self.assertEqual(events[-1]["reason"], "expired")
        self.assertNotIn("poison", actor["status_lifecycles"])

    def test_replace_max_retain_duration_indefinite_and_departure(self):
        actor = member("a")
        lifecycle.apply_layers(actor, "freeze", 4, cap=99, remaining_rounds=2)
        lifecycle.apply_layers(actor, "freeze", 2, cap=99, stacking="max", remaining_rounds=1, refresh="retain")
        self.assertEqual(actor["statuses"]["freeze"], 4)
        self.assertEqual(actor["status_lifecycles"]["freeze"]["remaining_rounds"], 2)
        lifecycle.apply_layers(actor, "freeze", 1, cap=99, stacking="replace", refresh="max")
        self.assertIsNone(actor["status_lifecycles"]["freeze"]["remaining_rounds"])
        lifecycle.apply_layers(actor, "leech", 2, cap=99, departure="clear")
        actor["status_sources"] = {"leech": {"member_id": "caster"}}
        events = lifecycle.on_departure(actor, "a")
        self.assertEqual(actor["statuses"], {"freeze": 1, "leech": 0})
        self.assertEqual(len(events), 1)
        self.assertNotIn("leech", actor["status_sources"])

    def test_declarative_decay_can_skip_an_already_processed_builtin(self):
        actor = member("a")
        lifecycle.apply_layers(actor, "burn", 8, remaining_rounds=2, decay="half_floor")
        lifecycle.advance_lifecycles(actor, "a", decayed_statuses=("burn",))
        self.assertEqual(actor["statuses"]["burn"], 8)
        self.assertEqual(actor["status_lifecycles"]["burn"]["remaining_rounds"], 1)

    def test_invalid_application_does_not_mutate(self):
        for options in ({"cap": True}, {"remaining_rounds": 0}, {"stacking": "guess"}, {"decay": "guess"}):
            actor = member("a")
            before = deepcopy(actor)
            with self.assertRaises(ValueError):
                lifecycle.apply_layers(actor, "burn", 2, **options)
            self.assertEqual(actor, before)

    def test_freeze_combines_sources_strict_threshold_and_ice_immunity(self):
        for hp, ice, exhausted in ((15, False, False), (14, False, True), (0, False, False), (14, True, False)):
            actor = member("a")
            actor.update(hp=hp, max_hp=100, types=["冰系"] if ice else ["普通系"],
                         statuses={"freeze": 2}, weather_statuses={"freeze": 1})
            events = lifecycle.check_freeze(actor, "a")
            self.assertEqual(bool(events), exhausted)
            self.assertEqual(actor["hp"], 0 if exhausted else hp)
            if events:
                self.assertEqual(events[0]["stacks"], 3)
                self.assertIn("BUFF_CONF", events[0]["source"])


class StatusBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.prepared = PreparedRules(cls.catalog)
        cls.programs = compile_catalog(cls.catalog)["skills"]

    def program(self, name):
        return deepcopy(next(p for p in self.programs.values() if p["name"] == name))

    def fragment(self, program, bridge=True):
        context = {"mode": "isolated_skill_experiment", "snapshot_id": program["snapshot_id"],
                   "source_hash": program["source_hash"], "operation_order": "source_text_order_experiment",
                   "unresolved_dependencies": [], "excluded_hooks": sorted(HOOKS),
                   "resolved_energy_cost": 2, "damage_policy": "resolver_returns_actual_integer_hp_loss",
                   "actor_side": "a", "actor_member_id": "a-active",
                   "faint_policy": "stop_remaining_skill_on_exhaustion_experiment"}
        if bridge:
            context.update(lifecycle.research_context())
        return context

    def joint(self):
        state = {"snapshot_id": self.catalog["snapshot_id"], "turn": 2,
                 "teams": {side: {"active_slot": 1, "members": [member(side + "-bench"), member(side + "-active")],
                                  "marks": {"positive": None, "negative": None}} for side in ("a", "b")}}
        # The actual BWIKI form defines the types, not this synthetic fixture.
        for team in state["teams"].values():
            for actor in team["members"]:
                actor["types"] = deepcopy(self.prepared._rules.form(actor["form_id"])["types"])
        return state

    def active(self, state, side):
        team = state["teams"][side]
        return team["members"][team["active_slot"]]

    def status_context(self, schedule):
        return {"mode": "isolated_status_phase_experiment", "snapshot_id": self.prepared.snapshot_id,
                "catalog_content_hash": self.prepared.catalog_content_hash, "excluded_hooks": sorted(HOOKS),
                "unresolved_dependencies": [], "operation_order": "damage_then_decay_experiment", "schedule": schedule,
                "status_policy": {"immunity": "reject_existing_immune_status", "burn_decay_rounding": "floor"},
                "faint_policy": "research_status_exhaustion_skip_remaining_ticks_experiment",
                "status_lifecycle_policy": lifecycle.POLICY, "leech_policy": lifecycle.LEECH_POLICY}

    def bind(self, actor, side="a", mid="a-active"):
        lifecycle.apply_layers(actor, "leech", 3, cap=99, departure="clear")
        actor["status_sources"] = {"leech": {"side": side, "member_id": mid,
            "policy": lifecycle.LEECH_POLICY, "refresh_policy": lifecycle.SOURCE_REFRESH_POLICY}}

    def test_blizzard_compound_damage_and_freeze_no_longer_false_block(self):
        p = self.program("暴风雪")
        state = {"self": member("a-active"), "opponent": member("b-active")}
        state["opponent"].update(hp=20, max_hp=100)
        state["opponent"]["weather_statuses"] = {"freeze": 2}
        context = self.fragment(p)
        original = deepcopy((state, context, p))
        result = execute_effects(p, state, context, damage_resolver=lambda *_: 6)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["opponent"]["hp"], 0)
        self.assertTrue(any(e.get("effect_op") == "freeze.exhaust" for e in result["events"]))
        self.assertEqual((state, context, p), original)
        self.assertFalse(result["training_eligible"])

    def test_leech_binding_and_grass_immunity(self):
        p = self.program("孢子")
        for grass in (False, True):
            state = {"self": member("a-active"), "opponent": member("b-active")}
            if grass:
                state["opponent"]["types"] = ["草系"]
            result = execute_effects(p, state, self.fragment(p))
            self.assertEqual(result["status"], "applied", result["blockers"])
            target = result["state"]["opponent"]
            if grass:
                self.assertEqual(target["statuses"]["leech"], 0)
                self.assertNotIn("status_sources", target)
            else:
                self.assertEqual(target["statuses"]["leech"], 3)
                self.assertEqual(target["status_sources"]["leech"]["member_id"], "a-active")
                self.assertEqual(target["status_lifecycles"]["leech"]["departure"], "clear")
                self.assertIn("2%", result["events"][-1]["transfer_source"]["description"])

    def test_multihit_checks_freeze_between_hits_and_never_calls_second_hit(self):
        # Synthetic composition tests scheduling; it is not a real skill claim.
        p = self.program("暴风雪")
        damage = deepcopy(next(op for op in p["operations"] if op["op"] == "damage"))
        damage.update(op="damage.sequence")
        damage["params"]["hits"] = 3
        p["operations"] = [damage]
        p["dependency_ids"] = [*p.get("dependency_ids", []), 3005]
        state = {"self": member("a-active"), "opponent": member("b-active")}
        state["opponent"].update(hp=36, max_hp=350, statuses={"freeze": 2})
        context = self.fragment(p)
        context["multi_hit_policy"] = {"power_basis": "source_power_per_hit", "timing": "sequential_experiment"}
        calls = []
        result = execute_effects(p, state, context, damage_resolver=lambda *_: calls.append(1) or 2)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(calls, [1])
        self.assertEqual(result["state"]["opponent"]["hp"], 0)
        self.assertTrue(any(e["op"] == "research.hits_stopped" for e in result["events"]))

    def test_reapplication_declares_latest_source_ownership_of_all_layers(self):
        p = self.program("孢子")
        state = {"self": member("a-active"), "opponent": member("b-active")}
        self.bind(state["opponent"], mid="a-bench")
        result = execute_effects(p, state, self.fragment(p))
        self.assertEqual(result["status"], "applied", result["blockers"])
        target = result["state"]["opponent"]
        self.assertEqual(target["statuses"]["leech"], 6)
        self.assertEqual(target["status_sources"]["leech"]["member_id"], "a-active")
        self.assertEqual(target["status_sources"]["leech"]["refresh_policy"], lifecycle.SOURCE_REFRESH_POLICY)

    def test_legacy_and_spoofed_source_gate_before_payment(self):
        for name in ("孢子", "暴风雪"):
            p = self.program(name)
            state = {"self": member("a-active"), "opponent": member("b-active")}
            context = self.fragment(p, bridge=False)
            result = execute_effects(p, state, context, damage_resolver=lambda *_: 2)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["state"], state)
            self.assertEqual(result["events"], [])
        p = self.program("孢子")
        context = self.fragment(p)
        context["actor_member_id"] = "unrelated-source"
        result = execute_effects(p, state, context)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["state"], state)

    def test_leech_target_damage_bound_caster_heal_and_expiry(self):
        state = self.joint()
        target, caster = self.active(state, "b"), self.active(state, "a")
        self.bind(target)
        target["status_lifecycles"]["leech"]["remaining_rounds"] = 1
        caster["hp"] = 340
        original = deepcopy(state)
        result = execute_status_phase(self.prepared, state, self.status_context([{"side": "b", "status": "leech"}]))
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(self.active(result["state"], "b")["hp"], 279)
        self.assertEqual(self.active(result["state"], "a")["hp"], 350)
        self.assertEqual(result["events"][0]["actual_hp_loss"], 21)
        self.assertEqual(result["events"][0]["restored"], 10)
        self.assertEqual(self.active(result["state"], "b")["statuses"]["leech"], 0)
        self.assertEqual(state, original)
        self.assertFalse(result["training_eligible"])

    def test_leech_overkill_heals_actual_loss_and_never_revives_source(self):
        for source_hp in (0, 100):
            state = self.joint()
            source = state["teams"]["a"]["members"][0]
            source["hp"] = source_hp
            target = self.active(state, "b")
            self.bind(target, mid="a-bench")
            target["hp"] = 4
            result = execute_status_phase(self.prepared, state, self.status_context([{"side": "b", "status": "leech"}]))
            self.assertEqual(result["status"], "applied", result["blockers"])
            self.assertEqual(self.active(result["state"], "b")["hp"], 0)
            self.assertEqual(result["state"]["teams"]["a"]["members"][0]["hp"], source_hp + (4 if source_hp else 0))
            self.assertEqual(result["events"][0]["actual_hp_loss"], 4)

    def test_missing_binding_or_policy_rolls_back_before_poison_callback(self):
        for flaw in ("identity", "policy", "same_side"):
            state = self.joint()
            self.active(state, "a")["statuses"] = {"poison": 1}
            target = self.active(state, "b")
            self.bind(target)
            context = self.status_context([{"side": "a", "status": "poison"}, {"side": "b", "status": "leech"}])
            if flaw == "identity":
                target["status_sources"]["leech"]["member_id"] = "missing"
            elif flaw == "same_side":
                target["status_sources"]["leech"]["side"] = "b"
            else:
                context.pop("leech_policy")
            calls = []
            result = execute_status_phase(self.prepared, state, context, damage_resolver=lambda *_: calls.append(1) or 1)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["state"], state)
            self.assertEqual(result["events"], [])
            self.assertEqual(calls, [])

    def test_later_poison_failure_rolls_back_prior_leech_damage_and_source_heal(self):
        state = self.joint()
        self.bind(self.active(state, "b"))
        self.active(state, "a")["statuses"] = {"poison": 1}
        context = self.status_context([{"side": "b", "status": "leech"}, {"side": "a", "status": "poison"}])
        def resolver(*_):
            raise ValueError("synthetic resolver failure after leech")
        result = execute_status_phase(self.prepared, state, context, damage_resolver=resolver)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["state"], state)
        self.assertEqual(result["events"], [])

    def test_immune_existing_leech_blocks_and_freeze_equality_does_not(self):
        state = self.joint()
        target = self.active(state, "b")
        target["form_id"] = 3001
        target["types"] = deepcopy(self.prepared._rules.form(3001)["types"])
        self.bind(target)
        result = execute_status_phase(self.prepared, state, self.status_context([{"side": "b", "status": "leech"}]))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["state"], state)
        state = self.joint()
        target = self.active(state, "b")
        target.update(hp=35, statuses={"freeze": 2})
        result = execute_status_phase(self.prepared, state, self.status_context([]))
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(self.active(result["state"], "b")["hp"], 35)

    def test_burn_then_freeze_cancels_later_leech_with_no_partial_source_heal(self):
        state = self.joint()
        target = self.active(state, "b")
        self.bind(target)
        target["statuses"].update(burn=4, freeze=2)
        target["hp"] = 40  # 2*5%*350=35, before damage it is above the threshold.
        context = self.status_context([{"side": "b", "status": "burn"}, {"side": "b", "status": "leech"}])
        result = execute_status_phase(self.prepared, state, context, damage_resolver=lambda *_: 6)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(self.active(result["state"], "b")["hp"], 0)
        self.assertEqual(self.active(result["state"], "b")["statuses"]["burn"], 2)
        self.assertEqual(self.active(result["state"], "a")["hp"], 300)
        self.assertTrue(any(e.get("effect_op") == "freeze.exhaust" for e in result["events"]))
        self.assertTrue(any(e["op"] == "research.status_skipped" for e in result["events"]))

    def test_burn_duration_uses_builtin_decay_once_and_legacy_status_gate_remains(self):
        state = self.joint()
        target = self.active(state, "b")
        lifecycle.apply_layers(target, "burn", 8, remaining_rounds=2, decay="half_floor")
        context = self.status_context([{"side": "b", "status": "burn"}])
        result = execute_status_phase(self.prepared, state, context, damage_resolver=lambda *_: 2)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(self.active(result["state"], "b")["statuses"]["burn"], 4)
        self.assertEqual(self.active(result["state"], "b")["status_lifecycles"]["burn"]["remaining_rounds"], 1)
        self.bind(target)
        context.pop("status_lifecycle_policy")
        result = execute_status_phase(self.prepared, state, context, damage_resolver=lambda *_: 2)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["state"], state)


if __name__ == "__main__":
    unittest.main()
