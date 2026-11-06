"""Named v2 turn experiment; source fragments remain separate from policy timing.

No trained agent or verified current-game simulator is provided by this module.
The v1 and strict fragment entry points retain their previous defaults.
"""
from lab import adjacent_power_runtime
from copy import deepcopy
from fractions import Fraction

from lab.action_runtime import _active, _relative
from lab.effect_runtime import HOOKS
from lab.prepared_rules import prepare_rules
from lab.research_battle import (FAINT_POLICY, SIDES, _PlanningOverrides, _finish,
                                 _outcome, _pending, _result, _validate,
                                 _validate_override)
from lab.ruleset import canonical_hash
from lab.skill_execution import execute_skill, preflight_skill
from lab.status_runtime import execute_status_phase
from lab.switch_runtime import execute_switch_fragment
from lab.turn_plan import plan_joint_actions
from lab import weather_runtime as weather
from lab import status_lifecycle as statuses_runtime
from lab import defense_runtime as defense
from lab import pressure_runtime
from lab import response_cost_runtime
from lab import adjacent_cost_runtime
from lab import adjacent_power_aura_runtime
from lab import slot_stat_runtime, power_rule_runtime, team_rotation_runtime, swift_release_runtime
from lab import mechanism_runtime as mechanisms
from lab import trait_attack_hooks, choice_runtime, duration_runtime, action_outcome_runtime, derived_power_runtime, slot_runtime, attack_grant_runtime, dark_surge_runtime, skill_history_runtime, action_field_runtime, status_skill_runtime, mark_steal_runtime
from lab import forced_trait_runtime, payment_runtime
from lab import user_skill_extensions as skill_extensions
from lab import forced_switch_programs, team_target_programs, random_devotion_runtime
from lab import action_traits
from lab import charge_runtime as charges
from lab import trait_runtime as traits
from lab import transformation_runtime as transformations
from lab import mark_runtime as marks
from lab.victory_rules import reconcile_knockouts, terminal
from lab.runtime_programs import reviewed_programs
from lab.core_magic_runtime import effective_skill_cost, effective_skill_power, on_core_magic_departure, end_core_magic_round, validate_core_magic


POLICY_V2 = "switch_charge_status_faint_manual_replacement_v2"
SELECTED_COST_POLICY = "user_confirmed_selected_skill_cost_lock_20261031"
STATUS_FAINT = "research_status_exhaustion_skip_remaining_ticks_experiment"
V2_POLICIES = {
    "ordering": "switch_first_priority_speed_then_explicit_tie_experiment",
    "speed": "weather_base_times_signed_terms_floor_then_flat_mark_experiment",
    "charge": "charge_pay_on_release_experiment",
    "end_phase": "actions_then_living_active_poison_burn_experiment",
    "exhaustion": "cancel_charge_skip_remaining_actions_manual_replacement_experiment",
    "mark_actions": "initial_snapshot_unacted_reset_on_entry_count_skill_recharge_and_charge_setup_experiment",
    "first_attack": "first_position_in_committed_turn_order_experiment",
}
UNRESOLVED_V2 = [
    "V2 switch-first, priority/speed/tie ordering and immediate intrinsic Swift are experimental timing, not verified game order.",
    "Effective speed uses floor(base speed * (1 + sum signed rational spd terms)); the member speed field remains the base input.",
    "Charge setup pays zero and release pays once under an explicit experiment; incomplete skill programs still block release.",
    "Only living active poison/burn tick after actions; side a then b, poison then burn, damage then decay is experimental.",
    "HP basis, status layer arithmetic, caps, rounding and elemental modifiers require an explicit status resolver.",
    "Faint cancels charge and skips remaining actions/ticks; replacement is manual, with source-bound entry/exit hooks but no intrinsic Swift under the replacement experiment.",
    "Reviewed mark layers use named replacement, linear layer and HP policies; star damage, calibrated random distributions, other field effects, full traits, bloodlines and revival remain incomplete. Complete-pool dark-surge sampling is a separate named experiment.",
    "First-action marks count skills, recharge and charge setup from the owned snapshot, reset on entry; first-moving attack means the first committed action position, an uncalibrated timing policy.",
    "Damage, base panels, effective costs/priorities and timing remain uncalibrated research inputs.",
    "Factory defaults treat fixed-hit source power as a total divided across hits; this is an explicit experiment, not verified game damage.",
    "Recharge clamps to each member's explicit max_energy; BattlePet's missing-value fallback is 10, not the historical character_max_energy field 9.",
]


def _suppress_stunned_actions(state, actions):
    actions = deepcopy(actions)
    for side in SIDES:
        if duration_runtime.skip_action(_active(state, side), state['turn'])['skip']:
            actions[side] = {**actions[side], 'kind':'recharge', 'effective_cost':0,
                             'effective_priority':0, 'suppressed_action':True}
    return actions


def _devotion_seed(state) -> int:
    """Episode-scoped random-devotion seed, owned by the state cursor.

    The cursor is written when the battle starts (act_simulation) and advanced
    by every draw, so reading it here keeps every fragment, trait and swift
    context on the same stream. Absent cursor = platform default 0.
    """
    cursor = state.get("random_devotion_rng") if isinstance(state, dict) else None
    if isinstance(cursor, dict) and type(cursor.get("seed")) is int and cursor["seed"] >= 0:
        return cursor["seed"]
    return 0


def _fragment(program, random_seed=0):
    context = {"mode": "isolated_skill_experiment", "snapshot_id": program["snapshot_id"],
               "source_hash": program["source_hash"], "excluded_hooks": sorted(HOOKS),
               "unresolved_dependencies": [], "operation_order": "source_text_order_experiment",
               "energy_policy": "clamp_to_declared_max", "energy_reduction_policy": "clamp_to_zero_experiment",
               "stat_policy": "record_signed_percentage_terms",
               "damage_policy": "resolver_returns_actual_integer_hp_loss",
               "component_evaluation_policy": "after_payment_before_each_component_experiment",
               "conditional_policy": {"timing": "after_payment_before_damage_experiment"},
               "multi_hit_policy": {"power_basis": "source_power_per_hit", "timing": "sequential_experiment"},
               "hp_policy": {"percentage_basis": "declared_max_hp", "rounding": "floor", "cap": "clamp_to_declared_max"},
               "status_policies": {name: {"stacking": "add_to_declared_count", "cap": None,
                                          "immunity_type": element}
                                   for name, element in (("poison", "毒系"), ("burn", "火系"))}}
    if any(key in program for key in ('forced_switch_components', 'team_target_components', 'random_devotion_components', 'slot_components', 'action_field_components')):
        context['component_sequence_payment'] = 'reviewed_component_sequence_v1'
    if "game_file_evidence" in program:
        from lab.game_skill_adapter import game_skill_context
        context.update(game_skill_context(program, resolved_energy_cost=0))
        context.pop("resolved_energy_cost", None)
    context.update(statuses_runtime.research_context())
    context.update(trait_attack_hooks.research_context())
    context["choice_policy"] = choice_runtime.POLICY
    context["choice_recoil_policy"] = choice_runtime.RECOIL_POLICY
    context["adjacent_power_policy"] = adjacent_power_runtime.POLICY
    context.update(duration_runtime.research_context())
    context.update(slot_runtime.research_context())
    context.update(pressure_runtime.research_context())
    context.update(response_cost_runtime.research_context())
    context.update(adjacent_cost_runtime.research_context())
    context.update(adjacent_power_aura_runtime.research_context())
    context.update(slot_stat_runtime.research_context())
    context.update(power_rule_runtime.research_context())
    context.update(team_rotation_runtime.research_context())
    context.update(swift_release_runtime.research_context())
    context.update(dark_surge_runtime.research_context())
    context.update(attack_grant_runtime.research_context())
    context.update(skill_history_runtime.research_context())
    context.update(status_skill_runtime.research_context())
    context.update(mark_steal_runtime.research_context())
    context.update(team_target_programs.research_context())
    context.update(random_devotion_runtime.research_context(random_seed))
    context["defense_policies"] = deepcopy(defense.POLICIES)
    context["transformation_policies"] = transformations.policies()
    context.update(marks.research_context())
    return context


def _recharge_program(prepared):
    from lab.game_runtime_defaults import load_game_runtime_defaults
    source = load_game_runtime_defaults()
    data = source["recharge"]
    return {"game_id": data["skill_id"], "category": "skill", "status": "compiled",
            "snapshot_id": prepared.snapshot_id, "source_hash": canonical_hash(source),
            "blockers": [], "dependency_ids": [], "operations": [{"op": "energy.restore",
            "params": {"target": "self", "amount": data["amount"]}}],
            "game_runtime_source": deepcopy(source)}, source["energy"]["pet_maximum_fallback"]


def _resolved_cost(prepared, state, side, skill_id, base_cost, weather_state, *, charge_setup=True, slot=None, check_readiness=True, choice_option=None, initial_entry_actions=None):
    relative = marks.attach_relative_marks(state, side)
    actor, opponent = relative["self"], relative["opponent"]
    if initial_entry_actions is not None:
        actor.setdefault("mark_entry_actions", initial_entry_actions)
    actor.setdefault("types", deepcopy(prepared._rules.form(actor["form_id"])["types"]))
    actor["weather_trait_id"] = prepared._rules.form(actor["form_id"]).get("trait_id")
    if charge_setup and actor["charge"] is None and prepared._components()[1].requires_charge(skill_id) and not duration_runtime.charge_bypass(actor, state["turn"]):
        if base_cost != 0:
            raise ValueError("V2 charge setup cost must be zero; release pays once")
        return 0
    skill = prepared._rules.skill(skill_id)
    from lab.action_mechanics import GENERATORS
    if skill_id in GENERATORS:
        return 0
    from lab.energy_burst_runtime import programs as energy_burst_programs
    if skill_id in energy_burst_programs(prepared):
        if check_readiness:
            duration_runtime.check_cooldown(actor, skill_id, state["turn"])
        return actor["energy"]
    base_cost = max(0, traits.base_skill_cost(actor, skill["energy"]) + base_cost - skill["energy"])
    if check_readiness:
        duration_runtime.check_cooldown(actor, skill_id, state["turn"])
    base_cost = skill_history_runtime.cost(prepared, state, side, skill_id, base_cost, slot=slot)
    base_cost = choice_runtime.cost(prepared._rules.program(skill_id), choice_option, base_cost, actor=actor)
    value = mechanisms.cost(actor, skill_id, base_cost, state["turn"], opponent=opponent, skill_kind=skill["kind"])
    value = duration_runtime.cost(actor, skill["kind"], value, state["turn"])
    value = traits.modify_cost(actor, opponent, skill, value)
    value = marks.modify_cost(actor, value, skill_id, opponent, skill["kind"])
    value = weather.modify_cost(weather_state, skill["type"], value, skill_id, actor)
    value = defense.conditional_cost(state, side, skill_id, value)
    value = response_cost_runtime.resolved_cost(state, side, skill_id, value)
    value = adjacent_cost_runtime.resolved_cost(state, side, skill_id, slot, value)
    return action_field_runtime.fixed_cost(skill_id, effective_skill_cost(state, side, value))


def _carried_cost_snapshot(prepared, state, side, selected_action=None, *, allow_partial=False):
    from lab.dynamic_skills import cost_delta
    actor = _active(state, side)
    selected_action = selected_action or {}
    matches = selected_action.get('actor_member_id',actor['member_id']) == actor['member_id']
    values = []
    for slot, mid in enumerate(actor['skill_slots']):
        if not mid:
            values.append(None)
            continue
        try:
            values.append(_resolved_cost(prepared, state, side, mid,
                max(0, prepared._rules.skill(mid)['energy'] + cost_delta(actor, slot)), state.get('weather'),
                charge_setup=False, slot=slot, check_readiness=False,
                choice_option=selected_action.get('choice_option') if matches and selected_action.get('kind')=='skill' and selected_action.get('slot')==slot else None))
        except ValueError as exc:
            if not allow_partial:
                raise
            values.append({'blocked':str(exc)})
    return values


def _trait_cost_context(prepared, state, side, actions=None):
    if not any(traits.requires_cost_snapshot(_active(state, s)) for s in SIDES):
        return {}
    other = 'b' if side == 'a' else 'a'
    actions = actions or {}
    return {'trait_carried_costs': {'self':_carried_cost_snapshot(prepared,state,side,actions.get(side)),
                                   'opponent':_carried_cost_snapshot(prepared,state,other,actions.get(other))}}


def _preflight_component(program, state, context, *, damage_resolver=None):
    return payment_runtime.preflight(program, state, context,
        preflight_base=_preflight_component_unpaid, damage_resolver=damage_resolver)


def _preflight_component_unpaid(program, state, context, *, damage_resolver=None):
    if context.get("execution_phase") == "jealousy_release_pending_execution":
        from lab.charge_program_adapter import validate_jealousy_release
        validate_jealousy_release(program, state['self'], context)
    from lab.hud_damage_runtime import resolve_adaptive_program
    program = resolve_adaptive_program(program, state, context)
    if "cute_components" in program:
        from lab import cute_runtime
        return cute_runtime.preflight(program, state, context, damage_resolver)
    if "conditional_mark_components" in program:
        return skill_extensions.preflight_conditional_mark(program, state, context, damage_resolver)
    if "per_type_power_components" in program:
        return skill_extensions.preflight_per_type_power(program, state, context, damage_resolver)
    if "status_skill_components" in program:
        return status_skill_runtime.preflight(program, state, context, damage_resolver)
    if "adjacent_power_components" in program and "adjacent_power_evidence" not in program:
        program = adjacent_power_runtime.resolve(program, state, context)
    if "action_field_components" in program:
        program = action_field_runtime.resolve(program, context, state)
    if "attack_grant_components" in program:
        return attack_grant_runtime.preflight(program, state, context, damage_resolver=damage_resolver)
    if "derived_power_components" in program:
        program = derived_power_runtime.resolve(program, context)
    if "duration_components" in program:
        duration_runtime._validate(program, context)
        duration_runtime.check_cooldown(state["self"], program["game_id"], context["turn"])
        context = {**context, "component_sequence_payment": "reviewed_component_sequence_v1"}
    if "choice_components" in program:
        return choice_runtime.preflight(program, state, context, option=context.get("choice_option"), damage_resolver=damage_resolver)
    if "charge_components" in program:
        charges.preflight(program, state, context, damage_resolver)
    elif "transformation_components" in program:
        transformations.preflight(program, state, context, damage_resolver)
    elif "defense_components" in program:
        defense.preflight_defense_skill(program, state, context, turn=context["turn"],
            opponent_kind=context["opponent_kind"], opponent_effective_cost=context.get("opponent_effective_cost"))
    elif "mechanism_components" in program:
        mechanisms.preflight(program, state, context, damage_resolver)
    elif "pressure_components" in program:
        pressure_runtime.preflight(program, state, context, damage_resolver)
    elif "response_cost_components" in program:
        response_cost_runtime.preflight(program, state, context, damage_resolver)
    elif "adjacent_cost_components" in program:
        adjacent_cost_runtime.preflight(program, state, context, damage_resolver)
    elif "adjacent_power_components" in program:
        adjacent_power_aura_runtime.preflight(program, state, context, damage_resolver)
    elif "power_rule_components" in program:
        program = power_rule_runtime.resolve(program, state, context)
    elif "swift_release_components" in program:
        swift_release_runtime.preflight(program, state, context, damage_resolver)
    elif "team_rotation_components" in program:
        team_rotation_runtime.preflight(program, state, context, damage_resolver)
    elif "slot_stat_components" in program:
        slot_stat_runtime.preflight(program, state, context, damage_resolver)
    elif "weather_components" in program:
        weather.preflight_weather_skill(program, state, context)
    else:
        preflight_skill(program, state, context, damage_resolver)


def _execute_component(program, state, context, *, damage_resolver=None):
    return payment_runtime.execute(program, state, context,
        execute_base=_execute_component_unpaid, damage_resolver=damage_resolver)


def _execute_component_unpaid(program, state, context, *, damage_resolver=None):
    if context.get("execution_phase") == "jealousy_release_pending_execution":
        from lab.charge_program_adapter import validate_jealousy_release
        validate_jealousy_release(program, state['self'], context)
        if ("charge_components" not in program
                and program.get("execution_scope") != "charge_release_payload_requires_external_charge_phase"
                and context.get("charge_program_source") != "override"):
            raise ValueError('Jealousy cannot release an uncompiled charge payload')
    from lab.hud_damage_runtime import resolve_adaptive_program
    program = resolve_adaptive_program(program, state, context)
    if "cute_components" in program:
        from lab import cute_runtime
        return cute_runtime.execute(program, state, context, damage_resolver)
    if "conditional_mark_components" in program:
        return skill_extensions.execute_conditional_mark(program, state, context, damage_resolver)
    if "per_type_power_components" in program:
        return skill_extensions.execute_per_type_power(program, state, context, damage_resolver)
    if (context.get("execution_phase") == "charge_release_pending_execution"
            and "charge_components" not in program
            and program.get("execution_scope") != "charge_release_payload_requires_external_charge_phase"
            and context.get("charge_program_source") != "override"):
        raise ValueError("Charge release requires compiled charge components; "
                         "a raw description cannot fake a complete release")
    if "status_skill_components" in program:
        return status_skill_runtime.execute(program, state, context, damage_resolver)
    if "adjacent_power_components" in program and "adjacent_power_evidence" not in program:
        program = adjacent_power_runtime.resolve(program, state, context)
    if "action_field_components" in program:
        program = action_field_runtime.resolve(program, context, state)
    if "attack_grant_components" in program:
        return attack_grant_runtime.execute(program, state, context, damage_resolver=damage_resolver)
    if "derived_power_components" in program:
        program = derived_power_runtime.resolve(program, context)
    if "duration_components" in program:
        return duration_runtime.execute_duration_skill(program, state, context, damage_resolver=damage_resolver)
    if "choice_components" in program:
        return choice_runtime.execute_choice_skill(program, state, context, option=context.get("choice_option"), damage_resolver=damage_resolver)
    if "charge_components" in program:
        return charges.execute(program, state, context, damage_resolver)
    if "transformation_components" in program:
        return transformations.execute(program, state, context, damage_resolver)
    if "defense_components" in program:
        return defense.execute_defense_skill(program, state, context, turn=context["turn"],
            opponent_kind=context["opponent_kind"], opponent_effective_cost=context.get("opponent_effective_cost"))
    if "mechanism_components" in program:
        return mechanisms.execute(program, state, context, damage_resolver)
    if "pressure_components" in program:
        return pressure_runtime.execute(program, state, context, damage_resolver)
    if "response_cost_components" in program:
        return response_cost_runtime.execute(program, state, context, damage_resolver)
    if "adjacent_cost_components" in program:
        return adjacent_cost_runtime.execute(program, state, context, damage_resolver)
    if "adjacent_power_components" in program:
        return adjacent_power_aura_runtime.execute(program, state, context, damage_resolver)
    if "power_rule_components" in program:
        program = power_rule_runtime.resolve(program, state, context)
    if "swift_release_components" in program:
        return swift_release_runtime.execute(program, state, context, damage_resolver)
    if "team_rotation_components" in program:
        return team_rotation_runtime.execute(program, state, context, damage_resolver)
    if "slot_stat_components" in program:
        return slot_stat_runtime.execute(program, state, context, damage_resolver)
    if "weather_components" in program:
        return weather.execute_weather_skill(program, state, context, context.get("weather"), context["turn"])
    return execute_skill(program, state, context, damage_resolver=damage_resolver)


def _finish_v2(result, current, *, advance=True, policy=POLICY_V2):
    if advance:
        result["events"].extend(end_core_magic_round(current))
    _finish(result, current, advance=advance, policy=policy)
    if result.get("turn_advanced"):
        try:
            result["events"].extend(marks.prepare_battle_transmission(current))
        except Exception as exc:
            current["research_battle"].update(phase="blocked", turn_pending=False,
                                              blocked_stage="next_round_transmission")
            result.update(status="blocked", blockers=[str(exc)], next_round_preparation={
                "status": "blocked", "stage": "transmission", "completed_turn": current["turn"] - 1,
                "next_turn": current["turn"], "completed_actions_retained": True})
        result["state"] = deepcopy(current)


def _record_action_events(result, events, current, side, index, action):
    other = "b" if side == "a" else "a"
    for event in events:
        event = deepcopy(event)
        target = side if event.get("target", "self") == "self" else other
        event.update(action_index=index, research_policy=POLICY_V2)
        if event.get('op') == 'trait.retaliation':
            event.setdefault("actor_side", side)
        else:
            event["actor_side"] = side
        event.setdefault("actor_member_id", action["actor_member_id"])
        event.setdefault("target_side", target)
        event.setdefault("target_member_id", _active(current, target)["member_id"])
        if action["kind"] in ("skill", "recharge") and event.get("op") != "trait.retaliation":
            event.setdefault("skill_id", action["skill_id"])
            event.setdefault("skill_slot", action["slot"])
            event.setdefault("source_hash", action["program"]["source_hash"])
        result["events"].append(event)


def _battle_reviewed_programs(prepared, state, program_overrides):
    ids = {mid for team in state["teams"].values() for member in team["members"]
           for mid in member["skill_slots"] if mid}
    ids.update(program_overrides or {})
    # A queued intrinsic Swift can outlive the carried slot that released it.
    swift = swift_release_runtime._data()
    ids.update(int(mid) for group in ("skills", "swift_skills") for mid in swift[group])
    return reviewed_programs(prepared, ids)


def build_research_context_v2(catalog, state, actions, *, program_overrides=None,
                              tie_break_side="a", fragment_overrides=None,
                              incoming_effective_costs=None, burn_decay_rounding="floor",
                              random_seed=None):
    """Server-owned factory: callers need no hashes, programs or policy strings.

    Incoming costs start from source energy plus the generated slot's delta.
    Caller-supplied incoming costs use that same base-plus-delta boundary; the
    reviewed mechanism/trait/mark/weather/magic chain is applied once here.

    ``random_seed`` is derived from the battle's ``random_devotion_rng`` cursor
    when omitted, so one episode keeps one seed; an explicit value must match
    the cursor the state already carries.
    """
    if random_seed is None:
        random_seed = _devotion_seed(state)
    if type(random_seed) is not int or random_seed < 0:
        raise ValueError("random_seed must be a nonnegative integer")
    prepared = prepare_rules(catalog)
    state = deepcopy(state)
    traits.bind(prepared, state)
    if "core_magic_runtime" in state:
        validate_core_magic(state)
    overrides = {**_battle_reviewed_programs(prepared, state, program_overrides), **weather.weather_programs(prepared), **weather.weather_attack_programs(prepared), **deepcopy(program_overrides or {})}
    for skill_id, program in overrides.items():
        _validate_override(prepared, skill_id, program)
    context = {"mode": "research_battle_experiment", "policy": POLICY_V2,
               "excluded_hooks": sorted(HOOKS), "v2_policies": deepcopy(V2_POLICIES),
               "tie_break_side": tie_break_side, "fragments": {}, "switches": {},
               "status_context": {"mode": "isolated_status_phase_experiment",
                   "status_lifecycle_policy": statuses_runtime.POLICY, "leech_policy": statuses_runtime.LEECH_POLICY,
                   "snapshot_id": prepared.snapshot_id, "catalog_content_hash": prepared.catalog_content_hash,
                   "excluded_hooks": sorted(HOOKS), "unresolved_dependencies": [],
                   "operation_order": "damage_then_decay_experiment", "faint_policy": STATUS_FAINT,
                   "status_policy": {"immunity": "reject_existing_immune_status",
                                     "burn_decay_rounding": burn_decay_rounding}}}
    actions = _suppress_stunned_actions(state, actions)
    for side in SIDES:
        action = actions[side]
        actor = _active(state, side)
        context["fragments"][side] = {}
        if action["kind"] == "skill":
            skill_id = actor["skill_slots"][action["slot"]]
            program = overrides.get(skill_id, prepared._rules.program(skill_id))
            if 'forced_switch_components' in program:
                forced_switch_programs.preflight_selection(prepared, state, side, skill_id, action.get('replacement_slot'), action.get('opponent_replacement_slot'))
            context["fragments"][side] = _fragment(program, _devotion_seed(state))
            context["fragments"][side]["selected_skill_slot"] = action.get("slot")
            context["fragments"][side]["charge_program_source"] = (
                "override" if skill_id in overrides else "raw")
            context["fragments"][side].update(_trait_cost_context(prepared, state, side, actions))
            if program.get("requires_carried_cost_snapshot"):
                context['fragments'][side]['carried_effective_skill_costs'] = _carried_cost_snapshot(prepared, state, side, action, allow_partial='adjacent_power_components' in program)

            if program.get('requires_opponent_cost_snapshot'):
                other = 'b' if side == 'a' else 'a'
                context['fragments'][side]['opponent_effective_skill_costs'] = _carried_cost_snapshot(prepared,state,other,actions[other])
            context["fragments"][side]["carried_attack_skill_ids"] = [mid for mid in actor['skill_slots']
                if mid and prepared._rules.skill(mid)['kind'] in ('physical','magical','higher')]
            if "choice_components" in program:
                context["fragments"][side]["choice_option"] = action.get("choice_option")
                choice_runtime.select(program, action.get("choice_option"), context=context["fragments"][side], validate_only=True)
        elif action["kind"] == "recharge":
            program, _ = _recharge_program(prepared)
            context["fragments"][side] = _fragment(program, _devotion_seed(state))
            context["fragments"][side]["selected_skill_slot"] = action.get("slot")
            context["fragments"][side].update(_trait_cost_context(prepared, state, side, actions))
            if program.get('requires_opponent_cost_snapshot'):
                other = 'b' if side == 'a' else 'a'
                context['fragments'][side]['opponent_effective_skill_costs'] = _carried_cost_snapshot(prepared,state,other,actions[other])
            context["fragments"][side]["carried_attack_skill_ids"] = [mid for mid in actor['skill_slots']
                if mid and prepared._rules.skill(mid)['kind'] in ('physical','magical','higher')]
        elif action["kind"] == "switch":
            from lab.dynamic_skills import cost_delta
            incoming = state["teams"][side]["members"][action["target_slot"]]
            provided = side in (incoming_effective_costs or {})
            costs = (deepcopy(incoming_effective_costs[side]) if provided else
                [max(0, prepared._rules.skill(mid)["energy"] + cost_delta(incoming, slot)) if mid else None
                 for slot, mid in enumerate(incoming["skill_slots"])])
            if not isinstance(costs, list) or len(costs) != 4:
                raise ValueError("Incoming final costs require four ordered slots")
            prospective = traits.preview_entry_history(state, side, action['target_slot'])
            entry_actor = _active(prospective, side)
            costs = [_resolved_cost(prepared, prospective, side, mid, base, state.get("weather"), charge_setup=False, slot=slot) if mid else None
                     for slot, (mid, base) in enumerate(zip(incoming["skill_slots"], costs))]
            switch = {"mode": "isolated_voluntary_switch_experiment", "snapshot_id": prepared.snapshot_id,
                      "catalog_content_hash": prepared.catalog_content_hash, "excluded_hooks": sorted(HOOKS),
                      "unresolved_dependencies": [], "cleanup_policy": "retain_member_fields_experiment",
                      "swift_policy": action_traits.SWIFT_POLICY if 'trait_policy' in state else "intrinsic_source_only_experiment", "incoming_effective_costs": costs,
                      "status_lifecycle_policy": statuses_runtime.POLICY,
                      "entry_timing": "after_position_change_experiment", "faint_policy": FAINT_POLICY}
            if "switch_cooldown" in action:
                switch["switch_cooldown"] = deepcopy(action["switch_cooldown"])
            switch.update(marks.research_context())
            candidates = action_traits.swift_candidates(prepared, prospective, entry_actor, costs)
            swift = prepared._components()[2].swift_first_slot(candidates, entry_actor["energy"])
            if swift["status"] == "selected":
                # Switch runtime binds its own reviewed Swift program, not an arbitrary override.
                switch["entry_skill_context"] = _fragment(prepared._rules.program(swift["skill_id"]),
                                                          _devotion_seed(state))
            context["switches"][side] = switch
        else:
            raise ValueError("Unknown v2 action kind")
        if side in (fragment_overrides or {}):
            context["fragments"][side].update(deepcopy(fragment_overrides[side]))
        if context["fragments"].get(side):
            # One episode, one seed: every skill fragment draws from the same
            # state-cursor stream (matches random_devotion.apply's cursor check).
            context["fragments"][side]["random_devotion_seed"] = random_seed
    _context(context)
    return context


def _context(context):
    if (not isinstance(context, dict) or context.get("mode") != "research_battle_experiment"
            or context.get("policy") != POLICY_V2 or context.get("v2_policies") != V2_POLICIES
            or context.get("tie_break_side") not in SIDES):
        raise ValueError("Explicit v2 policies and a deterministic tie_break_side are required")
    hooks = context.get("excluded_hooks")
    if not isinstance(hooks, list) or len(hooks) != len(HOOKS) or set(hooks) != HOOKS:
        raise ValueError("V2 requires explicitly excluded hooks")
    canonical_hash(context)


def _effective_speed(actor, turn=None, opponent=None):
    if actor.get("speed") is None:
        return None
    speed = Fraction(actor["speed"]) * (1 + sum((Fraction(t["numerator"], t["denominator"])
                    for t in [*actor["stat_modifiers"].get("spd", []), *traits.stat_terms(actor, "spd", turn)]), Fraction(0)))
    value = speed.numerator // speed.denominator
    value += traits.speed_bonus(actor, opponent=opponent)
    value = mechanisms.modify_speed(actor, value)
    value = charges.modify_speed(actor, value)
    value = dark_surge_runtime.modify_speed(actor, value)
    value = marks.modify_speed(actor, value)
    if value <= 0:
        raise ValueError("Experimental effective speed must be positive after signed terms and floor")
    return value


def _order(plan, state, actions, context):
    # Preserve source-supported ordering when available; named policy only fills
    # the unresolved switch/setup/same-priority order, never defense semantics.
    speeds = {side: _effective_speed(_active(state, side), state["turn"], _active(state, "b" if side == "a" else "a")) for side in SIDES}
    if plan["ordering"]["status"] == "determined":
        return plan["ordering"]["possible_orders"][0]
    for side in SIDES:
        action, actor = actions[side], _active(state, side)
        if action.get("unresolved_modifiers"):
            raise ValueError("Unresolved action modifiers cannot be erased by v2 ordering")
        if speeds[side] is None:
            raise ValueError("V2 ordering requires an explicit speed")
        if action["kind"] != "switch" and type(action.get("effective_priority")) is not int:
            raise ValueError("V2 skill/recharge requires explicit effective_priority")
    def key(side):
        action = actions[side]
        return (int(action["kind"] == "switch"), action.get("effective_priority", 0),
                speeds[side], int(side == context["tie_break_side"]))
    return sorted(SIDES, key=key, reverse=True)


def _skill_context(context, side, actor, opponent, action):
    fragment = deepcopy(context["fragments"][side])
    cost = action["effective_cost"]
    if "resolved_energy_cost" in fragment and fragment["resolved_energy_cost"] != cost:
        raise ValueError("Fragment cost conflicts with action cost")
    fragment.update(execution_phase=action.get("execution_phase"), resolved_energy_cost=cost,
                    energy_before_cast=actor["energy"], faint_policy=FAINT_POLICY, actor_side=side,
                    actor_member_id=actor["member_id"], opponent_member_id=opponent["member_id"],
                    selected_skill_slot=action.get('slot'))
    if action.get('jealousy_release') is not None:
        fragment['jealousy_release'] = deepcopy(action['jealousy_release'])
    return fragment


def _opponent_cost_snapshot(prepared, state, side, action, original_action, committed):
    if action['kind'] != 'skill':
        return 0
    if committed:
        return action.get('health_payment', {}).get('total_cost', action['effective_cost'])
    if _active(state, side)['member_id'] != action['actor_member_id']:
        return 0
    if '_selected_total_cost' in action and not action.get('program', {}).get('energy_burst_components'):
        return action['_selected_total_cost']
    return _resolved_cost(prepared, state, side, action['skill_id'], original_action['effective_cost'], state.get('weather'), slot=action.get('slot'), choice_option=original_action.get('choice_option'))


def _kind(prepared, action):
    if action.get("execution_phase") == "charge_setup_not_attack_release":
        return "charge"
    return prepared._rules.skill(action["skill_id"])["kind"] if action["kind"] == "skill" else action["kind"]


class CommittedHookFailure(ValueError):
    """A source component explicitly retained an earlier committed sub-action."""
    def __init__(self, message, events):
        super().__init__(message)
        self.events = events


def _reconcile_faint_traits(prepared, state):
    events = reconcile_knockouts(state)
    for event in list(events):
        if event.get('op') == 'victory.knockout':
            events.extend(traits.after_faint(prepared, state, event['side'], event['member_id'], occurrence=event['occurrence']))
    return events


def execute_research_turn_v2(catalog, state, actions, context, *, damage_resolver=None,
                             status_damage_resolver=None, program_overrides=None):
    result = _result(state, policy=POLICY_V2, unresolved=UNRESOLVED_V2)
    result.update(status_phase_executed=False, end_of_turn_executed=False)
    current = deepcopy(state)
    try:
        _context(context)
        context, actions = deepcopy(context), _suppress_stunned_actions(state, actions)
        prepared = prepare_rules(catalog)
        _validate(prepared, current, status_lifecycle_policy=statuses_runtime.POLICY)
        if "core_magic_runtime" in current:
            validate_core_magic(current)
        marks.validate_battle_transmission(current)
        traits.bind(prepared, current)
        weather.validate_weather_members(current)
        for side, team in current["teams"].items():
            marks.validate_marks(team["marks"])
            for member in team["members"]:
                count = member.setdefault("mark_entry_actions", 0)
                if type(count) is not int or count < 0:
                    raise ValueError("Mark entry action counter must be a nonnegative integer")
                statuses_runtime.validate_lifecycles(member)
                if member["statuses"].get("leech", 0):
                    statuses_runtime.validate_leech_binding(member, side, current)
                mechanisms.validate_member(member)
                pressure_runtime.validate_member(member)
                response_cost_runtime.validate_member(member)
                adjacent_cost_runtime.validate_member(member)
                adjacent_power_aura_runtime.validate_member(member)
                slot_stat_runtime.validate_member(member)
                power_rule_runtime.validate_member(member)
                team_rotation_runtime.validate_member(member)
                swift_release_runtime.validate_member(member)
        for team in current["teams"].values():
            for member in team["members"]:
                member["weather_trait_id"] = prepared._rules.form(member["form_id"]).get("trait_id")
        lifecycle = current.get("research_battle", {})
        if lifecycle and (lifecycle.get("policy") != POLICY_V2 or lifecycle.get("phase") != "ready"):
            raise ValueError("Pending, blocked or finished v2 turn cannot be replayed")
        if terminal(current)["terminal"] or any(_active(current, side)["hp"] == 0 for side in SIDES):
            _finish_v2(result, current, advance=False, policy=POLICY_V2)
            if result["status"] == "awaiting_replacement":
                current["research_battle"]["turn_pending"] = False
                result["state"] = deepcopy(current)
            return result
        if not isinstance(actions, dict) or set(actions) != set(SIDES):
            raise ValueError("Exactly both actions required")
        if set(context.get("fragments", {})) != set(SIDES):
            raise ValueError("Both fragment contexts required")
        overrides = {**_battle_reviewed_programs(prepared, current, program_overrides), **weather.weather_programs(prepared), **weather.weather_attack_programs(prepared), **deepcopy(program_overrides or {})}
        for skill_id, program in overrides.items():
            _validate_override(prepared, skill_id, program)
        result["events"].extend(traits.initialize(prepared, current))
        result["events"].extend(trait_attack_hooks.initialize(prepared, current))
        result["events"].extend(skill_history_runtime.initialize(prepared, current))
        planner = _PlanningOverrides(prepared, overrides) if overrides else prepared
        # Recharge is a common global skill outside the BWIKI carried learnset.
        # Validate its resource/action contract separately, then use a harmless
        # synthetic plan envelope only for ordering alongside the source planner.
        planned_actions = deepcopy(actions)
        planner_state = deepcopy(current)
        recharge = {}
        def type_ratio(element, member):
            ratio = prepared._rules.type_multiplier(element, member["form_id"])["multiplier"]
            return Fraction(ratio["numerator"], ratio["denominator"])
        for side in SIDES:
            actor = _active(planner_state, side)
            actor["field_marks"] = deepcopy(current["teams"][side]["marks"])
            if actor.get("speed") is not None:
                actor["speed"] = weather.modify_speed(current.get("weather"), actor["speed"], actor)
            action = planned_actions[side]
            if action.get("kind") == "skill":
                mid = actor["skill_slots"][action["slot"]]
                skill = prepared._rules.skill(mid)
                if 'forced_switch_components' in overrides.get(mid, {}):
                    forced_switch_programs.preflight_selection(prepared, current, side, mid, actions[side].get('replacement_slot'), actions[side].get('opponent_replacement_slot'))
                action["effective_cost"] = _resolved_cost(prepared, current, side, mid, action["effective_cost"], current.get("weather"), slot=action.get("slot"), choice_option=actions[side].get("choice_option"))
                action['effective_priority'] = mechanisms.modify_priority(overrides.get(mid, prepared._rules.program(mid)), action['effective_priority'])
                action['effective_priority'] += overrides.get(mid, {}).get('forced_switch_components', {}).get('priority_delta', 0)
                action['effective_priority'] = action_field_runtime.priority(mid, action['slot'], action['effective_priority'])
                action["effective_priority"] = weather.modify_priority(current.get("weather"), mid, action["effective_priority"], actor)
        # Admission uses the already-declared action order and preceding weather
        # setters. It must not reject an affordable later move at its old price.
        # This existing weather preview forms the selection quote; the queued
        # ordinary cast retains that price when later actions modify fees.
        if any(a.get("kind") == "skill" and weather.is_weather_skill(
                _active(current, side)["skill_slots"][a["slot"]]) for side, a in actions.items()):
            preview_order = _order({"ordering": {"status": "unresolved"}}, planner_state, planned_actions, context)
            preview_weather = deepcopy(current.get("weather"))
            for side in preview_order:
                action = planned_actions[side]
                if action.get("kind") != "skill":
                    continue
                actor = _active(current, side)
                mid = actor["skill_slots"][action["slot"]]
                skill = prepared._rules.skill(mid)
                action["effective_cost"] = _resolved_cost(prepared, current, side, mid, actions[side]["effective_cost"], preview_weather, slot=action.get("slot"), choice_option=actions[side].get("choice_option"))
                if weather.is_weather_skill(mid):
                    preview_weather, _ = weather.set_weather(preview_weather, mid, current["turn"])
        for side in SIDES:
            if actions[side].get("kind") == "recharge":
                program, fallback = _recharge_program(prepared)
                actor = _active(current, side)
                if actions[side].get("effective_cost") != 0 or type(actions[side].get("effective_cost")) is not int:
                    raise ValueError("Recharge source cost must be explicitly zero")
                recharge[side] = program
                source = program["game_runtime_source"]
                metadata = result.setdefault("global_skill_sources", {}).setdefault(str(program["game_id"]), {
                    "version": source["version"], "source_hashes": deepcopy(source["source_hashes"]),
                    "source_hash": program["source_hash"], "amount": source["recharge"]["amount"],
                    "raw_priority": source["recharge"]["priority"], "priority_mapping_verified": False,
                    "energy_cap_source": "actor.max_energy", "runtime_energy_caps": {},
                    "pet_maximum_fallback": fallback,
                    "pet_maximum_accessor": source["energy"]["pet_maximum_fallback_source"]["function"],
                    "pet_maximum_runtime_field": source["energy"]["pet_maximum_fallback_source"]["runtime_field"],
                    "character_max_energy_raw": source["energy"]["maximum_raw"],
                    "character_max_energy_used_as_pet_cap": False,
                    "runtime_version_verified": False})
                metadata["runtime_energy_caps"][side] = actor["max_energy"]
                # The planner never executes this stand-in carried skill.
                _active(planner_state, side)["charge"] = None
                _active(planner_state, side)["skill_slots"] = [7020370, 0, 0, 0]
                planned_actions[side] = {**actions[side], "kind": "skill", "slot": 0}
        forced_trait_runtime.bind_round_choices(prepared, current, actions)
        for side in SIDES:
            proposed = planned_actions[side]
            actor = _active(current, side)
            if proposed['kind'] == 'skill' and proposed['effective_cost'] > actor['energy']:
                mid = actor['skill_slots'][proposed['slot']]
                quote = payment_runtime.quote(prepared, actor, mid, proposed['effective_cost'])
                proposed['effective_cost'] = quote['paid_energy']
                proposed['health_payment'] = quote
        if any(_active(current, s).get('trait_id') == 200262 for s in SIDES):
            from lab.hud_damage_runtime import make_hud_damage_resolver
            from lab.turn_plan import charge_admission
            predictor = make_hud_damage_resolver(prepared)
            for watcher in SIDES:
                if _active(current, watcher).get('trait_id') != 200262:
                    continue
                enemy = 'b' if watcher == 'a' else 'a'
                selected = planned_actions[enemy]
                prediction = 0
                if actions[enemy]['kind'] == 'skill' and not selected.get('suppressed_action'):
                    attacker = _active(current, enemy)
                    mid = attacker['skill_slots'][selected['slot']]
                    admission = charge_admission(
                        prepared, attacker, mid, slot=selected['slot'], turn=current['turn'])
                    if (admission.get('execution_phase') != 'charge_setup_not_attack_release'
                            and prepared._rules.skill(mid)['kind'] in ('physical', 'magical', 'higher')):
                        fragment = _skill_context(context, enemy, attacker, _active(current, watcher), selected)
                        fragment.update(turn=current['turn'], mark_first_action=attacker['mark_entry_actions'] == 0,
                                        mark_first_attack=False, response_success=False)
                        prediction = predictor.predict_single_hit(marks.attach_relative_marks(current, enemy), mid, fragment)
                result['events'].extend(traits.prepare_sentry(prepared, current, watcher,
                    predicted_single_hit=prediction, token=f"{current['turn']}:{watcher}:sentry"))
                _active(planner_state, watcher)['sentry_prediction'] = deepcopy(_active(current, watcher)['sentry_prediction'])
        for priority_side in SIDES:
            planned_actions[priority_side]["effective_priority"] = planned_actions[priority_side].get("effective_priority", 0) + traits.priority_bonus(_active(current, priority_side)) + mechanisms.priority_bonus(_active(current, priority_side))
        plan = plan_joint_actions(planner, planner_state, planned_actions)
        if plan["status"] != "planned":
            raise ValueError("Joint plan rejected: " + "; ".join(plan["blockers"]))
        repeat_counts = {side: (skill_extensions.repeat_count(_active(current, side))
            if plan['plans'][side].get('program', {}).get('repeat_cast_components') else 1) for side in SIDES}
        for side in SIDES:
            action = plan["plans"][side]
            if action['kind'] == 'skill' and side not in recharge:
                proposed = planned_actions[side]
                action['_selected_total_cost'] = proposed.get('health_payment', {}).get(
                    'total_cost', proposed['effective_cost'])
                action['_selected_cost_policy'] = SELECTED_COST_POLICY
            action["_skill_history_binding"] = skill_history_runtime.bind_action(prepared, current, side, action)
            if side in recharge:
                action.update(kind="recharge", program=recharge[side], skill_id=recharge[side]["game_id"], slot=None)
                action.pop("execution_phase", None)
            if action["kind"] in ("skill", "recharge"):
                program = action["program"]
                if action.get("execution_phase") == "charge_setup_not_attack_release":
                    if action["effective_cost"] != 0:
                        raise ValueError("V2 charge setup cost must be zero; release pays once")
                else:
                    fragment = _skill_context(context, side, _active(current, side),
                                              _active(current, "b" if side == "a" else "a"), action)
                    fragment.update(turn=current["turn"])
                    if program.get('repeat_cast_components'):
                        fragment['repeat_cast_phase'] = {'policy': skill_extensions.POLICY,
                            'release_index': 0, 'release_count': repeat_counts[side]}
                    hit_field = traits.fixed_hits(current)
                    fragment.update(fixed_hit_count=hit_field["count"], fixed_hit_sources=hit_field["sources"], fixed_hit_policy=hit_field["policy"])
                    if 'health_payment' in planned_actions[side]:
                        fragment['health_payment'] = deepcopy(planned_actions[side]['health_payment'])
                    other_action = plan["plans"]["b" if side == "a" else "a"]
                    skill = prepared._rules.skill(action["skill_id"]) if action["kind"] == "skill" else {}
                    fragment.update(opponent_kind=_kind(prepared, other_action),
                        opponent_declared_skill=other_action.get("skill_id") if other_action.get("kind") == "skill" else None,
                        opponent_effective_cost=planned_actions["b" if side == "a" else "a"].get("health_payment", {}).get("total_cost", other_action.get("effective_cost", 0)),
                        skill_kind=skill.get("kind", "recharge"),
                        skill_type=weather.resolved_skill_type(current.get("weather"), action["skill_id"], skill.get("type")),
                        mark_first_action=_active(current, side)["mark_entry_actions"] == 0,
                        mark_first_attack=False, response_success=False)
                    if "defense_components" in program:
                        defense.preflight_departure(prepared, current, side, program, opponent_kind=_kind(prepared, other_action),
                            replacement_slot=actions[side].get("replacement_slot"), opponent_replacement_slot=actions[side].get("opponent_replacement_slot"))
                    if "mark_steal_components" in program:
                        mark_steal_runtime.preflight(prepared, current, side, program, context=fragment)
                    if "slot_components" in program:
                        slot_runtime.preflight_selection(prepared, current, side, action, context=fragment)
                    if "team_rotation_components" in program:
                        rotation_check = team_rotation_runtime.preflight_battle(
                            prepared, current, side, program, context=fragment)
                        if rotation_check["status"] != "applied":
                            raise ValueError("Team rotation blocked: " + "; ".join(rotation_check["blockers"]))
                    marks.preflight_with_marks(program, marks.attach_relative_marks(current, side), fragment,
                        damage_resolver=damage_resolver, mark_damage_resolver=getattr(damage_resolver, "mark_damage", None),
                        preflight_base=_preflight_component)
        order = _order(plan, planner_state, planned_actions, context)
        # Recharge must use the explicit common-action order, not any response
        # metadata accidentally inherited from its planner stand-in.
        if recharge:
            synthetic = deepcopy(plan)
            synthetic["ordering"]["status"] = "unresolved"
            order = _order(synthetic, planner_state, planned_actions, context)
        release_order = [(side, release, repeat_counts[side]) for side in order
                         for release in range(repeat_counts[side])]
        result["action_order"] = [side for side, _, _ in release_order]
        result["ordering_policy"] = context["v2_policies"]["ordering"]
        result["speed_policy"] = context["v2_policies"]["speed"]
        result["effective_speeds"] = {side: _effective_speed(_active(planner_state, side), planner_state["turn"], _active(planner_state, "b" if side == "a" else "a")) for side in SIDES}
        def post_hook(name, callback):
            nonlocal current
            result["post_action_stage"] = name
            owned = deepcopy(current)
            try:
                events = callback(owned)
            except CommittedHookFailure as exc:
                current = owned
                _record_action_events(result, exc.events, current, side, index, action)
                raise
            current = owned
            _record_action_events(result, events, current, side, index, action)
            result.pop("post_action_stage", None)
        stopped_repeats = set()
        for index, (side, repeat_index, repeat_total) in enumerate(release_order):
            if side in stopped_repeats:
                continue
            if repeat_index and (_active(current, side)['member_id'] != plan['plans'][side]['actor_member_id']
                    or any(_active(current, s)['hp'] == 0 for s in SIDES)):
                stopped_repeats.add(side)
                result['events'].append({'op': 'skill.repeat_stopped', 'actor_side': side,
                    'release_index': repeat_index, 'reason': 'departed_or_exhausted'})
                continue
            if any(_active(current, s)["hp"] == 0 for s in SIDES):
                result["skipped_actions"].append(side)
                result["events"].append({"op": "research.action_skipped", "actor_side": side,
                                         "reason": "exhausted_active_or_target", "research_policy": POLICY_V2})
                continue
            action = plan["plans"][side]
            other = "b" if side == "a" else "a"
            actor = _active(current, side)
            entry_first_action = actor.get("mark_entry_actions") == 0
            interrupted = action_outcome_runtime.consume_interrupt(current, side, action)
            result['events'].extend(interrupted['events'])
            stunned = duration_runtime.skip_action(actor, current['turn'])
            if interrupted['cancelled'] or stunned['skip']:
                if action.get('program', {}).get('repeat_cast_components'):
                    stopped_repeats.add(side)
                result['skipped_actions'].append(side)
                result['events'].append({'op':'research.action_skipped','actor_side':side,
                    'actor_member_id':action['actor_member_id'], 'reason':'interrupted' if interrupted['cancelled'] else 'timed_stun'})
                continue
            if actor['member_id'] != action['actor_member_id']:
                result['skipped_actions'].append(side)
                result['events'].append({'op':'research.action_skipped', 'actor_side':side,
                    'actor_member_id':action['actor_member_id'], 'reason':'planned_member_departed',
                    'research_policy':'forced_departure_cancels_original_member_action_experiment_v1'})
                continue
            if action['kind'] == 'skill'  and 'forced_switch_components' in action['program']:
                forced_switch_programs.preflight_selection(prepared, current, side, action['skill_id'], actions[side].get('replacement_slot'), actions[side].get('opponent_replacement_slot'))
            if action["kind"] == "switch":
                switch_context = {**deepcopy(context["switches"][side]), **marks.research_context(),
                                  "mark_first_attack": index == 0}
                fragment = execute_switch_fragment(prepared, current, side, action["target_slot"],
                                                   switch_context, damage_resolver=damage_resolver)
                if fragment["status"] != "applied":
                    raise ValueError("Switch blocked: " + "; ".join(fragment["blockers"]))
                current = deepcopy(fragment["state"])
            elif action.get("execution_phase") == "charge_setup_not_attack_release":
                actor["charge"] = deepcopy(action["charge_start"])
                fragment = {"events": [{"op": "research.charge_setup", "skill_id": action["skill_id"],
                                        "skill_slot": action["slot"], "paid_cost": 0,
                                        "charge": deepcopy(actor["charge"])}]}
                actor["mark_entry_actions"] += 1
            else:
                if action["kind"] == "skill":
                    skill = prepared._rules.skill(action["skill_id"])
                    # The queued cast keeps its selected price. Automatic repeats
                    # and consume-all-energy skills retain their own source rules.
                    if repeat_index or action['program'].get('energy_burst_components'):
                        action["effective_cost"] = _resolved_cost(prepared, current, side, action["skill_id"], actions[side]["effective_cost"], current.get("weather"), slot=action.get("slot"), choice_option=actions[side].get("choice_option"))
                    else:
                        duration_runtime.check_cooldown(actor, action['skill_id'], current['turn'])
                        action['effective_cost'] = action['_selected_total_cost']
                    action.pop('health_payment', None)
                    if repeat_index and action['effective_cost'] > actor['energy']:
                        stopped_repeats.add(side)
                        result['events'].append({'op': 'skill.repeat_stopped', 'actor_side': side,
                            'actor_member_id': action['actor_member_id'], 'release_index': repeat_index,
                            'required_energy': action['effective_cost'], 'available_energy': actor['energy'],
                            'reason': 'insufficient_energy_user_confirmed'})
                        continue
                    if action['effective_cost'] > actor['energy']:
                        quote = payment_runtime.quote(prepared, actor, action['skill_id'], action['effective_cost'])
                        action['health_payment'] = quote
                        action['effective_cost'] = quote['paid_energy']
                else:
                    skill = {"kind": "recharge", "type": None}
                fragment_context = _skill_context(context, side, actor, _active(current, other), action)
                if action.get('program', {}).get('repeat_cast_components'):
                    fragment_context['repeat_cast_phase'] = {'policy': skill_extensions.POLICY,
                        'release_index': repeat_index, 'release_count': repeat_total}
                old_charge = deepcopy(actor.get('charge'))
                fragment_context["charge_program_source"] = (
                    "override" if action["skill_id"] in overrides else "raw")
                if action["skill_id"] == 7150320:
                    fragment_context["swift_release_cost"] = swift_release_runtime.swift_release_cost(
                        current, side, prepared=prepared, turn=current["turn"])
                if "team_rotation_components" in action["program"]:
                    fragment_context["battle_state"] = current
                    fragment_context["battle_side"] = side
                if 'health_payment' in action:
                    fragment_context['health_payment'] = deepcopy(action['health_payment'])
                if action['program'].get('requires_carried_cost_snapshot'):
                    fragment_context['carried_effective_skill_costs'] = _carried_cost_snapshot(prepared, current, side, actions[side], allow_partial='adjacent_power_components' in action['program'])
                if action['program'].get('requires_opponent_cost_snapshot'):
                    fragment_context['opponent_effective_skill_costs'] = _carried_cost_snapshot(prepared,current,other,{**actions[other],'actor_member_id':plan['plans'][other]['actor_member_id']})
                fragment_context.update(_trait_cost_context(prepared, current, side, {s:{**actions[s], 'actor_member_id':plan['plans'][s]['actor_member_id']} for s in SIDES}))
                opposite = plan["plans"][other]
                opposite_kind = _kind(prepared, opposite)
                responses = action["program"].get("response_kinds", defense.response_categories(action["program"]))
                if "choice_components" in action["program"]:
                    from lab.choice_runtime import response_categories as choice_responses
                    responses = choice_responses(action["program"], actions[side].get("choice_option"))
                successful = any(prepared._components()[1].counter_matches(r, opposite_kind)
                    for r in responses) if opposite_kind in ("physical", "magical", "higher", "status", "defense") else False
                opposing_member = _active(current, other)
                guard = opposing_member.get('defense_runtime', {})
                fragment_context['opponent_defended_this_attack'] = bool(
                    other in result['committed_actions'] and opposite_kind == 'defense'
                    and opposing_member.get('member_id') == opposite.get('actor_member_id')
                    and guard.get('guard_turn') == current['turn'] and guard.get('response_success')
                    and guard.get('skill_id') == opposite.get('skill_id'))
                fragment_context['opponent_defense_policy'] = 'already_committed_current_actor_guard_response_this_turn_v1'
                fragment_context.update(weather=deepcopy(current.get("weather")), weather_skill_id=action["skill_id"],
                    turn=current["turn"], response_success=successful, weather_response_success=successful,
                    action_is_later=bool(result["committed_actions"]),
                    selected_skill_slot=action.get("slot"),
                    carried_attack_skill_ids=[mid for mid in actor['skill_slots'] if mid and prepared._rules.skill(mid)['kind'] in ('physical','magical','higher')],
                    opponent_switched_this_turn=_active(current, other).get("entered_turn") == current["turn"],
                    opponent_declared_skill=opposite.get("skill_id") if opposite.get("kind") == "skill" else None,
                    opponent_declared_slot=opposite.get("slot"),
                    opponent_declared_member_id=opposite.get("actor_member_id"),
                    opponent_kind=opposite_kind, opponent_effective_cost=_opponent_cost_snapshot(prepared, current, other, opposite, actions[other], other in result["committed_actions"]),
                    skill_kind=skill["kind"],
                    skill_type=weather.resolved_skill_type(current.get("weather"), action["skill_id"], skill["type"]),
                    mark_first_action=actor["mark_entry_actions"] == 0,
                    mark_first_attack=index == 0 and skill["kind"] in ("physical", "magical", "higher"))
                if action.get('_skill_history_binding') is not None:
                    fragment_context['skill_history_power'] = skill_history_runtime.power_terms(current, action['_skill_history_binding'])
                hit_field = traits.fixed_hits(current)
                fragment_context.update(fixed_hit_count=hit_field["count"], fixed_hit_sources=hit_field["sources"], fixed_hit_policy=hit_field["policy"])
                magic_ratio = Fraction(effective_skill_power(current, side, 1))
                fragment_context['core_magic_power_multiplier'] = {'numerator': magic_ratio.numerator, 'denominator': magic_ratio.denominator}
                fragment_context['_transformation_binding'] = transformations.before_action(
                    prepared, current, side, action, opposite, fragment_context)
                if "defense_components" in action["program"]:
                    defense.preflight_departure(prepared, current, side, action["program"], opponent_kind=opposite_kind,
                        replacement_slot=actions[side].get("replacement_slot"), opponent_replacement_slot=actions[side].get("opponent_replacement_slot"))
                if 'team_target_components' in action['program']:
                    team_target_programs.preflight_targets(prepared, current, side, action['program'], context=fragment_context)
                if "mark_steal_components" in action["program"]:
                    mark_steal_runtime.preflight(prepared, current, side, action["program"], context=fragment_context)
                if "slot_components" in action["program"]:
                    fragment_context["_slot_selection_binding"] = slot_runtime.preflight_selection(prepared, current, side, action, context=fragment_context)
                attack_binding = trait_attack_hooks.prepare_attack(prepared,
                    marks.attach_relative_marks(current, side)['self'], action['program'], fragment_context,
                    token=f"{current['turn']}:{index}:{side}:manual")
                if attack_binding is not None:
                    fragment_context['combined_lifesteal_binding'] = attack_binding
                fragment = marks.execute_with_marks(action["program"], marks.attach_relative_marks(current, side),
                    fragment_context, damage_resolver=damage_resolver, execute_base=_execute_component,
                    preflight_base=_preflight_component, mark_damage_resolver=getattr(damage_resolver, "mark_damage", None))
                if fragment["status"] != "applied":
                    raise ValueError("Skill blocked: " + "; ".join(fragment["blockers"]))
                marks.commit_marks(current, side, fragment)
                if "weather" in fragment:
                    current["weather"] = fragment["weather"]
                for relative, absolute in (("self", side), ("opponent", other)):
                    team = current["teams"][absolute]
                    team["members"][team["active_slot"]] = deepcopy(fragment["state"][relative])
                _active(current, side)["mark_entry_actions"] += 1
                if action.get("execution_phase") == "charge_release_pending_execution":
                    _active(current, side)["charge"] = None
                    fragment["events"].append({"op": "research.charge_released", "paid_cost": action["effective_cost"]})
                elif old_charge is not None and (action['kind'] == 'recharge' or action.get('execution_phase') in (
                        'jealousy_release_pending_execution', 'jealousy_carried_pending_execution', 'carried_while_charging')):
                    _active(current, side)['charge'] = None
                    fragment['events'].append({'op': 'charge.abandoned', 'previous_charge': old_charge,
                        'reason': 'recharge' if action['kind'] == 'recharge' else 'successful_jealousy_alternative'})
            # A later hook cannot revoke an already applied action or its payment.
            result["committed_actions"].append(side)
            if action['kind'] == 'skill':
                # Public cast identity before any slot mutation in its effects.
                result['events'].append({'op': 'skill.committed', 'actor_side': side,
                    'actor_member_id': action['actor_member_id'],
                    'skill_id': action['skill_id'], 'skill_slot': action['slot']})
            _record_action_events(result, fragment["events"], current, side, index, action)
            if 'victory' in current:
                def retaliation_proofs(owned):
                    from lab.victory_rules import record_retaliation_defeat
                    return [proof for event in fragment['events'] if event.get('op') == 'trait.retaliation'
                            for proof in record_retaliation_defeat(owned, event)]
                post_hook('trait.retaliation.defeat', retaliation_proofs)
            if action.get('program', {}).get('repeat_cast_components'):
                owner = next(m for m in current['teams'][side]['members'] if m['member_id'] == action['actor_member_id'])
                _record_action_events(result, skill_extensions.repeat_release(owner, turn=current['turn'],
                    token=f"{current['turn']}:{index}:{side}:repeat_release"), current, side, index, action)
            def consume_action_priority(owned):
                owner = next(m for m in owned['teams'][side]['members'] if m['member_id'] == action['actor_member_id'])
                return traits.consume_priority(owner) + mechanisms.consume_priority(owner)
            post_hook('trait.priority.consume', consume_action_priority)
            post_hook('trait.action.after', lambda owned: traits.run_event(prepared, owned, 'action.after', side=side,
                member_id=action['actor_member_id'], payload={'kind':action['kind'],'first_action':entry_first_action},
                token=f"{owned['turn']}:{index}:{side}:action.after"))
            if action['kind'] == 'skill' and action.get('execution_phase') != 'charge_setup_not_attack_release':
                post_hook('action.outcomes', lambda owned: action_outcome_runtime.record_committed_action(prepared, owned, side, action, fragment['events'],
                    event_token=f"{owned['turn']}:{index}:{side}:outcomes", opponent_action=plan['plans'][other],
                    opponent_committed=other in result['committed_actions'], response_success=successful))
                post_hook('trait.direct_defeat', lambda owned: traits.after_outcome(prepared, owned, side, action, fragment['events'],
                    token=f"{owned['turn']}:{index}:{side}:outcomes", context=fragment_context))
                if action.get('_skill_history_binding') is not None:
                    post_hook('skill.history.after', lambda owned: skill_history_runtime.after_skill(prepared, owned, side, action,
                        action['_skill_history_binding'], action_token=f"{owned['turn']}:{index}:{side}:outcomes", context=fragment_context))
                if action['kind'] == 'defense' and successful:
                    post_hook('response_cost.response', lambda owned: response_cost_runtime.record_response(
                        _active(owned, side), side, turn=owned['turn'],
                        token=f"{owned['turn']}:{index}:{side}:response"))
                post_hook('skill.history.received_attack', lambda owned: skill_history_runtime.observe_received_attack(prepared, owned, other,
                    action, fragment['events'], action_token=f"{owned['turn']}:{index}:{side}:outcomes", context=fragment_context))
                post_hook('pressure.received_attack', lambda owned: pressure_runtime.observe_received_attack(prepared, owned, other,
                    action, fragment['events'], action_token=f"{owned['turn']}:{index}:{side}:outcomes",
                    context=pressure_runtime.research_context()))
                post_hook('trait.received_attack', lambda owned: traits.after_received_attack(prepared, owned, other, fragment['events'],
                    context=fragment_context, token=f"{owned['turn']}:{index}:{side}:received"))
                post_hook('trait.opponent_skill_after', lambda owned: traits.after_opponent_skill(prepared, owned, side, action['skill_id'],
                    token=f"{owned['turn']}:{index}:{side}:skill_used"))
                from lab import trait_switch_components
                post_hook('trait.slot_after_action', lambda owned: trait_switch_components.after_action(
                    prepared, owned, side, action, token=f"{owned['turn']}:{index}:{side}:slot_trait"))
                post_hook('charge.observe_attack', lambda owned: charges.observe_attack(_active(owned, other),
                    skill_id=action['skill_id'], skill_kind=skill['kind'], turn=owned['turn'],
                    events=fragment['events'], action_token=f"{owned['turn']}:{index}:{side}"))
            if (action['kind'] == 'skill' and 'adjacent_power_components' in action['program']
                    and 'neighbor_grant' in action['program']['adjacent_power_components']):
                post_hook('adjacent_power.grant', lambda owned: adjacent_power_aura_runtime.grant(
                    _active(owned, side), side, action['program']['game_id'], action.get('slot'),
                    response_success=successful, turn=owned['turn'],
                    token=f"{owned['turn']}:{index}:{side}:adjgrant"))
            if action['kind'] == 'skill' and 'adjacent_power_components' in action['program']:
                post_hook('adjacent_power.grow', lambda owned: adjacent_power_aura_runtime.record_use(
                    _active(owned, side), action['program']['game_id'], turn=owned['turn'],
                    token=f"{owned['turn']}:{index}:{side}:adjpower"))
            if action['kind'] == 'skill' and 'adjacent_cost_components' in action['program']:
                post_hook('adjacent_cost.grow', lambda owned: adjacent_cost_runtime.record_use(
                    _active(owned, side), side, action['program']['game_id'], turn=owned['turn'],
                    token=f"{owned['turn']}:{index}:{side}:adjcost"))
            if action['kind'] == 'skill' and 'response_cost_components' in action['program']:
                post_hook('response_cost.consume', lambda owned: response_cost_runtime.consume(
                    _active(owned, side), side, action['program']['game_id'],
                    token=f"{owned['turn']}:{index}:{side}:responsecost"))
            if action['kind'] == 'skill' and 'pressure_components' in action['program']:
                post_hook('pressure.install', lambda owned: pressure_runtime.install(owned, side,
                    context=pressure_runtime.research_context(), turn=owned['turn'],
                    skill_id=action['program']['game_id'], token=f"{owned['turn']}:{index}:{side}"))
            post_hook('skill.history.observe_action', lambda owned: skill_history_runtime.observe_action(prepared, owned, side, action,
                action_token=f"{owned['turn']}:{index}:{side}:outcomes",
                context={**skill_history_runtime.research_context(), 'action_is_later':len(result['committed_actions']) > 1}))
            if action["kind"] == "switch":
                departed_id = actor["member_id"]
                def cleanup(owned):
                    departed = next(m for m in owned["teams"][side]["members"] if m["member_id"] == departed_id)
                    return weather.on_departure(departed, side) + statuses_runtime.on_departure(departed, side)
                post_hook("departure.cleanup", cleanup)
            elif action.get("execution_phase") != "charge_setup_not_attack_release":
                post_hook('trait.attack.after', lambda owned: trait_attack_hooks.after_skill(prepared, owned, side,
                    action['program'], fragment['events'], attack_binding, context=fragment_context))
                post_hook("transformation.after_action", lambda owned: transformations.after_action(
                    prepared, owned, side, action, opposite, fragment_context, fragment))
                if 'slot_components' in action['program']:
                    post_hook('skill.slot_movement', lambda owned: slot_runtime.after_skill(prepared, owned, side, action,
                        event_token=f"{owned['turn']}:{index}:{side}:slots", context=fragment_context))
            if action["kind"] == "skill" and action.get("execution_phase") != "charge_setup_not_attack_release":
                post_hook("weather.after_skill", lambda owned: weather.after_skill(owned.get("weather"), action["skill_id"],
                    _active(owned, side), _active(owned, other), fragment["events"], side=side,
                    type_multiplier=type_ratio, skill_type=prepared._rules.skill(action["skill_id"])["type"], turn=owned["turn"]))
            if action.get("execution_phase") == "charge_setup_not_attack_release":
                post_hook("trait.charge.start", lambda owned: traits.run_event(prepared, owned, "charge.start", side=side))
            elif action["kind"] == "skill":
                post_hook('trait.hits.after', lambda owned: mechanisms.after_skill_hits(prepared, owned, side,
                    action['skill_id'], token=f"{owned['turn']}:{index}:{side}:manual"))
                trait_payload = {**prepared._rules.skill(action["skill_id"]), "response_success": successful, "entry_first_action":fragment_context["mark_first_action"]}
                post_hook("trait.skill.after", lambda owned: traits.run_event(prepared, owned, "skill.after", side=side,
                    payload=trait_payload, token=f"{owned['turn']}:{index}:manual"))

                def swift_after(owned):
                    events, queued = swift_release_runtime.observe_after_skill(
                        owned, side, action['skill_id'], prepared=prepared, turn=owned['turn'])
                    for release in queued:
                        swift_release_runtime.pending_queue(owned, side).append(
                            {"skill_id": release, "kind": "auto"})
                    return events

                post_hook('swift.after', swift_after)
            post_hook("freeze.after_action", lambda owned: [event for affected_side in SIDES
                for event in weather.check_freeze(_active(owned, affected_side), affected_side)])
            if action['kind'] == 'skill' and 'mark_steal_components' in action['program']:
                post_hook('skill.mark_steal', lambda owned: mark_steal_runtime.after_skill(prepared, owned, side, action['program'],
                    event_token=f"{owned['turn']}:{index}:{side}:steal", context=fragment_context))
            if action['kind'] == 'skill' and 'team_target_components' in action['program']:
                def team_effect(owned):
                    applied = team_target_programs.after_skill(prepared, owned, side, action['program'],
                        event_token=f"{owned['turn']}:{index}:{side}:team", context=fragment_context)
                    if applied['status'] != 'applied':
                        raise ValueError('Team target hook blocked: ' + '; '.join(applied['blockers']))
                    owned.clear(); owned.update(applied['state'])
                    return applied['events']
                post_hook('skill.team_targets', team_effect)
            if action['kind'] == 'skill' and 'choice_components' in action['program']:
                post_hook('skill.choice.after', lambda owned: choice_runtime.after_skill(prepared,owned,side,action,fragment['events'],context=fragment_context,event_token=f"{owned['turn']}:{index}:{side}:choice"))
            if action['kind'] == 'skill' and 'random_devotion_components' in action['program']:
                sampled = random_devotion_runtime.apply(current, side, source_id=action['skill_id'], context=fragment_context)
                current = sampled['state']
                _record_action_events(result, sampled['events'], current, side, index, action)
                if sampled['status'] != 'applied':
                    raise ValueError('Original random devotion draw blocked: ' + '; '.join(sampled['blockers']))
            post_hook('trait.faint', lambda owned: _reconcile_faint_traits(prepared, owned))
            if action['kind'] == 'skill' and action['program'].get('defense_components', {}).get('departure'):
                def defense_departure(owned):
                    applied = defense.after_defense(prepared, owned, side, action['program'], opponent_kind=opposite_kind,
                        replacement_slot=actions[side].get('replacement_slot'), opponent_replacement_slot=actions[side].get('opponent_replacement_slot'),
                        context={**marks.research_context(), 'defense_departure_policy': defense.DEPARTURE_POLICY},
                        event_token=f"{owned['turn']}:{index}:{side}:defense")
                    if applied['status'] != 'applied':
                        if applied.get('partial_commit'):
                            owned.clear(); owned.update(applied['state'])
                            raise CommittedHookFailure('Defense departure blocked after committed departure: ' + '; '.join(applied['blockers']), applied['events'])
                        raise ValueError('Defense departure blocked: ' + '; '.join(applied['blockers']))
                    owned.clear(); owned.update(applied['state'])
                    return applied['events']
                post_hook('defense.departure', defense_departure)
            if action['kind'] == 'skill' and 'forced_switch_components' in action['program'] and _active(current, side)['hp'] > 0:
                def detach_after_skill(owned):
                    fragment = forced_switch_programs.after_skill(prepared, owned, side, action['skill_id'],
                        replacement_slot=actions[side].get('replacement_slot'), opponent_replacement_slot=actions[side].get('opponent_replacement_slot'),
                        event_token=f"{owned['turn']}:{index}:{side}:skill", context={**marks.research_context(), "response_success":successful, "random_seed":_devotion_seed(owned)})
                    if fragment['status'] != 'applied':
                        if fragment.get('partial_commit'):
                            owned.clear(); owned.update(fragment['state'])
                            raise CommittedHookFailure('Forced-switch hook blocked after committed departure: ' + '; '.join(fragment['blockers']), fragment['events'])
                        raise ValueError('Forced-switch hook blocked: ' + '; '.join(fragment['blockers']))
                    owned.clear(); owned.update(fragment['state'])
                    return fragment['events']
                post_hook('skill.forced_switch', detach_after_skill)
            if action['kind'] != 'switch':
                def departure_trait(owned):
                    fragment = forced_trait_runtime.after_action(prepared, owned, side, action,
                        replacement_slot=actions[side].get('replacement_slot'), context=marks.research_context())
                    if fragment['status'] != 'applied':
                        raise ValueError('Departure trait blocked: ' + '; '.join(fragment['blockers']))
                    owned.clear(); owned.update(fragment['state'])
                    return fragment['events']
                post_hook('trait.departure', departure_trait)
            result["events"].extend(_reconcile_faint_traits(prepared, current))
            if terminal(current)["terminal"]:
                _finish_v2(result, current, advance=False, policy=POLICY_V2)
                return result
        for side in SIDES:
            while swift_release_runtime.pending_queue(current, side):
                release = swift_release_runtime.pending_queue(current, side).pop(0)
                sid = release["skill_id"]
                other = "b" if side == "a" else "a"
                if _active(current, side)["hp"] == 0 or _active(current, other)["hp"] == 0:
                    result["events"].append({"op": "research.swift_release_skipped", "actor_side": side,
                                             "skill_id": sid, "reason": "exhausted", "research_policy": POLICY_V2})
                    break
                program = overrides.get(sid, prepared._rules.program(sid))
                if program.get("status") != "compiled":
                    result["events"].append({"op": "research.swift_release_skipped", "actor_side": side,
                                             "skill_id": sid, "reason": "not_compiled",
                                             "research_policy": POLICY_V2})
                    continue
                program = {**deepcopy(program),
                           "swift_release_components": deepcopy(swift_release_runtime._data()["skills"][str(sid)])}
                act = {"kind": "skill", "skill_id": sid, "slot": 0, "effective_cost": 0,
                       "effective_priority": 0,
                       "actor_member_id": _active(current, side)["member_id"], "program": program}
                fragment_context = _fragment(program, _devotion_seed(current))
                fragment_context.update(resolved_energy_cost=0, selected_skill_slot=None, turn=current["turn"],
                                        response_success=False, weather_response_success=False,
                                        action_is_later=True, opponent_kind="status",
                                        weather=deepcopy(current.get("weather")), weather_skill_id=sid,
                                        swift_auto_release=release.get("kind") == "auto")
                ctx = fragment_context
                fragment = marks.execute_with_marks(program, marks.attach_relative_marks(current, side), ctx,
                    damage_resolver=damage_resolver, execute_base=_execute_component, preflight_base=_preflight_component)
                if fragment["status"] != "applied":
                    raise ValueError("Swift release blocked: " + "; ".join(fragment["blockers"]))
                marks.commit_marks(current, side, fragment)
                current["teams"][side]["members"][current["teams"][side]["active_slot"]] = fragment["state"]["self"]
                current["teams"][other]["members"][current["teams"][other]["active_slot"]] = fragment["state"]["opponent"]
                result["events"].extend({**deepcopy(event), "actor_side": side,
                                         "action_index": len(result["committed_actions"]),
                                         "research_policy": POLICY_V2, "swift_release": True}
                                        for event in fragment["events"])
                result["committed_actions"].append(f"{side}:swift:{sid}")

        status_context = deepcopy(context["status_context"])
        schedule = [{"side": side, "status": status} for side in SIDES
                    if _active(current, side)["hp"] > 0 for status in ("poison", "burn", "leech")
                    if _active(current, side)["statuses"].get(status, 0) > 0]
        if "schedule" in status_context and status_context["schedule"] != schedule:
            raise ValueError("Submitted status schedule conflicts with fixed v2 experimental order")
        status_context["schedule"] = schedule
        if status_context.get("faint_policy") != STATUS_FAINT:
            raise ValueError("Explicit v2 status faint policy required")
        ticks = execute_status_phase(prepared, current, status_context, damage_resolver=status_damage_resolver)
        if ticks["status"] != "applied":
            raise ValueError("End status phase blocked after committed actions: " + "; ".join(ticks["blockers"]))
        current = deepcopy(ticks["state"])
        result["events"].extend({**deepcopy(event), "research_policy": POLICY_V2} for event in ticks["events"])
        result["status_phase_executed"] = True
        result["events"].extend(_reconcile_faint_traits(prepared, current))
        if terminal(current)["terminal"]:
            _finish_v2(result, current, advance=False, policy=POLICY_V2)
            return result
        for side in SIDES:
            marked = marks.apply_battle_phase(current, side, "round_end", context=marks.research_context())
            if marked["status"] != "applied":
                raise ValueError("End mark phase blocked: " + "; ".join(marked["blockers"]))
            current = marked["state"]
            result["events"].extend(marked["events"])
        result["mark_phase_executed"] = True
        result["events"].extend(_reconcile_faint_traits(prepared, current))
        if terminal(current)["terminal"]:
            _finish_v2(result, current, advance=False, policy=POLICY_V2)
            return result
        for side in SIDES:
            result["events"].extend(weather.check_freeze(_active(current, side), side))
        active_members = {side: _active(current, side) for side in SIDES}
        next_weather, updated, weather_events = weather.advance_weather(current.get("weather"), active_members,
            current["turn"], apply_effects=True, type_multiplier=type_ratio)
        if "weather" in current or next_weather is not None:
            current["weather"] = next_weather
        for side, member in updated.items():
            team = current["teams"][side]
            team["members"][team["active_slot"]] = member
        result["events"].extend(weather_events)
        result["events"].extend(_reconcile_faint_traits(prepared, current))
        result["weather_phase_executed"] = True
        result["weather_policy"] = weather.POLICY
        result["weather_numeric_policy"] = weather.NUMERIC_POLICY
        result["weather_uncertainties"] = deepcopy(weather.rules()["uncertainties"])
        for side in SIDES:
            for member in current["teams"][side]["members"]:
                if member["hp"] == 0 and member["charge"] is not None:
                    member["charge"] = None
                    result["events"].append({"op": "research.charge_cancelled", "member_id": member["member_id"],
                                             "reason": "exhaustion", "research_policy": POLICY_V2})
        result["events"].extend(skill_history_runtime.round_end(prepared, current))
        result["events"].extend(mark_steal_runtime.round_end(prepared, current, context={**marks.research_context(), **mark_steal_runtime.research_context()}))
        result["events"].extend(traits.run_event(prepared, current, "turn.end",
            token=f"{current['turn']}:turn.end",
            context=random_devotion_runtime.research_context(_devotion_seed(current))))
        returned = defense.end_round_departures(prepared, current, context={**marks.research_context(),
            'defense_end_return_policy':defense.END_RETURN_POLICY, 'random_seed':_devotion_seed(current)})
        current = returned['state']
        result['events'].extend(returned['events'])
        if returned['status'] != 'applied':
            raise ValueError('End defense return blocked: ' + '; '.join(returned['blockers']))
        result['events'].extend(_reconcile_faint_traits(prepared, current))
        forced_end = forced_trait_runtime.end_round(prepared, current, context=marks.research_context())
        current = forced_end['state']
        result['events'].extend(forced_end['events'])
        if forced_end['status'] != 'applied':
            raise ValueError('End departure trait blocked: ' + '; '.join(forced_end['blockers']))
        result["events"].extend(mechanisms.end_turn(current))
        for team in current["teams"].values():
            team["members"] = [defense.finish_turn(m, current["turn"]) for m in team["members"]]
        _finish_v2(result, current, policy=POLICY_V2)
    except Exception as exc:
        result["status"] = "blocked"
        result["blockers"] = [str(exc)]
        if result["committed_actions"]:
            current["research_battle"] = {"policy": POLICY_V2, "phase": "blocked", "turn_pending": True,
                                         "pending_replacements": _pending(current), "winner": None}
            result.update(state=deepcopy(current), pending_replacements=_pending(current))
    return result


def choose_research_replacements_v2(catalog, state, selections, context):
    """Manual replacements do not rerun completed status ticks or entry Swift."""
    result = _result(state, policy=POLICY_V2, unresolved=UNRESOLVED_V2)
    current = deepcopy(state)
    try:
        _context(context)
        prepared = prepare_rules(catalog)
        _validate(prepared, current, status_lifecycle_policy=statuses_runtime.POLICY)
        if "core_magic_runtime" in current:
            validate_core_magic(current)
        traits.bind(prepared, current)
        weather.validate_weather_members(current)
        for side, team in current["teams"].items():
            for member in team["members"]:
                statuses_runtime.validate_lifecycles(member)
                if member["statuses"].get("leech", 0):
                    statuses_runtime.validate_leech_binding(member, side, current)
                mechanisms.validate_member(member)
        for team in current["teams"].values():
            for member in team["members"]:
                member["weather_trait_id"] = prepared._rules.form(member["form_id"]).get("trait_id")
        lifecycle, pending = current.get("research_battle"), _pending(current)
        if (not isinstance(lifecycle, dict) or lifecycle.get("policy") != POLICY_V2
                or lifecycle.get("phase") != "awaiting_replacement" or not pending
                or lifecycle.get("pending_replacements") != pending
                or type(lifecycle.get("turn_pending")) is not bool or _outcome(current) is not None):
            raise ValueError("No matching v2 manual replacement phase")
        if not isinstance(selections, dict) or set(selections) != set(pending):
            raise ValueError("Choose exactly all pending replacement sides")
        for side, slot in selections.items():
            if type(slot) is not int or slot not in pending[side]:
                raise ValueError("Replacement must be a surviving reserve slot")
        for side in SIDES:
            if side not in selections:
                continue
            slot = selections[side]
            team = current["teams"][side]
            previous = team["active_slot"]
            result["events"].extend(skill_history_runtime.on_departure(prepared, current, side, team["members"][previous]["member_id"], event_token=f"{current['turn']}:replacement:{side}:leave"))
            team = current["teams"][side]
            result["events"].extend(on_core_magic_departure(current, side, team["members"][previous]['member_id']))
            result["events"].extend(skill_extensions.clear_per_type_power(current, team["members"][previous]["member_id"]))
            result["events"].extend(weather.on_departure(team["members"][previous], side))
            result["events"].extend(statuses_runtime.on_departure(team["members"][previous], side))
            result['events'].extend(traits.run_event(prepared, current, 'member.leave', side=side,
                member_id=team['members'][previous]['member_id'], token=f"{current['turn']}:replacement:{side}:{previous}:leave"))
            team = current['teams'][side]
            team["active_slot"] = slot
            team["members"][slot]["entered_turn"] = current["turn"]
            from lab import trait_switch_components
            result['events'].extend(trait_switch_components.after_switch(prepared, current, side,
                team['members'][previous]['member_id'], team['members'][slot]['member_id'],
                token=f"{current['turn']}:replacement:{side}:{previous}:{slot}:trait_switch"))
            result['events'].extend(trait_attack_hooks.on_entry(prepared, current, side))
            team["members"][slot]["mark_entry_actions"] = 0
            result["events"].extend(skill_history_runtime.on_entry(prepared, current, side, event_token=f"{current['turn']}:replacement:{side}:{slot}"))
            marked = marks.apply_battle_phase(current, side, "after_switch", context=marks.research_context())
            if marked["status"] != "applied":
                raise ValueError("Replacement mark phase blocked: " + "; ".join(marked["blockers"]))
            current = marked["state"]
            result["events"].extend(marked["events"])
            result["events"].extend(traits.run_event(prepared, current, "member.enter", side=side,
                token=f"{current['turn']}:replacement:{side}:{slot}"))
            result["events"].append({"op": "research.manual_replacement", "side": side, "order_policy":"replacement_a_then_b_experiment",
                                     "before_slot": previous, "after_slot": slot, "policy": POLICY_V2})
        _finish_v2(result, current, advance=lifecycle["turn_pending"], policy=POLICY_V2)
    except Exception as exc:
        result["blockers"] = [str(exc)]
    return result
