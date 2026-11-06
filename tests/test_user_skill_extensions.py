from copy import deepcopy
import unittest

from lab import user_skill_extensions as extensions, transformation_runtime
from lab.hud_damage_runtime import HUDDamageResolver
from lab.prepared_rules import PreparedRules
from lab.live_damage import _rules, estimate_moves
from lab.effect_runtime import execute_effects
from lab.ruleset import canonical_hash
from tests.test_hud_damage_runtime import member
from tests.test_mark_runtime import MarkRuntimeTests
from tests.test_transformation_runtime import TransformationRuntimeTests


class UserSkillExtensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog, cls.rules = _rules()
        cls.prepared = PreparedRules(cls.catalog)

    def test_dispersion_shared_bloodline_predicate_and_one_final_multiplier(self):
        program = extensions.programs(self.prepared)[7060270]
        resolver = HUDDamageResolver(self.catalog)
        damages = []
        for blood in (4, 3, 19):
            state = {'self': member(3001, 'a:0'), 'opponent': member(3002, 'b:0')}
            for pet in state.values():
                pet.update(types=self.rules.form(pet['form_id'])['types'], max_energy=10)
            state['opponent']['bloodline_id'] = blood
            context = {**MarkRuntimeTests().context(program), 'turn': 1, 'weather': None,
                       'weather_skill_id': 7060270, 'selected_skill_slot': 0,
                       'mark_first_attack': False, 'mark_first_action': True}
            before = deepcopy(state)
            resolved = extensions.resolve_program(program, state, context)
            applied = execute_effects(resolved, state, context, damage_resolver=resolver)
            self.assertEqual(applied['status'], 'applied', applied['blockers'])
            damages.append(state['opponent']['hp'] - applied['state']['opponent']['hp'])
            self.assertEqual(state, before)
        self.assertEqual(damages[1], int(damages[0] * 1.5))
        self.assertEqual(damages[1], damages[2])
        state['opponent']['bloodline_id'] = 0
        with self.assertRaises(ValueError):
            extensions.resolve_program(program, state, context)

    def test_random_stat_composite_has_sixteen_deterministic_draws_and_clever_change(self):
        fixture = TransformationRuntimeTests()
        fixture.prepared, fixture.catalog = self.prepared, self.catalog
        fixture.programs = transformation_runtime.programs(self.prepared)
        original = fixture.state(sid=7190430, seed=7)
        first, second = deepcopy(original), deepcopy(original)
        result1, events1, *_ = fixture.execute(first)
        result2, events2, *_ = fixture.execute(second)
        self.assertEqual(result1['status'], 'applied', result1['blockers'])
        self.assertEqual(result1['events'], result2['events'])
        draws = [e for e in result1['events'] if e.get('op') == 'stat.random_gain']
        self.assertEqual(len(draws), 16)
        self.assertEqual(sum(e['applied_layers'] for e in draws), 16)
        self.assertEqual(first['teams']['a']['members'][0]['energy'], 9)
        self.assertNotEqual(first['teams']['a']['members'][0]['skill_slots'][0], 7190430)
        self.assertEqual(first['teams']['a']['members'][0]['skill_slots'], second['teams']['a']['members'][0]['skill_slots'])
        self.assertEqual(original['teams']['a']['members'][0]['stat_modifiers'], {})

    def test_random_stat_full_caps_waste_sixteen_draws_without_redraw(self):
        from lab.modifier_ledger import register_stat
        from lab.mechanism_runtime import POLICY
        fixture = TransformationRuntimeTests()
        fixture.prepared, fixture.catalog = self.prepared, self.catalog
        fixture.programs = transformation_runtime.programs(self.prepared)
        state = fixture.state(sid=7190430)
        actor = state['teams']['a']['members'][0]
        for bid, stat in ((20010010, 'patk'), (20010020, 'matk'), (20010050, 'pdef'), (20010060, 'mdef')):
            actor['stat_modifiers'][stat] = [{'numerator': 99, 'denominator': 10}]
            register_stat(actor, stat, source_kind='skill', source_id=7190430,
                          source_hash=fixture.programs[7190430]['source_hash'], buff_id=bid)
        actor['mechanism_flat_modifiers'] = [{'op': 'speed.flat', 'amount': 990, 'buff_id': 20010100,
            'policy': POLICY, 'source_skill_id': 7190430, 'source_hash': fixture.programs[7190430]['source_hash']}]
        result, *_ = fixture.execute(state)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        draws = [e for e in result['events'] if e.get('op') == 'stat.random_gain']
        self.assertEqual(len(draws), 16)
        self.assertTrue(all(e['applied_layers'] == 0 and e['wasted_layers'] == 1 for e in draws))

    def test_repeat_history_deduplicates_departures_caps_and_rejects_forgery(self):
        actor = member(3001, 'a:0')
        actor['skill_slots'][0] = 7110380
        state = {'turn': 1, 'teams': {'a': {'members': [actor]}, 'b': {'members': []}}}
        extensions.initialize_repeats(state)
        self.assertEqual(extensions.repeat_count(actor), 1)
        program = extensions.programs(self.prepared)[7110380]
        with self.assertRaisesRegex(ValueError, 'driver'):
            extensions.resolve_program(program, {'self': actor}, {})
        extensions.repeat_release(actor, turn=1, token='cast:1:0')
        for i in range(12):
            extensions.repeat_departure(actor, turn=i + 2, token=f'departure:{i}')
        self.assertEqual(extensions.repeat_count(actor), 11)
        self.assertEqual(extensions.repeat_departure(actor, turn=2, token='departure:0'), [])
        with self.assertRaisesRegex(ValueError, 'already'):
            extensions.repeat_release(actor, turn=1, token='cast:1:0')
        actor['repeat_cast_history']['departures'][0]['carried'] = False
        with self.assertRaisesRegex(ValueError, 'digest'):
            extensions.repeat_count(actor)

    def test_repeat_cast_real_turn_pays_and_hooks_each_release_then_enemy_acts(self):
        from tests.test_mark_integration import MarkIntegrationTests
        fixture = MarkIntegrationTests()
        fixture.catalog, fixture.prepared = self.catalog, self.prepared
        # The fixture's actor/member records are synthetic; execution is the actual v2 driver.
        from tests.test_action_runtime import member as actor_fixture
        fixture.state = {'turn': 1, 'snapshot_id': self.catalog['snapshot_id'], 'teams': {
            side: {'active_slot': 1, 'members': [actor_fixture(side + ':reserve', 3016),
                    actor_fixture(side + ':active')], 'marks': {'positive': None, 'negative': None}}
            for side in ('a', 'b')}}
        fixture.actions = {'a': {'kind': 'skill', 'slot': 1, 'effective_cost': 2, 'effective_priority': 1},
                           'b': {'kind': 'recharge', 'effective_cost': 0, 'effective_priority': 0}}
        actor = fixture.actor()
        actor['skill_slots'][1] = 7110380
        actor['energy'] = 5
        extensions.initialize_repeats(fixture.state)
        extensions.repeat_departure(actor, turn=1, token='history:carried-before-first:1')
        extensions.repeat_departure(actor, turn=1, token='history:carried-before-first:2')
        self.assertEqual(extensions.repeat_count(actor), 3)
        fixture.state['turn'] = 2
        fixture.actions['a'].update(effective_cost=2, effective_priority=1)
        fixture.overrides = extensions.programs(self.prepared)
        calls = []
        result = fixture.turn(lambda params, state, context: calls.append(params['power']) or 1)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual(calls, [60, 60])
        self.assertEqual(result['committed_actions'], ['a', 'a', 'b'])
        self.assertEqual(result['state']['teams']['a']['members'][1]['energy'], 1)
        payments = [e['amount'] for e in result['events'] if e.get('actor_side') == 'a' and e.get('op') == 'energy.pay']
        self.assertEqual(payments, [2, 2])
        self.assertTrue(any(e.get('op') == 'skill.repeat_stopped' and e.get('reason') == 'insufficient_energy_user_confirmed'
                            for e in result['events']))

    def test_recharge_abandons_pending_charge_only_on_successful_real_action(self):
        from tests.test_mark_integration import MarkIntegrationTests
        from tests.test_action_runtime import member as actor_fixture
        from lab.action_rules import ActionRules
        fixture = MarkIntegrationTests()
        fixture.catalog, fixture.prepared = self.catalog, self.prepared
        fixture.state = {'turn': 2, 'snapshot_id': self.catalog['snapshot_id'], 'teams': {
            side: {'active_slot': 1, 'members': [actor_fixture(side + ':reserve', 3016),
                    actor_fixture(side + ':active')], 'marks': {'positive': None, 'negative': None}}
            for side in ('a', 'b')}}
        actor = fixture.actor()
        actor['skill_slots'][1] = 7100150
        actor['charge'] = ActionRules(self.catalog).charge_state(1, 7100150, 1)
        old_charge = deepcopy(actor['charge'])
        fixture.actions = {side: {'kind': 'recharge', 'effective_cost': 0, 'effective_priority': int(side == 'a')}
                           for side in ('a', 'b')}
        fixture.overrides = {}
        result = fixture.turn()
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertIsNone(result['state']['teams']['a']['members'][1]['charge'])
        self.assertEqual(actor['charge'], old_charge)
        abandoned = [event for event in result['events'] if event.get('op') == 'charge.abandoned']
        self.assertEqual(len(abandoned), 1)
        self.assertEqual(abandoned[0]['previous_charge'], old_charge)

    def test_singularity_uses_only_complete_previous_turn_water_history(self):
        program = extensions.programs(self.prepared)[7190510]
        resolver = HUDDamageResolver(self.catalog)
        for history_turn, skill_type, expected in ((1, '水系', 4), (2, '水系', 0), (1, '火系', 0)):
            state = {'self': member(3001, 'a:0'), 'opponent': member(3002, 'b:0')}
            for pet in state.values():
                pet.update(types=self.rules.form(pet['form_id'])['types'], max_energy=10)
            history = {'turn': history_turn, 'effective_type': skill_type}
            history['hash'] = canonical_hash(history)
            state['self']['battle_skill_history'] = [history]
            context = {**MarkRuntimeTests().context(program), 'turn': 2, 'weather': None,
                       'weather_skill_id': 7190510, 'selected_skill_slot': 0,
                       'mark_first_attack': False, 'mark_first_action': True, 'resolved_energy_cost': 4}
            before = deepcopy(state)
            result = extensions.execute_conditional_mark(program, state, context, resolver)
            self.assertEqual(result['status'], 'applied', result['blockers'])
            mark = result['state']['opponent']['field_marks']['negative']
            self.assertEqual(0 if mark is None else mark['stacks'], expected)
            self.assertEqual(state, before)
        del state['self']['battle_skill_history']
        with self.assertRaisesRegex(ValueError, 'complete'):
            extensions.preflight_conditional_mark(program, state, context, resolver)

    def test_juggling_keeps_exact_source_pool_and_never_applies_own_lifesteal(self):
        fixture = TransformationRuntimeTests()
        fixture.prepared, fixture.catalog = self.prepared, self.catalog
        fixture.programs = transformation_runtime.programs(self.prepared)
        source = fixture.programs[7180430]['transformation_metadata']
        self.assertEqual(source['historical_pool']['pool_id'], 24)
        self.assertEqual(source['pool_authority'], 'historical_game_file_candidates')
        state = fixture.state(sid=7180430)
        state['teams']['a']['members'][0]['hp'] = 50
        result, events, *_ = fixture.execute(state)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual(result['state']['self']['hp'], 50)
        self.assertIn(state['teams']['a']['members'][0]['skill_slots'][0], source['pool_ids'])
        self.assertFalse(any('drain' in event.get('op', '') for event in result['events']))

    def test_diffuse_reflection_freezes_skill_identity_recasts_and_clears_on_departure(self):
        from lab.dynamic_skills import remap_member_slots
        program = extensions.programs(self.prepared)[7060140]
        actor, target = member(3001, 'a:0'), member(3002, 'b:0')
        for pet in (actor, target):
            pet.update(types=self.rules.form(pet['form_id'])['types'], max_energy=10)
        actor['skill_slots'] = [7060140, 7060200, 7060190, 7020360]
        context = {**MarkRuntimeTests().context(program), 'turn': 1, 'weather': None,
                   'random_devotion_seed': 5, 'resolved_energy_cost': 1}
        original = {'self': actor, 'opponent': target}
        first = extensions.execute_per_type_power(program, original, context)
        self.assertEqual(first['status'], 'applied')
        owned = first['state']['self']
        selected = [event for event in first['events'] if event.get('op') == 'skill.power_selected']
        self.assertEqual(len(selected), 2)
        self.assertFalse(any(event['skill_id'] == 7060140 for event in selected))
        self.assertEqual(extensions.bound_skill_power(owned, 7020360, 3, 35), 70)
        self.assertNotIn('skill_history', actor)
        permutation = [0, 2, 1, 3]
        old_slots = list(owned['skill_slots'])
        owned['skill_slots'] = [old_slots[index] for index in permutation]
        remap_member_slots(owned, permutation, turn=1, event_token='explicit:transmission')
        chosen = next(event for event in selected if event['selected_type'] == '光系')
        moved_slot = permutation.index(chosen['selected_slot'])
        self.assertEqual(extensions.bound_skill_power(owned, chosen['skill_id'], moved_slot, 100), 135)
        self.assertEqual(extensions.bound_skill_power(owned, 7030440, moved_slot, 100), 100)
        context.update(weather_skill_id=7020360, selected_skill_slot=3,
                       mark_first_attack=False, mark_first_action=False)
        case = HUDDamageResolver(self.catalog).explain({'target': 'opponent', 'kind': 'physical',
            'type': '普通系', 'power': 35}, {'self': owned, 'opponent': target}, context)
        self.assertEqual(case['hud_case']['powerRange'], [70, 70])
        context['weather_skill_id'] = 7060140
        second = extensions.execute_per_type_power(program, {'self': owned, 'opponent': target}, context)
        self.assertEqual(len(list(extensions._power_grants(second['state']['self']))), 4)
        world = {'teams': {'a': {'members': [second['state']['self']]}, 'b': {'members': [target]}}}
        extensions.clear_per_type_power(world, 'a:0')
        self.assertEqual(extensions.bound_skill_power(world['teams']['a']['members'][0], 7020360, 3, 50), 50)

    def test_first_clever_seed_uses_episode_authority_and_keeps_existing_stream(self):
        from lab.dynamic_skills import initialize_dynamic_skills
        first, second = {}, {}
        for result, seed in ((first, 7), (second, 9)):
            fixture = TransformationRuntimeTests()
            fixture.catalog = self.catalog
            state = fixture.state(sid=7180430)
            state.pop('dynamic_skills')
            state['random_devotion_rng'] = {'seed': seed}
            initialize_dynamic_skills(state, seed=transformation_runtime._authoritative_dynamic_seed(state))
            result.update(state['dynamic_skills']['prng'])
            self.assertEqual(state['dynamic_skills']['prng']['seed'], seed)
            state['random_devotion_rng']['seed'] = 999
            self.assertEqual(transformation_runtime._authoritative_dynamic_seed(state), seed)
        self.assertNotEqual(canonical_hash(first), canonical_hash(second))


if __name__ == '__main__':
    unittest.main()
