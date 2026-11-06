from copy import deepcopy
import unittest

from lab import live_damage, live_modifiers
from lab.hud_damage_runtime import HUDDamageResolver, _pet


def member(form, name):
    return {"member_id": name, "form_id": form, "hp": 500, "max_hp": 500,
            "energy": 10, "stats": {"patk": 120, "matk": 100, "pdef": 90,
                                      "mdef": 110, "spd": 80},
            "stat_modifiers": {}, "statuses": {}, "trait_id": 0,
            "skill_slots": [7020360, 7030440, 7020880, 0],
            "field_marks": {"positive": None, "negative": None},
            "entered_turn": 0, "mark_entry_actions": 0}


class HudDamageTests(unittest.TestCase):
    def test_native_will_response_uses_the_shared_200_power_variant_once(self):
        sid = 7700002
        self.context.update(weather_skill_id=sid, response_success=True)
        self.state['self']['skill_slots'][0] = sid
        params = {**self.params(sid), 'kind': 'physical'}
        result = self.resolver.explain(params, self.state, self.context)
        self.assertEqual(result['hud_case']['powerRange'], [200, 200])

    @classmethod
    def setUpClass(cls):
        cls.catalog = live_damage._rules()[0]
        cls.resolver = HUDDamageResolver(cls.catalog)

    def setUp(self):
        self.state = {"self": member(3001, "a:0"), "opponent": member(3002, "b:0")}
        self.context = {"snapshot_id": self.catalog["snapshot_id"], "turn": 1,
                        "weather": None, "weather_skill_id": 7020360,
                        "mark_first_attack": False, "mark_first_action": True,
                        "selected_skill_slot": 0}

    def params(self, sid):
        profile = live_damage.skill_math(sid, 3001, 3002)
        return {"target": "opponent", "kind": profile["kind"],
                "power": profile["power"], "type": profile["skillType"]}

    def native_pet(self, relative):
        pet = _pet(self.state[relative], self.context, attacking=relative == "self")
        pet.pop("_simulation_actor")
        pet["effectiveTraitId"] = 0
        pet["entryActionCount"] = self.state[relative]["mark_entry_actions"]
        return pet

    def test_reviewed_action_trait_attacks_and_labels_use_source_binding(self):
        from lab import action_traits, trait_runtime
        from lab.hud_damage_runtime import member_capability_issues
        actor = self.state['self']
        actor.update(form_id=3545, trait_id=200208, trait_policy=trait_runtime.POLICY,
                     trait_source_hash=action_traits.ROWS[200208]['record_hash'])
        self.assertEqual(member_capability_issues(actor), [])
        result = self.resolver.explain(self.params(7020360), self.state, self.context)
        self.assertGreater(result['nominal_damage'], 0)
        self.assertNotIn(200208, result['hud_case']['effects']['unreviewed_trait_ids'])
        # This trait only restricts slots; it must not change the HUD formula.
        profile = {**live_damage.skill_math(7020360, 3545, 3002), 'skillId': 7020360}
        native = _pet(actor, self.context, attacking=True)
        native.pop('_simulation_actor')
        native['effectiveTraitId'] = 200208
        self.assertEqual(live_modifiers.actor(native)['trait_source_hash'], action_traits.ROWS[200208]['record_hash'])
        expected = live_damage._damage_case(native, self.native_pet('opponent'), profile, profile['kind'])
        self.assertEqual(result['nominal_damage'], expected['minimum'])
        self.context['selected_skill_slot'] = 1
        with self.assertRaisesRegex(ValueError, 'forbids current skill slot 2'):
            self.resolver.explain(self.params(7020360), self.state, self.context)

    def test_action_trait_hud_rejects_forged_form_source_and_binding(self):
        from unittest.mock import patch
        from lab import action_traits
        from lab.hud_damage_runtime import member_capability_issues
        from lab.ruleset import BwikiRuleset
        actor = self.state['self']
        actor.update(form_id=3545, trait_id=200208)
        for changes in ({'form_id': 3001}, {'trait_source_hash': 'forged'}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'source form|source binding'):
                member_capability_issues({**actor, **changes})
        for target in ('record', 'provenance'):
            changed = deepcopy(self.catalog)
            if target == 'record':
                changed['traits']['200208']['desc']['zh'] += 'unreviewed'
            else:
                changed['provenance']['Skills']['content_sha256'] = 'forged'
            with self.subTest(target=target), patch('lab.live_damage._rules', return_value=(changed, BwikiRuleset(changed))):
                with self.assertRaisesRegex(ValueError, 'whole source changed'):
                    member_capability_issues(actor)

    def test_reviewed_departure_traits_have_source_bound_hud_admission(self):
        from lab import forced_trait_runtime as forced
        from lab.hud_damage_runtime import member_capability_issues
        config = forced._config()
        self.assertEqual(set(config['traits']), {'200092', '200105', '200165', '200262', '200290'})
        for raw_tid, row in config['traits'].items():
            tid = int(raw_tid)
            fid = next(f['id'] for f in self.catalog['forms'] if f.get('trait_id') == tid)
            with self.subTest(trait=tid):
                actor = self.state['self']
                actor.update(form_id=fid, trait_id=tid, trait_source_hash=row['record_hash'])
                self.assertEqual(member_capability_issues(actor), [])
                result = self.resolver.explain(self.params(7020360), self.state, self.context)
                self.assertNotIn(tid, result['hud_case']['effects']['unreviewed_trait_ids'])
                native = _pet(actor, self.context, attacking=True)
                native.pop('_simulation_actor')
                native['effectiveTraitId'] = tid
                self.assertEqual(live_modifiers.actor(native)['trait_source_hash'], row['record_hash'])
                self.assertGreater(result['nominal_damage'], 0)
                self.assertEqual(forced.source_evidence(live_damage._rules()[1], actor)['components']['cause'],
                                 'return' if tid == 200290 else 'detach')

    def test_departure_trait_hud_rejects_changed_sources_and_forged_binding(self):
        from unittest.mock import patch
        from lab import forced_trait_runtime as forced
        from lab.hud_damage_runtime import member_capability_issues
        from lab.ruleset import BwikiRuleset
        actor = self.state['self']
        actor.update(form_id=next(f['id'] for f in self.catalog['forms'] if f.get('trait_id') == 200290),
                     trait_id=200290)
        for change in ({'form_id': 3001}, {'trait_source_hash': 'forged'}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'exact form|source binding'):
                member_capability_issues({**actor, **change})
        for target in ('record', 'snapshot'):
            changed = deepcopy(self.catalog)
            if target == 'record':
                changed['traits']['200290']['desc']['zh'] += 'unreviewed'
            else:
                changed['snapshot_id'] = 'forged'
            with self.subTest(target=target), patch('lab.live_damage._rules', return_value=(changed, BwikiRuleset(changed))):
                with self.assertRaisesRegex(ValueError, 'whole source|snapshot differs'):
                    member_capability_issues(actor)
        with patch.object(forced, 'CONFIG_HASH', 'forged'):
            with self.assertRaisesRegex(ValueError, 'configuration changed'):
                member_capability_issues(actor)

    def test_electric_arc_burst_uses_exact_reviewed_power_once(self):
        sid = 7110180
        self.context.update(weather_skill_id=sid, mark_first_action=True)
        self.state['self']['skill_slots'][0] = sid
        params = {**self.params(sid), 'power': 120}
        burst = self.resolver.explain(params, self.state, self.context)
        self.assertEqual(burst['hud_case']['powerRange'], [120, 120])
        native = _pet(self.state['self'], self.context, attacking=True)
        native.pop('_simulation_actor')
        native.pop('_resolved_first_action')
        native['effectiveTraitId'] = 0
        profile = {**live_damage.skill_math(sid, 3001, 3002), 'skillId': sid}
        for count, expected in ((0, [120, 120]), (1, [80, 80]), (None, [80, 120])):
            native['entryActionCount'] = count
            result = live_damage._damage_case(native, self.native_pet('opponent'), profile, 'physical')
            self.assertEqual(result['powerRange'], expected)

        self.context['mark_first_action'] = False
        ordinary = self.resolver.explain({**params, 'power': 80}, self.state, self.context)
        self.assertEqual(ordinary['hud_case']['powerRange'], [80, 80])
        self.assertGreater(burst['nominal_damage'], ordinary['nominal_damage'])
        with self.assertRaisesRegex(ValueError, 'entry-burst power differs'):
            self.resolver.explain(params, self.state, self.context)

    def test_entry_burst_rejects_forged_power_even_with_original_base_and_source_changes(self):
        from unittest.mock import patch
        from lab import mechanism_runtime as mechanisms
        sid = 7110180
        self.context.update(weather_skill_id=sid, mark_first_action=True)
        self.state['self']['skill_slots'][0] = sid
        params = {**self.params(sid), 'power': 999, 'base_power': 80}
        with self.assertRaisesRegex(ValueError, 'entry-burst power differs'):
            self.resolver.explain(params, self.state, self.context)
        changed = deepcopy(mechanisms._configuration(mechanisms.CONFIG.stat().st_mtime_ns))
        next(row for row in changed['skills'] if row['skill_id'] == sid)['record_hash'] = 'forged'
        with patch.object(mechanisms, '_configuration', return_value=changed):
            with self.assertRaisesRegex(ValueError, 'source differs|source changed'):
                self.resolver.explain({**params, 'power': 120}, self.state, self.context)

    def test_three_attacks_match_current_native_hud_per_hit(self):
        for sid in (7020360, 7030440, 7020880):
            with self.subTest(skill=sid):
                self.context["weather_skill_id"] = sid
                profile = {**live_damage.skill_math(sid, 3001, 3002), "skillId": sid,
                           "selectedSlot": 1}
                expected = live_damage._damage_case(self.native_pet("self"),
                    self.native_pet("opponent"), profile, profile["kind"])
                result = self.resolver.explain(self.params(sid), self.state, self.context)
                self.assertEqual(expected["minimum"], expected["maximum"])
                self.assertEqual(result["nominal_damage"], expected["minimum"])
                self.assertEqual(result["actual_hp_loss"], min(500, expected["minimum"]))

    def test_stat_term_matches_a_real_native_stat_buff(self):
        from lab.live_inference import _buffs
        buff_id, data = next((bid, data) for bid, data in _buffs().items()
            if data.get("phyAtkPercent") and not any(data.get(k)
                for k in ("flatPowerBonus", "powerPercent", "damageTakenPercent")))
        percent = data["phyAtkPercent"]
        from fractions import Fraction
        ratio = Fraction(str(percent)) / 100
        self.state["self"]["stat_modifiers"] = {"patk": [
            {"numerator": ratio.numerator, "denominator": ratio.denominator}]}
        attacker = self.native_pet("self")
        attacker["battleBuffs"] = [{"id": int(buff_id), "layers": 1}]
        profile = {**live_damage.skill_math(7020360, 3001, 3002), "skillId": 7020360}
        expected = live_damage._damage_case(attacker, self.native_pet("opponent"), profile, "physical")
        actual = self.resolver.explain(self.params(7020360), self.state, self.context)
        self.assertEqual(actual["nominal_damage"], expected["minimum"])

    def test_rain_power_matches_native_hud_and_changes_damage(self):
        from lab.weather_runtime import set_weather
        sid = 7050160
        self.context["weather_skill_id"] = sid
        self.state["self"]["skill_slots"][0] = sid
        dry = self.resolver.explain(self.params(sid), self.state, self.context)
        self.context["weather"] = set_weather(None, 7050250, 1)[0]
        profile = {**live_damage.skill_math(sid, 3001, 3002), "skillId": sid}
        expected = live_damage._damage_case(self.native_pet("self"),
            self.native_pet("opponent"), profile, profile["kind"])
        wet = self.resolver.explain(self.params(sid), self.state, self.context)
        self.assertEqual(wet["nominal_damage"], expected["minimum"])
        self.assertGreater(wet["nominal_damage"], dry["nominal_damage"])

    def test_unknown_or_missing_buff_state_fails_closed(self):
        for statuses in ({"unreviewed": 1}, None):
            with self.subTest(statuses=statuses):
                self.state["self"]["statuses"] = statuses
                with self.assertRaisesRegex(ValueError, "HUD state unsupported"):
                    self.resolver.explain(self.params(7020360), self.state, self.context)

    def test_unknown_first_condition_and_old_power_fail_closed(self):
        context = deepcopy(self.context)
        del context["mark_first_attack"]
        with self.assertRaisesRegex(ValueError, "explicit mark_first_attack"):
            self.resolver.explain(self.params(7020360), self.state, context)
        params = self.params(7020360)
        params["power"] += 5
        with self.assertRaisesRegex(ValueError, "source power differs"):
            self.resolver.explain(params, self.state, self.context)

    def test_unsupported_power_ledger_is_not_silently_lost(self):
        self.state["self"]["pressure_ledger"] = {"entries": [-20]}
        with self.assertRaisesRegex(ValueError, "suppression ledger changed"):
            self.resolver.explain(self.params(7020360), self.state, self.context)

    def test_poison_source_group_and_committed_response_match_native_hud(self):
        sid = 7120220
        self.context["weather_skill_id"] = sid
        self.state["opponent"]["statuses"] = {"poison": 3, "burn": 2}
        for responded in (False, True):
            self.context["response_success"] = responded
            native_id = 7120221 if responded else sid
            target = self.native_pet("opponent")
            target["battleBuffs"] = [{"id": 20070010, "layers": 3}, {"id": 20070020, "layers": 2}]
            profile = {**live_damage.skill_math(native_id, 3001, 3002), "skillId": native_id}
            expected = live_damage._damage_case(self.native_pet("self"), target, profile, profile["kind"])
            actual = self.resolver.explain(self.params(sid), self.state, self.context)
            self.assertEqual(actual["nominal_damage"], expected["minimum"])
            self.assertEqual(actual["hud_case"]["powerRange"], [195, 195] if responded else [105, 105])

    def test_weather_and_ordinary_freeze_share_source_layers(self):
        sid = 7090310
        self.context["weather_skill_id"] = sid
        self.state["opponent"]["statuses"] = {"freeze": 2}
        self.state["opponent"]["weather_statuses"] = {"freeze": 1}
        actual = self.resolver.explain(self.params(sid), self.state, self.context)
        self.assertEqual(actual["hud_case"]["powerRange"], [100, 100])

    def test_energy_table_requires_pre_payment_energy_and_core_multiplier(self):
        sid = 7020550
        self.context["weather_skill_id"] = sid
        self.state["self"]["energy"] = 0
        with self.assertRaisesRegex(ValueError, "energy_before_cast"):
            self.resolver.explain(self.params(sid), self.state, self.context)
        self.context["energy_before_cast"] = 7
        result = self.resolver.explain(self.params(sid), self.state, self.context)
        self.assertGreater(result["hud_case"]["powerRange"][0], 0)
        self.context["core_magic_power_multiplier"] = {"numerator": 5, "denominator": 2}
        boosted = self.resolver.explain(self.params(sid), self.state, self.context)
        self.assertEqual(boosted["hud_case"]["powerRange"][0], result["hud_case"]["powerRange"][0] * 2.5)

    def test_owned_slot_history_is_applied_once(self):
        from lab import skill_history_runtime as history
        from lab.prepared_rules import PreparedRules
        from tests.test_carried_skill_history import CarriedSkillHistoryTests
        fixture = CarriedSkillHistoryTests()
        fixture.prepared = PreparedRules(self.catalog)
        fixture.programs = history.programs(fixture.prepared)
        joint = fixture.fixture([7040200, 0, 0, 0])
        fixture.commit(joint, 0, "hud-history-first")
        action = fixture.action(joint, 0)
        binding = history.bind_action(fixture.prepared, joint, "a", action)
        self.context.update(weather_skill_id=7040200, skill_history_power=history.power_terms(joint, binding))
        self.state["self"]["skill_slots"] = [7040200, 0, 0, 0]
        result = self.resolver.explain(self.params(7040200), self.state, self.context)
        expected = history.modify_power(self.params(7040200)["power"], self.context["skill_history_power"])
        self.assertEqual(result["hud_case"]["powerRange"], [expected, expected])

    def test_unmatched_conditional_factor_stays_blocked(self):
        params = {**self.params(7020360), "damage_multiplier": {"numerator": 7, "denominator": 1}}
        with self.assertRaisesRegex(ValueError, "factor differs"):
            self.resolver.explain(params, self.state, self.context)


if __name__ == "__main__":
    unittest.main()
