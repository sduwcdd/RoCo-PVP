"""Small boundaries for user-confirmed pools and final-stage learning."""
from copy import deepcopy
import unittest

from lab.dynamic_skills import refresh_round, _learnset
from lab.learnset import legendary_available
from tests.test_dynamic_skills import catalog, member, battle, MIND, REWRITE


class ConfirmedInputsTests(unittest.TestCase):
    def test_mind_read_uses_carried_slots_and_refreshes_when_unused(self):
        source = catalog()
        state = battle(member('a', [MIND, 0, 0, 0]), opponent=member('b', [102, 0, 0, 0], 2))
        refresh_round(source, state)
        actor = state['teams']['a']['members'][0]
        self.assertEqual(actor['skill_slots'][0], 102)
        self.assertEqual(actor['dynamic_skill_origins']['0']['pool_ids'], [102])
        previous = deepcopy(state)
        state['turn'] = 2
        refresh_round(source, state)
        self.assertEqual(state['teams']['a']['members'][0]['dynamic_skill_origins']['0']['refreshed_turn'], 2)
        self.assertEqual(previous['dynamic_skills']['refreshed_turn'], 1)

    def test_rewrite_flat_pool_does_not_bypass_learning_conditions(self):
        source = catalog()
        source['forms'] = [{'id': 1, 'stage': 2}, {'id': 3, 'stage': 3}]
        source['details']['1'] = {'source_record': {'evolution_id': 'family'}, 'learnset': {
            'pool': [101, 102, 103, 104], 'native': [{'move': 101}],
            'legacy': [{'move': 102, 'bloodline': '水'}], 'legendary': [{'move': 103}]}}
        source['details']['3'] = {'source_record': {'evolution_id': 'family'}}
        actor = member('a', [REWRITE, 0, 0, 0])
        actor['original_configuration'] = {'form_id': 1, 'level': 60, 'bloodline_id': 3}
        self.assertEqual(_learnset(source, actor), [101, 104])
        actor['original_configuration']['bloodline_id'] = 4
        actor['original_configuration']['legendary_unlocked_ids'] = [103]
        self.assertEqual(_learnset(source, actor), [101, 102, 103, 104])

    def test_final_stage_defaults_unlocked_without_mutating_configuration(self):
        source = {'forms': [{'id': 1, 'stage': 2}, {'id': 2, 'stage': 3}],
                  'details': {str(i): {'source_record': {'evolution_id': 'family'}} for i in (1, 2)}}
        original = {'form_id': 2}
        self.assertTrue(legendary_available(source, original, 7150320))
        self.assertFalse(legendary_available(source, {'form_id': 1}, 7150320))
        self.assertEqual(original, {'form_id': 2})

    def test_generator_can_draw_a_generator_and_uses_original_enemy_slots(self):
        source = catalog()
        state = battle(member('a', [MIND, 0, 0, 0]), opponent=member('b', [MIND, 0, 0, 0], 2))
        refresh_round(source, state)
        first = state['teams']['a']['members'][0]
        self.assertEqual(first['dynamic_skill_origins']['0']['pool_ids'], [MIND])
        self.assertIsNone(first['dynamic_skill_origins']['0']['blocker'])
        # A later visible mutation must not expand mind-read's original team pool.
        state['teams']['b']['members'][0]['skill_slots'][1] = 999
        state['turn'] = 2
        refresh_round(source, state)
        self.assertEqual(state['teams']['a']['members'][0]['dynamic_skill_origins']['0']['pool_ids'], [MIND])

    def test_selected_generator_noop_spends_no_energy_and_deals_no_damage(self):
        from lab.dynamic_skills import POOL_POLICY
        from lab.effect_runtime import execute_effects, HOOKS
        from tests.test_effect_runtime import actor
        state = {'self': actor(), 'opponent': actor()}
        program = {'category': 'skill', 'status': 'compiled', 'game_id': MIND,
                   'snapshot_id': 'fixture', 'source_hash': 'reviewed-fixture', 'blockers': [],
                   'operations': [{'op': 'skill.noop', 'params': {'target': 'self'}}],
                   'generator_components': {'policy': POOL_POLICY, 'source_hash': 'reviewed-fixture'}}
        context = {'mode': 'isolated_skill_experiment', 'snapshot_id': 'fixture',
                   'source_hash': 'reviewed-fixture', 'operation_order': 'source_text_order_experiment',
                   'unresolved_dependencies': [], 'excluded_hooks': sorted(HOOKS),
                   'resolved_energy_cost': 0}
        result = execute_effects(program, state, context)
        self.assertEqual(result['status'], 'applied', result.get('blockers'))
        self.assertEqual(result['state'], state)
        self.assertIn('skill.noop', [e['op'] for e in result['events']])
