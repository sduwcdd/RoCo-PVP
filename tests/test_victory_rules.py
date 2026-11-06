"""Installed-rule accounting regressions; no online calibration is asserted."""
from copy import deepcopy
import unittest

from lab.research_battle import _finish, _outcome, _result
from lab.victory_rules import (initialize_victory, load_victory_rules,
                               reconcile_knockouts, terminal, validate_victory)


def state_with_six():
    return {"turn": 1, "teams": {side: {"active_slot": 0, "members": [
        {"member_id": f"{side}{slot}", "hp": 100} for slot in range(6)]} for side in ("a", "b")}}


class VictoryRulesTests(unittest.TestCase):
    def setUp(self):
        self.state = state_with_six()
        initialize_victory(self.state)

    def knockout(self, side, slot):
        self.state["teams"][side]["members"][slot]["hp"] = 0
        return reconcile_knockouts(self.state)

    def test_source_binding_and_initialization_are_explicit_and_idempotent(self):
        rules = load_victory_rules()
        self.assertEqual((rules["pvp_id"], rules["battle_config"], rules["max_round"]), (5001, 340005, 50))
        self.assertEqual(len(rules["source_hashes"]), 3)
        self.assertFalse(rules["runtime_version_verified"])
        self.assertEqual(self.state["victory"]["magic"], {"a": 4, "b": 4})
        before = deepcopy(self.state)
        self.assertIs(initialize_victory(self.state), self.state)
        self.assertEqual(self.state, before)
        with self.assertRaisesRegex(ValueError, "PVP5001"):
            initialize_victory(self.state, pvp_id=1001)

    def test_four_knockouts_end_six_member_roster_with_reserves_alive(self):
        for slot in range(4):
            events = self.knockout("b", slot)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["winning_points_delta"], 1)
            self.assertEqual(self.state["victory"]["magic"]["b"], 3 - slot)
            if slot < 3:
                self.assertFalse(terminal(self.state)["terminal"])
        self.assertEqual(self.state["victory"]["winning_points"]["a"], 4)
        self.assertEqual(terminal(self.state)["winner"], "a")
        self.assertEqual(_outcome(self.state), "a")
        self.assertTrue(all(m["hp"] > 0 for m in self.state["teams"]["b"]["members"][4:]))
        out = _result(self.state)
        _finish(out, self.state)
        self.assertEqual((out["status"], out["winner"]), ("finished", "a"))
        self.assertEqual(self.state["turn"], 1)

    def test_repeated_finish_and_phase_observations_do_not_double_charge(self):
        events = self.knockout("b", 0)
        self.assertEqual(events[0]["occurrence"], 1)
        for _ in range(3):
            self.assertEqual(reconcile_knockouts(self.state), [])
            out = _result(self.state)
            _finish(out, self.state, advance=False)
            self.assertEqual(out["status"], "awaiting_replacement")
        self.assertEqual(self.state["victory"]["magic"]["b"], 3)
        self.assertEqual(self.state["victory"]["winning_points"]["a"], 1)

    def test_observed_revival_allows_same_member_second_knockout(self):
        self.knockout("a", 0)
        self.state["teams"]["a"]["members"][0]["hp"] = 1
        self.assertEqual(reconcile_knockouts(self.state), [])
        events = self.knockout("a", 0)
        self.assertEqual(events[0]["occurrence"], 2)
        self.assertEqual(self.state["victory"]["magic"], {"a": 2, "b": 4})
        self.assertEqual(self.state["victory"]["winning_points"], {"a": 0, "b": 2})

    def test_simultaneous_final_knockouts_block_unknown_tie_policy(self):
        for slot in range(3):
            self.knockout("a", slot)
            self.knockout("b", slot)
        for side in ("a", "b"):
            self.state["teams"][side]["members"][3]["hp"] = 0
        events = reconcile_knockouts(self.state)
        self.assertEqual(len(events), 2)
        decision = terminal(self.state)
        self.assertTrue(decision["terminal"])
        self.assertIsNone(decision["winner"])
        self.assertEqual(decision["reason"], "simultaneous_magic_depletion")
        out = _result(self.state)
        _finish(out, self.state)
        self.assertEqual(out["status"], "blocked")
        self.assertTrue(out["blockers"])
        self.assertIsNone(out["winner"])
        self.assertEqual(self.state["research_battle"]["phase"], "blocked")

    def test_simultaneous_nonfinal_knockouts_charge_both_sides(self):
        for side in ("a", "b"):
            self.state["teams"][side]["members"][0]["hp"] = 0
        self.assertEqual(len(reconcile_knockouts(self.state)), 2)
        self.assertEqual(self.state["victory"]["magic"], {"a": 3, "b": 3})
        self.assertEqual(self.state["victory"]["winning_points"], {"a": 1, "b": 1})
        self.assertFalse(terminal(self.state)["terminal"])

    def test_round_50_may_begin_but_unknown_end_adjudication_blocks(self):
        self.knockout("b", 5)  # A point lead does not establish limit adjudication.
        self.state["turn"] = 50
        self.assertFalse(terminal(self.state)["terminal"])
        self.assertEqual(terminal(self.state, completed_turn=True)["reason"], "round_limit")
        out = _result(self.state)
        out["committed_actions"] = ["a", "b"]
        _finish(out, self.state)
        self.assertEqual(out["status"], "blocked")
        self.assertIsNone(out["winner"])
        self.assertFalse(out["turn_advanced"])
        self.assertEqual(self.state["turn"], 50)
        self.state["turn"] = 51
        self.assertTrue(terminal(self.state)["terminal"])

    def test_imported_dead_members_do_not_invent_historical_magic_loss(self):
        state = state_with_six()
        state["teams"]["a"]["members"][0]["hp"] = 0
        initialize_victory(state)
        self.assertEqual(reconcile_knockouts(state), [])
        self.assertEqual(state["victory"]["magic"]["a"], 4)

    def test_all_roster_exhausted_with_magic_remaining_blocks_without_hp_win(self):
        state = state_with_six()
        for member in state["teams"]["a"]["members"]:
            member["hp"] = 0
        initialize_victory(state)
        self.assertIsNone(_outcome(state))
        self.assertEqual(terminal(state)["reason"], "roster_exhausted_without_magic_depletion")

    def test_legacy_states_keep_previous_outcome_and_no_opt_in_side_effects(self):
        state = state_with_six()
        for member in state["teams"]["b"]["members"]:
            member["hp"] = 0
        before = deepcopy(state)
        self.assertEqual(reconcile_knockouts(state), [])
        self.assertEqual(_outcome(state), "a")
        self.assertEqual(state, before)
        self.assertNotIn("victory", state)

    def test_ledger_rejects_identity_and_score_changes(self):
        self.state["victory"]["magic"]["a"] = 3
        with self.assertRaisesRegex(ValueError, "disagree"):
            validate_victory(self.state)
        self.state["victory"]["magic"]["a"] = 4
        self.state["teams"]["a"]["members"][0]["member_id"] = "new-member"
        with self.assertRaisesRegex(ValueError, "member ledger"):
            reconcile_knockouts(self.state)


if __name__ == "__main__":
    unittest.main()
