"""Source immunity, exact choices, deterministic draws and whole skill chain."""
from copy import deepcopy
import unittest

from lab import forced_switch_programs as programs, forced_switch_runtime as forced
from tests import test_action_runtime as fixtures


class ForcedSwitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.JointActionRuntimeTests.setUpClass()
        cls.catalog = fixtures.JointActionRuntimeTests.catalog

    def setUp(self):
        fixture = fixtures.JointActionRuntimeTests()
        fixture.setUp()
        self.state = fixture.state
        self.context = {"snapshot_id": self.catalog["snapshot_id"],
            "forced_switch_policies": forced.policies(), "event_token": "skill-after-1", "random_seed": 7}

    def run_component(self, cause, slot=None, state=None):
        return forced.execute_forced_switch_fragment(self.catalog, self.state if state is None else state,
            "a", cause, target_slot=slot, context=self.context)

    def test_detach_return_source_immunity_and_no_swift(self):
        original = deepcopy(self.state)
        result = self.run_component("detach", 0)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(self.state, original)
        self.assertEqual(result["state"]["teams"]["a"]["active_slot"], 0)
        self.assertEqual(result["state"]["teams"]["a"]["members"][0]["energy"], 10)
        self.assertFalse(any("swift" in e["op"] for e in result["events"]))
        returned = self.run_component("return")
        self.assertEqual(returned["status"], "applied", returned["blockers"])
        self.assertEqual(returned["state"]["teams"]["a"]["active_slot"], 1)
        self.assertEqual(returned["state"]["teams"]["a"]["members"][1]["entered_turn"], 2)
        self.state["teams"]["a"]["members"][1]["entered_turn"] = 2
        immune = self.run_component("detach", 0)
        self.assertFalse(immune["switch_fragment_executed"])
        self.assertEqual(immune["state"]["teams"]["a"]["active_slot"], 1)

    def test_emergency_reproducibility_full_pool_and_failure_atomicity(self):
        reserve = deepcopy(self.state["teams"]["a"]["members"][0])
        reserve["member_id"] = "a-third"
        self.state["teams"]["a"]["members"].append(reserve)
        left, right = self.run_component("emergency"), self.run_component("emergency")
        self.assertEqual(left["status"], "applied", left["blockers"])
        self.assertEqual(left, right)
        self.assertEqual(left["events"][0]["random_draw"]["all_candidates"], [0, 2])
        blocked = self.run_component("emergency", 0)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["state"], self.state)
        repeat = self.run_component("emergency", state=left["state"])
        self.assertEqual(repeat["status"], "blocked")

    def test_whole_damage_detach_program_and_preflight_choice(self):
        from lab.skill_execution import execute_skill
        trusted = programs.programs(self.catalog)
        self.assertEqual(set(trusted), {7030290, 7040240, 7060290, 7110220, 7110370, 7170360, 7110270})
        with self.assertRaises(ValueError):
            programs.preflight_selection(self.catalog, self.state, "a", 7060290, None)
        programs.preflight_selection(self.catalog, self.state, "a", 7060290, 0)
        fixture = fixtures.JointActionRuntimeTests()
        fixture.setUp()
        from lab.switch_runtime import _typed_actor
        from lab.prepared_rules import prepare_rules
        rules = prepare_rules(self.catalog)._rules
        actors = {"self": _typed_actor(rules, self.state["teams"]["a"]["members"][1]),
                  "opponent": _typed_actor(rules, self.state["teams"]["b"]["members"][1])}
        context = fixture.fragment(7060290)
        result = execute_skill(trusted[7060290], actors, context, damage_resolver=lambda *_: 7)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["opponent"]["hp"], 293)

    def test_opponent_return_energy_steal_and_incoming_energy_followup(self):
        programs.preflight_selection(self.catalog, self.state, "a", 7110370, None)
        returned = programs.after_skill(self.catalog, self.state, "a", 7110370,
            replacement_slot=None, event_token="remote", context={})
        self.assertEqual(returned["status"], "applied", returned["blockers"])
        self.assertEqual(returned["state"]["teams"]["b"]["members"][1]["entered_turn"], 2)
        self.assertEqual(returned["state"]["teams"]["a"]["members"][1]["entered_turn"], 1)
        power = programs.after_skill(self.catalog, self.state, "a", 7110270,
            replacement_slot=0, event_token="power", context={})
        self.assertEqual(power["status"], "applied", power["blockers"])
        self.assertEqual(power["state"]["teams"]["a"]["members"][0]["energy"], 18)
        self.assertEqual(power["state"]["teams"]["a"]["members"][1]["energy"], 10)
        capped = deepcopy(self.state)
        capped["teams"]["a"]["members"][0]["energy"] = 19
        capped = programs.after_skill(self.catalog, capped, "a", 7110270,
            replacement_slot=0, event_token="capped", context={})
        self.assertEqual(capped["state"]["teams"]["a"]["members"][0]["energy"], 20)
        actor = self.state["teams"]["a"]["members"][1]
        actor["rooted"] = True
        immune = programs.after_skill(self.catalog, self.state, "a", 7110270,
            replacement_slot=None, event_token="rooted", context={})
        self.assertEqual(immune["status"], "applied", immune["blockers"])
        self.assertEqual(immune["state"]["teams"]["a"]["members"][1]["energy"], 10)
        self.assertEqual(programs.programs(self.catalog)[7170360]["operations"],
            [{"op": "energy.transfer", "params": {"target": "opponent", "amount": 2}}])
        from lab.research_phases import _fragment
        from lab.skill_execution import execute_skill
        from lab.switch_runtime import _typed_actor
        from lab.prepared_rules import prepare_rules
        rules = prepare_rules(self.catalog)._rules
        actors = {"self": _typed_actor(rules, actor),
                  "opponent": _typed_actor(rules, self.state["teams"]["b"]["members"][1])}
        actors["opponent"]["energy"] = 1
        trusted = programs.programs(self.catalog)
        steal = execute_skill(trusted[7170360], actors,
            {**_fragment(trusted[7170360]), "resolved_energy_cost": 3})
        self.assertEqual(steal["status"], "applied", steal["blockers"])
        self.assertEqual((steal["state"]["self"]["energy"], steal["state"]["opponent"]["energy"]), (8, 0))
        pure = execute_skill(trusted[7110370], actors,
            {**_fragment(trusted[7110370]), "resolved_energy_cost": 1})
        self.assertEqual(pure["status"], "applied", pure["blockers"])
        self.assertEqual(pure["state"]["self"]["energy"], 9)
        self.assertEqual(pure["state"]["opponent"]["hp"], actors["opponent"]["hp"])


if __name__ == "__main__":
    unittest.main()
