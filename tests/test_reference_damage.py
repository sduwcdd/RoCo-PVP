"""Reference predictions are explicit hypotheses, not midpoint interpolation."""
from copy import deepcopy
import unittest

from lab.live_damage import _race_stats
from lab.numeric_candidates import captured_stat60
from tests.test_live_power import pet, quote


class ReferenceDamageTests(unittest.TestCase):
    def baseline(self, stat, multiplier):
        return captured_stat60(_race_stats(3001)[0][stat], 0, multiplier, stat)["stat_values"][0]

    def test_outgoing_reference_removes_negative_nature_and_investment(self):
        attacker = pet(side=0)
        defender = pet(side=1, natureUp="patk", natureDown="pdef")
        defender["battleStats"]["phyDef"] = 0
        before = deepcopy(defender)
        result = quote(7040370, attacker=attacker, defender=defender)
        baseline = pet(side=1, battleStatsBasis="natured_base")
        baseline["battleStats"]["phyDef"] = self.baseline("pdef", 1)
        expected = quote(7040370, attacker=attacker, defender=baseline)
        self.assertEqual(result["referenceMin"], expected["normalMin"])
        self.assertEqual(result["referenceMax"], expected["normalMax"])
        self.assertNotEqual(result["referenceMin"], (result["normalMin"] + result["normalMax"]) / 2)
        self.assertEqual(defender, before)

    def test_known_positive_nature_and_stat_buffs_are_preserved(self):
        attacker = pet(side=0)
        defender = pet(side=1, natureUp="pdef", natureDown="spd", battleStatsBasis="natured_base",
                       battleBuffs=[{"id": 20010030, "layers": 2}])
        defender["battleStats"]["phyDef"] = 0
        result = quote(7040370, attacker=attacker, defender=defender)
        baseline = deepcopy(defender)
        baseline["battleStats"]["phyDef"] = self.baseline("pdef", 1.2)
        expected = quote(7040370, attacker=attacker, defender=baseline)
        self.assertEqual((result["referenceMin"], result["referenceMax"]),
                         (expected["normalMin"], expected["normalMax"]))

    def test_incoming_reference_uses_enemy_attack_and_keeps_response_hit_units(self):
        attacker = pet(side=1, natureUp="matk", natureDown="spd", battleStatsBasis="natured_base",
                       battleBuffs=[{"id": 20010020, "layers": 2}])
        attacker["battleStats"]["magAtk"] = 0
        defender = pet(side=0)
        result = quote(7020470, attacker=attacker, defender=defender)
        baseline = deepcopy(attacker)
        baseline["battleStats"]["magAtk"] = self.baseline("matk", 1.2)
        expected = quote(7020470, attacker=baseline, defender=defender)
        self.assertEqual(result["referenceMin"], expected["normalMin"])
        self.assertEqual(result["referencePerHitMin"] * result["hits"], result["referenceMin"])
        self.assertEqual(result["response"]["referenceMin"], expected["response"]["normalMin"])


    def test_temporary_abu_level_below_sixty_keeps_the_pvp_star_policy(self):
        from lab.live_stat_model import stat_candidates, star_candidates
        subject = pet(petBaseId=5068, level=54)
        self.assertEqual(star_candidates(subject), [5])
        values = stat_candidates(subject, _race_stats(5068)[0], "patk", 0, None, None, 5)
        self.assertTrue(values)
        standard = stat_candidates({**subject, "level": 60}, _race_stats(5068)[0], "patk", 0, None, None, 5)
        self.assertLess(max(values), min(standard))
        self.assertEqual(star_candidates({**subject, "battleMode": "world"}), [0])
        self.assertEqual(quote(7040370, attacker=subject)["levelDamageCandidate"]["attackerLevel"], 54)

    def test_abu_reference_uses_battle_level_and_guardian_stacks(self):
        from lab.numeric_candidates import captured_abu_panel_values
        attacker = pet(side=1, petBaseId=5068, level=82, effectiveTraitId=280041,
                       natureUp="patk", natureDown="mdef", battleStatsBasis="natured_base",
                       battleBuffs=[{"id": 23000030, "layers": 22}])
        attacker["battleStats"]["phyAtk"] = 0
        defender = pet(side=0)
        before = deepcopy(attacker)
        result = quote(7040370, attacker=attacker, defender=defender)
        baseline = deepcopy(attacker)
        baseline["battleStats"]["phyAtk"] = captured_abu_panel_values(105, 0, 1.2, "patk", 82)[0]
        expected = quote(7040370, attacker=baseline, defender=defender)
        self.assertEqual(result["referenceMin"], expected["normalMin"])
        self.assertEqual(result["referenceMax"], expected["normalMax"])
        self.assertEqual(attacker, before)


if __name__ == "__main__":
    unittest.main()
