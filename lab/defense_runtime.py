"""Source-bound defense phases under explicit, uncalibrated experiment policies.

This module does not decide priority, speed, entry actions, or damage formulas.
Call mitigation on the resolver's raw damage BEFORE clipping to remaining HP.
Only whole descriptions accepted by ``_phase`` gain an executable override.
"""
from copy import deepcopy
import json
from pathlib import Path
from functools import lru_cache

from lab.action_rules import ActionRules, TERMS_HASH
from lab.effect_runtime import _preflight_header, _integer, execute_effects
from lab.phase_config import load_phase_config, fingerprint
from lab.prepared_rules import prepare_rules


POLICY = "source_bound_defense_phase_experiment_v1"
SLOT_BONUS_POLICY = "positional_reduction_added_at_activation_cap_100_experiment_v1"
POLICIES = {
    "window": "after_defense_execution_through_current_turn_experiment",
    "damage": "multiply_raw_attack_damage_then_floor_before_hp_clip_experiment",
    "cooldown": "member_shared_defense_blocks_next_turn_inclusive_experiment",
    "response": "opponent_committed_skill_kind_before_execution_experiment",
    "effects": "response_effects_immediately_after_payment_experiment",
    "stats": "record_signed_percentage_terms",
    "hp": "declared_max_hp_floor_clamp_experiment",
    "energy": "clamp_to_declared_max_or_zero_experiment",
}
UNCERTAINTIES = [
    "Defense duration, rounding, shared cooldown boundary, and response effect timing are named experiments, not live-game calibration.",
    "Only direct physical/magical attack damage is reduced; status/environment damage bypasses this phase.",
    "Response compares selected executable skill kind; charge setup, recharge, switch and skipped actions need caller-supplied phase classification.",
    "Multiple simultaneous successful responses retain the action planner's unresolved conflict; this module never orders actions.",
]
STATS = {"物攻": "patk", "魔攻": "matk", "物防": "pdef", "魔防": "mdef"}
NON_SKILLS = {"switch", "recharge", "charge"}
HUILLU = "雨天的回合数延长4回合，应对防御：改为延长8回合。"


CONFIG = Path(__file__).resolve().parents[1] / "data/rules/reviewed-defense-components-1.json"
CONFIG_HASH = '68a5ebb004017c0d5993b6e51df34ee7fb15ff50a50bbdcc212f31d0d64d7284'
DEPARTURE_POLICY = "explicit_target_owner_replacement_after_defense_experiment_v1"
END_RETURN_POLICY = 'source_queued_original_active_entry_after_end_effects_before_trait_departures_experiment_v1'


@lru_cache(maxsize=2)
def _configuration(stamp):
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    if data.get("schema") != "reviewed-defense-components-1" or fingerprint(data) != CONFIG_HASH:
        raise ValueError("Defense component configuration changed; review required")
    return data


def _phase(record):
    """Look up reviewed component data; never parse prose in the battle runtime."""
    row = _configuration(CONFIG.stat().st_mtime_ns)["skills"].get(str(record.get("id")))
    if row is None or fingerprint(record) != row["record_hash"]:
        return None
    return deepcopy(row["components"])


def conditional_cost(state, side, skill_id, value):
    """Reviewed defense conditional energy discount keyed on committed history.

    A defense component may declare ``conditional_cost`` =
    ``{when_previous_kind: [..], discount: N, policy: ..}``. When the active
    member committed at least one skill of a listed kind on turn-1, the
    declared discount is applied to the action cost and floored at zero.
    This is an explicit experimental policy; the exact live trigger boundary is
    not calibrated.
    """
    if not isinstance(value, int) or value < 0:
        raise ValueError("Defense conditional cost requires a non-negative integer cost")
    data = _configuration(CONFIG.stat().st_mtime_ns)
    spec = None
    for row in data["skills"].values():
        if row["raw"]["id"] == skill_id:
            spec = row["components"]
            break
    cc = (spec or {}).get("conditional_cost")
    if not cc:
        return value
    if cc.get("policy") != "floor_zero_experiment":
        raise ValueError("Defense conditional cost policy is not the reviewed experiment")
    discount = cc.get("discount")
    kinds = cc.get("when_previous_kind")
    if type(discount) is not int or discount < 0 or not isinstance(kinds, list) or not kinds:
        raise ValueError("Defense conditional cost needs explicit discount and kinds")
    team = state["teams"][side]
    actor = team["members"][team["active_slot"]]
    from lab.action_outcome_runtime import committed_history
    history = committed_history(actor)
    turn = state["turn"]
    allowed = set(kinds)
    if not any(e["turn"] == turn - 1 and e["kind"] in allowed for e in history):
        return value
    return max(0, value - discount)


def defense_programs(catalog):
    """Detached overrides, with reviewed phase snapshot and original source hash.

    The existing phase manifest binds the whole owned skill/term snapshot; this
    runtime adds its separate versioned defense phase metadata to that boundary.
    Unknown descriptions remain absent, preserving the base program's blockers.
    """
    prepared = prepare_rules(catalog)
    folder = CONFIG.parent / prepared.snapshot_id
    paths = (CONFIG, folder / 'phase-config-1.json', folder / 'phase-config-1.manifest.json')
    stamp = tuple((str(p), s.st_size, s.st_mtime_ns, s.st_ctime_ns)
                  for p in paths for s in [p.stat()])
    return deepcopy(_defense_programs(prepared, stamp))


@lru_cache(maxsize=8)
def _defense_programs(prepared, stamp):
    # Static programs only; the public result remains detached from this cache.
    source = prepared._rules._catalog
    ActionRules(source)  # Validate reviewed Terms, including attack-response CD.
    phase_config = load_phase_config(source)
    records = source["moves"]
    records = records.values() if isinstance(records, dict) else records
    programs = {}
    for record in records:
        spec = _phase(record)
        if spec is None:
            continue
        mid = record.get("id", record.get("game_id"))
        program = deepcopy(prepared._rules.program(mid))
        program.pop("native_rule", None)
        program.update(status="compiled", blockers=[], dependency_ids=sorted(set(record.get("desc_notes", [])) | {1016}),
            operations=[{"op": "defense.plan", "params": {"target": "self",
                "reduction": deepcopy(spec["reduction"]), "response": "attack"}}],
            defense_components=spec, response_categories=["attack"],
            defense_installation_evidence=deepcopy(_configuration(CONFIG.stat().st_mtime_ns)["skills"][str(mid)]["installation_evidence"]),
            defense_source_record=deepcopy(record), defense_phase_version=POLICY,
            defense_phase_config_hash=fingerprint(phase_config),
            defense_policy_uncertainties=deepcopy(UNCERTAINTIES),
            executable=False, real_game_verified=False)
        programs[mid] = program
    return programs


def response_categories(program):
    """Whole-description metadata also exposes 汇流's source-backed response."""
    if "defense_components" in program:
        _validate_program(program)
        return deepcopy(program["defense_components"]["responses"])
    if (program.get("game_id") == 7050530 and program.get("source_description") == HUILLU
            and program.get("term_source", {}).get("content_sha256") == TERMS_HASH):
        return ["defense"]
    return []


def response_success(program, opponent_kind):
    if opponent_kind in NON_SKILLS:
        return False
    if opponent_kind not in {"physical", "magical", "status", "defense"}:
        raise ValueError("Unknown opposing action phase/kind")
    return any(ActionRules.counter_matches(category, opponent_kind)
               for category in response_categories(program))


def _validate_program(program):
    record = program.get("defense_source_record")
    if (not isinstance(record, dict) or fingerprint(record) != program.get("source_hash")
            or record.get("id", record.get("game_id")) != program.get("game_id")
            or program.get("defense_phase_version") != POLICY
            or not isinstance(program.get("defense_phase_config_hash"), str)
            or len(program["defense_phase_config_hash"]) != 64
            or program.get("term_source", {}).get("content_sha256") != TERMS_HASH
            or _phase(record) is None or program.get("defense_components") != _phase(record)):
        raise ValueError("Defense phase/source definition drift requires review")
    expected = [{"op": "defense.plan", "params": {"target": "self",
        "reduction": deepcopy(program["defense_components"]["reduction"]), "response": "attack"}}]
    if program.get("operations") != expected or "native_rule" in program:
        raise ValueError("Defense operations differ from source-bound phase")


def check_cooldown(member, turn):
    _integer(turn, "turn", 1)
    runtime = member.get("defense_runtime", {})
    if not isinstance(runtime, dict):
        raise ValueError("Malformed defense runtime state")
    if runtime and runtime.get("policy") != POLICY:
        raise ValueError("Unknown defense runtime policy")
    until = _integer(runtime.get("cooldown_through_turn", 0), "defense cooldown")
    if turn <= until:
        raise ValueError("Carried defense skills share cooldown through turn " + str(until))


def preflight_defense_skill(program, state, context, *, turn, opponent_kind,
                            opponent_effective_cost=None):
    _preflight_header(program, state, context)
    _validate_program(program)
    if context.get("defense_policies") != POLICIES:
        raise ValueError("Explicit versioned defense policies required")
    check_cooldown(state["self"], turn)
    cost = _integer(context.get("resolved_energy_cost"), "resolved defense cost")
    if cost > state["self"]["energy"]:
        raise ValueError("Insufficient energy for defense")
    successful = response_success(program, opponent_kind)
    if successful and any("opponent_cost_multiplier" in e for e in program["defense_components"]["response_effects"]):
        _integer(opponent_effective_cost, "resolved opposing skill cost")
    if successful and any(e["op"] == "skill.cost" and e.get("skill_selector")=="opponent.declared_skill" for e in program["defense_components"]["response_effects"]):
        _integer(context.get("opponent_declared_skill"), "declared opposing skill", 1)
        _integer(context.get("turn"), "cost modifier turn", 1)
    if successful:
        for effect in program["defense_components"]["response_effects"]:
            member = state[effect["target"]]
            if effect["op"] == "attack.grant":
                from lab.attack_grant_runtime import install
                install(deepcopy(member), program, context)
            elif effect['op'] == 'modifier.dispel_limited':
                from lab.modifier_ledger import limited_dispel
                limited_dispel(deepcopy(state),effect['target'],mode=effect['mode'],count=effect['count'],
                    source_skill_id=program['game_id'],source_hash=program['source_hash'],turn=turn)
            elif effect["op"] in {"power.percent","power.flat","next.power","next.priority"}:
                from lab.mechanism_runtime import grant_modifier
                grant_modifier(deepcopy(member),effect,program,context)
            elif effect["op"] == "hits.flat":
                from lab.mechanism_runtime import modify_hits
                modify_hits(member, 1)
            elif effect["op"] == "mark.add":
                from lab import mark_runtime as marks
                marks.change_marks(member.get("field_marks"), effect["mark_id"], effect["stacks"],
                    context=context, source={"skill_id": program["game_id"], "source_hash": program["source_hash"]})
    return {"response_success": successful, "policy": POLICY,
            "policies": deepcopy(POLICIES), "uncertainties": deepcopy(UNCERTAINTIES)}


def execute_defense_skill(program, state, context, *, turn, opponent_kind,
                          opponent_effective_cost=None):
    result = {"status": "blocked", "state": deepcopy(state), "events": [], "blockers": [],
              "policy": POLICY, "policies": deepcopy(POLICIES), "uncertainties": deepcopy(UNCERTAINTIES),
              "training_eligible": False, "calibrated": False, "real_game_verified": False,
              "full_turn_executed": False}
    try:
        checked = preflight_defense_skill(program, state, context, turn=turn,
            opponent_kind=opponent_kind, opponent_effective_cost=opponent_effective_cost)
        owned = deepcopy(state)
        actor = owned["self"]
        cost = context["resolved_energy_cost"]
        actor["energy"] -= cost
        events = [{"op": "energy.pay", "target": "self", "amount": cost}]
        spec = deepcopy(program["defense_components"])
        if spec.get("reduction_status_count"):
            from lab.mechanism_runtime import _status_count
            query=spec["reduction_status_count"]
            count=_status_count(owned[query["target"]],query["status"])
            spec["reduction"]["numerator"]=min(100,spec["reduction"]["numerator"]+count*query["amount"])
            events.append({"op":"defense.status_count","count":count,"reduction":deepcopy(spec["reduction"]),
                "policy":"snapshot_at_guard_activation_additive_cap_100_experiment_v1"})
        if spec.get("reduction_slot_bonus"):
            query = spec["reduction_slot_bonus"]
            slot = context.get("selected_skill_slot")
            hit = type(slot) is int and slot in query["slots"]
            if hit:
                spec["reduction"]["numerator"] = min(100, spec["reduction"]["numerator"] + query["amount"])
            events.append({"op": "defense.slot_bonus", "slot": slot, "applied": hit,
                "amount": query["amount"] if hit else 0, "reduction": deepcopy(spec["reduction"]),
                "policy": query.get("policy", "additive_at_activation_cap_100_experiment")})
        actor["defense_runtime"] = {"policy": POLICY, "cooldown_through_turn": turn + 1,
            "guard_turn": turn, "reduction": deepcopy(spec["reduction"]), "response_success":checked["response_success"],
            "skill_id": program["game_id"], "source_hash": program["source_hash"],
            "snapshot_id": program["snapshot_id"], "phase_config_hash": program["defense_phase_config_hash"]}
        events.append({"op": "defense.activate", "target": "self", "turn": turn,
            "reduction": deepcopy(spec["reduction"]), "response_success": checked["response_success"],
            "cooldown_through_turn": turn + 1, "source_hash": program["source_hash"], "policy": POLICY})
        from lab.mechanism_runtime import consume_skill_tokens
        events.extend(consume_skill_tokens(actor,attacked=False,turn=turn))
        if checked["response_success"]:
            for effect in spec["response_effects"]:
                target = owned[effect["target"]]
                if effect['op'] == 'defense.cooldown.reduce':
                    before = target['defense_runtime']['cooldown_through_turn']
                    after = max(turn,before-effect['amount'])
                    trace = {'op':effect['op'],'target':effect['target'],'before':before,'after':after,
                        'source_skill_id':program['game_id'],'source_hash':program['source_hash'],
                        'policy':'reduce_shared_defense_cooldown_after_current_install_floor_current_turn_experiment'}
                    target['defense_runtime']['cooldown_through_turn'] = after
                    target['defense_runtime'].setdefault('cooldown_changes',[]).append(deepcopy(trace))
                    events.append(trace)
                    continue
                if effect['op'] == 'modifier.dispel_limited':
                    from lab.modifier_ledger import limited_dispel
                    events.append(limited_dispel(owned,effect['target'],mode=effect['mode'],count=effect['count'],
                        source_skill_id=program['game_id'],source_hash=program['source_hash'],turn=turn))
                    continue
                if effect['op'] == 'adjacent_cost.grant':
                    from lab import adjacent_cost_runtime
                    target = owned[effect['target']]
                    token = f"{turn}:{program['game_id']}:adjcost:{len(events)}"
                    events.extend(adjacent_cost_runtime.grant(target, effect['target'], program['game_id'],
                        context.get('selected_skill_slot'), amount=effect['amount'], response_success=True,
                        turn=turn, token=token))
                    continue
                event = deepcopy(effect)
                if effect["op"] == "attack.grant":
                    from lab.attack_grant_runtime import install
                    event = install(target, program, context)
                elif effect["op"] in {"power.percent","power.flat","next.power","next.priority"}:
                    from lab.mechanism_runtime import grant_modifier
                    event = grant_modifier(target,effect,program,context)
                elif effect["op"] == "hits.flat":
                    from lab import mechanism_runtime as mechanisms
                    mechanisms.modify_hits(target, 1)
                    item = {"op": "hits.flat", "amount": effect["amount"], "policy": mechanisms.POLICY,
                            "hit_policy": mechanisms.HIT_POLICY, "source_skill_id": program["game_id"],
                            "source_hash": program["source_hash"]}
                    target.setdefault("mechanism_flat_modifiers", []).append(item)
                    event.update(deepcopy(item))
                elif effect["op"] == "skill.cost":
                    from lab.mechanism_runtime import _change_cost
                    event = _change_cost(target, effect, program, context)
                elif effect["op"] == "mark.add":
                    from lab import mark_runtime as marks
                    value, extra = marks.change_marks(target.get("field_marks"), effect["mark_id"],
                        effect["stacks"], context=context, source={"skill_id": program["game_id"],
                        "source_hash": program["source_hash"], "config_hash": CONFIG_HASH})
                    target["field_marks"] = value
                    events.extend({**entry, "target": effect["target"], "response_success": True}
                                  for entry in extra)
                    continue
                elif effect["op"] == "status.add":
                    primitive = deepcopy(program)
                    primitive["operations"] = [{"op": "status.add", "params": {
                        key: deepcopy(value) for key, value in effect.items() if key != "op"}}]
                    policy = deepcopy(context)
                    policy.pop("resolved_energy_cost", None)
                    fragment = execute_effects(primitive, owned, policy)
                    if fragment["status"] != "applied":
                        raise ValueError("; ".join(fragment["blockers"]))
                    owned = fragment["state"]
                    events.extend({**entry, "response_success": True, "defense_policy": POLICY}
                                  for entry in fragment["events"])
                    continue
                elif effect["op"] == "stat.modify":
                    for attribute in effect["attributes"]:
                        target["stat_modifiers"].setdefault(attribute, []).append(deepcopy(effect["percent"]))
                        from lab.modifier_ledger import register_stat
                        register_stat(target, attribute, source_kind="skill", source_id=program["game_id"], source_hash=program["source_hash"])
                elif effect["op"] == "hp.restore":
                    amount = target["max_hp"] * effect["percent"] // 100
                    before = target["hp"]
                    target["hp"] = min(target["max_hp"], before + amount)
                    event.update(before=before, after=target["hp"], amount=target["hp"] - before)
                else:
                    amount = (opponent_effective_cost * effect["opponent_cost_multiplier"]
                              if "opponent_cost_multiplier" in effect else effect["amount"])
                    if effect['op'] == 'energy.restore' and target.get('timed_effects'):
                        from lab.duration_runtime import recovery_amount
                        amount = recovery_amount(target, amount, turn)['amount']
                    before = target["energy"]
                    from lab.trait_runtime import energy_allows_overflow, after_energy_gain
                    target["energy"] = ((before + amount if energy_allows_overflow(target) else min(target["max_energy"], before + amount))
                        if effect["op"] == "energy.restore" else max(0, before - amount))
                    event.update(before=before, after=target["energy"], resolved_amount=amount)
                event.update(response_success=True, policy=POLICY)
                events.append(event)
                if effect['op'] == 'energy.restore':
                    events.extend({**e,'target':effect['target']} for e in after_energy_gain(target,target['energy']-before,{'turn':turn}))
        result.update(status="applied", state=owned, events=events,
                      response_success=checked["response_success"])
    except (ValueError, TypeError, KeyError) as exc:
        result["blockers"] = [str(exc)]
    return result


def mitigate_damage(raw_damage, member, turn, *, damage_kind):
    """Return pre-HP-clip integer damage; no actor/member inputs are mutated."""
    _integer(raw_damage, "raw damage")
    _integer(turn, "turn", 1)
    if damage_kind not in {"physical", "magical", "status", "environment"}:
        raise ValueError("Explicit damage kind required for defense mitigation")
    guard = member.get("defense_runtime", {})
    if guard and guard.get("policy") != POLICY:
        raise ValueError("Unknown defense runtime policy")
    damage = raw_damage
    if guard.get("guard_turn") == turn and damage_kind in {"physical", "magical"}:
        ratio = guard.get("reduction", {})
        numerator, denominator = ratio.get("numerator"), ratio.get("denominator")
        if type(numerator) is not int or denominator != 100 or not 0 <= numerator <= 100:
            raise ValueError("Invalid source-bound defense reduction")
        damage = raw_damage * (100 - numerator) // 100
    return {"damage": damage, "raw_damage": raw_damage, "prevented": raw_damage - damage,
            "policy": POLICIES["damage"], "source_hash": guard.get("source_hash"),
            "hp_clipped": False, "calibrated": False}


def finish_turn(member, turn):
    """Expire the guard, retaining absolute cooldown across swaps/idle turns."""
    _integer(turn, "turn", 1)
    owned = deepcopy(member)
    guard = owned.get("defense_runtime")
    if guard:
        if guard.get("policy") != POLICY:
            raise ValueError("Unknown defense runtime policy")
        if guard.get("guard_turn", 0) <= turn:
            guard.pop("guard_turn", None)
            guard.pop("reduction", None)
    return owned


def preflight_departure(catalog, state, side, program, *, opponent_kind,
                        replacement_slot=None, opponent_replacement_slot=None):
    """Validate the target owner's declared choice before defense payment."""
    _validate_program(program)
    spec = program["defense_components"].get("departure")
    if spec is None or (spec["when"] == "response.success" and not response_success(program, opponent_kind)):
        return None
    if side not in ("a", "b"):
        raise ValueError("Invalid defense departure side")
    if spec.get('timing') == 'round.end':
        return {'target_side': side, 'target': 'self', 'cause': spec['cause'],
                'timing': 'round.end', 'policy': END_RETURN_POLICY}
    if spec['target'] == 'both':
        from lab import forced_switch_runtime as forced
        return {'target': 'both', 'selections': [forced.preflight_departure(catalog, state, target,
            spec['cause'], choice) for target, choice in ((('b' if side == 'a' else 'a'), opponent_replacement_slot),
            (side, replacement_slot))], 'policy': spec['order_policy']}
    target_side = side if spec["target"] == "self" else "b" if side == "a" else "a"
    choice = replacement_slot if spec["target"] == "self" else opponent_replacement_slot
    team = state["teams"][target_side]
    actor = team["members"][team["active_slot"]]
    eligibility = prepare_rules(catalog)._components()[2].departure(spec["cause"],
        actor["entered_turn"], state["turn"], actor["charge"] is not None, actor["rooted"])
    if eligibility["status"] == "unresolved":
        raise ValueError(eligibility["reason"])
    candidates = [i for i, member in enumerate(team["members"])
                  if i != team["active_slot"] and member["hp"] > 0]
    if actor["hp"] > 0 and eligibility["status"] == "allowed" and candidates and (
            type(choice) is not int or choice not in candidates):
        raise ValueError("Defense departure requires explicit target-owner replacement slot")
    return {"target_side": target_side, "target": spec["target"], "cause": spec["cause"],
            "replacement_slot": choice, "eligible": eligibility, "policy": DEPARTURE_POLICY}


def after_defense(catalog, state, side, program, *, opponent_kind, context, event_token,
                  replacement_slot=None, opponent_replacement_slot=None):
    """Whole-state posthook after a committed defense; slots belong to the target."""
    from lab import forced_switch_runtime as forced
    result = {"status": "applied", "state": deepcopy(state), "events": [], "blockers": [],
              "training_eligible": False}
    try:
        selection = preflight_departure(catalog, state, side, program, opponent_kind=opponent_kind,
            replacement_slot=replacement_slot, opponent_replacement_slot=opponent_replacement_slot)
        if selection is None:
            return result
        if context.get("defense_departure_policy") != DEPARTURE_POLICY:
            raise ValueError("Explicit target-owner defense departure experiment policy required")
        if selection.get('timing') == 'round.end':
            actor = result['state']['teams'][side]['members'][result['state']['teams'][side]['active_slot']]
            if actor['hp'] <= 0:
                return result
            pending = {'turn': state['turn'], 'member_id': actor['member_id'], 'entered_turn': actor['entered_turn'],
                'skill_id': program['game_id'], 'source_hash': program['source_hash'], 'config_hash': CONFIG_HASH,
                'event_token': event_token, 'policy': END_RETURN_POLICY}
            previous = actor.get('defense_departure_pending')
            if previous is not None and previous != pending:
                raise ValueError('Conflicting defense round-end departure source')
            if previous == pending:
                return result
            actor['defense_departure_pending'] = pending
            result['events'].append({'op': 'defense.departure_pending', 'side': side, **deepcopy(pending)})
            return result
        if selection.get('target') == 'both':
            return forced.execute_departures(catalog, state, selection['selections'],
                event_token=event_token, context=context, source_skill_id=program['game_id'],
                source_hash=program['source_hash'], order_policy=selection['policy'])
        team = state["teams"][selection["target_side"]]
        if team["members"][team["active_slot"]]["hp"] <= 0:
            return result
        result = forced.execute_forced_switch_fragment(catalog, state, selection["target_side"],
            selection["cause"], target_slot=selection["replacement_slot"],
            context={**deepcopy(context), "snapshot_id": prepare_rules(catalog).snapshot_id,
                     "forced_switch_policies": forced.policies(), "event_token": event_token})
        result["events"].insert(0, {"op": "defense.departure", **selection,
            "source_skill_id": program["game_id"], "source_hash": program["source_hash"]})
    except (ValueError, TypeError, KeyError) as exc:
        result.update(status="blocked", blockers=[str(exc)])
    return result


def end_round_departures(catalog, state, *, context):
    """Original active entry only; leaving/exhaustion cancels the one-turn listener."""
    from lab import forced_switch_runtime as forced
    result = {'status': 'applied', 'state': deepcopy(state), 'events': [], 'blockers': [], 'training_eligible': False}
    try:
        if context.get('defense_end_return_policy') != END_RETURN_POLICY:
            raise ValueError('Explicit defense end-return experiment policy required')
        from lab.forced_switch_programs import programs as forced_programs
        trusted = {**defense_programs(catalog), **forced_programs(catalog)}
        for side in ('a', 'b'):
            # Snapshot identities; an earlier return replaces owned member objects.
            pending_members = [m['member_id'] for m in result['state']['teams'][side]['members']
                               if m.get('defense_departure_pending') is not None]
            for member_id in pending_members:
                team = result['state']['teams'][side]
                member = next(m for m in team['members'] if m['member_id'] == member_id)
                pending = member['defense_departure_pending']
                if not isinstance(pending, dict):
                    raise ValueError('Malformed defense end-return ledger')
                program = trusted.get(pending.get('skill_id'))
                spec = (program.get('forced_switch_components') or program.get('defense_components', {}).get('departure', {})) if program else {}
                source_config = program.get('forced_switch_config_hash', CONFIG_HASH) if program else None
                if (program is None or spec.get('timing') != 'round.end'
                        or pending != {'turn': result['state']['turn'], 'member_id': member_id,
                            'entered_turn': pending.get('entered_turn'), 'skill_id': program['game_id'],
                            'source_hash': program['source_hash'], 'config_hash': source_config,
                            'event_token': pending.get('event_token'), 'policy': END_RETURN_POLICY}
                        or type(pending.get('entered_turn')) is not int or pending['entered_turn'] < 0
                        or not isinstance(pending.get('event_token'), str) or not pending['event_token']):
                    raise ValueError('Defense end-return ledger source or turn differs')
                before_departure = deepcopy(result['state'])
                member.pop('defense_departure_pending')
                if (member['hp'] <= 0 or team['members'][team['active_slot']]['member_id'] != member_id
                        or member['entered_turn'] != pending['entered_turn']):
                    result['events'].append({'op': 'defense.departure_cancelled', 'side': side,
                        'member_id': member_id, 'reason': 'original_active_entry_no_longer_live', **deepcopy(pending)})
                    continue
                fragment = forced.execute_forced_switch_fragment(catalog, result['state'], side, spec.get('cause', 'return'),
                    context={**deepcopy(context), 'snapshot_id': prepare_rules(catalog).snapshot_id,
                        'forced_switch_policies': forced.policies(), 'event_token': pending['event_token'] + ':round.end'})
                if fragment['status'] != 'applied':
                    result.update(status='blocked', state=before_departure, blockers=fragment['blockers'],
                                  partial_commit=bool(result['events']))
                    return result
                result['state'] = fragment['state']
                result['events'].extend({**e, 'source_skill_id': program['game_id'],
                    'source_hash': program['source_hash'], 'defense_end_return_policy': END_RETURN_POLICY}
                    for e in fragment['events'])
    except (ValueError, TypeError, KeyError) as exc:
        result.update(status='blocked', blockers=[str(exc)])
    return result


def schedule_round_end_departure(state, target_side, program, *, event_token):
    """Use the same source-bound end queue for response attacks and defenses."""
    result = {'status':'applied','state':deepcopy(state),'events':[],'blockers':[]}
    team = result['state']['teams'][target_side]
    actor = team['members'][team['active_slot']]
    if actor['hp'] <= 0:
        return result
    pending = {'turn':state['turn'],'member_id':actor['member_id'],'entered_turn':actor['entered_turn'],
        'skill_id':program['game_id'],'source_hash':program['source_hash'],
        'config_hash':program.get('forced_switch_config_hash', CONFIG_HASH),
        'event_token':event_token,'policy':END_RETURN_POLICY}
    previous = actor.get('defense_departure_pending')
    if previous is not None and previous != pending:
        result.update(status='blocked',blockers=['Multiple distinct end departures on the same entry have unverified ordering'])
        return result
    if previous != pending:
        actor['defense_departure_pending'] = pending
        result['events'].append({'op':'defense.departure_pending','side':target_side,**deepcopy(pending)})
    return result


def received_effects(member, turn):
    guard=member.get('defense_runtime',{})
    if guard.get('guard_turn') is None:return []
    if type(turn) is not int:raise ValueError('Active defense requires explicit current turn')
    if guard.get('guard_turn')!=turn or not guard.get('response_success'):return []
    row=_configuration(CONFIG.stat().st_mtime_ns)['skills'].get(str(guard.get('skill_id')))
    if row is None or guard.get('source_hash')!=row['record_hash']:
        raise ValueError('Received-hit defense source changed')
    return row['components'].get('received_effects',[])


def resolve_received_damage(resolver, params, state, context):
    target=state[params['target']]
    effects=received_effects(target,context.get('turn'))
    mitigation=None
    if any(e['op']=='hp.restore_prevented' for e in effects):
        if not callable(getattr(resolver,'explain',None)):
            raise ValueError('Defense absorption requires resolver.explain with actual prevented damage')
        receipt=resolver.explain(deepcopy(params),deepcopy(state),deepcopy(context))
        mitigation=receipt.get('defense_mitigation')
        if not isinstance(mitigation,dict) or mitigation.get('source_hash')!=target['defense_runtime']['source_hash']:
            raise ValueError('Defense absorption mitigation source missing')
        _integer(mitigation.get('prevented'),'prevented damage')
        loss=receipt['actual_hp_loss']
    else:
        loss=resolver(deepcopy(params),deepcopy(state),deepcopy(context))
        survival=prevent_lethal(target,loss,context.get('turn'))
        loss=survival['damage']
        mitigation={'survival_event':survival['event']} if survival['event'] else None
    from lab.trait_runtime import before_hp_loss_relative
    counter=target.get('direct_damage_packet_counter',0)
    if type(counter) is not int or counter<0:raise ValueError('Direct damage packet cursor malformed')
    target['direct_damage_packet_counter']=counter+1
    token=f"{context.get('turn')}:{context.get('actor_member_id')}:{target.get('member_id')}:direct:{counter}"
    protected=before_hp_loss_relative(state,params['target'],loss,context,token)
    if protected['events']:
        mitigation={**(mitigation or {}),'trait_events':protected['events']}
    return protected['damage'],mitigation


def after_received_damage(member, actual_loss, mitigation, turn):
    effects=received_effects(member,turn)
    trait_events=deepcopy((mitigation or {}).get('trait_events',[]))
    if not effects or member['hp']<=0:return trait_events
    source=member['defense_runtime'];events=[]
    if mitigation and mitigation.get('survival_event'):events.append(mitigation['survival_event'])
    for effect in effects:
        if effect['op']=='hp.restore_prevented':
            if mitigation is None:raise ValueError('Prevented damage receipt required')
            before=member['hp'];member['hp']=min(member['max_hp'],before+mitigation['prevented'])
            events.append({'op':'defense.absorb_heal','before':before,'after':member['hp'],
                'amount':member['hp']-before,'prevented':mitigation['prevented']})
        elif effect['op']=='stat.modify' and actual_loss>0:
            from lab.modifier_ledger import enhance_buff_amount,register_stat
            from fractions import Fraction
            for attr in effect['attributes']:
                bid=effect['buff_ids'][attr]
                amount=enhance_buff_amount(member,bid,attr,Fraction(effect['percent'],100))
                member.setdefault('stat_modifiers',{}).setdefault(attr,[]).append({'numerator':amount.numerator,'denominator':amount.denominator})
                register_stat(member,attr,source_kind='skill',source_id=source['skill_id'],source_hash=source['source_hash'],buff_id=bid)
            events.append({'op':'defense.received_stats','attributes':effect['attributes'],'percent':effect['percent'],'actual_hp_loss':actual_loss})
    return trait_events + [{**e,'source_skill_id':source['skill_id'],'source_hash':source['source_hash'],
        'policy':e.get('policy','after_each_positive_actual_attack_hit_stats_prevented_heal_before_next_hit_v1')} for e in events]


def after_attack_retaliation(resolver, params, state, context, actual_loss, *, token):
    """React to one positive attack hit, including the owner's fatal hit, once."""
    if (params.get('target') != 'opponent' or actual_loss <= 0
            or params.get('kind') not in ('physical', 'magical')
            or context.get('damage_source_kind') == 'trait.retaliation'):
        return []
    from lab.trait_switch_components import retaliation_source
    owner, target = state['opponent'], state['self']
    source = retaliation_source(owner)
    if source is None or target['hp'] <= 0:
        return []
    callback = getattr(resolver, 'retaliation', None)
    if not callable(callback):
        raise ValueError('Thorns retaliation requires the shared source-bound HUD retaliation resolver')
    actor_side = context.get('actor_side')
    reverse_side = {'a': 'b', 'b': 'a'}.get(actor_side)
    reverse = {'self': owner, 'opponent': target}
    reaction_context = {**context, 'actor_side': reverse_side, 'actor_member_id': owner['member_id'],
                        'damage_source_kind': 'trait.retaliation', 'response_success': False}
    receipt = callback(deepcopy(source), deepcopy(reverse), deepcopy(reaction_context))
    loss = receipt.get('actual_hp_loss')
    _integer(loss, 'retaliation actual HP loss')
    if loss > target['hp']:
        raise ValueError('Retaliation resolver exceeds the actual remaining HP')
    from lab.trait_runtime import before_hp_loss_relative
    protection = before_hp_loss_relative(reverse, 'opponent', loss, reaction_context, token)
    mitigation = {**receipt.get('defense_mitigation', {}), 'trait_events': protection['events']}
    before = target['hp']
    target['hp'] -= protection['damage']
    events = [{'op': 'trait.retaliation', **source, 'damage_kind': 'physical', 'damage_type': '无系别',
        'actor_side': reverse_side, 'actor_member_id': owner['member_id'], 'actor_form_id': owner['form_id'],
        'target_side': actor_side, 'target_member_id': target['member_id'], 'target_form_id': target['form_id'],
        'target': 'self', 'before': before, 'after': target['hp'], 'damage': protection['damage'],
        'turn': context.get('turn'), 'token': token, 'nominal_damage': receipt['nominal_damage']}]
    # No recursive attack hook: this is a trait packet, never an ordinary cast.
    for event in after_received_damage(target, protection['damage'], mitigation, context.get('turn')):
        mapped = deepcopy(event)
        mapped['target'] = 'opponent' if event.get('target') == 'self' else 'self'
        mapped['target_side'] = reverse_side if mapped['target'] == 'opponent' else actor_side
        events.append(mapped)
    return events


def prevent_lethal(member, loss, turn):
    _integer(loss,'incoming HP loss')
    effects=received_effects(member,turn)
    effect=next((e for e in effects if e['op']=='hp.prevent_lethal'),None)
    if effect is None or member['hp']<=0 or loss<member['hp']:
        return {'damage':loss,'event':None}
    damage=max(0,member['hp']-effect['remaining_hp'])
    source=member['defense_runtime']
    return {'damage':damage,'event':{'op':'defense.prevent_lethal','before_loss':loss,'after_loss':damage,
        'remaining_hp':effect['remaining_hp'],'source_skill_id':source['skill_id'],'source_hash':source['source_hash'],
        'policy':'every_lethal_damage_during_successful_guard_turn_keep_one_no_consumption_v1'}}
