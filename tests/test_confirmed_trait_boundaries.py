"""Targeted user-confirmed trait boundaries; no game calibration claim."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from lab import trait_runtime as traits
from lab import defense_runtime
from tests import test_trait_runtime as fixtures
from tests.test_victory_rules import state_with_six
from lab.victory_rules import initialize_victory, terminal

class ConfirmedTraitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.TraitRuntimeTests.setUpClass()
        cls.fixture=fixtures.TraitRuntimeTests()
        cls.prepared=fixtures.TraitRuntimeTests.prepared

    def state(self,tid):
        state=self.fixture.state(tid,200080)
        traits.bind(self.prepared,state)
        for team in state['teams'].values():
            for member in team['members']:
                member['types']=deepcopy(self.prepared._rules.form(member['form_id'])['types'])
        return state

    def test_missing_entry_history_blocks_only_the_queried_effect(self):
        for tid in (200110, 200109, 200153, 200325, 200147):
            with self.subTest(trait=tid):
                state = self.state(tid)
                actor, other = [state['teams'][s]['members'][0] for s in ('a', 'b')]
                before = deepcopy(state)
                self.assertEqual(traits.stat_terms(actor, 'pdef', 1, opponent=other), [])
                self.assertEqual(traits.speed_bonus(actor, opponent=other), 0)
                if tid == 200153:
                    with self.assertRaisesRegex(ValueError, 'entry snapshot'):
                        traits.modify_power(actor, {}, 100, opponent=other)
                else:
                    self.assertEqual(traits.modify_power(actor, {}, 100, opponent=other), 100)
                if tid in (200110, 200109):
                    with self.assertRaisesRegex(ValueError, 'entry snapshot'):
                        traits.modify_cost(actor, other, {}, 4)
                else:
                    self.assertEqual(traits.modify_cost(actor, other, {}, 4), 4)
                if tid == 200325:
                    with self.assertRaisesRegex(ValueError, 'entry snapshot'):
                        traits.stat_terms(actor, 'patk', 1, opponent=other)
                self.assertEqual(state, before)
        state = self.state(200302)
        actor, other = [state['teams'][s]['members'][0] for s in ('a', 'b')]
        for query in (lambda: traits.stat_terms(actor, 'pdef', 1, opponent=other),
                      lambda: traits.speed_bonus(actor, opponent=other)):
            with self.assertRaisesRegex(ValueError, 'entry snapshot'):
                query()

    def test_irrelevant_query_still_rejects_tampered_existing_entry_snapshot(self):
        state = self.state(200110)
        traits.run_event(self.prepared, state, 'member.enter', side='a', member_id='a', token='entry')
        actor, other = [state['teams'][s]['members'][0] for s in ('a', 'b')]
        self.assertEqual(traits.modify_power(actor, {}, 100, opponent=other), 100)
        actor['confirmed_entry_history']['cost_delta'] = -99
        with self.assertRaisesRegex(ValueError, 'snapshot changed'):
            traits.modify_power(actor, {}, 100, opponent=other)

    def test_phoenix_one_hp_one_trigger_and_indirect_packet(self):
        state=self.state(200151)
        actor=state['teams']['a']['members'][0]
        other=state['teams']['b']['members'][0]
        result=traits.before_hp_loss(self.prepared,state,'a','a',100,token='mark:1')
        actor=state['teams']['a']['members'][0]
        self.assertEqual(result['damage'],99)
        self.assertEqual(state['teams']['b']['members'][0]['statuses']['burn'],15)
        actor['hp']=1
        self.assertEqual(traits.before_hp_loss(self.prepared,state,'a','a',1,token='hit:2')['damage'],1)
        with self.assertRaises(ValueError):
            traits.before_hp_loss(self.prepared,state,'a','a',100,token='mark:1')

    def test_direct_pipeline_keeps_protection_events_without_defense(self):
        state=self.state(200151)
        relative={'self':state['teams']['b']['members'][0],'opponent':state['teams']['a']['members'][0]}
        damage,receipt=defense_runtime.resolve_received_damage(lambda *args:100,{'target':'opponent'},relative,{'turn':1})
        self.assertEqual(damage,99)
        self.assertTrue(any(e['op']=='trait.fatal_protection' for e in defense_runtime.after_received_damage(relative['opponent'],99,receipt,1)))

    def test_revival_waits_four_rounds_and_does_not_save_empty_roster(self):
        state=self.state(200230)
        reserve=self.fixture.member('reserve',200076)
        state['teams']['a']['members'].append(reserve)
        actor=state['teams']['a']['members'][0];actor['hp']=0
        traits.run_event(self.prepared,state,'member.faint',side='a',member_id='a',token='faint:1')
        for turn in [1,2,3,4]:
            state['turn']=turn;traits.run_event(self.prepared,state,'turn.end')
            self.assertEqual(state['teams']['a']['members'][0]['hp'],0)
        state['turn']=5;traits.run_event(self.prepared,state,'turn.end')
        self.assertEqual((state['teams']['a']['members'][0]['hp'],state['teams']['a']['members'][0]['energy']),(200,10))
        empty=state_with_six();initialize_victory(empty)
        for m in empty['teams']['a']['members']:m['hp']=0;m['revival_pending']={'revive_at_turn':5}
        self.assertEqual(terminal(empty)['winner'],'b')

    def test_actual_paid_cost_not_base_cost_and_zero_is_recorded(self):
        state=self.state(200318)
        self.assertEqual(traits.base_skill_cost(state['teams']['a']['members'][0],7),7)
        for side,amount in [('a',0),('b',3)]:
            action={'kind':'skill','skill_id':7020370,'actor_member_id':side}
            traits.record_actual_payment(self.prepared,state,side,action,amount,token='pay:'+side)
        traits.run_event(self.prepared,state,'turn.end')
        self.assertEqual(traits.base_skill_cost(state['teams']['a']['members'][0],99),3)
        self.assertEqual(len(state['actual_skill_payments']),2)
        before=deepcopy(state)
        traits.run_event(self.prepared,state,'turn.end')
        self.assertEqual(state,before)


    def test_entry_history_includes_self_and_free_uses_but_freezes_at_entry(self):
        state=self.state(200110)
        sid=int(next(k for k,v in self.prepared._rules._catalog['moves'].items() if v.get('type')=='水系' and v.get('kind')=='magical'))
        for index,amount in enumerate([0,3]):
            traits.record_actual_payment(self.prepared,state,'a',{'skill_id':sid,'actor_member_id':'a','response_success':False},amount,token=f'water:{index}')
        traits.run_event(self.prepared,state,'member.enter',side='a',token='entry:1')
        actor=state['teams']['a']['members'][0]
        self.assertEqual(traits.modify_cost(actor,state['teams']['b']['members'][0],{},4),2)
        traits.record_actual_payment(self.prepared,state,'a',{'skill_id':sid,'actor_member_id':'a','response_success':False},0,token='after-entry')
        self.assertEqual(traits.modify_cost(actor,state['teams']['b']['members'][0],{},4),2)

    def test_switch_cost_preview_refreshes_entry_snapshot_without_committing_it(self):
        from lab.research_phases import build_research_context_v2
        state = self.state(200080)
        incoming = self.fixture.member('incoming', 200110, skill_slots=[7150080, 0, 0, 0])
        state['teams']['a']['members'].append(incoming)
        traits.bind(self.prepared, state)
        sid = int(next(k for k, v in self.prepared._rules._catalog['moves'].items()
                       if v.get('type') == '水系' and v.get('kind') == 'magical'))
        actions = {'a': {'kind': 'switch', 'target_slot': 1},
                   'b': {'kind': 'skill', 'slot': 0, 'skill_id': 7020370, 'effective_cost': 1}}
        before = deepcopy(state)
        initial = build_research_context_v2(self.prepared, state, actions)
        self.assertEqual(initial['switches']['a']['incoming_effective_costs'][0], 3)
        self.assertEqual(state, before)
        traits.record_actual_payment(self.prepared, state, 'a', {'skill_id': sid, 'actor_member_id': 'a',
                                     'response_success': False}, 0, token='water:before-old-entry')
        traits._snapshot_entry_history(state, 'a', 'incoming')
        traits.record_actual_payment(self.prepared, state, 'a', {'skill_id': sid, 'actor_member_id': 'a',
                                     'response_success': False}, 0, token='water:after-old-entry')
        before = deepcopy(state)
        context = build_research_context_v2(self.prepared, state, actions)
        self.assertEqual(context['switches']['a']['incoming_effective_costs'][0], 1)
        self.assertEqual(state, before)
        state['actual_skill_payments'][0]['amount'] = 999
        with self.assertRaisesRegex(ValueError, 'payment history was changed'):
            build_research_context_v2(self.prepared, state, actions)

    def test_entry_energy_preview_does_not_double_credit_and_requires_response_evidence(self):
        from lab.ruleset import canonical_hash
        state = self.state(200080)
        state['teams']['a']['members'].append(self.fixture.member('incoming', 200177))
        traits.bind(self.prepared, state)
        traits.record_actual_payment(self.prepared, state, 'a', {'skill_id': 7020370,
            'actor_member_id': 'a', 'response_success': True}, 0, token='response:before-entry')
        before = deepcopy(state)
        preview = traits.preview_entry_history(state, 'a', 1)
        self.assertEqual(preview['teams']['a']['members'][1]['energy'], 5)
        self.assertEqual(state, before)
        state['teams']['a']['active_slot'] = 1
        events = traits.run_event(self.prepared, state, 'member.enter', side='a', token='real-entry')
        actor = state['teams']['a']['members'][1]
        self.assertEqual(actor['energy'], 5)
        self.assertEqual(sum(e['op'] == 'trait.entry_history_energy' for e in events), 1)
        traits.run_event(self.prepared, state, 'member.enter', side='a', token='real-entry')
        self.assertEqual(state['teams']['a']['members'][1]['energy'], 5)
        broken = deepcopy(before)
        payment = broken['actual_skill_payments'][0]
        payment.pop('response_success')
        payment['record_hash'] = canonical_hash({k: v for k, v in payment.items() if k != 'record_hash'})
        with self.assertRaisesRegex(ValueError, 'response history is incomplete'):
            traits.preview_entry_history(broken, 'a', 1)

    def test_sentry_is_single_hit_hp_comparison_and_speed_bonus_is_source_bound(self):
        state=self.state(200262)
        traits.prepare_sentry(self.prepared,state,'a',predicted_single_hit=99,token='sentry:1')
        self.assertEqual(traits.speed_bonus(state['teams']['a']['members'][0]),0)
        traits.prepare_sentry(self.prepared,state,'a',predicted_single_hit=100,token='sentry:2')
        self.assertEqual(traits.speed_bonus(state['teams']['a']['members'][0]),50)
        state['teams']['a']['members'][0]['sentry_prediction']['predicted_single_hit']=0
        with self.assertRaises(ValueError):traits.speed_bonus(state['teams']['a']['members'][0])

    def test_dual_departure_orders_pre_switch_speed_and_seeded_tie(self):
        from lab import forced_switch_runtime as switches
        state=self.state(200151)
        state['teams']['a']['members'][0]['speed']=200
        state['teams']['b']['members'][0]['speed']=100
        selections=[{'side':'b','cause':'detach','replacement_slot':0},{'side':'a','cause':'detach','replacement_slot':0}]
        calls=[]
        def fragment(catalog,current,side,cause,**kw):
            calls.append(side)
            return {'status':'applied','state':deepcopy(current),'events':[{'op':'mock.switch','side':side}],'blockers':[]}
        with patch('lab.research_phases._effective_speed',side_effect=lambda actor,*args:actor['speed']), patch.object(switches,'execute_forced_switch_fragment',side_effect=fragment):
            result=switches.execute_departures(self.prepared,state,selections,event_token='dual',context={'random_seed':7},source_skill_id=7150270,source_hash='source',order_policy=switches.DUAL_ORDER)
            self.assertEqual(calls,['a','b'])
            self.assertEqual(result['events'][0]['pre_departure_speeds'],{'a':200,'b':100})
            state['teams']['b']['members'][0]['speed']=200
            one=switches.execute_departures(self.prepared,state,selections,event_token='tie',context={'random_seed':7},source_skill_id=7150270,source_hash='source',order_policy=switches.DUAL_ORDER)
            two=switches.execute_departures(self.prepared,state,selections,event_token='tie',context={'random_seed':7},source_skill_id=7150270,source_hash='source',order_policy=switches.DUAL_ORDER)
            self.assertEqual(one,two)
            self.assertNotIn('forced_switch_order_random',state)


    def test_encore_other_automatic_departure_has_priority(self):
        from lab import forced_trait_runtime as forced
        state=self.state(200290)
        actor=state['teams']['a']['members'][0]
        evidence=forced.evidence(self.prepared,state,actor)
        actor['other_automatic_departure_turn']=state['turn']
        actor['forced_trait_pending']={'turn':state['turn'],'trait_id':200290,'member_id':'a',
            'source_hash':evidence['source_hash'],'config_hash':forced.CONFIG_HASH,
            'replacement_slot':None,'action_token':'encore'}
        result=forced.end_round(self.prepared,state,context={})
        self.assertEqual(result['status'],'applied')
        self.assertTrue(any(e['op']=='trait.return.suppressed' for e in result['events']))
        self.assertNotIn('forced_trait_pending',result['state']['teams']['a']['members'][0])
        self.assertIn('forced_trait_pending',actor)

    def test_paid_comparison_uses_payment_not_base_and_harmony_adds_per_match(self):
        state=self.state(200104)
        state['teams']['b']['members'][0]['energy']=10
        traits.record_actual_payment(self.prepared,state,'a',{'skill_id':7020370,'actor_member_id':'a'},6,token='stone')
        events=traits.run_event(self.prepared,state,'turn.end')
        self.assertEqual(next(e for e in events if e['op']=='trait.paid_difference')['after'],4)
        self.assertEqual(state['teams']['b']['members'][0]['energy'],7)
        state=self.state(200275)
        for side in ('a','b'):
            traits.record_actual_payment(self.prepared,state,side,{'skill_id':7020370,'actor_member_id':side},0,token='harmony:'+side)
        traits.run_event(self.prepared,state,'turn.end')
        for attr in ('patk','pdef'):
            self.assertEqual(state['teams']['a']['members'][0]['stat_modifiers'][attr],[{'numerator':30,'denominator':100}])


    def test_cocoon_immune_two_indirect_packets_without_borrowing_hp_or_energy(self):
        state=self.state(200195)
        actor=state['teams']['a']['members'][0]
        before_hp,before_energy=actor['hp'],actor['energy']
        for index in range(2):
            result=traits.before_hp_loss(self.prepared,state,'a','a',before_hp,token=f'indirect:{index}')
            self.assertEqual(result['damage'],0)
        self.assertEqual(traits.before_hp_loss(self.prepared,state,'a','a',before_hp,token='indirect:2')['damage'],before_hp)
        actor=state['teams']['a']['members'][0]
        self.assertEqual((actor['hp'],actor['energy']),(before_hp,before_energy))


    def test_existing_payment_and_unlimited_cute_delegates_execute(self):
        from lab import payment_runtime, cute_runtime
        state=self.state(200100)
        actor=state['teams']['a']['members'][0]
        self.assertTrue(actor['trait_supported'])
        quote=payment_runtime.quote(self.prepared,actor,7020370,3)
        self.assertEqual((quote['paid_energy'],quote['paid_hp']),(1,20))
        self.assertEqual((actor['energy'],actor['hp']),(1,100))
        with self.assertRaises(ValueError):payment_runtime.quote(self.prepared,{**actor,'hp':20},7020370,3)
        state=self.state(200182);actor=state['teams']['a']['members'][0]
        self.assertTrue(actor['trait_supported'])
        result=cute_runtime.gain_cute(actor,8,source={'kind':'constructed_test'})
        self.assertEqual(result['gained'],8)
        self.assertEqual(actor['cute_layers'],8)
        state=self.state(200141)
        row=traits._rows()[200141]
        self.assertEqual(row['runtime_delegate'],'victory_rules')
        self.assertTrue(state['teams']['a']['members'][0]['trait_supported'])

    def test_guardian_counts_other_living_roster_cute_at_entry(self):
        state=self.state(200109)
        with self.assertRaisesRegex(ValueError,'initialized'):
            traits.modify_cost(state['teams']['a']['members'][0],state['teams']['b']['members'][0],{},3)
        reserve=self.fixture.member('reserve',200080)
        reserve['cute_layers']=2
        state['teams']['a']['members'].append(reserve)
        traits.run_event(self.prepared,state,'member.enter',side='a',token='guardian')
        actor=state['teams']['a']['members'][0]
        self.assertEqual(traits.modify_cost(actor,state['teams']['b']['members'][0],{},3),1)
        before=deepcopy(state)
        state['teams']['a']['members'][1]['hp']=0
        traits.run_event(self.prepared,state,'member.enter',side='a',token='exclude-fainted')
        self.assertEqual(traits.modify_cost(state['teams']['a']['members'][0],state['teams']['b']['members'][0],{},3),3)

    def test_shared_bloodline_relation_and_vulpine_power(self):
        state=self.state(200192)
        actor=state['teams']['a']['members'][0]
        enemy={'types':['草系'],'bloodline_id':4}
        self.assertEqual(traits.bloodline_relation(enemy),{'bloodline_id':4,'foreign_type':True,'mixed':True})
        self.assertEqual(traits.modify_power(actor,{},100,opponent=enemy),200)
        enemy['bloodline_id']=2
        self.assertEqual(traits.modify_power(actor,{},100,opponent=enemy),100)
        enemy['bloodline_id']=19
        self.assertTrue(traits.bloodline_relation(enemy)['mixed'])
        self.assertEqual(traits.modify_power(actor,{},100,opponent=enemy),100)
        for value in [0,20,None]:
            enemy['bloodline_id']=value
            with self.assertRaises(ValueError):traits.bloodline_relation(enemy)

    def test_jealousy_permits_carried_ordinary_skill_without_consuming_charge(self):
        state=self.state(200174)
        actor=state['teams']['a']['members'][0]
        phases=self.prepared._components()[1]
        import json
        from pathlib import Path
        charge_id=json.loads(Path('data/rules/reviewed-charge-components-1.json').read_text(encoding='utf8'))['skills'][0]['skill_id']
        actor['skill_slots']=[charge_id,7020370,0,0]
        actor['charge']=phases.charge_state(0,charge_id,1)
        original=deepcopy(actor['charge'])
        self.assertTrue(traits.permits_carried_skill_while_charging(self.prepared,state,'a',1))
        self.assertFalse(traits.permits_carried_skill_while_charging(self.prepared,state,'a',0))
        self.assertEqual(actor['charge'],original)
        with self.assertRaises(ValueError):traits.permits_carried_skill_while_charging(self.prepared,state,'a',2)


    def test_hurricane_magic_extra_applies_only_to_the_defeated_target_role(self):
        from lab import victory_rules as victory
        config=victory._loss_data()
        proof={'attacker':{'trait_id':200211},'target':{'trait_id':200076}}
        self.assertEqual(victory._direct_extra_sources(proof,config),[])
        proof={'attacker':{'trait_id':200076},'target':{'trait_id':200211}}
        extras=victory._direct_extra_sources(proof,config)
        self.assertEqual(len(extras),1)
        self.assertEqual((extras[0]['role'],extras[0]['trait_id'],extras[0]['amount']),('target',200211,1))


    def test_jealousy_releases_different_charged_payload_using_real_prior_charge(self):
        from lab.charge_program_adapter import load_charge_program_overrides
        from lab import charge_runtime
        from lab.turn_plan import charge_admission
        from lab.research_phases import _fragment
        state=self.state(200174)
        actor=state['teams']['a']['members'][0]
        phases=self.prepared._components()[1]
        actor['skill_slots']=[7100150,7100140,7020370,0]
        actor['charge']=phases.charge_state(0,7100150,1)
        actor['energy']=10
        charge_runtime.observe_attack(actor,skill_id=7020370,skill_kind='physical',turn=1,
            events=[{'op':'damage','target':'opponent','damage':0,'params':{'kind':'physical','power':90}}],
            action_token='actual-attack-during-original-charge')
        origin=deepcopy(actor['charge'])
        admission=charge_admission(self.prepared,actor,7100140,slot=1,turn=2)
        self.assertEqual(admission['execution_phase'],'jealousy_release_pending_execution')
        self.assertTrue(admission['charge_consumed_after_success'])
        self.assertEqual(admission['jealousy_release']['source_charge']['skill_id'],7100150)
        self.assertEqual(admission['jealousy_release']['selected_skill_id'],7100140)
        ordinary=charge_admission(self.prepared,actor,7020370,slot=2,turn=2)
        self.assertEqual(ordinary['execution_phase'],'jealousy_carried_pending_execution')
        programs=load_charge_program_overrides(self.prepared._rules._catalog)
        program=programs[7100140]
        relative={'self':actor,'opponent':state['teams']['b']['members'][0]}
        before=deepcopy(relative)
        context={**_fragment(program),**admission,'turn':2,'resolved_energy_cost':3,
            'selected_skill_slot':1,'response_success':False}
        powers=[]
        result=charge_runtime.execute(program,relative,context,lambda params,*args:powers.append(params['power']) or 0)
        self.assertEqual(result['status'],'applied',result['blockers'])
        self.assertEqual(powers,[270])
        self.assertEqual(result['state']['self']['energy'],7)
        self.assertEqual(result['state']['self']['charge'],origin)
        self.assertEqual(relative,before)
        forged=deepcopy(context);forged['jealousy_release']['source_charge']['skill_id']=7100140
        with self.assertRaisesRegex(ValueError,'proof changed'):
            charge_runtime.execute(program,relative,forged,lambda *args:0)
        self.assertEqual(relative,before)


    def test_full_research_turn_jealousy_cross_charge_and_ordinary_both_consume(self):
        from tests import test_action_runtime as action_fixtures
        from lab.charge_program_adapter import load_charge_program_overrides
        from lab.hud_damage_runtime import make_hud_damage_resolver
        from lab.research_phases import build_research_context_v2,execute_research_turn_v2
        from lab.simulation import _status_damage
        from lab.ruleset import canonical_hash
        programs=load_charge_program_overrides(self.prepared._rules._catalog)
        resolver=make_hud_damage_resolver(self.prepared)
        jealousy_form=next(f['id'] for f in self.prepared._rules._catalog['forms'] if f.get('trait_id')==200174)
        action_fixtures.JointActionRuntimeTests.setUpClass()
        for slot,cost,expected_skill in [(1,3,7100130),(2,1,7020370)]:
            with self.subTest(selected_skill=expected_skill):
                fixture=action_fixtures.JointActionRuntimeTests();fixture.setUp()
                state,actions=fixture.state,fixture.actions
                state['trait_policy']=traits.POLICY
                for team in state['teams'].values():
                    for member in team['members']:
                        member.update(stats={'patk':100,'matk':100,'pdef':100,'mdef':100,'spd':100},cute_layers=0)
                actor=state['teams']['a']['members'][1]
                actor.update(form_id=jealousy_form,skill_slots=[7100150,7100130,7020370,0],speed=101)
                actor['charge']=self.prepared._components()[1].charge_state(0,7100150,1)
                actions['a'].update(slot=slot,effective_cost=cost,effective_priority=0)
                actions['b'].update(effective_cost=0,effective_priority=0)
                before=deepcopy(state)
                context=build_research_context_v2(self.prepared,state,actions,program_overrides=programs)
                result=execute_research_turn_v2(self.prepared,state,actions,context,program_overrides=programs,
                    damage_resolver=resolver,status_damage_resolver=_status_damage)
                self.assertEqual(result['status'],'applied',result['blockers'])
                actual=result['state']['teams']['a']['members'][1]
                self.assertIsNone(actual['charge'])
                self.assertEqual(actual['energy'],10-cost)
                self.assertEqual(result['state']['turn'],3)
                casts=[e for e in result['events'] if e.get('op')=='skill.committed' and e.get('actor_side')=='a']
                self.assertEqual([e['skill_id'] for e in casts],[expected_skill])
                self.assertTrue(any(e.get('op')=='charge.abandoned' and e.get('previous_charge',{}).get('skill_id')==7100150 for e in result['events']))
                self.assertEqual(state,before)


    def test_repeated_cast_paid_cost_uses_user_two_plus_three_example(self):
        def recorded(tid,other_amount=3,own_amounts=(2,2,2)):
            state=self.state(tid)
            state['teams']['b']['members'][0]['energy']=10
            for index,amount in enumerate(own_amounts):
                traits.record_actual_payment(self.prepared,state,'a',{'skill_id':7110380,'actor_member_id':'a'},amount,token=f'a-cast:{index}')
            traits.record_actual_payment(self.prepared,state,'b',{'skill_id':7110380,'actor_member_id':'b'},other_amount,token='b-cast')
            return state
        state=recorded(200318)
        traits.run_event(self.prepared,state,'turn.end')
        self.assertEqual(traits.base_skill_cost(state['teams']['a']['members'][0],99),5)
        self.assertEqual([r['amount'] for r in state['actual_skill_payments']],[2,2,2,3])
        state=recorded(200104)
        events=traits.run_event(self.prepared,state,'turn.end')
        comparison=next(e for e in events if e['op']=='trait.paid_difference')
        self.assertEqual((comparison['own_per_cast_payment'],comparison['opponent_per_cast_payment']),(2,3))
        self.assertEqual(comparison['before'],comparison['after'])
        state=recorded(200275,other_amount=2)
        events=traits.run_event(self.prepared,state,'turn.end')
        comparison=next(e for e in events if e['op']=='trait.paid_matching_stats')
        self.assertEqual((comparison['own_per_cast_payment'],comparison['percent']),(2,30))
        state=recorded(200318,own_amounts=(2,3))
        before=deepcopy(state)
        with self.assertRaisesRegex(ValueError,'Different per-cast'):
            traits.run_event(self.prepared,state,'turn.end')
        self.assertEqual(state,before)


    def test_audited_final_retaliation_has_separate_ko_proof_and_magic_ledger(self):
        from lab import victory_rules as victory,action_outcome_runtime as outcomes,trait_switch_components as switch_traits
        for target_trait,first_loss in [(200141,2),(200211,1)]:
            with self.subTest(reflected_target_trait=target_trait):
                state=self.fixture.state(200103,target_trait)
                traits.bind(self.prepared,state)
                victory.initialize_victory(state)
                source=state['teams']['a']['members'][0]
                target=state['teams']['b']['members'][0]
                original_hp=target['hp']
                source['hp']=0;target['hp']=0
                program=self.prepared._rules.program(7020370)
                outcomes.record_committed_action(self.prepared,state,'b',{'kind':'skill','skill_id':7020370,
                    'actor_member_id':'b','slot':0,'program':program},
                    [{'op':'damage','target':'opponent','before':100,'after':0,'damage':100,
                      'params':{'kind':'physical','power':65,'type':'普通系'}}],event_token='original-enemy-skill')
                receipt=switch_traits.retaliation_source(source)
                event={**receipt,'op':'trait.retaliation','damage_kind':'physical','damage_type':'无系别',
                    'actor_side':'a','actor_member_id':'a','actor_form_id':source['form_id'],
                    'target_side':'b','target_member_id':'b','target_form_id':target['form_id'],
                    'before':original_hp,'after':0,'damage':original_hp,'turn':state['turn'],'token':'final-retaliation'}
                before=deepcopy(state)
                forged={**event,'source_trait_id':200104}
                with self.assertRaisesRegex(ValueError,'Unreviewed trait'):
                    victory.record_retaliation_defeat(state,forged)
                self.assertEqual(state,before)
                recorded=victory.record_retaliation_defeat(state,event)
                self.assertEqual(len(recorded),1)
                proof=state['trait_defeat_provenance']['b']['b']
                self.assertNotIn('skill_id',proof)
                self.assertEqual(proof['attacker']['trait_id'],200103)
                self.assertEqual(source['hp'],0)
                events=victory.reconcile_knockouts(state)
                by_side={e['side']:e for e in events}
                self.assertEqual(by_side['a']['requested_magic_loss'],first_loss)
                self.assertEqual(by_side['b']['requested_magic_loss'],2)
                self.assertEqual(by_side['b']['loss_source']['kind'],'trait_retaliation.loss')
                self.assertEqual(victory.record_retaliation_defeat(state,event),[])
                self.assertEqual(victory.reconcile_knockouts(state),[])
                victory.validate_victory(state)
                self.assertIsNone(victory.terminal(state)['winner'])

if __name__=='__main__':unittest.main()

