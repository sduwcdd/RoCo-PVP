"""Source trait gates/grants cover planning and the actual switch dispatcher."""
from copy import deepcopy
import unittest

from lab import action_traits
from lab import trait_runtime
from lab.prepared_rules import prepare_rules
from lab.server import load_catalog
from lab.turn_plan import plan_joint_actions


class ActionTraitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.prepared = prepare_rules(cls.catalog)

    def test_swords_gate_current_slots_in_joint_planner_and_swift_scan(self):
        from tests.test_turn_plan import JointPlanTests
        fixture = JointPlanTests()
        fixture.catalog = self.catalog
        fixture.setUp()
        fixture.state['trait_policy'] = trait_runtime.POLICY
        actor = fixture.state['teams']['a']['members'][0]
        actor['skill_slots'] = [7020360, 7150080, 7020370, 0]
        for form, allowed in [(3545, [0]), (5021, [0, 2])]:
            actor['form_id'] = form
            for slot in (0, 1, 2):
                with self.subTest(form=form, slot=slot):
                    fixture.actions['a']['slot'] = slot
                    result = plan_joint_actions(self.prepared, fixture.state, fixture.actions)
                    self.assertEqual(result['status'], 'planned' if slot in allowed else 'blocked', result)
            candidates = action_traits.swift_candidates(self.prepared, fixture.state, actor, [0, 3, 1, None])
            self.assertFalse(candidates[1]['swift'])
            self.assertEqual(len(candidates), 4)

    def test_grants_use_source_base_cost_and_dragon_type_before_final_affordability(self):
        from tests.test_turn_plan import actor
        state = {'snapshot_id': self.prepared.snapshot_id, 'trait_policy': trait_runtime.POLICY}
        incoming = actor('a', form=3069)
        incoming['skill_slots'] = [7020370, 7150080, 0, 0]
        candidates = action_traits.swift_candidates(self.prepared, state, incoming, [8, 0, None, None])
        self.assertTrue(candidates[0]['action_trait']['swift_granted'])
        self.assertFalse(candidates[1]['action_trait']['swift_granted'])
        self.assertEqual(candidates[0]['effective_cost'], 8)
        self.assertEqual(self.prepared._components()[2].swift_first_slot(candidates, 5)['slot'], 1)
        self.assertEqual(candidates[0]['action_trait']['raw'], self.catalog['traits']['200129'])
        incoming.update(form_id=3209, skill_slots=[7020370, 7100120, 0, 0])
        candidates = action_traits.swift_candidates(self.prepared, state, incoming, [0, 1, None, None])
        self.assertFalse(candidates[0]['action_trait']['swift_granted'])
        self.assertTrue(candidates[1]['action_trait']['swift_granted'])

    def test_quick_hammer_executes_complete_nonintrinsic_skill_on_switch(self):
        from tests.test_switch_runtime import SwitchRuntimeTests
        from lab.research_phases import _fragment
        fixture = SwitchRuntimeTests()
        fixture.prepared = self.prepared
        fixture.setUp()
        fixture.state['trait_policy'] = trait_runtime.POLICY
        incoming = fixture.actor(1)
        incoming.update(form_id=3069, skill_slots=[0, 7020370, 0, 0])
        fixture.context.update(swift_policy=action_traits.SWIFT_POLICY,
            incoming_effective_costs=[None, 1, None, None],
            entry_timing='after_position_change_experiment',
            entry_skill_context=_fragment(self.prepared._rules.program(7020370)))
        before = deepcopy(fixture.state)
        result = fixture.run_switch(resolver=lambda *args: 7)
        self.assertEqual(result['status'], 'applied', result['blockers'])
        self.assertTrue(result['entry_skill_executed'])
        self.assertEqual(result['entry_swift']['slot'], 1)
        self.assertTrue(result['entry_swift']['action_trait']['swift_granted'])
        self.assertEqual(result['state']['teams']['a']['members'][1]['energy'], incoming['energy'] - 1)
        self.assertEqual(result['state']['teams']['b']['members'][0]['hp'], 293)
        self.assertEqual(result['entry_skill_assumptions']['core_magic_power_multiplier'],
                         {'numerator': 1, 'denominator': 1})
        self.assertEqual(fixture.state, before)

    def test_changed_whole_trait_source_and_forged_trait_identity_are_rejected(self):
        from tests.test_turn_plan import actor
        state = {'snapshot_id': self.prepared.snapshot_id, 'trait_policy': trait_runtime.POLICY}
        incoming = actor('a', form=3069)
        changed = deepcopy(self.catalog)
        changed['traits']['200129']['desc']['zh'] += '额外效果。'
        with self.assertRaisesRegex(ValueError, 'whole source changed'):
            action_traits.evidence(prepare_rules(changed), state, incoming)
        incoming['trait_id'] = 200173
        with self.assertRaisesRegex(ValueError, 'exact source form'):
            action_traits.evidence(self.prepared, state, incoming)


if __name__ == '__main__':
    unittest.main()
