"""User-confirmed speed order, committed departure failures and deferred return."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from lab import defense_runtime as defense, forced_switch_programs as programs, forced_switch_runtime as forced
from tests import test_action_runtime as fixtures


class OrderedDepartureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.JointActionRuntimeTests.setUpClass()
        cls.catalog = fixtures.JointActionRuntimeTests.catalog

    def setUp(self):
        fixture = fixtures.JointActionRuntimeTests()
        fixture.setUp()
        self.state = fixture.state
        self.state['teams']['b']['members'][1]['speed'] = 110
        self.context = {'defense_departure_policy': defense.DEPARTURE_POLICY,
                        'defense_end_return_policy': defense.END_RETURN_POLICY}

    def test_dual_choices_precede_effects_and_second_failure_preserves_first(self):
        original = deepcopy(self.state)
        with self.assertRaisesRegex(ValueError, 'target-owner replacement_slot for b'):
            programs.preflight_selection(self.catalog, self.state, 'a', 7150270, 0)
        with self.assertRaisesRegex(ValueError, 'target-owner replacement_slot for a'):
            programs.preflight_selection(self.catalog, self.state, 'a', 7150270, None, 0)
        selected = programs.preflight_selection(self.catalog, self.state, 'a', 7150270, 0, 0)
        self.assertEqual([s['side'] for s in selected['selections']], ['b', 'a'])
        source = programs.programs(self.catalog)[7150270]
        self.assertEqual(source['forced_switch_components']['priority_delta'], -1)
        applied = programs.after_skill(self.catalog, self.state, 'a', 7150270, replacement_slot=0,
            opponent_replacement_slot=0, event_token='dual-ok', context={})
        self.assertEqual(applied['status'], 'applied', applied['blockers'])
        self.assertEqual([applied['state']['teams'][s]['active_slot'] for s in ('a', 'b')], [0, 0])
        actual = forced.execute_forced_switch_fragment
        def fail_second(catalog, state, side, cause, **kwargs):
            if side == 'a':
                return {'status': 'blocked', 'state': deepcopy(state), 'events': [], 'blockers': ['injected second hook failure']}
            return actual(catalog, state, side, cause, **kwargs)
        with patch.object(forced, 'execute_forced_switch_fragment', side_effect=fail_second):
            partial = programs.after_skill(self.catalog, self.state, 'a', 7150270, replacement_slot=0,
                opponent_replacement_slot=0, event_token='dual-partial', context={})
        self.assertEqual(partial['status'], 'blocked')
        self.assertTrue(partial['partial_commit'])
        self.assertEqual([partial['state']['teams'][s]['active_slot'] for s in ('a', 'b')], [1, 0])
        self.assertTrue(partial['events'])
        self.assertEqual(self.state, original)
        windless = defense.defense_programs(self.catalog)[7150420]
        self.assertIsNone(defense.preflight_departure(self.catalog, self.state, 'a', windless, opponent_kind='status'))
        with self.assertRaisesRegex(ValueError, 'replacement_slot for b'):
            defense.preflight_departure(self.catalog, self.state, 'a', windless, opponent_kind='physical', replacement_slot=0)
        response = defense.after_defense(self.catalog, self.state, 'a', windless, opponent_kind='physical',
            replacement_slot=0, opponent_replacement_slot=0, event_token='windless', context=self.context)
        self.assertEqual(response['status'], 'applied', response['blockers'])
        self.assertEqual([response['state']['teams'][s]['active_slot'] for s in ('a', 'b')], [0, 0])

    def test_return_is_deferred_once_and_cancelled_for_departed_original_entry(self):
        concentrate = defense.defense_programs(self.catalog)[7110280]
        self.assertEqual(concentrate['defense_components']['reduction'], {'numerator': 80, 'denominator': 100})
        unchanged = defense.after_defense(self.catalog, self.state, 'a', concentrate, opponent_kind='status',
            event_token='no-response', context=self.context)
        self.assertFalse(unchanged['events'])
        pending = defense.after_defense(self.catalog, self.state, 'a', concentrate, opponent_kind='physical',
            event_token='concentrate', context=self.context)
        self.assertEqual(pending['state']['teams']['a']['members'][1]['entered_turn'], 1)
        applied = defense.end_round_departures(self.catalog, pending['state'], context=self.context)
        self.assertEqual(applied['status'], 'applied', applied['blockers'])
        self.assertEqual(applied['state']['teams']['a']['active_slot'], 1)
        self.assertEqual(applied['state']['teams']['a']['members'][1]['entered_turn'], 2)
        self.assertTrue(any(e['op'] == 'switch.forced' for e in applied['events']))
        again = defense.end_round_departures(self.catalog, applied['state'], context=self.context)
        self.assertEqual(again['events'], [])
        departed = deepcopy(pending['state'])
        departed['teams']['a']['active_slot'] = 0
        cancelled = defense.end_round_departures(self.catalog, departed, context=self.context)
        self.assertEqual(cancelled['status'], 'applied', cancelled['blockers'])
        self.assertFalse(any(e['op'] == 'switch.forced' for e in cancelled['events']))
        self.assertTrue(any(e['op'] == 'defense.departure_cancelled' for e in cancelled['events']))
        tampered = deepcopy(pending['state'])
        tampered['teams']['a']['members'][1]['defense_departure_pending']['source_hash'] = 'forged'
        self.assertEqual(defense.end_round_departures(self.catalog, tampered, context=self.context)['status'], 'blocked')

    def test_response_attacks_reuse_end_departure_queue(self):
        for mid,cause in ((7110390,'return'),(7150200,'emergency')):
            with self.subTest(skill=mid):
                failed=programs.after_skill(self.catalog,self.state,'a',mid,replacement_slot=None,
                    event_token='miss',context={'response_success':False})
                self.assertEqual(failed['events'],[])
                scheduled=programs.after_skill(self.catalog,self.state,'a',mid,replacement_slot=None,
                    event_token=str(mid),context={'response_success':True})
                self.assertEqual(scheduled['status'],'applied',scheduled['blockers'])
                target=scheduled['state']['teams']['b']['members'][1]
                self.assertEqual(target['defense_departure_pending']['skill_id'],mid)
                result=defense.end_round_departures(self.catalog,scheduled['state'],context={**self.context,'random_seed':0})
                self.assertEqual(result['status'],'applied',result['blockers'])
                self.assertTrue(any(e.get('cause')==cause for e in result['events']))
                self.assertEqual(defense.end_round_departures(self.catalog,result['state'],context={**self.context,'random_seed':0})['events'],[])
