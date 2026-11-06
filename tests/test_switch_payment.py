"""Entry HP payment uses the same quote and atomic executor as manual actions."""
from copy import deepcopy
import unittest

from lab import trait_runtime
from lab.prepared_rules import prepare_rules
from lab.server import load_catalog


class SwitchPaymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = prepare_rules(load_catalog()[0])

    def fixture(self, hp=300):
        from tests.test_switch_runtime import SwitchRuntimeTests
        fixture = SwitchRuntimeTests()
        fixture.prepared = self.prepared
        fixture.setUp()
        fixture.enable_entry_attack(cost=3)
        fixture.state['trait_policy'] = trait_runtime.POLICY
        fixture.actor(1).update(form_id=3016, energy=1, max_hp=351, hp=hp)
        return fixture

    def test_selected_entry_pays_deficit_with_hp_and_real_energy_once(self):
        fixture = self.fixture()
        before = deepcopy(fixture.state)
        out = fixture.run_switch(resolver=lambda *_: 7)
        self.assertEqual(out['status'], 'applied', out['blockers'])
        actor = out['state']['teams']['a']['members'][1]
        self.assertEqual((actor['hp'], actor['energy']), (265, 0))
        quote = out['entry_skill_assumptions']['health_payment']
        self.assertEqual((quote['total_cost'], quote['paid_energy'], quote['paid_hp']), (3, 1, 35))
        self.assertEqual(len([e for e in out['events'] if e['op'] == 'hp.pay']), 1)
        self.assertEqual(len([e for e in out['events'] if e['op'] == 'energy.pay']), 1)
        self.assertEqual(fixture.state, before)

    def test_lethal_conversion_is_unaffordable_and_resolver_failure_rolls_back(self):
        fixture = self.fixture(hp=35)
        out = fixture.run_switch(resolver=lambda *_: 7)
        self.assertEqual(out['status'], 'applied', out['blockers'])
        self.assertFalse(out['entry_skill_executed'])
        self.assertEqual(out['state']['teams']['a']['members'][1]['hp'], 35)
        self.assertIn('Lethal', out['events'][0]['swift_candidates'][2]['health_payment_blocker'])
        fixture = self.fixture()
        def fail(*args):
            raise ValueError('resolver failed after quote')
        out = fixture.run_switch(resolver=fail)
        self.assertEqual(out['status'], 'blocked')
        self.assertEqual(out['state'], fixture.state)
        self.assertEqual(out['events'], [])


if __name__ == '__main__':
    unittest.main()
