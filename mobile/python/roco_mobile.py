"""Same-device ordered socket mirror -> unchanged desktop decoder and HUD.

Native code owns VPN/socket forwarding. Synthetic TCP sequence numbers below
adapt already ordered socket bytes; they are never packet-capture evidence.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
from collections import Counter, deque
import queue
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

_backend = None
_lifecycle = threading.RLock()
MAX_CHUNK = 65536
MAX_FLOWS = 128
MAX_STREAM_BUFFERS = 32 * 1024 * 1024
MAX_PROBE_BYTES = 65536
MAX_PENDING_BYTES = 8 * 1024 * 1024


def should_decode_mobile_payload(opcode):
    from lab.live_battle import _is_battle_code
    from rkpp_analysis import lookup_opcode
    return _is_battle_code(f"0x{opcode:04X}") or not lookup_opcode(opcode)


class ProtocolProbe:
    """Recognize the shared BE21 transport before allocating its full decoder."""
    def __init__(self, consume):
        self.consume = consume
        self.protocol = "pending"
        self.prefix = {"c2s": bytearray(), "s2c": bytearray()}
        self.pending = []
        self.size = 0

    def feed(self, direction, chunk):
        if self.protocol == "tgcp":
            self.consume(direction, chunk)
            return
        if self.protocol != "pending":
            return
        from rkpp_network import MAGIC, FIXED_HDR_LEN, _validate_be21_header
        self.pending.append((direction, chunk))
        self.size += len(chunk)
        prefix = self.prefix[direction]
        prefix.extend(chunk)
        if len(prefix) >= 3 and prefix[0] in (20, 21, 22, 23) and prefix[1] == 3 and prefix[2] <= 4:
            self.protocol = "tls"
        elif any(prefix.startswith(value) for value in (b"GET ", b"POST ", b"HEAD ", b"PUT ", b"HTTP/")):
            self.protocol = "http"
        else:
            offset = prefix.find(MAGIC)
            while offset >= 0 and offset + FIXED_HDR_LEN <= len(prefix):
                if _validate_be21_header(prefix, offset):
                    self.protocol = "tgcp"
                    break
                offset = prefix.find(MAGIC, offset + 1)
            if self.protocol == "pending" and self.size >= MAX_PROBE_BYTES:
                self.protocol = "other"
        if self.protocol != "pending":
            buffered, self.pending = self.pending, []
            self.prefix.clear()
            if self.protocol == "tgcp":
                for buffered_direction, buffered_chunk in buffered:
                    self.consume(buffered_direction, buffered_chunk)


_COUNT_FIELDS = ("packet_count", "key_hits", "decoded_rows", "business_frames_seen",
                 "parsed_business_records", "missing_key_records", "unknown_nonbattle_records",
                 "deferred_nonbattle_records", "metadata_business_records")


def _flow_counts(entry):
    analyzer = getattr(entry, "analyzer", None)
    return {name: getattr(analyzer, name, 0) for name in _COUNT_FIELDS}


class OrderedMirror:
    """One parser and key lifetime per native TCP flow; bounded fail-closed input."""

    def __init__(self, make_flow, publish, clear, *, capacity=1024, byte_capacity=MAX_PENDING_BYTES):
        self.make_flow, self.publish, self.clear = make_flow, publish, clear
        self.pending = queue.Queue(maxsize=capacity)
        self.byte_capacity = byte_capacity
        self.queued_bytes = 0
        self.flows = {}
        self.error = ""
        self.accepting = True
        self.received = 0
        self.totals = Counter()
        self.protocol_counts = Counter()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name="roco-mobile-decode", daemon=True)

    def submit(self, flow_id, address, port, direction, chunk):
        try:
            address = str(ipaddress.ip_address(str(address)))
            port = int(port)
            chunk = bytes(chunk) if isinstance(chunk, (bytes, bytearray, memoryview)) else bytes(int(v) & 255 for v in chunk)
            if not str(flow_id) or len(str(flow_id)) > 128 or not 1 <= port <= 65535:
                raise ValueError("Invalid TCP flow identity")
            if direction not in ("c2s", "s2c") or not 0 < len(chunk) <= MAX_CHUNK:
                raise ValueError("Invalid ordered TCP stream chunk")
            return self._enqueue((str(flow_id), address, port, direction, chunk))
        except (TypeError, ValueError) as exc:
            self.fail(str(exc))
            return False

    def close_flow(self, flow_id):
        return self._enqueue((str(flow_id), None, None, None, None))

    def _enqueue(self, item):
        with self._lock:
            if not self.accepting:
                return False
            size = len(item[-1]) if item[-1] is not None else 0
            if self.queued_bytes + size > self.byte_capacity:
                self.error = "Decoder byte budget exceeded; analysis paused, export protocol samples"
                self.accepting = False
                return False
            try:
                self.pending.put_nowait(item)
                self.queued_bytes += size
                return True
            except queue.Full:
                self.error = "Decoder queue full; analysis paused, reconnect before retrying"
                self.accepting = False
                return False

    def fail(self, message):
        with self._lock:
            if not self.error:
                self.error = str(message)
            self.accepting = False

    def _run(self):
        cleared = False
        last_publish = 0.0
        while not self._stop.is_set():
            if not self.accepting:
                if not cleared:
                    self.flows.clear()
                    self.clear()
                    cleared = True
                self._stop.wait(0.1)
                continue
            try:
                item = self.pending.get(timeout=0.1)
            except queue.Empty:
                try:
                    self.publish()
                except Exception as exc:
                    self.fail(f"{type(exc).__name__}: {exc}")
                continue
            try:
                flow_id, address, port, direction, chunk = item
                if address is None:
                    removed = self.flows.pop(flow_id, None) if flow_id else None
                    if not flow_id:
                        self.flows.clear()
                    if removed is not None or not flow_id:
                        self.clear(flow_id or None)
                    continue
                entry = self.flows.get(flow_id)
                if entry is None:
                    if len(self.flows) >= MAX_FLOWS:
                        raise RuntimeError("Too many active mirrored TCP flows")
                    entry = self.flows[flow_id] = (address, port, self.make_flow(flow_id, address, port))
                if entry[:2] != (address, port):
                    raise ValueError("TCP flow endpoint changed without close_flow")
                flow = entry[2]
                before = _flow_counts(flow)
                old_protocol = getattr(getattr(flow, "probe", None), "protocol", "pending")
                try:
                    flow.feed(direction, chunk)
                finally:
                    after = _flow_counts(flow)
                    self.totals.update({name: max(0, after[name] - before[name]) for name in _COUNT_FIELDS})
                    protocol = getattr(getattr(flow, "probe", None), "protocol", "pending")
                    if protocol != old_protocol:
                        self.protocol_counts[protocol] += 1
                self.received += len(chunk)
                if self.pending.empty() or time.monotonic() - last_publish >= 0.15:
                    self.publish()
                    last_publish = time.monotonic()
            except Exception as exc:
                self.fail(f"{type(exc).__name__}: {exc}")
            finally:
                with self._lock:
                    self.queued_bytes -= len(item[-1]) if item[-1] is not None else 0
                self.pending.task_done()

    def stop(self):
        self.accepting = False
        self._stop.set()
        if self.thread.is_alive():
            self.thread.join()
        self.flows.clear()
        self.clear()


class _Backend:
    def __init__(self, files_root):
        from _mobile_release import BUILD_ID, SOURCE_HASH, SOURCE_HASHES, RESOURCE_HASH, RESOURCE_KEY_HEX
        from lab import release_paths, release_runtime
        import lab

        files_root = Path(files_root).resolve()
        files_root.mkdir(parents=True, exist_ok=True)
        self.files_root = files_root
        self.release_id = BUILD_ID
        self.source_hashes = dict(SOURCE_HASHES)
        release_paths.configure_mobile(files_root, {"release_id": BUILD_ID, "source_hash": SOURCE_HASH})
        raw = (files_root / "resources.rpk").read_bytes()
        if hashlib.sha256(raw).hexdigest() != RESOURCE_HASH:
            raise ValueError("Mobile resource archive differs from this app build")
        self.root = Path(lab.__file__).resolve().parents[1]
        self.mount = release_runtime.install(self.root, raw, bytes.fromhex(RESOURCE_KEY_HEX), SOURCE_HASHES)
        try:
            self._initialize(files_root)
        except BaseException:
            self.mount.uninstall()
            raise

    def _initialize(self, files_root):
        import os
        import sys
        os.environ["ROCO_RELEASE"] = "1"
        # Source-tree tests and compiled staging use the same vendor modules.
        sys.path.insert(0, str(self.root / "vendor/rkpp"))
        from lab import server, live_battle
        from lab.catalog_store import runtime_catalog
        from lab.ruleset import BwikiRuleset
        from rkpp_analyzer import RkppAnalyzer
        from rkpp_io import build_opcode_summary
        from scapy.layers.inet import IP, TCP
        from scapy.layers.inet6 import IPv6
        from http.server import ThreadingHTTPServer

        self.server_module = server
        self.live_battle = live_battle
        self.capture_running = False
        self.native_error = ""
        settings = files_root / "mobile-mode.json"
        try:
            self.mode = json.loads(settings.read_text("utf8")).get("mode", "pvp")
        except (OSError, ValueError, AttributeError):
            self.mode = "pvp"
        if self.mode not in ("pvp", "pve"):
            self.mode = "pvp"
        self.mode_generation = 0
        self.applied_mode_generation = 0
        self.mode_lock = threading.Lock()
        self.pvp_ready = False
        self.samples = None
        self.decode_issues = deque(maxlen=12)
        self.battle_flow = None
        self.wire_commands = Counter()
        self.ack_extra_sizes = Counter()
        self.unknown_opcodes = Counter()
        catalog, self.catalog_hash, _ = runtime_catalog()
        self.rules = BwikiRuleset(catalog)
        from lab.mobile_pve import PveMetadata
        self.pve = PveMetadata(catalog)
        backend = self

        class Feed(live_battle.LiveBattleFeed):
            def __init__(self):
                super().__init__(base="ordered-stream://same-device", archive=None)
                self.rows = []

            def start(self):
                return self  # OrderedMirror is the only writer; never start a relay poller.

            def _get(self, path, timeout=3):
                rows, self.rows = self.rows, []
                return rows

            def _capture(self):
                return backend.diagnostics()

            def state(self):
                result = super().state()
                result["relay_ok"] = backend.capture_running and backend.mirror.accepting
                return result

        self.feed = Feed()
        self.previous_feed = live_battle._SHARED_FEED
        live_battle._SHARED_FEED = self.feed
        server._start_live_battle_feed()
        original_publish = self.feed.on_snapshot
        self.poll_generation = 0
        def publish_snapshot(payload, state):
            if self.mode == "pvp" and self.poll_generation == self.mode_generation and original_publish:
                original_publish(payload, state)
        self.feed.on_snapshot = publish_snapshot

        class QuietLog:
            def log(self, message):
                pass  # Session keys and payloads stay in parser memory, never mobile logs.

        class Listener:
            def __init__(self, flow_id):
                self.flow_id = flow_id

            def handle(self, index, row, info):
                if not live_battle._is_battle_code(row.get("opcode_hex") or row.get("opcode")):
                    return
                backend.apply_mode()
                if info.get("discard_mode_event"):
                    return
                if backend.mode == "pve":
                    backend.battle_flow = self.flow_id
                    record = info.get("record") or {}
                    backend.pve.handle(record["opcode"], record.get("_decoded") or {})
                    return
                summary = build_opcode_summary(row, parse_content=True)
                if summary is not None:
                    if live_battle._is_battle_code(summary.get("opencode")):
                        backend.battle_flow = self.flow_id
                    backend.feed.rows.append({**summary, "provenance": "ordered_stream"})

        class MemoryAnalyzer(RkppAnalyzer):
            missing_key_records = 0
            unknown_nonbattle_records = 0
            hard_decode_errors = 0
            deferred_nonbattle_records = 0
            metadata_business_records = 0

            def _should_decode_payload(self, opcode):
                if backend.mode == "pve":
                    return live_battle._is_battle_code(f"0x{opcode:04X}")
                return should_decode_mobile_payload(opcode)

            def _should_build_payload_tree(self, opcode):
                return backend.mode != "pve" and self._should_decode_payload(opcode)

            def _decode_schema_payload(self, record, seq):
                if backend.mode != "pve" or not live_battle._is_battle_code(record.get("opcode_hex")):
                    return super()._decode_schema_payload(record, seq)
                if record["opcode"] == 0x1316:
                    backend.pve.reset("正在识别当前精灵")
                decoded = backend.pve.decode(record)
                record.update(_decoded=decoded, _schema_found=True, _schema_decoded=True,
                              _decode_source="pve_metadata", payload_metadata_only=True)
                return decoded, True

            def _summarize(self, record, inner):
                if backend.mode == "pve":
                    return "pve_metadata", {}
                return super()._summarize(record, inner)

            def _write_key_outputs(self, key, flow_id):
                return Path("memory-only"), Path("memory-only")

            def _decode_be21_core(self, flow, be21, packet, frame_no):
                command = f"0x{be21.cmd:04X}"
                if command in backend.wire_commands or len(backend.wire_commands) < 32:
                    backend.wire_commands[command] += 1
                if be21.cmd == 0x1002:
                    backend.ack_extra_sizes[str(len(be21.header_extra))] += 1
                generation = backend.mode_generation
                row, info = super()._decode_be21_core(flow, be21, packet, frame_no)
                if info is not None and generation != backend.mode_generation:
                    info["discard_mode_event"] = True
                status = str(row.get("decrypt_status", ""))
                if status == "no_key":
                    self.missing_key_records += 1
                elif status.startswith(("decrypt_error", "parse_error")) or status == "ok_unparsed":
                    backend.record_decode_issue(row, be21)
                    self.hard_decode_errors += 1
                elif info is not None and be21.cmd == 0x4013:
                    record = info.get("record") or {}
                    if record.get("payload_deferred"):
                        self.deferred_nonbattle_records += 1
                        return row, info
                    if record.get("payload_metadata_only"):
                        self.metadata_business_records += 1
                    battle = live_battle._is_battle_code(row.get("opcode_hex") or row.get("opcode"))
                    incomplete = record.get("payload_schema_status") == "unknown_fields"
                    if not (record.get("_schema_decoded") and record.get("_schema_found")) or (battle and incomplete):
                        if battle:
                            category = "battle_schema_incomplete" if incomplete else "battle_schema_missing"
                            backend.record_decode_issue(row, be21, category=category)
                            self.hard_decode_errors += 1
                        else:
                            self.unknown_nonbattle_records += 1
                            code = str(row.get("opcode_hex") or row.get("opcode") or "unknown")
                            if code in backend.unknown_opcodes or len(backend.unknown_opcodes) < 16:
                                backend.unknown_opcodes[code] += 1
                return row, info

        class Flow:
            def __init__(self, flow_id, address, port):
                self.address, self.port = address, port
                self.seq = {"c2s": 1, "s2c": 1}
                self.flow_id = flow_id
                self.analyzer = None
                self.probe = ProtocolProbe(self._consume)

            def feed(self, direction, chunk):
                self.probe.feed(direction, chunk)

            def _consume(self, direction, chunk):
                if self.analyzer is None:
                    self._start_analyzer()
                self._decode(direction, chunk)

            def _start_analyzer(self):
                port, flow_id = self.port, self.flow_id
                self.analyzer = MemoryAnalyzer(port=port, logger=QuietLog(), writer=None,
                    key_file=files_root / "unused-session-key", key_store_dir=files_root / "unused-keys",
                    csv_sink=None, preset_key=None, stop_after_key=False, analysis_listener=Listener(flow_id))
                self.analyzer.invalidate_game_session_key("mobile-new-flow")

            def _decode(self, direction, chunk):
                # This models the already reassembled stream, never raw VPN IP packets.
                local = "::1" if ":" in self.address else "127.0.0.1"
                src, dst = (local, self.address) if direction == "c2s" else (self.address, local)
                local_port = 49152 if self.port != 49152 else 49153
                sport, dport = (local_port, self.port) if direction == "c2s" else (self.port, local_port)
                network = IPv6 if ":" in self.address else IP
                before = self.analyzer.listener_errors
                for offset in range(0, len(chunk), 60000):
                    part = chunk[offset:offset + 60000]
                    packet = network(src=src, dst=dst) / TCP(sport=sport, dport=dport,
                        seq=self.seq[direction], flags="PA") / part
                    self.seq[direction] += len(part)
                    self.analyzer.process_packet(packet)
                if self.analyzer.listener_errors != before:
                    raise RuntimeError("Shared protocol listener failed")
                if self.analyzer.hard_decode_errors:
                    issue = backend.decode_issues[-1] if backend.decode_issues else {}
                    raise RuntimeError("游戏协议分析已暂停（" + issue.get("category", "unknown") +
                        "，" + direction + "），请复制连接诊断；游戏网络继续转发")
                states = [state for _, _, mirrored in list(backend.mirror.flows.values())
                          if mirrored.analyzer is not None
                          for flow in mirrored.analyzer.flows.values() for state in (flow.c2s, flow.s2c)]
                if sum(len(state.buffer) + state._pending_bytes for state in states) > MAX_STREAM_BUFFERS:
                    raise RuntimeError("Ordered stream parser memory limit reached; capture stopped")
                if any(state.gap_skipped or state.dropped_pending_segments or state.trimmed_buffers for state in states):
                    raise RuntimeError("Ordered stream parser discarded bytes; capture stopped")

        self.mirror = OrderedMirror(Flow, self.publish, self.clear)

        class Handler(server.Handler):
            def do_POST(self):
                if urlparse(self.path).path != "/api/mobile/mode":
                    return super().do_POST()
                if not self.local_request_allowed():
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 128:
                        raise ValueError("模式请求大小无效")
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict) or set(data) != {"mode"}:
                        raise ValueError("模式请求格式无效")
                    backend.set_mode(data["mode"])
                    self.send_body(200, {"mode": backend.mode})
                except (ValueError, TypeError) as error:
                    self.send_body(400, {"error": str(error)})

            def do_GET(self):
                path = urlparse(self.path).path
                if path in ("/mobile", "/mobile/", "/api/mobile/status", "/mobile/state") or path.startswith("/mobile/"):
                    if not self.local_request_allowed():
                        return
                    if path in ("/api/mobile/status", "/mobile/state"):
                        self.send_body(200, backend.diagnostics())
                        return
                    relative = "index.html" if path in ("/mobile", "/mobile/") else path[len("/mobile/"):]
                    root = backend.root / "mobile/shared"
                    if not self.send_static(root / relative, root):
                        self.send_body(404, {"error": "Mobile resource unavailable"})
                    return
                super().do_GET()

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http.daemon_threads = True
        self.http_thread = threading.Thread(target=self.http.serve_forever, name="roco-mobile-http", daemon=True)
        self.mirror.thread.start()
        self.http_thread.start()

    def clear(self, flow_id=None):
        if flow_id is not None and flow_id != self.battle_flow:
            return
        self.battle_flow = None
        if getattr(self, "pve", None):
            self.pve.reset()
        self.feed.tracker.reset()
        self.feed.rows.clear()
        self.feed._published_snapshot = None
        with self.server_module.HUD_LOCK:
            self.server_module.HUD_SNAPSHOT.update(at=time.time(), payload=None, source="ordered-stream")

    def set_mode(self, mode):
        if mode not in ("pvp", "pve"):
            raise ValueError("请选择PVP或PVE模式")
        with self.mode_lock:
            if mode == self.mode:
                return
            target = self.files_root / "mobile-mode.json"
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps({"mode": mode}), encoding="utf8")
            temporary.replace(target)
            self.mode = mode
            self.mode_generation += 1
            self.pve.reset("模式已切换，请进入下一场对局")
            self.feed._published_snapshot = None
            with self.server_module.HUD_LOCK:
                self.server_module.HUD_SNAPSHOT.update(at=time.time(), payload=None, source="ordered-stream")

    def apply_mode(self):
        if self.applied_mode_generation != self.mode_generation:
            self.feed.tracker.reset()
            self.feed.rows.clear()
            self.feed._published_snapshot = None
            self.applied_mode_generation = self.mode_generation

    def publish(self):
        self.apply_mode()
        if self.mode != "pvp":
            return
        if self.feed.rows and not self.pvp_ready:
            self.rules.programs()
            self.pvp_ready = True
        generation = self.mode_generation
        self.poll_generation = generation
        self.feed.poll_once()
        if generation != self.mode_generation:
            self.feed._published_snapshot = None
            with self.server_module.HUD_LOCK:
                self.server_module.HUD_SNAPSHOT.update(at=time.time(), payload=None, source="ordered-stream")

    def record_decode_issue(self, row, packet, category=None):
        # Keep structural diagnostics only. Ciphertext, plaintext and handshake keys stay in memory.
        issue = {
            "category": category or str(row.get("decrypt_status", "unknown")).split(":", 1)[0],
            "direction": packet.direction,
            "command": f"0x{packet.cmd:04X}",
            "sequence": packet.seq,
            "body_bytes": len(packet.body),
            "cipher_remainder": len(packet.body) % 16,
            "header_extra_bytes": len(packet.header_extra),
        }
        plain_hex = row.get("decrypted_body_hex")
        if plain_hex:
            from rkpp_proto_core import tsf4g_trailer_len
            plain = bytes.fromhex(plain_hex)
            trailer = tsf4g_trailer_len(plain)
            issue.update(plain_bytes=len(plain), trailer_valid=bool(trailer),
                         outer_magic_matches=plain[4:6] == b"\x55\xaa",
                         outer_length_matches=(len(plain) >= 16 and
                             int.from_bytes(plain[6:10], "big") == len(plain) - trailer - 4))
            if len(plain) >= 30:
                issue.update(outer_sequence_matches=int.from_bytes(plain[:4], "big") == packet.seq,
                             outer_reserved_zero=plain[10:12] == b"\x00\x00",
                             outer_version=int.from_bytes(plain[12:16], "big"),
                             outer_word_12_16=int.from_bytes(plain[12:16], "big"),
                             inner_marker_hex=plain[24:26].hex(),
                             candidate_c2s_opcode=f"0x{int.from_bytes(plain[20:24], 'big') & 0xFFFF:04X}")
            issue["known_marker_offsets"] = {
                marker.hex(): [offset for offset in range(min(len(plain) - 1, 64))
                               if plain[offset:offset + 2] == marker]
                for marker in (b"\x55\xaa", b"\x39\x63", b"\xe6\x88", b"\x14\x28", b"\x7c\xa2")}
        self.decode_issues.append(issue)
        samples = getattr(self, "samples", None)
        if samples:
            samples.mark_failure(issue["category"])

    def diagnostics(self):
        mirror = getattr(self, "mirror", None)
        flows = list(mirror.flows.values()) if mirror else []
        analyzers = [entry[2].analyzer for entry in flows if entry[2].analyzer is not None]
        totals = mirror.totals if mirror else {}
        active_keys = sum(any(flow.key is not None for flow in a.flows.values()) for a in analyzers)
        protocol_counts = dict(mirror.protocol_counts) if mirror else {}
        return {"platform": "mobile", "provenance": "ordered_stream", "same_device": True,
            "capture_running": bool(self.capture_running),
            "decoder_ready": bool(mirror and mirror.accepting),
            "error": (mirror.error if mirror else "") or self.native_error,
            "queue_depth": mirror.pending.qsize() if mirror else 0,
            "queue_bytes": mirror.queued_bytes if mirror else 0,
            "queue_byte_limit": mirror.byte_capacity if mirror else MAX_PENDING_BYTES,
            "bytes_received": mirror.received if mirror else 0, "active_flows": len(flows),
            "protocol_counts": protocol_counts, "active_game_flows": len(analyzers),
            "active_key_flows": active_keys,
            "target_packets": totals.get("packet_count", 0),
            "protocol_frames": totals.get("decoded_rows", 0),
            "key_hits": totals.get("key_hits", 0),
            "missing_key_records": totals.get("missing_key_records", 0),
            "unknown_nonbattle_records": totals.get("unknown_nonbattle_records", 0),
            "wire_commands": dict(self.wire_commands),
            "ack_extra_sizes": dict(self.ack_extra_sizes),
            "unknown_opcodes": dict(self.unknown_opcodes),
            "decode_issues": list(self.decode_issues),
            "protocol_samples": self.samples.status() if self.samples else {},
            "parsed_business_records": totals.get("parsed_business_records", 0),
            "schema_business_records": max(0, totals.get("parsed_business_records", 0) -
                                           totals.get("unknown_nonbattle_records", 0) -
                                           totals.get("deferred_nonbattle_records", 0) -
                                           totals.get("metadata_business_records", 0)),
            "deferred_nonbattle_records": totals.get("deferred_nonbattle_records", 0),
            "metadata_business_records": totals.get("metadata_business_records", 0),
            "mode": self.mode,
            "pve": self.pve.snapshot(bool(self.capture_running and mirror and mirror.accepting and mirror.queued_bytes == 0)),
            "build_id": self.release_id,
            "battle_detected": bool(self.feed.tracker.battle_id is not None and
                                    any(self.feed.tracker.teams.values())),
            "battle_round": self.feed.tracker.round,
            "battle_finished": self.feed.tracker.finished,
            "catalog_sha256": self.catalog_hash, "snapshot_id": self.rules.snapshot_id,
            "game_process_detection": "native-vpn-socket-lifecycle"}

    def stop(self):
        self.http.shutdown()
        self.http.server_close()
        self.http_thread.join()
        self.mirror.stop()
        if self.samples:
            self.samples.finish()
        self.live_battle._SHARED_FEED = self.previous_feed
        self.mount.uninstall()

    def reset_capture(self):
        from lab.mobile_protocol_capture import ProtocolSamples
        from lab.release_paths import build_identity
        if self.samples:
            self.samples.finish()
        self.samples = ProtocolSamples(self.files_root, ProtocolProbe,
            {**build_identity(), "source_hashes": self.source_hashes,
             "catalog_sha256": self.catalog_hash, "snapshot_id": self.rules.snapshot_id})
        self.capture_running = False
        self.native_error = ""
        self.decode_issues.clear()
        self.wire_commands.clear()
        self.ack_extra_sizes.clear()
        self.unknown_opcodes.clear()
        old = self.mirror
        old.stop()
        self.mirror = OrderedMirror(old.make_flow, self.publish, self.clear)
        self.mirror.thread.start()


def start(filesRoot):
    global _backend
    with _lifecycle:
        if _backend is None:
            _backend = _Backend(filesRoot)
        elif Path(filesRoot).resolve() != _backend.files_root:
            raise ValueError("Backend is already bound to another application directory")
        return _backend.http.server_port


def feed(flowId, remoteAddress, remotePort, direction, chunk):
    backend = _backend
    if backend is None:
        return False
    samples = getattr(backend, "samples", None)
    if samples:
        raw = bytes(chunk) if isinstance(chunk, (bytes, bytearray, memoryview)) else bytes(int(v) & 255 for v in chunk)
        samples.feed(flowId, remoteAddress, remotePort, direction, raw)
    accepted = backend.mirror.submit(flowId, remoteAddress, remotePort, direction, chunk)
    return accepted or bool(samples and samples.status()["active"])


def close_flow(flowId):
    backend = _backend
    if backend and getattr(backend, "samples", None):
        backend.samples.close_flow(flowId)
    return bool(backend and backend.mirror.close_flow(flowId))


def flow_protocol(flowId):
    backend = _backend
    if backend and backend.samples:
        protocol = backend.samples.protocol(flowId)
        if protocol != "pending":
            return protocol
    entry = backend.mirror.flows.get(str(flowId)) if backend else None
    return entry[2].probe.protocol if entry else "pending"


def status():
    return json.dumps(_backend.diagnostics() if _backend else {"capture_running": False, "error": "Backend not started"})


def set_mode(mode):
    with _lifecycle:
        if _backend is None:
            raise ValueError("本机引擎尚未就绪")
        _backend.set_mode(str(mode))
        return _backend.mode


def get_mode():
    return _backend.mode if _backend else "pvp"


def reset_capture():
    with _lifecycle:
        if _backend is None:
            return False
        _backend.reset_capture()
        return True


def pause_analysis(reason):
    backend = _backend
    if backend is None:
        return False
    backend.mirror.fail(str(reason))
    if getattr(backend, "samples", None):
        backend.samples.mark_failure(reason)
    return True


def set_capture_state(running, error=""):
    with _lifecycle:
        if _backend is None:
            return False
        _backend.capture_running = bool(running)
        _backend.native_error = str(error)
        if not running:
            _backend.mirror.close_flow("")
            if getattr(_backend, "samples", None):
                _backend.samples.finish()
        return _backend.capture_running if running else True


def export_protocol_samples(native_json="{}"):
    backend = _backend
    if backend is None or not backend.samples:
        raise ValueError("请先开始采集并重新打开游戏")
    if len(native_json) > 65536:
        raise ValueError("Native diagnostics too large")
    return backend.samples.export(backend.diagnostics(), json.loads(native_json))


def sample_gap(reason):
    backend = _backend
    if backend and backend.samples:
        backend.samples.error = str(reason)
        backend.samples.finish("native_stream_gap")


def hud_snapshot():
    backend = _backend
    if backend is None:
        return json.dumps({"at": 0, "payload": None})
    from urllib.request import urlopen
    with urlopen(f"http://127.0.0.1:{backend.http.server_port}/api/hud/snapshot", timeout=5) as response:
        return response.read().decode("utf8")


def stop():
    global _backend
    with _lifecycle:
        if _backend is not None:
            _backend.stop()
            _backend = None
