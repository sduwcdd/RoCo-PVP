"""Small source-bound checks for persistent flat and first-action components."""
import unittest
from tests.test_mechanism_compositions import MechanismCompositionTests
from lab import mechanism_runtime as m
from lab.research_phases import _fragment


class ModifierTests(unittest.TestCase):
    setUpClass = classmethod(MechanismCompositionTests.setUpClass.__func__)
    actors = MechanismCompositionTests.actors
    run_skill = MechanismCompositionTests.run_skill
    def test_flat_speed_power_cost_and_percent_compositions(self):
        for mid, target, op, amount in [(7090300,'opponent','speed.flat',-90),
                (7150120,'self','speed.flat',120),(7090280,'opponent','speed.flat',-30),
                (7110340,'self','speed.flat',30),(7140140,'self','power.flat',40),
                (7150300,'self','power.flat',20)]:
            out=self.run_skill(mid,self.actors())
            self.assertEqual(out['status'],'applied',out['blockers'])
            actor=out['state'][target]
            self.assertEqual((m.modify_speed if op=='speed.flat' else m.modify_power)(actor,200),200+amount)
        for mid,target,stat,percent,delta in [(7020670,'opponent','patk',-60,-60),(7080370,'self','pdef',140,-30)]:
            out=self.run_skill(mid,self.actors())
            self.assertEqual(out['status'],'applied',out['blockers'])
            actor=out['state'][target]
            self.assertEqual(actor['stat_modifiers'][stat],[{'numerator':percent,'denominator':100}])
            self.assertEqual(m.modify_speed(actor,200),200+delta)
        for mid,amount in [(7090120,1),(7090150,2)]:
            out=self.run_skill(mid,self.actors())
            self.assertEqual(out['status'],'applied',out['blockers'])
            self.assertEqual(m.cost(out['state']['opponent'],123,3,99),3+amount)

    def test_priority_and_first_action_power(self):
        for mid,delta in [(7020970,1),(7021020,-1),(7150390,1),(7020980,1)]:
            self.assertEqual(m.modify_priority(self.programs[mid],0),delta)
        for mid,delta in [(7110180,40),(7020980,30)]:
            for first in (True,False):
                seen=[];p=self.programs[mid]
                def resolve(params,*args):
                    seen.append(params['power']);return 1
                out=m.execute(p,self.actors(),{**_fragment(p),'turn':1,'resolved_energy_cost':1,'mark_first_action':first},resolve)
                self.assertEqual(out['status'],'applied',out['blockers'])
                self.assertEqual(seen,[p['mechanism_record']['power']+(delta if first else 0)])
        self.assertTrue(self.programs[7150300]['intrinsic_swift'])

if __name__=='__main__':unittest.main()
