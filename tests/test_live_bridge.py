"""rkpp relay consumer: parsing and incremental polling against a stub relay."""
from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lab.live_bridge import LiveBridge, parse_summary

SAMPLE = {
    "row_index": 441,
    "captured_at": "2026-04-11 14:53:48",
    "flow_id": "192.168.31.179:18946->36.155.236.215:8195",
    "direction": "s2c",
    "seq": 123456,
    "opencode": "0x1324",
    "opcode": 4900,
    "opcode_name": "ZoneBattleActionResolveNotify",
    "meaning": "ZoneBattleActionResolveNotify | 战斗行动结算通知",
    "summary_kind": "action_resolve",
    "summary_text": "我方行动 | 技能=火焰箭(7040370) | 能量变化=-2 -> 1 | 伤害=211",
    "content": {"primary_skill": {"skill_id": 7040370}},
}


class ParseTests(unittest.TestCase):
    def test_action_resolve_is_fully_parsed(self):
        event = parse_summary(SAMPLE)
        self.assertTrue(event["recognized"])
        self.assertEqual(event["side"], "my")
        self.assertEqual(event["skill_id"], 7040370)
        self.assertEqual(event["skill_name"], "火焰箭")
        self.assertEqual(event["energy_delta"], -2)
        self.assertEqual(event["energy_after"], 1)
        self.assertEqual(event["damage"], 211)

    def test_opponent_side_and_full_width_parentheses(self):
        event = parse_summary({"row_index": 2, "summary_kind": "action_resolve",
                               "summary_text": "敌方行动 | 技能=藤绞（7030200） | 伤害=88"})
        self.assertEqual(event["side"], "opponent")
        self.assertEqual(event["skill_id"], 7030200)
        self.assertEqual(event["skill_name"], "藤绞")
        self.assertIsNone(event["energy_delta"])
        self.assertEqual(event["damage"], 88)

    def test_switch_is_recognised_without_a_skill(self):
        event = parse_summary({"row_index": 3, "summary_kind": "action_resolve",
                               "summary_text": "我方换成 水蓝蓝"})
        self.assertEqual(event["side"], "my")
        self.assertTrue(event["recognized"])
        self.assertIsNone(event["skill_id"])

    def test_unknown_summary_is_kept_not_dropped(self):
        event = parse_summary({"row_index": 4, "summary_kind": "battle_end",
                               "summary_text": "战斗结束"})
        self.assertFalse(event["recognized"])
        self.assertEqual(event["text"], "战斗结束")


class _Handler(BaseHTTPRequestHandler):
    rows: list[dict] = []

    def do_GET(self):  # noqa: N802 (http.server API)
        if self.path.startswith("/health"):
            body = json.dumps({"status": "ok", "events": len(self.rows)}).encode()
        elif self.path.startswith("/latest"):
            body = json.dumps(self.rows).encode()
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.portal = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.portal.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _Handler.rows = [dict(SAMPLE), dict(SAMPLE, row_index=442, summary_text="敌方行动 | 技能=藤绞(7030200) | 伤害=88")]

    def test_state_reports_a_live_relay(self):
        state = LiveBridge(self.base).state()
        self.assertTrue(state["relay_available"])
        self.assertEqual(state["relay"], self.base)

    def test_poll_is_incremental(self):
        bridge = LiveBridge(self.base)
        first = bridge.poll()
        self.assertEqual([e["row_index"] for e in first["events"]], [441, 442])
        second = bridge.poll()
        self.assertEqual(second["events"], [], "第二次轮询不重复推送同一批事件")
        _Handler.rows.append(dict(SAMPLE, row_index=443, summary_text="我方行动 | 技能=火焰箭(7040370) | 伤害=300"))
        third = bridge.poll()
        self.assertEqual([e["row_index"] for e in third["events"]], [443])

    def test_dead_relay_is_reported_not_raised(self):
        bridge = LiveBridge("http://127.0.0.1:9")
        result = bridge.poll()
        self.assertFalse(result["relay_available"])
        self.assertEqual(result["events"], [])
        self.assertFalse(bridge.state()["relay_available"])


if __name__ == "__main__":
    unittest.main()
