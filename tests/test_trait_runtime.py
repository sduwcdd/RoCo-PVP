"""Trait event/source contracts; synthetic battles are not game calibration."""
from copy import deepcopy
from fractions import Fraction
import json
import unittest
from unittest.mock import patch

from lab import trait_runtime as traits
from lab.prepared_rules import prepare_rules
from lab.ruleset import canonical_hash
from lab.server import load_catalog


class TraitRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.prepared = prepare_rules(cls.catalog)
        cls.forms = {}
        for form in cls.catalog['forms']:
            cls.forms.setdefault(form.get('trait_id'), form)

    def member(self, mid, tid, **changes):
        form = self.forms[tid]
        value = {'member_id': mid, 'form_id': form['id'], 'hp': 100, 'max_hp': 200,
            'energy': 1, 'max_energy': 20, 'skill_slots': [7020370, 0, 0, 0], 'statuses': {},
            'stat_modifiers': {}, 'charge': None, 'speed': 100, 'rooted': False, 'entered_turn': 0}
        value.update(changes)
        return value

    def state(self, a=200080, b=200076):
        return {'snapshot_id': self.prepared.snapshot_id, 'trait_policy': traits.POLICY, 'turn': 1,
            'teams': {side: {'active_slot': 0, 'members': [self.member(side, tid)],
                'marks': {'positive': None, 'negative': None}} for side, tid in [('a', a), ('b', b)]}}

    def actor(self, state, side='a', slot=0):
        return state['teams'][side]['members'][slot]

    def test_field_buff_kinds_union_uses_source_identity(self):
        state=self.state(200309); traits.bind(self.prepared,state)
        actor=self.actor(state); enemy=self.actor(state,'b')
        with patch('lab.modifier_ledger.buff_kind_ids',side_effect=[[20010010,20010020],[20010010]]):
            self.assertEqual(traits.stat_terms(actor,'pdef',1,opponent=enemy),[{'numerator':40,'denominator':100}])
        self.assertEqual(traits.stat_terms(actor,'pdef',1,opponent=enemy),[])
        with self.assertRaises(ValueError): traits.stat_terms(actor,'pdef',1)

    def test_poison_pairs_convert_to_team_mark_once(self):
        state=self.state(200187); traits.bind(self.prepared,state)
        self.actor(state,'b')['statuses']['poison']=7
        traits.run_event(self.prepared,state,'turn.end',side='a',token='etch:1')
        self.assertEqual(self.actor(state,'b')['statuses']['poison'],1)
        self.assertEqual(state['teams']['b']['marks']['negative']['stacks'],3)
        self.assertEqual(traits.run_event(self.prepared,state,'turn.end',side='a',token='etch:1'),[])
        self.actor(state,'b')['statuses']['poison']=2
        traits.run_event(self.prepared,state,'turn.end',side='a',token='etch:2')
        self.assertEqual(self.actor(state,'b')['statuses']['poison'],0)
        self.assertEqual(state['teams']['b']['marks']['negative']['stacks'],4)

    def test_burn_decay_growth_live_aura_and_cap(self):
        state=self.state(200203,200203); traits.bind(self.prepared,state)
        after,events=traits.status_decay_remaining(state,'burn',5,2)
        self.assertEqual(after,8); self.assertEqual(len(events[0]['sources']),2)
        self.assertEqual(traits.status_decay_remaining(state,'burn',98,49)[0],99)
        self.actor(state)['hp']=0; self.actor(state,'b')['hp']=0
        self.assertEqual(traits.status_decay_remaining(state,'burn',5,2),(2,[]))

    def test_burn_decay_converts_through_common_status_and_conflicts_block(self):
        state=self.state(200273); traits.bind(self.prepared,state)
        remaining,events=traits.status_decay_remaining(state,'burn',5,2)
        self.assertEqual(remaining,2)
        traits.apply_decay_conversion(self.prepared,state,'a',events)
        self.assertEqual(self.actor(state)['statuses']['poison'],0)  # Source owner is poison-immune.
        traits.apply_decay_conversion(self.prepared,state,'b',events)
        self.assertEqual(self.actor(state,'b')['statuses']['poison'],3)
        state=self.state(200273,200203); traits.bind(self.prepared,state)
        with self.assertRaises(ValueError): traits.status_decay_remaining(state,'burn',5,2)
        state=self.state(200273,200273); traits.bind(self.prepared,state)
        with self.assertRaises(ValueError): traits.status_decay_remaining(state,'burn',5,2)

    def test_super_effective_positive_hits_grant_stats_energy_once(self):
        state=self.state(200191); traits.bind(self.prepared,state)
        target=self.actor(state,'b')
        element=next(t for t in self.catalog['types'] if self.prepared._rules.type_multiplier(t,target['form_id'])['multiplier']['numerator']>self.prepared._rules.type_multiplier(t,target['form_id'])['multiplier']['denominator'])
        event={'op':'damage','target':'opponent','params':{'kind':'physical','type':element},'damage':3,'before':100,'after':97}
        traits.after_super_effective_damage(self.prepared,state,'a',[event],token='effective')
        self.assertEqual(self.actor(state)['energy'],3)
        self.assertEqual(traits.stat_terms(self.actor(state),'spd',1),[{'numerator':20,'denominator':100}])
        self.assertEqual(traits.after_super_effective_damage(self.prepared,state,'a',[event],token='effective'),[])
        self.assertEqual(traits.event_stat_layers(traits.depart(self.actor(state))),0)

    def test_buff_layer_speed_and_power_use_separate_source_scopes(self):
        state=self.state(200243); traits.bind(self.prepared,state)
        actor=self.actor(state);enemy=self.actor(state,'b')
        with patch('lab.modifier_ledger.buff_layer_count',return_value=3) as count:
            self.assertEqual(traits.modify_power(actor,{'type':'无系别'},100,opponent=enemy),130)
            self.assertEqual(traits.speed_bonus(actor,opponent=enemy),15)
            self.assertIsNone(count.call_args_list[0].kwargs['eligible_buff_ids'])
            self.assertIn(20010010,count.call_args_list[1].kwargs['eligible_buff_ids'])
        with self.assertRaises(ValueError):traits.speed_bonus(actor)

    def test_overheal_fraction_accumulation_poison_and_departure(self):
        state=self.state(280032);traits.bind(self.prepared,state)
        relative={'self':self.actor(state),'opponent':self.actor(state,'b')}
        traits.after_hp_restore(relative,'self',7,0,{'turn':1})
        self.assertEqual(traits.stat_terms(relative['self'],'patk',1),[])
        traits.after_hp_restore(relative,'self',3,0,{'turn':1})
        self.assertEqual(traits.stat_terms(relative['self'],'patk',1),[{'numerator':10,'denominator':100}])
        self.assertNotIn('trait_overheal',traits.depart(relative['self']))
        state=self.state(280038);traits.bind(self.prepared,state)
        relative={'self':self.actor(state),'opponent':self.actor(state,'b')}
        traits.after_hp_restore(relative,'self',21,0,{'turn':1})
        self.assertEqual(relative['opponent']['statuses']['poison'],1)
        self.assertEqual(traits._overheal_progress(relative['self'])[0],Fraction(21,20))

    def test_calendar_uses_explicit_game_date_and_rejects_host_fallback(self):
        state=self.state(200269)
        with self.assertRaisesRegex(ValueError,'trait_calendar'):traits.bind(self.prepared,state)
        state['trait_calendar']={'date':'2026-10-25','policy':traits.policies()['calendar']}
        traits.bind(self.prepared,state)
        self.assertEqual(traits.stat_terms(self.actor(state),'patk',1),[{'numerator':40,'denominator':100}])
        self.assertEqual(traits.stat_terms(self.actor(state),'pdef',1),[])
        state=self.state(200269);state['trait_calendar']={'date':'2026-10-26','policy':traits.policies()['calendar']}
        traits.bind(self.prepared,state)
        self.assertEqual(traits.stat_terms(self.actor(state),'pdef',1),[{'numerator':40,'denominator':100}])
        self.actor(state)['trait_calendar_binding']['weekday']=6
        with self.assertRaises(ValueError):traits.stat_terms(self.actor(state),'pdef',1)

    def test_field_mark_kinds_union_not_layers(self):
        state=self.state(200310); traits.bind(self.prepared,state)
        actor=self.actor(state); enemy=self.actor(state,'b')
        actor['field_marks']={'positive':{'id':3012,'stacks':3},'negative':None}
        enemy['field_marks']={'positive':{'id':3012,'stacks':1},'negative':{'id':1014,'stacks':2}}
        self.assertEqual(traits.stat_terms(actor,'matk',1,opponent=enemy),[{'numerator':100,'denominator':100}])
        enemy['field_marks']['negative']=None
        self.assertEqual(traits.stat_terms(actor,'matk',1,opponent=enemy),[{'numerator':50,'denominator':100}])
        self.assertEqual(traits.stat_terms(actor,'patk',1,opponent=enemy),[])
        with self.assertRaises(ValueError): traits.stat_terms(actor,'matk',1)

    def test_bind_all_reviewed_traits_and_preserve_unsupported_scope(self):
        self.assertEqual(len(traits._rows()), 109 + len(traits._confirmed_rows()))
        for tid, row in traits._rows().items():
            with self.subTest(tid=tid):
                state = self.state(tid)
                if tid==200269:state['trait_calendar']={'date':'2026-10-26','policy':traits.policies()['calendar']}
                traits.bind(self.prepared, state)
                actor = self.actor(state)
                self.assertEqual(actor['trait_id'], tid)
                self.assertTrue(actor['trait_supported'])
                self.assertEqual(actor['trait_source_hash'], row['record_hash'])
                self.assertEqual(row['record_hash'], canonical_hash(row['raw']))
                self.assertEqual(state['trait_policies'], traits.policies())
        for tid in traits._data()['weather_trait_sources']:
            state = self.state(int(tid))
            traits.bind(self.prepared, state)
            self.assertFalse(self.actor(state)['trait_supported'])
            self.assertTrue(self.actor(state)['trait_weather_supported'])
            self.assertEqual(self.actor(state)['trait_support_scope'], 'weather_module_subset')
        unknown = next(tid for tid in self.forms if tid and tid not in traits._rows()
                       and str(tid) not in traits._data()['weather_trait_sources'])
        state = self.state(unknown)
        traits.bind(self.prepared, state)
        self.assertFalse(self.actor(state)['trait_supported'])
        self.assertEqual(traits.run_event(self.prepared, state, 'skill.after', side='a'), [])

    def test_status_traits_keep_caster_source_and_component_conditions(self):
        target_tid = next(tid for tid, form in self.forms.items()
                          if tid in traits._rows() and '草系' not in form['types'])
        state = self.state(200293, target_tid)
        traits.run_event(self.prepared, state, 'skill.after', side='a', payload={'type': '火系'})
        target = self.actor(state, 'b')
        self.assertEqual(target['statuses'].get('leech'), 1)
        self.assertEqual(target['statuses'].get('burn', 0), 0)
        self.assertEqual(target['status_sources']['leech']['side'], 'a')
        self.assertEqual(target['status_sources']['leech']['member_id'], 'a')
        self.assertEqual(self.actor(state)['statuses'].get('leech', 0), 0)

    def test_energy_steal_actual_amount_cap_and_once_per_event(self):
        state = self.state(200155)
        self.actor(state)['energy'] = 19
        self.actor(state, 'b')['energy'] = 1
        events = traits.run_event(self.prepared, state, 'member.enter', side='a')
        self.assertEqual((self.actor(state)['energy'], self.actor(state, 'b')['energy']), (20, 0))
        self.assertEqual(next(e for e in events if e['op'] == 'energy.transfer')['actual_amount'], 1)
        self.assertEqual(traits.run_event(self.prepared, state, 'member.enter', side='a'), [])

    def test_damage_conditions_are_attack_only_and_cost_boundary_is_inclusive(self):
        for tid, energy, cost, carried, stab, expected in [
                (200074, 2, 3, ['火系'], ['火系'], Fraction(3, 5)),
                (200074, 2, 3, ['水系'], ['火系'], 1),
                (200268, 2, 3, [], ['水系'], Fraction(1, 2)),
                (200157, 0, 3, [], ['火系'], 0),
                (200157, 1, 3, [], ['火系'], 1),
                (200232, 2, 1, [], ['火系'], 0), (200232, 2, 2, [], ['火系'], 1)]:
            state = self.state(tid)
            traits.bind(self.prepared, state)
            attacker = self.actor(state, 'b'); attacker['energy'] = energy
            self.assertEqual(traits.damage_multiplier(self.actor(state), attacker,
                {'energy':cost, 'type':'火系', 'kind':'magical'}, carried_types=carried,
                attacker_types=stab), expected)

    def test_disabled_traits_are_noops_and_unknown_policy_is_not_silently_ignored(self):
        state = self.state()
        state.pop('trait_policy')
        original = deepcopy(state)
        self.assertEqual(traits.run_event(self.prepared, state, 'turn.end'), [])
        self.assertEqual(traits.initialize(self.prepared, state), [])
        traits.bind(self.prepared, state)
        self.assertEqual(state, original)
        state['trait_policy'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'Unknown trait'):
            traits.run_event(self.prepared, state, 'turn.end')

    def test_end_energy_heal_zero_energy_predicate_and_caps(self):
        for tid, change, expected in [(200080, {'energy': 19}, 20), (280013, {'energy': 1}, 7),
                                      (200297, {'energy': 0}, 10), (200297, {'energy': 1}, 1)]:
            with self.subTest(tid=tid, change=change):
                state = self.state(tid)
                self.actor(state).update(change)
                traits.run_event(self.prepared, state, 'turn.end', side='a')
                self.assertEqual(self.actor(state)['energy'], expected)
        state = self.state(200087)
        self.actor(state).update(hp=195, max_hp=201)
        traits.run_event(self.prepared, state, 'turn.end', side='a')
        self.assertEqual(self.actor(state)['hp'], 201)

    def test_all_team_restore_each_living_source_and_reserve_but_not_fainted(self):
        state = self.state(200301, 200301)
        state['teams']['a']['members'].append(self.member('reserve', 200301))
        state['teams']['b']['members'].append(self.member('fainted', 200301, hp=0))
        events = traits.run_event(self.prepared, state, 'turn.end')
        self.assertEqual(self.actor(state)['energy'], 3)
        self.assertEqual(self.actor(state, 'a', 1)['energy'], 3)
        self.assertEqual(self.actor(state, 'b')['energy'], 3)
        self.assertEqual(self.actor(state, 'b', 1)['energy'], 1)
        self.assertEqual(len(events), 6)
        self.assertEqual([e['actor_side'] for e in events], ['a'] * 3 + ['b'] * 3)

    def test_skill_type_heal_stats_and_opponent_energy_only_on_match(self):
        for tid, element, hp in [(200076, '草系', 120), (280002, '草系', 130)]:
            state = self.state(tid)
            traits.run_event(self.prepared, state, 'skill.after', side='a', payload={'type': '火系'})
            self.assertEqual(self.actor(state)['hp'], 100)
            traits.run_event(self.prepared, state, 'skill.after', side='a', payload={'type': element}, token='next-use')
            self.assertEqual(self.actor(state)['hp'], hp)
        for tid, percent in [(200146, 20), (280003, 30)]:
            state = self.state(tid)
            events = traits.run_event(self.prepared, state, 'skill.after', side='a', payload={'type': '火系'})
            self.assertEqual(self.actor(state)['stat_modifiers']['patk'], [{'numerator': percent, 'denominator': 100}])
            self.assertEqual(self.actor(state)['stat_modifiers']['matk'], [{'numerator': percent, 'denominator': 100}])
            self.assertEqual(events[0]['source_hash'], traits._rows()[tid]['record_hash'])
            self.assertIn('uncertainties', events[0])
        state = self.state(200089)
        traits.run_event(self.prepared, state, 'skill.after', side='a', payload={'type': '恶系'})
        self.assertEqual(self.actor(state, 'b')['energy'], 0)

    def test_explicit_departure_owner_and_initial_entry_are_once_and_atomic(self):
        state = self.state(200163)
        state['teams']['a']['members'].append(self.member('bench', 200076))
        state['teams']['a']['active_slot'] = 1
        traits.run_event(self.prepared, state, 'member.leave', side='a', member_id='a')
        self.assertEqual(self.actor(state, slot=0)['energy'], 11)
        self.assertEqual(self.actor(state, slot=1)['energy'], 1)
        for tid, amount in [(200169, 30), (280016, 40)]:
            state = self.state(tid)
            traits.initialize(self.prepared, state)
            saved = deepcopy(state)
            self.assertEqual(traits.initialize(self.prepared, state), [])
            self.assertEqual(state, saved)
            self.assertEqual(self.actor(state)['stat_modifiers']['patk'], [{'numerator': amount, 'denominator': 100}])
            traits.run_event(self.prepared, state, 'member.enter', side='a', token='later-reentry')
            self.assertEqual(len(self.actor(state)['stat_modifiers']['patk']), 2)

    def test_cost_modifiers_charge_events_persist_with_source_ledger(self):
        for tid, event, payload, delta in [(200107, 'skill.after', {'type': '水系'}, -1),
                (280001, 'skill.after', {'type': '水系'}, -2), (200114, 'charge.start', {}, -2)]:
            with self.subTest(tid=tid):
                state = self.state(tid)
                traits.run_event(self.prepared, state, event, side='a', payload=payload)
                actor = self.actor(state)
                self.assertEqual(actor['trait_modifiers']['cost'], delta)
                self.assertEqual(traits.modify_cost(actor, self.actor(state, 'b'), {}, 3), max(0, 3 + delta))
                saved = json.loads(json.dumps(state))
                saved['turn'] = 2
                traits.bind(self.prepared, saved)
                self.assertEqual(traits.modify_cost(self.actor(saved), self.actor(saved, 'b'), {}, 3), max(0, 3 + delta))
                self.assertEqual(actor['trait_modifier_sources'][0]['source_hash'], traits._rows()[tid]['record_hash'])

    def test_defense_reduction_opposing_aura_and_fainted_source(self):
        state = self.state(200108, 200123)
        traits.bind(self.prepared, state)
        actor, opponent = self.actor(state), self.actor(state, 'b')
        self.assertEqual(traits.modify_cost(actor, opponent, {'kind': 'defense'}, 3), 2)
        self.assertEqual(traits.modify_cost(actor, opponent, {'kind': 'physical'}, 3), 4)
        self.assertEqual(traits.modify_cost(actor, opponent, {'kind': 'defense'}, 0), 0)
        opponent['hp'] = 0
        self.assertEqual(traits.modify_cost(actor, opponent, {'kind': 'physical'}, 3), 3)

    def test_power_conditions_use_base_cost_type_and_exact_fraction(self):
        cases = [(200075, {'type': '火系'}, Fraction(125)), (200075, {'type': '光系'}, Fraction(100)),
                 (200088, {'energy': 1}, Fraction(150)), (200088, {'energy': 0}, Fraction(100)),
                 (200077, {'energy': 4}, Fraction(140)), (200077, {'energy': 3}, Fraction(100))]
        for tid, skill, expected in cases:
            with self.subTest(tid=tid, skill=skill):
                state = self.state(tid)
                if tid==200269:state['trait_calendar']={'date':'2026-10-26','policy':traits.policies()['calendar']}
                traits.bind(self.prepared, state)
                self.assertEqual(traits.modify_power(self.actor(state), skill, Fraction(100)), expected)
        state = self.state(200267)
        traits.bind(self.prepared, state)
        actor = self.actor(state)
        actor['types'] = self.forms[200267]['types']
        self.assertEqual(traits.modify_power(actor, {'type': actor['types'][0]}, 100), 100)
        other = next(t for t in self.catalog['types'] if t not in actor['types'])
        self.assertEqual(traits.modify_power(actor, {'type': other}, 100), 150)
        actor.pop('types')
        with self.assertRaisesRegex(ValueError, 'explicit source types'):
            traits.modify_power(actor, {'type': other}, 100)

    def test_successful_response_power_is_not_inferred_and_survives_json_restore(self):
        state = self.state(200148)
        self.assertEqual(traits.run_event(self.prepared, state, 'skill.after', side='a', payload={'response_success': False}), [])
        events = traits.run_event(self.prepared, state, 'skill.after', side='a', payload={'response_success': True}, token='success')
        self.assertEqual(events[0]['amount'], 30)
        saved = json.loads(json.dumps(state))
        self.assertEqual(traits.modify_power(self.actor(saved), {}, 100), 130)
        self.assertEqual(traits.run_event(self.prepared, saved, 'skill.after', side='a', payload={'response_success': True}, token='success'), [])
        self.assertEqual(saved, state)

    def test_event_tokens_are_scoped_by_kind_side_and_turn(self):
        state = self.state(200080, 200080)
        first = traits.run_event(self.prepared, state, 'turn.end', side='a', token='shared')
        saved = deepcopy(state)
        self.assertTrue(first)
        self.assertEqual(traits.run_event(self.prepared, state, 'turn.end', side='a', token='shared'), [])
        self.assertEqual(state, saved)
        self.assertTrue(traits.run_event(self.prepared, state, 'turn.end', side='b', token='shared'))
        state['turn'] = 2
        self.assertTrue(traits.run_event(self.prepared, state, 'turn.end', side='a', token='shared'))

    def test_shared_effect_gets_recipient_marks_without_leaking_temporary_fields(self):
        state = self.state(200146)
        state['teams']['a']['marks']['positive'] = {'id': 3012, 'stacks': 2}
        state['teams']['b']['marks']['positive'] = {'id': 3012, 'stacks': 1}
        original_marks = deepcopy(state['teams']['a']['marks'])
        observed = []
        execute = traits.execute_effects
        def capture(program, relative, context):
            observed.append(deepcopy(relative))
            return execute(program, relative, context)
        with patch.object(traits, 'execute_effects', side_effect=capture):
            traits.run_event(self.prepared, state, 'skill.after', side='a', payload={'type': '火系'})
        self.assertEqual(observed[0]['self']['field_marks'], original_marks)
        self.assertEqual(observed[0]['opponent']['field_marks']['positive']['stacks'], 1)
        for team in state['teams'].values():
            for actor in team['members']:
                self.assertNotIn('field_marks', actor)
                self.assertNotIn('team_devotion', actor)
                self.assertNotIn('types', actor)
        self.assertEqual(state['teams']['a']['marks'], original_marks)
        term = self.actor(state)['stat_modifiers']['patk'][0]
        self.assertEqual(Fraction(term['numerator'], term['denominator']), Fraction(4, 10))

    def test_failed_subscriber_and_initialization_roll_back_every_field(self):
        state = self.state(200301, 200301)
        original = deepcopy(state)
        execute = traits.execute_effects
        calls = []
        def fail_second(program, relative, context):
            calls.append(True)
            return {'status': 'blocked', 'blockers': ['injected failure']} if len(calls) == 2 else execute(program, relative, context)
        with patch.object(traits, 'execute_effects', side_effect=fail_second):
            with self.assertRaisesRegex(ValueError, 'injected failure'):
                traits.run_event(self.prepared, state, 'turn.end')
        self.assertEqual(state, original)
        state = self.state(200169, 200169)
        original, calls = deepcopy(state), []
        with patch.object(traits, 'execute_effects', side_effect=fail_second):
            with self.assertRaisesRegex(ValueError, 'injected failure'):
                traits.initialize(self.prepared, state)
        self.assertEqual(state, original)

    def test_source_policy_ledger_and_query_modifier_tampering_block(self):
        for change in [lambda state: state.update(trait_config_hash='bad'),
                       lambda state: state.update(trait_policies={}),
                       lambda state: self.actor(state).update(trait_id=200169),
                       lambda state: self.actor(state).update(trait_modifiers={'cost': -99}),
                       lambda state: self.actor(state).update(trait_modifiers={'unknown': 0}),
                       lambda state: state.update(trait_events={'turn': 1, 'tokens': 'bad'})]:
            state = self.state()
            change(state)
            original = deepcopy(state)
            with self.assertRaises(ValueError):
                traits.run_event(self.prepared, state, 'turn.end')
            self.assertEqual(state, original)
        state = self.state(200107)
        traits.run_event(self.prepared, state, 'skill.after', side='a', payload={'type': '水系'})
        self.actor(state)['trait_modifier_sources'][0]['source_hash'] = 'bad'
        with self.assertRaisesRegex(ValueError, 'modifier source'):
            traits.modify_cost(self.actor(state), self.actor(state, 'b'), {}, 2)
        with self.assertRaisesRegex(ValueError, 'Unknown trait condition'):
            traits._match({'when': {'unreviewed': True}}, self.actor(state), {})

    def test_invalid_event_inputs_are_atomic_and_evidence_hash_is_checked(self):
        for kwargs in [{'side': 'c'}, {'member_id': 'missing'}, {'payload': []}, {'token': ''},
                       {'payload': {'response_success': 1}}]:
            state = self.state()
            original = deepcopy(state)
            with self.assertRaises(ValueError):
                traits.run_event(self.prepared, state, 'turn.end', **kwargs)
            self.assertEqual(state, original)
        state = self.state()
        with patch.object(traits, '_source_hash', return_value='bad'):
            with self.assertRaisesRegex(ValueError, 'extracted source changed'):
                traits.bind(self.prepared, state)

    def test_whole_trait_description_or_configuration_changes_require_review(self):
        for tid in (200080, 200213):
            changed = deepcopy(self.catalog)
            changed['traits'][str(tid)]['desc']['zh'] += '未实现的额外效果。'
            prepared = prepare_rules(changed)
            state = self.state(tid)
            original = deepcopy(state)
            with self.assertRaisesRegex(ValueError, 'Trait source changed'):
                traits.bind(prepared, state)
            self.assertEqual(state, original)
        changed = deepcopy(traits._data())
        changed['policies']['dispatch'] = 'unreviewed_policy'
        with patch.object(traits.json, 'loads', return_value=changed):
            with self.assertRaisesRegex(ValueError, 'configuration changed'):
                traits._load.__wrapped__(0)

    def test_duplicate_or_future_modifier_sources_do_not_replay(self):
        state = self.state(200107)
        traits.run_event(self.prepared, state, 'skill.after', side='a', payload={'type': '水系'})
        actor = self.actor(state)
        actor['trait_modifier_sources'].append(deepcopy(actor['trait_modifier_sources'][0]))
        actor['trait_modifiers']['cost'] = -2
        with self.assertRaisesRegex(ValueError, 'Duplicate trait modifier'):
            traits.modify_cost(actor, self.actor(state, 'b'), {}, 3)
        actor['trait_modifier_sources'].pop()
        actor['trait_modifiers']['cost'] = -1
        actor['trait_modifier_sources'][0]['turn'] = 2
        with self.assertRaisesRegex(ValueError, 'after the current turn'):
            traits.bind(self.prepared, state)


if __name__ == '__main__':
    unittest.main()
