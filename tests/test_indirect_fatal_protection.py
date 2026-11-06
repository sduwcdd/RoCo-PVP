"""Indirect packets use the same real combatants and fatal hooks as direct hits."""
from copy import deepcopy
from fractions import Fraction
import unittest

from lab import status_lifecycle as life, trait_runtime as traits, weather_runtime as weather
from tests import test_trait_runtime as fixtures


class IndirectFatalProtectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.TraitRuntimeTests.setUpClass()
        cls.prepared = fixtures.TraitRuntimeTests.prepared
        cls.fixture = fixtures.TraitRuntimeTests()

    def state(self, opponent_trait=200080):
        state = self.fixture.state(200151, opponent_trait)
        traits.bind(self.prepared, state)
        for team in state['teams'].values():
            for member in team['members']:
                member['types'] = deepcopy(self.prepared._rules.form(member['form_id'])['types'])
        return state

    def test_leech_heals_only_actual_protected_hp_loss_and_burns_actual_foe(self):
        state = self.state()
        target, source = (state['teams'][s]['members'][0] for s in ('a', 'b'))
        target['hp'] = 1
        target['statuses']['leech'] = 1
        target['status_sources'] = {'leech': {'side': 'b', 'member_id': source['member_id'],
            'policy': life.LEECH_POLICY, 'refresh_policy': life.SOURCE_REFRESH_POLICY}}
        source['hp'] = 50
        event = life.tick_leech(state, 'a', policy=life.LEECH_POLICY)
        self.assertEqual(target['hp'], 1)
        self.assertEqual(event['actual_hp_loss'], 0)
        self.assertEqual(event['restored'], 0)
        self.assertEqual(source['hp'], 50)
        self.assertEqual(source['statuses']['burn'], 15)
        self.assertTrue(any(e['op'] == 'trait.fatal_protection' for e in event['trait_protection_events']))

    def test_weather_discharge_protects_before_loss_and_preserves_input_pair(self):
        state = self.state()
        members = {s: state['teams'][s]['members'][0] for s in ('a', 'b')}
        members['a']['hp'] = 10
        members['a']['weather_statuses'] = {'conductive': 1}
        before = deepcopy(members)
        field, _ = weather.set_weather(None, 7110440, 1)
        _, updated, events = weather.advance_weather(field, members, 1, apply_effects=True,
                                                     type_multiplier=lambda *_: Fraction(1))
        self.assertEqual(members, before)
        self.assertEqual(updated['a']['hp'], 1)
        self.assertEqual(updated['b']['statuses']['burn'], 15)
        packet = next(e for e in events if e.get('effect_op') == 'conductive.damage')
        self.assertEqual(packet['amount'], 9)
        burn = next(e for e in events if e['op'] == 'trait.fatal_burn')
        self.assertEqual(burn['target_side'], 'b')

    def test_missing_real_opponent_blocks_fatal_discharge_without_partial_commit(self):
        target = self.state()['teams']['a']['members'][0]
        target['hp'] = 10
        target['weather_statuses'] = {'conductive': 1}
        before = deepcopy(target)
        with self.assertRaisesRegex(ValueError, 'actual opposing member'):
            weather.apply_status(target, 'a', 'conductive', 1, apply_effects=True,
                                 type_multiplier=lambda *_: Fraction(1), turn=1)
        self.assertEqual(target, before)

    def test_conductive_skill_keeps_reflected_trait_event_target(self):
        from lab import status_skill_runtime
        from lab.research_phases import _fragment
        state = self.state()
        target, actor = (state['teams'][s]['members'][0] for s in ('a', 'b'))
        target['hp'] = 10
        target['weather_statuses'] = {'conductive': 1}
        program = status_skill_runtime.programs(self.prepared)[7110450]
        context = {**_fragment(program), **status_skill_runtime.research_context(),
                   'resolved_energy_cost': 0, 'turn': 1, 'actor_side': 'b'}
        result = status_skill_runtime.execute(program, {'self': actor, 'opponent': target}, context,
                                              damage_resolver=lambda *_: 0)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual(result['state']['opponent']['hp'], 1)
        self.assertEqual(result['state']['self']['statuses']['burn'], 15)
        event = next(e for e in result['events'] if e['op'] == 'trait.fatal_burn')
        self.assertEqual((event['target'], event['target_side']), ('self', 'b'))

    def test_after_skill_weather_hook_passes_real_actor_and_maps_reflection(self):
        state = self.state(opponent_trait=200303)
        target, actor = (state['teams'][s]['members'][0] for s in ('a', 'b'))
        target['hp'] = 10
        target['weather_statuses'] = {'conductive': 1}
        actor['weather_trait_id'] = 200303
        field, _ = weather.set_weather(None, 7110440, 1)
        events = weather.after_skill(field, 7110450, actor, target, [], side='b',
            type_multiplier=lambda *_: Fraction(1), skill_type='电系', turn=1)
        self.assertEqual(target['hp'], 1)
        self.assertEqual(actor['statuses']['burn'], 15)
        burn = next(e for e in events if e['op'] == 'trait.fatal_burn')
        self.assertEqual((burn['target'], burn['target_side']), ('self', 'b'))


if __name__ == '__main__':
    unittest.main()
