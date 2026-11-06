"""Battle-local world assumptions and PVP isolation, no capture processes."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from lab.live_battle import BattleTracker, LiveBattleFeed


class WorldStarPolicyTests(unittest.TestCase):
    def test_world_underlevel_zero_and_own_ten_do_not_affect_pvp(self):
        tracker = BattleTracker()
        tracker.is_npc_battle = True
        tracker.world_star_overrides = {"1": 10}
        own = {"petId": 1, "side": 0, "level": 56}
        tracker._apply_stat_policy(own)
        self.assertEqual(own["natureStatsPolicy"]["stars"], 0)
        own["level"] = 60
        tracker._apply_stat_policy(own)
        self.assertEqual(own["natureStatsPolicy"]["stars"], 10)
        enemy = {**own, "side": 1}
        tracker._apply_stat_policy(enemy)
        self.assertIsNone(enemy["natureStatsPolicy"]["stars"])
        tracker.is_npc_battle = False
        tracker._apply_stat_policy(own)
        self.assertEqual(own["natureStatsPolicy"]["stars"], 5)
        tracker.reset()
        self.assertEqual(tracker.world_star_overrides, {})

    def feed(self):
        feed = LiveBattleFeed()
        feed.tracker.battle_id = 12
        feed.tracker.is_npc_battle = True
        feed.tracker._pet_by_id = {"1": SimpleNamespace(side=0)}
        feed._published_snapshot = {"runtime": {"mode":"world", "sessionId":"12", "snapshotToken":1,
            "myTeam":[{"petId":1, "level":60}]}}
        return feed

    def test_queue_republishes_without_new_packets_and_never_mutates_published_truth(self):
        feed = self.feed()
        request = {"sessionId":"12", "snapshotToken":1, "petId":1, "stars":10}
        feed.set_world_stars(request)
        self.assertEqual(feed.tracker.world_star_overrides, {})
        with patch.object(feed, "_get", return_value=[]), patch.object(feed.tracker, "snapshot", return_value={"runtime": {}}):
            result = feed.poll_once()
        self.assertEqual(feed.tracker.world_star_overrides, {"1":10})
        self.assertIn("snapshotToken", result["runtime"])
        self.assertEqual(request["snapshotToken"], 1)

    def test_requests_reject_stale_pvp_enemy_and_out_of_range(self):
        feed = self.feed()
        valid = {"sessionId":"12", "snapshotToken":1, "petId":1, "stars":0}
        for extra in ({"snapshotToken":2}, {"petId":2}, {"stars":True}, {"stars":11}):
            with self.assertRaises(ValueError): feed.set_world_stars({**valid, **extra})
        feed._published_snapshot["runtime"]["mode"] = "pvp"
        with self.assertRaises(ValueError): feed.set_world_stars(valid)

    def test_pending_assumption_is_discarded_after_battle_reset(self):
        feed = self.feed()
        feed.set_world_stars({"sessionId":"12", "snapshotToken":1, "petId":1, "stars":10})
        feed.tracker.reset()
        self.assertFalse(feed._apply_world_star_requests())
        self.assertEqual(feed.tracker.world_star_overrides, {})
