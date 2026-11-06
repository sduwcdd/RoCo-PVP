"""Tests for damage_rule 35/38 table power (weight and stat-difference skills)."""
import unittest

from lab import power_rule_runtime as prr


def member(**overrides):
    base = {"member_id": "m1", "hp": 100, "max_energy": 10, "energy": 10, "skill_slots": [None, None, None, None],
            "weight": 0, "spd": 0, "pdef": 0, "patk": 50, "stat_modifiers": {}, "field_marks": {}}
    base.update(overrides)
    return base


class Rule35WeightTests(unittest.TestCase):
    def test_sugar_ball_diff_scales_up(self):
        # 7160150 砂糖弹球: |weight diff| buckets of 10 -> power 20/40/.../120
        attacker = member(weight=10)
        defender = member(weight=25)
        power = prr.rule_power(attacker, defender, 7160150, 0)
        self.assertEqual(power, 40)  # diff 15 -> level 1 -> para[2] = 40

    def test_tonnage_pressure_enemy_weight_flag(self):
        # 7020990 吨位压制: heavier enemy -> lower power (desc: 敌方体重越低，威力越高)
        attacker = member(weight=50)
        defender = member(weight=120)
        power = prr.rule_power(attacker, defender, 7020990, 0)
        self.assertEqual(power, 80)  # level 5 -> para[6] = 80
        defender = member(weight=5)
        power = prr.rule_power(attacker, defender, 7020990, 0)
        self.assertEqual(power, 160)  # level 0 -> para[1] = 160

    def test_counterweight_enemy_weight_flag(self):
        # 7021000 以重制重: heavier enemy -> higher power (desc: 敌方体重越高，威力越高)
        attacker = member(weight=50)
        defender = member(weight=5)
        power = prr.rule_power(attacker, defender, 7021000, 0)
        self.assertEqual(power, 80)  # level 0 -> para[1] = 80
        defender = member(weight=55)
        power = prr.rule_power(attacker, defender, 7021000, 0)
        self.assertEqual(power, 160)  # level 5 -> para[6] = 160

    def test_unconfigured_skill_returns_base_power_unchanged(self):
        # The power-query hook is an identity for skills without a rule 35/38
        # (otherwise every ordinary attack would see its power corrupted to None).
        self.assertEqual(prr.rule_power(member(), member(), 7070170, 100), 100)


class Rule38StatDiffTests(unittest.TestCase):
    def test_blitz_speed_diff(self):
        # Native 6 is the speed selector; the source-bound candidate uses 30-point tiers.
        attacker = member(spd=130)
        defender = member(spd=100)
        power = prr.rule_power(attacker, defender, 7150250, 0)
        self.assertEqual(power, 80)

    def test_blitz_no_advantage_keeps_base(self):
        attacker = member(spd=90)
        defender = member(spd=95)
        power = prr.rule_power(attacker, defender, 7150250, 0)
        self.assertEqual(power, 60)

    def test_sand_trap_pdef_diff(self):
        # Native 4 selects physical defense, not a four-point bucket width.
        attacker = member(pdef=200)
        defender = member(pdef=160)
        power = prr.rule_power(attacker, defender, 7080320, 0)
        self.assertEqual(power, 100)

    def test_candidate_positive_boundaries_and_cap_are_shared_by_both_skills(self):
        for difference, expected in ((0,60),(1,80),(30,80),(31,100),(60,100),(61,120),(270,190),(271,200),(1000,200)):
            for sid, stat in ((7080320,'pdef'),(7150250,'spd')):
                self.assertEqual(prr.rule_power(member(**{stat:100+difference}), member(**{stat:100}), sid, 0), expected)

    def test_negative_diff_floor(self):
        attacker = member(spd=50)
        defender = member(spd=200)
        power = prr.rule_power(attacker, defender, 7150250, 0)
        self.assertEqual(power, 60)


if __name__ == "__main__":
    unittest.main()
