"""Slot movement composes with source bindings under experimental timing."""
from copy import deepcopy
import unittest

from lab import mark_runtime as marks
from lab import transformation_runtime as transformation
from lab.dynamic_skills import (cost_delta, duplicate_slots_allowed, initialize_dynamic_skills,
                                refresh_round, _validate_root)
from tests.test_dynamic_skills import MIND, BORROW, battle, catalog, member


class TransmissionCompositionTests(unittest.TestCase):
    def test_generated_charge_moves_without_draw_or_rewriting_frozen_sources(self):
        state = battle(member('a', [7070010, MIND, 0, 0]))
        refresh_round(catalog(), state)
        actor = state['teams']['a']['members'][0]
        actor['charge'] = {'slot': 1, 'skill_id': 999}
        original = deepcopy(state['dynamic_skills'])
        source = deepcopy(actor['dynamic_skill_origins']['1']['pool_sources'])
        marks.prepare_battle_transmission(state)
        self.assertEqual(actor['skill_slots'], [999, 7070010, 0, 0])
        self.assertEqual(actor['carried_slot_order'], [1, 0, 2, 3])
        self.assertEqual(actor['charge'], {'slot': 0, 'skill_id': 999})
        self.assertEqual(cost_delta(actor, 0), -2)
        self.assertEqual(state['dynamic_skills'], original)
        self.assertEqual(actor['dynamic_skill_origins']['0']['pool_sources'], source)
        self.assertEqual(marks.prepare_battle_transmission(state), [])
        state['turn'] = 2
        self.assertEqual(refresh_round(catalog(), state)[0]['status'], 'held_charge')
        self.assertEqual(state['dynamic_skills']['prng']['counter'], 1)
        state['teams']['a']['members'][0]['charge'] = None
        state['turn'] = 3
        events = refresh_round(catalog(), state)
        self.assertEqual((events[0]['slot'], events[0]['origin_skill_id']), (0, MIND))
        self.assertEqual(state['dynamic_skills']['prng']['counter'], 2)
        self.assertEqual(state['dynamic_skills']['original_slots'], original['original_slots'])

    def test_each_copied_transmission_occurrence_moves_once_and_empty_slots_keep_identity(self):
        state = battle(member('a', [7070010, 0, 7060150, 0]))
        initialize_dynamic_skills(state)
        original = deepcopy(state['dynamic_skills'])
        transformation.replace_battle_slot(state, 'a', 'a', 2, 7070010,
            source_skill_id=7060150, source_hash='explicit-copy-fixture')
        actor = state['teams']['a']['members'][0]
        events = marks.prepare_battle_transmission(state)
        self.assertEqual(actor['skill_slots'], [0, 7070010, 0, 7070010])
        self.assertEqual(actor['carried_slot_order'], [1, 0, 3, 2])
        self.assertEqual([(e['from_slot'], e['to_slot']) for e in events], [(0, 1), (2, 3)])
        self.assertEqual(actor['transformation_skill_origins']['3']['slot'], 3)
        self.assertTrue(duplicate_slots_allowed(actor))
        self.assertEqual(state['dynamic_skills'], original)
        _validate_root(state)

    def test_movement_before_first_generation_preserves_original_snapshot(self):
        state = battle(member('a', [7070010, MIND, 0, 0]))
        marks.prepare_battle_transmission(state)
        events = refresh_round(catalog(), state)
        self.assertEqual(state['dynamic_skills']['original_slots']['a'], [7070010, MIND, 0, 0])
        self.assertEqual((events[0]['slot'], events[0]['origin_skill_id']), (0, MIND))
        self.assertEqual(state['dynamic_skills']['prng']['counter'], 1)

    def test_clever_return_restores_nested_dynamic_origin_at_its_moved_slot(self):
        from tests.test_transformation_runtime import TransformationRuntimeTests
        TransformationRuntimeTests.setUpClass()
        fixture = TransformationRuntimeTests()
        state = fixture.state(7070010, second=BORROW)
        state['teams']['a']['members'].append(member('reserve', [7150380, 0, 0, 0]))
        state.pop('dynamic_skills')
        initialize_dynamic_skills(state, seed=3)  # Fixed fixture draws the supported defense output.
        refresh_round(fixture.catalog, state)
        actor = state['teams']['a']['members'][0]
        original = deepcopy(state['dynamic_skills']['original_slots'])
        dynamic = deepcopy(actor['dynamic_skill_origins']['1'])
        action, opposite = fixture.action(state, slot=1), fixture.action(state, 'b')
        context = fixture.context(state, action, opposite)
        transformation.after_action(fixture.prepared, state, 'a', action, opposite, context, {'status': 'applied'})
        counter = state['dynamic_skills']['prng']['counter']
        marks.prepare_battle_transmission(state)
        actor = state['teams']['a']['members'][0]
        nested = actor['transformation_skill_origins']['0']['prior_dynamic_origin']
        self.assertEqual(nested['slot'], 0)
        self.assertEqual(nested['pool_sources'], dynamic['pool_sources'])
        action, opposite = fixture.action(state), fixture.action(state, 'b')
        context = fixture.context(state, action, opposite)
        events = transformation.after_action(fixture.prepared, state, 'a', action, opposite, context, {'status': 'applied'})
        actor = state['teams']['a']['members'][0]
        self.assertEqual(events[0]['op'], 'transformation.returned')
        self.assertEqual(actor['skill_slots'][0], 7150380)
        self.assertEqual(actor['dynamic_skill_origins']['0']['slot'], 0)
        self.assertEqual(state['dynamic_skills']['prng']['counter'], counter)
        self.assertEqual(state['dynamic_skills']['original_slots'], original)
        _validate_root(state)


if __name__ == '__main__':
    unittest.main()
