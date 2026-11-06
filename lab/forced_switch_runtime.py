"""Source-bound detach/return/emergency components, not whole skill programs."""
from copy import deepcopy

from lab import core_magic_runtime as magic, mark_runtime as marks, trait_runtime as traits
from lab import status_lifecycle, weather_runtime
from lab.dynamic_skills import _draw
from lab.effect_runtime import _state
from lab.prepared_rules import prepare_rules
from lab.ruleset import canonical_hash
from lab.switch_runtime import _typed_actor
from lab.turn_plan import _validate_state

POLICY = "source_departure_explicit_target_sha256_random_no_intrinsic_swift_v1"


def policies():
    return {"version": POLICY, "cleanup": "source_bound_status_weather_magic_departure_other_fields_retained",
            "entry": "existing_opt_in_traits_then_marks_no_intrinsic_swift",
            "random": "existing_sha256_counter_uniform_over_all_living_reserve_slots",
            "no_candidate": "no_change_no_random_draw_experiment",
            "ordering": "caller_committed_effect_order_experiment"}


DUAL_ORDER = 'user_confirmed_pre_departure_speed_seeded_tie_v1'


def preflight_departure(catalog, state, side, cause, replacement_slot=None):
    """Read-only target-owner choice validation shared by ordered departures."""
    team = state['teams'][side]
    actor = team['members'][team['active_slot']]
    eligibility = prepare_rules(catalog)._components()[2].departure(cause, actor['entered_turn'],
        state['turn'], actor['charge'] is not None, actor['rooted'])
    if eligibility['status'] == 'unresolved':
        raise ValueError(eligibility['reason'])
    candidates = [i for i, member in enumerate(team['members']) if i != team['active_slot'] and member['hp'] > 0]
    if (actor['hp'] > 0 and cause == 'detach' and eligibility['status'] == 'allowed' and candidates
            and (type(replacement_slot) is not int or replacement_slot not in candidates)):
        raise ValueError('Ordered departure requires an explicit living target-owner replacement_slot for ' + side)
    return {'side': side, 'cause': cause, 'replacement_slot': replacement_slot,
            'eligibility': eligibility, 'living_candidates': candidates}


def execute_departures(catalog, state, selections, *, event_token, context,
                       source_skill_id, source_hash, order_policy):
    """Commit each source-validated departure; later failure retains earlier changes."""
    if order_policy != DUAL_ORDER or not isinstance(selections, list) or len(selections) != 2:
        raise ValueError('Ordered dual departure requires the explicit reviewed research order')
    current, events, committed = deepcopy(state), [], False
    from lab.research_phases import _effective_speed
    if {selection.get('side') for selection in selections} != {'a', 'b'}:
        raise ValueError('Dual departure must contain each target side exactly once')
    actors = {side: current['teams'][side]['members'][current['teams'][side]['active_slot']] for side in ('a','b')}
    speeds = {side: _effective_speed(actors[side],current['turn'],actors['b' if side=='a' else 'a']) for side in ('a','b')}
    if any(type(speed) is not int for speed in speeds.values()):
        raise ValueError('Dual departure requires both pre-departure effective speeds')
    order = sorted(('a','b'),key=lambda side:-speeds[side])
    random_record = None
    if speeds['a'] == speeds['b']:
        seed = context.get('random_seed',current.get('random_devotion_rng',{}).get('seed'))
        if type(seed) is not int:
            raise ValueError('Equal-speed dual departure requires the battle random seed')
        rng = current.setdefault('forced_switch_order_random',{'seed':seed,'counter':0})
        if set(rng) != {'seed','counter'} or rng['seed'] != seed or type(rng['counter']) is not int or rng['counter']<0:
            raise ValueError('Dual departure random cursor changed')
        before = rng['counter']
        if _draw(rng,2): order.reverse()
        random_record = {'seed':seed,'counter_before':before,'counter_after':rng['counter']}
    selections = sorted(selections,key=lambda selection:order.index(selection['side']))
    events.append({'op':'switch.dual_order','sides':order,'pre_departure_speeds':speeds,
        'random_draw':random_record,'source':'user_confirmation_20261030','policy':DUAL_ORDER})
    for index, selection in enumerate(selections):
        side = selection['side']
        team = current['teams'][side]
        if team['members'][team['active_slot']]['hp'] <= 0:
            events.append({'op': 'switch.forced_skipped', 'side': side, 'reason': 'exhausted_target'})
            continue
        try:
            fragment = execute_forced_switch_fragment(catalog, current, side, selection['cause'],
                target_slot=selection['replacement_slot'] if selection['cause'] == 'detach' else None,
                context={**deepcopy(context), 'snapshot_id': prepare_rules(catalog).snapshot_id,
                    'forced_switch_policies': policies(), 'event_token': event_token + ':' + str(index) + ':' + side})
        except (ValueError, KeyError, TypeError) as exc:
            fragment = {'status': 'blocked', 'blockers': [str(exc)], 'training_eligible': False}
        if fragment['status'] != 'applied':
            fragment.update(state=current, events=events, partial_commit=committed,
                departure_order_policy=order_policy)
            return fragment
        current = fragment['state']
        events.extend({**e, 'source_skill_id': source_skill_id, 'source_hash': source_hash,
            'departure_order_policy': order_policy, 'departure_index': index} for e in fragment['events'])
        committed = committed or bool(fragment['events'])
    return {'status': 'applied', 'state': current, 'events': events, 'blockers': [],
            'departure_order_policy': order_policy, 'training_eligible': False}


def execute_forced_switch_fragment(catalog, state, side, cause, *, target_slot=None, context=None):
    """Apply one reviewed departure effect atomically with its entry/exit hooks.

    ``cause`` is detach (explicit selected reserve), return (same member), or
    emergency (uniform living reserve using context.random_seed). The caller
    must establish the triggering skill/response and supply an event_token;
    this pure component never infers that a carried skill has been executed.
    Source entry/charge/root immunities run before selection or random draws.
    Intrinsic Swift is voluntary-only and therefore never triggered here.
    """
    result = {"status": "blocked", "scope": "source_bound_forced_switch_component", "state": deepcopy(state),
              "events": [], "blockers": [], "full_switch_executed": False,
              "full_turn_executed": False, "training_eligible": False, "calibrated": False,
              "real_game_verified": False, "battle_executable": False}
    try:
        if (not isinstance(context, dict) or context.get("forced_switch_policies") != policies()
                or not isinstance(context.get("event_token"), str) or not context["event_token"]):
            raise ValueError("Forced switch requires complete policies and a unique source-event token")
        prepared = prepare_rules(catalog)
        rules, phases, switches = prepared._components()
        if context.get("snapshot_id") != prepared.snapshot_id:
            raise ValueError("Forced switch must bind its catalog snapshot")
        if side not in ("a", "b") or cause not in ("detach", "return", "emergency"):
            raise ValueError("Unknown forced-switch side or departure cause")
        current = deepcopy(state)
        _validate_state(rules, phases, current)
        team = current["teams"][side]
        before = team["active_slot"]
        outgoing = team["members"][before]
        if outgoing["hp"] <= 0:
            raise ValueError("An exhausted member needs a faint replacement, not a departure effect")
        token = canonical_hash({"turn": current["turn"], "side": side, "cause": cause,
                                "event_token": context["event_token"]})
        consumed = current.get("forced_switch_events", [])
        if not isinstance(consumed, list) or any(not isinstance(t, str) for t in consumed) or len(set(consumed)) != len(consumed):
            raise ValueError("Invalid forced-switch event ledger")
        if token in consumed:
            raise ValueError("Forced-switch source event was already consumed")
        eligibility = switches.departure(cause, outgoing["entered_turn"], current["turn"],
                                          outgoing["charge"] is not None, outgoing["rooted"])
        if eligibility["status"] == "unresolved":
            raise ValueError(eligibility["reason"])
        candidates = [slot for slot, member in enumerate(team["members"])
                      if slot != before and member["hp"] > 0]
        selected = before
        no_change = eligibility["status"] != "allowed" or (cause != "return" and not candidates)
        random_record = None
        if not no_change and cause == "detach":
            if type(target_slot) is not int or target_slot not in candidates:
                raise ValueError("Detach requires an explicit living reserve slot")
            selected = target_slot
        elif not no_change and cause == "emergency":
            seed = context.get("random_seed")
            if type(seed) is not int:
                raise ValueError("Emergency departure requires an explicit integer random_seed")
            if target_slot is not None:
                raise ValueError("Emergency target must be drawn from the entire living reserve pool")
            prng = current.setdefault("forced_switch_random", {"seed": seed, "counter": 0})
            if (not isinstance(prng, dict) or set(prng) != {"seed", "counter"}
                    or type(prng["seed"]) is not int or prng["seed"] != seed
                    or type(prng["counter"]) is not int or prng["counter"] < 0):
                raise ValueError("Emergency random stream changed or is malformed")
            old_counter = prng["counter"]
            selected = candidates[_draw(prng, len(candidates))]
            random_record = {"seed": seed, "counter_before": old_counter,
                             "counter_after": prng["counter"], "all_candidates": candidates,
                             "selected_slot": selected}
        elif cause == "return" and target_slot is not None:
            raise ValueError("Return re-enters the same member and has no reserve selection")
        events = [{"op": "switch.forced", "side": side, "cause": cause,
                   "from_slot": before, "to_slot": selected, "source_token": token,
                   "eligibility": eligibility, "no_change": no_change,
                   "random_draw": random_record, "policy": POLICY}]
        if not no_change:
            incoming = team["members"][selected]
            for member in (outgoing, incoming):
                actor = _typed_actor(rules, member)
                _state({"self": actor, "opponent": actor})
            if incoming["charge"] is not None:
                raise ValueError("Incoming charged reserve cancellation remains unresolved")
            inheritance_grant, inheritance_events = None, []
            inheritance_request = context.get('buff_inheritance')
            if inheritance_request is not None:
                if cause != 'detach' or selected == before or not isinstance(inheritance_request, dict):
                    raise ValueError('Source BUFF inheritance requires an actual detach to another member')
                from lab.modifier_ledger import prepare_inheritance
                inheritance = prepare_inheritance(outgoing,
                    source_skill_id=inheritance_request.get('source_skill_id'),
                    source_hash=inheritance_request.get('source_hash'), token=inheritance_request.get('token'))
                team['members'][before] = inheritance['departing_member']
                outgoing = team['members'][before]
                inheritance_grant = inheritance['grant']
                inheritance_events += [{**e, 'actor_side': side, 'actor_member_id': outgoing['member_id'],
                    'target_side': side, 'target_member_id': outgoing['member_id'],
                    'source_skill_id': inheritance_grant['source_skill_id'], 'source_hash': inheritance_grant['source_hash']}
                    for e in inheritance['events']]
            from lab import skill_history_runtime as history
            # Existing switch cleanup mutates member objects; history uses an
            # owned-state transaction, so reacquire pointers after it commits.
            events.extend(history.on_departure(prepared, current, side, outgoing['member_id'],
                event_token=token + ':history.leave'))
            team = current['teams'][side]
            outgoing, incoming = team['members'][before], team['members'][selected]
            from lab.user_skill_extensions import repeat_departure
            if 'repeat_cast_history' in outgoing or 7110380 in outgoing['skill_slots']:
                events.extend(repeat_departure(outgoing, turn=current['turn'], token=token + ':repeat.leave'))
            from lab.user_skill_extensions import clear_per_type_power
            events.extend(clear_per_type_power(current, outgoing["member_id"]))
            events.extend(magic.on_core_magic_departure(current, side, outgoing["member_id"]))
            events.extend(status_lifecycle.on_departure(outgoing, side))
            events.extend(weather_runtime.on_departure(outgoing, side))
            if cause != 'return':
                outgoing['other_automatic_departure_turn'] = current['turn']
            team["active_slot"] = selected
            incoming["entered_turn"] = current["turn"]
            incoming["mark_entry_actions"] = 0
            if inheritance_grant is not None:
                from lab.modifier_ledger import apply_inheritance
                inheritance_events += [{**e, 'actor_side': side, 'actor_member_id': outgoing['member_id'],
                    'target_side': side, 'source_skill_id': inheritance_grant['source_skill_id'],
                    'source_hash': inheritance_grant['source_hash']}
                    for e in apply_inheritance(incoming, inheritance_grant)]
                events.extend(inheritance_events)
            from lab import trait_switch_components
            events.extend(trait_switch_components.after_switch(prepared, current, side,
                outgoing['member_id'], incoming['member_id'], token=token + ':switch_traits'))
            events.extend(traits.run_event(prepared, current, "member.leave", side=side,
                member_id=outgoing["member_id"], token=token + ":leave"))
            events.extend(traits.run_event(prepared, current, "member.enter", side=side,
                member_id=incoming["member_id"], token=token + ":enter"))
            from lab import trait_attack_hooks
            events.extend(trait_attack_hooks.on_entry(prepared, current, side))
            events.extend(history.on_entry(prepared, current, side, event_token=token + ':history.enter'))
            if context.get("mark_policies") == marks.research_context()["mark_policies"]:
                actors = marks.attach_relative_marks(current, side)
                for key in actors:
                    actors[key] = _typed_actor(rules, actors[key])
                phase = marks.mark_phase(actors, "after_switch", context=context)
                if phase["status"] != "applied":
                    raise ValueError("Forced-entry marks blocked: " + "; ".join(phase["blockers"]))
                marks.commit_marks(current, side, phase)
                for key, absolute in (("self", side), ("opponent", "b" if side == "a" else "a")):
                    owner = current["teams"][absolute]
                    updated = phase["state"][key]
                    if "types" not in owner["members"][owner["active_slot"]]:
                        updated.pop("types", None)
                    owner["members"][owner["active_slot"]] = updated
                events.extend(phase["events"])
            elif any(mark is not None for owner in current["teams"].values()
                     for mark in owner.get("marks", {}).values()):
                raise ValueError("Existing field marks require their explicit entry policies")
        current["forced_switch_events"] = [*consumed, token]
        result.update(status="applied", state=current, events=events,
                      switch_fragment_executed=not no_change, selected_slot=selected,
                      source_effect_trigger_resolved=False)
    except (ValueError, KeyError, TypeError) as exc:
        result["blockers"] = [str(exc)]
    return result
