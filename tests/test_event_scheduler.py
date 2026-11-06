"""Scheduler composition checks; synthetic events are not game observations."""
from copy import deepcopy
import unittest

from lab.event_scheduler import dispatch_events


def source(rule="skill:1", component="effect:0"):
    return {"rule_id": rule, "component_id": component, "snapshot_id": "synthetic-test"}


def event(name="skill.use", **payload):
    return {"name": name, "payload": payload, "source": source()}


def subscription(sid="skill", name="skill.use", handler="add", order=None, maximum=10):
    return {"id": sid, "event": name, "handler": handler, "order": order,
            "max_executions": maximum, "source": source(sid)}


class EventSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.state = {"energy": 0, "nested": {"retained": [1]}}
        self.policy = {"mode": "explicit_fifo_experiment", "max_events": 30,
                       "max_depth": 8, "max_handler_calls": 30}

    def add(self, state, current):
        state["energy"] += current["payload"].get("amount", 1)
        return {"state": state, "events": [], "result": state["energy"]}

    def run_events(self, events=None, subscriptions=None, handlers=None, policy=None):
        return dispatch_events(self.state, [event()] if events is None else events,
                               [subscription()] if subscriptions is None else subscriptions,
                               {"add": self.add} if handlers is None else handlers,
                               policy=self.policy if policy is None else policy)

    def assert_blocked(self, result):
        self.assertEqual(result["status"], "blocked", result)
        self.assertEqual(result["state"], self.state)
        self.assertEqual(result["results"], {})
        self.assertTrue(result["blockers"])
        self.assertTrue(result["trace_is_diagnostic"])
        self.assertFalse(result["full_turn_executed"])
        self.assertFalse(result["training_eligible"])
        self.assertNotIn("events", result)

    def test_single_subscription_preserves_source_and_result(self):
        result = self.run_events(events=[event(amount=3)])
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["state"]["energy"], 3)
        self.assertEqual(result["results"], {"skill": [3]})
        self.assertEqual(result["trace"][0]["source"], source())
        self.assertEqual(result["trace"][1]["source"], source("skill"))
        self.assertFalse(result["calibrated"])
        self.assertEqual(self.state["energy"], 0)

    def test_nested_emission_retains_parent_and_uses_updated_state(self):
        def first(state, current):
            state["energy"] = 10
            return {"state": state, "events": [event("status.tick", amount=2)]}
        result = self.run_events(subscriptions=[subscription(handler="first"),
                                               subscription("status", "status.tick")],
                                 handlers={"first": first, "add": self.add})
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["state"]["energy"], 12)
        events = [item for item in result["trace"] if item["kind"] == "event"]
        self.assertEqual([(e["event_id"], e["parent_id"], e["depth"]) for e in events], [(1, None, 0), (2, 1, 1)])
        self.assertEqual([e["emitted_by"] for e in events], [None, "skill"])

    def test_fifo_is_explicit_and_distinct_from_nested_immediate_execution(self):
        def emit(state, current):
            state["nested"]["retained"].append(current["name"])
            return {"state": state, "events": [event("child")], "result": current["event_id"]}
        result = self.run_events(events=[event("root1"), event("root2")],
                                 subscriptions=[subscription("one", "root1", "emit"),
                                                subscription("two", "root2", "emit"),
                                                subscription("child", "child")],
                                 handlers={"emit": emit, "add": self.add})
        self.assertEqual([e["name"] for e in result["trace"] if e["kind"] == "event"],
                         ["root1", "root2", "child", "child"])
        self.assertEqual(result["assumptions"]["mode"], "explicit_fifo_experiment")

    def test_explicit_order_is_used_not_subscription_list_or_id(self):
        def digit(state, current):
            state["energy"] = state["energy"] * 10 + 1
            return {"state": state, "events": []}
        result = self.run_events(events=[event(amount=2)],
                                 subscriptions=[subscription("a", handler="digit", order=20),
                                                subscription("z", order=10)],
                                 handlers={"digit": digit, "add": self.add})
        self.assertEqual(result["state"]["energy"], 21)
        self.assertEqual([e["subscription_id"] for e in result["trace"] if e["kind"] == "handler"], ["z", "a"])

    def test_unknown_or_tied_order_blocks_before_either_handler(self):
        for orders in ((None, 1), (None, None), (0, 0)):
            called = []
            result = self.run_events(subscriptions=[subscription("a", order=orders[0]), subscription("b", order=orders[1])],
                                     handlers={"add": lambda *args: called.append(True)})
            self.assert_blocked(result)
            self.assertEqual(called, [])
            self.assertIn("unknown trigger order", result["blockers"][0])

    def test_per_subscription_execution_limit_is_visible_not_global_failure(self):
        result = self.run_events(events=[event(), event(), event()], subscriptions=[subscription(maximum=1)])
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["state"]["energy"], 1)
        skips = [e for e in result["trace"] if e["kind"] == "execution_limit_skip"]
        self.assertEqual(len(skips), 2)
        self.assertEqual(skips[0]["limit"], 1)
        self.assertEqual(result["executions"], {"skill": 1})

    def test_self_emission_terminates_at_declared_subscription_limit(self):
        def repeat(state, current):
            state["energy"] += 1
            return {"state": state, "events": [event()]}
        result = self.run_events(subscriptions=[subscription(maximum=3)], handlers={"add": repeat})
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["handler_calls"], 3)
        self.assertEqual(result["event_count"], 4)

    def test_event_depth_and_call_budgets_roll_back_trigger_cycles(self):
        def repeat(state, current):
            state["energy"] += 1
            return {"state": state, "events": [event()]}
        for key, message in (("max_events", "event count"), ("max_depth", "event depth"),
                             ("max_handler_calls", "handler call")):
            policy = dict(self.policy, max_events=50, max_depth=50, max_handler_calls=50)
            policy[key] = 2
            result = self.run_events(subscriptions=[subscription(maximum=100)], handlers={"add": repeat}, policy=policy)
            self.assert_blocked(result)
            self.assertIn(message, result["blockers"][0])

    def test_late_handler_exception_rolls_back_all_prior_changes(self):
        def fail(state, current):
            self.assertEqual(state["energy"], 1)
            state["energy"] = 999
            raise ValueError("synthetic nested failure")
        result = self.run_events(events=[event(), event("later")],
                                 subscriptions=[subscription(), subscription("later", "later", "fail")],
                                 handlers={"add": self.add, "fail": fail})
        self.assert_blocked(result)
        self.assertIn("synthetic nested failure", result["blockers"][0])
        self.assertTrue(any(e["kind"] == "handler" for e in result["trace"]))

    def test_callback_input_output_and_trace_are_deeply_isolated(self):
        held = []
        initial = [event()]
        subs = [subscription()]
        def hold(state, current):
            current["source"]["rule_id"] = "changed"
            state["nested"]["retained"].append(2)
            outcome = {"state": state, "events": [], "result": {"value": [3]}}
            held.append(outcome)
            return outcome
        before = deepcopy((self.state, initial, subs, self.policy))
        result = self.run_events(initial, subs, {"add": hold})
        held[0]["state"]["nested"]["retained"].append(999)
        held[0]["result"]["value"].append(999)
        self.assertEqual(result["state"]["nested"]["retained"], [1, 2])
        self.assertEqual(result["results"]["skill"], [{"value": [3]}])
        self.assertEqual(result["trace"][0]["source"]["rule_id"], "skill:1")
        self.assertEqual((self.state, initial, subs, self.policy), before)
        result["state"]["nested"]["retained"].append(4)
        self.assertEqual(self.state["nested"]["retained"], [1])

    def test_shared_handler_supports_skill_trait_status_and_mark_subscriptions(self):
        categories = ("skill", "trait", "status", "mark")
        result = self.run_events(events=[event("turn.end")],
                                 subscriptions=[subscription(kind + ":1", "turn.end", order=i) for i, kind in enumerate(categories)])
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["state"]["energy"], 4)
        self.assertEqual(set(result["results"]), {x + ":1" for x in categories})

    def test_repeated_dispatch_is_deterministic_and_does_not_reuse_counts(self):
        first = self.run_events([event(), event()], [subscription(maximum=1)])
        second = self.run_events([event(), event()], [subscription(maximum=1)])
        self.assertEqual(first, second)

    def test_unknown_handler_duplicate_id_and_invalid_subscription_reject(self):
        cases = [[subscription(handler="missing")], [subscription(), subscription()],
                 [dict(subscription(), order=True)], [dict(subscription(), max_executions=0)],
                 [dict(subscription(), unexpected="not ignored")]]
        for subs in cases:
            self.assert_blocked(self.run_events(subscriptions=subs))

    def test_missing_sources_forged_event_identity_and_invalid_payload_reject(self):
        for patch in ({"source": {}}, {"source": {**source(), "component_id": ""}},
                      {"event_id": 99}, {"payload": []}, {"payload": {"value": float("nan")}}):
            self.assert_blocked(self.run_events(events=[{**event(), **patch}]))

    def test_missing_unknown_or_boolean_policy_does_not_use_defaults(self):
        for change in ({"mode": "real_game"}, {"max_events": True}, {"max_depth": 0},
                       {"max_handler_calls": 1.5}, {"verified": True}):
            self.assert_blocked(self.run_events(policy={**self.policy, **change}))
        policy = dict(self.policy)
        policy.pop("max_depth")
        self.assert_blocked(self.run_events(policy=policy))

    def test_malformed_child_or_outcome_is_transactional(self):
        cases = [{"state": self.state, "events": [{"name": "bad"}]},
                 {"state": self.state, "events": [], "result": float("inf")},
                 {"state": self.state}, {"state": [], "events": []},
                 {"state": self.state, "events": [], "unrecognized": True}]
        for outcome in cases:
            self.assert_blocked(self.run_events(handlers={"add": lambda *_: outcome}))

    def test_initial_event_budget_prevents_any_handler_call(self):
        calls = []
        result = self.run_events(events=[event(), event()], policy={**self.policy, "max_events": 1},
                                 handlers={"add": lambda *args: calls.append(True)})
        self.assert_blocked(result)
        self.assertEqual(calls, [])

    def test_empty_event_stream_preserves_state_without_fabricated_triggers(self):
        result = self.run_events(events=[])
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["state"], self.state)
        self.assertEqual(result["event_count"], 0)
        self.assertEqual(result["trace"], [])


if __name__ == "__main__":
    unittest.main()
