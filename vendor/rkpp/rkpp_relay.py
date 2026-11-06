#!/usr/bin/env python3

"""HTTP relay for parsed opcode events.

Endpoints:
  GET /health  -> server stats
  GET /latest  -> recent opcode events as JSON
  GET /events  -> newline-delimited JSON stream for live consumers
"""
from __future__ import annotations

import json
import queue
import sys
import threading
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from rkpp_io import SessionLogger, build_client_move_rows, build_opcode_summary, now_text

try:
    from rkpp_game_process import game_process_snapshot
except Exception:  # pragma: no cover
    def game_process_snapshot():
        return {"game_process_alive": False}


class OpcodeRelayServer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        logger: SessionLogger,
        history_size: int = 500,
        mode: str = "normal",
    ) -> None:
        self.host = host
        self.port = port
        self.logger = logger
        self.mode = mode
        self._capture_integrity_epoch = str(uuid.uuid4())
        network = sys.modules.get("rkpp_network")
        try:
            self._capture_integrity_since = network.capture_integrity_watermark() if network else 0
        except Exception:
            self._capture_integrity_since = None
        self._history: deque[dict[str, Any]] = deque(maxlen=max(1, history_size))
        self._clients: set[queue.Queue[dict[str, Any] | None]] = set()
        self._lock = threading.Lock()
        self._event_count = 0
        self._event_cursor = 0
        self._requested_port = port
        self._httpd = self._make_server_with_fallback()
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="rkpp-opcode-relay", daemon=True)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        if self.port != self._requested_port:
            self.logger.log(
                f"[relay] requested port {self._requested_port} unavailable, fallback port={self.port}"
            )
        self._thread.start()
        self.logger.log(
            f"[relay] listening url={self.url} mode={self.mode} endpoints=/health,/latest,/events"
        )

    def close(self) -> None:
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            client.put_nowait(None)
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=2.0)

    def handle(self, row_index: int, row: dict[str, Any], parsed_info: dict[str, Any]) -> None:
        events = self._build_events(row_index, row, parsed_info)
        if not events:
            return
        integrity = self._capture_integrity_snapshot(row)
        with self._lock:
            self._event_count += len(events)
            for event in events:
                event["captureIntegrity"] = dict(integrity)
                self._event_cursor += 1
                event["_relay_event_id"] = self._event_cursor
                self._history.append(event)
            clients = list(self._clients)
        for event in events:
            for client in clients:
                try:
                    client.put_nowait(event)
                except queue.Full:
                    pass

    def stats(self) -> dict[str, Any]:
        with self._lock:
            payload = {
                "status": "ok",
                "mode": self.mode,
                "time": now_text(),
                "events": self._event_count,
                "latestEventId": self._event_cursor,
                "history": len(self._history),
                "clients": len(self._clients),
            }
        try:
            payload.update(game_process_snapshot())
        except Exception:
            payload["game_process_alive"] = False
        payload["captureIntegrity"] = self._capture_integrity_snapshot()
        return payload

    def _capture_integrity_snapshot(self, row=None) -> dict[str, Any]:
        # No new dependency requirement for standalone/older relay installations.
        unknown = {
            "revision": "20261020-capture-integrity-v1", "epoch": self._capture_integrity_epoch,
            "flowId": row.get("flow_id") if row is not None else None,
            "streamGeneration": None, "gapSkipped": None, "gapBytesDropped": None,
            "droppedPendingSegments": None, "trimmedBuffers": None,
            "resyncBytes": None, "decodeFailures": None,
            "pendingGap": None, "observed": False,
        }
        if row is None:
            unknown["flows"] = {}
        try:
            network = sys.modules.get("rkpp_network")
            if network is not None and self._capture_integrity_since is not None:
                return network.capture_integrity_snapshot(
                    epoch=self._capture_integrity_epoch, since=self._capture_integrity_since, row=row,
                )
        except Exception:
            pass
        return unknown

    def latest(self, limit: int = 50, after: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._history)
        if after > 0:
            items = [item for item in items if int(item.get("_relay_event_id") or 0) > after]
            return items[:max(0, limit)]
        return items[-max(0, limit):]

    def subscribe(self) -> queue.Queue[dict[str, Any] | None]:
        client: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=1000)
        with self._lock:
            self._clients.add(client)
        return client

    def unsubscribe(self, client: queue.Queue[dict[str, Any] | None]) -> None:
        with self._lock:
            self._clients.discard(client)

    def _build_events(self, row_index: int, row: dict[str, Any], parsed_info: dict[str, Any]) -> list[dict[str, Any]]:
        if self.mode == "move":
            return self._build_move_events(row_index, row, parsed_info)
        event = self._build_event(row_index, row, parsed_info)
        return [event] if event is not None else []

    def _build_event(self, row_index: int, row: dict[str, Any], parsed_info: dict[str, Any]) -> dict[str, Any] | None:
        summary = build_opcode_summary(row, parse_content=True)
        if summary is None:
            return None
        event = self._base_event_fields(row_index, row)
        event.update({
            "opencode": summary["opencode"],
            "meaning": summary["meaning"],
            "summary_kind": parsed_info.get("summary_kind") or row.get("summary_kind"),
            "summary_text": row.get("summary_text"),
            "content": summary["content"] or {},
        })
        return event

    def _build_move_events(
        self,
        row_index: int,
        row: dict[str, Any],
        parsed_info: dict[str, Any],
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for item in build_client_move_rows(row_index, row, parsed_info):
            event = self._base_event_fields(int(item.get("row_index") or row_index), item)
            event.update({
                "act_index": item.get("act_index"),
                "opencode": item.get("opcode_hex") or item.get("opcode"),
                "inner_message_id": item.get("inner_message_id"),
                "summary_kind": "client_move",
                "summary_text": item.get("summary_text"),
                "space_time_ms": item.get("space_time_ms"),
                "operator_obj_id": item.get("operator_obj_id"),
                "actor_id": item.get("actor_id"),
                "time_stamp": item.get("time_stamp"),
                "to_pos": self._vector_payload(item, "to_pos"),
                "to_rot": self._vector_payload(item, "to_rot"),
                "speed": self._vector_payload(item, "speed"),
                "acceleration": self._vector_payload(item, "acceleration"),
                "ctrl_rot": self._vector_payload(item, "ctrl_rot"),
                "move_mode": item.get("move_mode"),
                "custom_mode": item.get("custom_mode"),
                "stop_move": item.get("stop_move"),
                "ride_move": item.get("ride_move"),
                "mate_point": item.get("mate_point"),
                "mate_move_mode": item.get("mate_move_mode"),
                "content": item.get("content") or {},
            })
            events.append(event)
        return events

    def _base_event_fields(self, row_index: int, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "row_index": row_index,
            "captured_at": payload.get("captured_at"),
            "flow_id": payload.get("flow_id"),
            "direction": payload.get("protocol_direction") or payload.get("direction"),
            "seq": payload.get("seq"),
            "opcode": payload.get("opcode"),
            "opcode_name": str(payload.get("opcode_name") or "").strip(),
        }

    def _vector_payload(self, item: dict[str, Any], prefix: str) -> dict[str, Any]:
        return {
            "x": item.get(f"{prefix}_x"),
            "y": item.get(f"{prefix}_y"),
            "z": item.get(f"{prefix}_z"),
        }

    def _make_server_with_fallback(self) -> ThreadingHTTPServer:
        last_exc: OSError | None = None
        for candidate in range(self.port, self.port + 11):
            self.port = candidate
            try:
                return self._make_server()
            except OSError as exc:
                last_exc = exc
                code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
                if code not in {10013, 10048, 13, 48, 98}:
                    raise
        assert last_exc is not None
        raise last_exc

    def _make_server(self) -> ThreadingHTTPServer:
        relay = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            # The overlays are served from https://roco.native.  The normal
            # WebView bridge is preferred, but a hidden producer must be able
            # to poll this loopback-only relay directly if that bridge stalls.
            def end_headers(self) -> None:
                self.send_header("Access-Control-Allow-Origin", "https://roco.native")
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                super().end_headers()

            def log_message(self, fmt: str, *args: Any) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path == "/health":
                    self._send_json(relay.stats())
                    return
                if parsed.path == "/latest":
                    qs = parse_qs(parsed.query)
                    try:
                        limit = int(qs.get("limit", ["50"])[0])
                        after = int(qs.get("after", ["0"])[0])
                    except ValueError:
                        self.send_error(400, "invalid limit or cursor")
                        return
                    self._send_json(relay.latest(limit, after))
                    return
                if parsed.path == "/events":
                    self._stream_events()
                    return
                self.send_error(404, "not found")

            def do_OPTIONS(self) -> None:  # noqa: N802
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _send_json(self, value: Any) -> None:
                body = json.dumps(self._json_safe(value), ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            @staticmethod
            def _json_safe(item: Any) -> Any:
                # JavaScript Numbers cannot exactly represent the 64-bit battle IDs.
                # Preserve every large integer as a decimal string on every HTTP path.
                if isinstance(item, bool) or item is None:
                    return item
                if isinstance(item, int):
                    return str(item) if abs(item) > 9_007_199_254_740_991 else item
                if isinstance(item, list):
                    return [Handler._json_safe(child) for child in item]
                if isinstance(item, tuple):
                    return [Handler._json_safe(child) for child in item]
                if isinstance(item, dict):
                    return {key: Handler._json_safe(child) for key, child in item.items()}
                return item

            def _stream_events(self) -> None:
                client = relay.subscribe()
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    for item in relay.latest(50):
                        self._write_event(item)
                    while True:
                        item = client.get()
                        if item is None:
                            break
                        self._write_event(item)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    relay.unsubscribe(client)

            def _write_event(self, item: dict[str, Any]) -> None:
                line = json.dumps(
                    self._json_safe(item),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8") + b"\n"
                self.wfile.write(line)
                self.wfile.flush()

        return ThreadingHTTPServer((self.host, self.port), Handler)
