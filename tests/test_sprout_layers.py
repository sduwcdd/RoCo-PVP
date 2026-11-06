"""Layer composition tests; the ten-percent mapping is a named experiment."""
from copy import deepcopy
import unittest

from lab import mark_runtime as marks
from lab.effect_runtime import execute_effects
from tests import test_effect_runtime as fixture


class SproutLayersTests(unittest.TestCase):
    setUpClass = classmethod(fixture.EffectRuntimeTests.setUpClass.__func__)
    program = fixture.EffectRuntimeTests.program
    state = fixture.EffectRuntimeTests.state
    context = fixture.EffectRuntimeTests.context

    def setUp(self):
        self.p = deepcopy(self.program("魔镜"))
        # Synthetic composition fixture, not a claim that Mirror buffs its foe.
        self.p["operations"] = [self.p["operations"][0]]
        self.p["operations"][0]["params"]["percent"] = {"numerator": 20, "denominator": 100}
        self.s, self.c = self.state(), self.context(self.p)
        self.s["opponent"]["field_marks"] = {
            "positive": {"id": 3012, "stacks": 2, "sources": []}, "negative": None}
        self.c.update(marks.research_context())

    def test_sprout_adds_layers_once_and_preserves_input(self):
        before = deepcopy((self.s, self.p))
        result = execute_effects(self.p, self.s, self.c)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["opponent"]["stat_modifiers"]["mdef"],
                         [{"numerator": 2, "denominator": 5}])
        self.assertEqual((self.s, self.p), before)

    def test_unmapped_fraction_blocks_before_payment(self):
        self.p["operations"][0]["params"]["percent"] = {"numerator": 15, "denominator": 100}
        self.c["resolved_energy_cost"] = 2
        result = execute_effects(self.p, self.s, self.c)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["state"], self.s)
        self.assertEqual(result["events"], [])

    def test_debuff_unchanged_and_missing_policy_rejected(self):
        self.c.pop("mark_policies")
        self.assertEqual(execute_effects(self.p, self.s, self.c)["status"], "blocked")
        self.p["operations"][0]["params"]["percent"]["numerator"] = -20
        result = execute_effects(self.p, self.s, self.c)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["opponent"]["stat_modifiers"]["mdef"],
                         [{"numerator": -20, "denominator": 100}])


if __name__ == "__main__":
    unittest.main()
