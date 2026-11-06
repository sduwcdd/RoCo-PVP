from copy import deepcopy
import unittest

from lab import cute_runtime, mark_runtime, live_damage
from lab.prepared_rules import PreparedRules
from lab.hud_damage_runtime import HUDDamageResolver, resolve_adaptive_program
from lab.simulation import _estimate
from lab import energy_burst_runtime
from lab.effect_runtime import execute_effects
from tests.test_hud_damage_runtime import member
from tests.test_mark_runtime import MarkRuntimeTests


class ConfirmedMarkCuteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog, cls.rules = live_damage._rules()
        cls.prepared = PreparedRules(cls.catalog)

    def test_cute_reforms_exact_panel_keeps_hp_ratio_and_other_state(self):
        record = {'form_id': 3005, 'nature_id': 1, 'talent_selection': {
            'selected': ['hp', 'patk', 'spd'], 'values': {'hp': 10, 'patk': 10, 'spd': 10}}}
        form = self.rules.form(3005)
        panels, _, _ = _estimate(self.catalog, record, form)
        actor = member(3005, 'a:0')
        actor.update(hp=panels['hp'] // 2, max_hp=panels['hp'], original_configuration=record,
                     statuses={'poison': 3}, stat_modifiers={'patk': [{'numerator': 10, 'denominator': 100}]})
        before = deepcopy(actor)
        gained = cute_runtime.gain_cute(actor, 1, source={'test': 'user-confirmed'})
        self.assertEqual(gained['gained'], 1)
        self.assertEqual(actor['form_id'], 3033)
        self.assertEqual(actor['hp'], max(1, before['hp'] * actor['max_hp'] // before['max_hp']))
        self.assertEqual(actor['statuses'], before['statuses'])
        self.assertEqual(actor['stat_modifiers'], before['stat_modifiers'])
        self.assertEqual(actor['energy'], before['energy'])
        self.assertEqual(actor['skill_slots'], before['skill_slots'])
        base = member(3001, 'b:0')
        self.assertEqual(cute_runtime.gain_cute(base, 1, source={'test': True})['gained'], 0)
        base['trait_id'] = 200182
        self.assertEqual(cute_runtime.gain_cute(base, 1, source={'test': True})['gained'], 1)

    def test_moonlight_counts_living_reserves_and_requires_explicit_layers(self):
        actor = {'trait_team_roster': {'self': [{'hp': 100, 'cute_layers': 2}, {'hp': 50, 'cute_layers': 1}],
                                      'opponent': [{'hp': 0, 'cute_layers': 90}, {'hp': 100, 'cute_layers': 3}]}}
        self.assertEqual(cute_runtime.alive_party_layers(actor), 6)
        del actor['trait_team_roster']['opponent'][0]['cute_layers']
        self.assertEqual(cute_runtime.alive_party_layers(actor), 6)
        del actor['trait_team_roster']['self'][1]['cute_layers']
        with self.assertRaisesRegex(ValueError, 'explicit'):
            cute_runtime.alive_party_layers(actor)

    def test_cute_cast_executes_shared_damage_and_gain_is_not_a_future_subscription(self):
        program = cute_runtime.programs(self.prepared)[7160140]
        record = {'form_id': 3005, 'nature_id': 1, 'talent_selection': {
            'selected': ['hp', 'patk', 'spd'], 'values': {'hp': 10, 'patk': 10, 'spd': 10}}}
        form = self.rules.form(3005)
        panels, _, _ = _estimate(self.catalog, record, form)
        actor = member(3005, 'a:0')
        actor.update(hp=panels['hp'], max_hp=panels['hp'], max_energy=10,
                     types=form['types'], original_configuration=record)
        actor['skill_slots'][0] = 7160140
        target = member(3002, 'b:0')
        target.update(types=self.rules.form(3002)['types'], max_energy=10)
        state = {'self': actor, 'opponent': target}
        context = {**MarkRuntimeTests().context(program), 'turn': 1, 'weather': None,
                   'weather_skill_id': 7160140, 'mark_first_attack': False,
                   'mark_first_action': True, 'selected_skill_slot': 0}
        result = cute_runtime.execute(program, state, context, HUDDamageResolver(self.catalog))
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertTrue(result['cute_cast_gains']['self'])
        self.assertEqual(result['state']['self']['energy'], 8)
        self.assertLess(result['state']['opponent']['hp'], target['hp'])
        self.assertNotIn('cute_sources', state['self'])
        status_program = cute_runtime.programs(self.prepared)[7160170]
        status_context = {**context, 'source_hash': status_program['source_hash'], 'weather_skill_id': 7160170}
        status_result = cute_runtime.execute(status_program, state, status_context)
        self.assertEqual(status_result['status'], 'applied', status_result['blockers'])
        self.assertTrue(any(e.get('op') == 'speed.flat' and e.get('amount') == 130 for e in status_result['events']))

    def test_star_multihit_explodes_once_with_power_and_guardian_floor(self):
        fixture = MarkRuntimeTests()
        state = fixture.state()
        state['self']['trait_id'] = 200210
        fixture.put(state, 'opponent', 1035, 3)
        program = self.prepared._rules.program(7020360)
        context = {**fixture.context(program), 'turn': 1, 'skill_kind': 'physical', 'skill_type': '普通系'}
        seen = []
        def star(descriptor, relative, ctx):
            seen.append(descriptor)
            return 7
        def base(program, relative, context, **kwargs):
            relative['opponent']['hp'] -= 5
            return {'status': 'applied', 'state': relative, 'events': [{'op': 'damage', 'damage': 1}] * 5}
        before = deepcopy(state)
        result = mark_runtime.execute_with_marks(program, state, context,
            damage_resolver=lambda *args: 1, mark_damage_resolver=star, execute_base=base)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]['power'], 60)
        self.assertEqual(result['state']['opponent']['field_marks']['negative']['stacks'], 2)
        self.assertEqual(state, before)

    def test_star_uses_trigger_kind_and_shared_hud_panel_math(self):
        resolver = HUDDamageResolver(self.catalog)
        state = {'self': member(3001, 'a:0'), 'opponent': member(3002, 'b:0')}
        state['self']['stats'].update(patk=220, matk=80)
        context = {'snapshot_id': self.catalog['snapshot_id'], 'turn': 1, 'weather': None,
                   'weather_skill_id': 7020360, 'mark_first_attack': False, 'mark_first_action': False}
        descriptor = {'op': 'mark.star_damage', 'mark_id': 1035, 'target': 'opponent', 'stacks': 3, 'power': 60}
        before = deepcopy(state)
        physical = resolver.mark_damage(descriptor, state, {**context, 'skill_kind': 'physical'})
        magical = resolver.mark_damage(descriptor, state, {**context, 'skill_kind': 'magical'})
        self.assertGreater(physical, magical)
        self.assertNotEqual(physical, 60)
        self.assertEqual(state, before)
        with self.assertRaisesRegex(ValueError, '归属'):
            resolver.mark_damage(descriptor, state, {**context, 'skill_kind': None})

    def test_adaptive_wish_uses_same_hud_attack_tie_rule_without_mutation(self):
        state = {'self': member(3001, 'a:0'), 'opponent': member(3002, 'b:0')}
        state['self']['stats'].update(patk=100, matk=100)
        program = {'wish_adaptive_damage': True, 'operations': [{'op': 'damage', 'params': {'kind': 'higher'}}]}
        resolved = resolve_adaptive_program(program, state, {'turn': 1, 'weather': None, 'mark_first_attack': False, 'mark_first_action': True})
        self.assertEqual(resolved['operations'][0]['params']['kind'], 'physical')
        self.assertEqual(program['operations'][0]['params']['kind'], 'higher')

    def test_energy_burst_consumes_all_zero_and_overflow_keep_shared_table(self):
        program = energy_burst_runtime.programs(self.prepared)[7020550]
        resolver = HUDDamageResolver(self.catalog)
        for energy in (0, 10, 15):
            actor, target = member(3001, 'a:0'), member(3002, 'b:0')
            for pet in (actor, target):
                pet.update(types=self.rules.form(pet['form_id'])['types'], max_energy=20)
            actor.update(energy=energy, skill_slots=[7020550, 0, 0, 0])
            state = {'self': actor, 'opponent': target}
            context = {**MarkRuntimeTests().context(program), 'turn': 1, 'weather': None,
                       'weather_skill_id': 7020550, 'selected_skill_slot': 0,
                       'mark_first_attack': False, 'mark_first_action': True,
                       'energy_before_cast': energy, 'resolved_energy_cost': energy}
            resolved = energy_burst_runtime.resolve_program(program, state, context)
            self.assertEqual(resolved['operations'][0]['params']['power'], 46 if energy == 0 else 211)
            result = execute_effects(resolved, state, context, damage_resolver=resolver)
            self.assertEqual(result['status'], 'applied', result['blockers'])
            self.assertEqual(result['state']['self']['energy'], 0)
            self.assertEqual(state['self']['energy'], energy)

    def test_sentry_forecast_is_single_hit_normal_not_multihit_or_response(self):
        resolver = HUDDamageResolver(self.catalog)
        state = {'self': member(3001, 'a:0'), 'opponent': member(3002, 'b:0')}
        context = {'turn': 1, 'weather': None, 'mark_first_attack': False, 'mark_first_action': True,
                   'snapshot_id': self.catalog['snapshot_id'], 'selected_skill_slot': 0,
                   'weather_skill_id': 7160250, 'response_success': True}
        params = {'target': 'opponent', 'kind': 'magical', 'type': '萌系', 'power': 30}
        quote = resolver.explain(params, state, {**context, 'response_success': False})
        self.assertEqual(resolver.predict_single_hit(state, 7160250, context), quote['nominal_damage'])


if __name__ == '__main__':
    unittest.main()
