"""Plan both submitted actions against one immutable pre-turn state.

This component resolves only source-backed phase constraints. It does not run
damage, triggers, cleanup, resource regeneration, or the winner calculation.
Effective costs and priorities are explicitly supplied experiment inputs, never
silently derived from legacy rules. Plans are not policy observations.
"""
from __future__ import annotations

from copy import deepcopy

from lab.ruleset import canonical_hash
from lab.prepared_rules import PreparedRules, prepare_rules

SIDES = ("a", "b")


def charge_admission(catalog, member, skill_id, *, slot, turn):
    """Pure phase selection shared by submitted, generated and Swift skills.

    Bypass requires the actual sourced token. It neither fabricates a ready
    charge nor consumes anything; the caller pays execution cost and consumes
    the old token only after a successful skill commit.
    """
    prepared = prepare_rules(catalog)
    phases = prepared._components()[1]
    prepared._rules.skill(skill_id)
    _integer(turn, "turn", 1)
    if member.get("charge") is not None:
        from lab.trait_runtime import permits_member_skill_while_charging
        if permits_member_skill_while_charging(prepared, member, slot):
            if phases.requires_charge(skill_id):
                from lab.charge_program_adapter import jealousy_release_metadata
                proof=jealousy_release_metadata(prepared,member,skill_id,slot=slot,turn=turn)
                return {"execution_phase":"jealousy_release_pending_execution","jealousy_release":proof,
                        "charge_consumed_after_success":True}
            return {"execution_phase":"jealousy_carried_pending_execution","charge_consumed_after_success":True}
        transition = phases.charge_transition(member["charge"], current_turn=turn, slot=slot, skill_id=skill_id)
        if transition["status"] != "ready":
            raise ValueError("Charge phase does not permit releasing the selected slot")
        return {"execution_phase": "charge_release_pending_execution", "charge_transition": transition}
    if not phases.requires_charge(skill_id):
        return {}
    from lab import duration_runtime as duration
    tokens = duration.active_effects(member, turn, "charge_skip") if member.get("timed_effects") else []
    if tokens:
        return {"execution_phase": "bypass_charge_pending_execution",
                "charge_bypass": {"tokens": tokens, "policy": duration.POLICIES["charge_skip"],
                                  "consume": "only_after_successful_skill_commit"},
                "energy_cost_scope": "execution_cost_without_charge_setup"}
    _integer(slot, "charge setup slot")
    return {"execution_phase": "charge_setup_not_attack_release",
            "charge_start": phases.charge_state(slot, skill_id, turn)}


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _bool(value, name):
    if type(value) is not bool:
        raise ValueError(f"{name} must be an explicit boolean")
    return value


def _validate_state(rules, phases, state):
    if not isinstance(state, dict) or state.get("snapshot_id") != rules.snapshot_id:
        raise ValueError("State snapshot must match the current rules")
    _integer(state.get("turn"), "turn", 1)
    if not isinstance(state.get("teams"), dict) or set(state["teams"]) != set(SIDES):
        raise ValueError("State must contain exactly both teams")
    ids = set()
    for side in SIDES:
        team = state["teams"][side]
        if not isinstance(team, dict) or not isinstance(team.get("members"), list) or not 1 <= len(team["members"]) <= 6:
            raise ValueError("Each team must contain 1–6 explicit members")
        index = _integer(team.get("active_slot"), "active_slot")
        if index >= len(team["members"]):
            raise ValueError("Active slot is outside the team")
        for member in team["members"]:
            if not isinstance(member, dict) or not isinstance(member.get("member_id"), str) or not member["member_id"]:
                raise ValueError("Every member needs a stable member ID")
            if member["member_id"] in ids:
                raise ValueError("Member IDs must be unique across both teams")
            ids.add(member["member_id"])
            rules.form(member.get("form_id"))
            _integer(member.get("hp"), "hp")
            _integer(member.get("energy"), "energy")
            if member.get("speed") is not None:
                _integer(member["speed"], "speed")
            entered = _integer(member.get("entered_turn"), "entered_turn")
            if entered > state["turn"]:
                raise ValueError("Entry cannot be in the future")
            _bool(member.get("rooted"), "rooted")
            if "charge" not in member:
                raise ValueError("Charge state must be explicit (null or a bound record)")
            if member["charge"] is not None and not isinstance(member["charge"], dict):
                raise ValueError("Charge state must be a bound record, not a boolean")
            if not isinstance(member.get("skill_slots"), list) or len(member["skill_slots"]) != 4:
                raise ValueError("Four ordered skill slots including empties are required")
            filled = []
            for skill_id in member["skill_slots"]:
                _integer(skill_id, "skill game ID")
                if skill_id:
                    rules.skill(skill_id)
                    filled.append(skill_id)
            if len(set(filled)) != len(filled):
                from lab.dynamic_skills import duplicate_slots_allowed
                if not duplicate_slots_allowed(member):
                    raise ValueError("Duplicate carried skills require source-tracked dynamic slots before planning")
            if member["charge"] is not None:
                charge_slot = _integer(member["charge"].get("slot"), "charge slot")
                if charge_slot >= 4:
                    raise ValueError("Charge slot is outside four slots")
                inspection = phases.charge_transition(member["charge"], current_turn=state["turn"],
                                                      slot=charge_slot, skill_id=member["skill_slots"][charge_slot])
                if inspection["status"] == "blocked":
                    raise ValueError("Invalid or stale charge record: " + inspection["reason"])


def plan_joint_actions(catalog, state, actions):
    """Return both plans or no plans on invalid input; never mutate the state.

    State: snapshot_id, turn, teams[a|b]{active_slot, members, marks}. Members
    include stable member_id, form_id, hp, energy, speed (possibly null),
    entered_turn, rooted, charge, and four ordered skill_slots. A skill action
    supplies slot and effective_cost/effective_priority. effective_cost is an
    explicitly resolved cost for THIS action phase, not the future release cost
    of a charging skill. No cost is paid by this planner. A switch supplies
    target_slot; optional target swift_candidates must retain the same four slots.
    Source uncertainty is reported separately from malformed input.
    """
    result = {"status": "blocked", "scope": "joint_action_phase_plan", "plans": {},
              "blockers": [], "unresolved": [], "state_hash": None, "actions_hash": None,
              "snapshot_id": catalog.snapshot_id if isinstance(catalog, PreparedRules) else catalog.get("snapshot_id") if isinstance(catalog, dict) else None, "ordering": None,
              "state_mutated": False, "full_turn_executed": False,
              "battle_executable": False, "training_eligible": False, "calibrated": False}
    try:
        result["state_hash"] = canonical_hash(state)
        result["actions_hash"] = canonical_hash(actions)
        state, actions = deepcopy(state), deepcopy(actions)
        rules, phases, switches = prepare_rules(catalog)._components()
        _validate_state(rules, phases, state)
        if not isinstance(actions, dict) or set(actions) != set(SIDES):
            raise ValueError("Submit exactly both simultaneous actions; no first-action-only plan is exposed")
        plans, order_inputs, unresolved = {}, {}, []
        order_semantics_complete = True
        for side in SIDES:
            team, action = state["teams"][side], actions[side]
            actor = team["members"][team["active_slot"]]
            if not isinstance(action, dict) or action.get("kind") not in ("skill", "switch"):
                raise ValueError("Unknown action kind")
            if actor["hp"] == 0:
                raise ValueError("Exhausted active member requires a replacement phase, not an ordinary action")
            plan = {"side": side, "actor_member_id": actor["member_id"], "kind": action["kind"],
                    "source": "BWIKI bound phase rules", "dependencies": []}
            if action["kind"] == "switch":
                target = _integer(action.get("target_slot"), "target_slot")
                if target >= len(team["members"]) or target == team["active_slot"]:
                    raise ValueError("Switch target must be another member of this team")
                if team["members"][target]["hp"] == 0:
                    raise ValueError("Cannot switch to an exhausted member")
                eligibility = switches.departure("voluntary", actor["entered_turn"], state["turn"],
                                                  actor["charge"] is not None, actor["rooted"])
                plan.update(target_slot=target, target_member_id=team["members"][target]["member_id"],
                            departure=eligibility, inherited_marks=switches.transfer_field_marks(team.get("marks")))
                if plan["inherited_marks"]["status"] != "applied":
                    raise ValueError("Field mark state is not valid for transfer")
                if eligibility["status"] == "immune":
                    raise ValueError("Voluntary switch is blocked by departure immunity")
                if eligibility["status"] != "allowed":
                    unresolved.append({"side": side, "reason": eligibility["reason"]})
                incoming = team["members"][target]
                candidates = incoming.get("swift_candidates")
                if candidates is not None:
                    if not isinstance(candidates, list) or len(candidates) != 4:
                        raise ValueError("Swift candidates must retain four ordered slots")
                    for candidate, skill_id in zip(candidates, incoming["skill_slots"]):
                        if (skill_id == 0 and candidate is not None) or (skill_id != 0 and (not isinstance(candidate, dict) or candidate.get("skill_id") != skill_id)):
                            raise ValueError("Swift candidate IDs must exactly match carried slot positions")
                    if "trait_policy" in state:
                        from lab.action_traits import swift_candidates
                        candidates = swift_candidates(prepare_rules(catalog), state, incoming,
                            [row.get("effective_cost") if row else None for row in candidates])
                    plan["entry_swift"] = switches.swift_first_slot(candidates, incoming["energy"])
                    plan["entry_swift"]["input_source"] = "caller_resolved_entry_skill_metadata"
                else:
                    plan["entry_swift"] = {"status": "unresolved", "reason": "入场技能的迅捷条件与最终能耗未提供；不跳过此触发。"}
                if plan["entry_swift"]["status"] == "unresolved":
                    unresolved.append({"side": side, "reason": plan["entry_swift"]["reason"]})
                plan["dependencies"] = ["离场清理与特性触发链", "入场触发及迅捷的最终能耗与顺序"]
                order_inputs[side] = {"kind": "switch", "priority": 0, "speed": actor.get("speed"), "responses": []}
            else:
                slot = _integer(action.get("slot"), "skill slot")
                if slot >= 4 or actor["skill_slots"][slot] == 0:
                    raise ValueError("Selected skill slot is empty or outside four slots")
                skill_id = actor["skill_slots"][slot]
                from lab.action_traits import check_skill_slot
                trait_source = check_skill_slot(prepare_rules(catalog), state, actor, slot)
                if trait_source:
                    plan["action_trait"] = trait_source
                skill = rules.skill(skill_id)
                cost = _integer(action.get("effective_cost"), "explicit effective cost")
                priority = action.get("effective_priority")
                if type(priority) is not int:
                    raise ValueError("Effective priority must be explicitly supplied")
                if cost > actor["energy"]:
                    raise ValueError("Insufficient energy for the explicitly supplied effective cost")
                program = rules.plan(skill_id)["program"]
                if "native_rule" in program and any(component["effect"] == "defense.plan"
                        for component in program["native_rule"]["components"]):
                    raise ValueError("Native defense/response ordering is unresolved; conditional components cannot erase response metadata")
                from lab.defense_runtime import response_categories
                responses = list(dict.fromkeys([op["params"]["response"] for op in program["operations"]
                    if op["op"] == "defense.plan"] + program.get("response_kinds", []) + response_categories(program)))
                if "choice_components" in program:
                    from lab.choice_runtime import response_categories as choice_responses
                    responses = choice_responses(program, action.get("choice_option"))
                plan.update(slot=slot, skill_id=skill_id, program=program,
                            effective_cost=cost, effective_priority=priority,
                            energy_cost_scope="current_action_phase",
                            numeric_input_source="caller_supplied_experiment_inputs")
                order_kind = skill["kind"]
                plan.update(charge_admission(prepare_rules(catalog), actor, skill_id, slot=slot, turn=state["turn"]))
                if plan.get("execution_phase") == "charge_setup_not_attack_release":
                    order_kind = "charge"
                    unresolved.append({"side": side, "reason": "本次为蓄力准备；支付费用时点、迸发消耗及与对手行动的排序尚未核实。"})
                if program["status"] != "compiled":
                    order_semantics_complete = False
                    unresolved.append({"side": side, "reason": "技能完整语义尚未实现", "blockers": program["blockers"]})
                plan["dependencies"] = list(program["execution_blockers"])
                order_inputs[side] = {"kind": order_kind, "priority": priority,
                                      "speed": actor.get("speed"), "responses": responses,
                                      "unresolved_modifiers": deepcopy(action.get("unresolved_modifiers", []))}
            plans[side] = plan
        ordering = phases.order_candidates(order_inputs["a"], order_inputs["b"])
        if not order_semantics_complete:
            ordering = {"status": "unresolved", "possible_orders": [["a", "b"], ["b", "a"]],
                        "reason": "存在未完整解释的技能，无法确定其应对或先手规则。",
                        "probabilities": None, "training_eligible": False, "calibrated": False}
        if ordering["status"] != "determined":
            unresolved.append({"side": "both", "reason": ordering["reason"]})
        unresolved.append({"side": "both", "reason": "配招学习条件、完整伤害、资源结算、特性触发和胜负仍未校准；此结果仅为行动阶段计划，不证明阵容合法。"})
        result.update(status="planned", plans=plans, ordering=ordering, unresolved=unresolved)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        result["blockers"] = [str(exc)]
    return result
