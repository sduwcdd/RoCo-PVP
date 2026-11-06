import unittest

from lab import action_traits, forced_switch_runtime as forced, skill_history_runtime as history, trait_runtime as traits
from lab.research_phases import _fragment
from lab.prepared_rules import PreparedRules
from lab.server import load_catalog
from lab.victory_rules import initialize_victory, reconcile_knockouts
from tests import test_switch_runtime as switch_fixture


class HistorySwitchWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = PreparedRules(load_catalog()[0])

    def fixture(self):
        fixture = switch_fixture.SwitchRuntimeTests()
        fixture.prepared = self.prepared
        fixture.setUp()
        return fixture

    def test_voluntary_departure_disarms_round_growth_and_incoming_entry_grows_once(self):
        f = self.fixture()
        actor = f.actor()
        actor['skill_slots'][1] = 7050300
        action = {'kind': 'skill', 'actor_member_id': actor['member_id'], 'slot': 1,
                  'skill_id': 7050300, 'program': history.programs(self.prepared)[7050300]}
        binding = history.bind_action(self.prepared, f.state, 'a', action)
        history.after_skill(self.prepared, f.state, 'a', action, binding, action_token='earlier-water', context=history.research_context())
        f.actor(1)['skill_slots'][1] = 7110230
        f.context['incoming_effective_costs'] = [None, 3, None, None]
        result = f.run_switch()
        self.assertEqual(result['status'], 'applied', result['blockers'])
        outgoing, incoming = result['state']['teams']['a']['members']
        self.assertFalse(history.has_armed_listener(outgoing))
        entry_events = incoming['skill_history']['1']['events']
        self.assertEqual([e['phase'] for e in entry_events], ['member.enter'])

    def test_trait_granted_swift_uses_power_context_and_commits_after_use_growth(self):
        f = self.fixture()
        f.state['trait_policy'] = traits.POLICY
        f.actor(1).update(form_id=3069, skill_slots=[0, 7040200, 0, 0])
        program = history.programs(self.prepared)[7040200]
        f.context.update(swift_policy=action_traits.SWIFT_POLICY, incoming_effective_costs=[None, 1, None, None],
                         entry_timing='after_position_change_experiment', entry_skill_context=_fragment(program))
        observed = []
        result = f.run_switch(resolver=lambda params, actors, context: observed.append(
            history.modify_power(params['power'], context.get('skill_history_power'))) or 7)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual(observed, [50])
        incoming = result['state']['teams']['a']['members'][1]
        self.assertEqual(incoming['skill_history']['1']['events'][0]['phase'], 'after.use')
        self.assertEqual(incoming['energy'], 9)

    def test_swift_direct_defeat_proof_supplies_demon_extra_magic_loss(self):
        f = self.fixture()
        f.state['trait_policy'] = traits.POLICY
        f.enable_entry_attack()
        f.actor(1).update(form_id=3180)
        f.actor(0, 'b')['hp'] = 10
        f.context['faint_policy'] = 'stop_remaining_skill_on_exhaustion_experiment'
        initialize_victory(f.state)
        result = f.run_switch(resolver=lambda *_: 10)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        proof = result['state']['knockout_provenance']['b']['b-active']
        self.assertEqual(proof['attacker']['member_id'], 'a-bench')
        self.assertEqual(proof['accounting_scope'], 'victory')
        self.assertEqual(reconcile_knockouts(result['state'])[0]['actual_magic_loss'], 2)

    def test_forced_return_reenters_same_member_and_never_fires_intrinsic_swift(self):
        f = self.fixture()
        f.actor()['skill_slots'] = [7110230, 7150080, 0, 0]
        result = forced.execute_forced_switch_fragment(self.prepared, f.state, 'a', 'return',
            context={'snapshot_id': self.prepared.snapshot_id, 'forced_switch_policies': forced.policies(),
                     'event_token': 'return-history'})
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual(result['state']['teams']['a']['members'][0]['skill_history']['0']['events'][0]['phase'], 'member.enter')
        self.assertFalse(any(e['op'] == 'damage' for e in result['events']))
