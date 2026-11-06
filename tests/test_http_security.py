"""Regression checks for the desktop loopback HTTP boundary."""
import http.client
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

from lab.server import Handler
from lab.live_bridge import LiveBridge


class QuietHandler(Handler):
    def log_message(self, *args):
        pass


class HttpSecurityTests(unittest.TestCase):
    def test_release_hides_rule_exports_before_parsing_requests(self):
        with patch.dict(os.environ, {'ROCO_RELEASE': '1'}):
            for method, path in [('POST', '/api/rules/skill'), ('POST', '/api/research/game-skill'),
                                 ('GET', '/api/rules/coverage'), ('GET', '/native-data/skill.json')]:
                self.assertEqual(self.request(method, path), 404)

    def test_release_response_projection_preserves_ui_and_does_not_mutate_rules(self):
        from copy import deepcopy
        from lab.server import release_public_body
        original = {'state': {'hp': 4}, 'skills': {'1': {'supported': True}}, 'source_defaults': {'raw': 'private'},
                    'damage_traces': ['private'], 'events': [1]}
        before = deepcopy(original)
        actions = {'game_evidence': {'private': True}, 'generators': {'1': {'raw': 'private', 'pool_ids': [1]}},
                   'response_energy': {'7170100': {'effects': [{'op': 'energy.reduce', 'target': 'opponent', 'amount': 6, 'when': 'private'}]}}}
        with patch.dict(os.environ, {'ROCO_RELEASE': '1'}):
            result = release_public_body('/api/simulation/act', original)
            self.assertNotIn('source_defaults', result)
            self.assertNotIn('damage_traces', result)
            self.assertEqual(result['state'], original['state'])
            self.assertEqual(result['skills'], original['skills'])
            result = release_public_body('/api/action-mechanics', actions)
            self.assertNotIn('game_evidence', result)
            self.assertEqual(result['generators']['1'], {'pool_ids': [1]})
            self.assertEqual(result['response_energy']['7170100']['effects'], [{'op': 'energy.reduce', 'target': 'opponent', 'amount': 6}])
            self.assertIn('when', actions['response_energy']['7170100']['effects'][0])
        self.assertEqual(original, before)
        with patch.dict(os.environ, {'ROCO_RELEASE': '0'}):
            self.assertIs(release_public_body('/api/simulation/act', original), original)

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.port = cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(2)

    def request(self, method="GET", path="/missing", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request(method, path, body=b"{}" if method == "POST" else None, headers=headers or {})
            response = connection.getresponse()
            response.read()
            return response.status
        finally:
            connection.close()

    def test_normal_local_hosts_origins_and_cli_reach_routes(self):
        for method in ("GET", "POST"):
            self.assertEqual(self.request(method), 404)
            for host in ("localhost", "127.0.0.1", "[::1]"):
                authority = f"{host}:{self.port}"
                self.assertEqual(self.request(method, headers={"Host": authority, "Origin": "http://" + authority}), 404)

    def test_foreign_missing_or_wrong_port_headers_fail_before_routing(self):
        for method in ("GET", "POST"):
            for headers in ({"Host": "attacker.invalid"}, {"Host": ""}, {"Host": "localhost:1"},
                            {"Host": f"127.0.0.1:{self.port}.attacker.invalid"},
                            {"Origin": "null"}, {"Origin": "https://attacker.invalid"},
                            {"Origin": "http://127.0.0.1:1"}, {"Sec-Fetch-Site": "cross-site"}):
                with self.subTest(method=method, headers=headers):
                    self.assertEqual(self.request(method, headers=headers), 403)

    def test_duplicate_host_and_origin_are_rejected(self):
        for header, value in (("Host", f"localhost:{self.port}"), ("Origin", f"http://localhost:{self.port}")):
            connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
            try:
                connection.putrequest("GET", "/missing")
                connection.putheader(header, value)
                if header == "Origin":
                    connection.putheader(header, value)
                connection.endheaders()
                response = connection.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
            finally:
                connection.close()

    def test_release_rejects_relay_and_reset_even_when_blank(self):
        with patch.dict(os.environ, {"ROCO_RELEASE": "1"}), patch("lab.live_bridge.shared") as shared:
            for endpoint in ("status", "events"):
                for query in ("relay=", "relay=http://127.0.0.1:8765", "reset=", "reset=0", "reset=1"):
                    self.assertEqual(self.request(path=f"/api/live/{endpoint}?{query}"), 400)
            shared.assert_not_called()

    def test_development_allows_local_relay_only(self):
        bridge = Mock()
        bridge.state.return_value = {}
        bridge.poll.return_value = {}
        with patch.dict(os.environ, {"ROCO_RELEASE": "0"}), patch("lab.live_bridge.shared", return_value=bridge) as shared:
            for relay in ("http://127.0.0.1:8765", "http://localhost:8765", "http://[::1]:8765"):
                self.assertEqual(self.request(path="/api/live/status?relay=" + relay), 200)
                shared.assert_called_with(relay)
            shared.reset_mock()
            for relay in ("https://127.0.0.1:8765", "http://attacker.invalid:8765", "http://127.0.0.1",
                          "file:///tmp", "http://user@127.0.0.1:8765", "http://127.0.0.1:8765/path",
                          "http://127.0.0.1:99999", "http://127.0.0.1:abc"):
                self.assertEqual(self.request(path="/api/live/events?relay=" + relay), 400)
            shared.assert_not_called()

    def test_release_normal_live_request_is_preserved(self):
        bridge = Mock()
        bridge.state.return_value = {}
        with patch.dict(os.environ, {"ROCO_RELEASE": "1"}), patch("lab.live_bridge.shared", return_value=bridge) as shared:
            self.assertEqual(self.request(path="/api/live/status"), 200)
            shared.assert_called_once_with("http://127.0.0.1:8765")


class RelayTransportTests(unittest.TestCase):
    def test_redirects_are_not_followed_and_environment_proxy_is_not_used(self):
        hits = []

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/escaped")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:1", "no_proxy": ""}):
                self.assertIsNone(LiveBridge(f"http://127.0.0.1:{server.server_port}").health())
            self.assertEqual(hits, ["/health"])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(2)


if __name__ == "__main__":
    unittest.main()
