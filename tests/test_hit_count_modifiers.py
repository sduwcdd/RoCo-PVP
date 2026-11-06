import unittest
from tests.test_mechanism_compositions import MechanismCompositionTests
from lab import mechanism_runtime as m


class HitCountTests(unittest.TestCase):
    setUpClass = classmethod(MechanismCompositionTests.setUpClass.__func__)
    actors = MechanismCompositionTests.actors
    run_skill = MechanismCompositionTests.run_skill

    def apply(self, mid, state):
        out=self.run_skill(mid,state)
        self.assertEqual(out['status'],'applied',out['blockers'])
        return out['state']

    def test_flat_then_percentage_and_single_damage_untouched(self):
        state=self.apply(7021090,self.actors())
        state=self.apply(7150140,state)
        self.assertEqual(m.modify_hits(state['self'],2),10)
        seen=[]
        out=self.run_skill(7020460,state,resolver=lambda params,*args: seen.append(params['hit_count']) or 1)
        self.assertEqual(out['status'],'applied',out['blockers'])
        self.assertEqual(seen,[10]*10)
        seen=[]
        out=self.run_skill(7090280,state,resolver=lambda params,*args: seen.append(params.get('hit_count',1)) or 1)
        self.assertEqual(seen,[1])

    def test_enemy_reduction_minimum_one_and_swift_grant(self):
        state=self.apply(7021050,self.actors())
        state=self.apply(7080350,state)
        self.assertEqual(m.modify_hits(state['opponent'],2),1)
        switched={'self':state['opponent'],'opponent':state['self']}
        seen=[]
        out=self.run_skill(7020460,switched,resolver=lambda params,*args: seen.append(params['hit_count']) or 1)
        self.assertEqual(out['status'],'applied',out['blockers'])
        self.assertEqual(seen,[1])
        state=self.apply(7150410,self.actors())
        self.assertEqual(m.modify_hits(state['self'],2),3)
        self.assertTrue(self.programs[7150410]['intrinsic_swift'])

    def test_wing_trait_once_after_success_and_preserves_source_hit_counts(self):
        from lab import trait_runtime
        member=self.actors()['self']
        member.update(form_id=3127,trait_id=200128,trait_policy=trait_runtime.POLICY)
        state={'trait_policy':trait_runtime.POLICY,'snapshot_id':self.prepared.snapshot_id,
            'teams':{'a':{'members':[member],'active_slot':0}}}
        first=m.after_skill_hits(self.prepared,state,'a',7150410,token='turn1:a:entry')
        self.assertEqual(len(first),1)
        self.assertEqual(m.after_skill_hits(self.prepared,state,'a',7150410,token='turn1:a:entry'),[])
        self.assertEqual(m.after_skill_hits(self.prepared,state,'a',7021090,token='turn2:a'),[])
        self.assertEqual(m.modify_hits(member,2),3)
        actors=self.actors();actors['self']=member
        seen=[]
        out=self.run_skill(7020460,actors,resolver=lambda p,*args: seen.append(p) or 1)
        self.assertEqual(out['status'],'applied',out['blockers'])
        self.assertEqual([(p['base_hit_count'],p['effective_hit_count']) for p in seen],[(2,3)]*3)

    def test_policy_tampering_blocks_without_mutating_input(self):
        state=self.apply(7021090,self.actors())
        state['self']['mechanism_flat_modifiers'][0]['hit_policy']='invented'
        with self.assertRaisesRegex(ValueError,'hit-count modifier policy'):
            self.run_skill(7020460,state)

if __name__=='__main__':unittest.main()
