from copy import deepcopy
import unittest
from tests.test_mechanism_compositions import MechanismCompositionTests
from lab import mechanism_runtime as m
from lab.research_phases import _fragment

class SourceLayerTests(unittest.TestCase):
    setUpClass=classmethod(MechanismCompositionTests.setUpClass.__func__)
    actors=MechanismCompositionTests.actors
    run_skill=MechanismCompositionTests.run_skill

    def apply(self,mid,state,**kw):
        out=self.run_skill(mid,state,**kw)
        self.assertEqual(out['status'],'applied',(mid,out['blockers']))
        return out['state']

    def test_exact_layers_exclude_other_and_convert_to_poison(self):
        state=self.apply(7140290,self.actors())
        state=self.apply(7140140,state)
        state=self.apply(7050230,state)
        # Grant power first, then cost, so the cost token is still owned.
        state=self.apply(7020700,state)
        state=self.apply(7050230,state)
        state={'self':state['opponent'],'opponent':state['self']}
        out=self.apply(7120130,state)
        self.assertEqual(out['opponent']['statuses']['poison'],13)
        self.assertEqual(m.modify_power(out['opponent'],100),170)
        self.assertEqual(out['opponent']['stat_modifiers']['patk'],[])

    def test_stat_inversion_double_and_new_batch(self):
        state=self.apply(7140290,self.actors())
        state={'self':state['opponent'],'opponent':state['self']}
        state=self.apply(7180450,state)
        self.assertEqual(state['opponent']['stat_modifiers']['patk'][0]['numerator'],-80)
        state=self.apply(7120160,state)
        self.assertEqual(state['opponent']['stat_modifiers']['patk'][0]['numerator'],-160)
        for mid in (7040180,7140080,7140220,7140120,7090400,7120140,7140060,7110410):
            self.apply(mid,self.actors(),response=True)
        state=self.apply(7160160,self.apply(7140290,self.actors()))
        self.assertEqual(state['self']['stat_modifiers']['patk'][0]['numerator'],160)

    def test_added_compositions_per_hit_followups_and_scoped_hit_growth(self):
        for mid in (7020450,7020490,7030480,7040380,7090270,7120090,7021210,7160210,7160390,7040290,7170130,7080200,7090140,7090170,7150110):
            self.apply(mid,self.actors(),response=True)
        for mid,status,counts in [(7040230,'burn',[0,2]),(7120080,'poison',[0,1])]:
            seen=[]
            state=self.apply(mid,self.actors(),resolver=lambda p,a,c: seen.append(a['opponent']['statuses'].get(status,0)) or 1)
            self.assertEqual(seen,counts)
            self.assertEqual(state['opponent']['statuses'][status],counts[-1]*2)
        for mid,hits in [(7020510,1),(7030450,2)]:
            state=self.apply(mid,self.actors())
            self.assertEqual(m.modify_hits(state['self'],hits,mid),hits*2)
            self.assertEqual(m.modify_hits(state['self'],2,7020460),2)
        state=self.actors();state['self']['hp']=1
        state=self.apply(7030500,state)
        self.assertEqual(state['self']['hp'],17)
        state=self.apply(7030500,state)
        self.assertEqual(state['self']['hp'],41)

    def test_skill_lifesteal_layers_and_actual_energy_gain_hook(self):
        from lab import attack_grant_runtime as grants, trait_runtime
        from lab.ruleset import canonical_hash
        state=self.actors()
        program={'game_id':7180160,'source_hash':canonical_hash(self.catalog['moves']['7180160']),
                 'snapshot_id':self.prepared.snapshot_id}
        grants.install(state['self'],program,grants.research_context())
        state=self.apply(7160160,state)
        self.assertEqual(grants.validate_member(state['self'])[0]['layers'],20)
        state={'self':state['opponent'],'opponent':state['self']}
        state=self.apply(7120130,state)
        self.assertEqual(state['opponent']['statuses']['poison'],20)
        self.assertEqual(grants.validate_member(state['opponent']),[])
        state=self.actors()
        state['self'].update(hp=40,energy=10,trait_id=200083,trait_policy=trait_runtime.POLICY,
            trait_source_hash=canonical_hash(self.catalog['traits']['200083']),trait_config_hash=trait_runtime.CONFIG_HASH)
        state=self.apply(7021280,state)
        self.assertEqual(state['self']['hp'],55)

    def test_attack_order_flags_and_self_damage_target(self):
        for mid,first,expected in [(7140100,False,3),(7140100,True,2),(7150090,True,3),(7150090,False,1)]:
            program=self.programs[mid];seen=[]
            out=m.execute(program,self.actors(),{**_fragment(program),'turn':1,'resolved_energy_cost':0,
                'mark_first_attack':first,'action_is_later':not first,'opponent_kind':'physical'},lambda p,*args:seen.append(p) or 1)
            self.assertEqual(out['status'],'applied',out['blockers']);self.assertEqual(len(seen),expected)
        for response,target in [(False,'self'),(True,'opponent')]:
            seen=[]
            self.apply(7180140,self.actors(),response=response,resolver=lambda p,*args:seen.append(p['target']) or 1)
            self.assertEqual(seen,[target])

    def test_defeat_followups_use_committed_damage_and_pay_once(self):
        for mid in (7020590,7190230,7180340):
            for killed in (False,True):
                state=self.actors();state['opponent']['hp']=2
                program=self.programs[mid]
                out=m.execute(program,state,{**_fragment(program),'turn':1,'resolved_energy_cost':1,
                    'faint_policy':'stop_remaining_skill_on_exhaustion_experiment'},lambda p,a,c:a['opponent']['hp'] if killed else 0)
                self.assertEqual(out['status'],'applied',(mid,out['blockers']))
                self.assertEqual(len([e for e in out['events'] if e['op']=='energy.pay']),1)
                actor=out['state']['self']
                if mid==7020590:self.assertEqual(actor['energy'],10 if killed else 7)
                if mid==7190230:self.assertEqual(bool(actor['stat_modifiers'].get('matk')),killed)
                if mid==7180340:self.assertEqual(m.modify_hits(actor,2,mid),4 if killed else 2)

    def test_native_components_keep_next_power_until_whole_skill_finishes(self):
        from lab.rule_config import load_bundle
        from lab.skill_execution import execute_rule
        rules=load_bundle(self.catalog)['records']['skills']
        rule=deepcopy(next(r for r in rules.values() if r['components'] and r['components'][0]['effect']=='damage'))
        first=rule['components'][0]
        first['params']['power']={'expr':{'const':first['params']['power']}}
        second=deepcopy(first);second['id']='effect:1'
        rule['components']=[first,second]
        state=self.apply(7020700,self.actors())
        seen=[]
        out=execute_rule(rule,state,{**_fragment(rule['program']),'resolved_energy_cost':0,'turn':1},
            damage_resolver=lambda p,a,c: seen.append(m.modify_power(a['self'],100)) or 1)
        self.assertEqual(out['status'],'applied',out['blockers'])
        self.assertEqual(seen,[170,170])
        self.assertEqual(m.modify_power(out['state']['self'],100),100)

    def test_hp_tiers_committed_switch_and_after_use_exhaustion(self):
        for mid,hp,want in [(7020560,96,80),(7020560,95,85),(7180400,90,90),(7040460,95,150),(7170120,80,36)]:
            state=self.actors();state['opponent' if mid==7040460 else 'self']['hp']=hp
            seen=[];self.apply(mid,state,resolver=lambda p,*args:seen.append(p['power']) or 1)
            self.assertEqual(seen,[want])
        for switched in (False,True):
            p=self.programs[7021010];seen=[]
            out=m.execute(p,self.actors(),{**_fragment(p),'turn':1,'resolved_energy_cost':1,
                'opponent_switched_this_turn':switched},lambda p,*args:seen.append(p['power']) or 1)
            self.assertEqual(out['status'],'applied');self.assertEqual(seen,[180 if switched else 80])
        p=self.programs[7021060]
        out=m.execute(p,self.actors(),{**_fragment(p),'turn':1,'resolved_energy_cost':0,
            'faint_policy':'stop_remaining_skill_on_exhaustion_experiment'},lambda p,a,c:a['opponent']['hp'])
        self.assertEqual(out['status'],'applied');self.assertEqual([out['state'][s]['hp'] for s in ('self','opponent')],[0,0])
        self.assertEqual(out['events'][-1]['op'],'hp.consume_all')
        self.assertEqual(m.cost(self.actors()['self'],7180150,10,1),8)
        self.assertEqual(m.cost(self.actors()['self'],7190470,5,1,{'hp':50,'max_hp':100}),5)
        self.assertEqual(m.cost(self.actors()['self'],7190470,5,1,{'hp':49,'max_hp':100}),2)

    def test_limited_layers_then_inheritance_preserves_source_and_receipt(self):
        from lab import modifier_ledger as ledger
        from lab.ruleset import canonical_hash
        state=self.apply(7140290,self.actors())
        state={'self':state['opponent'],'opponent':state['self']}
        state=self.apply(7021070,state)
        self.assertEqual(state['opponent']['stat_modifiers']['patk'][0],{'numerator':3,'denominator':10})
        donor=state['opponent'];before=deepcopy(donor)
        plan=ledger.prepare_inheritance(donor,source_skill_id=7160270,
            source_hash=canonical_hash(self.catalog['moves']['7160270']),token='turn:1:source:inherit')
        self.assertEqual(donor,before)
        incoming=self.actors()['self'];incoming['member_id']='receiver'
        self.assertEqual(len(ledger.apply_inheritance(incoming,plan['grant'])),1)
        self.assertEqual(ledger.apply_inheritance(incoming,plan['grant']),[])
        self.assertEqual(incoming['stat_modifiers']['patk'][0],{'numerator':3,'denominator':10})
        _,bundle=ledger._split(incoming,{'buff'})
        self.assertEqual(ledger.layer_count(bundle),3)

    def test_status_count_includes_poison_mark_and_response_per_layer(self):
        state=self.actors();state['opponent']['statuses']={'poison':2,'freeze':3}
        state['opponent']['field_marks']={'positive':None,'negative':{'id':1014,'stacks':3}}
        for mid,response,want in [(7090310,False,100),(7120220,False,125),(7120220,True,275)]:
            seen=[];self.apply(mid,state,response=response,resolver=lambda p,*args:seen.append(p['power']) or 1)
            self.assertEqual(seen,[want])
        self.assertEqual(m.cost(state['self'],7120100,5,1,opponent=state['opponent']),0)
        after=self.apply(7120100,state)
        self.assertEqual(after['opponent']['statuses']['poison'],3)
        self.assertEqual(state['opponent']['statuses']['poison'],2)

    def test_typed_power_defense_tokens_and_whole_attack_attachment(self):
        from lab import defense_runtime as defense
        state=self.apply(7060240,self.actors(),response=True)
        self.assertEqual(m.modify_power(state['self'],100,{'type':'光系'}),200)
        self.assertEqual(m.modify_power(state['self'],100,{'type':'普通系'}),100)
        programs=defense.defense_programs(self.prepared)
        state=self.apply(7050230,self.actors());p=programs[7040640]
        out=defense.execute_defense_skill(p,state,{**_fragment(p),'turn':1,'resolved_energy_cost':0},turn=1,opponent_kind='physical')
        self.assertEqual(out['status'],'applied',out['blockers'])
        self.assertEqual(m.cost(out['state']['self'],7020460,4,1),4)
        self.assertEqual(m.modify_power(out['state']['self'],100),150)
        p=programs[7021110]
        out=defense.execute_defense_skill(p,self.actors(),{**_fragment(p),'turn':1,'resolved_energy_cost':1},turn=1,opponent_kind='physical')
        self.assertEqual(m.priority_bonus(out['state']['self']),1)
        self.assertEqual(len(m.consume_priority(out['state']['self'])),1)
        self.assertEqual(m.priority_bonus(out['state']['self']),0)
        p=self.programs[7120290]
        out=m.execute(p,self.actors(),{**_fragment(p),'turn':1,'resolved_energy_cost':1,'response_success':True,
            'carried_attack_skill_ids':[7020460]},lambda *args:1)
        self.assertEqual(out['status'],'applied',out['blockers'])
        state=self.apply(7020460,out['state']);self.assertEqual(state['opponent']['statuses']['poison'],6)
        state=self.apply(7020450,state);self.assertEqual(state['opponent']['statuses']['poison'],6)

    def test_departure_clears_source_rest_one_but_keeps_permanent_typed_power(self):
        from lab import modifier_ledger as ledger
        state=self.apply(7140290,self.actors());state=self.apply(7060240,state,response=True)
        actor=state['self'];self.assertTrue(ledger.depart_modifiers(actor))
        self.assertEqual(actor['stat_modifiers']['patk'],[])
        self.assertEqual(m.modify_power(actor,100,{'type':'光系'}),200)

    def test_team_roster_counts_and_explicit_current_zero_costs(self):
        state=self.actors();state['self']['trait_team_roster']={'self':[
            {'member_id':'self','hp':80,'skill_slots':[7130160,7130160,7020460,7130210]},
            {'member_id':'ally','hp':0,'skill_slots':[7130160,7020460,7130210,7020450]}],
            'opponent':[{'member_id':'enemy','hp':80},{'member_id':'fainted','hp':0}]}
        seen=[];self.apply(7180310,state,resolver=lambda p,*args:seen.append(p['power']) or 1)
        self.assertEqual(seen,[115])
        self.assertEqual(m.cost(state['self'],7180380,6,1),5)
        seen=[];self.apply(7130160,state,resolver=lambda p,*args:seen.append(p) or 1)
        self.assertEqual(len(seen),3)
        p=self.programs[7130210]
        out=m.execute(p,state,{**_fragment(p),'turn':1,'resolved_energy_cost':2,
            'carried_effective_skill_costs':[0,0,2,4]},lambda *args:1)
        self.assertEqual(out['status'],'applied',out['blockers'])
        self.assertEqual(out['state']['self']['stat_modifiers']['patk'][0]['numerator'],150)

    def test_instant_burn_keeps_layers_and_heals_trait_from_actual_loss(self):
        from lab import trait_runtime as traits
        from lab.ruleset import canonical_hash
        state=self.actors();state['self'].update(hp=40,trait_id=200152,trait_policy=traits.POLICY,
            trait_source_hash=canonical_hash(self.catalog['traits']['200152']),trait_config_hash=traits.CONFIG_HASH)
        state['opponent']['statuses']['burn']=3;state['opponent']['hp']=5
        seen=[]
        def resolver(params,actors,context):
            seen.append(params)
            return min(actors['opponent']['hp'],actors['opponent']['max_hp']*params['stacks']*2//100)
        out=self.run_skill(7040280,state,resolver=resolver)
        self.assertEqual(out['status'],'applied',out['blockers'])
        self.assertEqual(seen[0]['op'],'status.trigger');self.assertEqual(seen[0]['stacks'],6)
        self.assertEqual(out['state']['opponent']['statuses']['burn'],6)
        self.assertEqual(out['state']['opponent']['hp'],0)
        self.assertEqual(out['state']['self']['hp'],45)
        self.assertFalse(any(e['op']=='damage' for e in out['events']))

    def test_composed_choice_branches_keep_slots_marks_and_permanence(self):
        from lab import choice_runtime as choices, modifier_ledger as ledger
        programs=choices.choice_programs(self.prepared)
        def execute(mid,option,state):
            p=programs[mid]
            result=choices.execute_choice_skill(p,state,{**_fragment(p),'turn':1,'resolved_energy_cost':1,
                'response_success':True},option=option,damage_resolver=lambda *args:1)
            self.assertEqual(result['status'],'applied',result['blockers']);return result['state']
        state=self.actors()
        for member in state.values():member['field_marks']={'positive':None,'negative':{'id':1014,'stacks':3}}
        after=execute(7021190,1,state)
        self.assertEqual([after[k]['field_marks']['negative']['stacks'] for k in after],[2,2])
        state=self.actors();state['self']['skill_slots']=[7070220,7020460,7020450,7130210]
        after=execute(7070220,1,state)
        self.assertEqual(after['self']['skill_slots'],[7020460,7070220,7020450,7130210])
        for option,key,value in [(0,'hits',1),(1,'power',20)]:
            self.assertEqual(execute(7130330,option,self.actors())['self']['team_devotion'],{key:value})
        for option,power in [(0,100),(1,120)]:
            actor=execute(7150370,option,self.actors())['self'];ledger.depart_modifiers(actor)
            self.assertEqual(m.modify_power(actor,100),power)
        self.assertEqual(choices.cost(programs[7150370],0,2),1)
        self.assertEqual(choices.cost(programs[7150370],1,2),2)
        self.assertEqual(choices.cost(programs[7021190],None,3),3)

    def test_received_defense_per_hit_and_prevented_damage_receipts(self):
        from lab import defense_runtime as defense
        programs=defense.defense_programs(self.prepared)
        class Resolver:
            def explain(self,p,state,context):
                receipt=defense.mitigate_damage(10,state['opponent'],1,damage_kind='physical')
                return {'actual_hp_loss':min(state['opponent']['hp'],receipt['damage']),'defense_mitigation':receipt}
            def __call__(self,p,state,context):return self.explain(p,state,context)['actual_hp_loss']
        for mid,hp in [(7021120,36),(7020810,60)]:
            state=self.actors();state['self']['hp']=40;p=programs[mid]
            out=defense.execute_defense_skill(p,state,{**_fragment(p),'turn':1,'resolved_energy_cost':1},turn=1,opponent_kind='physical')
            self.assertEqual(out['status'],'applied',out['blockers'])
            relative={'self':out['state']['opponent'],'opponent':out['state']['self']}
            attacked=self.run_skill(7020460,relative,resolver=Resolver())
            self.assertEqual(attacked['status'],'applied',attacked['blockers'])
            actor=attacked['state']['opponent'];self.assertEqual(actor['hp'],hp)
            if mid==7021120:self.assertEqual(len(actor['stat_modifiers']['patk']),2)
            else:
                self.assertEqual(m.cost(actor,mid,5,1),7)
                blocked=self.run_skill(7020460,relative,resolver=lambda *args:0)
                self.assertEqual(blocked['status'],'blocked')

    def test_target_cooldown_and_defense_interrupt_binding(self):
        from lab import duration_runtime as duration, action_outcome_runtime as outcomes
        from tests.test_action_outcome_runtime import ActionOutcomeTests
        p=duration.programs(self.prepared)[7140160]
        out=duration.execute_duration_skill(p,self.actors(),{**_fragment(p),'turn':1,'resolved_energy_cost':1,
            'response_success':True,'opponent_declared_skill':7020780})
        self.assertEqual(out['status'],'applied',out['blockers']);actor=out['state']['opponent']
        duration.check_cooldown(actor,7020780,1)
        with self.assertRaises(ValueError):duration.check_cooldown(actor,7020780,2)
        duration.check_cooldown(actor,7140160,2);duration.check_cooldown(actor,7020780,4)
        fixture=ActionOutcomeTests();fixture.prepared=self.prepared;fixture.interrupts=outcomes.programs(self.prepared)
        for mid in (7021160,7030270):
            state,action,opposite=fixture.fixture(skill_id=mid)
            opposite['skill_id']=7020780;state['teams']['b']['members'][0]['skill_slots'][1]=7020780
            emitted=outcomes.record_committed_action(self.prepared,state,'a',action,[],event_token='defense:'+str(mid),
                opponent_action=opposite,response_success=True)
            self.assertEqual(emitted[0]['op'],'action.interrupt.scheduled')
            self.assertTrue(outcomes.consume_interrupt(state,'b',opposite)['cancelled'])

    def test_guard_survival_water_cost_and_actual_turn_used_skill_exclusion(self):
        from lab import defense_runtime as defense
        from lab.ruleset import canonical_hash
        programs=defense.defense_programs(self.prepared)
        state=self.actors();state['self']['hp']=5;p=programs[7020800]
        out=defense.execute_defense_skill(p,state,{**_fragment(p),'turn':1,'resolved_energy_cost':1},turn=1,opponent_kind='physical')
        self.assertEqual(out['status'],'applied',out['blockers'])
        actor=out['state']['self'];self.assertEqual(defense.prevent_lethal(actor,5,1)['damage'],4)
        self.assertIsNone(defense.prevent_lethal(actor,5,2)['event'])
        relative={'self':out['state']['opponent'],'opponent':actor}
        attacked=self.run_skill(7020460,relative,resolver=lambda p,s,c:min(5,s['opponent']['hp']))
        self.assertEqual(attacked['status'],'applied',attacked['blockers']);self.assertEqual(attacked['state']['opponent']['hp'],1)
        p=programs[7050280]
        out=defense.execute_defense_skill(p,self.actors(),{**_fragment(p),'turn':1,'resolved_energy_cost':1},turn=1,opponent_kind='physical')
        self.assertEqual(m.cost(out['state']['self'],7020460,3,1),1)
        state=self.actors();state['opponent']['committed_skill_history']=[]
        after=self.apply(7020660,state);member=after['opponent']
        self.assertEqual(m.cost(member,7020460,2,1),2)
        self.assertEqual(m.cost(member,7020460,2,2),5)
        row={'member_id':member['member_id'],'turn':1,'skill_id':7020460,'response_success':False,
             'effective_type':'普通系','kind':'physical','token':'actual-release'}
        row['hash']=canonical_hash(row);member['committed_skill_history'].append(row)
        self.assertEqual(m.cost(member,7020460,2,2),2)
        self.assertEqual(m.cost(member,7020450,2,2),5)
        self.assertEqual(m.cost(member,7020450,2,4),2)



    def test_mark_clear_reward_clever_clean_and_defended_attack(self):
        from lab import transformation_runtime as transforms, mark_runtime as marks
        programs=transforms.programs(self.catalog)
        for mid in (7040680,7050510,7021170):
            program=programs.get(mid,self.programs.get(mid))
            state=self.actors()
            for member in state.values():member['field_marks']={'positive':None,'negative':{'id':1014,'stacks':3}}
            if mid==7050510:
                state=self.apply(7080370,state)
                # Source-bound speed -30 contributes three actual debuff layers.
                self.assertEqual(m.cost(state['self'],mid,5,1),2)
            context={**_fragment(program),'turn':1,'resolved_energy_cost':0,
                'transformation_policies':transforms.policies(),'mark_policy':marks.POLICY,
                'opponent_defended_this_attack':False}
            execute=transforms.execute if mid in programs else m.execute
            out=execute(program,state,context,lambda *args:1)
            self.assertEqual(out['status'],'applied',out['blockers'])
            if mid==7040680:
                self.assertEqual(out['state']['self']['stat_modifiers']['patk'][0]['numerator'],150)
                from lab.modifier_ledger import buff_layer_count
                self.assertEqual(buff_layer_count(out['state']['self']),15)
            elif mid==7050510:
                self.assertEqual(m.cost(out['state']['self'],mid,5,1),5)
                self.assertEqual(out['state']['self']['field_marks'],state['self']['field_marks'])
            else:
                self.assertEqual(marks.layer_count(out['state']['opponent']),0)
                context['opponent_defended_this_attack']=True
                defended=execute(program,state,context,lambda *args:1)
                self.assertEqual(marks.layer_count(defended['state']['opponent']),3)

    def test_copy_hp_ratio_keeps_opponent_and_stale_guard_inactive(self):
        from lab import transformation_runtime as transforms, defense_runtime as defense
        program=transforms.programs(self.catalog)[7180440]
        state=self.actors();state['opponent'].update(hp=1,max_hp=1000)
        out=transforms.execute(program,state,{**_fragment(program),'turn':1,
            'resolved_energy_cost':0,'transformation_policies':transforms.policies()})
        self.assertEqual(out['status'],'applied',out['blockers'])
        self.assertEqual(out['state']['self']['hp'],1)
        self.assertEqual(out['state']['opponent'],state['opponent'])
        state['self']['defense_runtime']={'response_success':True}
        self.assertEqual(defense.received_effects(state['self'],None),[])
        state['self']['defense_runtime']['guard_turn']=1
        with self.assertRaises(ValueError):defense.received_effects(state['self'],None)

if __name__=='__main__':unittest.main()
