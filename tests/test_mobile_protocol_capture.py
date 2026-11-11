"""Private, bounded sample capture and shared-decoder offline replay."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor/rkpp"))
from Crypto.Cipher import AES
from lab.mobile_protocol_capture import ProtocolSamples
from mobile.python import roco_mobile
from mobile.python.roco_mobile import OrderedMirror, ProtocolProbe
from scripts.replay_mobile_protocol import replay
from tests.test_mobile_backend import frame
from tests.test_mobile_envelopes import envelope


class ProtocolCaptureTests(unittest.TestCase):
    def test_fragmented_key_failure_and_post_failure_frames_are_replayable(self):
        now = [0.0]
        with tempfile.TemporaryDirectory() as temp:
            samples = ProtocolSamples(temp, ProtocolProbe, {"release_id": "synthetic-test"}, clock=lambda: now[0])
            mirror = OrderedMirror(None, None, lambda *_: None)
            backend = SimpleNamespace(samples=samples, mirror=mirror)
            key = b"1234567890abcdef"
            ack = frame(0x1002, b"\0\0" + key + b"\0" * 9)
            body = envelope(b"\x0a\x03abc", marker=b"\x01\x01", raw_opcode=0x0101, version=0)
            request = frame(0x4013, b"\0" * 4, AES.new(key, AES.MODE_CBC, bytes(range(16))).encrypt(body), seq=4)
            with patch.object(roco_mobile, "_backend", backend):
                self.assertTrue(roco_mobile.feed("game", "192.0.2.1", 8195, "s2c", ack[:11]))
                self.assertTrue(roco_mobile.feed("game", "192.0.2.1", 8195, "s2c", ack[11:]))
                roco_mobile.pause_analysis("synthetic parser failure")
                self.assertTrue(roco_mobile.feed("game", "192.0.2.1", 8195, "c2s", request))
            archive = samples.export({"decoder_ready": False}, {"state": "running"})
            with zipfile.ZipFile(archive) as exported:
                self.assertEqual(len(exported.namelist()), 3)
                manifest = json.loads(exported.read("manifest.json"))
                self.assertEqual(manifest["first_analysis_error"], "synthetic parser failure")
                self.assertEqual(hashlib.sha256(exported.read("streams.jsonl")).hexdigest(), manifest["streams_sha256"])
            report = replay(archive)
            self.assertEqual(report["frames"], 2)
            self.assertEqual(report["key_hits"], 1)
            self.assertEqual(report["pending_stream_bytes"], 0)
            self.assertEqual(report["frame_results"][-1]["opcode"], "0x0101")
            self.assertEqual(report["frame_results"][-1]["status"], "ok")
            self.assertNotIn(key.hex(), json.dumps(report))
            self.assertFalse(samples.status()["active"])

    def test_non_game_streams_are_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            samples = ProtocolSamples(temp, ProtocolProbe, {})
            samples.feed("http", "192.0.2.1", 80, "c2s", b"GET /private HTTP/1.1\r\n")
            samples.feed("tls", "192.0.2.1", 443, "c2s", b"\x16\x03\x03private")
            self.assertEqual(samples.status()["events"], 0)
            with self.assertRaises(ValueError):
                samples.export({}, {})
            samples.finish()
            self.assertEqual(samples.path.read_bytes(), b"")

    def test_failure_window_and_size_limit_preserve_the_start(self):
        now = [0.0]
        with tempfile.TemporaryDirectory() as temp:
            samples = ProtocolSamples(temp, ProtocolProbe, {}, clock=lambda: now[0])
            samples.feed("g", "192.0.2.1", 8195, "c2s", frame(0x1001))
            samples.mark_failure("failure")
            now[0] = 14
            samples.mark_failure("later failure")
            self.assertTrue(samples.status()["active"])
            now[0] = 16
            self.assertFalse(samples.status()["active"])
            self.assertEqual(samples.status()["reason"], "failure_window_complete")
            before = samples.path.read_bytes()
            samples.feed("g", "192.0.2.1", 8195, "c2s", frame(0x9001))
            self.assertEqual(samples.path.read_bytes(), before)
            samples = ProtocolSamples(temp, ProtocolProbe, {})
            with patch("lab.mobile_protocol_capture.MAX_ARCHIVE_BYTES", 400):
                for _ in range(10):
                    samples.feed("g", "192.0.2.1", 8195, "c2s", frame(0x1001))
            self.assertLessEqual(samples.status()["bytes"], 400)
            self.assertEqual(samples.status()["reason"], "size_limit")

    def test_capture_io_error_is_separate_from_parser_acceptance(self):
        with tempfile.TemporaryDirectory() as temp:
            samples = ProtocolSamples(temp, ProtocolProbe, {})
            samples._output.close()
            mirror = OrderedMirror(None, None, lambda *_: None)
            with patch.object(roco_mobile, "_backend", SimpleNamespace(samples=samples, mirror=mirror)):
                self.assertTrue(roco_mobile.feed("g", "192.0.2.1", 8195, "c2s", frame(0x1001)))
            self.assertTrue(mirror.accepting)
            self.assertEqual(samples.status()["reason"], "capture_error")

    def test_replay_rejects_tampered_stream(self):
        with tempfile.TemporaryDirectory() as temp:
            samples = ProtocolSamples(temp, ProtocolProbe, {})
            samples.feed("g", "192.0.2.1", 8195, "c2s", frame(0x1001))
            original = samples.export({}, {})
            altered = Path(temp) / "altered.zip"
            with zipfile.ZipFile(original) as source, zipfile.ZipFile(altered, "w") as target:
                for item in source.infolist():
                    content = source.read(item)
                    if item.filename == "streams.jsonl":
                        content += b"\n"
                    target.writestr(item, content)
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                replay(altered)

    def test_battle_payload_and_schema_decode_are_identical_with_mobile_policy(self):
        import Data
        import rkpp_analysis as analysis
        import rkpp_codec as codec
        import rkpp_proto_core as proto
        messages = Data.get_proto_schema()["messages"]
        resolve = lambda name: analysis._codec_schema_for_message(messages, name)
        payload = codec.encode_payload(resolve("ZoneBattleEnterNotify"),
            {"init_info": {"battle_id": 918}}, resolve_message=resolve)
        plain = b"\0" * 16 + (0x1316).to_bytes(4, "big") + b"\x55\xaa" + (1).to_bytes(4, "big") + payload
        padding = 16 - len(plain) % 16
        if padding < 6:
            padding += 16
        plain += b"\0" * (padding - 6) + b"tsf4g" + bytes([padding])
        packet = {"cmd": 0x4013, "seq": 1, "direction": "s2c",
                  "decrypt_mode": "Ivdecoder", "decrypted_body_hex": plain.hex()}
        full = proto.parse_record(packet)
        mobile = proto.parse_record(packet, payload_filter=roco_mobile.should_decode_mobile_payload)
        self.assertEqual(mobile, full)
        self.assertFalse(mobile.get("payload_deferred"))
        self.assertEqual(analysis.decode_record(mobile), analysis.decode_record(full))
        self.assertEqual(analysis.decode_record(mobile)["decoded"]["init_info"]["battle_id"], 918)


if __name__ == "__main__":
    unittest.main()
