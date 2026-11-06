"""Trusted Wind Wall Swift execution and clever-slot return on entry."""
from copy import deepcopy
import json
import unittest

from lab import defense_runtime as defense
from lab import transformation_runtime as transformations
from lab.dynamic_skills import initialize_dynamic_skills, cost_delta
from lab.effect_runtime import HOOKS
from lab.prepared_rules import prepare_rules
from lab.research_phases import _fragment
from lab.server import load_catalog
from lab.switch_runtime import execute_switch_fragment, ENTRY_SWIFT_RESPONSE_POLICY
from tests.test_switch_runtime import member


class TransformationSwitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = prepare_rules(load_catalog()[0])
        cls.programs = transformations.programs(cls.prepared)

    def setUp(self):
        self.state = {'snapshot_id': self.prepared.snapshot_id, 'turn': 4,
            'teams': {side: {'active_slot': 0, 'members': [member(side+'-active'), member(side+'-bench', 3016)],
                'marks': {'positive': None, 'negative': None}} for side in ('a', 'b')}}
        self.state['teams']['a']['members'][1]['skill_slots'] = [7150150, 0, 0, 0]
        self.context = {'mode': 'isolated_voluntary_switch_experiment', 'snapshot_id': self.prepared.snapshot_id,
            'catalog_content_hash': self.prepared.catalog_content_hash, 'excluded_hooks': sorted(HOOKS),
            'unresolved_dependencies': [], 'cleanup_policy': 'retain_member_fields_experiment',
            'swift_policy': 'intrinsic_source_only_experiment', 'entry_timing': 'after_position_change_experiment',
            'incoming_effective_costs': [2, None, None, None],
            'entry_skill_context': _fragment(self.programs[7150150])}

    def execute(self, side='a'):
        return execute_switch_fragment(self.prepared, self.state, side, 1, self.context)

    def test_intrinsic_wind_wall_entry_activates_guard_without_inventing_response(self):
        original = deepcopy((self.state, self.context))
        self.context['entry_skill_context']['response_success'] = True
        result = self.execute()
        self.assertEqual(result['status'], 'applied', result['blockers'])
        actor = result['state']['teams']['a']['members'][1]
        self.assertEqual(actor['energy'], 8)
        self.assertEqual(actor['defense_runtime']['cooldown_through_turn'], 5)
        self.assertEqual(defense.mitigate_damage(101, actor, 4, damage_kind='magical')['damage'], 50)
        self.assertFalse(result['entry_skill_assumptions']['response_success'])
        self.assertEqual(result['entry_skill_assumptions']['entry_response_policy'], ENTRY_SWIFT_RESPONSE_POLICY)
        self.assertEqual(self.state, original[0])
        self.assertTrue(result['entry_swift']['skill_executed'])

    def test_temporary_wind_wall_uses_discount_then_returns_exact_slot_on_entry(self):
        actor = self.state['teams']['a']['members'][1]
        actor['skill_slots'] = [0, 0, 7150380, 0]
        initialize_dynamic_skills(self.state, seed=8)
        program = self.programs[7150380]
        transformations.replace_battle_slot(self.state, 'a', 'a-bench', 2, 7150150,
            source_skill_id=7150380, source_hash=program['source_hash'], kind='clever_change',
            pool_ids=program['transformation_metadata']['pool_ids'])
        self.assertEqual(cost_delta(actor, 2), -1)
        self.context['incoming_effective_costs'] = [None, None, 1, None]
        saved = json.loads(json.dumps(self.state))
        result = self.execute()
        self.assertEqual(result['status'], 'applied', result['blockers'])
        actor = result['state']['teams']['a']['members'][1]
        self.assertEqual(actor['skill_slots'], [0, 0, 7150380, 0])
        self.assertEqual(actor['energy'], 9)
        self.assertEqual(cost_delta(actor, 2), 0)
        self.assertEqual(result['state']['dynamic_skills']['original_slots']['a-bench'], [0, 0, 7150380, 0])
        self.assertEqual(result['state']['dynamic_skills']['prng']['counter'], 0)
        self.assertEqual(len([e for e in result['events'] if e['op'] == 'transformation.returned']), 1)
        self.assertEqual(self.state, saved)

    def test_b_side_uses_identical_trusted_path(self):
        self.state['teams']['b']['members'][1]['skill_slots'] = [7150150, 0, 0, 0]
        result = self.execute('b')
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual(result['state']['teams']['b']['active_slot'], 1)
        self.assertEqual(result['state']['teams']['b']['members'][1]['energy'], 8)
        self.assertEqual(result['state']['teams']['a'], self.state['teams']['a'])

    def test_client_program_cannot_change_source_bound_wind_wall(self):
        altered = deepcopy(self.programs[7150150])
        altered['operations'][0]['params']['reduction']['numerator'] = 100
        altered['transformation_components']['reduction_percent'] = 100
        self.context['entry_skill_program'] = altered
        result = self.execute()
        self.assertEqual(result['status'], 'applied', result['blockers'])
        actor = result['state']['teams']['a']['members'][1]
        self.assertEqual(actor['defense_runtime']['reduction']['numerator'], 50)

    def test_shared_cooldown_blocks_entire_switch_without_slot_return(self):
        actor = self.state['teams']['a']['members'][1]
        actor['defense_runtime'] = {'policy': defense.POLICY, 'cooldown_through_turn': 4}
        before = deepcopy(self.state)
        result = self.execute()
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('share cooldown', result['blockers'][0])
        self.assertEqual(result['state'], before)
        self.assertEqual(result['events'], [])
        self.assertEqual(self.state, before)


if __name__ == '__main__':
    unittest.main()
