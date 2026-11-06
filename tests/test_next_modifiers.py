from copy import deepcopy
import unittest
from tests.test_mechanism_compositions import MechanismCompositionTests
from lab import mechanism_runtime as m
from lab.research_phases import _fragment

class NextModifierTests(unittest.TestCase):
    setUpClass=classmethod(MechanismCompositionTests.setUpClass.__func__)
    actors=MechanismCompositionTests.actors
    run_skill=MechanismCompositionTests.run_skill

    def test_next_cost_consumes_once_without_consuming_new_grant(self):
        state=self.run_skill(7050230,self.actors())['state']
        self.assertEqual(m.cost(state['self'],7140140,8,1),2)
        p=self.programs[7140140]
        out=m.execute(p,state,{**_fragment(p),'turn':1,'resolved_energy_cost':0},lambda *a:1)
        self.assertEqual(out['status'],'applied',out['blockers'])
        self.assertEqual(m.cost(out['state']['self'],7140140,8,1),8)
        renewed=self.run_skill(7050230,state)['state']
        self.assertEqual(m.cost(renewed['self'],7140140,8,1),2)

    def test_next_attack_survives_status_and_failure_and_applies_whole_sequence(self):
        state=self.run_skill(7020700,self.actors())['state']
        state=self.run_skill(7150120,state)['state']
        self.assertEqual(m.modify_power(state['self'],100),170)
        before=deepcopy(state)
        def fail(*a):raise ValueError('test resolver error')
        out=self.run_skill(7020460,state,resolver=fail)
        self.assertEqual(out['status'],'blocked');self.assertEqual(out['state'],before)
        seen=[]
        out=self.run_skill(7020460,state,resolver=lambda p,a,c: seen.append(m.modify_power(a['self'],100)) or 1)
        self.assertEqual(out['status'],'applied',out['blockers']);self.assertEqual(seen,[170,170])
        self.assertEqual(m.modify_power(out['state']['self'],100),100)

    def test_reviewed_stat_combinations_and_response_replacements(self):
        for mid in (7030490,7080160,7080190,7080330,7140150,7140290,7180130,7180290,7180320):
            for response in (False,True):
                out=self.run_skill(mid,self.actors(),response=response)
                self.assertEqual(out['status'],'applied',(mid,out['blockers']))
        low=self.actors();low['self']['hp']=50
        self.assertEqual(self.run_skill(7180130,low)['state']['self']['stat_modifiers'],{})
        out=self.run_skill(7180320,self.actors(),response=True)
        self.assertEqual(out['state']['self']['stat_modifiers'],{})
        self.assertEqual(out['state']['opponent']['stat_modifiers']['patk'][0]['numerator'],-120)

if __name__=='__main__':unittest.main()
