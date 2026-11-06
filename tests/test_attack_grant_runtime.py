from copy import deepcopy
import unittest
from lab import attack_grant_runtime as grants, defense_runtime as defense, mechanism_runtime as mechanisms
from lab import trait_attack_hooks as hooks
from lab.prepared_rules import prepare_rules
from lab.research_phases import _fragment
from lab.server import load_catalog
from tests.test_action_runtime import member


class AttackGrantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.prepared = prepare_rules(cls.catalog)
        cls.programs = {**grants.programs(cls.prepared), **defense.defense_programs(cls.prepared)}

    def actors(self):
        return {key: {**member(key), 'types': ['普通系']} for key in ('self', 'opponent')}

    def test_warmup_response_selects_source_bound_two_or_four(self):
        program=self.programs[7040270]
        for response,factor,buff in ((False,2,20230350),(True,4,20231070)):
            ctx={**_fragment(program),**grants.research_context(),'resolved_energy_cost':1,'turn':2,'response_success':response}
            result=grants.execute(program,self.actors(),ctx)
            self.assertEqual(result['status'],'applied',result['blockers'])
            actor=result['state']['self']
            self.assertEqual(grants.power_factor(actor),factor)
            self.assertEqual(actor['skill_attack_grants'][0]['buff_id'],buff)
            actor['skill_attack_grants'][0]['resolved_response_success']=not response
            with self.assertRaises(ValueError):grants.validate_member(actor)
        ctx.pop('response_success')
        self.assertEqual(grants.execute(program,self.actors(),ctx)['status'],'blocked')

    def test_pending_power_consumes_old_and_installs_new_after_attack(self):
        state = self.actors()
        program = self.programs[7040450]
        ctx = {**_fragment(program), **grants.research_context(), 'defense_policies':defense.POLICIES,
               'resolved_energy_cost':2, 'turn':2}
        out = defense.execute_defense_skill(program, state, ctx, turn=2, opponent_kind='physical')
        self.assertEqual(out['status'], 'applied', out['blockers'])
        state = out['state']
        self.assertEqual(mechanisms.modify_power(state['self'], 70), 140)
        program = self.programs[7040220]
        ctx = {**_fragment(program), **grants.research_context(), 'resolved_energy_cost':2,
               'turn':2,'response_success':True}
        powers=[]
        def resolver(params, owned, context):
            powers.append(mechanisms.modify_power(owned['self'], params['power']))
            return 7
        grants.preflight(program,state,ctx,resolver)
        self.assertEqual(powers,[])
        out = grants.execute(program,state,ctx,damage_resolver=resolver)
        self.assertEqual(out['status'], 'applied', out['blockers'])
        self.assertEqual(powers,[140])
        self.assertEqual(grants.power_factor(out['state']['self']),2)
        self.assertEqual(out['state']['self']['skill_attack_grants'][0]['buff_id'],20230350)
        self.assertEqual(grants.power_factor(grants.depart(out['state']['self'])),1)

    def test_same_buff_lifesteal_layers_actual_damage_cap_and_transform(self):
        actor = member('a'); actor['hp']=100
        ctx=grants.research_context()
        grants.install(actor,self.programs[7180160],ctx)
        grants.install(actor,self.programs[7180210],ctx)
        self.assertEqual(grants.lifesteal_source(actor)['percent'],150)
        state={'snapshot_id':self.prepared.snapshot_id,'turn':2,
               'teams':{'a':{'active_slot':0,'members':[actor]},'b':{'active_slot':0,'members':[member('b')]}}}
        program=self.prepared._rules.program(7020360)
        context={**_fragment(program),**hooks.research_context(),'turn':2}
        binding=hooks.prepare_attack(self.prepared,actor,program,context,token='2:a:test')
        damage=[{'op':'damage','target':'opponent','params':{'kind':'physical'},'before':300,'after':280,'damage':20}]
        events=hooks.after_skill(self.prepared,state,'a',program,damage,binding,context=context)
        self.assertEqual(state['teams']['a']['members'][0]['hp'],130)
        self.assertEqual(events[0]['lifesteal_source_kind'],'skill_buff')
        self.assertEqual(hooks.after_skill(self.prepared,state,'a',program,damage,binding,context=context),[])
        actor=state['teams']['a']['members'][0]
        source=grants.rules()['transformations']['7160160']
        doubled=grants.transform_lifesteal(actor['skill_attack_grants'][0],30,7160160,source['record_hash'])
        actor['skill_attack_grants']=[doubled]
        self.assertEqual(grants.lifesteal_source(actor)['percent'],300)
        for _ in range(10): grants.install(actor,self.programs[7180160],ctx)
        self.assertEqual(grants.lifesteal_source(actor)['percent'],990)
        forged=deepcopy(actor);forged['skill_attack_grants'][0]['layers']=100
        with self.assertRaises(ValueError):grants.validate_member(forged)
