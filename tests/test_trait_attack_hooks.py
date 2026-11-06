from copy import deepcopy
import unittest

from lab import payment_runtime as payment
from lab import trait_attack_hooks as hooks
from lab import trait_runtime as traits
from lab.prepared_rules import PreparedRules
from lab.research_phases import _fragment
from lab.server import load_catalog
from tests.test_action_runtime import member


class TraitAttackHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = PreparedRules(load_catalog()[0])

    def fixture(self, form=3010, hp=100):
        actor = member('actor', form)
        actor.update(hp=hp, trait_policy=traits.POLICY,
                     trait_id=self.prepared._rules.form(form)['trait_id'])
        state = {'snapshot_id': self.prepared.snapshot_id, 'turn': 1, 'trait_policy': traits.POLICY,
                 'teams': {'a': {'active_slot': 0, 'members': [actor]},
                           'b': {'active_slot': 0, 'members': [member('target')]}}}
        program = self.prepared._rules.program(7020360)
        context = {**_fragment(program), **hooks.research_context(), 'turn': 1, 'skill_kind': 'magical'}
        return state, actor, program, context

    @staticmethod
    def hit(before, after):
        return {'op': 'damage', 'target': 'opponent', 'params': {'kind': 'magical', 'power': 100},
                'before': before, 'after': after, 'damage': before - after}

    def test_entry_grant_actual_hits_floor_once_and_idempotent_token(self):
        state, actor, program, context = self.fixture()
        actor['entered_turn'] = 0
        with self.assertRaisesRegex(ValueError, 'owned entered_turn'):
            hooks.on_entry(self.prepared, state, 'a')
        with self.assertRaisesRegex(ValueError, 'not granted'):
            hooks.prepare_attack(self.prepared, actor, program, context, token='1:a:0')
        self.assertEqual(len(hooks.initialize(self.prepared, state)), 1)
        self.assertEqual(state['teams']['a']['members'][0]['trait_attack_aura']['entry_turn'], 0)
        actor = state['teams']['a']['members'][0]
        self.assertEqual(hooks.initialize(self.prepared, state), [])
        actor = state['teams']['a']['members'][0]
        binding = hooks.prepare_attack(self.prepared, actor, program, context, token='1:a:0')
        events = [self.hit(300, 297), self.hit(297, 294),
                  {'op': 'mark.trigger', 'target': 'opponent', 'damage': 99}]
        state['teams']['b']['members'][0]['hp'] = 294
        healed = hooks.after_skill(self.prepared, state, 'a', program, events, binding, context=context)
        self.assertEqual(state['teams']['a']['members'][0]['hp'], 103)
        self.assertEqual(healed[0]['damage_basis'], 6)
        self.assertEqual(healed[0]['requested'], 3)
        self.assertEqual(healed[0]['hit_losses'], [3, 3])
        self.assertEqual(hooks.after_skill(self.prepared, state, 'a', program, events, binding, context=context), [])
        self.assertEqual(state['teams']['a']['members'][0]['hp'], 103)

    def test_feast_payment_crosses_half_and_exact_half_is_inactive(self):
        state, actor, program, context = self.fixture(5053, 180)
        actor['energy'] = 0
        quote = payment.quote(self.prepared, actor, program['game_id'], 1)
        context['health_payment'] = quote
        binding = hooks.prepare_attack(self.prepared, actor, program, context, token='paid:1')
        self.assertEqual(binding['hp_after_payment'], 163)
        actor['hp'] -= quote['paid_hp']
        state['teams']['b']['members'][0]['hp'] = 269
        healed = hooks.after_skill(self.prepared, state, 'a', program, [self.hit(300, 269)], binding, context=context)
        self.assertEqual(healed[0]['lifesteal_percent'], 100)
        self.assertEqual(state['teams']['a']['members'][0]['hp'], 194)
        state, actor, program, context = self.fixture(5053, 175)
        binding = hooks.prepare_attack(self.prepared, actor, program, context, token='half:1')
        self.assertEqual(binding['percent'], 0)
        self.assertEqual(hooks.after_skill(self.prepared, state, 'a', program, [self.hit(300, 290)], binding, context=context), [])
        self.assertEqual(state['teams']['a']['members'][0]['hp'], 175)

    def test_skill_overlap_is_admitted_but_devotion_stays_separate_and_overheal_is_complete(self):
        state, actor, program, context = self.fixture()
        hooks.initialize(self.prepared, state)
        actor = state['teams']['a']['members'][0]
        overlapping = deepcopy(program)
        overlapping['mechanism_components'] = [{'op': 'hp.drain', 'target': 'self', 'percent': 50}]
        self.assertEqual(hooks.prepare_attack(self.prepared, actor, overlapping, context, token='1:overlap')['percent'], 50)
        actor['team_devotion'] = {'lifesteal': 1}
        with self.assertRaisesRegex(ValueError, 'overlap'):
            hooks.prepare_attack(self.prepared, actor, program, context, token='1:devotion')
        state, actor, program, context = self.fixture(5055,hp=350)
        traits.bind(self.prepared,state)
        hooks.initialize(self.prepared,state)
        actor=state['teams']['a']['members'][0]
        binding=hooks.prepare_attack(self.prepared,actor,program,context,token='1:greed')
        state['teams']['b']['members'][0]['hp']=200
        hooks.after_skill(self.prepared,state,'a',program,[self.hit(300,200)],binding,context=context)
        self.assertEqual(traits.stat_terms(state['teams']['a']['members'][0],'patk',1),
            [{'numerator':20,'denominator':100}])

    def test_direct_skill_and_trait_percentages_heal_once_after_sum_and_keep_source_binding(self):
        from lab import mechanism_runtime as mechanisms
        program = mechanisms.programs(self.prepared)[7180120]
        state, actor, _, _ = self.fixture(hp=100)
        actor['skill_slots'][0] = 7180120
        hooks.initialize(self.prepared, state)
        actor = state['teams']['a']['members'][0]
        context = {**_fragment(program), **hooks.research_context(), 'turn': 1,
                   'resolved_energy_cost': 4, 'response_success': False}
        binding = hooks.prepare_attack(self.prepared, actor, program, context, token='combined:1')
        context['combined_lifesteal_binding'] = binding
        relative = {'self': deepcopy(actor), 'opponent': deepcopy(state['teams']['b']['members'][0])}
        for member in relative.values():
            member['types'] = self.prepared._rules.form(member['form_id'])['types']
        result = mechanisms.execute(program, relative, context, damage_resolver=lambda *args: 101)
        self.assertEqual(result['status'], 'applied', result.get('blockers'))
        self.assertEqual(result['state']['self']['hp'], 100)  # No separate skill heal.
        pending = [e for e in result['events'] if e['op'] == 'hp.drain.deferred']
        self.assertEqual(len(pending), 1)
        for target, side in (('self','a'),('opponent','b')):
            state['teams'][side]['members'][0] = result['state'][target]
        before = deepcopy(state)
        tampered = deepcopy(result['events'])
        next(e for e in tampered if e['op'] == 'hp.drain.deferred')['percent'] = 51
        with self.assertRaisesRegex(ValueError, 'source differs'):
            hooks.after_skill(self.prepared, state, 'a', program, tampered, binding, context=context)
        self.assertEqual(state, before)
        healed = hooks.after_skill(self.prepared, state, 'a', program, result['events'], binding, context=context)
        self.assertEqual(state['teams']['a']['members'][0]['hp'], 201)
        self.assertEqual(healed[0]['lifesteal_percent'], 100)
        self.assertEqual(healed[0]['requested'], 101)
        self.assertEqual(healed[0]['stacking_rule']['source'], 'user_instruction_20261030')
        self.assertEqual(hooks.after_skill(self.prepared, state, 'a', program, result['events'], binding, context=context), [])

    def test_granted_skill_buff_and_conditional_trait_share_one_pre_heal_snapshot(self):
        from lab import attack_grant_runtime as grants
        from lab.defense_runtime import defense_programs
        grant_program = defense_programs(self.prepared)[7180210]
        for form, hp, expected in ((3010,100,100),(5053,170,150),(5053,175,50)):
            state, actor, program, context = self.fixture(form,hp)
            grants.install(actor,grant_program,grants.research_context())
            hooks.initialize(self.prepared,state)
            actor=state['teams']['a']['members'][0]
            binding=hooks.prepare_attack(self.prepared,actor,program,context,token='buff:'+str(form)+':'+str(hp))
            self.assertEqual(binding['percent'],expected)
            events=hooks.after_skill(self.prepared,state,'a',program,[self.hit(300,199)],binding,context=context)
            self.assertEqual(events[0]['requested'],101*expected//100)
            self.assertEqual(state['teams']['a']['members'][0]['hp'],min(350,hp+101*expected//100))

    def test_heal_caps_and_invalid_or_duplicate_damage_rolls_back_hook(self):
        state, actor, program, context = self.fixture(hp=349)
        hooks.initialize(self.prepared, state)
        actor = state['teams']['a']['members'][0]
        binding = hooks.prepare_attack(self.prepared, actor, program, context, token='1:a:cap')
        before = deepcopy(state)
        for events in ([self.hit(300, 290), self.hit(300, 290)], [{**self.hit(300, 290), 'damage': 11}]):
            with self.assertRaises(ValueError):
                hooks.after_skill(self.prepared, state, 'a', program, events, binding, context=context)
            self.assertEqual(state, before)
        state['teams']['b']['members'][0]['hp'] = 290
        events = hooks.after_skill(self.prepared, state, 'a', program, [self.hit(300, 290)], binding, context=context)
        self.assertEqual(state['teams']['a']['members'][0]['hp'], 350)
        self.assertEqual((events[0]['requested'], events[0]['restored'], events[0]['overflow']), (5, 1, 4))
