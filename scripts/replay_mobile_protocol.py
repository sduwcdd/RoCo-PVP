"""Replay an explicitly exported mobile protocol sample with the shared decoder."""
from __future__ import annotations

import argparse
from collections import Counter, deque
import hashlib
import ipaddress
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor/rkpp"))

from lab.mobile_protocol_capture import FORMAT, MAX_ARCHIVE_BYTES


def replay(path):
    from mobile.python.roco_mobile import _Backend
    from rkpp_analyzer import RkppAnalyzer
    from scapy.layers.inet import IP, TCP
    from scapy.layers.inet6 import IPv6

    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if (len(entries) != 3 or {e.filename for e in entries} !=
                {"manifest.json", "streams.jsonl", "diagnostics.json"}):
            raise ValueError("Unexpected mobile sample archive members")
        if any(e.file_size > MAX_ARCHIVE_BYTES for e in entries):
            raise ValueError("Mobile sample exceeds size limit")
        manifest = json.loads(archive.read("manifest.json"))
        stream = archive.read("streams.jsonl")
    if manifest.get("format") != FORMAT or manifest.get("provenance") != "ordered_stream":
        raise ValueError("Unsupported mobile sample format")
    if hashlib.sha256(stream).hexdigest() != manifest.get("streams_sha256"):
        raise ValueError("Mobile sample stream hash mismatch")

    frames = []
    issues = SimpleNamespace(decode_issues=deque(maxlen=100))

    class QuietLog:
        def log(self, *_args, **_kwargs):
            pass

    class Analyzer(RkppAnalyzer):
        def _write_key_outputs(self, *_args):
            return Path("memory-only"), Path("memory-only")

        def _decode_be21_core(self, flow, packet, network, frame_no):
            row, info = super()._decode_be21_core(flow, packet, network, frame_no)
            status = str(row.get("decrypt_status", ""))
            record = info.get("record", {}) if info else {}
            frames.append({"stream_event": frame_no, "direction": packet.direction,
                           "command": f"0x{packet.cmd:04X}", "sequence": packet.seq,
                           "body_bytes": len(packet.body), "status": status.split(":", 1)[0],
                           "opcode": record.get("opcode_hex"),
                           "payload_schema_status": record.get("payload_schema_status"),
                           "schema_found": bool(record.get("_schema_found")),
                           "schema_decoded": bool(record.get("_schema_decoded"))})
            if status == "ok_unparsed" or status.startswith(("decrypt_error", "parse_error")):
                _Backend.record_decode_issue(issues, row, packet)
            return row, info

    flows = {}
    key_hits = 0
    closed_pending = 0

    def pending_bytes(analyzer):
        return sum(len(state.buffer) - state.parse_offset for flow in analyzer.flows.values()
                   for state in (flow.c2s, flow.s2c))

    for index, line in enumerate(stream.splitlines()):
        if len(line) > 140000:
            raise ValueError("Mobile stream event too large")
        event = json.loads(line)
        if event.get("index") != index:
            raise ValueError("Mobile stream event order is incomplete")
        flow_id = event["flow"]
        if not isinstance(flow_id, str) or not flow_id or len(flow_id) > 128:
            raise ValueError("Invalid mobile stream identity")
        if event["kind"] == "close":
            removed = flows.pop(flow_id, None)
            if removed:
                key_hits += removed[3].key_hits
                closed_pending += pending_bytes(removed[3])
            continue
        if event["kind"] != "data" or event.get("direction") not in ("c2s", "s2c"):
            raise ValueError("Invalid mobile stream event")
        address, port = str(ipaddress.ip_address(event["address"])), int(event["port"])
        if not 1 <= port <= 65535:
            raise ValueError("Invalid mobile stream port")
        chunk = bytes.fromhex(event["hex"])
        if not 0 < len(chunk) <= 65536:
            raise ValueError("Invalid mobile stream chunk length")
        entry = flows.get(flow_id)
        if entry is None:
            if len(flows) >= 128:
                raise ValueError("Mobile sample active flow limit exceeded")
            analyzer = Analyzer(port=port, logger=QuietLog(), writer=None, key_file=Path("memory-only"),
                                csv_sink=None, preset_key=None, stop_after_key=False,
                                analysis_listener=SimpleNamespace(handle=lambda *_args: None))
            entry = flows[flow_id] = (address, port, {"c2s": 1, "s2c": 1}, analyzer)
        if entry[:2] != (address, port):
            raise ValueError("Mobile stream endpoint changed")
        _, _, seq, analyzer = entry
        direction = event["direction"]
        local = "::1" if ":" in address else "127.0.0.1"
        src, dst = (local, address) if direction == "c2s" else (address, local)
        local_port = 49152 if port != 49152 else 49153
        sport, dport = (local_port, port) if direction == "c2s" else (port, local_port)
        network = IPv6 if ":" in address else IP
        for offset in range(0, len(chunk), 60000):
            part = chunk[offset:offset + 60000]
            packet = network(src=src, dst=dst) / TCP(sport=sport, dport=dport,
                seq=seq[direction], flags="PA") / part
            seq[direction] += len(part)
            analyzer.process_packet(packet, frame_no=index + 1)

    key_hits += sum(entry[3].key_hits for entry in flows.values())
    pending = closed_pending + sum(pending_bytes(entry[3]) for entry in flows.values())
    current_hash = hashlib.sha256(b"".join(p.name.encode("utf8") + b"\0" + p.read_bytes()
        for p in sorted((ROOT / "lab").glob("*.py")))).hexdigest()
    parser_paths = ["mobile/python/roco_mobile.py", "vendor/rkpp/rkpp_proto_core.py",
                    "vendor/rkpp/rkpp_network.py", "vendor/rkpp/rkpp_analyzer.py"]
    recorded_hashes = manifest.get("identity", {}).get("source_hashes", {})
    return {"format": FORMAT, "recorded_identity": manifest.get("identity"),
            "current_lab_source_matches": manifest.get("identity", {}).get("source_hash") == current_hash,
            "current_parser_source_matches": {p: recorded_hashes.get(p) == hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                                              for p in parser_paths},
            "capture": manifest.get("capture"), "key_hits": key_hits,
            "frames": len(frames), "pending_stream_bytes": pending,
            "statuses": dict(Counter(frame["status"] for frame in frames)),
            "decode_issues": list(issues.decode_issues), "frame_results": frames}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="Structural report; excludes keys and payloads")
    args = parser.parse_args()
    result = replay(args.sample)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({key: result[key] for key in ("frames", "key_hits", "statuses", "pending_stream_bytes")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
