"""Ordered stream boundary and shared HUD contract checks; no fabricated capture."""
import sys
import threading
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from collections import deque
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor/rkpp"))
from mobile.python.roco_mobile import OrderedMirror, ProtocolProbe, _Backend
from mobile.python import roco_mobile
from rkpp_network import DirectionState
from lab import release_paths


def frame(cmd, extra=b"", body=b"", seq=1):
    return (b"\x33\x66" + b"\0" * 4 + cmd.to_bytes(2, "big") + b"\0"
            + seq.to_bytes(4, "big") + (21 + len(extra)).to_bytes(4, "big")
            + len(body).to_bytes(4, "big") + extra + body)


class MobileStreamTests(unittest.TestCase):
    def test_decode_diagnostics_keep_structure_without_secrets(self):
        backend = object.__new__(_Backend)
        backend.decode_issues = deque(maxlen=12)
        packet = SimpleNamespace(direction="c2s", cmd=0x4013, seq=7,
                                 body=b"private encrypted content", header_extra=b"secret")
        for _ in range(15):
            backend.record_decode_issue({"decrypt_status": "parse_error:PRIVATE PAYLOAD",
                                         "decrypted_body_hex": b"PRIVATE PAYLOAD".hex()}, packet)
        self.assertEqual(len(backend.decode_issues), 12)
        issue = backend.decode_issues[-1]
        self.assertEqual(issue["category"], "parse_error")
        self.assertEqual(issue["body_bytes"], len(packet.body))
        self.assertEqual(issue["cipher_remainder"], len(packet.body) % 16)
        self.assertFalse(issue["trailer_valid"])
        self.assertNotIn("PRIVATE", str(issue))
        self.assertNotIn("secret", str(issue))

    def test_protocol_probe_replays_fragmented_header_and_both_directions(self):
        seen = []
        probe = ProtocolProbe(lambda direction, data: seen.append((direction, data)))
        request = frame(0x1001)
        acknowledgement = frame(0x1002, b"\0\0" + b"1234567890abcdef")
        probe.feed("c2s", request[:1])
        probe.feed("s2c", acknowledgement[:12])
        self.assertEqual(probe.protocol, "pending")
        probe.feed("s2c", acknowledgement[12:])
        probe.feed("c2s", request[1:])
        self.assertEqual(probe.protocol, "tgcp")
        self.assertEqual(seen, [("c2s", request[:1]), ("s2c", acknowledgement[:12]),
                               ("s2c", acknowledgement[12:]), ("c2s", request[1:])])
        self.assertFalse(probe.pending)

    def test_non_game_transports_are_bounded_and_never_reach_decoder(self):
        for first, kind in [(b"\x16\x03\x03", "tls"), (b"GET / HTTP/1.1\r\n", "http"),
                            (b"x" * 65536, "other")]:
            with self.subTest(kind=kind):
                probe = ProtocolProbe(lambda *_: self.fail("Not a game protocol"))
                for byte in first[:2]:
                    probe.feed("c2s", bytes([byte]))
                probe.feed("c2s", first[2:])
                probe.feed("s2c", b"x" * 65536)
                self.assertEqual(probe.protocol, kind)
                self.assertFalse(probe.prefix)
                self.assertFalse(probe.pending)

    def test_diagnostics_counters_remain_after_a_flow_closes(self):
        class Flow:
            def __init__(self, *_):
                self.analyzer = SimpleNamespace(key_hits=0, parsed_business_records=0)
                self.probe = SimpleNamespace(protocol="pending")
            def feed(self, *_):
                self.probe.protocol = "tgcp"
                self.analyzer.key_hits += 1
                self.analyzer.parsed_business_records += 2
        mirror = OrderedMirror(Flow, lambda: None, lambda *_: None)
        mirror.thread.start()
        try:
            mirror.submit("game", "192.0.2.1", 17000, "s2c", b"fixture")
            mirror.close_flow("game")
            mirror.pending.join()
            self.assertFalse(mirror.flows)
            self.assertEqual(mirror.totals["key_hits"], 1)
            self.assertEqual(mirror.totals["parsed_business_records"], 2)
            self.assertEqual(mirror.protocol_counts["tgcp"], 1)
        finally:
            mirror.stop()

    def test_real_frame_chunking_and_closed_flow_key_lifetime(self):
        observed = []
        class Flow:
            def __init__(self, flow_id, address, port):
                self.flow_id = flow_id
                self.states = {d: DirectionState(d) for d in ("c2s", "s2c")}
                self.seq = {"c2s": 1, "s2c": 1}
            def feed(self, direction, chunk):
                for parsed in self.states[direction].feed(self.seq[direction], chunk):
                    observed.append((self.flow_id, parsed.cmd, parsed.header_extra, parsed.body))
                self.seq[direction] += len(chunk)
        mirror = OrderedMirror(Flow, lambda: None, lambda *args: None)
        mirror.thread.start()
        try:
            one = frame(0x1002, b"\0\0" + b"1234567890abcdef")
            two = frame(0x4013, body=b"x" * 16)
            for index in range(len(one)):
                self.assertTrue(mirror.submit("one", "192.0.2.1", 17000, "s2c", one[index:index + 1]))
            self.assertTrue(mirror.submit("two", "192.0.2.1", 17000, "s2c", two[:11]))
            self.assertTrue(mirror.submit("one", "192.0.2.1", 17000, "c2s", two))
            self.assertTrue(mirror.close_flow("two"))
            self.assertTrue(mirror.submit("two", "192.0.2.1", 17000, "s2c", two))
            mirror.pending.join()
            self.assertEqual(observed, [("one", 0x1002, b"\0\0" + b"1234567890abcdef", b""),
                ("one", 0x4013, b"", b"x" * 16), ("two", 0x4013, b"", b"x" * 16)])
        finally:
            mirror.stop()

    def test_full_queue_is_explicit_and_capture_fails_closed(self):
        mirror = OrderedMirror(None, None, lambda: None, capacity=1)
        self.assertTrue(mirror.submit("one", "192.0.2.1", 17000, "c2s", b"first"))
        self.assertFalse(mirror.submit("one", "192.0.2.1", 17000, "c2s", b"second"))
        self.assertFalse(mirror.accepting)
        self.assertIn("queue full", mirror.error)
        self.assertFalse(mirror.close_flow("one"))

    def test_signed_java_bytes_keep_the_original_octets(self):
        mirror = OrderedMirror(None, None, lambda: None)
        self.assertTrue(mirror.submit("one", "2001:db8::1", 17000, "c2s", [-128, -1, 0, 127]))
        self.assertEqual(mirror.pending.get_nowait()[-1], b"\x80\xff\0\x7f")

    def test_unrelated_socket_close_preserves_battle_and_active_close_clears_it(self):
        backend = object.__new__(_Backend)
        resets = []
        backend.battle_flow = "game"
        backend.feed = SimpleNamespace(tracker=SimpleNamespace(reset=lambda: resets.append(True)),
                                       rows=[{"fixture": True}], _published_snapshot={"fixture": True})
        backend.server_module = SimpleNamespace(HUD_LOCK=threading.Lock(), HUD_SNAPSHOT={"payload": {"fixture": True}})
        backend.clear("auth-http")
        self.assertEqual(backend.feed._published_snapshot, {"fixture": True})
        self.assertFalse(resets)
        backend.clear("game")
        self.assertEqual(resets, [True])
        self.assertIsNone(backend.feed._published_snapshot)
        self.assertIsNone(backend.server_module.HUD_SNAPSHOT["payload"])

    def test_parser_error_clears_publication_and_stops_accepting(self):
        cleared = threading.Event()
        class Flow:
            def __init__(self, *args):
                pass
            def feed(self, *args):
                raise ValueError("Rejected real stream")
        mirror = OrderedMirror(Flow, lambda: None, cleared.set)
        mirror.thread.start()
        try:
            self.assertTrue(mirror.submit("one", "192.0.2.1", 17000, "c2s", b"data"))
            self.assertTrue(cleared.wait(2))
            self.assertFalse(mirror.accepting)
            self.assertIn("Rejected real stream", mirror.error)
        finally:
            mirror.stop()

    def test_analysis_pause_clears_estimates_without_claiming_vpn_stopped(self):
        cleared = threading.Event()
        mirror = OrderedMirror(None, lambda: None, cleared.set)
        backend = SimpleNamespace(mirror=mirror, capture_running=True, native_error="")
        mirror.thread.start()
        try:
            with patch.object(roco_mobile, "_backend", backend):
                self.assertTrue(roco_mobile.pause_analysis("decoder overloaded"))
                self.assertTrue(cleared.wait(2))
                self.assertFalse(mirror.accepting)
                self.assertTrue(backend.capture_running)
                self.assertIn("overloaded", mirror.error)
                self.assertTrue(roco_mobile.set_capture_state(True))
                self.assertFalse(roco_mobile.feed("game", "192.0.2.1", 17000, "s2c", b"incomplete"))
                self.assertTrue(roco_mobile.set_capture_state(False))
                self.assertFalse(backend.capture_running)
        finally:
            mirror.stop()


class MobileStorageTests(unittest.TestCase):
    def test_rejects_invalid_identity_and_relative_storage(self):
        identity = {"release_id": "mobile-test", "source_hash": "a" * 64}
        with patch.object(release_paths, "_MOBILE_CONTEXT", None), tempfile.TemporaryDirectory() as temp:
            for invalid in ({}, {**identity, "release_id": "invalid.id"},
                            {**identity, "source_hash": "not-a-sha256"}, {**identity, "extra": True}):
                with self.subTest(identity=invalid), self.assertRaises(ValueError):
                    release_paths.configure_mobile(temp, invalid)
            with self.assertRaises(ValueError):
                release_paths.configure_mobile("relative-storage", identity)
            self.assertIsNone(release_paths._MOBILE_CONTEXT)

    def test_binding_is_repeatable_but_immutable_and_identity_is_detached(self):
        identity = {"release_id": "mobile-test", "source_hash": "a" * 64}
        with patch.object(release_paths, "_MOBILE_CONTEXT", None), tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "private"
            release_paths.configure_mobile(root, identity)
            release_paths.configure_mobile(root, dict(identity))
            self.assertEqual(release_paths.user_root(), root.resolve())
            actual = release_paths.build_identity()
            self.assertEqual(actual, identity)
            actual["source_hash"] = "b" * 64
            identity["release_id"] = "changed-by-caller"
            self.assertEqual(release_paths.build_identity(),
                             {"release_id": "mobile-test", "source_hash": "a" * 64})
            with self.assertRaises(RuntimeError):
                release_paths.configure_mobile(root, {"release_id": "different-build", "source_hash": "a" * 64})


if __name__ == "__main__":
    unittest.main()
