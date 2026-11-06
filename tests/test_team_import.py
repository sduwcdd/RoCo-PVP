"""Batch diagnostics and observed-opponent search, without invented priors."""
import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import unittest
from unittest.mock import patch

from lab.server import Handler, import_request, load_catalog
from lab.team_import import parse_team_codes, recognize_opponent, search_opponent_teams


class TeamImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.raw = (Path(__file__).resolve().parents[1] / "data/reference/team-code-20261025/user-team-codes.txt").read_text(encoding="utf-8-sig")

    def test_batch_keeps_line_numbers_and_does_not_join_short_codes(self):
        result = parse_team_codes(self.raw, self.catalog)
        self.assertEqual(result["record_count"], 33)
        invalid = [r["line"] for r in result["results"] if not r["result"]["format_valid"]]
        self.assertEqual(invalid, [22, 38])
        self.assertTrue(all(not r["result"]["training_eligible"] for r in result["results"]))

    def test_nonblank_lines_preserve_whitespace_and_report_it(self):
        original = self.raw.splitlines()[0]
        padded = " " + original + " "
        r = parse_team_codes(padded, self.catalog)["results"][0]["result"]
        self.assertEqual(r["raw_code"], padded)
        self.assertFalse(r["format_valid"])

    def test_game_id_not_dex_number_and_ambiguous_names_not_guessed(self):
        c = {"snapshot_id": "test", "forms": [
            {"id": 101, "number": 7, "title": "甲", "name": {"zh": "甲"}},
            {"id": 202, "number": 8, "title": "甲（首领）", "name": {"zh": "甲"}}]}
        self.assertFalse(recognize_opponent("7", c)["importable"])
        self.assertEqual(len(recognize_opponent("甲", c)["members"][0]["candidates"]), 2)
        self.assertEqual(recognize_opponent("甲(首领)", c)["members"][0]["form_id"], 202)
        self.assertEqual(recognize_opponent("101", c)["members"][0]["form_id"], 101)

    def test_names_never_supply_hidden_configuration(self):
        r = recognize_opponent("3080", self.catalog)
        self.assertTrue(r["importable"])
        m = r["members"][0]
        self.assertEqual(m["move_ids"], [0, 0, 0, 0])
        self.assertTrue(all(v is None for v in m["talents"].values()))
        self.assertFalse(r["training_eligible"])

    def test_more_names_intersect_library_and_never_rank_as_probability(self):
        one = search_opponent_teams("火羽", self.catalog, self.raw)
        two = search_opponent_teams("火羽，罗隐", self.catalog, self.raw)
        self.assertGreater(one["matched_teams"], 0)
        self.assertLessEqual(two["matched_teams"], one["matched_teams"])
        self.assertTrue(set(m["library_id"] for m in two["matches"]).issubset(m["library_id"] for m in one["matches"]))
        first = next(m for m in two["matches"] if m["line"] == 1)
        self.assertFalse(first["result"]["importable"])
        self.assertIsNone(two["probability_source"])
        self.assertFalse(two["population_statistics"])

    def test_empty_search_lists_diagnostics_and_unknown_query_does_not_match(self):
        self.assertEqual(search_opponent_teams("", self.catalog, self.raw)["matched_teams"], 33)
        r = search_opponent_teams("并不存在的精灵", self.catalog, self.raw)
        self.assertFalse(r["query"]["importable"])
        self.assertEqual(r["matches"], [])

    def test_repeated_observed_species_require_repeated_roster_slots(self):
        r = search_opponent_teams("火羽，火羽", self.catalog, self.raw)
        self.assertEqual(r["matches"], [])

    def test_requests_ignore_client_claims_and_revalidate_snapshot(self):
        with patch("lab.server.load_catalog", return_value=(self.catalog, "verified-hash", None)) as mocked:
            r = import_request("/api/team-code/parse", {"code": "bad", "training_eligible": True, "importable": True})
        mocked.assert_called_once()
        self.assertFalse(r["format_valid"])
        self.assertFalse(r["training_eligible"])
        self.assertEqual(r["snapshot_sha256"], "verified-hash")

    def test_invalid_payload_sizes_and_counts(self):
        for text in (None, "", "x\n" * 201, "x" * 100001):
            with self.subTest(text_type=type(text).__name__), self.assertRaises(ValueError):
                parse_team_codes(text, self.catalog)
        self.assertFalse(recognize_opponent("甲，乙，丙，丁，戊，己，庚", self.catalog)["format_valid"])


class TeamImportHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class QuietHandler(Handler):
            def log_message(self, *args):
                pass
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def post(self, path, payload, origin=None):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            headers = {"Content-Type": "application/json"}
            if origin:
                headers["Origin"] = origin
            conn.request("POST", path, json.dumps(payload).encode(), headers)
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def test_batch_and_search_endpoints(self):
        status, result = self.post("/api/team-codes/parse", {"text": "bad\n\nbad"})
        self.assertEqual(status, 200)
        self.assertEqual([x["line"] for x in result["results"]], [1, 3])
        self.assertFalse(result["results"][0]["result"]["format_valid"])
        status, result = self.post("/api/opponent/search", {"text": "火羽，罗隐"})
        self.assertEqual(status, 200)
        self.assertTrue(result["matches"])
        self.assertIn("sha256", result["library_source"])

    def test_bad_requests_and_external_origin_are_rejected(self):
        self.assertEqual(self.post("/api/team-codes/parse", {"text": []})[0], 400)
        self.assertEqual(self.post("/api/team-code/parse", [], origin=None)[0], 400)
        self.assertEqual(self.post("/api/opponent/search", {"text": "火羽"}, "https://unrelated.example")[0], 403)

    def test_versioned_rule_plan_does_not_fallback_to_legacy_or_fake_damage(self):
        status, result = self.post("/api/rules/skill", {"skill_id": 7020440, "defender_form_id": 3016})
        self.assertEqual(status, 200)
        self.assertEqual(result["skill"]["power"], 95)
        self.assertEqual(result["skill"]["energy"], 4)
        self.assertFalse(result["battle_executable"])
        self.assertNotIn("damage", result)
        self.assertEqual(self.post("/api/rules/skill", {"skill_id": 1})[0], 400)


if __name__ == "__main__":
    unittest.main()
