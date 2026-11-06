import json
from http.server import ThreadingHTTPServer
from threading import Thread
import unittest
from urllib.request import urlopen

from lab.pvp_rules import DEFAULT_SETTINGS, PROFILE_ID, load_pvp_rules, _validate_profile
from lab.simulation import settings, simulation_request


class SharedPvpRulesTests(unittest.TestCase):
    def test_conflicting_or_malformed_profile_is_rejected(self):
        for section, key, value in (("damage", "same_type_multiplier", 1.5),
                                    ("battle", "team_size", True),
                                    ("settings", "initial_energy", 10.0),
                                    ("uncertainty", "unknown_mechanisms", "assume_neutral")):
            profile = load_pvp_rules()
            profile[section][key] = value
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                _validate_profile(profile)

    def test_profile_is_owned_and_hud_settings_are_fixed(self):
        profile = load_pvp_rules()
        self.assertEqual(profile["profile_id"], PROFILE_ID)
        self.assertEqual(profile["settings"], DEFAULT_SETTINGS)
        self.assertEqual(profile["battle"]["team_size"], 6)
        self.assertEqual(profile["battle"]["initial_magic"], 4)
        self.assertEqual(profile["damage"]["same_type_multiplier"], DEFAULT_SETTINGS["same_type_multiplier"])
        profile["settings"]["initial_energy"] = 1
        self.assertEqual(load_pvp_rules()["settings"]["initial_energy"], 10)
        for key, value in (("damage_candidate", "arena_documented_damage60_v1"),
                           ("same_type_multiplier", 1.5), ("multi_hit_power", "source_power_total")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                settings({**DEFAULT_SETTINGS, key: value})

    def test_product_boundary_rejects_small_rosters_before_loading_catalog(self):
        with self.assertRaisesRegex(ValueError, "六只"):
            simulation_request("/api/simulation/prepare", {"teams": {"my": [{}], "opponent": [{}]}}, {})
        with self.assertRaisesRegex(ValueError, "6v6"):
            simulation_request("/api/simulation/start", {"state": {"teams": {}}}, {})

    def test_read_only_rules_endpoint_returns_the_same_profile(self):
        from lab.server import Handler

        class QuietHandler(Handler):
            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/api/pvp/rules", timeout=5) as response:
                self.assertEqual(json.load(response), load_pvp_rules())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
