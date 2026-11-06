"""Opt-in ordinary-skill battle loop with explicitly experimental KO policies.

Each completed skill commits separately. Unsupported later actions retain that
progress, rather than making transaction rollback a game rule. Entry hooks,
end-of-turn effects, regeneration, revival and team magic are deliberately
excluded by a named policy. No real-game calibration or training is implied.
"""
from __future__ import annotations

from copy import deepcopy

from lab.action_runtime import _active, _relative
from lab.effect_runtime import HOOKS, _state as validate_fragment_state
from lab.prepared_rules import PreparedRules, prepare_rules
from lab.ruleset import canonical_hash
from lab.skill_execution import execute_skill, preflight_skill
from lab.turn_plan import _validate_state, plan_joint_actions
from lab.victory_rules import reconcile_knockouts, terminal, validate_victory


POLICY = "ordinary_skills_faint_skip_manual_replacement_v1"
FAINT_POLICY = "stop_remaining_skill_on_exhaustion_experiment"
SIDES = ("a", "b")
UNRESOLVED = [
    "Experimental policy: stop remaining skill effects/hits on exhaustion; no faint/revival triggers are executed.",
    "Experimental policy: a knocked-out member loses its unexecuted action; replacement is manual after both action slots.",
    "Experimental policy: entry/departure hooks, statuses, traits, marks, weather and all end-of-turn effects are excluded.",
    "Experimental policy: no HP/energy/team-magic regeneration or revival. Legacy states use surviving HP; enabled victory ledgers use source-bound trainer magic with unresolved limit/tie adjudication blocked.",
    "Damage, panels, costs and priorities are explicit uncalibrated inputs; no formula is inferred here.",
]


class _OverrideRules:
    def __init__(self, base, overrides):
        self.base, self.overrides = base, overrides

    def __getattr__(self, name):
        return getattr(self.base, name)

    def plan(self, skill_id, defender_form_id=None):
        result = self.base.plan(skill_id, defender_form_id)
        if skill_id in self.overrides:
            result["program"] = deepcopy(self.overrides[skill_id])
        return result


class _PlanningOverrides(PreparedRules):
    """Only a trusted in-process adapter may supply alternate programs."""
    def __init__(self, prepared, overrides):
        self.base = prepared
        self._rules = _OverrideRules(prepared._rules, overrides)

    def _components(self):
        _, phases, switches = self.base._components()
        return self._rules, phases, switches


def _context(context):
    if not isinstance(context, dict) or context.get("mode") != "research_battle_experiment":
        raise ValueError("Explicit research_battle_experiment context required")
    if context.get("policy") != POLICY:
        raise ValueError("Explicit named research battle policy required: " + POLICY)
    excluded = context.get("excluded_hooks")
    if (not isinstance(excluded, list) or len(excluded) != len(HOOKS)
            or any(not isinstance(x, str) for x in excluded) or set(excluded) != HOOKS):
        raise ValueError("Research policy requires explicitly excluded trait/field/mark/bloodline/event hooks")
    canonical_hash(context)


def _validate(prepared, state, *, status_lifecycle_policy=None):
    rules, phases, _ = prepared._components()
    _validate_state(rules, phases, state)
    validate_victory(state)
    # Reserve members must be usable before a KO is allowed to commit.
    for side in SIDES:
        for member in state["teams"][side]["members"]:
            expected = rules.form(member["form_id"])["types"]
            if "types" in member and member["types"] != expected:
                raise ValueError("Member types conflict with source form; transformation is unresolved")
            member["types"] = deepcopy(expected)
            validate_fragment_state({"self": member, "opponent": member})
            if status_lifecycle_policy != "source_bound_freeze_leech_lifecycle_v1" and any(member["statuses"].get(status, 0) > 0 for status in ("freeze", "leech")):
                raise ValueError("Existing freeze/leech needs unresolved threshold/source-binding rules")


def _pending(state):
    return {side: [i for i, member in enumerate(state["teams"][side]["members"])
                   if member["hp"] > 0]
            for side in SIDES if _active(state, side)["hp"] == 0}


def _outcome(state):
    if "victory" in state:
        return terminal(state)["winner"]
    alive = {side: any(member["hp"] > 0 for member in state["teams"][side]["members"])
             for side in SIDES}
    if not any(alive.values()):
        return "draw"
    if not alive["a"]:
        return "b"
    if not alive["b"]:
        return "a"
    return None


def _result(state, *, policy=POLICY, unresolved=UNRESOLVED):
    return {"status": "blocked", "scope": "research_battle_experiment", "policy": policy,
            "state": deepcopy(state), "events": [], "blockers": [], "unresolved": deepcopy(unresolved),
            "committed_actions": [], "skipped_actions": [], "pending_replacements": {}, "winner": None,
            "turn_advanced": False, "research_turn_executed": False,
            "full_turn_executed": False, "battle_executable": False,
            "training_eligible": False, "calibrated": False, "real_game_verified": False}


def _finish(result, current, *, advance=True, policy=POLICY):
    result["events"].extend(reconcile_knockouts(current))
    decision = terminal(current, completed_turn=advance)
    if "victory" in current:
        result["victory"] = deepcopy(current["victory"])
        result["terminal_reason"] = decision["reason"]
    if decision["blockers"]:
        current["research_battle"] = {"policy": policy, "phase": "blocked", "pending_replacements": {},
                                     "turn_pending": False, "winner": None,
                                     "terminal_reason": decision["reason"]}
        result.update(status="blocked", state=deepcopy(current), pending_replacements={}, winner=None,
                      blockers=deepcopy(decision["blockers"]), research_turn_executed=bool(result["committed_actions"]))
        return
    winner = _outcome(current)
    pending = {} if winner is not None else _pending(current)
    if winner is not None:
        phase, status = "finished", "finished"
    elif pending:
        phase, status = "awaiting_replacement", "awaiting_replacement"
    else:
        phase, status = "ready", "applied"
        if advance:
            previous = current["turn"]
            current["turn"] += 1
            result["events"].append({"op": "research.turn_advanced", "before": previous,
                                     "after": current["turn"], "policy": policy})
            result["turn_advanced"] = True
    current["research_battle"] = {"policy": policy, "phase": phase,
                                 "pending_replacements": deepcopy(pending),
                                 "turn_pending": bool(pending), "winner": winner}
    result.update(status=status, state=deepcopy(current), pending_replacements=pending,
                  winner=winner, research_turn_executed=not pending and (bool(result["committed_actions"]) or advance))


def _validate_override(prepared, skill_id, program):
    if (type(skill_id) is not int or not isinstance(program, dict)
            or program.get("game_id") != skill_id or program.get("category") != "skill"
            or program.get("status") != "compiled" or not program.get("source_hash")):
        raise ValueError("Trusted program override identity is invalid")
    prepared._rules.skill(skill_id)
    if "game_file_evidence" in program:
        from lab.game_rule_candidates import digest
        evidence = program["game_file_evidence"]
        source = evidence.get("source_id") if isinstance(evidence, dict) else None
        if (not isinstance(source, str) or not source or program.get("snapshot_id") != "game-file:" + source
                or program.get("research_skill_override_allowed") is not True
                or program.get("whole_skill_verified") is not False
                or program.get("source_hash") != digest(evidence)
                or program.get("game_file_program_sha256") != digest(
                    {k: v for k, v in program.items() if k != "game_file_program_sha256"})):
            raise ValueError("Trusted game-file override source, eligibility or program hash is invalid")
    elif program.get("snapshot_id") != prepared.snapshot_id:
        raise ValueError("Trusted program override snapshot is invalid")


def execute_research_turn(catalog, state, actions, context, *, damage_resolver=None,
                          program_overrides=None):
    """Run two ordinary skill slots; preserve every successfully completed skill.

    Inputs match the joint planner and isolated fragment protocols. The outer
    context additionally requires mode=research_battle_experiment and POLICY.
    ``program_overrides`` maps integer skill IDs to trusted adapter programs;
    servers must never accept arbitrary programs from request bodies.
    """
    result = _result(state)
    current = deepcopy(state)
    try:
        _context(context)
        prepared = prepare_rules(catalog)
        _validate(prepared, current)
        lifecycle = current.get("research_battle", {})
        if lifecycle and (not isinstance(lifecycle, dict) or lifecycle.get("policy") != POLICY
                          or lifecycle.get("phase") != "ready"):
            raise ValueError("Pending replacement, finished or partially blocked turn must be resolved before another turn")
        if "victory" in current and terminal(current)["terminal"]:
            _finish(result, current, advance=False)
            return result
        if any(_active(current, side)["hp"] == 0 for side in SIDES):
            # Imported/manual states may begin with exhausted active members.
            _finish(result, current, advance=False)
            if result["status"] == "applied":
                raise ValueError("Exhausted active member has no replacement")
            # No action slots have run, so replacement must not advance turn.
            if result["status"] == "awaiting_replacement":
                current["research_battle"]["turn_pending"] = False
                result["state"] = deepcopy(current)
            return result
        fragments = context.get("fragments")
        if not isinstance(fragments, dict) or set(fragments) != set(SIDES):
            raise ValueError("Supply exactly both fragment contexts")
        overrides = {} if program_overrides is None else deepcopy(program_overrides)
        if not isinstance(overrides, dict):
            raise ValueError("Trusted program overrides must be an integer skill-ID mapping")
        for skill_id, program in overrides.items():
            _validate_override(prepared, skill_id, program)
        planner = _PlanningOverrides(prepared, overrides) if overrides else prepared
        plan = plan_joint_actions(planner, current, actions)
        if plan["status"] != "planned":
            raise ValueError("Joint plan rejected: " + "; ".join(plan["blockers"]))
        if plan["ordering"]["status"] != "determined":
            raise ValueError("Action order unresolved: " + plan["ordering"]["reason"])
        orders = plan["ordering"]["possible_orders"]
        if len(orders) != 1 or sorted(orders[0]) != list(SIDES):
            raise ValueError("A unique action order is required")
        contexts = {}
        for side in SIDES:
            action = plan["plans"][side]
            program = action.get("program", {})
            actor = _active(current, side)
            if action["kind"] != "skill" or action.get("execution_phase") or actor["charge"] is not None:
                raise ValueError("Research v1 supports ordinary skill actions only; switch/charge unresolved")
            if program.get("status") != "compiled" or any(op["op"] == "defense.plan" for op in program["operations"]):
                raise ValueError("Unsupported/defense skills cannot execute as ordinary actions")
            if not isinstance(fragments[side], dict):
                raise ValueError("Each fragment context must be an object")
            fragment = deepcopy(fragments[side])
            if "resolved_energy_cost" in fragment and (type(fragment["resolved_energy_cost"]) is not int
                    or fragment["resolved_energy_cost"] != action["effective_cost"]):
                raise ValueError("Fragment cost conflicts with the submitted action cost")
            fragment.update(resolved_energy_cost=action["effective_cost"], faint_policy=FAINT_POLICY,
                            actor_side=side, actor_member_id=actor["member_id"],
                            opponent_member_id=_active(current, "b" if side == "a" else "a")["member_id"])
            if action["skill_id"] in overrides:
                fragment.update(snapshot_id=program["snapshot_id"], source_hash=program["source_hash"])
                if "game_file_evidence" in program:
                    policy = program["game_file_evidence"].get("policy")
                    if canonical_hash(fragment.get("game_file_policy")) != canonical_hash(policy):
                        raise ValueError("Fragment must bind the trusted game-file experiment policy")
            # Validate both input fragments before invoking any damage callback.
            preflight_skill(program, _relative(current, side), fragment, damage_resolver)
            contexts[side] = fragment
        result["action_order"] = deepcopy(orders[0])
        result["unresolved"].extend(deepcopy(plan["unresolved"]))
        for index, side in enumerate(orders[0]):
            if any(_active(current, candidate)["hp"] == 0 for candidate in SIDES):
                result["skipped_actions"].append(side)
                result["events"].append({"op": "research.action_skipped", "actor_side": side,
                                         "reason": "exhausted_active_or_target", "policy": POLICY})
                continue
            action = plan["plans"][side]
            fragment = execute_skill(action["program"], _relative(current, side), contexts[side],
                                     damage_resolver=damage_resolver)
            if fragment["status"] != "applied":
                raise ValueError(f"Action {side} blocked after committed progress: " + "; ".join(fragment["blockers"]))
            other = "b" if side == "a" else "a"
            for relative, absolute in (("self", side), ("opponent", other)):
                team = current["teams"][absolute]
                team["members"][team["active_slot"]] = deepcopy(fragment["state"][relative])
            result["committed_actions"].append(side)
            result["events"].extend(reconcile_knockouts(current))
            for event in fragment["events"]:
                event = deepcopy(event)
                target = side if event.get("target", "self") == "self" else other
                event.update(action_index=index, actor_side=side, actor_member_id=action["actor_member_id"],
                             target_side=target, target_member_id=_active(current, target)["member_id"],
                             skill_slot=action["slot"], skill_id=action["skill_id"],
                             source_hash=action["program"]["source_hash"], research_policy=POLICY)
                result["events"].append(event)
        _finish(result, current)
    except Exception as exc:
        result["blockers"] = [str(exc)]
        if result["committed_actions"]:
            result["events"].extend(reconcile_knockouts(current))
            current["research_battle"] = {"policy": POLICY, "phase": "blocked",
                                         "pending_replacements": _pending(current), "turn_pending": True,
                                         "winner": None, "committed_actions": deepcopy(result["committed_actions"])}
            result.update(state=deepcopy(current), pending_replacements=_pending(current))
    return result


def choose_research_replacements(catalog, state, selections, context):
    """Choose all pending sides atomically; preserve marks and member state.

    ``selections`` is exactly {side: reserve_slot} for the returned pending sides.
    Incoming members retain their explicit state and entered_turn is set now;
    no Swift/entry hooks, departure cleanup or automatic revival is inferred.
    """
    result = _result(state)
    current = deepcopy(state)
    try:
        _context(context)
        prepared = prepare_rules(catalog)
        _validate(prepared, current)
        lifecycle = current.get("research_battle")
        pending = _pending(current)
        if (not isinstance(lifecycle, dict) or lifecycle.get("policy") != POLICY
                or lifecycle.get("phase") != "awaiting_replacement"
                or type(lifecycle.get("turn_pending")) is not bool
                or lifecycle.get("pending_replacements") != pending or not pending
                or any(not candidates for candidates in pending.values()) or _outcome(current) is not None):
            raise ValueError("State has no matching pending manual replacement phase")
        if not isinstance(selections, dict) or set(selections) != set(pending):
            raise ValueError("Choose exactly all pending replacement sides")
        for side, slot in selections.items():
            if type(slot) is not int or slot not in pending[side]:
                raise ValueError(f"Replacement {side} must be a surviving reserve slot")
        for side, slot in selections.items():
            team = current["teams"][side]
            previous = team["active_slot"]
            team["active_slot"] = slot
            team["members"][slot]["entered_turn"] = current["turn"]
            result["events"].append({"op": "research.manual_replacement", "side": side,
                                     "before_slot": previous, "after_slot": slot,
                                     "member_id": team["members"][slot]["member_id"], "policy": POLICY})
        _finish(result, current, advance=lifecycle["turn_pending"])
    except Exception as exc:
        result["blockers"] = [str(exc)]
    return result
