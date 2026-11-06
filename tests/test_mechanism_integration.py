"""Constructed browser-to-engine integration cases, not live-game calibration."""
from copy import deepcopy
import unittest

from lab.server import load_catalog
from lab.simulation import DEFAULT_SETTINGS, simulation_request


class MechanismIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.normal_form = next(row['id'] for row in cls.catalog['forms'] if row['types'] == ['普通系'])

    def call(self, operation, **payload):
        return simulation_request('/api/simulation/' + operation,
            {'settings': {**DEFAULT_SETTINGS, 'source_mode': 'bwiki_only'}, **payload}, self.catalog)

    def prepare(self, a, b=None, count=2, bform=None):
        teams = {side: [{'form_id': bform if side == 'opponent' and bform else self.normal_form, 'move_ids': moves} for _ in range(count)]
                 for side, moves in [('my', a), ('opponent', b or [7020360])]}
        state = self.call('prepare', teams=teams)['state']
        for team in state['teams'].values():
            for actor in team['members']:
                actor.update(hp=10000, max_hp=10000)
        return state

    @staticmethod
    def actor(state, side='a'):
        team = state['teams'][side]
        return team['members'][team['active_slot']]

    def act(self, state, a=None, b=None, expected='applied'):
        result = self.call('act', state=state, actions={
            'a': a or {'kind': 'recharge'}, 'b': b or {'kind': 'recharge'}})
        self.assertEqual(result['status'], expected, result['blockers'])
        return result

    @staticmethod
    def skill(slot=0, **options):
        return {'kind': 'skill', 'slot': slot, **options}

    def test_defense_mitigates_before_hp_clip_and_shared_cooldown(self):
        state = self.prepare([7020780, 7020790], [7020360])
        out = self.act(state, self.skill(priority=10), self.skill())
        trace = out['damage_traces'][0]
        mitigation = trace['defense_mitigation']
        self.assertEqual(mitigation['damage'], mitigation['raw_damage'] * 30 // 100)
        self.assertGreater(mitigation['prevented'], 0)
        self.assertEqual(self.actor(out['state'])['hp'], 10000 - trace['actual_hp_loss'])
        blocked = self.call('act', state=out['state'], actions={'a': self.skill(1), 'b': {'kind': 'recharge'}})
        self.assertEqual(blocked['status'], 'blocked')
        self.assertTrue(any('cooldown' in message.lower() for message in blocked['blockers']), blocked['blockers'])
        clipped = deepcopy(state)
        self.actor(clipped)['hp'] = 1
        lethal = self.act(clipped, self.skill(priority=10), self.skill(), expected='awaiting_replacement')
        self.assertGreater(lethal['damage_traces'][0]['final_unclipped_damage'], 1)
        self.assertEqual(lethal['damage_traces'][0]['actual_hp_loss'], 1)

    def test_huilliu_response_to_defense_extends_rain_by_eight(self):
        from lab.weather_runtime import rules
        rain = next(int(mid) for mid, row in rules()['setters'].items() if row['weather'] == 'rain')
        state = self.prepare([rain, 7050530], [7020780])
        first = self.act(state, self.skill())
        before = first['state']['weather']['remaining_rounds']
        out = self.act(first['state'], self.skill(1), self.skill())
        extensions = [e for e in out['events'] if e['op'] == 'weather.extend']
        self.assertEqual(len(extensions), 1)
        self.assertEqual(extensions[0]['amount'], 8)
        self.assertEqual(out['state']['weather']['remaining_rounds'], before + 8 - 1)

    def test_drain_uses_actual_hp_loss_under_overkill(self):
        state = self.prepare([7030340])
        self.actor(state)['hp'] = 100
        self.actor(state, 'b')['hp'] = 7
        out = self.act(state, self.skill(), expected='awaiting_replacement')
        drains = [e for e in out['events'] if e['op'] == 'hp.drain']
        self.assertEqual(drains[0]['damage_basis'], 7)
        self.assertEqual(drains[0]['amount'], 7)
        self.assertEqual(self.actor(out['state'])['hp'], 107)

    def test_collision_end_turn_discount_is_used_next_turn(self):
        state = self.prepare([7020420])
        first = self.act(state, self.skill())
        changes = [e for e in first['events'] if e['op'] == 'skill.cost.modify']
        self.assertEqual(changes[0]['amount'], -1)
        self.assertIsNone(changes[0]['expires_after'])
        ready = self.act(first['state'])
        out = self.act(ready['state'], self.skill())
        pays = [e['amount'] for e in out['events'] if e['op'] == 'energy.pay' and e['actor_side'] == 'a']
        self.assertEqual(pays, [6])

    def test_heavy_hit_permanent_increase_applies_to_next_use(self):
        state = self.prepare([7020540])
        first = self.act(state, self.skill())
        self.assertEqual(self.actor(first['state'])['skill_modifiers'][0]['amount'], 1)
        out = self.act(first['state'], self.skill())
        pays = [e['amount'] for e in out['events'] if e['op'] == 'energy.pay' and e['actor_side'] == 'a']
        self.assertEqual(pays, [3])

    def test_control_after_opponent_use_costs_seven_for_three_rounds(self):
        state = self.prepare([7020720], [7020360])
        out = self.act(state, self.skill(priority=-10), self.skill())
        self.assertEqual(out['committed_actions'], ['b', 'a'])
        item = self.actor(out['state'], 'b')['skill_modifiers'][0]
        self.assertEqual((item['skill_id'], item['amount'], item['expires_after']), (7020360, 7, 3))
        # Application round counts toward the declared three-round duration.
        for turn in (2, 3):
            current = out['state']
            self.actor(current, 'b')['energy'] = 10
            out = self.act(current, b=self.skill())
            base = self.catalog['moves']['7020360']['energy']
            pays = [e['amount'] for e in out['events'] if e['op'] == 'energy.pay' and e['actor_side'] == 'b']
            self.assertEqual(pays, [base + 7])
        self.assertEqual(self.actor(out['state'], 'b')['skill_modifiers'], [])
        self.actor(out['state'], 'b')['energy'] = 10
        final = self.act(out['state'], b=self.skill())
        self.assertEqual(next(e['amount'] for e in final['events'] if e['op'] == 'energy.pay' and e['actor_side'] == 'b'), base)

    def test_stone_lock_expires_after_third_end_phase(self):
        state = self.prepare([7080150])
        out = self.act(state, self.skill())
        self.assertTrue(self.actor(out['state'], 'b')['rooted'])
        blocked = self.call('act', state=out['state'], actions={
            'a': {'kind': 'recharge'}, 'b': {'kind': 'switch', 'target_slot': 1}})
        self.assertEqual(blocked['status'], 'blocked')
        out = self.act(out['state'])
        self.assertTrue(self.actor(out['state'], 'b')['rooted'])
        out = self.act(out['state'])
        self.assertFalse(self.actor(out['state'], 'b')['rooted'])
        switched = self.act(out['state'], b={'kind': 'switch', 'target_slot': 1})
        self.assertEqual(switched['state']['teams']['b']['active_slot'], 1)

    def test_blizzard_ordinary_freeze_executes_threshold(self):
        state = self.prepare([7090110])
        self.actor(state, 'b')['hp'] = 500
        out = self.act(state, self.skill(), expected='awaiting_replacement')
        self.assertEqual(self.actor(out['state'], 'b')['statuses']['freeze'], 1)
        self.assertTrue(any(e.get('effect_op') == 'freeze.exhaust' and e.get('ordinary_stacks') == 1
                            for e in out['events']))

    def test_spore_grass_immunity_and_original_source_binding(self):
        immune = self.prepare([7030260], bform=3001)
        out = self.act(immune, self.skill())
        self.assertEqual(self.actor(out['state'], 'b')['statuses'].get('leech', 0), 0)
        state = self.prepare([7030260])
        self.actor(state)['hp'] = 100
        out = self.act(state, self.skill())
        binding = self.actor(out['state'], 'b')['status_sources']['leech']
        self.assertEqual((binding['side'], binding['member_id']), ('a', 'a:0'))
        out = self.act(out['state'], {'kind': 'switch', 'target_slot': 1})
        tick = next(e for e in out['events'] if e['op'] == 'status.tick' and e.get('status') == 'leech')
        self.assertEqual(tick['source_binding']['member_id'], 'a:0')
        self.assertGreater(tick['restored'], 0)
        self.assertEqual(out['state']['teams']['a']['members'][0]['hp'], tick['source_hp_after'])

    def test_four_knockouts_end_six_member_match_with_reserves_alive(self):
        state = self.prepare([7020360], count=6)
        for slot in range(4):
            self.actor(state, 'b')['hp'] = 1
            out = self.act(state, self.skill(), expected='finished' if slot == 3 else 'awaiting_replacement')
            self.assertEqual(out['state']['victory']['magic']['b'], 3 - slot)
            if slot != 3:
                state = self.call('replace', state=out['state'], selections={'b': slot + 1})['state']
                self.actor(state)['energy'] = 10
        self.assertEqual(out['winner'], 'a')
        self.assertEqual(out['terminal_reason'], 'trainer_magic_depleted')
        self.assertTrue(all(m['hp'] > 0 for m in out['state']['teams']['b']['members'][4:]))

    def test_borrow_generated_slot_is_executable_through_browser_request(self):
        state = self.prepare([7020840])
        # Only the teammate's carried move enters the borrow pool.
        state['teams']['a']['members'][1]['skill_slots'] = [7020360, 0, 0, 0]
        started = self.call('start', state=state)
        actor = self.actor(started['state'])
        self.assertEqual(actor['skill_slots'][0], 7020360)
        self.assertEqual(actor['dynamic_skill_origins']['0']['origin_skill_id'], 7020840)
        before = deepcopy(started['state'])
        out = self.act(started['state'], self.skill())
        self.assertEqual(started['state'], before)
        self.assertTrue(any(e['op'] == 'damage' and e.get('skill_id') == 7020360 for e in out['events']))


if __name__ == '__main__':
    unittest.main()
