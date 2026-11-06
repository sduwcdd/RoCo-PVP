import unittest
from unittest.mock import patch

from lab import random_devotion_runtime as devotion


class RandomDevotionTests(unittest.TestCase):
    def state(self):
        return {"snapshot_id": "20261025T013619+0800", "teams": {"a": {}, "b": {}}}

    def test_replay_cursor_and_complete_pool(self):
        state, context = self.state(), devotion.research_context(17)
        first = devotion.apply(state, "a", context=context)
        self.assertEqual(first, devotion.apply(state, "a", context=context))
        self.assertNotIn("devotion", state["teams"]["a"])
        self.assertEqual(sum(first["state"]["teams"]["a"]["devotion"].values()), 2)
        second = devotion.apply(first["state"], "b", context=context)
        self.assertEqual([e["draw_index"] for e in second["events"]], [2, 3])
        self.assertEqual(len(devotion.rules()["pool"]), 5)
        self.assertFalse(second["training_eligible"])
        with self.assertRaises(ValueError):
            devotion.apply(first["state"], "a", context=devotion.research_context(18))
        with self.assertRaises(ValueError):
            devotion.apply(state, "a", context={})

    def test_replacement_and_unsupported_selection_never_rerolled(self):
        with patch.object(devotion.random.Random, "getrandbits", return_value=0):
            result = devotion.apply(self.state(), "a", context=devotion.research_context(0))
        self.assertEqual(result["state"]["teams"]["a"]["devotion"], {"power": 2})
        data = devotion.rules()
        data["pool"][0]["enhancement"] = "unimplemented"
        with patch.object(devotion, "rules", return_value=data), patch.object(
                devotion.random.Random, "getrandbits", return_value=0) as draw:
            result = devotion.apply(self.state(), "a", context=devotion.research_context(0))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(draw.call_count, 2)
        self.assertEqual(len(result["events"]), 2)
        self.assertEqual(result["state"]["random_devotion_rng"]["draw_index"], 2)
        self.assertTrue(all(e["selection"]["enhancement"] == "unimplemented" for e in result["events"]))
