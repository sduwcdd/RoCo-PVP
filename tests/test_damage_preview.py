"""Tests for the naked damage preview endpoint (lab/damage_preview.py)."""
import math
import unittest
from fractions import Fraction

from lab.damage_preview import preview_damage
from lab.numeric_candidates import arena_documented_damage60
from lab.ruleset import BwikiRuleset
from lab.server import load_catalog
from lab.simulation import DEFAULT_SETTINGS, act_simulation, prepare_simulation, start_simulation
from lab.skill_hits import base_hits


def _member(form_id, slots, selected=None):
    values = {dim: 10 for dim in (selected or [])}
    return {
        "form_id": form_id,
        "max_energy": 30,
        "move_ids": list(slots),
        "talent_selection": {"selected": list(selected or []), "values": values},
        "nature_modifiers": {"up_id": 0, "down_id": 0},
    }


class DamagePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog, _, _ = load_catalog()
        cls.rules = BwikiRuleset(cls.catalog)
        raw_moves = cls.catalog["moves"]
        raw_forms = cls.catalog["forms"]
        moves = [move for move in (raw_moves.values() if isinstance(raw_moves, dict) else raw_moves)
                 if isinstance(move, dict)]
        forms = [form for form in (raw_forms.values() if isinstance(raw_forms, dict) else raw_forms)
                 if isinstance(form, dict)]
        form_ids = {form["id"] for form in forms}
        cls.attacker_form = 3004 if 3004 in form_ids else forms[0]["id"]
        attacker_types = cls.rules.form(cls.attacker_form)["types"]
        damage_moves = [move for move in moves
                        if move.get("kind") in ("physical", "magical")
                        and isinstance(move.get("power"), (int, float)) and move["power"] > 0]
        cls.same_type_move = next(move["id"] for move in damage_moves if move.get("type") in attacker_types)
        cls.off_type_move = next(move["id"] for move in damage_moves if move.get("type") not in attacker_types)
        cls.status_move = next(move["id"] for move in moves
                               if move.get("kind") not in ("physical", "magical"))
        cls.defender_form = 3876 if 3876 in form_ids else forms[0]["id"]
        cls.slots = [int(cls.same_type_move), int(cls.off_type_move), int(cls.status_move), 0]

    def _teams(self):
        return {
            "my": [_member(self.attacker_form, self.slots, ["hp", "patk", "spd"])],
            "opponent": [_member(self.defender_form, [0, 0, 0, 0], ["hp", "pdef", "spd"])],
        }

    def _preview(self, **extra):
        return preview_damage(self.catalog, {"teams": self._teams(), **extra})

    def test_damage_matches_shared_hud_expression(self):
        reply = self._preview()
        self.assertEqual(len(reply["results"]), 2)
        self.assertEqual(len(reply["non_damage_slots"]), 1)
        for row in reply["results"]:
            expected_hit = arena_documented_damage60(
                row["attack_panel"], row["defense_panel"], row["per_hit_power"],
                float(Fraction(row["type_multiplier"]["numerator"], row["type_multiplier"]["denominator"]))
                * float(row["same_type_bonus"]))["nominal_damage"]
            self.assertEqual(row["damage"], expected_hit * row["hits_executed"],
                             "多段按段数逐段取整后求和")
            self.assertEqual(row["hit_count"], len(row["hits_detail"]))
            self.assertEqual(row["defender_hp_after"], max(0, row["defender_hp_before"] - row["applied_damage"]))
            self.assertLessEqual(row["defender_hp_after"], row["defender_hp_before"])

    def test_same_type_bonus_applies_only_to_matching_type(self):
        reply = self._preview()
        same = next(row for row in reply["results"] if row["slot"] == 0)
        off = next(row for row in reply["results"] if row["slot"] == 1)
        self.assertEqual(same["same_type_bonus"], DEFAULT_SETTINGS["same_type_multiplier"])
        self.assertEqual(off["same_type_bonus"], 1)

    def test_unresolved_hud_query_stays_blocked_without_legacy_fallback(self):
        from unittest.mock import patch
        with patch("lab.hud_damage_runtime.HUDDamageResolver.explain", side_effect=ValueError("unresolved HUD state")):
            reply = self._preview()
        self.assertEqual(reply["results"], [])
        self.assertEqual(len(reply["blocked_slots"]), 2)
        self.assertTrue(all(row["reason"] == "unresolved HUD state" for row in reply["blocked_slots"]))

    def test_hp_override_drives_remaining_hp_and_lethal(self):
        reply = self._preview(hp={"b": 1})
        for row in reply["results"]:
            self.assertEqual(row["defender_hp_before"], 1)
            self.assertEqual(row["defender_hp_after"], 0)
            self.assertTrue(row["lethal"])
            self.assertGreater(row["damage"], 0)

    def test_percent_hp_keeps_one_hp_alive(self):
        reply = self._preview(hp_percent={"b": 1})
        defender_max = reply["defender"]["max_hp"]
        self.assertEqual(reply["defender"]["hp"], max(1, math.ceil(defender_max / 100)))
        self.assertGreaterEqual(reply["defender"]["hp"], 1)
        zero = self._preview(hp_percent={"b": 0})
        self.assertEqual(zero["defender"]["hp"], 0)

    def test_absolute_and_percent_conflict_is_rejected(self):
        with self.assertRaises(ValueError):
            self._preview(hp={"b": 10}, hp_percent={"b": 50})

    def test_excluded_effects_are_declared(self):
        reply = self._preview()
        joined = "".join(reply["excluded_effects"])
        self.assertIn("换人", joined)
        self.assertIn("防御", joined)
        self.assertIn("聚能", joined)
        self.assertIn("应对", joined)
        self.assertFalse(reply["policy"]["calibrated"])
        self.assertFalse(reply["calibrated"])

    def test_status_skill_is_reported_as_non_damage(self):
        reply = self._preview()
        self.assertEqual(reply["non_damage_slots"][0]["slot"], 2)
        self.assertIn("变化技能", reply["non_damage_slots"][0]["reason"])

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            preview_damage(self.catalog, {"teams": {"my": [], "opponent": []}})
        with self.assertRaises(ValueError):
            self._preview(hp={"b": 99999})
        with self.assertRaises(ValueError):
            self._preview(side="c")
        with self.assertRaises(ValueError):
            self._preview(active_slot={"b": 99})

    def test_stat_terms_scale_the_panel_linearly(self):
        base = self._preview()
        boosted = self._preview(stat_terms={"a": {"patk": [50, 50], "matk": [50, 50]}})
        for row_base, row_boost in zip(base["results"], boosted["results"]):
            self.assertEqual(row_boost["attack_panel_base"], row_base["attack_panel_base"])
            self.assertAlmostEqual(row_boost["attack_panel"], row_base["attack_panel_base"] * 2)
            self.assertEqual(row_boost["attack_stat_modifier_percent"], 100.0)
            expected = arena_documented_damage60(
                row_boost["attack_panel"], row_boost["defense_panel"], row_boost["per_hit_power"],
                float(Fraction(row_boost["type_multiplier"]["numerator"], row_boost["type_multiplier"]["denominator"]))
                * float(row_boost["same_type_bonus"]))["nominal_damage"]
            self.assertEqual(row_boost["damage"], expected * row_boost["hits_executed"])
            self.assertGreater(row_boost["damage"], row_base["damage"])
        self.assertEqual(boosted["stat_terms"], {"a": {"patk": [50.0, 50.0], "matk": [50.0, 50.0]}})
        self.assertTrue(any("线性相加口径一致" in note for note in boosted["warnings"]))

    def test_defense_debuff_lowers_the_defender_panel(self):
        base = self._preview()
        debuffed = self._preview(stat_terms={"b": {"pdef": [-30], "mdef": [-30]}})
        for row_base, row_debuff in zip(base["results"], debuffed["results"]):
            self.assertAlmostEqual(row_debuff["defense_panel"], row_base["defense_panel_base"] * 0.7)
            self.assertGreater(row_debuff["damage"], row_base["damage"])

    def test_stat_terms_reject_bad_input(self):
        for bad in ({"c": {"patk": 10}}, {"a": {"luck": 10}}, {"a": {"patk": "10"}},
                    {"a": {"patk": 2000}}, {"a": {"patk": [-150]}}, {"a": {"patk": [0, 0] * 20}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self._preview(stat_terms=bad)
        with self.assertRaises(ValueError):
            self._preview(stat_terms={"b": {"pdef": [-100]}})

    def test_side_swap_previews_the_other_direction(self):
        reply = self._preview(side="b")
        self.assertEqual(reply["side"], "b")
        # opponent carries no moves in this fixture, so nothing can be quoted
        self.assertEqual(reply["results"], [])

    def test_multi_hit_sequence_matches_engine_settlement(self):
        """The preview must equal what the engine actually settles, hit by hit."""
        teams = {
            "my": [_member(self.attacker_form, [7020480, 0, 0, 0], ["hp", "patk", "spd"])],
            "opponent": [_member(3001, [0, 0, 0, 0], ["hp", "pdef", "spd"])],
        }
        prepared = prepare_simulation(self.catalog, {"teams": teams, "settings": dict(DEFAULT_SETTINGS)})
        started = start_simulation(self.catalog, {"state": prepared["state"],
                                                  "settings": dict(DEFAULT_SETTINGS)})
        settled = act_simulation(self.catalog, {
            "state": started["state"], "settings": dict(DEFAULT_SETTINGS),
            "actions": {"a": {"kind": "skill", "slot": 0}, "b": {"kind": "recharge"}},
        })
        self.assertEqual(settled["status"], "applied", settled.get("blockers"))
        engine_hits = [event["damage"] for event in settled["events"] if event.get("op") == "damage"]
        engine_after = settled["state"]["teams"]["b"]["members"][0]["hp"]
        row = preview_damage(self.catalog, {"teams": teams})["results"][0]
        self.assertEqual(row["hit_count"], 3)
        self.assertEqual(row["hit_count_source"], "wiki_desc_parsed")
        self.assertEqual(len(engine_hits), row["hits_executed"], "段数必须与引擎结算的段数一致")
        self.assertEqual(row["hits_detail"] and [hit["nominal_damage"] for hit in row["hits_detail"]], engine_hits)
        self.assertEqual(row["damage"], sum(engine_hits))
        self.assertEqual(row["defender_hp_after"], engine_after)

    def test_hit_count_parser_ignores_conditional_clauses(self):
        self.assertEqual(base_hits(self.catalog, 7020480), (3, "wiki_desc_parsed"))  # 旋转突击 3连击
        self.assertEqual(base_hits(self.catalog, 7020470)[0], 1)  # 追打：1连击，应对改为3连击
        self.assertEqual(base_hits(self.catalog, 7140100)[0], 2)  # 反击拳：2连击，后手改3
        self.assertEqual(base_hits(self.catalog, 7080350)[0], 1)  # 震击：敌方获得连击数-3，不是段数
        self.assertEqual(base_hits(self.catalog, 7070280)[0], 1)  # 微型斥候：描述里是「不含连击」
        self.assertEqual(base_hits(self.catalog, 7020500)[0], 5)  # 乱打 5连击


if __name__ == "__main__":
    unittest.main()
