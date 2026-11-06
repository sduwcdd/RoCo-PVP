"""Status-fragment tests use synthetic damage, never real-game calibration."""
from copy import deepcopy
import unittest

from lab.effect_runtime import HOOKS
from lab.prepared_rules import PreparedRules
from lab.server import load_catalog
from lab.status_runtime import execute_status_phase


def member(mid, form=3001):
    return {"member_id": mid, "form_id": form, "hp": 300, "max_hp": 350,
            "energy": 10, "max_energy": 20, "speed": 100, "entered_turn": 1,
            "rooted": False, "charge": None, "skill_slots": [0, 7020360, 0, 7020780],
            "statuses": {}, "stat_modifiers": {}}


class StatusRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        cls.prepared = PreparedRules(cls.catalog)

    def setUp(self):
        self.state = {"snapshot_id": self.catalog["snapshot_id"], "turn": 2,
                      "teams": {s: {"active_slot": 1,
                                    "members": [member(s+"-reserve", 3016), member(s+"-active")],
                                    "marks": {"positive": None, "negative": None}} for s in ("a", "b")}}
        self.actor("a")["statuses"] = {"poison": 2, "burn": 4}
        self.actor("b")["statuses"] = {"burn": 2}
        self.context = {
            "mode": "isolated_status_phase_experiment", "snapshot_id": self.prepared.snapshot_id,
            "catalog_content_hash": self.prepared.catalog_content_hash,
            "excluded_hooks": sorted(HOOKS), "unresolved_dependencies": [],
            "operation_order": "damage_then_decay_experiment",
            "schedule": [{"side": "a", "status": "poison"}, {"side": "a", "status": "burn"},
                         {"side": "b", "status": "burn"}],
            "status_policy": {"immunity": "reject_existing_immune_status", "burn_decay_rounding": "exact"},
        }

    def actor(self, side, state=None):
        state = self.state if state is None else state
        team = state["teams"][side]
        return team["members"][team["active_slot"]]

    def run_status(self, resolver=None, rules=None):
        return execute_status_phase(self.prepared if rules is None else rules, self.state, self.context,
                                    damage_resolver=resolver)

    def assert_blocked(self, result):
        self.assertEqual(result["status"], "blocked", result)
        self.assertEqual(result["state"], self.state)
        self.assertEqual(result["events"], [])
        self.assertFalse(result["status_phase_executed"])
        self.assertFalse(result["training_eligible"])
        self.assertFalse(result["full_turn_executed"])

    def test_decay_conversion_uses_original_schedule(self):
        from lab import trait_runtime as traits
        form=next(f for f in self.catalog['forms'] if f.get('trait_id')==200273)
        self.actor('a')['form_id']=form['id']
        self.actor('a')['statuses']={}
        self.state['trait_policy']=traits.POLICY
        traits.bind(self.prepared,self.state)
        self.context['schedule']=[{'side':'b','status':'burn'}]
        result=self.run_status(lambda *_: 1)
        self.assertEqual(result['status'],'applied',result['blockers'])
        self.assertEqual(self.actor('b',result['state'])['statuses']['poison'],1)
        self.assertEqual(len([e for e in result['events'] if e['op']=='status.tick']),1)

    def test_poison_burn_damage_is_callback_final_loss_and_decay_separate(self):
        seen = []
        def resolver(descriptor, state, context):
            seen.append(descriptor)
            return 7
        result = self.run_status(resolver)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(self.actor("a", result["state"])["hp"], 286)
        self.assertEqual(self.actor("b", result["state"])["hp"], 293)
        self.assertEqual(self.actor("a", result["state"])["statuses"], {"poison": 2, "burn": 2})
        self.assertEqual(self.actor("b", result["state"])["statuses"], {"burn": 1})
        self.assertEqual([d["rate"] for d in seen], [{"numerator": 3, "denominator": 100},
                                                    {"numerator": 2, "denominator": 100},
                                                    {"numerator": 2, "denominator": 100}])
        self.assertEqual([d["damage_type"] for d in seen], ["毒系", "火系", "火系"])
        self.assertEqual([d["source"]["key"] for d in seen], [1001, 1002, 1002])
        self.assertEqual(result["state"]["turn"], 2)
        self.assertFalse(result["end_of_turn_executed"])
        self.assertFalse(result["real_game_verified"])
        self.assertFalse(result["training_eligible"])

    def test_no_status_is_noop_and_needs_no_damage_formula(self):
        for side in ("a", "b"):
            self.actor(side)["statuses"] = {"burn": 0, "freeze": 0, "leech": 0}
        self.context["schedule"] = []
        result = self.run_status()
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"], self.state)
        self.assertEqual(result["events"], [])

    def test_nonzero_status_without_formula_blocks(self):
        self.assert_blocked(self.run_status())

    def test_callback_and_returned_result_are_isolated(self):
        original_state, original_context = deepcopy(self.state), deepcopy(self.context)
        def resolver(descriptor, state, context):
            descriptor["stacks"] = 999
            descriptor["rate"]["numerator"] = 999
            self.actor("a", state)["hp"] = 1
            context["schedule"].clear()
            context["status_policy"]["burn_decay_rounding"] = "broken"
            return 3
        result = self.run_status(resolver)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual([e["stacks_before"] for e in result["events"]], [2, 4, 2])
        self.assertEqual(result["events"][0]["rate"]["numerator"], 3)
        self.assertEqual(self.state, original_state)
        self.assertEqual(self.context, original_context)
        result["state"]["teams"]["a"]["members"].clear()
        result["events"][0]["source"]["evidence"]["content_sha256"] = "bad"
        again = self.run_status(lambda *_: 3)
        self.assertEqual(again["status"], "applied", again["blockers"])
        self.assertEqual(self.state, original_state)

    def test_schedule_drives_current_state_not_original_hp_or_stacks(self):
        def resolver(descriptor, state, context):
            # A controlled synthetic formula to expose ordering differences.
            if descriptor["status"] == "poison":
                return self.actor("a", state)["statuses"]["burn"]
            return self.actor(descriptor["target_side"], state)["hp"] // 100
        original_order = self.run_status(resolver)
        self.assertEqual(self.actor("a", original_order["state"])["hp"], 294)
        self.context["schedule"][:2] = list(reversed(self.context["schedule"][:2]))
        reverse_order = self.run_status(resolver)
        self.assertEqual(self.actor("a", reverse_order["state"])["hp"], 295)
        self.assertEqual(reverse_order["events"][1]["hp_before"], 297)

    def test_missing_duplicate_extra_and_malformed_schedule_reject_before_callback(self):
        bad_schedules = [None, [], self.context["schedule"][:-1], self.context["schedule"]*2,
                         self.context["schedule"] + [{"side": "b", "status": "poison"}],
                         [{"side": "a", "status": "freeze"}], [{"side": "a", "status": "burn", "skip": True}],
                         [{"side": "c", "status": "burn"}]]
        for schedule in bad_schedules:
            with self.subTest(schedule=schedule):
                self.context["schedule"] = schedule
                calls = []
                self.assert_blocked(self.run_status(lambda *args: calls.append(args) or 1))
                self.assertEqual(calls, [])

    def test_odd_burn_exact_rejects_before_any_callback(self):
        self.actor("b")["statuses"]["burn"] = 3
        calls = []
        self.assert_blocked(self.run_status(lambda *args: calls.append(args) or 1))
        self.assertEqual(calls, [])

    def test_burn_floor_and_ceil_remain_explicit_different_experiments(self):
        self.actor("a")["statuses"]["burn"] = 3
        for rounding, expected in (("floor", 1), ("ceil", 2)):
            self.context["status_policy"]["burn_decay_rounding"] = rounding
            result = self.run_status(lambda *_: 0)
            self.assertEqual(result["status"], "applied", result["blockers"])
            event = result["events"][1]
            self.assertEqual(event["stacks_after"], expected)
            self.assertEqual(event["decay_remaining_unrounded"], {"numerator": 3, "denominator": 2})
            self.assertEqual(event["decay_rounding"], rounding)
            self.assertEqual(event["operation_order"], "damage_then_decay_experiment")

    def test_second_callback_failure_rolls_back_damage_and_decay(self):
        calls = []
        def resolver(descriptor, *_):
            calls.append(descriptor["schedule_index"])
            if len(calls) == 3:
                raise RuntimeError("synthetic second-actor failure")
            return 3
        self.assert_blocked(self.run_status(resolver))
        self.assertEqual(calls, [0, 1, 2])

    def test_exhaustion_does_not_continue_or_publish_partial_phase(self):
        calls = []
        def resolver(descriptor, state, context):
            calls.append(descriptor["schedule_index"])
            if descriptor["schedule_index"] == 1:
                return self.actor("a", state)["hp"]
            return 2
        self.assert_blocked(self.run_status(resolver))
        self.assertEqual(calls, [0, 1])

    def test_invalid_resolver_values_do_not_coerce_or_cap(self):
        for value in (-1, 301, 1.0, True, None, float("nan"), {"damage": 1}):
            with self.subTest(value=value):
                self.assert_blocked(self.run_status(lambda *_, value=value: value))

    def test_existing_freeze_leech_block_before_poison_callback(self):
        for status in ("freeze", "leech"):
            with self.subTest(status=status):
                self.actor("b")["statuses"][status] = 1
                calls = []
                self.assert_blocked(self.run_status(lambda *args: calls.append(args) or 1))
                self.assertEqual(calls, [])
                del self.actor("b")["statuses"][status]

    def test_existing_immune_status_is_neither_removed_nor_silently_skipped(self):
        for status, dtype in (("poison", "毒系"), ("burn", "火系")):
            form = next(f for f in self.catalog["forms"] if dtype in f["types"])
            self.actor("b")["form_id"] = form["id"]
            self.actor("b")["statuses"] = {status: 2}
            self.context["schedule"][-1] = {"side": "b", "status": status}
            calls = []
            self.assert_blocked(self.run_status(lambda *args: calls.append(args) or 1))
            self.assertEqual(calls, [])

    def test_existing_types_must_match_exact_form(self):
        self.actor("a")["types"] = ["火系"]
        self.assert_blocked(self.run_status(lambda *_: 1))

    def test_source_term_change_even_with_old_hash_requires_review(self):
        catalog = deepcopy(self.catalog)
        next(t for t in catalog["glossary"] if t["key"] == 1001)["definition"] += " Changed."
        prepared = PreparedRules(catalog)
        self.context["catalog_content_hash"] = prepared.catalog_content_hash
        self.assert_blocked(self.run_status(lambda *_: 1, prepared))

    def test_source_hash_change_requires_review(self):
        catalog = deepcopy(self.catalog)
        catalog["provenance"]["Terms"]["content_sha256"] = "unknown"
        prepared = PreparedRules(catalog)
        self.context["catalog_content_hash"] = prepared.catalog_content_hash
        self.assert_blocked(self.run_status(lambda *_: 1, prepared))

    def test_source_duplicate_and_missing_term_reject(self):
        for duplicate in (True, False):
            catalog = deepcopy(self.catalog)
            term = next(t for t in catalog["glossary"] if t["key"] == 1002)
            if duplicate:
                catalog["glossary"].append(deepcopy(term))
            else:
                catalog["glossary"].remove(term)
            prepared = PreparedRules(catalog)
            self.context["catalog_content_hash"] = prepared.catalog_content_hash
            self.assert_blocked(self.run_status(lambda *_: 1, prepared))

    def test_explicit_context_dependencies_and_policy_are_required(self):
        original = deepcopy(self.context)
        changes = [("mode", "full_battle"), ("snapshot_id", "other"), ("catalog_content_hash", "stale"),
                   ("excluded_hooks", []), ("excluded_hooks", sorted(HOOKS)+["marks"]),
                   ("unresolved_dependencies", ["missing damage"]), ("operation_order", None),
                   ("status_policy", {"immunity": "skip", "burn_decay_rounding": "exact"}),
                   ("status_policy", {"immunity": "reject_existing_immune_status", "burn_decay_rounding": "guess"})]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                self.context = {**deepcopy(original), key: value}
                calls = []
                self.assert_blocked(self.run_status(lambda *args: calls.append(args) or 1))
                self.assertEqual(calls, [])
        self.context = deepcopy(original)
        del self.context["unresolved_dependencies"]
        self.assert_blocked(self.run_status(lambda *_: 1))

    def test_malformed_joint_and_resource_states_block(self):
        original = deepcopy(self.state)
        mutations = [lambda s: s.update(snapshot_id="other"),
                     lambda s: s["teams"]["a"].update(active_slot=6),
                     lambda s: self.actor("b", s).update(member_id="a-active"),
                     lambda s: self.actor("b", s).update(hp=0),
                     lambda s: self.actor("b", s).update(hp=351),
                     lambda s: self.actor("b", s).update(energy=21),
                     lambda s: self.actor("b", s).update(statuses={"burn": True}),
                     lambda s: self.actor("b", s).update(statuses={"unknown": 1})]
        for mutate in mutations:
            self.state = deepcopy(original)
            mutate(self.state)
            calls = []
            self.assert_blocked(self.run_status(lambda *args: calls.append(args) or 1))
            self.assertEqual(calls, [])

    def test_bench_marks_and_unknown_metadata_are_preserved_not_processed(self):
        reserve = self.state["teams"]["a"]["members"][0]
        reserve["statuses"] = {"freeze": 8, "burn": 3}
        self.state["teams"]["a"]["marks"] = {"negative": {"term_id": 1014, "stacks": 2}, "positive": None}
        self.actor("a")["observed_config"] = {"raw_code": "preserve", "skill_slots": [0, 1, 0, 2]}
        result = self.run_status(lambda *_: 1)
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["teams"]["a"]["members"][0], reserve)
        self.assertEqual(result["state"]["teams"]["a"]["marks"], self.state["teams"]["a"]["marks"])
        self.assertEqual(self.actor("a", result["state"])["observed_config"], self.actor("a")["observed_config"])
        self.assertTrue(any("poison marks" in x for x in result["unresolved"]))

    def test_catalog_and_prepared_paths_match_including_hashes(self):
        prepared = self.run_status(lambda *_: 1)
        fresh = self.run_status(lambda *_: 1, self.catalog)
        self.assertEqual(prepared, fresh)
        self.assertEqual(prepared["events"][0]["target_member_id"], "a-active")
        self.assertEqual(prepared["events"][0]["catalog_hash"], self.prepared.catalog_content_hash)
        self.assertEqual(prepared["events"][0]["source"]["evidence"]["snapshot_id"], self.prepared.snapshot_id)


if __name__ == "__main__":
    unittest.main()
