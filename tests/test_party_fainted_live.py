"""Public death totals work without revealing all six opposing identities."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from lab.live_battle import BattleTracker
from lab import live_modifiers, trait_runtime


class PublicFaintedCountTests(unittest.TestCase):
    def tracker(self):
        t=BattleTracker()
        p=SimpleNamespace(pet_id=401,side=1,hp=100)
        p.apply_hp=lambda value,*args:setattr(p,"hp",value)
        t._pet_by_id={"401":p};t.teams={0:[],1:[p]}
        t._owners={0:"my-owner",1:"their-owner"}
        t._party_message_sequence=10
        t._update_party_life(0,{"pet_num":6,"dead_pet_num":1,"random_pet_num":0})
        t._update_party_life(1,{"pet_num":6,"dead_pet_num":3,"random_pet_num":0})
        return t,p

    def test_unknown_opponents_do_not_require_placeholder_pets(self):
        t,_=self.tracker()
        self.assertEqual(len(t.teams[1]),1)
        self.assertEqual(t._party_counts_context(0)["faintedCounts"],{"self":1,"opponent":3})
        self.assertEqual(t._party_counts_context(1)["faintedCounts"],{"self":3,"opponent":1})
        t.reset()
        self.assertEqual(t._party_counts_context(0),{})

    def test_death_duplicate_stale_absolute_sync_and_revival(self):
        t,p=self.tracker();t._party_message_sequence=11
        event={"dead_info":{"target_id":401,"dead_type":0}}
        t._apply_perform_item(event);t._apply_perform_item(event)
        self.assertEqual(t.party_life[1]["dead"],4)
        t._party_message_sequence=10
        t._update_party_life(1,{"pet_num":6,"dead_pet_num":3})
        self.assertEqual(t.party_life[1]["dead"],4)
        t._party_message_sequence=12
        t._apply_perform_item({"data_update":{"uin":"their-owner","role_simple":{"pet_num":6,"dead_pet_num":4}}})
        t._apply_perform_item(event)
        self.assertEqual(t.party_life[1]["dead"],4)
        t._party_message_sequence=13;p.hp=100
        t._apply_perform_item({})
        self.assertEqual(t.party_life[1]["dead"],3)
        t._apply_perform_item({})
        self.assertEqual(t.party_life[1]["dead"],3)

    def test_authoritative_summary_preceding_duplicate_death_is_not_added_twice(self):
        t,p=self.tracker();p.hp=0;t._party_message_sequence=11
        t._update_party_life(1,{"pet_num":6,"dead_pet_num":4})
        t._apply_perform_item({"dead_info":{"target_id":401,"dead_type":0}})
        self.assertEqual(t.party_life[1]["dead"],4)

    def test_random_pet_scope_and_invalid_counts_remain_unknown(self):
        t,_=self.tracker();t._party_message_sequence=11
        t._update_party_life(1,{"random_pet_num":1})
        counts=t._party_counts_context(0)["faintedCounts"]
        self.assertNotIn("opponent",counts)
        for bad in (None,-1,True,7):
            with self.assertRaises(ValueError):
                trait_runtime.party_fainted_count({"trait_team_fainted_counts":{"self":bad}})

    def test_wolf_defense_does_not_require_its_attack_only_condition(self):
        comp={"op":"stat.party_fainted","attributes":["patk","matk"],"scope":"both","cap":10,"percent_per":30}
        member={"trait_id":280024,"trait_team_roster":{"self":[],"opponent":[]}}
        row={"event":"stats.query","components":[comp]}
        with patch.object(trait_runtime,"_rows",return_value={280024:row}),patch.object(trait_runtime,"_passive",return_value=[comp]),patch.object(trait_runtime,"_entry_history_snapshot",return_value=None):
            self.assertEqual(live_modifiers._stat_terms(member,{}, {}, {},"pdef"),[])
            member["trait_team_fainted_counts"]={"self":4,"opponent":2}
            self.assertEqual(live_modifiers._stat_terms(member,{}, {}, {},"patk"),[{"numerator":180,"denominator":100}])
            member.pop("trait_team_fainted_counts")
            member["trait_team_roster"]={"self":[{"hp":100},{"hp":0}],"opponent":[{"hp":0}]}
            self.assertEqual(trait_runtime.stat_terms(member,"patk",None),[{"numerator":60,"denominator":100}])

    def test_native_wolf_stacks_take_priority_without_double_counting(self):
        pet={"petBaseId":5016,"level":60,"effectiveTraitId":280024,"currentHp":100,"maxHp":100,
             "battleStats":{"phyAtk":100,"phyDef":100,"magAtk":100,"magDef":100},"battleStatsBasis":"natured_base",
             "energy":10,"battleBuffs":[{"id":20011541,"layers":12}],
             "liveContext":{"turn":13,"rosters":{"self":[],"opponent":[]},"faintedCounts":{"self":4,"opponent":1}}}
        foe={"petBaseId":3001,"currentHp":100,"maxHp":100,"effectiveTraitId":0}
        with trait_runtime.query_scope():
            values,_=live_modifiers.panel_candidates(pet,"phyAtk",foe)
            defense,_=live_modifiers.panel_candidates(pet,"phyDef",foe)
        self.assertAlmostEqual(values[0],220)
        self.assertEqual(defense,[100.0])
