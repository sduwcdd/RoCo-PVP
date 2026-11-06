"""Payment timing is explicit input to the shared HUD query, never inferred."""
import unittest

from lab.research_phases import _skill_context


class EnergyContextTests(unittest.TestCase):
    def test_cast_captures_present_energy_without_mutating_fragment(self):
        context = {"fragments": {"a": {"energy_before_cast": 99}}}
        result = _skill_context(context, "a", {"member_id": "a:0", "energy": 8},
                                {"member_id": "b:0"}, {"effective_cost": 8})
        self.assertEqual(result["energy_before_cast"], 8)
        self.assertEqual(result["resolved_energy_cost"], 8)
        self.assertEqual(context["fragments"]["a"]["energy_before_cast"], 99)


if __name__ == "__main__":
    unittest.main()
