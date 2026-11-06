"""Source-bound transformations, committed action identity and rollback tests."""
from copy import deepcopy
import json
import unittest

from lab import transformation_runtime as transformation
from lab.action_runtime import _relative
from lab.dynamic_skills import cost_delta, duplicate_slots_allowed, initialize_dynamic_skills, refresh_round
from lab.prepared_rules import prepare_rules
from lab.research_phases import _fragment
from lab.server import load_catalog


def member(mid, slots):
    return {'member_id': mid, 'form_id': 1, 'skill_slots': list(slots), 'hp': 100, 'max_hp': 100,
        'energy': 10, 'max_energy': 10, 'statuses': {}, 'stat_modifiers': {}, 'charge': None,
        'types': ['普通系'], 'speed': 100, 'rooted': False, 'entered_turn': 0}


class TransformationRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.prepared = prepare_rules(cls.catalog)
        cls.programs = transformation.programs(cls.prepared)

    def state(self, sid=7150380, *, seed=0, second=0):
        state = {'turn': 1, 'snapshot_id': self.catalog['snapshot_id'], 'teams': {
            'a': {'active_slot': 0, 'members': [member('a', [sid, second, 0, 0])]},
            'b': {'active_slot': 0, 'members': [member('b', [7020410, 0, 0, 0])]}}}
        initialize_dynamic_skills(state, seed=seed)
        return state

    def action(self, state, side='a', slot=0):
        actor = state['teams'][side]['members'][0]
        sid = actor['skill_slots'][slot]
        return {'kind': 'skill', 'slot': slot, 'skill_id': sid, 'actor_member_id': actor['member_id'],
            'effective_cost': max(0, self.prepared._rules.skill(sid)['energy'] + cost_delta(actor, slot)),
            'program': deepcopy(self.programs.get(sid, self.prepared._rules.program(sid)))}

    def context(self, state, action, opposite, *, response=False):
        context = _fragment(action['program'])
        context.update(resolved_energy_cost=action['effective_cost'], turn=state['turn'],
            transformation_policies=transformation.policies(), response_success=response,
            faint_policy='stop_remaining_skill_on_exhaustion_experiment')
        context['_transformation_binding'] = transformation.before_action(
            self.prepared, state, 'a', action, opposite, context)
        return context

    def execute(self, state, *, damage=10, response=False):
        action, opposite = self.action(state), self.action(state, 'b')
        context = self.context(state, action, opposite, response=response)
        def resolver(params, relative, ctx):
            return min(damage, relative['opponent']['hp'])
        result = transformation.execute(action['program'], _relative(state, 'a'), context, resolver)
        if result['status'] == 'applied':
            for key, side in [('self', 'a'), ('opponent', 'b')]:
                state['teams'][side]['members'][0] = deepcopy(result['state'][key])
        events = transformation.after_action(self.prepared, state, 'a', action, opposite, context, result)
        return result, events, action, opposite, context

    def test_full_source_and_unpacked_pool_evidence_are_retained(self):
        program = self.programs[7150380]
        evidence = program['transformation_evidence']
        self.assertEqual(program['source_description'], '造成魔伤，3连击。巧变：翼系防御技能。')
        self.assertEqual(evidence['raw'], self.catalog['moves']['7150380'])
        self.assertEqual(evidence['unpacked_pool']['pool_id'], 14)
        self.assertEqual(len(evidence['unpacked_pool']['versions']), 3)
        self.assertEqual(program['source_hash'], self.prepared._rules.program(7150380)['source_hash'])
        self.assertEqual(program['operations'][0]['params']['hits'], 3)
        self.assertNotIn(7040680, self.programs)  # Mark cleanse/stat effects are not discarded.
        self.assertNotIn(7060260, self.programs)  # Choice and alternate damage branch remain blocked.
        changed = deepcopy(self.catalog)
        changed['moves']['7150380']['desc']['zh'] += '额外效果。'
        with self.assertRaisesRegex(ValueError, 'source.*changed'):
            transformation.programs(changed)

    def test_three_hits_generate_once_ko_still_generates_and_failed_use_does_not(self):
        for damage, count in [(10, 3), (100, 1)]:
            with self.subTest(damage=damage):
                state = self.state()
                result, events, *_ = self.execute(state, damage=damage)
                self.assertEqual(result['status'], 'applied', result['blockers'])
                self.assertEqual(len([e for e in result['events'] if e['op'] == 'damage']), count)
                self.assertEqual(len(events), 1)
                self.assertEqual(state['dynamic_skills']['prng']['counter'], 1)
                self.assertIn(events[0]['skill_id'], [7150150, 7150310, 7150420])
                self.assertEqual(events[0]['energy_delta'], -1)
        state = self.state()
        original = deepcopy(state)
        action, opposite = self.action(state), self.action(state, 'b')
        context = self.context(state, action, opposite)
        result = transformation.execute(action['program'], _relative(state, 'a'), context)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(transformation.after_action(self.prepared, state, 'a', action, opposite, context, result), [])
        self.assertEqual(state, original)

    def test_generated_supported_defense_cost_and_return_then_original_template(self):
        # Seed choice is a test fixture; runtime never searches for supported draws.
        seed = next(seed for seed in range(30) if self._draw_id(seed) == 7150150)
        state = self.state(seed=seed)
        original = deepcopy(state['dynamic_skills']['original_slots'])
        self.execute(state)
        actor = state['teams']['a']['members'][0]
        self.assertEqual(actor['skill_slots'][0], 7150150)
        self.assertEqual(cost_delta(actor, 0), -1)
        state['turn'] = 2
        refresh_round(self.catalog, state)
        result, events, *_ = self.execute(state, response=True)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual(result['state']['self']['energy'], 6)  # 3 then (2 - 1).
        self.assertEqual(events[0]['op'], 'transformation.returned')
        self.assertEqual(state['teams']['a']['members'][0]['skill_slots'][0], 7150380)
        self.assertEqual(cost_delta(state['teams']['a']['members'][0], 0), 0)
        self.assertEqual(state['dynamic_skills']['original_slots'], original)

    def _draw_id(self, seed):
        from lab.dynamic_skills import _draw
        return [7150150, 7150310, 7150420][_draw({'seed': seed, 'counter': 0}, 3)]

    def test_unsupported_candidate_is_committed_no_reroll_and_restore_replays(self):
        seed = next(seed for seed in range(30) if self._draw_id(seed) == 7150310)
        state = self.state(seed=seed)
        result, events, action, opposite, context = self.execute(state)
        self.assertEqual(events[0]['blocker_code'], 'unsupported_candidate')
        self.assertIn('7150310', events[0]['blocker'])
        self.assertEqual(state['dynamic_skills']['prng']['counter'], 1)
        saved = json.loads(json.dumps(state))
        self.assertEqual(transformation.after_action(self.prepared, state, 'a', action, opposite, context, result), [])
        self.assertEqual(state, saved)
        with self.assertRaisesRegex(ValueError, '7150310'):
            cost_delta(saved['teams']['a']['members'][0], 0)
        for seed in [0, 1, 15]:
            a, b = self.state(seed=seed), self.state(seed=seed)
            self.execute(a)
            self.execute(b)
            self.assertEqual(a, b)

    def test_magic_pool_keeps_unsupported_candidates_and_source_is_not_modified(self):
        catalog_before = deepcopy(self.catalog)
        state = self.state(7021220)
        result, events, *_ = self.execute(state)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        origin = state['teams']['a']['members'][0]['transformation_skill_origins']['0']
        self.assertIn(7021220, origin['pool_ids'])
        self.assertIn(7150380, origin['pool_ids'])
        self.assertEqual(self.catalog, catalog_before)
        self.assertEqual(state['dynamic_skills']['prng']['counter'], 1)

    def test_mirror_response_replaces_exact_slot_and_survives_rounds(self):
        state = self.state(7060150, second=7020410)
        template = deepcopy(state['dynamic_skills']['original_slots'])
        result, events, *_ = self.execute(state, response=True)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        actor = state['teams']['a']['members'][0]
        self.assertEqual(actor['skill_slots'][:2], [7020410, 7020410])
        self.assertTrue(duplicate_slots_allowed(actor))
        self.assertEqual(cost_delta(actor, 0), 0)
        self.assertEqual(state['dynamic_skills']['prng']['counter'], 0)
        state['turn'] = 2
        refresh_round(self.catalog, state)
        self.assertEqual(state['teams']['a']['members'][0]['skill_slots'][0], 7020410)
        self.assertEqual(state['dynamic_skills']['original_slots'], template)
        state = self.state(7060150)
        _, events, *_ = self.execute(state, response=False)
        self.assertEqual(events, [])
        self.assertEqual(state['teams']['a']['members'][0]['skill_slots'][0], 7060150)

    def test_public_replacement_updates_both_sides_by_slot_and_blocks_copied_generator(self):
        state = self.state(7060150, second=7020410)
        for side in ('a', 'b'):
            transformation.replace_battle_slot(state, side, side, 2, 7020410,
                source_skill_id=7060150, source_hash=self.programs[7060150]['source_hash'])
            self.assertTrue(duplicate_slots_allowed(state['teams'][side]['members'][0]))
        transformation.replace_battle_slot(state, 'a', 'a', 0, 7020860,
            source_skill_id=7060150, source_hash=self.programs[7060150]['source_hash'])
        actor = state['teams']['a']['members'][0]
        self.assertEqual(actor['skill_slots'][0], 7020860)
        with self.assertRaisesRegex(ValueError, 'generator'):
            cost_delta(actor, 0)
        state['turn'] = 2
        refresh_round(self.catalog, state)
        self.assertEqual(state['teams']['a']['members'][0]['skill_slots'][0], 7020860)

    def test_already_committed_action_never_executes_new_replacement_skill(self):
        state = self.state(7021220)
        action, opposite = self.action(state), self.action(state, 'b')
        transformation.replace_battle_slot(state, 'a', 'a', 0, 7020410,
            source_skill_id=7060150, source_hash=self.programs[7060150]['source_hash'])
        context = self.context(state, action, opposite)
        self.assertEqual(context['_transformation_binding']['skill_id'], 7021220)
        self.assertFalse(context['_transformation_binding']['slot_matches_committed_action'])
        result = transformation.execute(action['program'], _relative(state, 'a'), context,
            lambda params, relative, ctx: 10)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        events = transformation.after_action(self.prepared, state, 'a', action, opposite, context, result)
        self.assertEqual(events[0]['op'], 'transformation.locked_action_retained')
        self.assertEqual(state['teams']['a']['members'][0]['skill_slots'][0], 7020410)
        self.assertEqual(state['dynamic_skills']['prng']['counter'], 0)

    def test_json_saved_generated_state_resumes_return_without_extra_draw(self):
        seed = next(seed for seed in range(30) if self._draw_id(seed) == 7150150)
        state = self.state(seed=seed)
        self.execute(state)
        restored = json.loads(json.dumps(state))
        for current in (state, restored):
            current['turn'] = 2
            refresh_round(self.catalog, current)
            self.execute(current)
        self.assertEqual(state, restored)
        self.assertEqual(state['dynamic_skills']['prng']['counter'], 1)

    def test_generated_clever_skill_returns_without_recursively_drawing(self):
        state = self.state(7021220)
        program = self.programs[7021220]
        transformation.replace_battle_slot(state, 'a', 'a', 0, 7150380,
            source_skill_id=7021220, source_hash=program['source_hash'], kind='clever_change',
            pool_ids=program['transformation_metadata']['pool_ids'])
        result, events, *_ = self.execute(state)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual(events[0]['op'], 'transformation.returned')
        self.assertEqual(state['teams']['a']['members'][0]['skill_slots'][0], 7021220)
        self.assertEqual(state['dynamic_skills']['prng']['counter'], 0)

    def test_clever_temporary_return_preserves_prior_persistent_copy_origin(self):
        state = self.state(7060150)
        mirror = self.programs[7060150]
        transformation.replace_battle_slot(state, 'a', 'a', 0, 7150380,
            source_skill_id=7060150, source_hash=mirror['source_hash'])
        previous = deepcopy(state['teams']['a']['members'][0]['transformation_skill_origins']['0'])
        seed = next(seed for seed in range(30) if self._draw_id(seed) == 7150150)
        state['dynamic_skills']['prng']['seed'] = seed
        self.execute(state)
        state['turn'] = 2
        refresh_round(self.catalog, state)
        self.execute(state)
        actor = state['teams']['a']['members'][0]
        self.assertEqual(actor['skill_slots'][0], 7150380)
        self.assertEqual(actor['transformation_skill_origins']['0'], previous)
        self.assertEqual(state['dynamic_skills']['original_slots']['a'][0], 7060150)

    def test_borrowed_clever_slot_is_held_then_restores_its_generator_provenance(self):
        from lab.dynamic_skills import _draw
        def second_draw(seed):
            prng = {'seed': seed, 'counter': 0}
            _draw(prng, 1)
            return [7150150, 7150310, 7150420][_draw(prng, 3)]
        seed = next(seed for seed in range(30) if second_draw(seed) == 7150150)
        state = self.state(7020840, seed=seed)
        state['teams']['a']['members'].append(member('reserve', [7150380, 0, 0, 0]))
        # A complete roster is fixed before initialising the PRNG originals.
        state.pop('dynamic_skills')
        initialize_dynamic_skills(state, seed=seed)
        refresh_round(self.catalog, state)
        dynamic = deepcopy(state['teams']['a']['members'][0]['dynamic_skill_origins']['0'])
        self.execute(state)
        state['turn'] = 2
        refresh_round(self.catalog, state)
        self.assertEqual(state['teams']['a']['members'][0]['skill_slots'][0], 7150150)
        self.execute(state)
        actor = state['teams']['a']['members'][0]
        self.assertEqual(actor['skill_slots'][0], 7150380)
        self.assertEqual(actor['dynamic_skill_origins']['0'], dynamic)
        state['turn'] = 3
        refresh_round(self.catalog, state)
        self.assertEqual(state['teams']['a']['members'][0]['dynamic_skill_origins']['0']['origin_skill_id'], 7020840)

    def test_research_turn_pipeline_generates_then_defends_and_returns(self):
        from tests.test_action_runtime import member as phase_member
        from lab.research_phases import build_research_context_v2, execute_research_turn_v2
        state = {'snapshot_id': self.prepared.snapshot_id, 'turn': 2, 'teams': {side: {
            'active_slot': 0, 'members': [phase_member(side)],
            'marks': {'positive': None, 'negative': None}} for side in ('a', 'b')}}
        state['teams']['a']['members'][0]['skill_slots'] = [7150380, 0, 0, 0]
        state['teams']['b']['members'][0]['skill_slots'] = [7020370, 0, 0, 0]
        seed = next(seed for seed in range(30) if self._draw_id(seed) == 7150150)
        initialize_dynamic_skills(state, seed=seed)
        actions = {side: {'kind': 'skill', 'slot': 0, 'effective_cost': 3 if side == 'a' else 2,
            'effective_priority': int(side == 'a')} for side in ('a', 'b')}
        context = build_research_context_v2(self.prepared, state, actions)
        result = execute_research_turn_v2(self.prepared, state, actions, context,
            damage_resolver=lambda params, relative, ctx: min(10, relative['opponent']['hp']))
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual(len([e for e in result['events'] if e.get('source_op') == 'damage.sequence']), 3)
        self.assertEqual(result['state']['teams']['a']['members'][0]['skill_slots'][0], 7150150)
        state = result['state']
        actions['a']['effective_cost'] = 1
        context = build_research_context_v2(self.prepared, state, actions)
        result = execute_research_turn_v2(self.prepared, state, actions, context,
            damage_resolver=lambda params, relative, ctx: min(10, relative['opponent']['hp']))
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual(result['state']['teams']['a']['members'][0]['skill_slots'][0], 7150380)
        self.assertEqual(len([e for e in result['events'] if e['op'] == 'transformation.returned']), 1)
        self.assertEqual(result['state']['dynamic_skills']['prng']['counter'], 1)

    def test_tampered_components_pool_or_saved_trace_reject(self):
        for field in ['operations', 'transformation_metadata']:
            state = self.state()
            action, opposite = self.action(state), self.action(state, 'b')
            context = self.context(state, action, opposite)
            if field == 'operations':
                action['program'][field][0]['params']['hits'] = 1
            else:
                action['program'][field]['pool_ids'] = [7150150]
            result = transformation.execute(action['program'], _relative(state, 'a'), context,
                lambda *args: 1)
            self.assertEqual(result['status'], 'blocked')
        state = self.state()
        self.execute(state)
        state['teams']['a']['members'][0]['transformation_skill_origins']['0']['energy_delta'] = -10
        with self.assertRaisesRegex(ValueError, 'source-tracked'):
            cost_delta(state['teams']['a']['members'][0], 0)


if __name__ == '__main__':
    unittest.main()
