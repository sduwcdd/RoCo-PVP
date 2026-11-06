"""Whole-source batches use the shared effects; no server timing is claimed."""
from copy import deepcopy
import unittest

from lab import mechanism_runtime as mechanisms
from lab.prepared_rules import prepare_rules
from lab.research_phases import _fragment
from lab.server import load_catalog


class MechanismCompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.prepared = prepare_rules(cls.catalog)
        cls.programs = mechanisms.programs(cls.prepared)

    def actors(self):
        return {side: {'member_id': side, 'hp': 80, 'max_hp': 100, 'energy': 8, 'max_energy': 10,
            'types': ['普通系'], 'statuses': {}, 'stat_modifiers': {}} for side in ('self', 'opponent')}

    def run_skill(self, mid, state, *, response=False, resolver=None):
        program = self.programs[mid]
        context = {**_fragment(program), 'turn': 1, 'resolved_energy_cost': 1,
                   'response_success': response}
        return mechanisms.execute(program, state, context, resolver or (lambda *args: 1))

    def test_energy_theft_uses_actual_opponent_loss_and_receiver_cap_without_extra_payment(self):
        state = self.actors()
        state['self']['energy'] = 10
        state['opponent']['energy'] = 2
        before = deepcopy(state)
        out = self.run_skill(7170250, state)
        self.assertEqual(out['status'], 'applied', out['blockers'])
        self.assertEqual(out['state']['opponent']['energy'], 0)
        self.assertEqual(out['state']['self']['energy'], 10)
        transfer = next(e for e in out['events'] if e['op'] == 'energy.transfer')
        self.assertEqual((transfer['actual_amount'], transfer['received']), (2, 1))
        self.assertEqual(len([e for e in out['events'] if e['op'] == 'energy.pay']), 1)
        self.assertEqual(state, before)

    def test_conditional_hit_groups_read_response_poison_and_exact_half_hp(self):
        for mid, normal, changed in [(7020460, 2, 4), (7020470, 1, 3), (7140070, 2, 6),
                                     (7120280, 1, 3), (7180110, 3, 5)]:
            for matched in (False, True):
                with self.subTest(mid=mid, matched=matched):
                    state = self.actors()
                    if mid == 7120280:
                        state['opponent']['statuses']['poison'] = int(matched)
                    if mid == 7180110:
                        state['self']['hp'] = 49 if matched else 50
                    traces = []
                    def resolve(params, actors, context):
                        traces.append(deepcopy(params))
                        return 1
                    out = self.run_skill(mid, state, response=matched, resolver=resolve)
                    self.assertEqual(out['status'], 'applied', out['blockers'])
                    self.assertEqual(len(traces), changed if matched else normal)
                    self.assertEqual(traces[0]['hit_count'], changed if matched else normal)
                    # 2026-10-28 实机口径：多段技能每段都用完整威力。
                    self.assertEqual(traces[0]['power_basis'], 'source_power_per_hit')
                    self.assertEqual(len([e for e in out['events'] if e['op'] == 'energy.pay']), 1)

    def test_response_resources_keep_no_response_damage_and_reject_modified_composition(self):
        for response in (False, True):
            state = self.actors()
            state['self']['hp'] = 20
            out = self.run_skill(7030530, state, response=response)
            self.assertEqual(out['status'], 'applied', out['blockers'])
            self.assertEqual(out['state']['self']['hp'], 70 if response else 20)
            self.assertEqual(out['state']['self']['energy'], 10 if response else 7)
            out = self.run_skill(7170100, self.actors(), response=response)
            self.assertEqual(out['state']['opponent']['energy'], 2 if response else 8)
            self.assertEqual(out['state']['opponent']['hp'], 79)
        program = deepcopy(self.programs[7170250])
        program['mechanism_components'][0]['amount'] = 30
        program['mechanism_evidence']['components'][0]['amount'] = 30
        with self.assertRaisesRegex(ValueError, 'identity or source differs'):
            mechanisms.execute(program, self.actors(), {**_fragment(program), 'turn': 1})

    def test_public_action_path_resolves_status_response_and_four_hits(self):
        from tests.test_mechanism_integration import MechanismIntegrationTests
        fixture = MechanismIntegrationTests()
        fixture.catalog = self.catalog
        fixture.normal_form = next(row['id'] for row in self.catalog['forms'] if row['types'] == ['普通系'])
        state = fixture.prepare([7020460], [7020620])
        out = fixture.act(state, fixture.skill(), fixture.skill())
        self.assertEqual(len([e for e in out['events'] if e['op'] == 'damage' and e.get('skill_id') == 7020460]), 4)
        self.assertEqual(out['state']['turn'], state['turn'] + 1)
        self.assertFalse(out['training_eligible'])


if __name__ == '__main__':
    unittest.main()
