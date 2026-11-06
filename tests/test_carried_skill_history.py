"""Committed event fixtures; persistent source growth, not damage calibration."""
from copy import deepcopy
import unittest

from lab import action_outcome_runtime as outcomes, skill_history_runtime as history, dynamic_skills as dynamic
from lab.prepared_rules import PreparedRules
from lab.server import load_catalog
from lab.victory_rules import initialize_victory
from tests import test_action_runtime as fixtures


class CarriedSkillHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = PreparedRules(load_catalog()[0])
        cls.programs = history.programs(cls.prepared)

    def fixture(self, slots):
        state = {'snapshot_id': self.prepared.snapshot_id, 'turn': 1, 'teams': {}}
        for side in ('a', 'b'):
            actor = fixtures.member(side + '0')
            actor.update(entered_turn=0, skill_slots=list(slots if side == 'a' else [7020360, 0, 0, 0]), committed_skill_history=[])
            state['teams'][side] = {'active_slot': 0, 'members': [actor], 'marks': {'positive': None, 'negative': None}}
        initialize_victory(state)
        return state

    def action(self, state, slot):
        actor = state['teams']['a']['members'][0]
        mid = actor['skill_slots'][slot]
        return {'kind': 'skill', 'slot': slot, 'skill_id': mid, 'actor_member_id': actor['member_id'],
                'program': self.programs.get(mid, self.prepared._rules.program(mid))}

    def power(self, state, slot):
        action = self.action(state, slot)
        binding = history.bind_action(self.prepared, state, 'a', action)
        return history.modify_power(self.prepared._rules.skill(action['skill_id'])['power'], history.power_terms(state, binding))

    def commit(self, state, slot, token, *, successful=False, later=False, swift=False, kill=False):
        action = self.action(state, slot)
        binding = history.bind_action(self.prepared, state, 'a', action)
        events = [{'op': 'energy.pay', 'target': 'self', 'amount': 1}]
        if kill:
            target = state['teams']['b']['members'][0]
            target['hp'] = 0
            events.append({'op': 'damage', 'target': 'opponent', 'before': 10, 'after': 0, 'damage': 10,
                'params': {'kind': self.prepared._rules.skill(action['skill_id'])['kind'], 'target': 'opponent'}})
        outcomes.record_committed_action(self.prepared, state, 'a', action, events,
            event_token=token, response_success=successful)
        context = {**history.research_context(), 'action_is_later': later,
            'history_order_scope': 'entry_swift_subaction' if swift else 'top_level_action'}
        emitted = history.observe_action(self.prepared, state, 'a', action, action_token=token, context=context)
        history.after_skill(self.prepared, state, 'a', action, binding, action_token=token, context=context)
        return action, context, emitted

    def test_response_type_and_cost_count_committed_uses_once_with_slot_identity(self):
        state = self.fixture([7030210, 7020570, 7020600, 7030340])
        action, context, _ = self.commit(state, 3, 'grass')
        self.assertEqual(self.power(state, 0), 160)
        self.assertEqual(self.power(state, 1), 80)
        self.assertEqual(history.observe_action(self.prepared, state, 'a', action, action_token='grass', context=context), [])
        actor = state['teams']['a']['members'][0]
        actor['skill_slots'][3] = 7020780
        state['turn'] = 2
        self.commit(state, 3, 'response', successful=True)
        self.assertEqual(self.power(state, 1), 170)
        self.assertEqual(history.cost(self.prepared, state, 'a', 7020600, 6), 4)
        state['turn'] = 3
        self.commit(state, 2, 'self-cost-excluded')
        self.assertEqual(history.cost(self.prepared, state, 'a', 7020600, 6), 4)
        for index in range(3):
            state['turn'] += 1
            self.commit(state, 3, 'discount:' + str(index), later=True)
        self.assertEqual(history.cost(self.prepared, state, 'a', 7020600, 6), 0)
        actor = state['teams']['a']['members'][0]
        permutation = [2, 0, 1, 3]
        actor['skill_slots'] = [actor['skill_slots'][old] for old in permutation]
        dynamic.remap_member_slots(actor, permutation)
        self.assertEqual(history.cost(self.prepared, state, 'a', 7020600, 6, slot=0), 0)
        self.assertEqual(self.power(state, 2), 170)
        actor['dynamic_skill_origins'] = {'0': {'source': 'unproved-acquisition'}}
        with self.assertRaisesRegex(ValueError, 'acquisition baseline'):
            history.cost(self.prepared, state, 'a', 7020600, 6, slot=0)

    def test_fire_reset_first_action_scopes_and_other_skill_direct_defeat(self):
        state = self.fixture([7040250, 7040690, 7150350, 7040210])
        self.commit(state, 0, 'mountain-first')
        self.assertEqual(self.power(state, 0), 15)
        self.assertEqual(self.power(state, 1), 110)
        self.assertEqual(self.power(state, 2), 75)
        state['turn'] = 2
        self.commit(state, 1, 'warm-swift', swift=True)
        self.assertEqual(self.power(state, 0), 30)
        self.assertEqual(self.power(state, 1), 70)
        self.assertEqual(self.power(state, 2), 75)
        state['turn'] = 3
        action = {'kind': 'recharge', 'actor_member_id': 'a0'}
        history.observe_action(self.prepared, state, 'a', action, action_token='recharge-first',
            context={**history.research_context(), 'action_is_later': False})
        self.assertEqual(self.power(state, 2), 100)
        state['turn'] = 4
        self.commit(state, 0, 'other-skill-kill', kill=True, later=True)
        self.assertEqual(self.power(state, 3), 170)
        before = deepcopy(state)
        action = self.action(state, 0)
        with self.assertRaisesRegex(ValueError, 'already committed skill outcome token'):
            history.observe_action(self.prepared, state, 'a', action, action_token='unproved',
                context={**history.research_context(), 'action_is_later': False})
        self.assertEqual(state, before)

    def test_received_attack_packet_counts_once_and_resistance_uses_source_table(self):
        state = self.fixture([7040200, 7020360, 0, 0])
        target = state['teams']['b']['members'][0]
        forms = self.prepared._rules._catalog['forms']
        forms = forms.values() if isinstance(forms, dict) else forms
        target['form_id'] = next(f['id'] for f in forms
            if self.prepared._rules.type_multiplier('火系', f['id'])['multiplier'] == {'numerator':1, 'denominator':2}
            and self.prepared._rules.type_multiplier('普通系', f['id'])['multiplier'] == {'numerator':1, 'denominator':1})
        target['skill_slots'] = [7080140, 7070280, 7070300, 0]
        action = self.action(state, 0)
        source_kind = self.prepared._rules.skill(action['skill_id'])['kind']
        events = [{'op':'damage.hit','target':'opponent','before':300,'after':295,'damage':5,
            'params':{'kind':source_kind,'type':'火系'}},
            {'op':'damage.hit','target':'opponent','before':295,'after':290,'damage':5,
            'params':{'kind':source_kind,'type':'火系'}}]
        target['hp'] = 290
        outcomes.record_committed_action(self.prepared, state, 'a', action, events, event_token='received-fire')
        context = history.research_context()
        emitted = history.observe_received_attack(self.prepared, state, 'b', action, events,
            action_token='received-fire', context=context)
        self.assertEqual(len(emitted), 3)
        self.assertEqual(history.cost(self.prepared, state, 'b', 7080140, 8), 7)
        self.assertEqual(history.cost(self.prepared, state, 'b', 7070300, 5), 4)
        target = state['teams']['b']['members'][0]
        terms = history._totals(target['skill_history']['1']['events'], 7070280)
        self.assertEqual(terms[0], 20)
        self.assertEqual(history.observe_received_attack(self.prepared, state, 'b', action, events,
            action_token='received-fire', context=context), [])
        state['turn'] = 2
        action = self.action(state, 1)
        zero = [{'op':'damage','target':'opponent','before':290,'after':290,'damage':0,
            'params':{'kind':'physical','type':'普通系'}}]
        outcomes.record_committed_action(self.prepared, state, 'a', action, zero, event_token='received-neutral-zero')
        history.observe_received_attack(self.prepared, state, 'b', action, zero,
            action_token='received-neutral-zero', context=context)
        self.assertEqual(history.cost(self.prepared, state, 'b', 7080140, 8), 6)
        self.assertEqual(history.cost(self.prepared, state, 'b', 7070300, 5), 4)
        state['turn'] = 3
        action = self.action(state, 0)
        ignored = deepcopy(events)
        for event in ignored:
            event['params']['ignore_type_resistance'] = True
            event['before'] -= 10
            event['after'] -= 10
        state['teams']['b']['members'][0]['hp'] = 280
        outcomes.record_committed_action(self.prepared, state, 'a', action, ignored, event_token='ignored-resistance')
        history.observe_received_attack(self.prepared, state, 'b', action, ignored,
            action_token='ignored-resistance', context=context)
        self.assertEqual(history.cost(self.prepared, state, 'b', 7080140, 8), 5)
        self.assertEqual(history.cost(self.prepared, state, 'b', 7070300, 5), 4)

    def test_response_permanent_hits_and_previous_turn_nonattack_condition(self):
        state = self.fixture([7140270, 7100260, 7020780, 7020360])
        self.commit(state, 2, 'hit-response', successful=True)
        actor = state['teams']['a']['members'][0]
        self.assertEqual(history.hits(actor, 2, 7140270), 4)
        self.assertEqual(self.programs[7140270]['operations'][0]['params']['hits'], 2)
        self.assertIn(3005, self.programs[7140270]['dependency_ids'])
        from lab.research_phases import _fragment
        from lab.skill_execution import execute_skill
        relative = {k: deepcopy(state['teams'][s]['members'][0]) for k,s in (('self','a'),('opponent','b'))}
        for member in relative.values():
            member['types'] = self.prepared._rules.form(member['form_id'])['types']
        result = execute_skill(self.programs[7140270], relative,
            {**_fragment(self.programs[7140270]), 'turn': 1, 'resolved_energy_cost': 3}, damage_resolver=lambda *_: 1)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual(sum(e['op'] == 'damage' and e.get('source_op') == 'damage.sequence' for e in result['events']), 4)
        state['turn'] = 2
        self.commit(state, 1, 'after-defense')
        self.assertEqual(self.power(state, 1), 80)
        state['turn'] = 3
        self.commit(state, 1, 'after-attack')
        self.assertEqual(self.power(state, 1), 80)
        state['turn'] = 5
        self.commit(state, 1, 'after-empty-turn')
        self.assertEqual(self.power(state, 1), 100)
