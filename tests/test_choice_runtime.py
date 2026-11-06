from copy import deepcopy
import unittest
from lab import choice_runtime as choice
from lab.research_phases import _fragment
from lab.server import load_catalog
from tests.test_defense_runtime import member


class ChoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.programs = choice.choice_programs(load_catalog()[0])

    def execute(self, mid, option):
        program = self.programs[mid]
        self.state = {"self": member(), "opponent": member()}
        context = _fragment(program)
        context.update(choice_policy=choice.POLICY, resolved_energy_cost=program["static_fields"]["energy"])
        return choice.execute_choice_skill(program, self.state, context, option=option)

    def test_each_branch_and_one_payment(self):
        out = self.execute(7030600, 0)
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertEqual((out["state"]["self"]["hp"], out["state"]["self"]["energy"]), (150, 3))
        out = self.execute(7030600, 1)
        self.assertEqual((out["state"]["self"]["hp"], out["state"]["self"]["energy"]), (100, 10))
        self.assertEqual(self.execute(7040660, 0)["state"]["opponent"]["statuses"], {"burn": 7})
        self.assertEqual(self.execute(7040660, 1)["state"]["opponent"]["stat_modifiers"]["pdef"],
                         [{"numerator": -90, "denominator": 100}])
        from lab.mechanism_runtime import modify_speed
        out = self.execute(7070210, 0)
        self.assertEqual(out["status"], "applied", out["blockers"])
        self.assertEqual(modify_speed(out["state"]["self"], 100), 160)
        self.assertEqual(out["state"]["self"]["energy"], 4)
        self.assertEqual(self.execute(7070210, 1)["state"]["self"]["stat_modifiers"]["patk"],
                         [{"numerator": 90, "denominator": 100}])

    def test_missing_invalid_or_tampered_choice_is_atomic(self):
        for option in (None, True, -1, 2):
            out = self.execute(7030600, option)
            self.assertEqual(out["status"], "blocked")
            self.assertEqual(out["state"], self.state)
            self.assertEqual(out["events"], [])
        program = deepcopy(self.programs[7030600])
        program["choice_components"][0] = []
        with self.assertRaises(ValueError):
            choice.select(program, 0, context={"choice_policy": choice.POLICY})
