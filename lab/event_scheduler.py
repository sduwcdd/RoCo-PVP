"""Deterministic, bounded event dispatch for explicitly isolated experiments.

FIFO scheduling and subscriber order are supplied policies, not inferred game
timing. Skills, traits, statuses and marks can share handlers without declaring
that their real-game trigger chains are implemented. A failed transaction
returns its original state; diagnostic traces are not committed battle events.
External side effects in callbacks cannot be rolled back and must be avoided.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import math

from lab.constants import EXPLICIT_FIFO_EXPERIMENT, MIN_SUBSCRIPTION_ORDER

SOURCE_KEYS = frozenset({"rule_id", "component_id", "snapshot_id"})


def _json(value, label):
    """Reject non-JSON and non-finite values instead of silently coercing."""
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _json(item, label)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _json(item, label)
        return
    raise ValueError(f"{label} must contain finite JSON values only")


def _positive(value, label):
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")


def _text(value, label):
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")


def _source(source):
    if type(source) is not dict or not SOURCE_KEYS <= source.keys():
        raise ValueError("source must retain rule_id, component_id and snapshot_id")
    _json(source, "source")
    for key in SOURCE_KEYS:
        _text(source[key], f"source.{key}")


def _event(event):
    if type(event) is not dict or set(event) != {"name", "payload", "source"}:
        raise ValueError("event must contain exactly name, payload and source; IDs are scheduler-owned")
    _text(event["name"], "event.name")
    if type(event["payload"]) is not dict:
        raise ValueError("event.payload must be an object")
    _json(event["payload"], "event.payload")
    _source(event["source"])


def dispatch_events(state, initial_events, subscriptions, handlers, *, policy):
    """Dispatch copied events through copied state with an explicit FIFO policy.

    Subscriptions contain id, event, handler, order (int or None),
    max_executions (per transaction) and source. Each handler receives independent
    copies of (state, event) and returns {state, events, result?}. Child events
    use the same input schema; event_id, parent_id and depth are assigned here.
    Subscriber results are stored as lists under their subscription ID.

    If multiple eligible subscribers match, their supplied order integers must
    be unique. No ID/alphabetical/default order resolves an unknown tie. Reaching
    a subscriber's declared execution limit skips it with a diagnostic entry;
    exceeding global event/call/depth limits rejects the entire transaction.
    The trace is always diagnostic, never a committed game-event log.
    """
    original = deepcopy(state)
    result = {"status": "blocked", "state": original, "trace": [], "blockers": [],
              "results": {}, "training_eligible": False, "full_turn_executed": False,
              "calibrated": False, "trace_is_diagnostic": True}
    trace = result["trace"]
    try:
        if type(state) is not dict:
            raise ValueError("state must be an object")
        _json(state, "state")
        required_policy = {"mode", "max_events", "max_depth", "max_handler_calls"}
        if type(policy) is not dict or set(policy) != required_policy or policy["mode"] != EXPLICIT_FIFO_EXPERIMENT:
            raise ValueError("explicit_fifo_experiment and exactly its three budgets are required")
        policy = deepcopy(policy)
        for key in required_policy - {"mode"}:
            _positive(policy[key], f"policy.{key}")
        if type(initial_events) is not list or type(subscriptions) is not list or type(handlers) is not dict:
            raise ValueError("events/subscriptions must be lists and handlers must be a registry")
        for key, handler in handlers.items():
            _text(key, "handler name")
            if not callable(handler):
                raise ValueError(f"handler {key} is not callable")
        # Copy containers before callbacks can mutate their original references.
        handlers = dict(handlers)
        subscriptions = deepcopy(subscriptions)
        initial_events = deepcopy(initial_events)
        known = set()
        required_subscription = {"id", "event", "handler", "order", "max_executions", "source"}
        for sub in subscriptions:
            if type(sub) is not dict or set(sub) != required_subscription:
                raise ValueError("subscription fields must exactly match the dispatch schema")
            for key in ("id", "event", "handler"):
                _text(sub[key], f"subscription.{key}")
            if sub["id"] in known:
                raise ValueError(f"duplicate subscription id: {sub['id']}")
            known.add(sub["id"])
            if sub["handler"] not in handlers:
                raise ValueError(f"unknown handler: {sub['handler']}")
            if sub["order"] is not MIN_SUBSCRIPTION_ORDER and type(sub["order"]) is not int:
                raise ValueError("subscription.order must be an integer or explicit None")
            _positive(sub["max_executions"], "subscription.max_executions")
            _source(sub["source"])
        current = deepcopy(state)
        queue = deque()
        generated, calls = 0, 0
        counts = {sub["id"]: 0 for sub in subscriptions}
        values = {sub["id"]: [] for sub in subscriptions}

        def enqueue(event, parent_id=None, depth=0, emitted_by=None):
            nonlocal generated
            _event(event)
            if depth > policy["max_depth"]:
                raise ValueError("event depth budget exceeded; possible trigger cycle")
            if generated >= policy["max_events"]:
                raise ValueError("event count budget exceeded; possible trigger cycle")
            generated += 1
            item = deepcopy(event)
            item.update(event_id=generated, parent_id=parent_id, depth=depth,
                        emitted_by=emitted_by)
            queue.append(item)

        for event in initial_events:
            enqueue(event)
        while queue:
            event = queue.popleft()
            trace.append({"kind": "event", **deepcopy(event)})
            eligible = []
            for sub in subscriptions:
                if sub["event"] != event["name"]:
                    continue
                if counts[sub["id"]] >= sub["max_executions"]:
                    trace.append({"kind": "execution_limit_skip", "event_id": event["event_id"],
                                  "subscription_id": sub["id"], "source": deepcopy(sub["source"]),
                                  "executions": counts[sub["id"]], "limit": sub["max_executions"]})
                else:
                    eligible.append(sub)
            if len(eligible) > 1:
                orders = [sub["order"] for sub in eligible]
                if None in orders or len(set(orders)) != len(orders):
                    raise ValueError(f"unknown trigger order for event {event['name']}; supply unique explicit subscriber order")
                eligible.sort(key=lambda sub: sub["order"])
            for sub in eligible:
                if calls >= policy["max_handler_calls"]:
                    raise ValueError("handler call budget exceeded; possible trigger cycle")
                calls += 1
                counts[sub["id"]] += 1
                trace.append({"kind": "handler", "event_id": event["event_id"],
                              "subscription_id": sub["id"], "handler": sub["handler"],
                              "execution": counts[sub["id"]], "order": sub["order"],
                              "source": deepcopy(sub["source"])})
                outcome = handlers[sub["handler"]](deepcopy(current), deepcopy(event))
                if (type(outcome) is not dict or not {"state", "events"} <= outcome.keys()
                        or set(outcome) - {"state", "events", "result"}):
                    raise ValueError(f"handler {sub['handler']} returned an invalid outcome")
                if type(outcome["state"]) is not dict or type(outcome["events"]) is not list:
                    raise ValueError("handler outcome needs an object state and an event list")
                _json(outcome, "handler outcome")
                # Publish only detached copies, including callback-owned results.
                current = deepcopy(outcome["state"])
                if "result" in outcome:
                    values[sub["id"]].append(deepcopy(outcome["result"]))
                for emitted in outcome["events"]:
                    enqueue(emitted, event["event_id"], event["depth"] + 1, sub["id"])
        result.update(status="applied", state=current, results=values,
                      assumptions=deepcopy(policy), event_count=generated,
                      handler_calls=calls, executions=counts)
    except Exception as exc:
        result["blockers"] = [str(exc)]
        trace.append({"kind": "blocked", "reason": str(exc), "committed": False})
    return result
