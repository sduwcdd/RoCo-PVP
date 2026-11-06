from copy import deepcopy
import unittest

from lab import live_damage, trait_runtime
from lab.prepared_rules import prepare_rules
from lab.hud_damage_runtime import HUDDamageResolver
from lab.effect_runtime import execute_effects
from lab.research_phases import _fragment


class ThornsRetaliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = live_damage._rules()[0]
        cls.prepared = prepare_rules(cls.catalog)
        cls.resolver = HUDDamageResolver(cls.prepared)
        cls.forms = {f.get('trait_id'): f for f in cls.catalog['forms']}
        cls.sid = 7020480
        cls.program = cls.prepared._rules.program(cls.sid)

    def battle(self, attacker=200103):
        teams = {}
        for side, tid in [('a', attacker), ('b', 200103)]:
            form = self.forms[tid]
            member = {'member_id': side, 'form_id': form['id'], 'hp': 2000, 'max_hp': 2000,
                'energy': 10, 'max_energy': 10, 'skill_slots': [self.sid, 0, 0, 0],
                'stats': dict(patk=100, matk=100, pdef=100, mdef=100, spd=100),
                'speed': 100, 'statuses': {}, 'stat_modifiers': {}, 'charge': None,
                'rooted': False, 'entered_turn': 0, 'types': deepcopy(form['types'])}
            teams[side] = {'active_slot': 0, 'members': [member], 'marks': {'positive': None, 'negative': None}}
        world = {'snapshot_id': self.prepared.snapshot_id, 'trait_policy': trait_runtime.POLICY,
                 'turn': 1, 'teams': teams}
        trait_runtime.bind(self.prepared, world)
        return {'self': world['teams']['a']['members'][0], 'opponent': world['teams']['b']['members'][0]}

    def execute(self, state):
        context = _fragment(self.program)
        context.update(turn=1, weather=None, weather_skill_id=self.sid, actor_side='a', actor_member_id='a',
                       selected_skill_slot=0, mark_first_attack=True, mark_first_action=True,
                       resolved_energy_cost=0, faint_policy='stop_remaining_skill_on_exhaustion_experiment')
        return execute_effects(self.program, state, context, damage_resolver=self.resolver)

    def test_each_hit_uses_shared_physical_panels_without_recursive_thorns(self):
        state = self.battle()
        before = deepcopy(state)
        result = self.execute(state)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        hits = [e for e in result['events'] if e['op'] == 'damage']
        reactions = [e for e in result['events'] if e['op'] == 'trait.retaliation']
        self.assertEqual(len(hits), 3)
        self.assertEqual(len(reactions), 3)
        self.assertTrue(all(e['actor_member_id'] == 'b' and e['target_member_id'] == 'a' for e in reactions))
        self.assertTrue(all(e['damage_type'] == '无系别' and e['power'] == 50 for e in reactions))
        self.assertEqual(len({e['token'] for e in reactions}), 3)
        self.assertEqual(state, before)
        state['opponent']['stat_modifiers']['patk'] = [{'numerator': 1, 'denominator': 1}]
        boosted = self.execute(state)
        self.assertEqual(boosted['status'], 'applied', boosted['blockers'])
        extra = [e for e in boosted['events'] if e['op'] == 'trait.retaliation']
        self.assertGreater(extra[0]['damage'], reactions[0]['damage'])

    def test_fatal_owner_hit_still_retaliates_and_recipient_fatal_protection_runs(self):
        state = self.battle()
        state['self']['hp'] = 1
        result = self.execute(state)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual(result['state']['self']['hp'], 0)
        self.assertGreater(result['state']['opponent']['hp'], 0)
        self.assertEqual(len([e for e in result['events'] if e['op'] == 'damage']), 1)
        state = self.battle()
        state['self']['hp'] = state['opponent']['hp'] = 1
        result = self.execute(state)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual(result['state']['self']['hp'], 0)
        self.assertEqual(result['state']['opponent']['hp'], 0)
        self.assertEqual(len([e for e in result['events'] if e['op'] == 'trait.retaliation']), 1)
        state = self.battle(200151)
        state['self']['hp'] = state['opponent']['hp'] = 1
        result = self.execute(state)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual(result['state']['self']['hp'], 1)
        self.assertEqual(result['state']['opponent']['hp'], 0)
        self.assertTrue(any(e['op'] == 'trait.fatal_protection' and e['target'] == 'self' for e in result['events']))

    def test_real_six_member_simulation_commits_fatal_hit_retaliation_and_ko_proof(self):
        import json
        from pathlib import Path
        from lab.simulation import DEFAULT_SETTINGS, prepare_simulation, start_simulation, act_simulation
        path = Path(__file__).parent / 'fixtures/six-member-mechanism-roster.json'
        roster = json.loads(path.read_text(encoding='utf-8'))['roster']
        own, other = deepcopy(roster), deepcopy(roster)
        other[0]['form_id'] = self.forms[200103]['id']
        settings = deepcopy(DEFAULT_SETTINGS)
        prepared = prepare_simulation(self.catalog, {'settings': settings,
            'teams': {'my': own, 'opponent': other}}, prepared_rules=self.prepared)
        start = start_simulation(self.catalog, {'settings': settings, 'state': prepared['state']},
            prepared_rules=self.prepared)
        self.assertEqual(start['status'], 'ready', start.get('blockers'))
        state = start['state']
        for side in ('a', 'b'):
            self.assertEqual(len(state['teams'][side]['members']), 6)
            state['teams'][side]['members'][0]['hp'] = 1
        original = deepcopy(state)
        result = act_simulation(self.catalog, {'settings': settings, 'state': state,
            'actions': {'a': {'kind': 'skill', 'slot': 0}, 'b': {'kind': 'recharge'}}},
            prepared_rules=self.prepared, random_seed=902, diagnostics=False)
        self.assertIn(result['status'], ('applied', 'awaiting_replacement'), result.get('blockers'))
        final = result['state']
        self.assertEqual(final['teams']['a']['members'][0]['hp'], 0)
        self.assertEqual(final['teams']['b']['members'][0]['hp'], 0)
        reactions = [event for event in result['events'] if event['op'] == 'trait.retaliation']
        self.assertEqual(len(reactions), 1)
        self.assertEqual((reactions[0]['actor_member_id'], reactions[0]['target_member_id']), ('b:0', 'a:0'))
        self.assertEqual((reactions[0]['before'], reactions[0]['after'], reactions[0]['damage']), (1, 0, 1))
        proof = final['trait_defeat_provenance']['a']['a:0']
        self.assertEqual(proof['damage_event']['source_trait_id'], 200103)
        self.assertEqual(proof['damage_event']['actor_side'], 'b')
        self.assertEqual(final['victory']['knockouts']['a']['a:0'], 1)
        self.assertEqual(final['victory']['knockouts']['b']['b:0'], 1)
        self.assertEqual(state, original)




