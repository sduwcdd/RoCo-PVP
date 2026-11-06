from copy import deepcopy
import unittest

from lab import action_outcome_runtime as outcomes
from lab import trait_runtime as traits
from lab.prepared_rules import PreparedRules
from lab.server import load_catalog
from lab.victory_rules import initialize_victory, reconcile_knockouts, validate_victory
from tests.test_action_runtime import member


class ActionOutcomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = PreparedRules(load_catalog()[0])
        cls.interrupts = outcomes.programs(cls.prepared)

    def fixture(self, actor_form=3001, target_form=3001, skill_id=7020360):
        state = {'snapshot_id': self.prepared.snapshot_id, 'turn': 1, 'trait_policy': traits.POLICY, 'teams': {}}
        for side, form in [('a', actor_form), ('b', target_form)]:
            members = [member(side + '0', form), member(side + '1', 3001)]
            for m in members:
                m.update(trait_id=self.prepared._rules.form(m['form_id'])['trait_id'], trait_policy=traits.POLICY)
            state['teams'][side] = {'active_slot': 0, 'members': members}
        program = self.interrupts.get(skill_id) or self.prepared._rules.program(skill_id)
        action = {'kind': 'skill', 'skill_id': skill_id, 'actor_member_id': 'a0', 'slot': 1, 'program': program}
        opposite = {'kind': 'skill', 'skill_id': 7030510, 'actor_member_id': 'b0', 'slot': 1}
        state['teams']['b']['members'][0]['skill_slots'][1] = 7030510
        initialize_victory(state)
        return state, action, opposite

    @staticmethod
    def hit(before=10, after=0, kind='magical'):
        return {'op': 'damage', 'target': 'opponent', 'before': before, 'after': after,
                'damage': before - after, 'params': {'kind': kind, 'power': 75}}

    def test_three_interrupt_sources_cancel_only_pending_declared_action_without_payment(self):
        for mid in (7020520, 7080130, 7140090):
            state, action, opposite = self.fixture(skill_id=mid)
            hp = state['teams']['b']['members'][0]['hp']
            event = self.hit(hp, hp - 7, self.prepared._rules.skill(mid)['kind'])
            state['teams']['b']['members'][0]['hp'] -= 7
            emitted = outcomes.record_committed_action(self.prepared, state, 'a', action, [event],
                event_token='1:a:' + str(mid), opponent_action=opposite, response_success=True)
            self.assertEqual(emitted[0]['op'], 'action.interrupt.scheduled')
            before_energy = state['teams']['b']['members'][0]['energy']
            cancelled = outcomes.consume_interrupt(state, 'b', opposite)
            self.assertTrue(cancelled['cancelled'])
            self.assertEqual(cancelled['events'][0]['paid_energy'], 0)
            self.assertEqual(state['teams']['b']['members'][0]['energy'], before_energy)
            self.assertEqual(outcomes.consume_interrupt(state, 'b', opposite), {'cancelled': True, 'events': []})

    def test_interrupt_never_rewinds_committed_action_or_moves_to_replacement(self):
        state, action, opposite = self.fixture(skill_id=7020520)
        emitted = outcomes.record_committed_action(self.prepared, state, 'a', action, [], event_token='already',
            opponent_action=opposite, opponent_committed=True, response_success=True)
        self.assertEqual(emitted[0]['reason'], 'opponent_already_committed')
        self.assertFalse(outcomes.consume_interrupt(state, 'b', opposite)['cancelled'])
        outcomes.record_committed_action(self.prepared, state, 'a', action, [], event_token='pending',
            opponent_action=opposite, response_success=True)
        state['teams']['b']['active_slot'] = 1
        replacement = {**opposite, 'actor_member_id': 'b1'}
        state['teams']['b']['members'][1]['skill_slots'][1] = 7030510
        self.assertFalse(outcomes.consume_interrupt(state, 'b', replacement)['cancelled'])
        state['teams']['b']['active_slot'] = 0
        state['teams']['b']['members'][0]['skill_slots'][1] = 7030560
        self.assertFalse(outcomes.consume_interrupt(state, 'b', opposite)['cancelled'])

    def test_direct_defeat_credits_both_proved_demon_roles_once_and_rejects_stale_proof(self):
        state, action, _ = self.fixture(3180, 3180)
        state['teams']['b']['members'][0]['hp'] = 0
        event = self.hit()
        emitted = outcomes.record_committed_action(self.prepared, state, 'a', action, [event], event_token='kill:1')
        self.assertEqual(emitted[0]['op'], 'action.direct_defeat')
        scored = reconcile_knockouts(state)[0]
        self.assertEqual((scored['requested_magic_loss'], scored['actual_magic_loss']), (3, 3))
        self.assertEqual([r['role'] for r in scored['loss_source']['extras']], ['attacker', 'target'])
        self.assertEqual(outcomes.record_committed_action(self.prepared, state, 'a', action, [event, *emitted], event_token='kill:1'), [])
        self.assertEqual(reconcile_knockouts(state), [])
        state['teams']['b']['members'][0]['hp'] = 1
        reconcile_knockouts(state)
        state['teams']['b']['members'][0]['hp'] = 0
        with self.assertRaisesRegex(ValueError, 'Unadapted trait 200141'):
            reconcile_knockouts(state)

    def test_periodic_death_is_not_promoted_to_direct_kill_and_invalid_loss_has_no_proof(self):
        state, action, _ = self.fixture(3180)
        state['teams']['b']['members'][0]['hp'] = 0
        outcomes.record_committed_action(self.prepared, state, 'a', action,
            [{'op': 'status.damage', 'status': 'poison', 'target': 'opponent', 'damage': 10}], event_token='poison')
        self.assertNotIn('knockout_provenance', state)
        with self.assertRaisesRegex(ValueError, 'Unadapted trait 200141'):
            reconcile_knockouts(state)
        before = deepcopy(state)
        with self.assertRaisesRegex(ValueError, 'actual lethal'):
            outcomes.record_committed_action(self.prepared, state, 'a', action,
                [{**self.hit(), 'damage': 9}], event_token='wrongloss')
        self.assertEqual(state, before)

    def test_proved_demon_extra_composes_with_feign_zero_and_survives_attacker_switch(self):
        state, action, _ = self.fixture(3180, 3040)
        state['teams']['b']['members'][0]['hp'] = 0
        outcomes.record_committed_action(self.prepared, state, 'a', action, [self.hit()], event_token='kill:feign')
        state['teams']['a']['active_slot'] = 1
        scored = reconcile_knockouts(state)[0]
        self.assertEqual(scored['loss_source']['base_source']['trait_id'], 200081)
        self.assertEqual((scored['requested_magic_loss'], scored['actual_magic_loss']), (1, 1))
        self.assertEqual(scored['loss_source']['proof']['attacker']['member_id'], 'a0')
        self.assertEqual(state['victory']['knockouts']['b']['b0'], 1)
        validate_victory(state)
