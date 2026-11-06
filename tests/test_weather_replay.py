"""Weather projection contracts; constructed records, not real-game calibration."""
from copy import deepcopy
import unittest

from lab.server import load_catalog, import_request
from lab.weather_replay import replay_weather_records


class WeatherReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]

    def setUp(self):
        self.s = {"snapshot_id": self.catalog["snapshot_id"], "opening_full_hp": True,
            "teams": {"my": [{"member_id": "one", "form_id": 3001}],
                      "opponent": [{"member_id": "two", "form_id": 3001}]}, "rounds": []}

    def add(self, skill=None, enemy=None):
        turn = len(self.s["rounds"]) + 1
        r = {"turn": turn, "event_id": str(turn), "teams_snapshot": deepcopy(self.s["teams"]),
             "my": {"member_id": "one", "kind": "move" if skill else "wait", "move_id": skill},
             "opponent": {"member_id": "two", "kind": "move" if enemy else "wait", "move_id": enemy}}
        self.s["rounds"].append(r)
        return r

    def run_replay(self):
        return replay_weather_records(self.catalog, self.s)

    def test_empty_and_manual_weather_never_authoritative(self):
        self.assertIsNone(self.run_replay()["current"])
        self.add()["weather_observation"] = {"kind": "rain", "remaining_rounds": 8}
        self.assertIsNone(self.run_replay()["current"])

    def test_set_count_expire_and_undo_prefix(self):
        self.add(7050250)
        self.assertEqual(self.run_replay()["current"]["remaining_rounds"], 7)
        for _ in range(7):
            self.add()
        result = self.run_replay()
        self.assertIsNone(result["current"])
        self.assertEqual(result["frames"][-1]["events"][-1]["op"], "weather.expired")
        self.s["rounds"].pop()
        self.assertEqual(self.run_replay()["current"]["remaining_rounds"], 1)

    def test_override_order_and_uncertainty(self):
        r = self.add(7050250, 7080210)
        a = self.run_replay()
        self.assertEqual(a["current"]["kind"], "sandstorm")
        self.assertTrue(any("同时开启天气" in str(x) for x in a["uncertainty"]))
        r["action_order"] = ["opponent", "my"]
        self.assertEqual(self.run_replay()["current"]["kind"], "rain")

    def test_shadow_stacks_persist_without_editing_actual_hp(self):
        self.add(7110440)
        self.add()["my"]["remaining_hp_percent"] = 73
        before = deepcopy(self.s)
        result = self.run_replay()
        self.assertEqual(self.s, before)
        discharge = [e for e in result["frames"][-1]["events"] if e.get("effect_op") == "conductive.damage"]
        self.assertEqual(len(discharge), 2)
        self.assertTrue(all(e["applied"] is False and e["amount"] is None for e in discharge))
        self.assertEqual(result, self.run_replay())

    def test_own_exact_hp_is_projected_as_percent_only_inside_weather_shadow(self):
        self.add(7090370)["my"].update(remaining_hp_exact=0, max_hp_exact=500)
        before = deepcopy(self.s)
        result = self.run_replay()
        self.assertNotIn("freeze", result["affected"][0]["weather_statuses"])
        self.assertEqual(self.s, before)

    def test_switch_targets_bench_does_not_receive_weather(self):
        self.s["teams"]["my"].append({"member_id": "bench", "form_id": 3001})
        self.add(7090370)
        r = self.add()
        r["my"].update(kind="switch", target_member_id="bench")
        result = self.run_replay()
        active = result["frames"][-1]["affected"][0]
        self.assertEqual(active["member_id"], "bench")
        self.assertEqual(active["weather_statuses"]["freeze"], 2)

    def test_unknown_move_and_bad_turn_rejected(self):
        r = self.add(999999999)
        with self.assertRaisesRegex(ValueError, "未知技能"):
            self.run_replay()
        r["turn"] = 2
        with self.assertRaisesRegex(ValueError, "连续记录"):
            self.run_replay()

    def test_rain_extension_uses_same_runtime_and_response_branch(self):
        self.add(7050250)
        r = self.add(7050530)
        self.assertEqual(self.run_replay()["current"]["remaining_rounds"], 10)
        r["my"]["response_success"] = True
        result = self.run_replay()
        self.assertEqual(result["current"]["remaining_rounds"], 14)
        self.assertTrue(any(e["op"] == "weather.extend" for e in result["frames"][-1]["events"]))

    def test_switch_clears_conductive_per_named_policy(self):
        self.s["teams"]["my"].append({"member_id": "bench", "form_id": 3001})
        self.add(7110440)
        self.add()["my"].update(kind="switch", target_member_id="bench")
        r = self.add()
        r["my"].update(kind="switch", member_id="bench", target_member_id="one")
        self.assertEqual(self.run_replay()["affected"][0]["weather_statuses"]["conductive"], 1)

    def test_fainted_member_not_affected(self):
        self.add(7090370)["opponent"]["remaining_hp_percent"] = 0
        result = self.run_replay()
        self.assertNotIn("freeze", result["affected"][1]["weather_statuses"])

    def test_http_dispatch_and_snapshot_check(self):
        self.add(7050250)
        result = import_request("/api/weather/replay", {"session": self.s})
        self.assertEqual(result["current"]["kind"], "rain")
        self.assertFalse(result["training_eligible"])
        self.s["snapshot_id"] = "other"
        with self.assertRaisesRegex(ValueError, "快照"):
            self.run_replay()


if __name__ == "__main__":
    unittest.main()
