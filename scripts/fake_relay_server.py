"""常驻假中继：把真实抓包 dump 当成 /latest 一直提供，用于联调与演示。

真实链路（管理员权限 + 游戏在线 + Npcap）在自查时不一定具备，用这个替身
就能验证 server → live_battle → HUD 这一段。

用法：
    python scripts/fake_relay_server.py --port 8899
然后让工作台连它：
    $env:ROCO_RELAY='http://127.0.0.1:8899'; python -m lab.server --port 8766
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "artifacts"
ORDER = (
    "_battle_enter.json",
    "_battle_round_start.json",
    "_battle_cmd_sync.json",
    "_battle_perform_start.json",
    "_battle_finish.json",
)


def relay_safe(value):
    """中继会把 64 位整数序列化成字符串，替身必须照做。"""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return str(value) if abs(value) > 9_007_199_254_740_991 else value
    if isinstance(value, list):
        return [relay_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: relay_safe(item) for key, item in value.items()}
    return value


def build_rows() -> list[dict]:
    rows: list[dict] = [{"_relay_event_id": 1, "opencode": "0x0413", "content": {"noise": True}}]
    event_id = 1
    for name in ORDER:
        path = ART / name
        if not path.exists():
            continue
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict) or item.get("content") is None:
                continue
            event_id += 1
            rows.append({
                "_relay_event_id": event_id,
                "captureIntegrity": {"revision": "fake-relay", "epoch": "demo"},
                "opencode": item.get("opencode"),
                "opcode_name": item.get("meaning"),
                "summary_kind": "schema_decoded",
                "content": relay_safe(item.get("content")),
            })
    return rows


class FakeRelay(BaseHTTPRequestHandler):
    rows: list[dict] = []
    started_at = time.time()

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/latest":
            query = parse_qs(parsed.query)
            try:
                after = int((query.get("after") or ["0"])[0])
                limit = int((query.get("limit") or ["50"])[0])
            except ValueError:
                self.send_error(400, "bad cursor")
                return
            payload = [row for row in self.rows if row["_relay_event_id"] > after][:limit]
        elif parsed.path == "/health":
            payload = {
                "status": "ok", "mode": "fake", "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "events": len(self.rows), "latestEventId": len(self.rows),
                "history": len(self.rows), "clients": 0,
                "game_process_alive": False, "uptime_seconds": round(time.time() - self.started_at, 1),
            }
        else:
            self.send_error(404)
            return
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8899)
    args = parser.parse_args()
    rows = build_rows()
    if len(rows) < 2:
        print("没有 dump 文件可提供，先跑 scripts/replay_battle_track.py 之前那一步的 dump")
        return 1
    FakeRelay.rows = rows
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), FakeRelay)
    print(f"fake relay http://127.0.0.1:{args.port} rows={len(rows)}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
