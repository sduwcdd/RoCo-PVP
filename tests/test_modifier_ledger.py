import unittest
from tests.test_mechanism_compositions import MechanismCompositionTests
from lab import modifier_ledger as ledger
from lab import mechanism_runtime as m

class LedgerTests(unittest.TestCase):
    setUpClass=classmethod(MechanismCompositionTests.setUpClass.__func__)
    actors=MechanismCompositionTests.actors
    run_skill=MechanismCompositionTests.run_skill

    def test_repeated_status_stat_cost_keep_individual_events(self):
        for mid,op,count in [(7090470,'status.add',3),(7030490,'stat.modify',2),(7090320,'skill.cost.modify',2)]:
            out=self.run_skill(mid,self.actors())
            self.assertEqual(out['status'],'applied',(mid,out['blockers']))
            self.assertEqual(len([e for e in out['events'] if e['op']==op]),count)
            self.assertEqual(len([e for e in out['events'] if e['op']=='energy.pay']),1)
        self.assertEqual(m.cost(out['state']['opponent'],1,3,1),5)

    def test_dispel_preserves_trait_stat_and_hit_and_unknown_source_blocks(self):
        state=self.run_skill(7140290,self.actors())['state']
        member=state['self']
        member['stat_modifiers']['patk'].append({'numerator':50,'denominator':100})
        ledger.register_stat(member,'patk',source_kind='trait',source_id=123,source_hash='bound')
        member.setdefault('mechanism_flat_modifiers',[]).append({'op':'hits.flat','amount':1,'policy':m.POLICY,
            'hit_policy':m.HIT_POLICY,'source_trait_id':200128})
        state={'self':state['opponent'],'opponent':member}
        out=self.run_skill(7021100,state)
        self.assertEqual(out['status'],'applied',out['blockers'])
        self.assertEqual(out['state']['opponent']['stat_modifiers']['patk'],[{'numerator':50,'denominator':100}])
        self.assertEqual(m.modify_hits(out['state']['opponent'],2),3)
        state['opponent']['stat_modifier_sources']={}
        with self.assertRaisesRegex(ValueError,'source classification'):self.run_skill(7021100,state)

    def test_exchange_source_bundles_and_debuff_dispel(self):
        state=self.run_skill(7140290,self.actors(),response=True)['state']
        out=self.run_skill(7180180,state)
        self.assertEqual(out['status'],'applied',out['blockers'])
        self.assertEqual(out['state']['self']['stat_modifiers']['pdef'][0]['numerator'],-80)
        self.assertEqual(out['state']['opponent']['stat_modifiers']['patk'][0]['numerator'],80)
        out=self.run_skill(7050400,out['state'])
        self.assertEqual(out['status'],'applied',out['blockers'])
        self.assertEqual(out['state']['self']['stat_modifiers']['pdef'],[])
        self.assertEqual(m.cost(out['state']['self'],999,3,2),2)

if __name__=='__main__':unittest.main()
