from copy import deepcopy
import unittest

from lab import payment_runtime as payment
from lab import trait_runtime as traits
from lab.prepared_rules import PreparedRules
from lab.research_phases import _fragment
from lab.server import load_catalog
from lab.skill_execution import execute_skill, preflight_skill
from tests.test_action_runtime import member


class PaymentRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = PreparedRules(load_catalog()[0])

    def actor(self):
        actor = member('payer', 3016)
        actor.update(trait_id=200100, trait_policy=traits.POLICY, energy=1, max_hp=351,
                     trait_config_hash=traits.CONFIG_HASH,
                     trait_source_hash=traits._rows()[200100]['record_hash'],
                     types=self.prepared._rules.form(3016)['types'])
        return actor

    def test_source_bound_quote_uses_real_energy_and_floor_after_total_deficit(self):
        actor = self.actor()
        before = deepcopy(actor)
        quote = payment.quote(self.prepared, actor, 7020360, 4)
        self.assertEqual((quote['paid_energy'], quote['missing_energy'], quote['paid_hp']), (1, 3, 52))
        self.assertEqual(quote['unrounded_hp'], {'numerator': 1053, 'denominator': 20})
        self.assertEqual(quote['sources'][0]['source_id'], 200100)
        self.assertEqual(actor, before)
        # The skill's own conversion applies even without a trait component.
        actor.pop('trait_policy')
        self.assertEqual(payment.quote(self.prepared, actor, 7180300, 4)['paid_hp'], 52)
        with self.assertRaisesRegex(ValueError, 'no reviewed'):
            payment.quote(self.prepared, actor, 7020360, 4)

    def test_wrapper_pays_hp_then_energy_once_and_failure_keeps_original(self):
        state = {'self': self.actor(), 'opponent': member('target')}
        state['opponent']['types'] = ['龙系']
        program = self.prepared._rules.program(7020360)
        quote = payment.quote(self.prepared, state['self'], 7020360, 4)
        context = {**_fragment(program), 'resolved_energy_cost': quote['paid_energy'], 'health_payment': quote}
        payment.preflight(program, state, context, preflight_base=preflight_skill, damage_resolver=lambda *_: 0)
        observed = []
        result = payment.execute(program, state, context, execute_base=execute_skill,
            damage_resolver=lambda _, current, __: observed.append((current['self']['hp'], current['self']['energy'])) or 0)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertEqual(observed, [(248, 0)])
        self.assertEqual([e['op'] for e in result['events']].count('hp.pay'), 1)
        self.assertEqual([e['amount'] for e in result['events'] if e['op'] == 'energy.pay'], [1])
        self.assertEqual(state['self']['hp'], 300)
        def fail(*_):
            raise ValueError('resolver failed')
        failed = payment.execute(program, state, context, execute_base=execute_skill, damage_resolver=fail)
        self.assertEqual(failed['status'], 'blocked')
        self.assertEqual(failed['state'], state)
        self.assertEqual(failed['events'], [])

    def test_lethal_zero_rounding_and_quote_resource_changes_are_blocked(self):
        actor = self.actor()
        actor['hp'] = 52
        with self.assertRaisesRegex(ValueError, 'Lethal'):
            payment.quote(self.prepared, actor, 7020360, 4)
        actor.update(hp=1, max_hp=1)
        with self.assertRaisesRegex(ValueError, 'Rounded zero'):
            payment.quote(self.prepared, actor, 7020360, 4)
        actor = self.actor()
        quote = payment.quote(self.prepared, actor, 7020360, 4)
        program = self.prepared._rules.program(7020360)
        state = {'self': actor, 'opponent': member('target')}
        context = {'resolved_energy_cost': 1, 'health_payment': quote}
        quote['paid_hp'] -= 1
        with self.assertRaisesRegex(ValueError, 'quote source'):
            payment.preflight(program, state, context, preflight_base=preflight_skill)
        context['health_payment'] = payment.quote(self.prepared, actor, 7020360, 4)
        actor['hp'] -= 1
        with self.assertRaisesRegex(ValueError, 'quote source'):
            payment.preflight(program, state, context, preflight_base=preflight_skill)
