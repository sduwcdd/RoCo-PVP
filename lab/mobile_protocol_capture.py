"""Bounded, app-private ordered game streams for explicit diagnostic export."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import threading
import time
import zipfile
from pathlib import Path

FORMAT = "roco-mobile-streams-v1"
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_SECONDS = 180
AFTER_FAILURE_SECONDS = 15


class ProtocolSamples:
    def __init__(self, root, probe_factory, identity, *, clock=time.monotonic):
        self.root = Path(root) / "protocol-samples"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "streams.jsonl"
        self._output = self.path.open("wb")
        self.probe_factory = probe_factory
        self.identity = dict(identity)
        self.clock = clock
        self.started = clock()
        self.deadline = self.started + MAX_SECONDS
        self.probes = {}
        self.total_bytes = 0
        self.events = 0
        self.game_flows = set()
        self.failure = ""
        self.error = ""
        self.reason = ""
        self._lock = threading.RLock()

    def _active(self):
        if not self.reason and self.clock() >= self.deadline:
            self.finish("failure_window_complete" if self.failure else "time_limit")
        return not self.reason

    def _append(self, event):
        if not self._active():
            return
        event = {"index": self.events, "elapsed_ms": round((self.clock() - self.started) * 1000), **event}
        raw = (json.dumps(event, separators=(",", ":")) + "\n").encode("utf8")
        if self.total_bytes + len(raw) > MAX_ARCHIVE_BYTES:
            self.finish("size_limit")
            return
        self._output.write(raw)
        self.total_bytes += len(raw)
        self.events += 1

    def feed(self, flow_id, address, port, direction, chunk):
        with self._lock:
            if not self._active():
                return
            try:
                flow_id, address, port = str(flow_id), str(ipaddress.ip_address(str(address))), int(port)
                if not flow_id or len(flow_id) > 128 or not 1 <= port <= 65535:
                    raise ValueError("Invalid sample flow")
                if direction not in ("c2s", "s2c") or not 0 < len(chunk) <= 65536:
                    raise ValueError("Invalid sample chunk")
                entry = self.probes.get(flow_id)
                if entry is None:
                    if len(self.probes) >= 128:
                        raise ValueError("Sample flow limit")

                    def record(part_direction, part):
                        self.game_flows.add(flow_id)
                        self._append({"kind": "data", "flow": flow_id, "address": address,
                                      "port": port, "direction": part_direction, "hex": part.hex()})

                    entry = self.probes[flow_id] = (address, port, self.probe_factory(record))
                if entry[:2] != (address, port):
                    raise ValueError("Sample flow endpoint changed")
                entry[2].feed(direction, chunk)
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"
                self.finish("capture_error")

    def close_flow(self, flow_id):
        with self._lock:
            entry = self.probes.pop(str(flow_id), None)
            if entry and entry[2].protocol == "tgcp":
                try:
                    self._append({"kind": "close", "flow": str(flow_id)})
                except OSError as exc:
                    self.error = f"{type(exc).__name__}: {exc}"
                    self.finish("capture_error")

    def protocol(self, flow_id):
        with self._lock:
            entry = self.probes.get(str(flow_id))
            return entry[2].protocol if entry else "pending"

    def mark_failure(self, reason):
        with self._lock:
            if not self.failure:
                self.failure = str(reason)
                self.deadline = min(self.deadline, self.clock() + AFTER_FAILURE_SECONDS)

    def finish(self, reason="stopped"):
        with self._lock:
            if not self.reason:
                self.reason = reason
                self._output.close()
                self.probes.clear()

    def status(self):
        with self._lock:
            active = self._active()
            return {"active": active, "events": self.events, "bytes": self.total_bytes,
                    "game_flows": len(self.game_flows), "reason": self.reason, "error": self.error,
                    "seconds_remaining": max(0, round(self.deadline - self.clock())) if active else 0}

    def export(self, diagnostics, native):
        with self._lock:
            if not self.game_flows:
                raise ValueError("尚未采集到游戏协议，请先开始采集并重新打开游戏")
            self.finish("exported")
            manifest = {"format": FORMAT, "provenance": "ordered_stream", "identity": self.identity,
                        "capture": self.status(), "first_analysis_error": self.failure,
                        "streams_sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
                        "sensitive": "Contains session keys and account traffic; share privately."}
            target = self.root / "roco-mobile-protocol.zip"
            temporary = target.with_suffix(".tmp")
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(self.path, "streams.jsonl")
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                archive.writestr("diagnostics.json", json.dumps({"parser": diagnostics, "native": native},
                                                                ensure_ascii=False, indent=2))
            temporary.replace(target)
            return str(target)
