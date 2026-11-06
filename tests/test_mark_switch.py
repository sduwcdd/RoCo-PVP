"""Field inheritance and entry Swift share the mark executor."""
from copy import deepcopy
import unittest

from lab import mark_runtime as marks
from tests import test_switch_runtime as fixture


class MarkSwitchTests(unittest.TestCase):
    setUpClass = classmethod(fixture.SwitchRuntimeTests.setUpClass.__func__)
    actor = fixture.SwitchRuntimeTests.actor
    run_switch = fixture.SwitchRuntimeTests.run_switch
    enable_entry_attack = fixture.SwitchRuntimeTests.enable_entry_attack

    def setUp(self):
        fixture.SwitchRuntimeTests.setUp(self)
        self.context.update(marks.research_context())

    def test_entry_hazard_hits_incoming_once_and_stays_on_team(self):
        mark = {"id": 1019, "stacks": 2, "sources": []}
        self.state["teams"]["a"]["marks"]["negative"] = mark
        before = deepcopy(self.state)
        result = self.run_switch()
        self.assertEqual(result["status"], "applied", result["blockers"])
        team = result["state"]["teams"]["a"]
        self.assertEqual(team["members"][1]["hp"], 258)
        self.assertEqual(team["members"][0]["hp"], 300)
        self.assertEqual(team["marks"]["negative"], mark)
        self.assertNotIn("field_marks", team["members"][1])
        self.assertEqual(self.state, before)

    def test_swift_consumes_first_action_and_keeps_slot(self):
        self.enable_entry_attack()
        result = self.run_switch(resolver=lambda *_: 7)
        self.assertEqual(result["status"], "applied", result["blockers"])
        actor = result["state"]["teams"]["a"]["members"][1]
        self.assertEqual(actor["mark_entry_actions"], 1)
        self.assertEqual(actor["skill_slots"], [0, 0, 7150080, 0])
        self.assertNotIn("field_marks", actor)

    def test_swift_entry_attack_settles_star_mark_on_opponent(self):
        # 星陨印记已解码（20/层，非幻系攻击触发）。翼击是翼系魔法攻击，
        # 因此入场疾风的 7 点伤害之后，还要结算 20×1 的星陨伤害并清空层数。
        # 目标是对手"在场"成员（fixture 默认 b[0]），事件里记作 b-active。
        self.enable_entry_attack()
        self.state["teams"]["b"]["marks"]["negative"] = {"id": 1035, "stacks": 1, "sources": []}
        seen = []
        result = self.run_switch(resolver=lambda *_: seen.append(True) or 7)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(seen, [True])
        self.assertEqual(result["state"]["teams"]["b"]["members"][0]["hp"], 300 - 7 - 20)
        self.assertIsNone(result["state"]["teams"]["b"]["marks"]["negative"])

    def test_entry_energy_loss_rechecks_swift_affordability(self):
        self.enable_entry_attack()
        self.actor(1)["energy"] = 3
        self.state["teams"]["a"]["marks"]["negative"] = {"id": 1028, "stacks": 1, "sources": []}
        seen = []
        result = self.run_switch(resolver=lambda *_: seen.append(True) or 7)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["energy"], 2)
        self.assertFalse(result["entry_skill_executed"])
        self.assertEqual(seen, [])

    def test_unaffordable_after_entry_does_not_require_unsupported_skill_executor(self):
        self.actor(1).update(skill_slots=[7150260, 0, 0, 0], energy=1)
        self.context["incoming_effective_costs"] = [1, None, None, None]
        self.state["teams"]["a"]["marks"]["negative"] = {"id": 1028, "stacks": 1, "sources": []}
        result = self.run_switch()
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["energy"], 0)
        self.assertFalse(result["entry_skill_executed"])

    def test_energy_loss_can_select_a_later_affordable_swift_without_reordering_slots(self):
        self.enable_entry_attack()
        self.actor(1).update(skill_slots=[7150080, 7150150, 0, 0], energy=3)
        self.context["incoming_effective_costs"] = [3, 2, None, None]
        self.state["teams"]["a"]["marks"]["negative"] = {"id": 1028, "stacks": 1, "sources": []}
        seen = []
        result = self.run_switch(resolver=lambda *_: seen.append(True) or 7)
        self.assertEqual(result["status"], "applied", result["blockers"])
        actor = result["state"]["teams"]["a"]["members"][1]
        self.assertEqual(actor["energy"], 0)
        self.assertEqual(result["entry_swift"]["slot"], 1)
        self.assertEqual(actor["skill_slots"], [7150080, 7150150, 0, 0])
        self.assertIn("defense_runtime", actor)
        self.assertEqual(seen, [])

    def test_entry_exhaustion_commits_without_swift_under_full_turn_policy(self):
        self.enable_entry_attack()
        self.actor(1)["hp"] = 1
        self.context["faint_policy"] = "stop_remaining_skill_on_exhaustion_experiment"
        self.state["teams"]["a"]["marks"]["negative"] = {"id": 1019, "stacks": 1, "sources": []}
        seen = []
        result = self.run_switch(resolver=lambda *_: seen.append(True) or 7)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["teams"]["a"]["members"][1]["hp"], 0)
        self.assertFalse(result["entry_skill_executed"])
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
