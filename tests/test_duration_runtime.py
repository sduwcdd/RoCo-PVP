from copy import deepcopy
import unittest
from lab import duration_runtime as duration
from lab.research_phases import _fragment
from lab.server import load_catalog
from tests.test_defense_runtime import member


class DurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.programs = duration.programs(load_catalog()[0])

    def execute(self, mid, state=None, turn=4, response_success=None):
        state = state or {"self": member(), "opponent": member()}
        program = self.programs[mid]
        context = {**_fragment(program), **duration.research_context(), "turn": turn,
                   "resolved_energy_cost": program["static_fields"]["energy"]}
        if response_success is not None:
            context["response_success"] = response_success
        return duration.execute_duration_skill(program, state, context, damage_resolver=lambda *_: 7)

    def test_cost_duration_refresh_departure_and_delayed_stun(self):
        out = self.execute(7020650)
        self.assertEqual(out["status"], "applied", out["blockers"])
        target = out["state"]["opponent"]
        self.assertEqual([duration.cost(target, "physical", 3, t) for t in (3, 4, 5, 6, 7)], [3, 5, 5, 5, 3])
        self.assertEqual(duration.cost(target, "status", 3, 4), 3)
        self.assertEqual(duration.cost(duration.depart(target), "physical", 3, 4), 3)
        again = self.execute(7020650, {"self": member(), "opponent": target}, turn=5)
        self.assertEqual(len(again["state"]["opponent"]["timed_effects"]), 1)
        self.assertEqual(duration.cost(again["state"]["opponent"], "physical", 3, 7), 5)
        out = self.execute(7040650)
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertEqual(out["state"]["opponent"]["hp"], 93)
        self.assertEqual([duration.skip_action(out["state"]["self"], t)["skip"] for t in (4, 5, 6)], [False, True, False])

    def test_recovery_cooldown_boundaries_and_source_tamper(self):
        out = self.execute(7170300)
        self.assertEqual(out["status"], "applied", out["blockers"])
        target = out["state"]["opponent"]
        self.assertEqual([duration.recovery_amount(target, 8, t)["amount"] for t in (4, 5, 6)], [8, 3, 8])
        self.assertEqual(duration.recovery_amount(target, 3, 5)["amount"], 0)
        for turn in (4, 5, 6):
            with self.assertRaises(ValueError):
                duration.check_cooldown(out["state"]["self"], 7170300, turn)
        duration.check_cooldown(out["state"]["self"], 7170300, 7)
        changed = deepcopy(target)
        changed["timed_effects"][0]["amount"] = -6
        with self.assertRaises(ValueError):
            duration.recovery_amount(changed, 8, 5)

    def test_charge_token_response_refresh_and_consumption(self):
        out = self.execute(7100180)
        self.assertEqual(out["status"], "applied", out["blockers"])
        actor = out["state"]["self"]
        self.assertEqual(actor["hp"], 140)
        self.assertEqual([duration.charge_bypass(actor, t) for t in (4, 5, 6)], [True, True, False])
        consumed = duration.consume_charge_bypass(actor, 5)
        self.assertFalse(duration.charge_bypass(consumed["member"], 5))
        self.assertTrue(duration.charge_bypass(actor, 5))
        for success in (False, True):
            result = self.execute(7100200, response_success=success)
            self.assertEqual(result["status"], "applied", result["blockers"])
            self.assertEqual(duration.charge_bypass(result["state"]["self"], 4), success)
        refreshed = self.execute(7100200, state=out["state"], response_success=True)
        self.assertEqual(len(refreshed["state"]["self"]["timed_effects"]), 1)
        self.assertEqual(self.execute(7100200)["status"], "blocked")
