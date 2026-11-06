from copy import deepcopy
import unittest

from lab import team_target_programs as teams
from lab.prepared_rules import PreparedRules
from lab.research_phases import _fragment
from lab.server import load_catalog
from lab.skill_execution import execute_skill
from tests.test_action_runtime import member


class TeamTargetProgramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = PreparedRules(load_catalog()[0])
        cls.programs = teams.programs(cls.prepared)

    def state(self):
        state = {'snapshot_id': self.prepared.snapshot_id, 'turn': 1, 'teams': {}}
        for side in ('a', 'b'):
            members = [member(side + str(i)) for i in range(4)]
            for actor in members:
                actor.update(energy=2, max_energy=10)
            members[3]['hp'] = 0
            state['teams'][side] = {'active_slot': 1, 'members': members}
        return state

    def apply(self, state, mid):
        return teams.after_skill(self.prepared, state, 'a', self.programs[mid],
                                 event_token='1:a:0', context=teams.research_context())

    def test_restore_targets_own_reserves_caps_skips_dead_and_is_idempotent(self):
        state = self.state()
        state['teams']['a']['members'][0]['energy'] = 9
        before = deepcopy(state)
        result = self.apply(state, 7030510)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual([m['energy'] for m in result['state']['teams']['a']['members']], [10, 2, 5, 2])
        self.assertEqual(result['state']['teams']['b'], before['teams']['b'])
        self.assertEqual([e['target_slot'] for e in result['events']], [0, 2])
        self.assertEqual([e['actual_amount'] for e in result['events']], [1, 3])
        self.assertTrue(all(e['source_skill_id'] == 7030510 and e['actor_member_id'] == 'a1' for e in result['events']))
        repeated = self.apply(result['state'], 7030510)
        self.assertEqual(repeated['state'], result['state'])
        self.assertEqual(repeated['events'], [])
        self.assertEqual(state, before)
        historical = self.programs[7030510]['team_target_evidence']['evidence']['historical_patch2_raw']
        self.assertEqual(historical['skill_result'][0]['result_target_type'], 5)

    def test_opponent_whole_team_loses_one_once_despite_duplicate_source_slots(self):
        state = self.state()
        state['teams']['b']['members'][0]['energy'] = 0
        before = deepcopy(state['teams']['a'])
        result = self.apply(state, 7170330)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual([m['energy'] for m in result['state']['teams']['b']['members']], [0, 1, 1, 2])
        self.assertEqual(result['state']['teams']['a'], before)
        self.assertEqual(len(result['events']), 3)
        self.assertEqual([e['actual_amount'] for e in result['events']], [0, 1, 1])
        self.assertEqual(len(self.programs[7170330]['team_target_evidence']['evidence']['current_game_raw']['skill_result']), 2)

    def test_damage_prefix_runs_once_then_team_restore_and_modified_program_rejects(self):
        state = self.state()
        actor = state['teams']['a']['members'][1]
        actor['energy'] = 10
        program = self.programs[7030560]
        context = {**_fragment(program), 'resolved_energy_cost': 3}
        relative = {'self': deepcopy(actor), 'opponent': deepcopy(state['teams']['b']['members'][1])}
        for member_state in relative.values():
            member_state['types'] = self.prepared._rules.form(member_state['form_id'])['types']
        seen = []
        prefix = execute_skill(program, relative, context,
            damage_resolver=lambda params, *_: seen.append(params['power']) or 7)
        self.assertEqual(prefix['status'], 'applied', prefix['blockers'])
        self.assertEqual(seen, [75])
        state['teams']['a']['members'][1] = prefix['state']['self']
        state['teams']['b']['members'][1] = prefix['state']['opponent']
        result = self.apply(state, 7030560)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual(result['state']['teams']['a']['members'][1]['energy'], 7)
        self.assertEqual([m['energy'] for m in result['state']['teams']['a']['members']], [3, 7, 3, 2])
        self.assertEqual(result['state']['teams']['b']['members'][1]['hp'], 293)
        modified = deepcopy(program)
        modified['team_target_components']['effect']['amount'] = 9
        rejected = teams.after_skill(self.prepared, state, 'a', modified, event_token='changed', context=teams.research_context())
        self.assertEqual(rejected['status'], 'blocked')
        self.assertEqual(rejected['state'], state)
        self.assertEqual(rejected['events'], [])
