from copy import deepcopy
import unittest

from lab.server import load_catalog
from lab import trait_runtime as traits
from lab.victory_rules import initialize_victory, reconcile_knockouts, validate_victory, terminal


class VictoryTraitLossTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]

    def state(self, form=3040, *, enabled=True):
        state = {'snapshot_id': self.catalog['snapshot_id'], 'turn': 1, 'teams': {}}
        forms = {record['id']: record for record in self.catalog['forms']}
        for side in ('a', 'b'):
            members = []
            for slot in range(3):
                selected = form if side == 'a' and slot == 0 else 3001
                members.append({'member_id': side + str(slot), 'form_id': selected, 'hp': 100,
                    'trait_id': forms[selected]['trait_id'], 'trait_policy': traits.POLICY})
            state['teams'][side] = {'active_slot': 0, 'members': members}
        if enabled:
            state['trait_policy'] = traits.POLICY
        initialize_victory(state)
        return state

    def test_feign_death_keeps_zero_loss_separate_from_two_knockout_occurrences(self):
        state = self.state()
        state['teams']['a']['members'][0]['hp'] = 0
        event = reconcile_knockouts(state)[0]
        self.assertEqual((event['requested_magic_loss'], event['actual_magic_loss']), (0, 0))
        self.assertEqual(event['loss_source']['trait_id'], 200081)
        self.assertEqual(state['victory']['knockouts']['a']['a0'], 1)
        self.assertEqual(state['victory']['magic']['a'], 4)
        self.assertEqual(state['victory']['winning_points']['b'], 0)
        self.assertEqual(reconcile_knockouts(state), [])
        state['teams']['a']['members'][0]['hp'] = 1
        self.assertEqual(reconcile_knockouts(state), [])
        state['teams']['a']['members'][0]['hp'] = 0
        self.assertEqual(reconcile_knockouts(state)[0]['occurrence'], 2)
        self.assertEqual(state['victory']['magic']['a'], 4)
        validate_victory(state)

    def test_royal_requests_four_and_actual_loss_caps_at_remaining_magic(self):
        full = self.state(5023)
        full['teams']['a']['members'][0]['hp'] = 0
        direct = reconcile_knockouts(full)[0]
        self.assertEqual((direct['requested_magic_loss'], direct['actual_magic_loss']), (4, 4))
        self.assertEqual(full['victory']['knockouts']['a']['a0'], 1)
        state = self.state(5023)
        state['teams']['a']['members'][1]['hp'] = 0
        first = reconcile_knockouts(state)[0]
        self.assertEqual(first['actual_magic_loss'], 1)
        state['teams']['a']['members'][0]['hp'] = 0
        event = reconcile_knockouts(state)[0]
        self.assertEqual((event['requested_magic_loss'], event['actual_magic_loss']), (4, 3))
        self.assertEqual(event['loss_source']['scope'], 'self_knockout_magic_loss_component_only')
        self.assertEqual(state['victory']['magic']['a'], 0)
        self.assertEqual(state['victory']['winning_points']['b'], 4)
        self.assertEqual(sum(state['victory']['knockouts']['a'].values()), 2)
        self.assertEqual(terminal(state)['winner'], 'b')
        self.assertEqual(reconcile_knockouts(state), [])

    def test_legacy_without_trait_policy_stays_one_and_can_migrate_known_counts(self):
        state = self.state(5023, enabled=False)
        state['teams']['a']['members'][0]['hp'] = 0
        self.assertEqual(reconcile_knockouts(state)[0]['winning_points_delta'], 1)
        self.assertNotIn('loss_components', state['victory'])
        state['trait_policy'] = traits.POLICY
        state['teams']['a']['members'][0]['hp'] = 10
        reconcile_knockouts(state)
        self.assertEqual(state['victory']['loss_components']['baseline']['knockouts']['a']['a0'], 1)
        state['teams']['a']['members'][0]['hp'] = 0
        event = reconcile_knockouts(state)[0]
        self.assertEqual((event['occurrence'], event['requested_magic_loss'], event['actual_magic_loss']), (2, 4, 3))
        validate_victory(state)

    def test_unattributed_demon_loss_and_modified_loss_source_are_rejected_transactionally(self):
        state = self.state(3180)
        before = deepcopy(state['victory'])
        state['teams']['a']['members'][0]['hp'] = 0
        with self.assertRaisesRegex(ValueError, 'Unadapted trait 200141'):
            reconcile_knockouts(state)
        self.assertEqual(state['victory'], before)
        state = self.state()
        state['teams']['a']['members'][0]['hp'] = 0
        reconcile_knockouts(state)
        state['victory']['loss_components']['events'][0]['loss_source']['source_hash'] = 'forged'
        with self.assertRaisesRegex(ValueError, 'unreviewed trait source'):
            validate_victory(state)
