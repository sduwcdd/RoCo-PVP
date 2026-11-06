"""An isolated, source-bound voluntary position-change experiment.

This is not a complete switch or turn. Entry/exit hooks, cleanup and external
Swift grants require reviewed source traits. A selected Swift skill goes through
the common skill dispatcher with its explicit policies and effect dependencies.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction

from lab.effect_runtime import HOOKS, _state
from lab.prepared_rules import PreparedRules, prepare_rules
from lab.ruleset import canonical_hash
from lab.turn_plan import SIDES, _validate_state
from lab import mark_runtime as marks
from lab import action_traits


ENTRY_SWIFT_RESPONSE_POLICY = "entry_swift_without_committed_opponent_action_no_response_experiment"


UNRESOLVED = [
    "Retaining member fields on departure is an explicit experiment, not verified game cleanup.",
    "Swift includes reviewed source trait grants only under their named policy; other external grants remain unsupported.",
    "Field mark effects require the named mark policy; entry trait/mark/Swift order is an uncalibrated experiment.",
    "Skill ID presence does not establish learnset, bloodline, level or team-configuration legality.",
    "This single position change does not determine joint action order, resource regeneration, replacement or victory.",
]


def _active(state, side):
    team = state["teams"][side]
    return team["members"][team["active_slot"]]


def _typed_actor(rules, actor):
    types = rules.form(actor["form_id"])["types"]
    if "types" in actor and actor["types"] != types:
        raise ValueError("Member types conflict with the exact BWIKI form; transformation rules are unresolved")
    return {**deepcopy(actor), "types": deepcopy(types)}


def entry_swift_candidates(prepared, state, incoming, costs, *, include_trait_grants=True):
    """Quote HP conversion without making an unaffordable source skill free."""
    from lab import payment_runtime as payment
    candidates = action_traits.swift_candidates(prepared, state, incoming, costs,
        include_trait_grants=include_trait_grants)
    from lab.turn_plan import charge_admission
    for slot, candidate in enumerate(candidates):
        if candidate is not None and candidate['swift'] is True:
            candidate['charge_admission'] = charge_admission(prepared, incoming, candidate['skill_id'],
                slot=slot, turn=state['turn'])
        if (candidate is None or candidate['swift'] is False or candidate['effective_cost'] is None
                or candidate['effective_cost'] <= incoming['energy']):
            continue
        try:
            quote = payment.quote(prepared, incoming, candidate['skill_id'], candidate['effective_cost'])
        except ValueError as exc:
            if not str(exc).startswith(('Insufficient energy; no reviewed', 'Lethal or unaffordable',
                                        'Rounded zero health cost')):
                raise
            candidate['health_payment_blocker'] = str(exc)
            continue
        candidate['health_payment'] = quote
        candidate['total_effective_cost'] = candidate['effective_cost']
        candidate['effective_cost'] = quote['paid_energy']
    return candidates


def execute_switch_fragment(catalog, state, side, target_slot, context, *, damage_resolver=None):
    """Change one active slot only under explicit isolated policies.

    ``context`` binds snapshot/catalog, excludes all HOOKS, declares no unresolved
    isolated dependencies, and supplies ``cleanup_policy`` equal to
    ``retain_member_fields_experiment`` and ``swift_policy`` equal to
    ``intrinsic_source_only_experiment`` or the reviewed trait Swift policy.
    ``incoming_effective_costs`` retains
    four ordered int/None entries; empty skill slots require None.

    Source-derived intrinsic/trait Swift metadata is used instead of supplied
    member.swift_candidates. A selected compiled Swift skill requires
    entry_timing=after_position_change_experiment and entry_skill_context using
    the isolated skill contract. Other selected/unresolved skills still block.
    Known unaffordable Swift is not executed. Without an entry skill the only
    edits are active_slot and entered_turn. Entry cost/damage are atomic with
    those changes. An incomplete candidate is not committed locally; this is
    not a claim that the live game undoes an already committed switch.
    The optional named faint_policy=stop_remaining_skill_on_exhaustion_experiment
    lets research v2 commit exhaustion and defer replacement to its outer loop;
    absent that opt-in, the original strict rollback behavior is unchanged.
    """
    result = {
        "status": "blocked", "scope": "isolated_voluntary_switch_experiment",
        "state": deepcopy(state), "events": [], "blockers": [],
        "snapshot_id": catalog.snapshot_id if isinstance(catalog, PreparedRules)
        else catalog.get("snapshot_id") if isinstance(catalog, dict) else None,
        "state_hash": None, "context_hash": None, "catalog_hash": None,
        "final_state_hash": None, "entry_swift": None,
        "switch_fragment_executed": False, "entry_skill_executed": False, "full_switch_executed": False,
        "full_turn_executed": False, "battle_executable": False,
        "calibrated": False, "real_game_verified": False, "training_eligible": False,
        "input_state_mutated": False, "unresolved": deepcopy(UNRESOLVED),
    }
    try:
        result.update(state_hash=canonical_hash(state), context_hash=canonical_hash(context))
        context = deepcopy(context)
        allow_faint = context.get("faint_policy") == "stop_remaining_skill_on_exhaustion_experiment"
        if "faint_policy" in context and not allow_faint:
            raise ValueError("Unknown switch faint policy")
        prepared = prepare_rules(catalog)
        rules, phases, switches = prepared._components()
        result["catalog_hash"] = rules.catalog_content_hash
        if not isinstance(context, dict) or context.get("mode") != "isolated_voluntary_switch_experiment":
            raise ValueError("An isolated voluntary-switch experiment must be explicitly requested")
        if context.get("snapshot_id") != rules.snapshot_id or context.get("catalog_content_hash") != rules.catalog_content_hash:
            raise ValueError("Switch experiment must bind both snapshot and catalog content hash")
        if context.get("cleanup_policy") != "retain_member_fields_experiment":
            raise ValueError("Departure cleanup is unresolved; explicit member-field retention experiment required")
        if context.get("swift_policy") not in ("intrinsic_source_only_experiment", action_traits.SWIFT_POLICY):
            raise ValueError("Swift requires an explicit intrinsic or reviewed-trait experiment policy")
        excluded = context.get("excluded_hooks")
        if (not isinstance(excluded, list) or len(excluded) != len(HOOKS)
                or any(not isinstance(x, str) for x in excluded) or set(excluded) != HOOKS):
            raise ValueError("All trait, field, mark, bloodline and event hooks must be explicitly excluded")
        if context.get("unresolved_dependencies") != []:
            raise ValueError("Isolated dependency list must be explicit and empty")
        if not isinstance(side, str) or side not in SIDES:
            raise ValueError("Switch side must be a or b")
        if type(target_slot) is not int or target_slot < 0:
            raise ValueError("Switch target must be a nonnegative integer slot")

        current = deepcopy(state)
        _validate_state(rules, phases, current)
        from lab import trait_runtime
        trait_runtime.bind(prepared, current)
        team = current["teams"][side]
        old_slot = team["active_slot"]
        if target_slot >= len(team["members"]) or target_slot == old_slot:
            raise ValueError("Voluntary switch must select another existing member of the same team")
        outgoing, incoming = team["members"][old_slot], team["members"][target_slot]
        opponent = _active(current, "b" if side == "a" else "a")
        switch_cooldown = context.get("switch_cooldown")
        if "switch_cooldown" in context:
            if not isinstance(switch_cooldown, dict):
                raise ValueError("switch_cooldown must be an object")
            cooldown = deepcopy(switch_cooldown)
            if "state_info" in cooldown:
                info = cooldown["state_info"]
                if not isinstance(info, dict):
                    raise ValueError("switch state_info must be an object")
                for raw, normalized in (("round", "current_round"),
                                        ("last_change_pet_round", "last_change_round_index")):
                    if raw in info:
                        value = info[raw]
                        if value is not None and (type(value) is not int or value < 0):
                            raise ValueError("Invalid switch state_info field: " + raw)
                        if normalized in cooldown and cooldown[normalized] != value:
                            raise ValueError("switch state_info conflicts with " + normalized)
                        cooldown[normalized] = value
            if cooldown.get("current_round") is not None and cooldown["current_round"] != current["turn"]:
                raise ValueError("switch current_round conflicts with battle turn")
            if "last_change_round_index" not in cooldown and "last_change_pet_round_index" in team:
                cooldown["last_change_round_index"] = team["last_change_pet_round_index"]
            if "battle_inside_pet_info" in cooldown:
                source_ban = switches.change_pet_banned(cooldown["battle_inside_pet_info"])
                override = cooldown.get("ban_change_pet")
                if override is not None and (type(override) is not bool or override != source_ban):
                    raise ValueError("ban_change_pet conflicts with packed client state_bits")
                cooldown["ban_change_pet"] = source_ban
            elif cooldown.get("ban_change_pet") is None:
                cooldown.pop("ban_change_pet", None)
            eligibility = switches.change_eligibility(**{
                key: cooldown[key] for key in (
                    "current_round", "exchange_initial_cold", "exchange_cold",
                    "last_change_round_index", "can_changepet", "ban_change_pet")
                if key in cooldown})
            result["switch_cooldown"] = deepcopy(eligibility)
            if eligibility["status"] != "allowed":
                raise ValueError("Voluntary switch rejected: " + eligibility["reason"])
        for actor in (outgoing, incoming, opponent):
            # Reuse the resource/status schema for every participant, including
            # the incoming bench member that ordinary active-only validation misses.
            typed = _typed_actor(rules, actor)
            _state({"self": typed, "opponent": typed})
            if actor["hp"] == 0:
                raise ValueError("Exhaustion requires a replacement/trigger phase, not an ordinary voluntary switch")
            if context.get("status_lifecycle_policy") != "source_bound_freeze_leech_lifecycle_v1" and any(actor["statuses"].get(status, 0) > 0 for status in ("freeze", "leech")):
                raise ValueError("Existing freeze/leech needs unresolved threshold/source binding before switching")
        if incoming["charge"] is not None:
            raise ValueError("Incoming charged reserve requires its separate cancellation/entry rule")
        departure = switches.departure("voluntary", outgoing["entered_turn"], current["turn"],
                                       outgoing["charge"] is not None, outgoing["rooted"])
        if departure["status"] != "allowed":
            raise ValueError("Voluntary departure rejected: " + departure["reason"])
        inherited = switches.transfer_field_marks(team.get("marks"))
        entry_selection_state = trait_runtime.preview_entry_history(current, side, target_slot)
        entry_selection_view = _active(entry_selection_state, side)
        candidates = entry_swift_candidates(prepared, entry_selection_state, entry_selection_view,
            context.get("incoming_effective_costs"),
            include_trait_grants=context["swift_policy"] == action_traits.SWIFT_POLICY)
        swift = switches.swift_first_slot(candidates, entry_selection_view["energy"])
        result["entry_swift"] = deepcopy(swift)
        entry_program, entry_context = None, None
        mark_enabled = context.get("mark_policies") == marks.research_context()["mark_policies"]
        if swift["status"] == "unresolved":
            raise ValueError("Entry Swift is unresolved; local switch candidate is not committed")
        if swift["status"] == "selected" and not mark_enabled:
            from lab.runtime_programs import reviewed_programs
            entry_program = reviewed_programs(prepared).get(swift["skill_id"]) or rules.program(swift["skill_id"])
            if not action_traits.entry_program_has_swift(entry_program, candidates[swift["slot"]]):
                raise ValueError("First selected Swift does not have a supported complete skill program; cannot skip to a later slot")
            if context.get("entry_timing") != "after_position_change_experiment":
                raise ValueError("Entry skill timing must explicitly select after_position_change_experiment")
            if not isinstance(context.get("entry_skill_context"), dict):
                raise ValueError("Selected Swift requires its complete isolated entry_skill_context")
            entry_context = deepcopy(context["entry_skill_context"])
            cost = swift["effective_cost"]
            if "resolved_energy_cost" in entry_context and (
                    type(entry_context["resolved_energy_cost"]) is not int
                    or entry_context["resolved_energy_cost"] != cost):
                raise ValueError("Entry skill cost conflicts with source-ordered selected effective cost")
            entry_context.update(resolved_energy_cost=cost, actor_side=side,
                                 actor_member_id=incoming["member_id"],
                                 opponent_member_id=opponent["member_id"],
                                 entry_origin="voluntary_switch", skill_slot=swift["slot"])
            admission = candidates[swift['slot']].get('charge_admission', {})
            if admission.get('execution_phase') == 'charge_setup_not_attack_release':
                raise ValueError('Entry Swift charge setup timing remains unresolved; no release payload executed')
            entry_context.update(deepcopy(admission))
            if allow_faint:
                entry_context["faint_policy"] = context["faint_policy"]
        elif swift["status"] not in ("none", "selected"):
            raise ValueError("Unknown entry Swift selection result")

        inheritance_grant, inheritance_events = None, []
        inheritance_request = context.get('buff_inheritance')
        if inheritance_request is not None:
            if not isinstance(inheritance_request, dict):
                raise ValueError('Buff inheritance requires a source-bound server-owned request')
            from lab.modifier_ledger import prepare_inheritance
            inheritance = prepare_inheritance(outgoing,
                source_skill_id=inheritance_request.get('source_skill_id'),
                source_hash=inheritance_request.get('source_hash'), token=inheritance_request.get('token'))
            team['members'][old_slot] = inheritance['departing_member']
            outgoing = team['members'][old_slot]
            inheritance_grant = inheritance['grant']
            inheritance_events += [{**e, 'actor_side': side, 'actor_member_id': outgoing['member_id'],
                'target_side': side, 'target_member_id': outgoing['member_id'],
                'source_skill_id': inheritance_grant['source_skill_id'], 'source_hash': inheritance_grant['source_hash']}
                for e in inheritance['events']]
        # Unrelated fields remain intact; explicit source inheritance moves BUFFs.
        abandoned_charge = deepcopy(outgoing["charge"])
        if abandoned_charge is not None:
            outgoing["charge"] = None
        team["active_slot"] = target_slot
        if outgoing.get('timed_effects'):
            from lab.duration_runtime import depart
            outgoing.update(depart(outgoing))
        if outgoing.get('skill_attack_grants'):
            from lab.attack_grant_runtime import depart as depart_grants
            outgoing.update(depart_grants(outgoing))
        incoming["entered_turn"] = current["turn"]
        if mark_enabled:
            incoming["mark_entry_actions"] = 0
        if inheritance_grant is not None:
            from lab.modifier_ledger import apply_inheritance
            inheritance_events += [{**e, 'actor_side': side, 'actor_member_id': outgoing['member_id'],
                'target_side': side, 'source_skill_id': inheritance_grant['source_skill_id'],
                'source_hash': inheritance_grant['source_hash']}
                for e in apply_inheritance(incoming, inheritance_grant)]
        event = {
            "op": "switch.voluntary", "side": side, "from_slot": old_slot, "to_slot": target_slot,
            "departing_member_id": outgoing["member_id"], "entering_member_id": incoming["member_id"],
            "entered_turn_before": state["teams"][side]["members"][target_slot]["entered_turn"],
            "entered_turn_after": current["turn"], "departure": deepcopy(departure),
            "inherited_marks": deepcopy(inherited), "entry_swift": deepcopy(swift),
            "swift_candidates": deepcopy(candidates), "cleanup_policy": context["cleanup_policy"],
            "snapshot_id": rules.snapshot_id, "catalog_hash": rules.catalog_content_hash,
            "real_game_verified": False, "full_switch_executed": False,
        }
        if switch_cooldown is not None:
            event["switch_cooldown"] = deepcopy(result["switch_cooldown"])
        events = [event, *inheritance_events]
        if abandoned_charge is not None:
            events.append({'op': 'charge.abandoned', 'actor_side': side,
                'actor_member_id': outgoing['member_id'], 'charge': abandoned_charge,
                'reason': 'voluntary_switch', 'source': 'user_confirmation_20261030'})
        from lab import skill_history_runtime as history
        events.extend(history.on_departure(prepared, current, side, outgoing['member_id'],
            event_token=f"{current['turn']}:voluntary:{side}:{old_slot}:history.leave"))
        from lab.user_skill_extensions import repeat_departure
        if 'repeat_cast_history' in outgoing or 7110380 in outgoing['skill_slots']:
            events.extend(repeat_departure(outgoing, turn=current['turn'],
                token=f"{current['turn']}:voluntary:{side}:{old_slot}:repeat.leave"))
        from lab.user_skill_extensions import clear_per_type_power
        events.extend(clear_per_type_power(current, outgoing["member_id"]))
        from lab.core_magic_runtime import on_core_magic_departure
        events.extend(on_core_magic_departure(current, side, outgoing["member_id"]))
        from lab import trait_switch_components
        events.extend(trait_switch_components.after_switch(prepared, current, side,
            outgoing['member_id'], incoming['member_id'], token=context.get('event_token') or
            f"{current['turn']}:voluntary:{side}:{old_slot}:{target_slot}:switch_traits:{len(current.get('trait_switch_receipts', {}))}"))
        events.extend(trait_runtime.run_event(prepared, current, "member.leave", side=side,
            member_id=outgoing["member_id"], token=f"{current['turn']}:leave:{side}:{old_slot}"))
        events.extend(trait_runtime.run_event(prepared, current, "member.enter", side=side,
            token=f"{current['turn']}:enter:{side}:{target_slot}"))
        from lab import trait_attack_hooks
        events.extend(trait_attack_hooks.on_entry(prepared, current, side))
        events.extend(history.on_entry(prepared, current, side,
            event_token=f"{current['turn']}:voluntary:{side}:{target_slot}:history.enter"))
        if mark_enabled:
            actors = marks.attach_relative_marks(current, side)
            for key in actors:
                actors[key] = _typed_actor(rules, actors[key])
            phase = marks.mark_phase(actors, "after_switch", context=context)
            if phase["status"] != "applied":
                raise ValueError("Entry marks blocked: " + "; ".join(phase["blockers"]))
            marks.commit_marks(current, side, phase)
            for key, absolute in (("self", side), ("opponent", "b" if side == "a" else "a")):
                target_team = current["teams"][absolute]
                updated = phase["state"][key]
                if "types" not in _active(current, absolute):
                    updated.pop("types", None)
                target_team["members"][target_team["active_slot"]] = updated
            events.extend(phase["events"])
        team = current["teams"][side]
        incoming, opponent = team["members"][target_slot], _active(current, "b" if side == "a" else "a")
        if incoming["hp"] > 0:
            # Entry energy marks can change which ordered Swift slot is affordable.
            candidates = entry_swift_candidates(prepared, current, incoming,
                context.get("incoming_effective_costs"),
                include_trait_grants=context["swift_policy"] == action_traits.SWIFT_POLICY)
            selected = switches.swift_first_slot(candidates, incoming["energy"])
            if selected != swift:
                swift = selected
                result["entry_swift"] = deepcopy(swift)
                events.append({"op": "entry_swift.reselected", "selection": deepcopy(swift),
                    "policy": "after_entry_marks_affordability_experiment"})
            if swift["status"] == "none":
                entry_program = None
            elif swift["status"] == "selected":
                from lab.runtime_programs import reviewed_programs
                from lab.research_phases import _fragment
                if mark_enabled:
                    entry_program = reviewed_programs(prepared).get(swift["skill_id"]) or rules.program(swift["skill_id"])
                elif entry_program is None or entry_program.get('game_id') != swift['skill_id']:
                    entry_program = reviewed_programs(prepared).get(swift['skill_id']) or rules.program(swift['skill_id'])
                if not action_traits.entry_program_has_swift(entry_program, candidates[swift["slot"]]):
                    raise ValueError("After entry marks the first affordable Swift has no complete reviewed program")
                if context.get("entry_timing") != "after_position_change_experiment":
                    raise ValueError("Entry skill timing must explicitly select after_position_change_experiment")
                entry_context = {**(context.get("entry_skill_context") or {}),
                    **(_fragment(entry_program, context.get("random_devotion_seed", 0)) if mark_enabled else {}),
                    "resolved_energy_cost": swift["effective_cost"], "actor_side": side,
                    "actor_member_id": incoming["member_id"], "opponent_member_id": opponent["member_id"],
                    "entry_origin": "voluntary_switch", "skill_slot": swift["slot"]}
                if allow_faint:
                    entry_context["faint_policy"] = context["faint_policy"]
            else:
                raise ValueError("After entry marks Swift affordability remains unresolved")
        if mark_enabled and incoming["hp"] == 0 and allow_faint:
            entry_program = None
            events.append({"op": "entry_swift.skipped", "reason": "exhausted_by_entry_mark"})
        if entry_program is not None:
            from lab.turn_plan import charge_admission
            admission = charge_admission(prepared, incoming, swift['skill_id'],
                slot=swift['slot'], turn=current['turn'])
            if admission.get('execution_phase') == 'charge_setup_not_attack_release':
                raise ValueError('Entry Swift charge setup/release timing remains unresolved; no release payload executed')
            entry_context.update(deepcopy(admission))
            result['entry_swift']['charge_admission'] = deepcopy(admission)
            from lab.core_magic_runtime import effective_skill_power
            ratio = Fraction(effective_skill_power(current, side, 1))
            entry_context["core_magic_power_multiplier"] = {"numerator": ratio.numerator,
                                                           "denominator": ratio.denominator}
            other = "b" if side == "a" else "a"
            from lab.research_phases import _trait_cost_context
            entry_context.update(_trait_cost_context(prepared, current, side))
            entry_context.update(turn=current['turn'], response_success=False,
                opponent_kind='unobserved_entry_opponent_action', opponent_effective_cost=None,
                opponent_switched_this_turn=current['teams'][other]['members'][current['teams'][other]['active_slot']]['entered_turn'] == current['turn'],
                weather=deepcopy(current.get('weather')), weather_skill_id=swift['skill_id'],
                weather_response_success=False)
            quote = candidates[swift['slot']].get('health_payment')
            entry_context.pop('health_payment', None)
            if quote:
                entry_context['health_payment'] = deepcopy(quote)
                result['entry_swift']['health_payment'] = deepcopy(quote)
            if candidates[swift["slot"]].get("action_trait"):
                entry_context["action_trait"] = deepcopy(candidates[swift["slot"]]["action_trait"])
                result["entry_swift"]["action_trait"] = deepcopy(entry_context["action_trait"])
            other = "b" if side == "a" else "a"
            relative = {"self": _typed_actor(rules, incoming), "opponent": _typed_actor(rules, opponent)}
            if mark_enabled:
                relative = marks.attach_relative_marks(current, side)
                relative = {key: _typed_actor(rules, member) for key, member in relative.items()}
                skill = rules.skill(swift["skill_id"])
                entry_context.update(marks.research_context())
                entry_context.update(skill_kind=skill["kind"], skill_type=skill["type"],
                    mark_first_action=incoming["mark_entry_actions"] == 0,
                    mark_first_attack=context.get("mark_first_attack", False))
            from lab import transformation_runtime as transformations
            entry_action = {"kind": "skill", "slot": swift["slot"], "skill_id": swift["skill_id"],
                "actor_member_id": incoming["member_id"], "effective_cost": swift["effective_cost"],
                "program": entry_program}
            if entry_program.get('requires_carried_cost_snapshot'):
                from lab.research_phases import _carried_cost_snapshot
                entry_context['carried_effective_skill_costs'] = _carried_cost_snapshot(prepared,current,side,entry_action,
                    allow_partial='adjacent_power_components' in entry_program)
            if 'adjacent_power_components' in entry_program:
                from lab.adjacent_power_runtime import POLICY as ADJACENT_POWER_POLICY
                entry_context.update(adjacent_power_policy=ADJACENT_POWER_POLICY, selected_skill_slot=swift['slot'])
            entry_opponent = {"kind": "unobserved_entry_opponent_action"}
            entry_context.update(history.research_context())
            history_binding = history.bind_action(prepared, current, side, entry_action)
            if history_binding is not None:
                entry_context['skill_history_power'] = history.power_terms(current, history_binding)
            if "transformation_components" in entry_program:
                # The switch fragment has no locked opposing action. Reduction
                # is active, but an unobserved response is never presumed true.
                entry_context.update(turn=current["turn"], response_success=False,
                    entry_response_policy=ENTRY_SWIFT_RESPONSE_POLICY,
                    transformation_policies=transformations.policies())
            entry_context["_transformation_binding"] = transformations.before_action(
                prepared, current, side, entry_action, entry_opponent, entry_context)
            from lab import payment_runtime as payment
            from lab.research_phases import _preflight_component_unpaid, _execute_component_unpaid
            def preflight_dispatch(program, actors, policies, *, damage_resolver=None):
                if mark_enabled:
                    return marks.preflight_with_marks(program, actors, policies,
                        damage_resolver=damage_resolver, preflight_base=_preflight_component_unpaid)
                return _preflight_component_unpaid(program, actors, policies, damage_resolver=damage_resolver)
            def dispatch(program, actors, policies, *, damage_resolver=None):
                if mark_enabled:
                    return marks.execute_with_marks(program, actors, policies,
                        damage_resolver=damage_resolver, execute_base=_execute_component_unpaid,
                        preflight_base=_preflight_component_unpaid)
                return _execute_component_unpaid(program, actors, policies, damage_resolver=damage_resolver)
            entry_context.update(trait_attack_hooks.research_context())
            attack_binding = trait_attack_hooks.prepare_attack(prepared, relative["self"], entry_program,
                entry_context, token=f"{current['turn']}:entry:{side}:{target_slot}")
            payment.preflight(entry_program, relative, entry_context,
                preflight_base=preflight_dispatch, damage_resolver=damage_resolver)
            fragment = payment.execute(entry_program, relative, entry_context,
                execute_base=dispatch, damage_resolver=damage_resolver)
            if fragment["status"] != "applied":
                raise ValueError("Entry skill rejected; local switch candidate is not committed: " + "; ".join(fragment["blockers"]))
            if not allow_faint and any(fragment["state"][name]["hp"] == 0 for name in ("self", "opponent")):
                raise ValueError("Entry skill exhaustion needs unresolved faint/replacement/trigger rules; local switch candidate is not committed")
            if mark_enabled:
                marks.commit_marks(current, side, fragment)
            for relative_side, absolute_side, original in (("self", side, incoming), ("opponent", other, opponent)):
                updated = deepcopy(fragment["state"][relative_side])
                # Types are source-derived validation inputs. Do not add a new
                # stored field to a caller state that omitted them originally.
                if "types" not in original:
                    updated.pop("types", None)
                target_team = current["teams"][absolute_side]
                target_team["members"][target_team["active_slot"]] = updated
            from lab import action_outcome_runtime as outcomes
            action_token = f"{current['turn']}:entry:{side}:{target_slot}:outcomes"
            fragment['events'].extend(outcomes.record_committed_action(prepared, current, side,
                entry_action, fragment['events'], event_token=action_token))
            fragment['events'].extend(history.observe_action(prepared, current, side, entry_action,
                action_token=action_token, context={**entry_context, 'action_is_later': False,
                    'history_order_scope': 'entry_swift_subaction'}))
            fragment['events'].extend(history.observe_received_attack(prepared, current, other, entry_action,
                fragment['events'], action_token=action_token, context=entry_context))
            fragment['events'].extend(trait_runtime.after_outcome(prepared, current, side,
                entry_action, fragment['events'], token=action_token, context=entry_context))
            fragment['events'].extend(trait_runtime.after_opponent_skill(prepared, current, side,
                entry_action['skill_id'], token=action_token + ':opponent.skill.after'))
            fragment['events'].extend(trait_runtime.after_received_attack(prepared, current, other,
                fragment['events'], context=entry_context, token=action_token + ':received'))
            fragment['events'].extend(history.after_skill(prepared, current, side, entry_action,
                history_binding, action_token=action_token, context=entry_context))
            fragment['events'].extend(trait_switch_components.after_action(prepared, current, side,
                entry_action, token=action_token + ':switch_trait.after_skill'))
            fragment["events"].extend(trait_attack_hooks.after_skill(prepared, current, side, entry_program,
                fragment["events"], attack_binding, context=entry_context))
            if mark_enabled:
                _active(current, side)["mark_entry_actions"] += 1
            if entry_action is not None:
                fragment["events"].extend(transformations.after_action(prepared, current, side,
                    entry_action, entry_opponent, entry_context, fragment))
            for item in fragment["events"]:
                item = deepcopy(item)
                target_side = item.get('target_side', side if item.get("target", "self") == "self" else other)
                item.update(origin="entry_swift", entry_timing=context["entry_timing"])
                for key, value in {'actor_side': side, 'actor_member_id': incoming['member_id'],
                        'target_side': target_side, 'target_member_id': _active(current, target_side)['member_id'],
                        'skill_slot': swift['slot'], 'skill_id': swift['skill_id'],
                        'source_hash': entry_program['source_hash']}.items():
                    item.setdefault(key, value)
                events.append(item)
        if entry_program is not None:
            from lab import mechanism_runtime as mechanisms
            events.extend(mechanisms.after_skill_hits(prepared, current, side, swift['skill_id'],
                token=f"{current['turn']}:entry:{side}:{target_slot}"))
            events.extend(trait_runtime.run_event(prepared, current, "skill.after", side=side,
                payload={**rules.skill(swift["skill_id"]), "response_success": False, "entry_first_action":entry_context.get("mark_first_action", False)},
                token=f"{current['turn']}:entry_swift:{side}:{target_slot}"))
            events.extend(trait_runtime.run_event(prepared, current, 'action.after', side=side,
                member_id=incoming['member_id'], payload={'kind':'skill','first_action':entry_context.get('mark_first_action',False)},
                token=f"{current['turn']}:entry_swift:{side}:{target_slot}:action.after"))
        result.update(status="applied", state=current, events=events,
                      final_state_hash=canonical_hash(current), assumptions=deepcopy(context),
                      switch_fragment_executed=True, entry_skill_executed=entry_program is not None)
        if entry_program is not None:
            result["entry_skill_assumptions"] = deepcopy(entry_context)
            result["entry_swift"]["skill_executed"] = True
    except Exception as exc:
        result["blockers"] = [str(exc)]
    return result
