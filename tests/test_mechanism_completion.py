"""Small cross-module checks for the continued mechanism rollout."""
from copy import deepcopy
import unittest
from lab.server import load_catalog
from lab.prepared_rules import PreparedRules
from lab.research_phases import build_research_context_v2, execute_research_turn_v2
from lab.simulation import simulation_request, DEFAULT_SETTINGS
from tests import test_action_runtime as fixtures
from tests.test_simulation import member

class MechanismCompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.prepared = PreparedRules(cls.catalog)

    def test_charged_components_run_through_two_real_turns(self):
        for sid in (7100130, 7100140, 7100170):
            with self.subTest(skill=sid):
                fixtures.JointActionRuntimeTests.setUpClass()
                f = fixtures.JointActionRuntimeTests(); f.setUp()
                state = f.state
                state['teams']['a']['members'][1]['skill_slots'][1] = sid
                actions = {'a': {'kind':'skill','slot':1,'effective_cost':0,'effective_priority':1},
                           'b': {'kind':'recharge','effective_cost':0,'effective_priority':0}}
                powers = []
                for step in (0,1):
                    actions['a']['effective_cost'] = 0 if step == 0 else self.prepared._rules.skill(sid)['energy']
                    ctx = build_research_context_v2(self.prepared, state, actions)
                    result = execute_research_turn_v2(self.prepared, state, actions, ctx,
                        damage_resolver=lambda p,*_: powers.append(p['power']) or 0,
                        status_damage_resolver=lambda *_: 0)
                    self.assertEqual(result['status'], 'applied', result['blockers'])
                    state = result['state']
                actor = state['teams']['a']['members'][1]
                self.assertIsNone(actor['charge'])
                if sid == 7100170:
                    self.assertEqual(actor['charge_flat_modifiers'][0]['amount'], 80)
                else:
                    self.assertEqual(len(powers), 1)

    def test_healing_magic_browser_api_and_round_end(self):
        settings = {**DEFAULT_SETTINGS, 'source_mode':'bwiki_only'}
        def call(action, payload):
            return simulation_request('/api/simulation/'+action, {**payload,'settings':settings}, self.catalog)
        prepared = call('prepare', {'teams':{'my':[member()], 'opponent':[member()]}})
        state = prepared['state']
        state['teams']['a']['core_magic'] = {'id':104001}
        state['teams']['a']['core_magic_experiment'] = {'target_states':'assume_absent_drill_static_mimic_experiment'}
        state['teams']['a']['members'][0].update(hp=10,max_hp=100)
        started = call('start', {'state':state})
        cast = call('magic', {'state':started['state'], 'side':'a'})
        self.assertEqual(cast['status'],'applied',cast.get('blockers'))
        self.assertEqual(cast['state']['teams']['a']['members'][0]['hp'],25)
        result = call('act', {'state':cast['state'], 'actions':{side:{'kind':'recharge'} for side in ('a','b')}})
        self.assertEqual(result['status'],'applied',result.get('blockers'))
        self.assertGreaterEqual(result['state']['teams']['a']['members'][0]['hp'],40)
        self.assertTrue(any(e['op']=='core_magic.heal' and e['phase']=='round_end' for e in result['events']))

    def test_detach_and_health_payment_reach_the_joint_turn(self):
        fixtures.JointActionRuntimeTests.setUpClass()
        for mode in ('detach','payment'):
            f=fixtures.JointActionRuntimeTests();f.setUp();state=f.state
            a=state['teams']['a']['members'][1]
            skill=7040240 if mode=='detach' else 7020360
            a['skill_slots'][1]=skill
            actions={'a':{'kind':'skill','slot':1,'effective_cost':4,'effective_priority':1,'replacement_slot':0},
                     'b':{'kind':'recharge','effective_cost':0,'effective_priority':0}}
            if mode=='payment':
                from lab.trait_runtime import POLICY
                state['trait_policy']=POLICY
                a.update(form_id=3016,energy=1,hp=300,max_hp=350)
            ctx=build_research_context_v2(self.prepared,state,actions)
            result=execute_research_turn_v2(self.prepared,state,actions,ctx,
                damage_resolver=lambda *_:0,status_damage_resolver=lambda *_:0)
            self.assertEqual(result['status'],'applied',result['blockers'])
            if mode=='detach':
                self.assertEqual(result['state']['teams']['a']['active_slot'],0)
                self.assertTrue(any(e['op']=='switch.forced' for e in result['events']))
            else:
                after=result['state']['teams']['a']['members'][1]
                self.assertEqual(after['hp'],248)
                payments=[e for e in result['events'] if e['op']=='energy.pay' and e.get('actor_side')=='a']
                self.assertEqual([e['amount'] for e in payments],[1])
                self.assertEqual(len([e for e in result['events'] if e['op']=='hp.pay']),1)

    def test_team_random_and_forced_pure_programs_execute_in_turn(self):
        fixtures.JointActionRuntimeTests.setUpClass()
        for sid in (7030510,7030560,7170330,7130200,7110370,7110270):
            with self.subTest(skill=sid):
                f=fixtures.JointActionRuntimeTests();f.setUp();state=f.state
                state['teams']['a']['members'][1]['skill_slots'][1]=sid
                state['teams']['a']['members'][0]['energy']=1
                actions={'a':{'kind':'skill','slot':1,'effective_cost':self.prepared._rules.skill(sid)['energy'],
                              'effective_priority':1,'replacement_slot':0},
                         'b':{'kind':'recharge','effective_cost':0,'effective_priority':0}}
                ctx=build_research_context_v2(self.prepared,state,actions)
                result=execute_research_turn_v2(self.prepared,state,actions,ctx,
                    damage_resolver=lambda *_:0,status_damage_resolver=lambda *_:0)
                self.assertEqual(result['status'],'applied',result['blockers'])
                if sid==7130200:
                    self.assertEqual(sum(result['state']['teams']['a']['devotion'].values()),2)
                elif sid in (7030510,7030560):
                    self.assertEqual(result['state']['teams']['a']['members'][0]['energy'],4 if sid==7030510 else 2)
                elif sid==7110270:
                    self.assertEqual(result['state']['teams']['a']['active_slot'],0)
                    self.assertEqual(result['state']['teams']['a']['members'][0]['energy'],9)

    def test_explicit_choice_reaches_joint_turn_without_default(self):
        fixtures.JointActionRuntimeTests.setUpClass()
        f=fixtures.JointActionRuntimeTests(); f.setUp(); state=f.state
        a=state['teams']['a']['members'][1]
        a['skill_slots'][1]=7030600
        a.update(hp=50,max_hp=100)
        actions={'a':{'kind':'skill','slot':1,'effective_cost':0,'effective_priority':1},
                 'b':{'kind':'recharge','effective_cost':0,'effective_priority':0}}
        with self.assertRaises(ValueError):
            build_research_context_v2(self.prepared,state,actions)
        actions['a']['choice_option']=0
        ctx=build_research_context_v2(self.prepared,state,actions)
        result=execute_research_turn_v2(self.prepared,state,actions,ctx,
            damage_resolver=lambda *_:0,status_damage_resolver=lambda *_:0)
        self.assertEqual(result['status'],'applied',result['blockers'])
        self.assertEqual(result['state']['teams']['a']['members'][1]['hp'],75)
        self.assertTrue(any(e['op']=='choice.select' and e['option']==0 for e in result['events']))

    def test_interrupt_defense_departure_and_delayed_stun_in_joint_turn(self):
        fixtures.JointActionRuntimeTests.setUpClass()
        for sid in (7020520,7080250,7040650):
            with self.subTest(skill=sid):
                f=fixtures.JointActionRuntimeTests();f.setUp();state=f.state
                state['teams']['a']['members'][1]['skill_slots'][1]=sid
                state['teams']['b']['members'][state['teams']['b']['active_slot']]['skill_slots'][0]=7020620
                actions={'a':{'kind':'skill','slot':1,'effective_cost':self.prepared._rules.skill(sid)['energy'],
                              'effective_priority':1,'replacement_slot':0},
                         'b':{'kind':'skill','slot':0,'effective_cost':0,'effective_priority':0}}
                ctx=build_research_context_v2(self.prepared,state,actions)
                result=execute_research_turn_v2(self.prepared,state,actions,ctx,
                    damage_resolver=lambda *_:0,status_damage_resolver=lambda *_:0)
                self.assertEqual(result['status'],'applied',result['blockers'])
                if sid==7020520:
                    self.assertIn('b',result['skipped_actions'])
                elif sid==7080250:
                    self.assertEqual(result['state']['teams']['a']['active_slot'],0)
                else:
                    state=result['state']
                    actions['a']['effective_cost']=100
                    ctx=build_research_context_v2(self.prepared,state,actions)
                    result=execute_research_turn_v2(self.prepared,state,actions,ctx,
                        damage_resolver=lambda *_:0,status_damage_resolver=lambda *_:0)
                    self.assertEqual(result['status'],'applied',result['blockers'])
                    self.assertIn('a',result['skipped_actions'])

    def test_cost_delta_power_uses_total_cost_and_preserves_three_hits(self):
        from lab import derived_power_runtime as runtime
        programs=runtime.programs(self.prepared)
        for mid,direction,factor in ((7021150,1,50),(7050390,-1,10),(7050480,-1,10)):
            p=programs[mid];base=self.prepared._rules.skill(mid)
            cost=base['energy']+direction
            resolved=runtime.resolve(p,{'resolved_energy_cost':0,'health_payment':{'total_cost':cost}})
            self.assertEqual(resolved['operations'][0]['params']['power'],base['power']+factor)
            if mid==7050480:self.assertEqual(resolved['operations'][0]['params']['hits'],3)
            self.assertEqual(p['operations'][0]['params']['power'],base['power'])

    def test_native_nested_status_expressions_use_common_executor(self):
        from lab.expression_programs import programs
        from lab.research_phases import _fragment, _execute_component
        from lab.action_runtime import _relative
        fixtures.JointActionRuntimeTests.setUpClass()
        f=fixtures.JointActionRuntimeTests();f.setUp()
        from lab.mark_runtime import attach_relative_marks
        state=attach_relative_marks(f.state,'a');state['opponent']['statuses']['poison']=2
        for m in state.values():m['types']=self.prepared._rules.form(m['form_id'])['types']
        program=programs(self.prepared)[7120150]
        ctx=_fragment(program);ctx.update(resolved_energy_cost=0,turn=1)
        result=_execute_component(program,state,ctx)
        self.assertEqual(result['status'],'applied',result['blockers'])
        self.assertEqual(result['state']['self']['stat_modifiers']['matk'][-1],{'numerator':60,'denominator':100})

    def test_slot_swap_and_real_charge_skip_flow(self):
        fixtures.JointActionRuntimeTests.setUpClass()
        for sid in (7070050,7100180):
            f=fixtures.JointActionRuntimeTests();f.setUp();state=f.state
            actor=state['teams']['a']['members'][1]
            actor['skill_slots']=[7020360,sid,7020370,7100130]
            before=list(actor['skill_slots'])
            actions={'a':{'kind':'skill','slot':1,'effective_cost':0,'effective_priority':1},
                     'b':{'kind':'recharge','effective_cost':0,'effective_priority':0}}
            ctx=build_research_context_v2(self.prepared,state,actions)
            result=execute_research_turn_v2(self.prepared,state,actions,ctx,
                damage_resolver=lambda *_:0,status_damage_resolver=lambda *_:0)
            self.assertEqual(result['status'],'applied',result['blockers'])
            if sid==7070050:
                self.assertEqual(result['state']['teams']['a']['members'][1]['skill_slots'],[before[2],sid,before[0],before[3]])
            else:
                state=result['state'];actions['a'].update(slot=3,effective_cost=3)
                ctx=build_research_context_v2(self.prepared,state,actions)
                result=execute_research_turn_v2(self.prepared,state,actions,ctx,
                    damage_resolver=lambda *_:1,status_damage_resolver=lambda *_:0)
                self.assertEqual(result['status'],'applied',result['blockers'])
                after=result['state']['teams']['a']['members'][1]
                self.assertIsNone(after['charge'])
                self.assertFalse(any(e['kind']=='charge_skip' for e in after.get('timed_effects',[])))
                self.assertTrue(any(e['op']=='damage' for e in result['events']))

    def test_flat_choice_and_skill_lifesteal_reach_joint_dispatch(self):
        fixtures.JointActionRuntimeTests.setUpClass()
        for sid in (7070210,7180160):
            f=fixtures.JointActionRuntimeTests();f.setUp();state=f.state
            actor=state['teams']['a']['members'][1];actor['skill_slots'][1]=sid
            actions={'a':{'kind':'skill','slot':1,'effective_cost':0,'effective_priority':1,'choice_option':0},
                     'b':{'kind':'recharge','effective_cost':0,'effective_priority':0}}
            ctx=build_research_context_v2(self.prepared,state,actions)
            result=execute_research_turn_v2(self.prepared,state,actions,ctx,
                damage_resolver=lambda *_:1,status_damage_resolver=lambda *_:0)
            self.assertEqual(result['status'],'applied',result['blockers'])
            actor=result['state']['teams']['a']['members'][1]
            if sid==7070210:
                self.assertEqual(actor['mechanism_flat_modifiers'][-1]['amount'],60)
            else:self.assertEqual(actor['skill_attack_grants'][0]['layers'],10)

    def test_complete_dark_surge_pool_is_deterministic_and_keeps_speed_flat(self):
        from lab.dark_surge_runtime import apply, research_context, modify_speed
        fixtures.JointActionRuntimeTests.setUpClass()
        f=fixtures.JointActionRuntimeTests();f.setUp()
        a=deepcopy(f.state['teams']['a']['members'][1]);b=deepcopy(a)
        ea=apply(a,5,context=research_context());eb=apply(b,5,context=research_context())
        self.assertEqual(ea,eb);self.assertEqual(a,b)
        self.assertEqual(a['dark_surge_draw_index'],25)
        self.assertEqual({e['pool_index'] for e in ea},set(range(5)))
        self.assertEqual(modify_speed(a,100),max(1,100-10*sum(e['pool_index']==4 for e in ea)))
        self.assertFalse(a['stat_modifiers'].get('spd'))

    def test_history_and_fixed_action_fields_use_joint_context(self):
        fixtures.JointActionRuntimeTests.setUpClass()
        f=fixtures.JointActionRuntimeTests();f.setUp();state=f.state
        state['teams']['a']['members'][1]['skill_slots'][1]=7020400
        actions={'a':{'kind':'skill','slot':1,'effective_cost':0,'effective_priority':1},
                 'b':{'kind':'recharge','effective_cost':0,'effective_priority':0}}
        terms=[]
        for _ in range(2):
            ctx=build_research_context_v2(self.prepared,state,actions)
            result=execute_research_turn_v2(self.prepared,state,actions,ctx,
                damage_resolver=lambda p,s,c:terms.append(c['skill_history_power']['add']) or 0,
                status_damage_resolver=lambda *_:0)
            self.assertEqual(result['status'],'applied',result['blockers']);state=result['state']
        self.assertEqual(terms,[0,45])
        from lab.action_field_runtime import fixed_cost,priority,resolve,programs
        self.assertEqual(fixed_cost(7080340,0),4)
        self.assertEqual(priority(7070340,0,0),1)
        self.assertEqual(priority(7070340,1,0),0)
        self.assertEqual(resolve(programs(self.prepared)[7090180],{'opponent_effective_cost':5})['operations'][0]['params']['amount'],2)

    def test_previous_turn_conditions_use_committed_actor_history(self):
        fixtures.JointActionRuntimeTests.setUpClass()
        f=fixtures.JointActionRuntimeTests();f.setUp();state=f.state
        actor=state['teams']['a']['members'][1]
        actor['committed_skill_history']=[]
        actor['skill_slots'][1]=7020620
        actions={'a':{'kind':'skill','slot':1,'effective_cost':1,'effective_priority':1},
                 'b':{'kind':'recharge','effective_cost':0,'effective_priority':0}}
        actions['a']['effective_cost']=self.prepared._rules.skill(7020620)['energy']
        ctx=build_research_context_v2(self.prepared,state,actions)
        first=execute_research_turn_v2(self.prepared,state,actions,ctx,damage_resolver=lambda *_:0,status_damage_resolver=lambda *_:0)
        self.assertEqual(first['status'],'applied',first['blockers'])
        state=first['state'];actor=state['teams']['a']['members'][1];actor['skill_slots'][1]=7020430
        actions['a']['effective_cost']=self.prepared._rules.skill(7020430)['energy']
        powers=[];ctx=build_research_context_v2(self.prepared,state,actions)
        second=execute_research_turn_v2(self.prepared,state,actions,ctx,damage_resolver=lambda p,*_:powers.append(p['power']) or 0,status_damage_resolver=lambda *_:0)
        self.assertEqual(second['status'],'applied',second['blockers'])
        self.assertIn(self.prepared._rules.skill(7020430)['power']+55,powers)
        from lab.action_field_runtime import programs,resolve
        from lab.action_outcome_runtime import committed_history
        history=committed_history(second['state']['teams']['a']['members'][1])
        self.assertEqual([e['kind'] for e in history],['status','physical'])
        prog=programs(self.prepared)[7020580]
        self.assertEqual(resolve(prog,{'turn':2},{'self':actor})['operations'][0]['params']['power'],self.prepared._rules.skill(7020580)['power'])

    def test_previous_team_type_is_recorded_before_member_changes(self):
        fixtures.JointActionRuntimeTests.setUpClass()
        f=fixtures.JointActionRuntimeTests();f.setUp();state=f.state
        for team in state['teams'].values():
            for m in team['members']:m['committed_skill_history']=[]
        actor=state['teams']['a']['members'][1];actor['skill_slots'][1]=7160130
        actions={'a':{'kind':'skill','slot':1,'effective_cost':self.prepared._rules.skill(7160130)['energy'],'effective_priority':1},
                 'b':{'kind':'recharge','effective_cost':0,'effective_priority':0}}
        ctx=build_research_context_v2(self.prepared,state,actions)
        first=execute_research_turn_v2(self.prepared,state,actions,ctx,damage_resolver=lambda *_:0,status_damage_resolver=lambda *_:0)
        self.assertEqual(first['status'],'applied',first['blockers'])
        state=first['state'];actor=state['teams']['a']['members'][1];actor['skill_slots'][1]=7030620;actor['energy']=actor['max_energy']
        actions['a']['effective_cost']=self.prepared._rules.skill(7030620)['energy']
        ctx=build_research_context_v2(self.prepared,state,actions)
        second=execute_research_turn_v2(self.prepared,state,actions,ctx,damage_resolver=lambda *_:0,status_damage_resolver=lambda *_:0)
        self.assertEqual(second['status'],'applied',second['blockers'])
        self.assertEqual(second['state']['teams']['a']['members'][1]['energy'],actor['max_energy'])
        for team in second['state']['teams'].values():
            for m in team['members']:
                self.assertNotIn('battle_skill_history',m)
                self.assertNotIn('trait_team_roster',m)

    def test_attack_choices_share_damage_and_explicit_conditions(self):
        from lab.choice_runtime import choice_programs,execute_choice_skill
        from lab.research_phases import _fragment
        from lab.mark_runtime import attach_relative_marks
        fixtures.JointActionRuntimeTests.setUpClass()
        programs=choice_programs(self.prepared)
        for mid in (7090450,7080460,7140340,7030580):
            with self.subTest(skill=mid):
                f=fixtures.JointActionRuntimeTests();f.setUp();relative=attach_relative_marks(f.state,'a')
                for actor in relative.values():actor['types']=self.prepared._rules.form(actor['form_id'])['types']
                relative['self']['hp']=50;relative['self']['max_hp']=100
                program=programs[mid];ctx=_fragment(program);ctx.update(turn=2,resolved_energy_cost=0,response_success=True)
                powers=[]
                result=execute_choice_skill(program,relative,ctx,option=1,damage_resolver=lambda p,*_:powers.append(p['power']) or 0)
                self.assertEqual(result['status'],'applied',result['blockers'])
                if mid==7140340:self.assertIn(self.prepared._rules.skill(mid)['power']+140,powers)
                if mid==7030580:self.assertEqual(result['state']['self']['hp'],85)
                if mid==7090450:self.assertEqual(result['state']['opponent']['mechanism_flat_modifiers'][-1]['amount'],-20)
                if mid==7080460:self.assertEqual(result['state']['self']['stat_modifiers']['mdef'][-1]['numerator'],90)

    def test_live_cost_queries_reach_simulation_damage_without_persisting_views(self):
        forms={}
        for f in self.catalog['forms']:forms.setdefault(f.get('trait_id'),f['id'])
        settings={**DEFAULT_SETTINGS,'source_mode':'bwiki_only'}
        def call(op,payload):return simulation_request('/api/simulation/'+op,{**payload,'settings':settings},self.catalog)
        prepared=call('prepare',{'teams':{'my':[member(forms[200117],[7020370,0,0,0])],
            'opponent':[member(forms[200094],[7020370,0,0,0])]}})
        started=call('start',{'state':prepared['state']})
        self.assertEqual(started['status'],'ready',started.get('blockers'))
        result=call('act',{'state':started['state'],'actions':{side:{'kind':'skill','slot':0} for side in ('a','b')}})
        self.assertEqual(result['status'],'applied',result.get('blockers'))
        for team in result['state']['teams'].values():
            for actor in team['members']:self.assertNotIn('trait_carried_costs',actor)

    def test_guard_survival_reaches_conductive_and_bound_leech(self):
        from fractions import Fraction
        from lab import defense_runtime as defense, weather_runtime as weather, status_lifecycle as lifecycle
        from tests.test_defense_runtime import member as bare
        actor=bare();actor.update(hp=2,member_id='target')
        program=defense.defense_programs(self.prepared)[7020800]
        from lab.research_phases import _fragment
        result=defense.execute_defense_skill(program,{'self':actor,'opponent':bare()},
            {**_fragment(program),'resolved_energy_cost':1},turn=1,opponent_kind='physical')
        self.assertEqual(result['status'],'applied',result['blockers'])
        protected=result['state']['self']
        events=weather.add_conductive(protected,'b',5,lambda *_:Fraction(1),turn=1)
        self.assertEqual(protected['hp'],1)
        self.assertTrue(any(e.get('op')=='defense.prevent_lethal' for e in events))
        caster=bare();caster.update(member_id='caster',hp=50)
        protected['statuses']['leech']=3
        protected['status_sources']={'leech':{'side':'a','member_id':'caster',
            'policy':lifecycle.LEECH_POLICY,'refresh_policy':lifecycle.SOURCE_REFRESH_POLICY}}
        state={'turn':1,'teams':{side:{'active_slot':0,'members':[m]} for side,m in [('a',caster),('b',protected)]}}
        tick=lifecycle.tick_leech(state,'b',policy=lifecycle.LEECH_POLICY)
        self.assertEqual((tick['actual_hp_loss'],tick['restored']),(0,0))
        state['turn']=2
        tick=lifecycle.tick_leech(state,'b',policy=lifecycle.LEECH_POLICY)
        self.assertEqual((tick['actual_hp_loss'],tick['restored']),(1,1))

    def test_conditional_devotion_uses_actual_history_and_complete_pool(self):
        from lab import random_devotion_runtime as devotion
        from lab.action_outcome_runtime import record_committed_action
        fixtures.JointActionRuntimeTests.setUpClass()
        f=fixtures.JointActionRuntimeTests();f.setUp();state=f.state
        for team in state['teams'].values():
            for m in team['members']:m['committed_skill_history']=[]
        ctx={**devotion.research_context(0),'response_success':False,'opponent_switched_this_turn':False}
        one=devotion.apply(state,'a',7130360,context=ctx)
        self.assertEqual(len(one['events']),1)
        none=devotion.apply(state,'a',7130370,context=ctx)
        self.assertEqual(len(none['events']),0)
        three=devotion.apply(state,'a',7130370,context={**ctx,'opponent_switched_this_turn':True})
        self.assertEqual(len(three['events']),3)
        actor=state['teams']['a']['members'][state['teams']['a']['active_slot']]
        action={'kind':'skill','skill_id':7080340,'actor_member_id':actor['member_id'],'slot':0,'program':self.prepared._rules.program(7080340)}
        actor['skill_slots'][0]=7080340
        record_committed_action(self.prepared,state,'a',action,[],event_token='earth-observed',response_success=False)
        state['turn']+=1
        four=devotion.apply(state,'a',7130360,context=ctx)
        self.assertEqual(len(four['events']),4)
        self.assertEqual(four,devotion.apply(state,'a',7130360,context=ctx))

    def test_enemy_cost_power_quotes_four_slots_without_filling_unknown(self):
        from lab import action_field_runtime as fields
        program=fields.programs(self.prepared)[7090360]
        state={'opponent':{'skill_slots':[7020460,None,7020780,7020460]}}
        out=fields.resolve(program,{'opponent_effective_skill_costs':[2,None,3,2]},state)
        self.assertEqual(out['operations'][0]['params']['power'],70)
        for values in ([2,None,None,2],[0,None,0,0]):
            with self.assertRaises(ValueError):fields.resolve(program,{'opponent_effective_skill_costs':values},state)

    def test_payment_and_conditional_devotion_reach_real_turn_dispatch(self):
        fixtures.JointActionRuntimeTests.setUpClass()
        for sid in (7180300,7180330,7130320,7130360,7090360):
            with self.subTest(skill=sid):
                f=fixtures.JointActionRuntimeTests();f.setUp();state=f.state
                for team in state['teams'].values():
                    for m in team['members']:m['committed_skill_history']=[]
                actor=state['teams']['a']['members'][1];actor['skill_slots'][1]=sid
                if sid in (7180300,7180330):actor.update(energy=1,hp=100,max_hp=100)
                actions={'a':{'kind':'skill','slot':1,'effective_cost':self.prepared._rules.skill(sid)['energy'],'effective_priority':1},
                         'b':{'kind':'recharge','effective_cost':0,'effective_priority':0}}
                ctx=build_research_context_v2(self.prepared,state,actions)
                result=execute_research_turn_v2(self.prepared,state,actions,ctx,
                    damage_resolver=lambda *_:0,status_damage_resolver=lambda *_:0)
                self.assertEqual(result['status'],'applied',result['blockers'])
                if sid in (7180300,7180330):
                    payments=[e for e in result['events'] if e['op']=='hp.pay']
                    self.assertEqual(len(payments),1)
                    self.assertEqual(payments[0]['amount'],(self.prepared._rules.skill(sid)['energy']-1)*5)
                if sid==7130360:self.assertEqual(sum(result['state']['teams']['a']['devotion'].values()),1)
