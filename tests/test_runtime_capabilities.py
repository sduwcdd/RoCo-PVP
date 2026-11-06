import unittest
from copy import deepcopy

from lab.runtime_capabilities import inspect_program
from lab.mechanism_runtime import cost, end_turn, POLICY


class RuntimeCapabilityTests(unittest.TestCase):
    def test_compilation_does_not_authorize_unknown_runtime_components(self):
        program = {'status': 'compiled', 'blockers': [], 'operations': [], 'native_rule': {
            'components': [{'effect': 'unimplemented.revive', 'params': {}}]}}
        report = inspect_program(program)
        self.assertTrue(report['description_structured'])
        self.assertFalse(report['components_executable'])
        self.assertIn('unimplemented.revive', report['blockers'][0])
        self.assertFalse(report['calibrated'])

    def test_defense_requires_source_bound_runtime_adapter(self):
        report = inspect_program({'status': 'compiled', 'operations': [{'op': 'defense.plan', 'params': {}}]})
        self.assertFalse(report['supported'])

    def test_unrecognized_status_is_not_silently_applied(self):
        report = inspect_program({'status': 'compiled', 'operations': [
            {'op': 'status.add', 'params': {'status': 'unknown'}}]})
        self.assertFalse(report['supported'])

    def test_modifier_expiry_and_skill_identity_and_floor(self):
        member = {'member_id': 'a', 'rooted': True,
            'root_restriction': {'policy': POLICY, 'expires_after': 3},
            'skill_modifiers': [
                {'policy': POLICY, 'skill_id': 1, 'amount': 7, 'applied_turn': 1, 'expires_after': 3},
                {'policy': POLICY, 'skill_id': 2, 'amount': -5, 'applied_turn': 1, 'expires_after': None}]}
        before = deepcopy(member)
        self.assertEqual(cost(member, 1, 2, 3), 9)
        self.assertEqual(cost(member, 1, 2, 4), 2)
        self.assertEqual(cost(member, 2, 2, 3), 0)
        self.assertEqual(cost(member, 3, 2, 3), 2)
        self.assertEqual(member, before)
        state = {'turn': 3, 'teams': {'a': {'members': [member]}}}
        events = end_turn(state)
        self.assertFalse(member['rooted'])
        self.assertEqual(len(member['skill_modifiers']), 1)
        self.assertEqual(events[0]['op'], 'restriction.expire')
        self.assertEqual(end_turn(state), [])

    def test_pending_end_turn_modifier_commits_once(self):
        actor = {'member_id': 'a', 'pending_modifiers': [{'policy': POLICY,
            'component': {'op': 'skill.cost', 'target': 'self', 'amount': -1},
            'program': {'game_id': 42, 'source_hash': 'source'}, 'context': {'turn': 1}}]}
        state = {'turn': 1, 'teams': {'a': {'members': [actor]}}}
        self.assertEqual(len(end_turn(state)), 1)
        self.assertEqual(end_turn(state), [])
        self.assertEqual(cost(actor, 42, 3, 2), 2)


if __name__ == '__main__':
    unittest.main()
