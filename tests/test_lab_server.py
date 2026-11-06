import json
import hashlib
from pathlib import Path
import tempfile
import unittest

from lab.server import load_catalog, status, update_belief, public_catalog, policy_advice, import_request
from lab.effect_runtime import HOOKS
from lab.ruleset import BwikiRuleset


class LocalServiceTests(unittest.TestCase):
    def test_hud_projection_hides_diagnostics_without_deleting_backend_evidence(self):
        from lab.server import hud_payload
        info={"status":"conditional","known_talents":{"hp":{"selected":True,"values":[10]}},
              "known_nature":{"up":"hp"},"groups":[{"combination_count":1210}],"panel_fit":[1],"observations":[2]}
        raw={"runtime":{"myTeam":[{"configurationInference":info}],"enemyTeam":[]}}
        compact=hud_payload(raw)
        self.assertEqual(set(compact["runtime"]["myTeam"][0]["configurationInference"]),{"status","known_talents","known_nature"})
        self.assertIn("groups",raw["runtime"]["myTeam"][0]["configurationInference"])

    def test_cached_live_reads_and_local_png_routes_do_not_invoke_solver(self):
        from http.server import ThreadingHTTPServer
        from threading import Thread
        from unittest.mock import Mock, patch
        import urllib.request
        from lab import server as module
        class QuietHandler(module.Handler):
            def log_message(self,*args):pass
        feed=Mock();feed.state.return_value={"relay_ok":True};feed.snapshot.return_value={"runtime":{}}
        feed.tracker.snapshot.side_effect=AssertionError("request must not run analysis")
        server=ThreadingHTTPServer(("127.0.0.1",0),QuietHandler)
        worker=Thread(target=server.serve_forever,daemon=True);worker.start()
        base="http://127.0.0.1:"+str(server.server_address[1])
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with patch("lab.live_battle.shared_feed",return_value=feed),patch.object(module,"_SKILL_ICON_ALIAS",{}):
                self.assertNotIn("snapshot",json.load(opener.open(base+"/api/live/battle?state=1",timeout=2)))
                self.assertEqual(json.load(opener.open(base+"/api/live/battle",timeout=2))["snapshot"],{"runtime":{}})
                feed.tracker.snapshot.assert_not_called()
                for url in ("/roco-pet-avatars-id/3776.png","/roco-skill-icons/706026000.png"):
                    with opener.open(base+url,timeout=2) as response:
                        self.assertEqual(response.read(8),b'\x89PNG\r\n\x1a\n')
                        self.assertIn("max-age",response.headers["Cache-Control"])
        finally:
            server.shutdown();server.server_close();worker.join(2)

    def test_coverage_separates_structuring_component_support_battle_and_calibration(self):
        from lab.server import rules_coverage
        result = rules_coverage()
        self.assertEqual(result["configuration_schema"], "roco-rule-config-1")
        self.assertFalse(result["skill_runtime_natural_language_parsing"])
        self.assertEqual(result["capability_counts"]["skills"], {
            "description_structured": 172, "isolated_components_supported": 168,
            "full_battle_executable": 0, "real_game_calibrated": 0})
        self.assertEqual(result["capability_counts"]["traits"], {
            "description_structured": 0, "isolated_components_supported": 0,
            "full_battle_executable": 0, "real_game_calibrated": 0})

    def joint_request(self, skill_id):
        catalog = load_catalog()[0]
        program = BwikiRuleset(catalog).plan(skill_id)["program"]
        members = {side: {"member_id": side, "form_id": 3001, "hp": 100, "max_hp": 100,
                         "energy": 10, "max_energy": 20, "speed": 100, "entered_turn": 1,
                         "rooted": False, "charge": None, "skill_slots": [0, skill_id, 0, 0],
                         "statuses": {}, "stat_modifiers": {}} for side in ("a", "b")}
        fragment = {"mode": "isolated_skill_experiment", "snapshot_id": catalog["snapshot_id"],
                    "source_hash": program["source_hash"], "operation_order": "source_text_order_experiment",
                    "excluded_hooks": sorted(HOOKS), "unresolved_dependencies": [],
                    "energy_policy": "clamp_to_declared_max"}
        return {"state": {"snapshot_id": catalog["snapshot_id"], "turn": 2,
                          "teams": {side: {"active_slot": 0, "members": [member],
                                           "marks": {"positive": None, "negative": None}}
                                    for side, member in members.items()}},
                "actions": {side: {"kind": "skill", "slot": 1, "effective_cost": 2,
                                   "effective_priority": 1 if side == "a" else 0} for side in ("a", "b")},
                "context": {"mode": "isolated_joint_action_experiment", "excluded_hooks": sorted(HOOKS),
                            "fragments": {side: dict(fragment) for side in ("a", "b")}}}

    def test_joint_execution_api_applies_two_source_skills_without_claiming_a_full_turn(self):
        payload = self.joint_request(7030220)  # BWIKI 徒长; synthetic resource inputs.
        before = json.loads(json.dumps(payload))
        result = import_request("/api/rules/execute-actions", payload)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual([result["state"]["teams"][s]["members"][0]["energy"] for s in ("a", "b")], [18, 18])
        self.assertEqual(result["state"]["turn"], 2)
        self.assertEqual(payload, before)
        self.assertFalse(result["full_turn_executed"])
        self.assertFalse(result["training_eligible"])

    def test_http_execution_does_not_use_client_damage_as_a_formula(self):
        payload = self.joint_request(7020360)
        payload["predicted_damage"] = {"a": 7, "b": 8}
        result = import_request("/api/rules/execute-actions", payload)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["state"], payload["state"])
        self.assertEqual(result["events"], [])
        self.assertTrue(any("resolver" in issue for issue in result["blockers"]))

    def test_mirror_api_requires_floor_policy_and_executes_both_effects(self):
        payload = self.joint_request(7170280)
        for fragment in payload["context"]["fragments"].values():
            fragment["stat_policy"] = "record_signed_percentage_terms"
        result = import_request("/api/rules/execute-actions", payload)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["state"], payload["state"])
        self.assertEqual(result["events"], [])
        for fragment in payload["context"]["fragments"].values():
            fragment["energy_reduction_policy"] = "clamp_to_zero_experiment"
        result = import_request("/api/rules/execute-actions", payload)
        self.assertEqual(result["status"], "applied", result["blockers"])
        for side in ("a", "b"):
            member = result["state"]["teams"][side]["members"][0]
            self.assertEqual(member["energy"], 5)
            self.assertEqual(member["stat_modifiers"]["mdef"], [{"numerator": -50, "denominator": 100}])
        self.assertFalse(result["training_eligible"])

    def test_healing_api_requires_policies_and_runs_source_percent_when_explicit(self):
        payload = self.joint_request(7020640)
        for side in ("a", "b"):
            payload["state"]["teams"][side]["members"][0]["hp"] = 50
        result = import_request("/api/rules/execute-actions", payload)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["state"], payload["state"])
        for side in ("a", "b"):
            payload["context"]["fragments"][side]["hp_policy"] = {
                "percentage_basis": "declared_max_hp", "rounding": "exact", "cap": "clamp_to_declared_max"}
        result = import_request("/api/rules/execute-actions", payload)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual([result["state"]["teams"][s]["members"][0]["hp"] for s in ("a", "b")], [80, 80])
        self.assertFalse(result["calibrated"])
        self.assertFalse(result["training_eligible"])

    def test_joint_plan_request_never_invents_missing_state_or_actions(self):
        result = import_request("/api/rules/turn-plan", {"state": None, "actions": {"a": {"kind": "skill"}}})
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["plans"], {})
        self.assertFalse(result["battle_executable"])
        self.assertFalse(result["training_eligible"])
        self.assertIn("snapshot_sha256", result)

    def test_untrained_policy_has_no_fake_recommendations_or_probabilities(self):
        result = policy_advice()
        self.assertEqual(result["status"], "model_unavailable")
        self.assertEqual(result["actions"], [])
        self.assertIsNone(result["model"])
        self.assertFalse(result["training_allowed"])

    def test_missing_snapshot_does_not_enable_training(self):
        with tempfile.TemporaryDirectory() as d:
            result = status(d)
            self.assertFalse(result["training_allowed"])
            self.assertEqual(result["counts"]["forms"], 0)

    def test_snapshot_cannot_traverse_to_other_directory(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "latest.json").write_text(json.dumps({"path": "../outside"}))
            with self.assertRaises(ValueError):
                load_catalog(d)

    def test_empty_belief_is_not_a_population_probability(self):
        result = update_belief({})
        self.assertEqual(result["summary"]["status"], "prior_not_established")

    def test_discrete_damage_api_uses_supplied_mass_and_retains_replay_source(self):
        candidates = [{"id": key, "nature_id": i, "talents": {"hp": 10},
                       "moves": [7020360, 0, 0, 0], "prior": prior}
                      for key, i, prior in (("a", 1, 3), ("b", 2, 1))]
        event = {"id": "hit-1", "kind": "damage_distribution", "damage": 10,
                 "prediction_source": {"id": "synthetic-pmf", "snapshot_id": "fixture"},
                 "predictions": {"a": [{"damage": 10, "probability": .1}, {"damage": 20, "probability": .9}],
                                 "b": [{"damage": 10, "probability": .9}, {"damage": 20, "probability": .1}]}}
        result = update_belief({"candidates": candidates, "event": event})
        self.assertEqual(result["belief"]["schema_version"], 3)
        self.assertAlmostEqual(result["summary"]["candidates"][0]["posterior"], .25)
        self.assertAlmostEqual(result["summary"]["candidates"][1]["posterior"], .75)
        self.assertEqual(result["belief"]["events"][0]["prediction_source"], event["prediction_source"])
        self.assertFalse(result["prediction_verified"])
        self.assertFalse(result["training_allowed"])
        replayed = update_belief({"belief": result["belief"]})
        self.assertEqual(replayed["summary"], result["summary"])
        event["prediction_source"]["calibrated"] = True
        with self.assertRaises(ValueError):
            update_belief({"candidates": candidates, "event": event})

    def test_revealed_move_requires_confirmed_carried(self):
        with self.assertRaises(ValueError):
            update_belief({"event": {"kind": "revealed_move", "id": "t1", "move_id": 1}})

    def test_invalid_event_is_rejected(self):
        with self.assertRaises(ValueError):
            update_belief({"event": {"kind": "pretend_win"}})

    def test_corrupted_published_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d, "snap")
            folder.mkdir()
            (folder / "catalog.json").write_text('{"changed":true}')
            Path(d, "latest.json").write_text(json.dumps({"snapshot_id": "snap", "catalog_sha256": "0" * 64}))
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_catalog(d)

    def test_incomplete_snapshot_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d, "snap")
            folder.mkdir()
            raw = json.dumps({"validation": {"complete": False}}).encode()
            (folder / "catalog.json").write_bytes(raw)
            Path(d, "latest.json").write_text(json.dumps({"snapshot_id": "snap", "catalog_sha256": hashlib.sha256(raw).hexdigest()}))
            with self.assertRaisesRegex(ValueError, "integrity"):
                load_catalog(d)

    def test_ui_keeps_conditions_without_repeating_source_records(self):
        c = {"forms": [], "moves": {}, "details": {"1": {"learnset": {"legacy": [{"move": 1, "bloodline": "光"}]}, "source_record": {"raw": "large"}, "moves": [1]}}}
        result = public_catalog(c)
        self.assertEqual(result["details"]["1"]["learnset"]["legacy"][0]["bloodline"], "光")
        self.assertNotIn("source_record", result["details"]["1"])
        self.assertIn("source_record", c["details"]["1"])


if __name__ == "__main__":
    unittest.main()
