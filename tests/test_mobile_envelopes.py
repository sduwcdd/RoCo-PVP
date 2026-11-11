"""Typed client-envelope compatibility and malformed-payload boundaries."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor/rkpp"))
import rkpp_analysis as analysis
import rkpp_proto_core as proto


MESSAGES = {
    "Fixture": {"fields": {
        "1": {"name": "value", "type": "uint32"},
        "2": {"name": "child", "type": "Child", "message": True},
        "3": {"name": "label", "type": "string"},
        "4": {"name": "blob", "type": "bytes"},
        "5": {"name": "values", "type": "uint32", "repeated": True},
    }},
    "Child": {"fields": {"1": {"name": "number", "type": "uint32"}}},
}


def envelope(payload, marker=b"\x11\x22", raw_opcode=0x8AAB0055, version=1):
    inner = b"\0" * 4 + raw_opcode.to_bytes(4, "big") + marker + b"\0\0\0\x01" + payload
    header = (4).to_bytes(4, "big") + b"\x55\xaa"
    header += (12 + len(inner)).to_bytes(4, "big") + b"\0\0" + version.to_bytes(4, "big")
    body = header + inner
    padding = 16 - len(body) % 16
    if padding < 6:
        padding += 16
    return body + b"\0" * (padding - 6) + b"tsf4g" + bytes([padding])


class MobileEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.info = patch.object(analysis, "lookup_opcode", return_value={"direction": "c2s", "name": "Fixture"})
        self.schema = patch.object(analysis, "_ensure_loaded", return_value=({}, {"messages": MESSAGES}))
        self.info.start()
        self.schema.start()
        self.addCleanup(self.info.stop)
        self.addCleanup(self.schema.stop)

    def parse(self, body, **overrides):
        common = {"direction": "c2s", "seq": 4, "first_frame": None, "first_time": None, **overrides}
        return proto._parse_ivdecoder_record(body, common)

    def test_variable_marker_and_opaque_opcode_require_direct_schema(self):
        for marker in (b"\x11\x22", b"\x7c\xa2", b"\x39\x63"):
            with self.subTest(marker=marker.hex()):
                record = self.parse(envelope(b"\x08\x07", marker))
                self.assertIsNotNone(record)
                self.assertEqual(record["opcode"], 0x55)
                self.assertEqual(record["magic"], int.from_bytes(marker, "big"))
                self.assertTrue(record["schema_validated_envelope"])

    def test_optional_fields_empty_nested_and_opaque_bytes_are_valid(self):
        for payload in (b"\x08\x00", b"\x12\x00", b"\x22\x02\xff\x00", b"\x2a\x02\x01\x02"):
            with self.subTest(payload=payload.hex()):
                self.assertIsNotNone(self.parse(envelope(payload)))

    def test_observed_zero_version_retains_full_schema_validation(self):
        # Synthetic payload with the version and marker from the 0.4 phone diagnostic.
        for version in (0, 1):
            with self.subTest(version=version):
                record = self.parse(envelope(b"\x08\x01", marker=b"\x01\x01", version=version))
                self.assertIsNotNone(record)
                self.assertTrue(record["schema_validated_envelope"])
                self.assertIsNone(self.parse(envelope(b"\x08", marker=b"\x01\x01", version=version)))
        self.assertIsNone(self.parse(envelope(b"\x08\x01", version=2)))

    def test_confirmed_mobile_layout_accepts_empty_and_preserves_unknown_fields(self):
        for payload, expected in [(b"", "complete"), (b"\x08\x01", "complete"),
                                  (b"\x30\x01", "unknown_fields"),
                                  (b"\x12\x02\x10\x01", "unknown_fields")]:
            with self.subTest(payload=payload.hex()):
                record = self.parse(envelope(payload, marker=b"\x00\x55", raw_opcode=0x780055, version=0))
                self.assertIsNotNone(record)
                self.assertEqual(record["transport_layout"], "tgcp_4013_mobile_c2s")
                self.assertEqual(record["payload_hex"], payload.hex())
                self.assertEqual(record["payload_schema_status"], expected)
                self.assertEqual(record["schema_validated_envelope"], expected == "complete")

    def test_mobile_compatibility_still_rejects_invalid_wire_and_unconfirmed_headers(self):
        for payload in (b"\x00\x00", b"\x30", b"\x32\x03x", b"\x0a\x01x",
                        b"\x12\x01\x08", b"\x08" + b"\xff" * 9 + b"\x02"):
            with self.subTest(payload=payload.hex()):
                self.assertIsNone(self.parse(envelope(payload, marker=b"\x00\x55", raw_opcode=0x780055, version=0)))
        for marker, raw_opcode, version in [(b"\x00\x55", 0x790055, 0),
                                             (b"\x00\x56", 0x780055, 0)]:
            self.assertIsNone(self.parse(envelope(b"\x30\x01", marker, raw_opcode, version)))

    def test_mobile_outer_word_is_preserved_without_version_assumptions(self):
        for word in (0, 1, 46384, 0xFFFFFFFF):
            record = self.parse(envelope(b"", marker=b"\x00\x55", raw_opcode=0x780055, version=word))
            self.assertIsNotNone(record)
            self.assertEqual(record["mobile_header_word"], word)
        record = self.parse(envelope(b"", marker=b"\x14\x28", raw_opcode=0x781428, version=46384))
        self.assertEqual(record["transport_layout"], "tgcp_4013_mobile_c2s")

    def test_confirmed_73_prefix_retains_wire_checks_and_unknown_fields(self):
        for payload, status in [(b"", "complete"), (b"\x08\x01", "complete"),
                                (b"\x30\x01", "unknown_fields")]:
            with self.subTest(payload=payload):
                record = self.parse(envelope(payload, marker=b"\x00\x55", raw_opcode=0x730055, version=110))
                self.assertIsNotNone(record)
                self.assertEqual(record["raw_opcode"], 0x730055)
                self.assertEqual(record["opcode"], 0x55)
                self.assertEqual(record["payload_schema_status"], status)
                self.assertEqual(record["mobile_header_word"], 110)
        for payload in (b"\x0a\x01x", b"\x08\x80", b"\x12\x01\x08"):
            with self.subTest(payload=payload):
                self.assertIsNone(self.parse(envelope(payload, marker=b"\x00\x55", raw_opcode=0x730055, version=110)))
        self.assertIsNone(self.parse(envelope(b"\x30\x01", marker=b"\x00\x56", raw_opcode=0x730055)))

    def test_payload_filter_is_scoped_and_full_decode_stays_identical(self):
        packet = {"cmd": 0x4013, "seq": 4, "direction": "c2s", "decrypt_mode": "Ivdecoder",
                  "decrypted_body_hex": envelope(b"\x08\x01").hex()}
        full = proto.parse_record(packet)
        self.assertEqual(proto.parse_record(packet, payload_filter=lambda op: op == 0x55), full)
        deferred = proto.parse_record(packet, payload_filter=lambda _op: False)
        self.assertTrue(deferred["payload_deferred"])
        self.assertEqual(deferred["payload_hex"], full["payload_hex"])
        self.assertTrue(deferred["root"]["clean"])
        self.assertNotIn("_payload_filter", deferred)
        self.assertEqual(proto.parse_record(packet), full)

    def test_confirmed_mobile_direction_and_missing_schema_remain_explicit(self):
        body = envelope(b"\x08\x01", marker=b"\x00\x55", raw_opcode=0x780055, version=0)
        with patch.object(analysis, "lookup_opcode", return_value={}):
            record = self.parse(body)
            self.assertEqual(record["direction"], "c2s")
            self.assertEqual(record["payload_schema_status"], "schema_missing")
            self.assertFalse(record["schema_validated_envelope"])
            self.assertEqual(record["payload_hex"], "0801")
        with patch.object(analysis, "lookup_opcode", return_value={"direction": "s2c", "name": "Fixture"}):
            record = self.parse(body)
            self.assertTrue(record["schema_direction_mismatch"])
            self.assertEqual(record["direction"], "c2s")

    def test_malformed_or_unknown_fields_cannot_certify_a_new_envelope(self):
        cases = [b"", b"\x08\x01\x08", b"\x08\x01\x80", b"\x30\x01",
                 b"\x0a\x01\x00", b"\x12\x01\x08", b"\x12\x02\x10\x01",
                 b"\x1a\x01\xff", b"\x2a\x01\x80"]
        for payload in cases:
            with self.subTest(payload=payload.hex()):
                self.assertIsNone(self.parse(envelope(payload)))

    def test_missing_nested_schema_and_unrecognized_opcode_are_rejected(self):
        with patch.object(analysis, "_ensure_loaded", return_value=({}, {"messages": {"Fixture": MESSAGES["Fixture"]}})):
            self.assertIsNone(self.parse(envelope(b"\x12\x00")))
        for info in ({}, {"direction": "s2c", "name": "Fixture"}, {"direction": "c2s", "name": "Missing"}):
            with self.subTest(info=info), patch.object(analysis, "lookup_opcode", return_value=info):
                self.assertIsNone(self.parse(envelope(b"\x08\x01")))

    def test_outer_version_sequence_length_and_padding_remain_required(self):
        valid = envelope(b"\x08\x01")
        self.assertIsNone(self.parse(valid, seq=5))
        self.assertIsNone(self.parse(valid, direction="s2c"))
        for offset in (4, 9, 10, len(valid) - 1):
            malformed = bytearray(valid)
            malformed[offset] ^= 1
            with self.subTest(offset=offset):
                self.assertIsNone(self.parse(bytes(malformed)))

    def test_known_e688_and_1428_keep_their_existing_path(self):
        for marker in (b"\xe6\x88", b"\x14\x28"):
            record = self.parse(envelope(b"\x08\x01", marker))
            self.assertIsNotNone(record)
            self.assertNotIn("schema_validated_envelope", record)
        record = self.parse(envelope(b"\x08\x01", b"\x39\x63", raw_opcode=0x55))
        self.assertEqual(record["transport_layout"], "tgcp_4013_live_c2s")


if __name__ == "__main__":
    unittest.main()
