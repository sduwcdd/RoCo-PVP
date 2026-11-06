from copy import deepcopy
from fractions import Fraction
import unittest

from lab.action_rules import ActionRules
from lab.charge_program_adapter import load_charge_program_overrides
from lab import charge_runtime as charge
from lab.research_phases import _fragment
from lab.server import load_catalog
from tests.test_action_runtime import member


class ChargeComponentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.programs = load_charge_program_overrides(cls.catalog)
        cls.rules = ActionRules(cls.catalog)

    def fragment(self, mid):
        program = self.programs[mid]
        state = {'self': member('actor'), 'opponent': member('target')}
        for actor in state.values():
            actor['types'] = ['龙系']
        state['self']['charge'] = self.rules.charge_state(1, mid, 1)
        context = {**_fragment(program), 'turn': 2, 'resolved_energy_cost': 3, 'response_success': False}
        return program, state, context

    def test_response_payload_doubles_only_when_response_succeeds(self):
        program, state, context = self.fragment(7100130)
        powers = []
        resolver = lambda params, *_: powers.append(params['power']) or 0
        ordinary = charge.execute(program, state, context, resolver)
        self.assertEqual(ordinary['status'], 'applied', ordinary['blockers'])
        counter = charge.execute(program, state, {**context, 'response_success': True}, resolver)
        self.assertEqual(counter['status'], 'applied', counter['blockers'])
        self.assertEqual(powers, [170, 340])
        self.assertEqual(counter['state']['self']['energy'], 7)
        self.assertEqual(program['response_kinds'], ['status'])
        self.assertEqual(state['self']['energy'], 10)

    def test_bypass_uses_real_token_without_fabricated_charge_history(self):
        from lab import duration_runtime as duration
        program, state, context = self.fragment(7100140)
        state['self']['charge'] = None
        grant = duration.programs(self.catalog)[7100180]
        granted = duration.execute_duration_skill(grant, state,
            {**_fragment(grant), **duration.research_context(), 'turn': 2, 'resolved_energy_cost': 2})
        self.assertEqual(granted['status'], 'applied', granted['blockers'])
        context['execution_phase'] = 'bypass_charge_pending_execution'
        powers = []
        result = charge.execute(program, granted['state'], context,
            lambda params, *_: powers.append(params['power']) or 0)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertIsNone(result['state']['self']['charge'])
        self.assertTrue(duration.charge_bypass(result['state']['self'], 2))
        self.assertEqual(powers, [program['operations'][0]['params']['power']])
        with self.assertRaises(ValueError):
            charge.execute(program, state, context, lambda *_: 0)

    def test_charge_observes_actual_attack_not_status_and_rejects_ambiguous_powers(self):
        program, state, context = self.fragment(7100140)
        actor = state['self']
        self.assertEqual(charge.observe_attack(actor, skill_id=1, skill_kind='status', turn=1,
            events=[{'op': 'status.add', 'target': 'opponent'}], action_token='1:0'), [])
        powers = []
        resolver = lambda params, *_: powers.append(params['power']) or 0
        charge.execute(program, state, context, resolver)
        event = {'op': 'damage', 'target': 'opponent', 'damage': 0,
                 'params': {'kind': 'physical', 'power': 90}}
        self.assertEqual(len(charge.observe_attack(actor, skill_id=123, skill_kind='physical', turn=1,
            events=[event, event], action_token='1:1')), 1)
        charge.execute(program, state, context, resolver)
        self.assertEqual(powers, [1, 270])
        self.assertEqual(len(actor['charge']['incoming_attacks']), 1)
        charge.observe_attack(actor, skill_id=124, skill_kind='physical', turn=2,
            events=[{**event, 'params': {'kind': 'physical', 'power': 100}}], action_token='2:0')
        with self.assertRaisesRegex(ValueError, 'selection is not source-verified'):
            charge.preflight(program, state, context, resolver)
        self.assertEqual(state['self']['energy'], 10)

    def test_file_bound_layers_and_flat_speed_are_applied_without_rewriting_source(self):
        program, state, context = self.fragment(7100170)
        before = deepcopy(state)
        result = charge.execute(program, state, context)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        actor = result['state']['self']
        for name in ('patk', 'matk'):
            term = actor['stat_modifiers'][name][0]
            self.assertEqual(Fraction(term['numerator'], term['denominator']), Fraction(3, 2))
        self.assertEqual(charge.modify_speed(actor, 100), 180)
        self.assertEqual(actor['charge_flat_modifiers'][0]['layers'], 8)
        for field, value in (('source_skill_id', 1), ('source_hash', 'changed'), ('per_layer', 11), ('layers', 9)):
            forged = deepcopy(actor)
            forged['charge_flat_modifiers'][0][field] = value
            with self.assertRaises(ValueError):
                charge.modify_speed(forged, 100)
        sprouting = deepcopy(state)
        sprouting['self']['field_marks'] = {'positive': {'id': 3012, 'stacks': 2, 'sources': []}, 'negative': None}
        enhanced = charge.execute(program, sprouting, context)
        self.assertEqual(enhanced['status'], 'applied', enhanced['blockers'])
        self.assertEqual(charge.modify_speed(enhanced['state']['self'], 100), 200)
        raw = program['charge_adapter_evidence']['patch2_skill_raw']['skill_result']
        self.assertEqual([raw[i]['buff_group_level'] for i in (1, 2, 3)], [15, 15, 8])
        self.assertTrue(all('buff_group_level' not in row for row in program['charge_adapter_evidence']['game_skill_raw']['skill_result']))
        self.assertEqual(state, before)
        edited = deepcopy(program)
        edited['charge_components'][0]['layers'] = 16
        with self.assertRaisesRegex(ValueError, 'modified'):
            charge.preflight(edited, state, context)
