"""User-confirmed lifecycle boundaries, not a whole-engine calibration claim."""
from copy import deepcopy
import unittest

from lab import core_magic_runtime as magic
from tests.test_core_magic_additions import CoreMagicAdditionTests


class UserConfirmedCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        CoreMagicAdditionTests.setUpClass()
        cls.catalog = CoreMagicAdditionTests.catalog

    def state(self, item):
        state = CoreMagicAdditionTests().state(item)
        target = state['teams']['a']['members'][1]
        target['original_configuration'] = {'form_id': target['form_id'], 'level': 60,
            'bloodline_id': 4 if item == 104002 else 19, 'nature_id': 1,
            'talent_selection': {'selected': ['hp', 'patk', 'spd'],
                                 'values': {'hp': 10, 'patk': 10, 'spd': 10}}}
        return state

    def cast(self, state, item):
        return magic.execute_core_magic(state, {'kind': 'core_magic', 'item_id': item,
            'side': 'a', 'target_slot': 1}, {'policy': magic.core_magic_policy()}, catalog=self.catalog)

    def test_wish_ordered_slot_restore_on_departure_unused_and_tplus3_cooldown(self):
        state = self.state(104002)
        before = deepcopy(state)
        original = state['teams']['a']['members'][1]['skill_slots'][:]
        cast = self.cast(state, 104002)
        self.assertEqual(cast['status'], 'applied', cast['blockers'])
        self.assertEqual(state, before)
        state = cast['state']
        target = state['teams']['a']['members'][1]
        self.assertEqual(target['skill_slots'], [7700004, *original[1:]])
        self.assertFalse(cast['events'][0]['ordinary_action_consumed'])
        self.assertFalse(magic.core_magic_available(state, 'a', self.catalog))
        state['teams']['a']['active_slot'] = 0
        magic.end_core_magic_round(state)
        self.assertEqual(target['skill_slots'], original)
        self.assertEqual(state['core_magic_runtime']['confirmed']['players']['a']['uses_remaining'], 1)
        state['teams']['a']['active_slot'] = 1
        for turn in (2, 3):
            state['turn'] = turn
            self.assertEqual(self.cast(state, 104002)['status'], 'blocked')
            magic.end_core_magic_round(state)
        state['turn'] = 4
        second = self.cast(state, 104002)
        self.assertEqual(second['status'], 'applied', second['blockers'])
        self.assertEqual(second['state']['core_magic_runtime']['confirmed']['players']['a']['uses_remaining'], 0)

    def test_wish_targets_and_ledger_tampering_fail_without_commit(self):
        state = self.state(104002)
        bad = magic.execute_core_magic(state, {'kind': 'core_magic', 'item_id': 104002,
            'side': 'a', 'target_slot': 0}, {'policy': magic.core_magic_policy()}, catalog=self.catalog)
        self.assertEqual(bad['status'], 'blocked')
        self.assertEqual(bad['state'], state)
        cast = self.cast(state, 104002)['state']
        cast['core_magic_runtime']['confirmed']['players']['a']['casts'][0]['slot_before'] = 123
        with self.assertRaisesRegex(ValueError, 'history changed'):
            magic.validate_core_magic(cast)

    def test_wish_source_ids_and_higher_damage_remain_explicit(self):
        from lab.prepared_rules import PreparedRules
        prepared = PreparedRules(self.catalog)
        self.assertIsNone(magic.reviewed_wish_skill(7700006))
        self.assertIsNone(magic.reviewed_wish_skill(7020880))
        normal = magic.reviewed_wish_program(prepared, 7700004)
        response = magic.reviewed_wish_program(prepared, 7700104)
        self.assertEqual(normal['operations'][0]['params']['kind'], 'higher')
        self.assertEqual(normal['operations'][0]['params']['power'], 80)
        self.assertEqual(response['operations'][0]['params']['power'], 200)

    def test_current_boss_mapping_never_uses_stale_parallel_arrays(self):
        from lab.prepared_rules import PreparedRules
        p = PreparedRules(self.catalog)
        target = magic._boss_target(p, {'form_id': 3005, 'boss_token_id': 10000005})
        self.assertEqual(target['id'], 5010)
        self.assertNotEqual(target['id'], 5001)
        with self.assertRaisesRegex(ValueError, 'matching leader token'):
            magic._boss_target(p, {'form_id': 3005})

    def test_evolution_uses_shared_panels_preserves_battle_fields_and_persists(self):
        from lab.prepared_rules import PreparedRules
        from lab.simulation import _estimate
        state = self.state(104007)
        target = state['teams']['a']['members'][1]
        target['form_id'] = 3001
        target['original_configuration']['form_id'] = 3001
        target.update(hp=101, max_hp=303, energy=7, statuses={'poison': 2},
                      stat_modifiers={'patk': [{'numerator': 20, 'denominator': 100}]}, cooldowns={'7020880': 3})
        before = deepcopy(target)
        result = self.cast(state, 104007)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        evolved = result['state']['teams']['a']['members'][1]
        prepared = PreparedRules(self.catalog)
        panels, _, _ = _estimate(self.catalog, before['original_configuration'], prepared._rules.form(3025))
        self.assertEqual(evolved['form_id'], 3025)
        self.assertEqual(evolved['max_hp'], panels['hp'])
        self.assertEqual(evolved['hp'], panels['hp'] * 101 // 303)
        for field in ('energy', 'statuses', 'stat_modifiers', 'cooldowns', 'skill_slots'):
            self.assertEqual(evolved[field], before[field], field)
        result['state']['teams']['a']['active_slot'] = 0
        magic.on_core_magic_departure(result['state'], 'a', evolved['member_id'])
        self.assertEqual(evolved['form_id'], 3025)
        self.assertEqual(state['teams']['a']['members'][1], before)


if __name__ == '__main__':
    unittest.main()
