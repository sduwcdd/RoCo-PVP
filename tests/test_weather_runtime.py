"""Weather integration regressions are constructed cases, never live calibration."""
from copy import deepcopy
from fractions import Fraction
import unittest

from lab.server import load_catalog
from lab.simulation import DEFAULT_SETTINGS, simulation_request
from lab.prepared_rules import PreparedRules
from lab.weather_runtime import (set_weather, advance_weather, apply_weather_skill,
    modify_cost, modify_power, check_freeze, apply_status, on_departure)

class WeatherRuntimeTests(unittest.TestCase):
    def test_eight_inclusive_rounds_and_input_isolation(self):
        weather, _ = set_weather(None, 7050250, 1)
        original = deepcopy(weather)
        for turn in range(1, 9):
            weather, _, events = advance_weather(weather, {}, turn)
            self.assertEqual(weather["remaining_rounds"] if weather else 0, 8-turn)
        self.assertEqual(events[-1]["op"], "weather.expired")
        self.assertEqual(original["remaining_rounds"], 8)

    def test_override_reset_extend_and_nonsetter(self):
        weather, _ = set_weather(None, 7050250, 1)
        weather, _, _ = advance_weather(weather, {}, 1)
        weather, events = apply_weather_skill(weather, 7050530, 2)
        self.assertEqual(weather["remaining_rounds"], 11)
        weather, _ = apply_weather_skill(weather, 7050530, 2, response_success=True)
        self.assertEqual(weather["remaining_rounds"], 19)
        weather, _ = set_weather(weather, 7110440, 2)
        self.assertEqual((weather["kind"], weather["remaining_rounds"]), ("thunder", 8))
        with self.assertRaises(ValueError):
            set_weather(weather, 7090110, 3)

    def test_shadow_stacks_never_change_observed_resources(self):
        weather, _ = set_weather(None, 7110440, 1)
        actor = {"member_id": "a", "types": ["水系"], "hp_percent": 70}
        weather, members, _ = advance_weather(weather, {"a": actor}, 1)
        self.assertEqual(members["a"]["weather_statuses"]["conductive"], 1)
        _, members, events = advance_weather(weather, members, 2)
        self.assertEqual(members["a"]["hp_percent"], 70)
        self.assertNotIn("hp", members["a"])
        self.assertEqual(members["a"]["weather_statuses"]["conductive"], 0)
        discharge = next(e for e in events if e.get("effect_op") == "conductive.damage")
        self.assertIsNone(discharge["amount"])
        self.assertEqual(discharge["damage_percent"], 25)
        self.assertNotIn("weather_statuses", actor)

    def test_freeze_strict_threshold_and_switch_policies(self):
        actor = {"member_id": "x", "hp": 10, "max_hp": 100, "weather_statuses": {"freeze": 2, "conductive": 1}}
        self.assertFalse(check_freeze(actor, "a"))
        on_departure(actor, "a")
        self.assertEqual(actor["weather_statuses"], {"freeze": 2, "conductive": 0})
        actor["hp"] = 9
        self.assertEqual(check_freeze(actor, "a")[0]["effect_op"], "freeze.exhaust")
        self.assertEqual(actor["hp"], 0)

    def test_type_immunity_and_source_damage_chart(self):
        actor = {"member_id": "x", "types": ["冰系"], "hp": 100, "max_hp": 100}
        events = apply_status(actor, "a", "freeze", 2, apply_effects=True)
        self.assertTrue(events[0]["immune"])
        actor["types"] = ["水系"]
        apply_status(actor, "a", "conductive", 1, apply_effects=True, type_multiplier=lambda *_: Fraction(2))
        events = apply_status(actor, "a", "conductive", 1, apply_effects=True, type_multiplier=lambda *_: Fraction(2))
        self.assertEqual(actor["hp"], 50)
        self.assertEqual(actor["weather_statuses"]["conductive"], 0)
        actor.update(hp=1, max_hp=1)
        apply_status(actor, "a", "conductive", 2, apply_effects=True, type_multiplier=lambda *_: Fraction(1))
        self.assertEqual(actor["hp"], 0)

    def test_thunder_immunity_is_not_general_conductive_immunity(self):
        member = {"member_id":"electric", "types":["电系"], "hp":100,"max_hp":100}
        weather, _ = set_weather(None, 7110440, 1)
        _, members, events = advance_weather(weather, {"a":member}, 1, apply_effects=True,
            type_multiplier=lambda *_: Fraction(1,2))
        self.assertTrue(events[0]["immune"])
        self.assertNotIn("weather_statuses", members["a"])
        apply_status(member, "a", "conductive", 1, apply_effects=True,
            type_multiplier=lambda *_: Fraction(1,2))
        self.assertEqual(member["weather_statuses"]["conductive"], 1)

class WeatherSimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.prepared = PreparedRules(cls.catalog)
        cls.settings = dict(DEFAULT_SETTINGS)
        cls.base = cls.call("prepare", {"teams": {s: [{"form_id": 3001,
            "move_ids": [7050250, 7050490, 7090370, 7110440]}, {"form_id": 3001, "move_ids": [7020370]}]
            + [{"form_id": 3001, "move_ids": [7020370]} for _ in range(4)]
            for s in ("my", "opponent")}})["state"]

    @classmethod
    def call(cls, name, payload):
        return simulation_request("/api/simulation/"+name, {"settings": cls.settings, **payload}, cls.catalog)

    def setUp(self):
        self.state = deepcopy(self.base)
        for side in ("a", "b"):
            actor = self.actor(side)
            actor["hp"] = actor["max_hp"] = 1000

    def actor(self, side="a", state=None):
        team = (state or self.state)["teams"][side]
        return team["members"][team["active_slot"]]

    def act(self, a, b, state=None):
        return self.call("act", {"state": state or self.state, "actions": {"a": a, "b": b}})

    def test_rain_affects_later_cost_power_single_payment_and_clone(self):
        before = deepcopy(self.state)
        out = self.act({"kind": "skill", "slot": 0, "priority": 1}, {"kind": "skill", "slot": 1})
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertEqual(out["state"]["weather"]["remaining_rounds"], 7)
        self.assertEqual([e["amount"] for e in out["events"] if e["op"] == "energy.pay"], [5, 2])
        self.assertEqual(out["damage_traces"][0]["effective_power_this_hit"], 192.5)
        self.assertEqual(self.state, before)
        self.assertEqual(out, self.act({"kind": "skill", "slot": 0, "priority": 1}, {"kind": "skill", "slot": 1}))

    def test_weather_setters_override_in_actual_action_order(self):
        out = self.act({"kind": "skill", "slot": 0, "priority": 1}, {"kind": "skill", "slot": 3})
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertEqual(out["state"]["weather"]["kind"], "thunder")
        self.assertEqual(self.actor("a",out["state"])["weather_statuses"]["conductive"], 1)

    def test_thunder_continues_next_turn_and_consumes_two_layers(self):
        first = self.act({"kind": "skill", "slot": 3, "priority": 1}, {"kind": "recharge"})
        second = self.act({"kind": "recharge"}, {"kind": "recharge"}, first["state"])
        self.assertEqual(second["status"], "applied", second["blockers"])
        actor = self.actor("a", second["state"])
        ratio = self.prepared._rules.type_multiplier("电系", actor["form_id"])["multiplier"]
        expected = 1000 * Fraction(1,4) * Fraction(ratio["numerator"], ratio["denominator"])
        self.assertEqual(actor["hp"], 1000-int(expected))
        self.assertEqual(actor["weather_statuses"]["conductive"], 0)
        self.assertEqual(second["state"]["weather"]["remaining_rounds"], 6)

    def test_snow_ko_then_replacement_does_not_repeat_weather_tick(self):
        self.actor("b")["hp"] = 99
        out = self.act({"kind": "skill", "slot": 2, "priority": 1}, {"kind": "recharge"})
        self.assertEqual(out["status"], "awaiting_replacement", out["blockers"])
        self.assertEqual(self.actor("b",out["state"])["hp"], 0)
        replaced = self.call("replace", {"state": out["state"], "selections": {"b": 1}})
        self.assertEqual(replaced["status"], "applied", replaced["blockers"])
        self.assertEqual(replaced["state"]["weather"]["remaining_rounds"], 7)
        self.assertNotIn("weather_statuses", self.actor("b", replaced["state"]))

    def test_sand_cost_ceil_priority_and_type_change(self):
        self.actor()["skill_slots"] = [7080210, 7060220, 0, 0]
        self.actor("b")["skill_slots"] = [7080450, 0, 0, 0]
        out = self.act({"kind": "skill", "slot": 0, "priority": 1}, {"kind": "skill", "slot": 0})
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertEqual([e["amount"] for e in out["events"] if e["op"] == "energy.pay"], [7, 2])
        self.actor("a",out["state"])["energy"] = 9
        next_out = self.act({"kind": "skill", "slot": 1}, {"kind": "skill", "slot": 0}, out["state"])
        self.assertEqual(next_out["status"], "applied", next_out["blockers"])
        self.assertEqual(next_out["action_order"], ["b", "a"])
        self.assertEqual(self.actor("a",next_out["state"])["energy"], 7)
        self.assertEqual(next_out["damage_traces"][-1]["type_matchup"]["attacking_type"], "地系")

    def test_huiliu_extends_weather_in_simulation(self):
        self.actor("b")["skill_slots"] = [7050530, 0, 0, 0]
        out = self.act({"kind": "skill", "slot": 0, "priority": 1}, {"kind": "skill", "slot": 0})
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertEqual(out["state"]["weather"]["remaining_rounds"], 11)
        self.assertTrue(any(e["op"] == "weather.extend" for e in out["events"]))

    def test_trait_rain_drain_uses_actual_damage(self):
        form = next(f for f in self.catalog["forms"] if f.get("trait_id") == 200144)
        actor = self.actor("b")
        actor.update(form_id=form["id"],types=form["types"], hp=500)
        out = self.act({"kind": "skill", "slot": 0, "priority": 1}, {"kind": "skill", "slot": 1})
        self.assertEqual(out["status"], "applied", out["blockers"])
        damage = out["damage_traces"][0]["actual_hp_loss"]
        self.assertEqual(self.actor("b",out["state"])["hp"], 500+int(damage*0.5))

    def test_trait_thunder_non_attack_skill_also_adds_stack(self):
        form = next(f for f in self.catalog["forms"] if f.get("trait_id") == 200303)
        actor = self.actor()
        actor.update(form_id=form["id"],types=form["types"])
        out = self.act({"kind": "skill", "slot": 3, "priority": 1}, {"kind": "recharge"})
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertEqual(self.actor("b",out["state"])["weather_statuses"]["conductive"], 0)
        self.assertTrue(any(e.get("effect_op") == "conductive.damage" for e in out["events"]))

    def test_weather_traits_modify_speed_attack_and_power(self):
        cases = [(200298, 7080210, 7080450, "sandstorm"),
                 (200213, 7050250, 7050490, "rain"),
                 (200311, 7090370, 7090460, "blizzard")]
        for trait, setter, attack, kind in cases:
            with self.subTest(trait=trait):
                state = deepcopy(self.base)
                form = next(f for f in self.catalog["forms"] if f.get("trait_id") == trait)
                actor = self.actor("b", state)
                actor.update(form_id=form["id"],types=form["types"], skill_slots=[attack, 0, 0, 0])
                state["weather"], _ = set_weather(None, setter, 1)
                for side in ("a", "b"):
                    member = self.actor(side, state)
                    member.update(hp=1000,max_hp=1000,speed=100)
                    member["stats"]["spd"] = 100
                out = self.act({"kind":"recharge"}, {"kind":"skill", "slot":0}, state)
                self.assertEqual(out["status"], "applied", out["blockers"])
                if kind == "sandstorm":
                    self.assertEqual(out["effective_speeds"]["b"], 150)
                elif kind == "rain":
                    self.assertEqual(out["damage_traces"][0]["attack"]["weather_multiplier"], 2)
                else:
                    self.assertEqual(out["damage_traces"][0]["effective_power_this_hit"], 270)

    def test_snow_switch_preserves_frozen_but_not_conductive_layers(self):
        weather, _ = set_weather(None, 7090370, 1)
        self.state["weather"] = weather
        actor = self.actor()
        actor["weather_statuses"] = {"freeze": 4, "conductive": 1}
        out = self.act({"kind":"switch", "target_slot":1}, {"kind":"recharge"})
        self.assertEqual(out["status"], "applied", out["blockers"])
        departed = out["state"]["teams"]["a"]["members"][0]
        self.assertEqual(departed["weather_statuses"], {"freeze":4,"conductive":0})
        self.assertEqual(self.actor("a",out["state"])["weather_statuses"]["freeze"], 2)

    def test_later_weather_discount_admits_low_energy_move(self):
        for setter, attack in ((7050250, 7050490), (7080210, 7080450)):
            with self.subTest(setter=setter):
                state = deepcopy(self.base)
                self.actor("a", state)["skill_slots"] = [setter, 0, 0, 0]
                self.actor("b", state).update(skill_slots=[attack, 0, 0, 0], energy=2)
                out = self.act({"kind":"skill", "slot":0, "priority":1},
                               {"kind":"skill", "slot":0}, state)
                self.assertEqual(out["status"], "applied", out["blockers"])
                self.assertEqual(self.actor("b", out["state"])["energy"], 0)
                self.assertEqual([e["amount"] for e in out["events"] if e["op"] == "energy.pay"][-1], 2)

    def test_weather_source_version_survives_expiry(self):
        state = deepcopy(self.state)
        state["simulation_profile"]["weather_rules_hash"] = "stale"
        state["weather"] = None
        self.actor("a", state)["weather_statuses"] = {"freeze": 2}
        with self.assertRaisesRegex(ValueError, "天气规则资料变化"):
            self.call("act", {"state":state, "actions":{"a":{"kind":"recharge"},"b":{"kind":"recharge"}}})
        fresh = deepcopy(self.state)
        fresh["simulation_profile"].pop("weather_rules_hash")
        out = self.call("start", {"state":fresh})
        self.assertIn("weather_rules_hash", out["state"]["simulation_profile"])
        self.assertNotIn("weather_rules_hash", fresh["simulation_profile"])

if __name__ == '__main__':
    unittest.main()
