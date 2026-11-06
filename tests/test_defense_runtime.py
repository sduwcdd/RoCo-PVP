"""Source records plus constructed phases; these are not real-game calibration."""
from copy import deepcopy
import unittest

from lab import defense_runtime as defense
from lab.prepared_rules import PreparedRules
from lab.research_phases import _fragment
from lab.server import load_catalog


def member():
    return {"member_id": "constructed", "hp": 100, "max_hp": 200, "energy": 5,
            "max_energy": 10, "types": ["普通系"], "statuses": {}, "stat_modifiers": {}}


class DefenseRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.prepared = PreparedRules(cls.catalog)
        cls.programs = defense.defense_programs(cls.prepared)

    def setUp(self):
        self.state = {"self": member(), "opponent": member()}

    def execute(self, mid=7020780, kind="physical", **kwargs):
        program = self.programs[mid]
        context = _fragment(program)
        context.update(defense_policies=deepcopy(defense.POLICIES), resolved_energy_cost=1)
        return defense.execute_defense_skill(program, self.state, context,
            turn=2, opponent_kind=kind, **kwargs)

    def test_source_bound_whole_description_and_original_hash(self):
        program = self.programs[7020780]
        self.assertEqual(program["source_description"], "减伤70%，应对攻击。")
        self.assertEqual(program["source_hash"], self.prepared._rules.program(7020780)["source_hash"])
        self.assertEqual(program["defense_components"]["reduction"], {"numerator": 70, "denominator": 100})
        for mid in (7100320, 7140180, 7150150):
            self.assertNotIn(mid, self.programs)
        self.assertIn(7020800, self.programs)
        self.assertIn(7020810, self.programs)
        self.assertIn(7090350, self.programs)  # Exact, fully parsed Snow Substitute.

    def test_dissolve_response_limited_buff_kind_dispel(self):
        from lab.modifier_ledger import register_stat
        opponent=self.state['opponent']
        opponent['stat_modifiers']['patk']=[{'numerator':20,'denominator':100}]
        register_stat(opponent,'patk',source_kind='trait',source_id=200235,
            source_hash=defense.fingerprint(self.catalog['traits']['200235']),buff_id=20010010)
        result=self.execute(7120270)
        self.assertEqual(result['status'],'applied',result['blockers'])
        self.assertFalse(result['state']['opponent']['stat_modifiers'].get('patk'))
        self.assertEqual(result['state']['self']['defense_runtime']['reduction'],{'numerator':90,'denominator':100})

    def test_barrier_reduces_shared_cooldown_only_on_attack_response(self):
        success=self.execute(7080240,'physical')
        self.assertEqual(success['status'],'applied',success['blockers'])
        defense.check_cooldown(success['state']['self'],3)
        missed=self.execute(7080240,'status')
        with self.assertRaises(ValueError):defense.check_cooldown(missed['state']['self'],3)
        self.assertEqual(success['state']['self']['defense_runtime']['cooldown_changes'][0]['before'],3)

    def test_phase_manifest_rejects_owned_source_drift(self):
        catalog = deepcopy(self.catalog)
        catalog["moves"]["7020780"]["desc"]["zh"] += "未实现附效。"
        with self.assertRaisesRegex(ValueError, "reviewed snapshot"):
            defense.defense_programs(catalog)

    def test_basic_response_window_shared_cd_and_isolation(self):
        before = deepcopy(self.state)
        out = self.execute()
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertTrue(out["response_success"])
        self.assertEqual(out["state"]["self"]["energy"], 4)
        self.assertEqual(self.state, before)
        self.assertFalse(out["calibrated"])
        defended = out["state"]["self"]
        for turn in (2, 3):
            with self.assertRaisesRegex(ValueError, "share cooldown"):
                defense.check_cooldown(defended, turn)
        defense.check_cooldown(defended, 4)
        self.assertEqual(defense.mitigate_damage(101, defended, 2, damage_kind="physical")["damage"], 30)
        self.assertEqual(defense.mitigate_damage(101, defended, 3, damage_kind="physical")["damage"], 101)
        expired = defense.finish_turn(defended, 2)
        self.assertNotIn("guard_turn", expired["defense_runtime"])
        self.assertIn("guard_turn", defended["defense_runtime"])
        self.assertEqual(expired["defense_runtime"]["cooldown_through_turn"], 3)

    def test_reduce_before_hp_clip_handles_overkill_and_bypasses_status(self):
        defended = self.execute()["state"]["self"]
        defended["hp"] = 10
        reduced = defense.mitigate_damage(1000, defended, 2, damage_kind="magical")
        self.assertEqual(reduced["damage"], 300)
        self.assertEqual(min(defended["hp"], reduced["damage"]), 10)
        self.assertFalse(reduced["hp_clipped"])
        for kind in ("status", "environment"):
            self.assertEqual(defense.mitigate_damage(101, defended, 2, damage_kind=kind)["damage"], 101)

    def test_counter_stats_only_if_matching_skill_kind(self):
        for kind, success in (("physical", True), ("magical", True), ("status", False),
                              ("defense", False), ("charge", False), ("switch", False), ("recharge", False)):
            out = self.execute(7020790, kind)
            self.assertEqual(out["status"], "applied", out["blockers"])
            self.assertEqual(out["response_success"], success)
            stats = out["state"]["self"]["stat_modifiers"]
            self.assertEqual(set(stats), {"patk", "matk"} if success else set())
            # CD follows every defense use, including unsuccessful responses.
            self.assertEqual(out["state"]["self"]["defense_runtime"]["cooldown_through_turn"], 3)

    def test_energy_and_hp_effects_cap_without_fabricated_coefficients(self):
        self.state["self"]["hp"] = 190
        out = self.execute(7030320)
        self.assertEqual(out["state"]["self"]["hp"], 200)
        out = self.execute(7030330)
        self.assertEqual(out["state"]["self"]["energy"], 7)
        self.state["opponent"]["energy"] = 1
        out = self.execute(7170150)
        self.assertEqual(out["state"]["opponent"]["energy"], 0)

    def test_status_response_uses_shared_immunity_and_lifecycle(self):
        for mid, status, layers, immune, reduction in (
                (7040300, "burn", 6, "火系", 70), (7090210, "freeze", 2, "冰系", 80)):
            self.state = {"self": member(), "opponent": member()}
            out = self.execute(mid)
            self.assertEqual(out["status"], "applied", out["blockers"])
            self.assertEqual(out["state"]["opponent"]["statuses"][status], layers)
            self.assertEqual(out["state"]["self"]["energy"], 4)
            self.assertEqual(defense.mitigate_damage(100, out["state"]["self"], 2,
                damage_kind="physical")["damage"], 100 - reduction)
            self.assertEqual(self.execute(mid, "status")["state"]["opponent"]["statuses"], {})
            self.state["opponent"]["types"] = [immune]
            out = self.execute(mid)
            self.assertEqual(out["status"], "applied", out["blockers"])
            self.assertEqual(out["state"]["opponent"]["statuses"].get(status, 0), 0)

    def test_freeze_response_requires_lifecycle_before_commit(self):
        program = self.programs[7090210]
        context = _fragment(program)
        context.update(defense_policies=deepcopy(defense.POLICIES), resolved_energy_cost=1)
        context.pop("status_lifecycle_policy", None)
        out = defense.execute_defense_skill(program, self.state, context, turn=2, opponent_kind="physical")
        self.assertEqual(out["status"], "blocked")
        self.assertEqual(out["state"], self.state)
        self.assertEqual(out["events"], [])

    def test_departure_targets_response_and_explicit_target_owner_choice(self):
        from tests import test_action_runtime as fixtures
        fixtures.JointActionRuntimeTests.setUpClass()
        fixture = fixtures.JointActionRuntimeTests()
        fixture.setUp()
        state = fixture.state
        with self.assertRaises(ValueError):
            defense.preflight_departure(self.catalog, state, "a", self.programs[7021130],
                opponent_kind="physical", replacement_slot=0)
        for mid, target, kind, self_slot, enemy_slot in (
                (7021130, "b", "physical", None, 0), (7050260, "a", "physical", 0, None),
                (7080250, "a", "status", 0, None)):
            out = defense.after_defense(self.catalog, state, "a", self.programs[mid],
                opponent_kind=kind, replacement_slot=self_slot, opponent_replacement_slot=enemy_slot,
                event_token=str(mid), context={"defense_departure_policy": defense.DEPARTURE_POLICY})
            self.assertEqual(out["status"], "applied", out["blockers"])
            self.assertEqual(out["state"]["teams"][target]["active_slot"], 0)
            self.assertEqual(state["teams"][target]["active_slot"], 1)
        self.assertIsNone(defense.preflight_departure(self.catalog, state, "a", self.programs[7021130],
            opponent_kind="status"))

    def test_response_hit_cost_and_mark_ledgers(self):
        from lab import mechanism_runtime as mechanisms, mark_runtime as marks
        for mid, target, change in ((7080400, "opponent", -3), (7150310, "self", 2)):
            out = self.execute(mid)
            self.assertEqual(out["status"], "applied", out["blockers"])
            self.assertEqual(mechanisms.modify_hits(out["state"][target], 5), 5 + change)
        program = self.programs[7090200]
        ctx = {**_fragment(program), "defense_policies": deepcopy(defense.POLICIES),
               "turn": 2, "resolved_energy_cost": 1, "opponent_declared_skill": 7020360}
        out = defense.execute_defense_skill(program, self.state, ctx, turn=2, opponent_kind="physical")
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertEqual(mechanisms.cost(out["state"]["opponent"], 7020360, 1, 2), 4)
        self.assertEqual(mechanisms.cost(out["state"]["opponent"], 7020370, 1, 2), 1)
        for mid, target, mark, stacks in ((7050420, "self", 1022, 1), (7090340, "opponent", 1032, 2),
                                         (7160340, "self", 3012, 1)):
            self.state = {"self": member(), "opponent": member()}
            for actor in self.state.values(): actor["field_marks"] = deepcopy(marks.EMPTY)
            out = self.execute(mid)
            self.assertEqual(out["status"], "applied", out["blockers"])
            self.assertEqual(marks.layer_count(out["state"][target], mark), stacks)

    def test_snow_substitute_requires_resolved_opponent_cost(self):
        missing = self.execute(7090350)
        self.assertEqual(missing["status"], "blocked")
        self.assertEqual(missing["state"], self.state)
        self.assertEqual(missing["events"], [])
        out = self.execute(7090350, opponent_effective_cost=2)
        self.assertEqual(out["state"]["self"]["energy"], 8)
        out = self.execute(7090350, "status")
        self.assertEqual(out["status"], "applied")
        self.assertEqual(out["state"]["self"]["energy"], 4)

    def test_huillu_response_uses_actual_source_category(self):
        from lab.weather_runtime import weather_programs
        program = weather_programs(self.prepared)[7050530]
        self.assertEqual(defense.response_categories(program), ["defense"])
        self.assertTrue(defense.response_success(program, "defense"))
        self.assertFalse(defense.response_success(program, "physical"))
        self.assertFalse(defense.response_success(program, "charge"))
        with self.assertRaisesRegex(ValueError, "Unknown opposing"):
            defense.response_success(program, "unknown")

    def test_missing_policy_and_tampered_phase_block_atomically(self):
        program = deepcopy(self.programs[7020780])
        context = _fragment(program)
        context.pop("defense_policies", None)
        context["resolved_energy_cost"] = 1
        out = defense.execute_defense_skill(program, self.state, context, turn=2, opponent_kind="physical")
        self.assertEqual(out["status"], "blocked")
        context["defense_policies"] = deepcopy(defense.POLICIES)
        program["defense_components"]["reduction"]["numerator"] = 100
        out = defense.execute_defense_skill(program, self.state, context, turn=2, opponent_kind="physical")
        self.assertEqual(out["status"], "blocked")
        self.assertEqual(out["state"], self.state)
        self.assertEqual(out["events"], [])

    def _history_state(self, turn, rows):
        from lab.phase_config import fingerprint
        actor = {"member_id": "actor-a", "hp": 100, "max_hp": 200, "energy": 5,
                  "max_energy": 10, "types": ["地系"], "statuses": {}, "stat_modifiers": {},
                  "committed_skill_history": []}
        for r in rows:
            row = {"member_id": "actor-a", "turn": r["turn"], "kind": r["kind"],
                   "response_success": r.get("response_success", False),
                   "effective_type": r.get("effective_type", "地系"), "token": r["token"]}
            row["hash"] = fingerprint({k: v for k, v in row.items() if k != "hash"})
            actor["committed_skill_history"].append(row)
        return {"turn": turn, "teams": {"a": {"active_slot": 0, "members": [actor]},
                                        "b": {"active_slot": 0, "members": [member()]}}}

    def test_hardening_conditional_cost_discounts_after_previous_attack(self):
        # Base cost 2 stays when previous turn had no attack commit.
        no_attack = self._history_state(2, [{"turn": 1, "kind": "defense", "token": "d1"}])
        self.assertEqual(defense.conditional_cost(no_attack, "a", 7080230, 2), 2)
        # Previous turn physical attack -> discount 2, floored at zero.
        attacked = self._history_state(2, [{"turn": 1, "kind": "physical", "token": "p1"}])
        self.assertEqual(defense.conditional_cost(attacked, "a", 7080230, 2), 0)
        # Previous turn magical also qualifies.
        magic = self._history_state(2, [{"turn": 1, "kind": "magical", "token": "m1"}])
        self.assertEqual(defense.conditional_cost(magic, "a", 7080230, 5), 3)
        # Previous turn was two turns ago; no discount.
        stale = self._history_state(3, [{"turn": 1, "kind": "physical", "token": "p1"}])
        self.assertEqual(defense.conditional_cost(stale, "a", 7080230, 2), 2)
        # Non-conditional-cost defense skill ignores history entirely.
        plain = self._history_state(2, [{"turn": 1, "kind": "physical", "token": "p1"}])
        self.assertEqual(defense.conditional_cost(plain, "a", 7020780, 1), 1)

    def test_phase_move_slot_bonus_only_from_source_positions(self):
        """相位移动: 50% base, +40% only from slot 1/3, additive cap 100."""
        program = self.programs[7070270]
        self.assertEqual(program["defense_components"]["reduction"], {"numerator": 50, "denominator": 100})
        self.assertEqual(program["defense_components"]["reduction_slot_bonus"]["slots"], [0, 2])
        context = _fragment(program)
        context.update(defense_policies=deepcopy(defense.POLICIES), resolved_energy_cost=1,
                       selected_skill_slot=0)
        state = {"self": member(), "opponent": member()}
        state["self"]["skill_slots"] = [7070270, None, None, None]
        result = defense.execute_defense_skill(program, state, context, turn=2, opponent_kind="physical")
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["self"]["defense_runtime"]["reduction"],
                         {"numerator": 90, "denominator": 100})
        context["selected_skill_slot"] = 1
        result = defense.execute_defense_skill(program, deepcopy(state), context, turn=2, opponent_kind="physical")
        self.assertEqual(result["state"]["self"]["defense_runtime"]["reduction"],
                         {"numerator": 50, "denominator": 100})
        context["selected_skill_slot"] = None
        result = defense.execute_defense_skill(program, deepcopy(state), context, turn=2, opponent_kind="physical")
        self.assertEqual(result["state"]["self"]["defense_runtime"]["reduction"],
                         {"numerator": 50, "denominator": 100})


    def test_meditation_composes_guard_and_success_only_star_grant(self):
        from lab import mark_runtime as marks
        program=self.programs[7190400]
        self.assertEqual(program['defense_components']['response_effects'],[
            {'op':'mark.add','target':'opponent','mark_id':1035,'stacks':2}])
        state={'self':member(),'opponent':member()}
        for actor in state.values():actor['field_marks']=deepcopy(marks.EMPTY)
        before=deepcopy(state)
        context={**_fragment(program),**marks.research_context(),
            'defense_policies':deepcopy(defense.POLICIES),'resolved_energy_cost':3}
        for kind,success in [('physical',True),('status',False)]:
            with self.subTest(opponent_kind=kind):
                result=defense.execute_defense_skill(program,state,context,turn=2,opponent_kind=kind)
                self.assertEqual(result['status'],'applied',result['blockers'])
                self.assertEqual(result['response_success'],success)
                self.assertEqual(result['state']['self']['energy'],2)
                self.assertEqual(sum(e['amount'] for e in result['events'] if e['op']=='energy.pay'),3)
                mark=result['state']['opponent']['field_marks']['negative']
                self.assertEqual((mark['id'],mark['stacks']) if mark else None,(1035,2) if success else None)
                self.assertEqual(defense.mitigate_damage(100,result['state']['self'],2,damage_kind='physical')['damage'],20)
        self.assertEqual(state,before)

if __name__ == "__main__":
    unittest.main()
