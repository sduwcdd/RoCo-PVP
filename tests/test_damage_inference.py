import unittest

from lab.damage_inference import infer_damage_candidates, _ally_panels, _selection_cases
from lab.numeric_candidates import arena_documented_damage60, arena_stat60
from lab.ruleset import BwikiRuleset
from lab.server import load_catalog
from lab.simulation import _estimate


class DamageInferenceTests(unittest.TestCase):
    def test_explicit_directions_do_not_require_a_nature_name(self):
        catalog, _, _ = load_catalog()
        form = BwikiRuleset(catalog).form(3001)
        selection = {"selected": ["hp", "matk", "mdef"], "values": {"hp": 10, "matk": 10, "mdef": 10},
                     "value_sources": {"hp": "user_default", "matk": "user_default", "mdef": "user_default"},
                     "selection_source": "user_selected", "default_value": 10}
        member = {"nature_id": None, "nature_modifiers": {"up_id": 1, "down_id": 6},
                  "talent_selection": selection}
        panels = _ally_panels(catalog, member, form)
        self.assertGreater(panels["hp"], 0)

    def test_exact_three_selections_retain_zero_and_all_unobserved_values(self):
        cases = _selection_cases({}, {})
        self.assertEqual(len(cases), 20)
        self.assertEqual(sum(c["combination_count"] for c in cases), 20 * 11**3)
        self.assertEqual(_selection_cases({}, {d: [1] for d in ("patk", "matk", "pdef", "mdef")}), [])
        fixed = {"talent_selection": {"selected": ["hp", "patk", "spd"],
                                      "values": {"hp": 0, "patk": 10, "spd": 7}}}
        cases = _selection_cases(fixed, {"hp": [0], "patk": [9, 10]})
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["combination_count"], 1)
        self.assertEqual(cases[0]["value_options"]["hp"], [0])

    def test_damage_both_directions_enumerates_all_matching_nature_talent_values(self):
        catalog, _, _ = load_catalog()
        rules = BwikiRuleset(catalog)
        my_form, opponent_form = rules.form(3001), rules.form(3080)
        selection = {"selected": ["hp", "matk", "mdef"], "values": {"hp": 10, "matk": 10, "mdef": 10},
                     "value_sources": {"hp": "user_default", "matk": "user_default", "mdef": "user_default"},
                     "selection_source": "user_selected", "default_value": 10}
        mine = {"member_id": "my", "form_id": 3001, "nature_id": 2, "nature_modifiers": {"up_id": 0, "down_id": 0},
                "talent_selection": selection, "confirmed": {"nature": True, "talents": {}, "moves": []}, "move_ids": [7060200]}
        opponent = {"member_id": "opp", "form_id": 3080, "nature_id": None, "nature_modifiers": {"up_id": 0, "down_id": 0},
                    "confirmed": {"nature": False, "talents": {}, "moves": []}, "move_ids": [7060200]}
        panels, _, _ = _estimate(catalog, mine, my_form)
        nature = next(row for row in catalog["natures"] if row["id"] == 2)
        opponent_matk = arena_stat60(opponent_form["stats"]["matk"], 7 * 6, .9, "matk")["stat_value"]
        opponent_mdef = arena_stat60(opponent_form["stats"]["mdef"], 5 * 6, 1, "mdef")["stat_value"]
        move = catalog["moves"]["7060200"]
        out_ratio = rules.type_multiplier(move["type"], opponent_form["id"])["multiplier"]
        in_ratio = rules.type_multiplier(move["type"], my_form["id"])["multiplier"]
        out_mult = out_ratio["numerator"] / out_ratio["denominator"] * (1.25 if move["type"] in my_form["types"] else 1)
        in_mult = in_ratio["numerator"] / in_ratio["denominator"] * (1.25 if move["type"] in opponent_form["types"] else 1)
        dealt = arena_documented_damage60(panels["matk"], opponent_mdef, move["power"], out_mult)["nominal_damage"]
        taken = arena_documented_damage60(opponent_matk, panels["mdef"], move["power"], in_mult)["nominal_damage"]
        snapshot = {"my": [mine], "opponent": [opponent]}
        session = {"snapshot_id": catalog["snapshot_id"], "teams": snapshot, "rounds": [{"turn": 1, "teams_snapshot": snapshot,
            "my": {"member_id": "my", "kind": "move", "move_id": 7060200, "received_damage": taken},
            "opponent": {"member_id": "opp", "kind": "move", "move_id": 7060200, "received_damage": dealt}}]}

        result = infer_damage_candidates(catalog, session)
        self.assertEqual(result["blockers"], [])
        inferred = result["members"][0]
        self.assertEqual(inferred["observed_dimensions"], ["matk", "mdef"])
        group = next(row for row in inferred["groups"] if row["nature_id"] == nature["id"])
        self.assertIn(7, group["talent_value_options"]["matk"])
        self.assertIn(5, group["talent_value_options"]["mdef"])
        self.assertGreater(inferred["combination_count"], 1)
        self.assertTrue(all(len(case["selected"]) == 3 for g in inferred["groups"] for case in g["selection_cases"]))
        self.assertFalse(result["probability_available"])


if __name__ == "__main__":
    unittest.main()
