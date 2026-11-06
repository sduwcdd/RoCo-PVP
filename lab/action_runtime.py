"""Execute a pair of isolated skill fragments, never a complete game turn.

This connects source-bound phase plans to the fragment runtime. Final costs,
priorities and damage are explicit experiment inputs. Trait/field/event hooks,
end-of-turn ticks, replacement, victory, and regeneration remain unavailable.
Any failure (including exhaustion) rolls back BOTH actions and their events.
"""
from __future__ import annotations

from copy import deepcopy

from lab.effect_runtime import HOOKS
from lab.skill_execution import execute_skill, preflight_skill
from lab.ruleset import canonical_hash
from lab.prepared_rules import PreparedRules, prepare_rules
from lab.turn_plan import plan_joint_actions


SIDES = ("a", "b")


def _active(state, side):
    team = state["teams"][side]
    return team["members"][team["active_slot"]]


def _relative(state, side):
    """Return isolated actor copies without deep copying the entire state."""
    other = "b" if side == "a" else "a"
    self_actor = _active(state, side)
    opponent_actor = _active(state, other)
    # Deep copy only the active members, not the full state
    return {"self": deepcopy(self_actor), "opponent": deepcopy(opponent_actor)}


def execute_joint_actions(catalog, state, actions, context, *, damage_resolver=None):
    """Apply both supported actions atomically against one shared front state.

    ``state`` and ``actions`` use the joint planner's contract. Active members
    additionally require max_hp, max_energy, statuses and stat_modifiers, as in
    effect_runtime. Types come from the exact form's BWIKI record; an existing
    conflicting types field is rejected instead of silently replaced.

    ``context`` requires mode=isolated_joint_action_experiment, excluded_hooks
    listing every HOOKS value, and fragments={a: ..., b: ...}. Each fragment has
    execute_effects' explicit source/snapshot/operation policies. The final cost
    is taken from its submitted action; a duplicate fragment cost must agree.
    Resolver context gets actor_side, actor_member_id and opponent_member_id.
    Resolver arguments and every returned structure are isolated copies.

    An applied result is two skill fragments only: the turn number is unchanged,
    no replacement or winner is inferred, and training eligibility stays false.
    """
    result = {"status": "blocked", "scope": "isolated_joint_action_experiment",
              "state": deepcopy(state), "events": [], "blockers": [],
              "snapshot_id": catalog.snapshot_id if isinstance(catalog, PreparedRules) else catalog.get("snapshot_id") if isinstance(catalog, dict) else None,
              "state_hash": None, "actions_hash": None, "context_hash": None,
              "catalog_hash": None, "plan_hash": None, "order": None,
              "input_state_mutated": False, "full_turn_executed": False,
              "battle_executable": False, "calibrated": False,
              "training_eligible": False, "implementation_unvalidated": True}
    try:
        result.update(state_hash=canonical_hash(state), actions_hash=canonical_hash(actions),
                      context_hash=canonical_hash(context))
        prepared = prepare_rules(catalog)
        rules = prepared._rules
        result["catalog_hash"] = rules.catalog_content_hash
        if not isinstance(context, dict) or context.get("mode") != "isolated_joint_action_experiment":
            raise ValueError("An isolated joint-action experiment must be explicitly requested")
        excluded = context.get("excluded_hooks")
        if (not isinstance(excluded, list) or len(excluded) != len(HOOKS)
                or any(not isinstance(x, str) for x in excluded) or set(excluded) != HOOKS):
            raise ValueError("Every trait, field, mark, bloodline and event hook must be explicitly excluded")
        fragments = context.get("fragments")
        if not isinstance(fragments, dict) or set(fragments) != set(SIDES):
            raise ValueError("Supply exactly both fragment contexts")
        plan = plan_joint_actions(prepared, state, actions)
        result["plan_hash"] = canonical_hash(plan)
        if plan["status"] != "planned":
            raise ValueError("Joint plan rejected: " + "; ".join(plan["blockers"]))
        if plan["ordering"]["status"] != "determined":
            raise ValueError("Action order unresolved: " + plan["ordering"]["reason"])
        order = plan["ordering"]["possible_orders"]
        if len(order) != 1 or sorted(order[0]) != list(SIDES):
            raise ValueError("A unique source-bound action order is required")

        current = deepcopy(state)
        contexts = {}
        for side in SIDES:
            action_plan = plan["plans"][side]
            actor = _active(current, side)
            if action_plan["kind"] != "skill" or action_plan.get("execution_phase") or actor["charge"] is not None:
                raise ValueError("Switch and charge execution phases are not implemented")
            program = action_plan["program"]
            if program["status"] != "compiled" or any(op["op"] == "defense.plan" for op in program["operations"]):
                raise ValueError("Unsupported skill or defense execution cannot be treated as an ordinary fragment")
            types = rules.form(actor["form_id"])["types"]
            if "types" in actor and actor["types"] != types:
                raise ValueError("Active actor types conflict with the exact BWIKI form; transformation rules are unresolved")
            actor["types"] = deepcopy(types)
            fragment = fragments[side]
            if not isinstance(fragment, dict):
                raise ValueError("Each fragment context must be an object")
            fragment = deepcopy(fragment)
            if "resolved_energy_cost" in fragment and (type(fragment["resolved_energy_cost"]) is not int
                    or fragment["resolved_energy_cost"] != action_plan["effective_cost"]):
                raise ValueError("Fragment cost conflicts with the submitted current-phase effective cost")
            fragment["resolved_energy_cost"] = action_plan["effective_cost"]
            fragment.update(actor_side=side, actor_member_id=actor["member_id"],
                            opponent_member_id=_active(current, "b" if side == "a" else "a")["member_id"])
            contexts[side] = fragment

        # Reject a malformed second fragment before invoking either callback.
        for side in SIDES:
            preflight_skill(plan["plans"][side]["program"], _relative(current, side), contexts[side], damage_resolver)
        # Freeze is an immediate exhaustion condition, not just a future
        # end-of-turn tick. A positive HP value therefore cannot establish
        # eligibility to act, either before or after another skill's damage.
        # Until its threshold/rounding resolver is bound, do not execute any
        # action against an active frozen actor (even one currently above a
        # caller-estimated threshold). Leech remains opaque here: its source-
        # bound transfer is not executed because no end-of-turn phase runs.
        if any(_active(current, side)["statuses"].get("freeze", 0) > 0 for side in SIDES):
            raise ValueError("Existing freeze requires an immediate exhaustion-threshold resolver; both actions rejected")
        unresolved = deepcopy(plan["unresolved"])
        for side in SIDES:
            if _active(current, side)["statuses"].get("leech", 0) > 0:
                unresolved.append({"side": side,
                                   "reason": "Existing leech count is retained only; its source binding, transfer direction and end-of-turn transfer remain unresolved."})

        events = []
        for action_index, side in enumerate(order[0]):
            other = "b" if side == "a" else "a"
            action_plan = plan["plans"][side]
            fragment = execute_skill(action_plan["program"], _relative(current, side),
                                       contexts[side], damage_resolver=damage_resolver)
            if fragment["status"] != "applied":
                raise ValueError(f"Action {side} rejected: " + "; ".join(fragment["blockers"]))
            if any(fragment["state"][relative]["hp"] == 0 for relative in ("self", "opponent")):
                raise ValueError("Exhaustion requires unresolved faint/replacement/trigger rules; both actions rolled back")
            for relative, absolute in (("self", side), ("opponent", other)):
                team = current["teams"][absolute]
                team["members"][team["active_slot"]] = deepcopy(fragment["state"][relative])
            for event in fragment["events"]:
                event = deepcopy(event)
                target_side = side if event.get("target", "self") == "self" else other
                event.update(action_index=action_index, actor_side=side,
                             actor_member_id=action_plan["actor_member_id"],
                             target_side=target_side, target_member_id=_active(current, target_side)["member_id"],
                             skill_slot=action_plan["slot"], skill_id=action_plan["skill_id"],
                             source_hash=action_plan["program"]["source_hash"])
                events.append(event)
        result.update(status="applied", state=current, events=events, order=deepcopy(order[0]),
                      final_state_hash=canonical_hash(current), assumptions=deepcopy(context),
                      unresolved=unresolved, end_of_turn_executed=False)
    except Exception as exc:
        # External resolvers are extension boundaries. They cannot leave a
        # partially applied first action or energy payment visible on failure.
        result["blockers"] = [str(exc)]
    return result


def execute_action_status_sequence(catalog, state, actions, context, *, damage_resolver=None,
                                   status_damage_resolver=None):
    """Atomically compose two explicit experimental phases, not a full turn.

    The status schedule describes the state AFTER both skills (including newly
    applied statuses). A failure in that phase discards both skills and costs.
    Resolvers must be pure: their external side effects cannot be rolled back.
    No regeneration, turn increment, victory, or implicit phase order is added.
    """
    from lab.status_runtime import execute_status_phase

    result = {"status": "blocked", "scope": "isolated_action_status_sequence",
              "state": deepcopy(state), "events": [], "blockers": [], "unresolved": [],
              "initial_state_hash": None, "final_state_hash": None,
              "full_turn_executed": False, "end_of_turn_executed": False,
              "status_fragment_executed": False, "battle_executable": False,
              "training_eligible": False, "calibrated": False, "real_game_verified": False}
    try:
        result["initial_state_hash"] = canonical_hash(state)
        canonical_hash(context)
        if (not isinstance(context, dict)
                or set(context) != {"mode", "phase_order", "actions_context", "status_context"}
                or context["mode"] != "isolated_action_status_sequence"
                or context["phase_order"] != "actions_then_status_experiment"):
            raise ValueError("Explicit actions_then_status_experiment and both phase contexts required")
        prepared = prepare_rules(catalog)
        result.update(snapshot_id=prepared.snapshot_id,
                      catalog_content_hash=prepared.catalog_content_hash)
        # Copy all submitted data before either extension point is invoked.
        state, actions, context = deepcopy(state), deepcopy(actions), deepcopy(context)
        pair = execute_joint_actions(prepared, state, actions, context["actions_context"],
                                     damage_resolver=damage_resolver)
        if pair["status"] != "applied":
            raise ValueError("Action phase rejected: " + "; ".join(pair["blockers"]))
        ticks = execute_status_phase(prepared, pair["state"], context["status_context"],
                                     damage_resolver=status_damage_resolver)
        if ticks["status"] != "applied":
            raise ValueError("Status phase rejected; both phases rolled back: " + "; ".join(ticks["blockers"]))
        events = [{**deepcopy(event), "sequence_phase": label}
                  for label, phase in (("actions", pair), ("statuses", ticks))
                  for event in phase["events"]]
        result.update(status="applied", state=deepcopy(ticks["state"]), events=events,
                      final_state_hash=canonical_hash(ticks["state"]),
                      assumptions=context, action_order=deepcopy(pair["order"]),
                      unresolved=deepcopy(pair["unresolved"]) + deepcopy(ticks.get("unresolved", [])),
                      status_fragment_executed=True)
    except Exception as exc:
        result["blockers"] = [str(exc)]
    return result
