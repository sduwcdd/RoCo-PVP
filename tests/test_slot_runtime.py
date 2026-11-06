from copy import deepcopy
import unittest

from lab import dynamic_skills as dynamic
from lab import mark_runtime as marks
from lab import slot_runtime as slots
from lab import transformation_runtime as transform
from lab.prepared_rules import PreparedRules
from lab.research_phases import _fragment
from lab.server import load_catalog
from lab.skill_execution import execute_skill
from tests.test_action_runtime import member
from tests.test_dynamic_skills import catalog as dynamic_catalog


class SlotRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = PreparedRules(load_catalog()[0])
        cls.programs = slots.programs(cls.prepared)

    def fixture(self, own, opposing=None):
        state = {'snapshot_id': self.prepared.snapshot_id, 'turn': 1, 'teams': {}}
        for side, skill_slots in [('a', own), ('b', opposing or [7020360, 0, 0, 0])]:
            actor = member(side + '0')
            actor['skill_slots'] = list(skill_slots)
            state['teams'][side] = {'active_slot': 0, 'members': [actor]}
        return state

    def action(self, mid, slot):
        return {'kind': 'skill', 'actor_member_id': 'a0', 'skill_id': mid,
                'slot': slot, 'program': self.programs[mid]}

    def bind(self, state, action):
        context = {**slots.research_context(), 'turn': state['turn']}
        context['_slot_selection_binding'] = slots.preflight_selection(self.prepared, state, 'a', action, context=context)
        return context

    def test_position_locks_allow_safe_transmission_but_block_collision_without_mutation(self):
        for anchor in (7070160, 7070230):
            state = self.fixture([7070010, anchor, 7020410, 0])
            before = deepcopy(state)
            with self.assertRaisesRegex(ValueError, 'Position-locked'):
                marks.prepare_battle_transmission(state)
            self.assertEqual(state, before)
            state = self.fixture([7070010, 7020410, anchor, 0])
            marks.prepare_battle_transmission(state)
            self.assertEqual(state['teams']['a']['members'][0]['skill_slots'], [7020410, 7070010, anchor, 0])

    def test_interior_lever_runs_energy_prefix_once_then_reorders_and_edges_or_locks_block(self):
        state = self.fixture([7020410, 7070050, 7020360, 0])
        action = self.action(7070050, 1)
        context = self.bind(state, action)
        actor = state['teams']['a']['members'][0]
        actor['energy'] = 5
        relative = {'self': deepcopy(actor), 'opponent': deepcopy(state['teams']['b']['members'][0])}
        for m in relative.values():
            m['types'] = self.prepared._rules.form(m['form_id'])['types']
        prefix = execute_skill(action['program'], relative, {**_fragment(action['program']), 'resolved_energy_cost': 0})
        self.assertEqual(prefix['status'], 'applied', prefix['blockers'])
        state['teams']['a']['members'][0] = prefix['state']['self']
        events = slots.after_skill(self.prepared, state, 'a', action, event_token='lever:1', context=context)
        self.assertEqual(state['teams']['a']['members'][0]['skill_slots'], [7020360, 7070050, 7020410, 0])
        self.assertEqual(state['teams']['a']['members'][0]['energy'], 7)
        self.assertEqual(len(events), 1)
        self.assertEqual(slots.after_skill(self.prepared, state, 'a', action, event_token='lever:1', context=context), [])
        with self.assertRaisesRegex(ValueError, 'edge slot'):
            self.bind(self.fixture([7070050, 7020410, 7020360, 0]), self.action(7070050, 0))
        with self.assertRaisesRegex(ValueError, 'Position-locked'):
            self.bind(self.fixture([7070160, 7070050, 7020360, 0]), action)

    def test_bundle_exchange_rebinds_nested_origins_preserves_originals_and_clever_return(self):
        state = self.fixture([7180200, 7020410, 0, 0], [7020850, 7100150, 0, 0])
        fixture_catalog = dynamic_catalog()
        fixture_catalog['moves']['7060150'] = self.prepared._rules.skill(7060150)
        fixture_catalog['details']['3001'] = {'learnset': {'pool': [7060150]}}
        dynamic.refresh_round(fixture_catalog, state)
        donor = state['teams']['b']['members'][0]
        dynamic_origin = deepcopy(donor['dynamic_skill_origins']['0'])
        mirror = transform.programs(self.prepared)[7060150]
        transform.replace_battle_slot(state, 'b', 'b0', 0, 7150380, source_skill_id=7060150,
            source_hash=mirror['source_hash'], prior_dynamic_origin=dynamic_origin)
        previous = deepcopy(donor['transformation_skill_origins']['0'])
        clever = transform.programs(self.prepared)[7150380]
        transform.replace_battle_slot(state, 'b', 'b0', 0, 7150150, source_skill_id=7150380,
            source_hash=clever['source_hash'], kind='clever_change',
            pool_ids=clever['transformation_metadata']['pool_ids'], prior_transformation_origin=previous)
        donor['charge'] = self.prepared._components()[1].charge_state(1, 7100150, 1)
        originals = deepcopy(state['dynamic_skills']['original_slots'])
        counter = state['dynamic_skills']['prng']['counter']
        action = self.action(7180200, 0)
        context = self.bind(state, action)
        events = slots.after_skill(self.prepared, state, 'a', action, event_token='swap:1', context=context)
        actor, donor = (state['teams'][s]['members'][0] for s in ('a', 'b'))
        self.assertIsNone(donor['charge'])
        self.assertTrue(any(e['op'] == 'slot.charge_cancelled' for e in events))
        self.assertEqual(actor['carried_slot_owner'], 'b0')
        self.assertEqual(donor['carried_slot_owner'], 'a0')
        origin = actor['transformation_skill_origins']['0']
        nested = origin['prior_transformation_origin']['prior_dynamic_origin']
        self.assertEqual([origin['member_id'], origin['prior_transformation_origin']['member_id'], nested['member_id']], ['a0'] * 3)
        self.assertEqual(nested['pool_sources'], dynamic_origin['pool_sources'])
        self.assertEqual(nested['transfer_history'][0]['from_member_id'], 'b0')
        self.assertEqual(dynamic.cost_delta(actor, 0), -1)
        self.assertEqual(state['dynamic_skills']['original_slots'], originals)
        self.assertEqual(state['dynamic_skills']['prng']['counter'], counter)
        dynamic._validate_root(state)
        generated = {'kind': 'skill', 'actor_member_id': 'a0', 'skill_id': 7150150,
                     'slot': 0, 'program': self.prepared._rules.program(7150150)}
        opposite = {'kind': 'skill', 'actor_member_id': 'b0', 'skill_id': 7180200, 'slot': 0}
        follow_context = {'turn': 1}
        follow_context['_transformation_binding'] = transform.before_action(self.prepared, state, 'a', generated, opposite, follow_context)
        transform.after_action(self.prepared, state, 'a', generated, opposite, follow_context, {'status': 'applied'})
        actor = state['teams']['a']['members'][0]
        self.assertEqual(actor['skill_slots'][0], 7150380)
        self.assertEqual(actor['transformation_skill_origins']['0']['prior_dynamic_origin']['member_id'], 'a0')
        dynamic._validate_root(state)
        blocked = self.fixture([7180200, 7020410, 0, 0])
        blocked['teams']['a']['members'][0]['skill_modifiers'] = [{'amount': -1}]
        with self.assertRaisesRegex(ValueError, 'modifier transfer'):
            self.bind(blocked, action)
