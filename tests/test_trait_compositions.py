from copy import deepcopy
from fractions import Fraction
import unittest
from lab import trait_runtime as traits, mechanism_runtime as mechanisms
from lab import random_devotion_runtime as devotion, attack_grant_runtime as grants
from tests.test_trait_runtime import TraitRuntimeTests


class TraitCompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TraitRuntimeTests.setUpClass()
        cls.catalog, cls.prepared, cls.forms = TraitRuntimeTests.catalog, TraitRuntimeTests.prepared, TraitRuntimeTests.forms
    member, state, actor = TraitRuntimeTests.member, TraitRuntimeTests.state, TraitRuntimeTests.actor

    def bound(self, tid, **changes):
        state=self.state(tid)
        self.actor(state).update(changes)
        traits.bind(self.prepared,state)
        return state,self.actor(state)

    def test_fixed_hits_priority_and_buff_layer_sources(self):
        state,actor=self.bound(200209)
        result=traits.fixed_hits(state)
        self.assertEqual(traits.validate_fixed_hits({'fixed_hit_count':result['count'],
            'fixed_hit_sources':result['sources'],'fixed_hit_policy':result['policy']}),2)
        state=self.state(200209,280035);traits.bind(self.prepared,state)
        with self.assertRaises(ValueError): traits.fixed_hits(state)
        state,actor=self.bound(200249)
        traits.run_event(self.prepared,state,'skill.after',side='a',payload={'response_success':True},token='priority')
        actor=self.actor(state)
        self.assertEqual(traits.priority_bonus(actor),1)
        self.assertTrue(traits.consume_priority(actor));self.assertEqual(traits.priority_bonus(actor),0)
        _,actor=self.bound(200084)
        self.assertEqual(traits.buff_extra_layers(actor,'buff',3),5)
        self.assertEqual(traits.buff_extra_layers(actor,'debuff',3),3)
        with self.assertRaises(ValueError): traits.buff_extra_layers(actor,'unknown',3)

    def test_dynamic_hit_threshold_marks_and_carried_types(self):
        _,actor=self.bound(200143,hp=150)
        self.assertEqual(traits.hit_bonus(actor),2)
        actor['hp']=151;self.assertEqual(traits.hit_bonus(actor),0)
        actor['hp']=1;self.assertEqual(traits.hit_bonus(actor),6)
        actor['hp']=200;self.assertEqual(traits.hit_bonus(actor),0)
        _,actor=self.bound(200204)
        self.assertEqual(traits.hit_bonus(actor,{'statuses':{'poison':7}}),7)
        _,actor=self.bound(200323)
        other={'field_marks':{'positive':None,'negative':{'id':1035,'stacks':3}}}
        self.assertEqual(traits.stat_terms(actor,'pdef',1,opponent=other),[{'numerator':30,'denominator':100}])
        state,actor=self.bound(200251)
        self.assertEqual(traits.modify_power(actor,{},50,opponent=self.actor(state,'b')),60)

    def test_signed_cost_change_transform_before_floor(self):
        _,actor=self.bound(200112)
        self.assertEqual(traits.cost_delta(actor,-3),-6)
        self.assertEqual(traits.cost_delta(actor,2),4)
        _,actor=self.bound(200113)
        self.assertEqual(traits.cost_delta(actor,-3),3)
        self.assertEqual(traits.cost_delta(actor,2),-2)
        with self.assertRaises(ValueError): traits.cost_delta(actor,1.5)

    def test_inflicted_status_modifiers_caps_and_no_zero_gain(self):
        from lab.modifier_ledger import apply
        state,actor=self.bound(200122)
        self.assertEqual(traits.status_extra_layers(actor,'freeze',1),3)
        self.assertEqual(traits.status_extra_layers(actor,'poison',1),1)
        state,actor=self.bound(200116)
        pair={'self':actor,'opponent':self.actor(state,'b')}
        for _ in range(12): traits.after_status_gain(pair,'opponent','freeze',1,{'turn':1})
        self.assertEqual(sum(x['amount'] for x in pair['opponent']['skill_modifiers']),10)
        self.assertEqual(traits.after_status_gain(pair,'opponent','freeze',0,{'turn':1}),[])
        state,actor=self.bound(200185)
        pair={'self':actor,'opponent':self.actor(state,'b')}
        self.assertEqual(len(traits.after_status_gain(pair,'opponent','poison',3,{'turn':1})),2)
        self.assertEqual(pair['opponent']['mechanism_flat_modifiers'][0]['amount'],-40)
        apply(pair,'modifier.dispel','opponent','debuff')
        self.assertEqual(pair['opponent']['mechanism_flat_modifiers'],[])
        self.assertFalse(pair['opponent']['stat_modifiers'].get('patk'))

    def test_freezing_entry_composite_uses_actual_status_gain_hook(self):
        state,actor=self.bound(280012)
        traits.run_event(self.prepared,state,'member.enter',side='a',token='entry')
        other=self.actor(state,'b')
        self.assertEqual(other['statuses']['freeze'],2)
        self.assertEqual(sum(m['amount'] for m in other['skill_modifiers']),1)

    def test_initial_poison_types_and_current_poison_marks(self):
        poison=next(int(k) for k,r in self.catalog['moves'].items() if r['type']=='毒系')
        for tid,expected in ((200111,1),(280022,2)):
            state,actor=self.bound(tid,skill_slots=[poison,0,0,0])
            actor['skill_slots']=[7020370,0,0,0]
            traits.run_event(self.prepared,state,'skill.after',side='a',payload={'type':'水系'},token='water')
            self.assertEqual(self.actor(state,'b')['statuses']['poison'],expected)
        state,_=self.bound(200115)
        state['teams']['b']['marks']['negative']={'id':1014,'stacks':3}
        traits.run_event(self.prepared,state,'skill.after',side='a',payload={'type':'水系'},token='water')
        self.assertEqual(self.actor(state,'b')['statuses']['poison'],6)

    def test_received_hit_and_whole_skill_mark_cadence(self):
        hits=[{'op':'damage.hit','target':'opponent','params':{'kind':'physical'},'before':100,'after':90,'damage':10},
              {'op':'damage.hit','target':'opponent','params':{'kind':'physical'},'before':90,'after':80,'damage':10}]
        for tid,mark,count in ((200324,1035,6),(200239,1019,1),(200296,3020,1)):
            state,_=self.bound(tid)
            traits.after_received_attack(self.prepared,state,'a',hits,context={},token='attack')
            self.assertEqual(state['teams']['b']['marks']['negative']['id'],mark)
            self.assertEqual(state['teams']['b']['marks']['negative']['stacks'],count)
            self.assertEqual(traits.after_received_attack(self.prepared,state,'a',hits,context={},token='attack'),[])

    def test_party_type_and_fainted_counts_are_live_queries(self):
        roster={'self':[{'member_id':'a','types':['普通系'],'hp':100},{'member_id':'bench','types':['虫系'],'hp':0}],
                'opponent':[{'member_id':'b','types':['草系'],'hp':0}]}
        for tid,amount in ((200090,50),(200140,30),(280024,60)):
            _,actor=self.bound(tid)
            actor['trait_team_roster']=deepcopy(roster)
            self.assertEqual(traits.stat_terms(actor,'patk',1),[{'numerator':amount,'denominator':100}])
            actor['trait_team_roster']['self'][1]['hp']=100
            if tid==200140:self.assertEqual(traits.stat_terms(actor,'patk',1),[])

    def test_entry_other_bug_snapshot_refreshes_without_accumulation(self):
        for tid,amount in ((200132,10),(280006,15)):
            state=self.state(tid)
            bugform=next(f for f in self.catalog['forms'] if '虫系' in f['types'])
            reserve=self.member('other',tid,form_id=bugform['id'])
            state['teams']['a']['members'].append(reserve)
            traits.run_event(self.prepared,state,'member.enter',side='a',token='entry1')
            actor=self.actor(state)
            self.assertEqual(traits.stat_terms(actor,'spd',1),[{'numerator':amount,'denominator':100}])
            traits.run_event(self.prepared,state,'member.enter',side='a',token='entry2')
            self.assertEqual(traits.stat_terms(self.actor(state),'patk',1),[{'numerator':amount,'denominator':100}])

    def test_entry_magic_conditions_use_validated_ledger_and_clear(self):
        from lab.victory_rules import initialize_victory,reconcile_knockouts
        state=self.state(200244,200245)
        state['teams']['a']['members'].extend(self.member('reserve'+str(i),200076) for i in range(3))
        traits.bind(self.prepared,state);initialize_victory(state)
        for m in state['teams']['a']['members'][1:]:m['hp']=0
        reconcile_knockouts(state)
        for side,attr in [('a','patk'),('b','pdef')]:
            traits.run_event(self.prepared,state,'member.enter',side=side,token='entry'+side)
            actor=self.actor(state,side)
            self.assertEqual(traits.stat_terms(actor,attr,1),[{'numerator':100,'denominator':100}])
            self.assertEqual(traits.stat_terms(traits.depart(actor),attr,1),[])
        missing,_=self.bound(200244)
        with self.assertRaises(ValueError):traits.run_event(self.prepared,missing,'member.enter',side='a')

    def test_order_power_and_burst_cost_use_explicit_commit_predicates(self):
        for tid,factor in ((200124,150),(280023,175)):
            _,actor=self.bound(tid)
            self.assertEqual(traits.modify_power(actor,{},100,first_attack=True),factor)
            self.assertEqual(traits.modify_power(actor,{},100,first_attack=False),100)
            with self.assertRaises(ValueError):traits.modify_power(actor,{},100)
        state,actor=self.bound(200278,mark_entry_actions=1)
        traits.run_event(self.prepared,state,'skill.after',side='a',payload={'kind':'physical','entry_first_action':True},token='first')
        self.assertEqual(self.actor(state,'b')['skill_modifiers'][0]['amount'],1)
        traits.run_event(self.prepared,state,'skill.after',side='a',payload={'kind':'physical','entry_first_action':False},token='second')
        self.assertEqual(len(self.actor(state,'b')['skill_modifiers']),1)

    def test_first_action_hits_includes_recharge_and_clears_on_departure(self):
        state,actor=self.bound(200125)
        traits.run_event(self.prepared,state,'action.after',side='a',member_id=actor['member_id'],
            payload={'kind':'recharge','first_action':True},token='recharge')
        actor=self.actor(state)
        self.assertEqual(mechanisms.modify_hits(actor,2),3)
        self.assertEqual(mechanisms.modify_hits(traits.depart(actor),2),2)

    def test_direct_defeat_random_devotion_draws_full_five_once(self):
        state,_=self.bound(200133)
        ctx=devotion.research_context(17)
        events=traits.run_event(self.prepared,state,'opponent.defeated',side='a',token='proof1',context=ctx)
        self.assertEqual(len(events),5)
        self.assertEqual(sum(state['teams']['a']['devotion'].values()),5)
        self.assertEqual(state['random_devotion_rng']['draw_index'],5)
        self.assertTrue(all(e['effect_id']==1016004 and 0 <= e['pool_index'] < 5 for e in events))
        self.assertEqual(traits.run_event(self.prepared,state,'opponent.defeated',side='a',token='proof1',context=ctx),[])

    def test_periodic_loss_heals_opposite_living_owner_and_includes_poison_mark(self):
        for tid,status in ((200152,'burn'),(200240,'poison'),(200240,'poison_mark')):
            state,actor=self.bound(tid,hp=195)
            events=traits.after_periodic_loss(state,'b',status,12)
            self.assertEqual(actor['hp'],200);self.assertEqual(events[0]['amount'],5)
            actor['hp']=0
            self.assertEqual(traits.after_periodic_loss(state,'b',status,12),[])
            self.assertEqual(actor['hp'],0)
        state,actor=self.bound(200240)
        pair={'self':self.actor(state,'b'),'opponent':actor}
        events=traits.after_periodic_loss_relative(pair,'self','poison_mark',7)
        self.assertEqual(events[0]['target'],'opponent');self.assertEqual(actor['hp'],107)

    def test_periodic_healing_is_visible_to_the_next_status_tick(self):
        from lab.status_runtime import execute_status_phase
        from lab.effect_runtime import HOOKS
        state,_=self.bound(200152)
        self.actor(state,'b')['statuses']={'burn':2,'poison':1}
        ctx={'mode':'isolated_status_phase_experiment','snapshot_id':self.prepared.snapshot_id,
            'catalog_content_hash':self.prepared.catalog_content_hash,'excluded_hooks':sorted(HOOKS),
            'unresolved_dependencies':[],'operation_order':'damage_then_decay_experiment',
            'schedule':[{'side':'b','status':'burn'},{'side':'b','status':'poison'}],
            'status_policy':{'immunity':'reject_existing_immune_status','burn_decay_rounding':'exact'}}
        seen=[]
        def resolver(descriptor,current,context):
            seen.append(self.actor(current)['hp']);return 7
        result=execute_status_phase(self.prepared,state,ctx,damage_resolver=resolver)
        self.assertEqual(result['status'],'applied',result['blockers'])
        self.assertEqual(seen,[100,107]);self.assertEqual(self.actor(result['state'])['hp'],107)

    def test_energy_attack_stats_cap_survive_departure_and_clear_only_attack(self):
        _,actor=self.bound(280031,max_energy=200,energy=102)
        self.assertEqual(traits.after_energy_gain(actor,0,{'turn':1}),[])
        traits.after_energy_gain(actor,101,{'turn':1})
        self.assertEqual(traits.validate_energy_attack_stats(actor)['layers'],99)
        self.assertEqual(traits.stat_terms(actor,'patk',1),[{'numerator':1980,'denominator':100}])
        actor=traits.depart(actor)
        self.assertEqual(traits.stat_terms(actor,'matk',1),[{'numerator':1980,'denominator':100}])
        self.assertEqual(traits.consume_energy_attack_stats(actor,False),[])
        forged=deepcopy(actor);forged['trait_energy_attack_layers']['layers']=98
        with self.assertRaises(ValueError):traits.validate_energy_attack_stats(forged)
        self.assertTrue(traits.consume_energy_attack_stats(actor,True))
        self.assertEqual(traits.stat_terms(actor,'patk',1),[])

    def test_exact_twelve_committed_energy_refill_once_and_overshoot(self):
        state,actor=self.bound(200246,energy=0,hp=35)
        traits.record_paid_energy(actor,6,1,'paid1')
        self.assertEqual(traits.record_paid_energy(actor,6,1,'paid1'),[])
        traits.record_paid_energy(actor,6,1,'paid2')
        traits.run_event(self.prepared,state,'turn.end',side='a')
        actor=self.actor(state)
        self.assertEqual((actor['hp'],actor['energy']),(200,20))
        actor.update(hp=40,energy=0);state['turn']=2
        self.assertEqual(traits.run_event(self.prepared,state,'turn.end',side='a'),[])
        self.assertEqual(actor['hp'],40)
        state,actor=self.bound(200246,energy=0,hp=35)
        traits.record_paid_energy(actor,13,1,'overshoot')
        self.assertEqual(traits.run_event(self.prepared,state,'turn.end',side='a'),[])
        self.assertEqual(self.actor(state)['hp'],35)
        with self.assertRaises(ValueError):traits.record_paid_energy(self.actor(state),12,1,'overshoot')

    def test_current_carried_cost_snapshots_require_all_occupied_slots(self):
        _,actor=self.bound(200094)
        self.assertTrue(traits.requires_cost_snapshot(actor))
        with self.assertRaises(ValueError):traits.stat_terms(actor,'pdef',1)
        actor['trait_carried_costs']=[3,None,None,None]
        self.assertEqual(traits.stat_terms(actor,'pdef',1),[{'numerator':80,'denominator':100}])
        actor['trait_carried_costs'][0]=4
        self.assertEqual(traits.stat_terms(actor,'mdef',1),[])
        state,actor=self.bound(200117)
        other=self.actor(state,'b');other['trait_carried_costs']=[6,None,None,None]
        self.assertEqual(traits.modify_power(actor,{},100,opponent=other),160)
        other['trait_carried_costs'][0]=100
        self.assertEqual(traits.modify_power(actor,{},100,opponent=other),1090)
        other['trait_carried_costs'][0]=None
        with self.assertRaises(ValueError):traits.modify_power(actor,{},100,opponent=other)

    def test_status_skill_installs_sourced_three_turn_noisy_duration(self):
        from lab import duration_runtime as duration
        state,_=self.bound(200227)
        traits.run_event(self.prepared,state,'skill.after',side='a',payload={'kind':'status'},token='status1')
        other=self.actor(state,'b')
        self.assertEqual(duration.cost(other,'physical',3,3),5)
        self.assertEqual(duration.cost(other,'physical',3,4),3)
        self.assertEqual(duration.cost(other,'status',3,1),3)
        self.assertEqual(other['timed_effects'][0]['source_trait_id'],200227)
        state['turn']=2
        traits.run_event(self.prepared,state,'skill.after',side='a',payload={'kind':'status'},token='status2')
        other=self.actor(state,'b')
        self.assertEqual(len(other['timed_effects']),1)
        self.assertEqual(duration.cost(other,'magical',3,4),5)
        self.assertEqual(duration.depart(other)['timed_effects'],[])

    def test_enemy_departure_cost_layers_cap_and_dead_leaver_forwarding(self):
        state,actor=self.bound(200216)
        self.actor(state,'b')['hp']=0
        for i in range(5):
            traits.run_event(self.prepared,state,'member.leave',side='b',member_id='b',token='depart'+str(i))
        actor=self.actor(state)
        self.assertEqual(actor['trait_modifiers']['cost'],-10)
        self.assertEqual([r['amount'] for r in actor['trait_modifier_sources']],[-3,-3,-3,-1])
        self.assertEqual(traits.modify_cost(actor,{}, {},15),5)
        self.assertEqual(traits.run_event(self.prepared,state,'member.leave',side='b',member_id='b',token='depart4'),[])
        cleared=traits.depart(actor)
        self.assertEqual(cleared['trait_modifiers'],{})
        self.assertEqual(traits.modify_cost(cleared,{}, {},15),15)

    def test_faint_occurrence_and_permanent_kill_layer_cap(self):
        state,actor=self.bound(200235,hp=0)
        self.assertTrue(traits.after_faint(self.prepared,state,'a',actor['member_id'],occurrence=1))
        self.assertEqual(len(self.actor(state,'b')['stat_modifiers']['patk']),1)
        self.assertEqual(traits.after_faint(self.prepared,state,'a',actor['member_id'],occurrence=1),[])
        state,actor=self.bound(200257)
        traits.run_event(self.prepared,state,'opponent.defeated',side='a',token='kill1')
        actor=self.actor(state)
        self.assertEqual(actor['trait_permanent_layers']['200257']['layers'],5)
        self.assertEqual(actor['stat_modifiers']['patk'],[{'numerator':50,'denominator':100}])

    def test_partial_lifesteal_removal_replays_source_history(self):
        row=grants.rules()['skills']['7180160']
        grant={'source_skill_id':7180160,'source_hash':row['record_hash'],'requested_layers':10,'added_layers':10}
        entry=grants._life_entry([grant],10)
        source=grants.rules()['reductions']['7021070']
        reduced=grants.reduce_lifesteal(entry,5,7021070,source['record_hash'])
        self.assertEqual(grants.validate_member({'skill_attack_grants':[reduced]})[0]['layers'],5)
        reduced['layers']=6
        with self.assertRaises(ValueError): grants.validate_member({'skill_attack_grants':[reduced]})

    def test_energy_overflow_payment_and_first_entry_once(self):
        from lab import payment_runtime as payment
        _,actor=self.bound(200215)
        actor['energy']=25
        self.assertTrue(traits.energy_allows_overflow(actor))
        self.assertEqual(payment.quote(self.prepared,actor,7020370,22)['paid_energy'],22)
        state,actor=self.bound(200223,hp=101)
        traits.run_event(self.prepared,state,'member.enter',side='a',token='entry1')
        self.assertEqual(self.actor(state)['hp'],51)
        state['turn']=2
        traits.run_event(self.prepared,state,'member.enter',side='a',token='entry2')
        self.assertEqual(self.actor(state)['hp'],51)

    def test_opposing_used_skill_cooldown_lifetime(self):
        from lab import duration_runtime as duration
        state=self.state(200080,200300);traits.bind(self.prepared,state)
        self.assertTrue(traits.after_opponent_skill(self.prepared,state,'a',7020370,token='skill1'))
        self.assertEqual(traits.after_opponent_skill(self.prepared,state,'a',7020370,token='skill1'),[])
        actor=self.actor(state)
        with self.assertRaises(ValueError): duration.check_cooldown(actor,7020370,2)
        duration.check_cooldown(actor,7020380,2)
        duration.check_cooldown(actor,7020370,3)
        self.assertEqual(duration.expire(actor,3)['trait_skill_cooldowns'],[])

    def test_source_queries_dynamic_stats_burst_initial_types_and_stars(self):
        _,actor=self.bound(200091,energy=7)
        self.assertEqual(traits.stat_terms(actor,'pdef',1),[{'numerator':70,'denominator':100}])
        actor['energy']=2
        self.assertEqual(traits.stat_terms(actor,'mdef',1),[{'numerator':20,'denominator':100}])
        _,actor=self.bound(200149)
        self.assertTrue(traits.stat_terms(actor,'patk',1));self.assertEqual(traits.stat_terms(actor,'patk',2),[])
        _,actor=self.bound(200098)
        self.assertEqual(traits.modify_power(actor,{'id':7130160},50),70)
        _,actor=self.bound(200164,mark_entry_actions=0)
        self.assertEqual(traits.modify_power(actor,{'kind':'magical'},50),90)
        actor['mark_entry_actions']=1
        self.assertEqual(traits.modify_power(actor,{'kind':'magical'},50),50)
        _,actor=self.bound(200167,mark_entry_actions=0)
        self.assertEqual(traits.modify_cost(actor,{}, {'type':'电系'},3),1)
        ice=next(int(k) for k,r in self.catalog['moves'].items() if r['type']=='冰系')
        _,actor=self.bound(200120,skill_slots=[ice,0,0,0])
        actor['skill_slots']=[7020370,0,0,0]
        self.assertEqual(traits.modify_power(actor,{'type':'地系'},100),110)
        _,actor=self.bound(280011)
        other={'field_marks':{'positive':None,'negative':{'id':1035,'stacks':3}}}
        self.assertEqual(traits.modify_power(actor,{'type':'火系'},100,opponent=other),160)

    def test_response_tokens_energy_gain_and_mark_events(self):
        state,actor=self.bound(200248)
        traits.run_event(self.prepared,state,'skill.after',side='a',payload={'response_success':True},token='x')
        actor=self.actor(state)
        self.assertEqual(mechanisms.cost(actor,7020370,7,1),2)
        self.assertEqual(traits.run_event(self.prepared,state,'skill.after',side='a',payload={'response_success':True},token='x'),[])
        state,actor=self.bound(200247)
        traits.run_event(self.prepared,state,'skill.after',side='a',payload={'response_success':True},token='x')
        self.assertEqual(grants.power_factor(self.actor(state)),2)
        _,actor=self.bound(200083,hp=100)
        self.assertEqual(traits.after_energy_gain(actor,3,{'turn':1})[0]['amount'],30)
        self.assertEqual(traits.after_energy_gain(actor,0,{'turn':1}),[])
        state,_=self.bound(200189)
        traits.run_event(self.prepared,state,'turn.end',side='a')
        self.assertEqual(state['teams']['b']['marks']['negative']['stacks'],2)
        state,_=self.bound(200326)
        traits.run_event(self.prepared,state,'skill.after',side='a',payload={'id':7050320},token='water')
        self.assertEqual(set(self.actor(state,'b')['stat_modifiers']),{'patk','matk','pdef','mdef'})

    def test_random_traits_share_full_pool_and_cursor_without_duplicate_events(self):
        state,_=self.bound(200136)
        ctx=devotion.research_context(3)
        events=traits.run_event(self.prepared,state,'turn.end',side='a',context=ctx)
        self.assertEqual(sum(state['teams']['a']['devotion'].values()),1)
        self.assertEqual(events[0]['effect_id'],1016005)
        self.assertEqual(state['random_devotion_rng']['draw_index'],1)
        state,_=self.bound(200138)
        hit={'op':'damage','target':'opponent','params':{'kind':'physical'},'before':100,'after':90,'damage':10}
        events=traits.after_received_attack(self.prepared,state,'a',[hit],context=ctx,token='attack')
        self.assertEqual(events[0]['effect_id'],1016035)
        self.assertIn(events[0]['selection']['raw_buff_id'],[20640010,20640020,20640030,20640040,20640050])
        self.assertEqual(traits.after_received_attack(self.prepared,state,'a',[hit],context=ctx,token='attack'),[])
        self.assertEqual(state['random_devotion_rng']['draw_index'],1)
