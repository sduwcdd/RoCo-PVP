"""Small component combinations; actual switch drivers are integrated separately."""
from copy import deepcopy
import unittest

from lab import trait_runtime as traits, trait_switch_components as components
from tests import test_trait_runtime as fixtures


class SwitchTraitComponentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.TraitRuntimeTests.setUpClass()
        cls.prepared = fixtures.TraitRuntimeTests.prepared
        cls.fixture = fixtures.TraitRuntimeTests()

    def state(self, leaving, observer=200080, incoming=200080):
        state = self.fixture.state(leaving, observer)
        reserve = self.fixture.member('reserve', incoming, hp=40)
        state['teams']['a']['members'].append(reserve)
        traits.bind(self.prepared, state)
        for team in state['teams'].values():
            for member in team['members']:
                member['types'] = deepcopy(self.prepared._rules.form(member['form_id'])['types'])
        return state

    def switch(self, state):
        state['teams']['a']['active_slot'] = 1
        return components.after_switch(self.prepared, state, 'a', 'a', 'reserve', token='switch:1')

    def test_successor_heal_and_immunity_clear_without_other_status_loss(self):
        state = self.state(200202)
        events = self.switch(state)
        incoming = state['teams']['a']['members'][1]
        self.assertEqual(incoming['hp'], 80)
        self.assertTrue(components.status_immune(incoming, 'leech'))
        self.assertTrue(any(e['op'] == 'hp.restore' for e in events))
        incoming['statuses']['poison'] = 3
        components.clear_successor_effects(incoming)
        self.assertFalse(components.status_immune(incoming, 'leech'))
        self.assertEqual(incoming['statuses']['poison'], 3)

    def test_poison_entry_and_defense_inheritance_compose_and_clean_exact_terms(self):
        state = self.state(200253, 200156)
        self.switch(state)
        incoming = state['teams']['a']['members'][1]
        self.assertEqual(incoming['statuses']['poison'], 5)
        self.assertEqual(incoming['stat_modifiers']['pdef'], [{'numerator': 20, 'denominator': 100}])
        self.assertTrue(components.status_immune(incoming, 'freeze'))
        components.clear_successor_effects(incoming)
        self.assertEqual(incoming['stat_modifiers']['pdef'], [])
        self.assertEqual(incoming['stat_modifiers']['mdef'], [])
        self.assertEqual(incoming['statuses']['poison'], 5)

    def test_reflection_reuses_existing_percent_exchange_and_deduplicates(self):
        state = self.state(200142)
        state['teams']['a']['members'][0]['hp'] = 20
        self.switch(state)
        self.assertEqual([m['hp'] for m in state['teams']['a']['members']], [40, 20])
        self.assertEqual(components.after_switch(self.prepared, state, 'a', 'a', 'reserve', token='switch:1'), [])

    def test_current_first_slot_grants_ignore_original_identity_and_use_selected_slot(self):
        state = self.state(200234)
        actor = state['teams']['a']['members'][0]
        actor['skill_slots'] = [7020370, 7020360, 7030440, 7020620]
        actor['carried_slot_order'] = [1, 0, 2, 3]
        self.assertEqual(set(components.swift_grants(self.prepared, state, actor)), {0})
        self.assertEqual(set(components.transmission_grants(actor)), {0})
        actor['skill_slots'][0] = 0
        self.assertEqual(components.transmission_grants(actor), {})
        state = self.state(200171)
        actor = state['teams']['a']['members'][0]
        actor['skill_slots'] = [7020370, 7020360, 7030440, 7020620]
        actor['carried_slot_order'] = [1, 0, 2, 3]
        old_original = {'kind': 'skill', 'slot': 1, 'skill_id': 7020360, 'actor_member_id': 'a'}
        self.assertEqual(components.after_action(self.prepared, state, 'a', old_original, token='old-original:1'), [])
        action = {'kind': 'skill', 'slot': 0, 'skill_id': 7020370, 'actor_member_id': 'a'}
        # The cast can move the selected skill away before its after-use hook.
        actor['skill_slots'] = [7020360, 7020370, 7030440, 7020620]
        components.after_action(self.prepared, state, 'a', action, token='use:1')
        self.assertEqual(state['teams']['b']['members'][0]['statuses']['burn'], 6)
        self.assertEqual(components.after_action(self.prepared, state, 'a', action, token='use:1'), [])

    def test_zero_energy_replacement_reuses_the_actual_forced_switch_executor(self):
        state = self.state(200080, incoming=200166)
        state['teams']['a']['members'][0]['energy'] = 0
        events = components.on_event(self.prepared, state, 'turn.end', side='a', token='end:1')
        self.assertEqual(state['teams']['a']['active_slot'], 1)
        self.assertTrue(any(e['op'] == 'switch.forced' for e in events))

    def test_real_forced_switch_applies_entry_poison_defense_and_immunity(self):
        from lab import forced_switch_runtime, weather_runtime
        state = self.state(200253, 200156)
        before = deepcopy(state)
        result = forced_switch_runtime.execute_forced_switch_fragment(self.prepared, state, 'a', 'detach',
            target_slot=1, context={'snapshot_id': self.prepared.snapshot_id,
                'forced_switch_policies': forced_switch_runtime.policies(), 'event_token': 'real-switch:1'})
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual(state, before)
        member = result['state']['teams']['a']['members'][1]
        self.assertEqual(member['statuses']['poison'], 5)
        self.assertEqual(member['stat_modifiers']['mdef'], [{'numerator': 20, 'denominator': 100}])
        self.assertTrue(components.status_immune(member, 'freeze'))
        events = weather_runtime.apply_status(member, 'a', 'freeze', 4, apply_effects=True)
        self.assertTrue(events[0]['immune'])

    def test_shared_transmission_reselects_current_first_slot_for_swift(self):
        from lab import mark_runtime, action_traits
        state = self.state(200234)
        actor = state['teams']['a']['members'][0]
        actor['skill_slots'] = [7020370, 7020360, 7030440, 7020620]
        events = mark_runtime.prepare_battle_transmission(state)
        self.assertEqual(actor['skill_slots'], [7020360, 7020370, 7030440, 7020620])
        self.assertEqual(actor['carried_slot_order'], [1, 0, 2, 3])
        self.assertEqual(len([e for e in events if e['op'] == 'transmission.move']), 1)
        self.assertEqual(mark_runtime.prepare_battle_transmission(state), [])
        mark_runtime.validate_battle_transmission(state)
        candidates = action_traits.swift_candidates(self.prepared, state, actor, [1, 1, 1, 1])
        self.assertTrue(candidates[0]['swift'])
        self.assertEqual(candidates[0]['action_trait']['trait_id'], 200234)
        self.assertNotIn('action_trait', candidates[1])
        self.assertTrue(action_traits.entry_program_has_swift(self.prepared._rules.program(7020360), candidates[0]))

    def test_hurricane_shared_wing_skill_uses_only_own_team(self):
        state = self.state(200211, observer=200124)
        actor = state['teams']['a']['members'][0]
        actor['skill_slots'] = [7020370, 7020360, 7030440, 7020620]
        self.assertEqual(components.swift_grants(self.prepared, state, actor), {})
        own_wing = self.fixture.member('own-wing', 200124)
        state['teams']['a']['members'].append(own_wing)
        self.assertEqual(set(components.swift_grants(self.prepared, state, actor)), {0})

    def test_voluntary_switch_abandons_charge_but_forced_departure_stays_immune(self):
        from tests import test_switch_runtime
        from lab import forced_switch_runtime
        fixture = test_switch_runtime.SwitchRuntimeTests()
        fixture.prepared = self.prepared
        fixture.catalog = self.prepared._rules._catalog
        fixture.setUp()
        actor = fixture.actor(0)
        actor['skill_slots'][0] = 7100170
        actor['charge'] = self.prepared._components()[1].charge_state(0, 7100170, 3)
        before = deepcopy(fixture.state)
        result = fixture.run_switch()
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertIsNone(result['state']['teams']['a']['members'][0]['charge'])
        self.assertTrue(any(e['op'] == 'charge.abandoned' for e in result['events']))
        self.assertEqual(fixture.state, before)
        forced = forced_switch_runtime.execute_forced_switch_fragment(self.prepared, before, 'a', 'detach',
            target_slot=1, context={'snapshot_id': self.prepared.snapshot_id,
                'forced_switch_policies': forced_switch_runtime.policies(), 'event_token': 'charged-detach'})
        self.assertEqual(forced['status'], 'applied', forced['blockers'])
        self.assertEqual(forced['state']['teams']['a']['active_slot'], 0)
        self.assertIsNotNone(forced['state']['teams']['a']['members'][0]['charge'])


if __name__ == '__main__':
    unittest.main()
