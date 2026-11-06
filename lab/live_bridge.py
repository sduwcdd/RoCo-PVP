"""Consumer for the vendored rkpp relay (``opencode-server``).

The relay is started separately with administrator rights and Npcap:

    python vendor/rkpp/rkpp_live_tools.py opencode-server \
        --iface WLAN --port 8195 --relay-host 127.0.0.1 --relay-port 8765

It exposes ``/health``, ``/latest?limit=N`` and an NDJSON ``/events`` stream. This
module only reads ``/latest`` and turns each summary line into a compact battle
event for the workbench. Nothing here changes game state, and nothing is written
to disk: an unread relay simply reports ``relay_available: false``.

The parser is deliberately forgiving: an unrecognised summary keeps its raw text
and is marked ``kind: "unknown"`` rather than being dropped or guessed at.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE = "http://127.0.0.1:8765"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

_SIDE = re.compile(r"^(我方|敌方)")
_SKILL = re.compile(r"技能=([^|(（]+)[(（](\d+)[)）]")
_SKILL_ID_ONLY = re.compile(r"技能=(\d+)")
_ENERGY = re.compile(r"能量变化=(-?\d+)\s*(?:->|→)\s*(-?\d+)")
_DAMAGE = re.compile(r"伤害=(\d+)")
_SWITCH = re.compile(r"换成|换人|替补|登场")
_TURN = re.compile(r"第\s*(\d+)\s*回合")


def parse_summary(event: dict[str, Any]) -> dict[str, Any]:
    """Turn one relay event into a workbench-friendly battle event."""
    text = str(event.get("summary_text") or "")
    kind = str(event.get("summary_kind") or "unknown")
    out: dict[str, Any] = {
        "row_index": event.get("row_index"),
        "captured_at": event.get("captured_at"),
        "opcode_name": event.get("opcode_name"),
        "summary_kind": kind,
        "text": text,
        "side": None,
        "skill_id": None,
        "skill_name": None,
        "energy_delta": None,
        "energy_after": None,
        "damage": None,
        "turn": None,
        "recognized": False,
        "content": event.get("content"),
    }
    side = _SIDE.search(text)
    if side:
        out["side"] = "my" if side.group(1) == "我方" else "opponent"
    turn = _TURN.search(text)
    if turn:
        out["turn"] = int(turn.group(1))
    skill = _SKILL.search(text)
    if skill:
        out["skill_name"] = skill.group(1).strip()
        out["skill_id"] = int(skill.group(2))
    else:
        bare = _SKILL_ID_ONLY.search(text)
        if bare:
            out["skill_id"] = int(bare.group(1))
    energy = _ENERGY.search(text)
    if energy:
        out["energy_delta"] = int(energy.group(1))
        out["energy_after"] = int(energy.group(2))
    damage = _DAMAGE.search(text)
    if damage:
        out["damage"] = int(damage.group(1))
    if kind == "action_resolve" and (out["skill_id"] is not None or _SWITCH.search(text)):
        out["recognized"] = True
    elif out["skill_id"] is not None or out["damage"] is not None:
        out["recognized"] = True
    return out


class LiveBridge:
    """Incremental reader over one relay endpoint."""

    def __init__(self, base: str = DEFAULT_BASE, timeout: float = 3.0):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self._last_row: int | None = None
        self._seen: set[int] = set()
        self._last_error: str | None = None

    # -- transport -------------------------------------------------------
    def _get(self, path: str) -> Any:
        request = urllib.request.Request(self.base + path, headers={"Accept": "application/json"})
        # A local relay must not redirect requests or route them through an environment proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def health(self) -> dict[str, Any] | None:
        try:
            payload = self._get("/health")
        except (urllib.error.URLError, OSError, ValueError):
            self._last_error = "relay 未运行"
            return None
        return payload if isinstance(payload, dict) else None

    def _events(self, limit: int) -> list[dict[str, Any]]:
        payload = self._get(f"/latest?limit={int(limit)}")
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            rows = payload.get("events") or payload.get("latest") or payload.get("history") or []
        else:
            rows = []
        return [row for row in rows if isinstance(row, dict)]

    # -- polling ---------------------------------------------------------
    def poll(self, limit: int = 200) -> dict[str, Any]:
        """New events since the previous call, oldest first."""
        try:
            rows = self._events(limit)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self._last_error = f"relay 读取失败：{exc}"
            return {"relay_available": False, "error": self._last_error, "events": []}
        self._last_error = None
        parsed = []
        for row in sorted(rows, key=lambda r: r.get("row_index") or 0):
            index = row.get("row_index")
            if isinstance(index, int):
                if index in self._seen:
                    continue
                self._seen.add(index)
                self._last_row = index if self._last_row is None else max(self._last_row, index)
            parsed.append(parse_summary(row))
        if len(self._seen) > 5000:
            # Keep memory bounded without changing what the next poll returns:
            # ordering already guarantees monotonic row indexes.
            self._seen = set(sorted(self._seen)[-2000:])
        return {"relay_available": True, "error": None, "events": parsed, "last_row_index": self._last_row}

    def state(self) -> dict[str, Any]:
        health = self.health()
        return {
            "relay": self.base,
            "relay_available": health is not None,
            "health": health,
            "last_row_index": self._last_row,
            "error": self._last_error,
            "start_hint": (
                "python vendor/rkpp/rkpp_live_tools.py opencode-server "
                "--iface WLAN --port 8195 --relay-host 127.0.0.1 --relay-port 8765"
            ),
        }


_SHARED: LiveBridge | None = None


def shared(base: str = DEFAULT_BASE) -> LiveBridge:
    global _SHARED
    if _SHARED is None or _SHARED.base != base.rstrip("/"):
        _SHARED = LiveBridge(base)
    return _SHARED
