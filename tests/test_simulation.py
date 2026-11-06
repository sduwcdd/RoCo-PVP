"""Browser-to-engine contracts; constructed cases, not gameplay truth."""
from copy import deepcopy
import unittest

from lab.server import load_catalog, import_request
from lab.simulation import DEFAULT_SETTINGS, simulation_request


def member(form=3001, moves=None):
    return {"member_id": "original-browser-id", "form_id": form, "nature_id": 2,
        "move_ids": [7020360, 7020370, 7020640, 7030220] if moves is None else moves,
        "talent_selection": {"selected": ["hp", "patk", "spd"],
            "values": {"hp": 10, "patk": 10, "spd": 10}},
        "team_code": {"raw_markers": [80, 80, 80]}}


class SimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]

    def setUp(self):
        self.settings = {**DEFAULT_SETTINGS, "source_mode": "bwiki_only"}
        self.teams = {side: [member(), member()] for side in ("my", "opponent")}
        self.prepared = self.call("prepare", {"teams": self.teams})
        self.state = self.call("prepare", {"teams": self.teams})["state"]

    def call(self, operation, payload):
        return simulation_request("/api/simulation/" + operation,
                                  {"settings": self.settings, **payload}, self.catalog)

    def act(self, a=None, b=None, state=None):
        return self.call("act", {"state": state or self.state, "actions": {
            "a": a or {"kind": "skill", "slot": 0}, "b": b or {"kind": "skill", "slot": 0}}})

    def test_preparation_preserves_original_codes_and_generates_distinct_simulation_ids(self):
        before = deepcopy(self.teams)
        result = self.call("prepare", {"teams": self.teams})
        ids = [m["member_id"] for t in result["state"]["teams"].values() for m in t["members"]]
        self.assertEqual(len(set(ids)), 4)
        self.assertEqual(self.teams, before)
        actor = result["state"]["teams"]["a"]["members"][0]
        self.assertEqual(actor["original_configuration"]["team_code"]["raw_markers"], [80, 80, 80])
        self.assertNotIn("mdef", actor["original_configuration"]["talent_selection"]["values"])
        self.assertEqual(actor["panel_provenance"]["mode"], "estimated_candidate")
        self.assertFalse(result["training_eligible"])

    def test_empty_slots_and_unknown_nature_are_explicit_not_invented(self):
        self.teams["my"][0] = {"form_id": 3001, "move_ids": [0, 7020370]}
        result = self.call("prepare", {"teams": self.teams})
        actor = result["state"]["teams"]["a"]["members"][0]
        self.assertEqual(actor["skill_slots"], [0, 7020370, 0, 0])
        self.assertGreaterEqual(len(actor["setup_notes"]), 2)
        self.assertNotIn("talent_selection", actor["original_configuration"])

    def test_start_respects_edited_panels_then_executes_without_changing_request(self):
        actor = self.state["teams"]["a"]["members"][0]
        actor["stats"]["patk"] = 300
        before = deepcopy(self.state)
        started = self.call("start", {"state": self.state})
        self.assertEqual(started["state"]["teams"]["a"]["members"][0]["stats"]["patk"], 300)
        result = self.act(state=started["state"])
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["turn"], 2)
        self.assertTrue(result["damage_traces"])
        self.assertEqual(result["damage_traces"][0]["attack"]["base_panel"], 300)
        self.assertEqual(self.state, before)

    def test_recharge_empty_slots_clamps_at_source_cap_and_does_not_create_charge(self):
        for side in ("a", "b"):
            actor = self.state["teams"][side]["members"][0]
            actor.update(skill_slots=[0, 0, 0, 0], energy=7)
        result = self.act({"kind": "recharge"}, {"kind": "recharge"})
        self.assertEqual(result["status"], "applied", result["blockers"])
        for side in ("a", "b"):
            actor = result["state"]["teams"][side]["members"][0]
            self.assertEqual(actor["energy"], 10)
            self.assertIsNone(actor["charge"])
            self.assertEqual(actor["skill_slots"], [0, 0, 0, 0])

    def test_member_runtime_cap_overrides_client_fallback(self):
        self.teams["my"][0]["max_energy"] = 12
        self.teams["opponent"][0]["max_energy"] = 0
        result = self.call("prepare", {"teams": self.teams})
        teams = result["state"]["teams"]
        self.assertEqual(teams["a"]["members"][0]["max_energy"], 12)
        self.assertEqual(teams["a"]["members"][1]["max_energy"], 10)
        self.assertEqual(teams["b"]["members"][0]["max_energy"], 0)
        out = self.act({"kind": "recharge"}, {"kind": "recharge"}, result["state"])
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertEqual(out["state"]["teams"]["a"]["members"][0]["energy"], 12)
        self.assertEqual(out["state"]["teams"]["b"]["members"][0]["energy"], 0)

    def test_source_charge_prepares_for_zero_then_releases_once(self):
        teams = {side: [member(moves=[7100150])] for side in ("my", "opponent")}
        prepared = self.call("prepare", {"teams": teams})
        self.assertTrue(prepared["skills"]["7100150"]["supported"])
        first = self.act(state=prepared["state"])
        self.assertEqual(first["status"], "applied", first["blockers"])
        for side in ("a", "b"):
            actor = first["state"]["teams"][side]["members"][0]
            self.assertIsNotNone(actor["charge"])
            self.assertEqual(actor["energy"], 10)
        second = self.act(state=first["state"])
        self.assertEqual(second["status"], "applied", second["blockers"])
        for side in ("a", "b"):
            actor = second["state"]["teams"][side]["members"][0]
            self.assertIsNone(actor["charge"])
            self.assertEqual(actor["energy"], 7)
        self.assertTrue(second["damage_traces"])

    def test_switch_targets_incoming_and_preserves_bench_hp(self):
        before = deepcopy(self.state)
        result = self.act({"kind": "switch", "target_slot": 1})
        self.assertEqual(result["status"], "applied", result["blockers"])
        team = result["state"]["teams"]["a"]
        self.assertEqual(team["active_slot"], 1)
        self.assertEqual(team["members"][0]["hp"], before["teams"]["a"]["members"][0]["hp"])
        self.assertLess(team["members"][1]["hp"], team["members"][1]["max_hp"])

    def test_ko_manual_replacement_then_next_turn(self):
        self.state["teams"]["b"]["members"][0]["hp"] = 1
        result = self.act()
        self.assertEqual(result["status"], "awaiting_replacement", result["blockers"])
        replaced = self.call("replace", {"state": result["state"], "selections": {"b": 1}})
        self.assertEqual(replaced["status"], "applied", replaced["blockers"])
        self.assertEqual(replaced["state"]["turn"], 2)
        self.assertEqual(replaced["state"]["teams"]["b"]["members"][0]["hp"], 0)
        again = self.act(state=replaced["state"])
        self.assertEqual(again["status"], "applied", again["blockers"])

    def test_poison_end_phase_once_and_explicit_formula(self):
        actor = self.state["teams"]["a"]["members"][0]
        actor["statuses"]["poison"] = 2
        hp = actor["hp"]
        result = self.act({"kind": "recharge"}, {"kind": "recharge"})
        self.assertEqual(result["status"], "applied", result["blockers"])
        ticks = [e for e in result["events"] if e["op"] == "status.tick"]
        self.assertEqual(len(ticks), 1)
        self.assertEqual(result["state"]["teams"]["a"]["members"][0]["hp"], hp - hp * 6 // 100)
        self.assertEqual(result["status_damage_policy"], "max_hp_per_layer_floor_no_type_bonus_experiment")

    def test_profile_or_catalog_changes_cannot_continue_same_battle(self):
        self.settings["tie_break_side"] = "b"
        with self.assertRaises(ValueError): self.act()
        self.settings["tie_break_side"] = "a"
        self.state["simulation_profile"]["catalog_content_hash"] = "changed"
        with self.assertRaises(ValueError): self.act()
        self.state = self.prepared["state"]
        self.state["simulation_profile"]["engine_revision"] = "composable-battle-20261026-3"
        with self.assertRaisesRegex(ValueError, "试战机制已升级"):
            self.act()

    def test_bad_slots_duplicates_and_nonfinite_panels_rejected(self):
        self.teams["my"][0]["move_ids"] = [7020360, 7020360]
        with self.assertRaises(ValueError): self.call("prepare", {"teams": self.teams})
        for a in ({"kind": "skill", "slot": -1}, {"kind": "switch", "target_slot": 2}, []):
            with self.subTest(action=a), self.assertRaises(ValueError):
                self.call("act", {"state": self.state, "actions": {"a": a, "b": {"kind": "recharge"}}})
        self.state["teams"]["a"]["members"][0]["stats"]["patk"] = float("nan")
        with self.assertRaises(ValueError): self.act()

    def test_client_rule_injection_rejected(self):
        for key in ("program", "program_overrides", "damage_resolver", "predicted_damage", "context"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.call("prepare", {"teams": self.teams, key: {}})

    def test_demo_is_isolated_and_http_dispatch_works(self):
        before = deepcopy(self.teams)
        result = import_request("/api/simulation/demo", {"settings": self.settings})
        self.assertTrue(result["demo"])
        self.assertEqual(self.teams, before)
        self.assertEqual(len(result["state"]["teams"]["a"]["members"]), 2)
        self.assertTrue(all(m["original_configuration"]["demo_configuration"]
            for team in result["state"]["teams"].values() for m in team["members"]))


if __name__ == "__main__": unittest.main()
