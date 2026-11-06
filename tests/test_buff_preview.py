"""Buff percentage carry-over used by the damage preview panel."""
from __future__ import annotations

import unittest
from fractions import Fraction

from lab import damage_preview
from lab.buff_preview import CHANNELS, move_buffs


class BuffPreviewTests(unittest.TestCase):
    def test_self_attack_buff_becomes_percent_term(self):
        buffs = move_buffs(7020620)
        self.assertEqual(len(buffs), 1)
        buff = buffs[0]
        self.assertEqual(buff["target"], "self")
        self.assertEqual(buff["percents"], {"patk": 10.0})
        self.assertEqual(buff["buff_id"], 20010010)

    def test_self_magic_buff_becomes_percent_term(self):
        buff = move_buffs(7020630)[0]
        self.assertEqual(buff["target"], "self")
        self.assertEqual(buff["percents"], {"matk": 10.0})

    def test_enemy_defence_debuff_is_negative_and_opponent_targeted(self):
        buffs = {b["name"]: b for b in move_buffs(7020680)}
        self.assertEqual(len(buffs), 2)
        for name in ("物防等级降低", "魔防等级降低"):
            self.assertEqual(buffs[name]["target"], "opponent")
        self.assertEqual(buffs["物防等级降低"]["percents"], {"pdef": -10.0})
        self.assertEqual(buffs["魔防等级降低"]["percents"], {"mdef": -10.0})

    def test_non_channel_buffs_are_not_offered(self):
        # 聒噪 raises skill cost, 防御 is a defence action: neither touches a panel term.
        self.assertEqual(move_buffs(7020650), [])
        self.assertEqual(move_buffs(7020780), [])

    def test_unknown_skill_returns_nothing(self):
        self.assertEqual(move_buffs(999999), [])

    def test_percent_is_the_preview_linear_term(self):
        """+10% must mean ratio 1.10, the same as a hand-typed 10 in the input box."""
        panel, total = damage_preview._panel_with_terms(200, [Fraction(str(10.0))])
        self.assertEqual(panel, 220.0)
        self.assertEqual(total, 10.0)
        panel, total = damage_preview._panel_with_terms(200, [Fraction(str(-10.0))])
        self.assertEqual(panel, 180.0)

    def test_every_offered_channel_is_one_the_preview_understands(self):
        for buffs in (move_buffs(7020680) + move_buffs(7020620)):
            self.assertTrue(set(buffs["percents"]).issubset(set(CHANNELS)))


if __name__ == "__main__":
    unittest.main()
