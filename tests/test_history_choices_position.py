from copy import deepcopy
import unittest

from lab import skill_history_runtime as history, choice_runtime as choice, action_outcome_runtime as outcomes
from lab import dynamic_skills as dynamic, action_traits
from lab.power_query import quote_damage_power
from lab.prepared_rules import PreparedRules
from lab.research_phases import _fragment
from lab.server import load_catalog
from lab.skill_execution import execute_skill
from tests import test_carried_skill_history as fixtures


class HistoryChoicePositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = PreparedRules(load_catalog()[0])
        cls.programs = history.programs(cls.prepared)

    def fixture(self,slots):
        f = fixtures.CarriedSkillHistoryTests()
        f.prepared, f.programs = self.prepared,self.programs
        f.programs = {**choice.choice_programs(self.prepared), **f.programs}
        state = f.fixture(slots)
        for team in state['teams'].values():
            team['members'][0].update(energy=100,max_energy=100)
        return f,state

    def commit(self,f,state,slot,token,*,option=None,response=False,opponent_action=None):
        action=f.action(state,slot);program=action['program'];binding=history.bind_action(self.prepared,state,'a',action)
        ctx={**_fragment(program),'turn':state['turn'],'resolved_energy_cost':self.prepared._rules.skill(action['skill_id'])['energy'],
            'choice_option':option,'weather_skill_id':action['skill_id'],'response_success':response,
            'mark_first_action':False,'mark_first_attack':False,'action_is_later':False}
        ctx['choice_recoil_policy']=choice.RECOIL_POLICY
        if opponent_action:
            ctx.update(opponent_kind='status',opponent_declared_skill=opponent_action['skill_id'],
                opponent_declared_slot=opponent_action['slot'],opponent_declared_member_id=opponent_action['actor_member_id'])
        if binding:ctx['skill_history_power']=history.power_terms(state,binding)
        actors={key:deepcopy(state['teams'][side]['members'][0]) for key,side in (('self','a'),('opponent','b'))}
        for member in actors.values():member['types']=self.prepared._rules.form(member['form_id'])['types']
        powers=[]
        def resolver(params,actors,context):
            powers.append(quote_damage_power(self.prepared,params,actors,context)['power'])
            return 0
        result=(choice.execute_choice_skill(program,actors,ctx,option=option,damage_resolver=resolver)
            if 'choice_components' in program else execute_skill(program,actors,ctx,damage_resolver=resolver))
        self.assertEqual(result['status'],'applied',result['blockers'])
        for key,side in (('self','a'),('opponent','b')):state['teams'][side]['members'][0]=result['state'][key]
        outcomes.record_committed_action(self.prepared,state,'a',action,result['events'],event_token=token,response_success=response)
        history.after_skill(self.prepared,state,'a',action,binding,action_token=token,context=ctx)
        history.observe_action(self.prepared,state,'a',action,action_token=token,context=ctx)
        self.last_result,self.last_context,self.last_action=result,ctx,action
        return powers

    def test_horse_stance_strict_hp_conditions_priority_and_nonlethal_bet(self):
        from fractions import Fraction
        from lab.action_field_runtime import priority
        f,state=self.fixture([7140330,7180420,0,0])
        state['teams']['a']['members'][0]['hp']=50
        self.commit(f,state,0,'stance-low',option=0)
        self.assertEqual(state['teams']['a']['members'][0]['hp'],260)
        state['turn']=2;state['teams']['a']['members'][0]['hp']=70
        self.commit(f,state,0,'stance-boundary',option=0)
        self.assertEqual(state['teams']['a']['members'][0]['hp'],70)
        state['turn']=3;state['teams']['a']['members'][0]['hp']=300
        self.commit(f,state,0,'stance-high',option=1)
        term=state['teams']['a']['members'][0]['stat_modifiers']['patk'][0]
        self.assertEqual(Fraction(term['numerator'],term['denominator']),Fraction(3,2))
        self.assertEqual([priority(7140330,s,0) for s in range(4)],[-1]*4)
        state['turn']=4;state['teams']['a']['members'][0]['hp']=350
        self.assertEqual(self.commit(f,state,1,'bet-light',option=0),[125])
        self.assertEqual(state['teams']['a']['members'][0]['hp'],315)
        state['turn']=5;state['teams']['a']['members'][0]['hp']=100
        self.assertEqual(self.commit(f,state,1,'bet-dark',option=1),[185])
        state['teams']['a']['members'][0]['hp']=35
        actors={key:deepcopy(state['teams'][side]['members'][0]) for key,side in (('self','a'),('opponent','b'))}
        with self.assertRaisesRegex(ValueError,'lethal'):
            choice.preflight(f.programs[7180420],actors,{**self.last_context,'choice_option':0},option=0,damage_resolver=lambda *_:0)

    def test_lens_carry_type_and_exact_declared_status_slot_replacement(self):
        f,state=self.fixture([7060260,0,0,0])
        state['teams']['b']['members'][0]['skill_slots']=[7060230,0,7020620,0]
        self.assertEqual(self.commit(f,state,0,'lens-light',option=0),[165])
        state['turn']=2
        opponent={'skill_id':7020620,'slot':2,'actor_member_id':'b0'}
        self.assertEqual(self.commit(f,state,0,'lens-dark',option=1,response=True,opponent_action=opponent),[115])
        self.assertEqual(state['teams']['b']['members'][0]['skill_slots'][2],7020620)
        events=choice.after_skill(self.prepared,state,'a',self.last_action,self.last_result['events'],
            context=self.last_context,event_token='lens-replace')
        self.assertTrue(events)
        self.assertEqual(state['teams']['b']['members'][0]['skill_slots'][2],7060230)
        self.assertEqual(choice.after_skill(self.prepared,state,'a',self.last_action,self.last_result['events'],
            context=self.last_context,event_token='lens-replace'),[])

    def test_choice_growth_and_current_response_factor_preserve_same_skill_history(self):
        f,state=self.fixture([7021230,7150360,0,0])
        self.assertEqual(self.commit(f,state,0,'friend-light',option=0),[70])
        state['turn']=2
        self.assertEqual(self.commit(f,state,0,'friend-dark',option=1,response=True),[180])
        self.assertEqual(f.power(state,0),90)
        self.assertEqual(choice.response_categories(self.programs[7021230],0),[])
        self.assertEqual(choice.response_categories(self.programs[7021230],1),['status'])
        state['turn']=3
        self.assertEqual(len(self.commit(f,state,1,'test-flight-light',option=0)),2)
        self.assertEqual(f.power(state,1),30)
        state['turn']=4
        self.assertEqual(self.commit(f,state,1,'test-flight-dark',option=1),[30,30])
        self.assertEqual(history.hits(state['teams']['a']['members'][0],2,7150360),3)

    def test_position_growth_requires_use_and_counts_one_change_per_turn(self):
        f,state=self.fixture([7070020,7020400,0,0]);actor=state['teams']['a']['members'][0]
        p=[1,0,2,3]
        def move(turn):
            actor=state['teams']['a']['members'][0]
            actor['skill_slots']=[actor['skill_slots'][i] for i in p]
            return dynamic.remap_member_slots(actor,p,turn=turn)
        self.assertEqual(move(1),[])
        self.commit(f,state,1,'gear-arm')
        self.assertEqual(len(move(1)),1)
        self.assertEqual(f.power(state,0),85)
        self.assertEqual(move(1),[])
        state['turn']=2;move(2)
        self.assertEqual(f.power(state,0),100)
        history.on_departure(self.prepared,state,'a','a0',event_token='gear-leave')
        state['turn']=3;self.assertEqual(move(3),[])
        self.assertEqual(f.power(state,1),100)

    def test_distinct_type_set_and_previous_round_any_member_conditional_swift(self):
        f,state=self.fixture([7060120,7040200,7020360,7150400])
        self.commit(f,state,1,'fire-type')
        state['turn']=2;self.commit(f,state,1,'same-fire-type')
        self.assertEqual(f.power(state,0),90)
        self.commit(f,state,2,'ordinary-type')
        self.assertEqual(f.power(state,0),120)
        candidates=action_traits.swift_candidates(self.prepared,state,state['teams']['a']['members'][0],[3,2,2,2])
        self.assertFalse(candidates[3]['swift'])
        phantom=next(v['id'] for v in self.prepared._rules._catalog['moves'].values() if v['type']=='幻系')
        opponent=state['teams']['b']['members'][0];opponent['skill_slots']=[phantom,0,0,0]
        action={'kind':'skill','skill_id':phantom,'slot':0,'actor_member_id':'b0','program':self.prepared._rules.program(phantom)}
        outcomes.record_committed_action(self.prepared,state,'b',action,[{'op':'energy.pay','amount':0}],event_token='other-side-phantom')
        state['turn']=3
        candidates=action_traits.swift_candidates(self.prepared,state,state['teams']['a']['members'][0],[3,2,2,2])
        self.assertTrue(candidates[3]['swift'])
        self.assertTrue(action_traits.entry_program_has_swift(self.programs[7150400],candidates[3]))
        state['turn']=4
        self.assertFalse(action_traits.swift_candidates(self.prepared,state,state['teams']['a']['members'][0],[3,2,2,2])[3]['swift'])
