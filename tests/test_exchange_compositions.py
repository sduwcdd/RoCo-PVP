from copy import deepcopy
import unittest
from tests.test_mechanism_compositions import MechanismCompositionTests
from lab import mechanism_runtime as m

class ExchangeCompositions(unittest.TestCase):
    setUpClass=classmethod(MechanismCompositionTests.setUpClass.__func__)
    actors=MechanismCompositionTests.actors
    run_skill=MechanismCompositionTests.run_skill

    def test_exchange_uses_simultaneous_fractions_and_nonlethal_floor(self):
        state=self.actors();state['self'].update(hp=90,max_hp=100);state['opponent'].update(hp=70,max_hp=200)
        before=deepcopy(state)
        out=self.run_skill(7180230,state)
        self.assertEqual(out['status'],'applied',out['blockers'])
        self.assertEqual((out['state']['self']['hp'],out['state']['opponent']['hp']),(35,180))
        self.assertEqual(state,before)
        state['self'].update(hp=1,max_hp=3);state['opponent'].update(hp=1,max_hp=1000)
        out=self.run_skill(7180230,state)
        self.assertEqual((out['state']['self']['hp'],out['state']['opponent']['hp']),(1,333))
        state['opponent']['hp']=0
        with self.assertRaises(ValueError):self.run_skill(7180230,state)

    def test_response_replacements_do_not_accumulate_normal_effect(self):
        for response in (False,True):
            for mid,op,normal,success,target in [(7020690,'speed.flat',80,160,'self'),(7030230,'power.flat',30,60,'self')]:
                out=self.run_skill(mid,self.actors(),response=response)
                self.assertEqual(out['status'],'applied',out['blockers'])
                self.assertEqual(m._flat(out['state'][target],op),success if response else normal)
            for mid,normal,success,target in [(7020760,1,3,'opponent'),(7050410,-2,-3,'self'),(7090130,0,3,'opponent')]:
                out=self.run_skill(mid,self.actors(),response=response)
                self.assertEqual(m.cost(out['state'][target],999,5,3),5+(success if response else normal))
            state=self.actors();state['self'].update(hp=1,max_hp=101)
            out=self.run_skill(7020730,state,response=response)
            self.assertEqual(out['state']['self']['hp'],51 if response else 26)

    def test_stat_sequences_and_true_damage_multiplier(self):
        state=self.actors()
        out=self.run_skill(7021080,state)
        self.assertEqual(out['status'],'applied',out['blockers'])
        self.assertEqual(len(out['state']['self']['stat_modifiers']['patk']),3)
        self.assertEqual(len([e for e in out['events'] if e['op']=='energy.pay']),1)
        state=self.run_skill(7021090,state)['state']
        out=self.run_skill(7021080,state)
        self.assertEqual(len(out['state']['self']['stat_modifiers']['patk']),6)
        for mid,attrs in [(7040440,{'patk':120,'matk':120,'pdef':-40,'mdef':-40}),
                          (7080360,{'pdef':160,'mdef':-60}),(7040430,{'pdef':-40})]:
            out=self.run_skill(mid,self.actors())
            self.assertEqual(out['status'],'applied',out['blockers'])
            self.assertEqual({k:v[0]['numerator'] for k,v in out['state']['self']['stat_modifiers'].items()},attrs)
        for response in (False,True):
            seen=[]
            out=self.run_skill(7070240,self.actors(),response=response,resolver=lambda p,*args: seen.append(p) or 1)
            self.assertEqual(out['status'],'applied',out['blockers'])
            self.assertEqual(seen[0]['power'],85)
            self.assertEqual(seen[0].get('damage_multiplier',{'numerator':1,'denominator':1}),
                             {'numerator':2 if response else 1,'denominator':1})

    def test_multi_resource_stat_and_dual_power_compositions(self):
        state=self.actors();state['self']['hp']=40
        out=self.run_skill(7021280,state)
        self.assertEqual(out['status'],'applied',out['blockers'])
        actor=out['state']['self']
        self.assertEqual((actor['hp'],actor['energy'],m.modify_speed(actor,100)),(50,8,110))
        self.assertEqual(set(actor['stat_modifiers']),{'matk','mdef'})
        out=self.run_skill(7180170,self.actors())
        self.assertEqual((m.modify_power(out['state']['self'],100),m.modify_power(out['state']['opponent'],100)),(120,80))

if __name__=='__main__':unittest.main()
