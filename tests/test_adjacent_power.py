from copy import deepcopy
import unittest

from lab import adjacent_power_runtime as adjacent, skill_history_runtime as history
from lab.prepared_rules import PreparedRules
from lab.research_phases import _fragment
from lab.server import load_catalog
from tests import test_skill_history_runtime as fixtures


class AdjacentPowerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = PreparedRules(load_catalog()[0])
        cls.programs = adjacent.programs(cls.prepared)

    def fixture(self, slots):
        f = fixtures.SkillHistoryTests()
        f.prepared, f.programs = self.prepared, history.programs(self.prepared)
        state = f.fixture(slots)
        actors = {k:state['teams'][side]['members'][0] for k,side in (('self','a'),('opponent','b'))}
        for actor in actors.values():
            actor['types'] = self.prepared._rules.form(actor['form_id'])['types']
        context = {**_fragment(self.programs[7070030]), 'adjacent_power_policy':adjacent.POLICY,
            'turn':state['turn'], 'actor_side':'a', 'selected_skill_slot':1, 'mark_first_action':False,
            'mark_first_attack':False, 'opponent_kind':'physical', 'carried_effective_skill_costs':[2,4,3,None]}
        return f,state,actors,context

    def test_current_history_power_is_shared_pure_and_not_catalog_base(self):
        f,state,_,context = self.fixture([7040200,7070030,7020400,0])
        f.use(state,f.action(7040200,0),'blow')
        f.use(state,f.action(7020400,2),'approach')
        actors = {k:state['teams'][side]['members'][0] for k,side in (('self','a'),('opponent','b'))}
        before = deepcopy(actors)
        resolved = adjacent.resolve(self.programs[7070030],actors,context)
        self.assertEqual(resolved['operations'][0]['params']['power'],68)
        snapshot = resolved['adjacent_power_quote']['slots']
        self.assertEqual([snapshot[i]['power'] for i in (0,2)],[70,135])
        self.assertTrue(snapshot[0]['history_terms_hash'])
        self.assertEqual(actors,before)
        actors['self']['skill_slots'][3] = 7020360
        partial = adjacent.resolve(self.programs[7070030],actors,
            {**context,'carried_effective_skill_costs':[2,4,3,{'blocked':'unrelated choice cost unavailable'}]})
        self.assertEqual(partial['operations'][0]['params']['power'],68)
        self.assertEqual(partial['adjacent_power_quote']['slots'][3]['status'],'blocked')

    def test_difference_edge_cycle_and_unselected_choice_are_explicit(self):
        _,_,actors,context = self.fixture([7040200,7070200,7020400,0])
        result = adjacent.resolve(self.programs[7070200],actors,context)
        self.assertEqual(result['operations'][0]['params']['power'],40)
        actors['self']['skill_slots'] = [7070200,7040200,7020400,0]
        with self.assertRaisesRegex(ValueError,'interior'):
            adjacent.resolve(self.programs[7070200],actors,{**context,'selected_skill_slot':0})
        actors['self']['skill_slots'] = [7040200,7070030,7070200,7020400]
        with self.assertRaisesRegex(ValueError,'Recursive'):
            adjacent.resolve(self.programs[7070030],actors,{**context,'carried_effective_skill_costs':[2,4,4,3]})
        from lab.choice_runtime import choice_programs
        choice = next(iter(choice_programs(self.prepared)))
        actors['self']['skill_slots'] = [choice,7070030,7020400,0]
        with self.assertRaisesRegex(ValueError,'Unselected neighbor choice'):
            adjacent.resolve(self.programs[7070030],actors,context)
