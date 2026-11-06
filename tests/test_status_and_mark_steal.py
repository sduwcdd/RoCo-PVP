from copy import deepcopy
from fractions import Fraction
import unittest

from lab import status_skill_runtime as status_skills, mark_steal_runtime as steals, mark_runtime as marks, trait_runtime as traits
from lab.prepared_rules import PreparedRules
from lab.research_phases import _fragment
from lab.server import load_catalog
from tests.test_action_runtime import member


class StatusAndMarkStealTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = PreparedRules(load_catalog()[0])

    def state(self):
        return {'snapshot_id': self.prepared.snapshot_id, 'turn': 1,
            'teams': {side: {'active_slot': 0, 'members': [member(side)],
                            'marks': deepcopy(marks.EMPTY)} for side in ('a', 'b')}}

    def test_conductive_uses_existing_pair_discharge_chart_and_one_payment_per_cast(self):
        program = status_skills.programs(self.prepared)[7110450]
        state = {'self': member('caster'), 'opponent': member('target')}
        for actor in state.values():
            actor['types'] = self.prepared._rules.form(actor['form_id'])['types']
        context = {**_fragment(program), **status_skills.research_context(), 'resolved_energy_cost': 3}
        before = deepcopy(state)
        first = status_skills.execute(program, state, context, lambda *_: 7)
        self.assertEqual(first['status'], 'applied', first['blockers'])
        self.assertEqual(first['state']['opponent']['weather_statuses']['conductive'], 1)
        second = status_skills.execute(program, first['state'], context, lambda *_: 7)
        self.assertEqual(second['status'], 'applied', second['blockers'])
        ratio = self.prepared._rules.type_multiplier('电系', state['opponent']['form_id'])['multiplier']
        exact = Fraction(350, 4) * Fraction(ratio['numerator'], ratio['denominator'])
        discharged = min(286, max(1, exact.numerator // exact.denominator) if exact > 0 else 0)
        self.assertEqual(second['state']['opponent']['hp'], 286 - discharged)
        self.assertEqual(second['state']['opponent']['weather_statuses']['conductive'], 0)
        self.assertEqual(second['state']['self']['energy'], 4)
        self.assertEqual(state, before)

    def test_single_mark_transfers_one_layer_with_original_sources_and_replay_is_idempotent(self):
        state = self.state()
        state['teams']['b']['marks']['positive'] = {'id': 1021, 'stacks': 2,
            'sources': [{'source_id': 7030240, 'added_layers': 2}]}
        program = steals.programs(self.prepared)[7130340]
        context = {**marks.research_context(), **steals.research_context()}
        before = deepcopy(state)
        steals.preflight(self.prepared, state, 'a', program, context=context)
        self.assertEqual(state, before)
        events = steals.after_skill(self.prepared, state, 'a', program, event_token='steal:1', context=context)
        self.assertEqual(state['teams']['b']['marks']['positive']['stacks'], 1)
        gained = state['teams']['a']['marks']['positive']
        self.assertEqual(gained['stacks'], 1)
        self.assertEqual(gained['sources'][0]['donor_sources'][0]['source_id'], 7030240)
        self.assertEqual(len(events), 2)
        self.assertEqual(steals.after_skill(self.prepared, state, 'a', program, event_token='steal:1', context=context), [])

    def test_ambiguous_polarities_replacement_lineage_and_simultaneous_traits_block(self):
        program = steals.programs(self.prepared)[7130340]
        context = {**marks.research_context(), **steals.research_context()}
        state = self.state()
        state['teams']['b']['marks']['positive'] = {'id': 1021, 'stacks': 2, 'sources': []}
        state['teams']['b']['marks']['negative'] = {'id': 1014, 'stacks': 1, 'sources': []}
        with self.assertRaisesRegex(ValueError, 'both enemy mark polarities'):
            steals.preflight(self.prepared, state, 'a', program, context=context)
        state['teams']['b']['marks']['negative'] = None
        state['teams']['a']['marks']['positive'] = {'id': 1022, 'stacks': 1, 'sources': []}
        with self.assertRaisesRegex(ValueError, 'replacement semantics'):
            steals.preflight(self.prepared, state, 'a', program, context=context)
        state['teams']['a']['marks']['positive'] = None
        state['teams']['b']['marks']['positive']['sources'] = [{'added_layers': 1}, {'added_layers': 1}]
        with self.assertRaisesRegex(ValueError, 'multiple donor source histories'):
            steals.preflight(self.prepared, state, 'a', program, context=context)
        form = next(f['id'] for f in self.prepared._rules._catalog['forms'] if f.get('trait_id') == 200256)
        state['trait_policy'] = traits.POLICY
        for team in state['teams'].values():
            team['members'][0].update(form_id=form, trait_id=200256, trait_policy=traits.POLICY)
        before = deepcopy(state)
        with self.assertRaisesRegex(ValueError, 'Simultaneous mark-stealing'):
            steals.round_end(self.prepared, state, context=context)
        self.assertEqual(state, before)
