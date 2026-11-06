from fractions import Fraction
import unittest
from unittest.mock import patch

from lab import forced_switch_programs, modifier_ledger, trait_runtime as traits
from lab.prepared_rules import PreparedRules
from lab.research_phases import build_research_context_v2, execute_research_turn_v2
from lab.ruleset import canonical_hash
from lab.server import load_catalog
from tests import test_action_runtime as action_fixture, test_history_switch_wiring as swift_fixture


class InheritanceSwitchWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = PreparedRules(load_catalog()[0])

    def test_actual_drum_pass_program_pays_once_and_transfers_classified_buff_on_detach(self):
        f = action_fixture.JointActionRuntimeTests()
        f.catalog = self.prepared._rules._catalog
        f.programs = {'7020360': self.prepared._rules.program(7020360)}
        f.setUp()
        actor = f.state['teams']['a']['members'][1]
        actor['skill_slots'][1] = 7160270
        actor['stat_modifiers']['patk'] = [{'numerator': 1, 'denominator': 1}]
        modifier_ledger.register_stat(actor, 'patk', source_kind='skill', source_id=7020620,
            source_hash=canonical_hash(self.prepared._rules.skill(7020620)))
        f.actions['a'].update(effective_cost=3, replacement_slot=0)
        programs = forced_switch_programs.programs(self.prepared)
        self.assertIn(7160270, programs)
        context = build_research_context_v2(self.prepared, f.state, f.actions, program_overrides=programs)
        result = execute_research_turn_v2(self.prepared, f.state, f.actions, context, program_overrides=programs,
            damage_resolver=lambda *_: 0, status_damage_resolver=lambda *_: 0)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        team = result['state']['teams']['a']
        self.assertEqual(team['active_slot'], 0)
        incoming, outgoing = team['members']
        self.assertEqual(outgoing['energy'], 7)
        self.assertEqual(sum(Fraction(t['numerator'], t['denominator']) for t in outgoing['stat_modifiers'].get('patk', [])), 0)
        self.assertEqual(sum(Fraction(t['numerator'], t['denominator']) for t in incoming['stat_modifiers']['patk']), 1)
        self.assertEqual(incoming['stat_modifier_sources']['patk'][0]['source_id'], 7020620)
        self.assertEqual(len(incoming['buff_inheritance_receipts']), 1)
        self.assertEqual(sum(e.get('amount', 0) for e in result['events'] if e['op'] == 'energy.pay' and e.get('actor_side') == 'a'), 3)

    def test_swift_outcome_and_opponent_skill_hooks_share_the_committed_action_token(self):
        f = swift_fixture.HistorySwitchWiringTests()
        f.prepared = self.prepared
        with patch.object(traits, 'after_outcome', wraps=traits.after_outcome) as outcome, \
             patch.object(traits, 'after_opponent_skill', wraps=traits.after_opponent_skill) as opponent:
            f.test_swift_direct_defeat_proof_supplies_demon_extra_magic_loss()
        self.assertEqual(outcome.call_count, 1)
        self.assertEqual(opponent.call_count, 1)
        self.assertEqual(outcome.call_args.kwargs['token'], '4:entry:a:1:outcomes')
        self.assertEqual(opponent.call_args.kwargs['token'], '4:entry:a:1:outcomes:opponent.skill.after')
