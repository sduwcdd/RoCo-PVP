from copy import deepcopy
from fractions import Fraction
import unittest

from lab import action_outcome_runtime as outcomes
from lab import skill_history_runtime as history
from lab import slot_runtime as slots
from lab import dynamic_skills as dynamic
from lab.prepared_rules import PreparedRules
from lab.research_phases import _fragment
from lab.server import load_catalog
from lab.skill_execution import execute_skill
from lab.victory_rules import initialize_victory, reconcile_knockouts
from tests.test_action_runtime import member


class SkillHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = PreparedRules(load_catalog()[0])
        cls.programs = history.programs(cls.prepared)

    def fixture(self, skill_slots):
        state = {'snapshot_id': self.prepared.snapshot_id, 'turn': 1, 'teams': {}}
        for side in ('a', 'b'):
            actor = member(side + '0')
            actor.update(entered_turn=0, max_energy=10)
            actor['skill_slots'] = list(skill_slots if side == 'a' else [7020360, 0, 0, 0])
            state['teams'][side] = {'active_slot': 0, 'members': [actor], 'marks': {'positive': None, 'negative': None}}
        initialize_victory(state)
        return state

    def action(self, mid, slot=0):
        return {'kind': 'skill', 'actor_member_id': 'a0', 'skill_id': mid,
                'slot': slot, 'program': self.programs[mid]}

    def use(self, state, action, token, *, kill=False):
        binding = history.bind_action(self.prepared, state, 'a', action)
        context = {**_fragment(action['program']), **history.research_context(), 'turn': state['turn'],
                   'resolved_energy_cost': self.prepared._rules.skill(action['skill_id'])['energy']}
        if kill:
            state['teams']['b']['members'][0]['hp'] = 10
        relative = {k: deepcopy(state['teams'][s]['members'][0]) for k, s in [('self', 'a'), ('opponent', 'b')]}
        for actor in relative.values():
            actor['types'] = self.prepared._rules.form(actor['form_id'])['types']
        result = execute_skill(action['program'], relative, context, damage_resolver=lambda *_: 10 if kill else 0)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        for key, side in [('self', 'a'), ('opponent', 'b')]:
            state['teams'][side]['members'][0] = result['state'][key]
        outcomes.record_committed_action(self.prepared, state, 'a', action, result['events'], event_token=token)
        events = history.after_skill(self.prepared, state, 'a', action, binding, action_token=token, context=context)
        return binding, context, events

    def test_after_use_additions_are_once_and_follow_the_original_bundle_through_exchange(self):
        for mid, base, change in [(7020400, 90, 45), (7040200, 50, 20)]:
            state = self.fixture([mid, 7180200, 0, 0])
            binding, context, _ = self.use(state, self.action(mid), 'use:' + str(mid))
            self.assertEqual(history.modify_power(base, history.power_terms(state, binding)), base + change)
            self.assertEqual(history.after_skill(self.prepared, state, 'a', self.action(mid), binding,
                action_token='use:' + str(mid), context=context), [])
            swap = {'kind': 'skill', 'actor_member_id': 'a0', 'skill_id': 7180200,
                    'slot': 1, 'program': slots.programs(self.prepared)[7180200]}
            swap_context = slots.research_context()
            swap_context['_slot_selection_binding'] = slots.preflight_selection(self.prepared, state, 'a', swap, context=swap_context)
            slots.after_skill(self.prepared, state, 'a', swap, event_token='swap:' + str(mid), context=swap_context)
            self.assertEqual(history.modify_power(base, history.power_terms(state, binding)), base + change)
            moved = state['teams']['b']['members'][0]['skill_history']['0']
            self.assertEqual(moved['member_id'], 'b0')
            self.assertEqual(moved['events'][0]['actor_member_id'], 'a0')
            dynamic._validate_root(state)

    def test_entry_growth_and_use_installed_round_listener_survive_departure_without_fabricated_ticks(self):
        state = self.fixture([7110230, 7050300, 7180200, 0])
        history.initialize(self.prepared, state)
        entry = history.bind_action(self.prepared, state, 'a', self.action(7110230))
        self.assertEqual(history.modify_power(35, history.power_terms(state, entry)), 75)
        self.assertEqual(history.initialize(self.prepared, state), [])
        self.assertEqual(history.round_end(self.prepared, state), [])
        state['turn'] = 2
        state['teams']['a']['members'][0]['entered_turn'] = 2
        history.on_entry(self.prepared, state, 'a', event_token='entry:2')
        self.assertEqual(history.modify_power(35, history.power_terms(state, entry)), 115)
        water = self.action(7050300, 1)
        binding, _, _ = self.use(state, water, 'water:2')
        history.round_end(self.prepared, state)
        self.assertEqual(history.modify_power(90, history.power_terms(state, binding)), 110)
        self.assertEqual(history.round_end(self.prepared, state), [])
        state['turn'] = 3
        history.round_end(self.prepared, state)
        self.assertEqual(history.modify_power(90, history.power_terms(state, binding)), 130)
        swap = {'kind': 'skill', 'actor_member_id': 'a0', 'skill_id': 7180200, 'slot': 2,
                'program': slots.programs(self.prepared)[7180200]}
        with self.assertRaisesRegex(ValueError, 'round listener ownership'):
            slots.preflight_selection(self.prepared, state, 'a', swap, context=slots.research_context())
        history.on_departure(self.prepared, state, 'a', 'a0', event_token='leave:3')
        self.assertFalse(history.has_armed_listener(state['teams']['a']['members'][0]))
        state['turn'] = 4
        self.assertEqual(history.round_end(self.prepared, state), [])
        self.assertEqual(history.modify_power(90, history.power_terms(state, binding)), 130)

    def test_same_skill_direct_kills_double_power_restore_six_or_apply_seventy_percent_once(self):
        for mid in (7040620, 7020590, 7190230):
            state = self.fixture([mid, 0, 0, 0])
            action = self.action(mid)
            binding, context, events = self.use(state, action, 'kill:' + str(mid), kill=True)
            actor = state['teams']['a']['members'][0]
            if mid == 7040620:
                self.assertEqual(history.modify_power(75, history.power_terms(state, binding)), 150)
            elif mid == 7020590:
                self.assertEqual(actor['energy'], 10)
                self.assertEqual(sum(e['after'] - e['before'] for e in events if e['op'] == 'energy.restore'), 6)
            else:
                term = actor['stat_modifiers']['matk'][0]
                self.assertEqual(Fraction(term['numerator'], term['denominator']), Fraction(7, 10))
                self.assertEqual(actor['stat_modifier_sources']['matk'][0]['source_kind'], 'skill')
            self.assertEqual(history.after_skill(self.prepared, state, 'a', action, binding,
                action_token='kill:' + str(mid), context=context), [])
            reconcile_knockouts(state)

    def test_no_proof_means_no_kill_bonus_and_tampered_power_terms_are_rejected(self):
        state = self.fixture([7040620, 7020410, 0, 0])
        action = self.action(7040620)
        binding, context, _ = self.use(state, action, 'notkill')
        self.assertEqual(history.modify_power(75, history.power_terms(state, binding)), 75)
        other = {'kind': 'skill', 'actor_member_id': 'a0', 'skill_id': 7020410, 'slot': 1,
                 'program': self.prepared._rules.program(7020410)}
        self.assertIsNone(history.bind_action(self.prepared, state, 'a', other))
        self.assertEqual(history.after_skill(self.prepared, state, 'a', other, None,
            action_token='otherkill', context=context), [])
        terms = history.power_terms(state, binding)
        terms['add'] = 999
        with self.assertRaisesRegex(ValueError, 'terms changed'):
            history.modify_power(75, terms)
