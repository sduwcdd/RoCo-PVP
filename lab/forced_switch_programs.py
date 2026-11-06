"""Whole-description reviewed departure skills and source-ordered follow-ups."""
from copy import deepcopy
import json
from pathlib import Path

from lab import forced_switch_runtime as forced
from lab.prepared_rules import prepare_rules
from lab.ruleset import canonical_hash

CONFIG = Path(__file__).resolve().parents[1] / "data/rules/reviewed-forced-switch-skills-1.json"
CONFIG_HASH = '2f4a987e588fc4d6db269866825daf88b5d4b429c6976536d0d6c2c6551e0ab2'


def _configuration():
    config = json.loads(CONFIG.read_text(encoding="utf8"))
    if canonical_hash(config) != CONFIG_HASH:
        raise ValueError("Forced-switch whole-description configuration changed")
    return config


def programs(catalog):
    prepared = prepare_rules(catalog)
    config = _configuration()
    if prepared.snapshot_id != config["snapshot_id"]:
        raise ValueError("Forced-switch skill catalog snapshot changed")
    result = {}
    for key, row in config["skills"].items():
        record = prepared._rules._catalog["moves"].get(key)
        if record != row["record"] or canonical_hash(record) != row["record_hash"]:
            raise ValueError("Forced-switch skill whole source changed: " + key)
        program = deepcopy(prepared._rules.program(int(key)))
        program.pop("native_rule", None)
        program.update(status="compiled", blockers=[], operations=deepcopy(row["before_operations"]),
            forced_switch_components={"cause": row["cause"], "target": row["target"],
                                      "after_operations": deepcopy(row["after_operations"]), "inherit_buffs": row.get("inherit_buffs", False),
                                      "priority_delta": row.get("priority_delta", 0), "timing":row.get("timing", "after.use"),
                                      "response_only":row.get("response_only",False)},
            forced_switch_evidence=deepcopy(row), forced_switch_config_hash=CONFIG_HASH,
            forced_switch_policies=deepcopy(config["policies"]), response_kinds=deepcopy(row.get("response_kinds", [])),
            dependency_ids=deepcopy(record["desc_notes"]), executable=False, real_game_verified=False)
        result[int(key)] = program
    return result


def preflight_selection(catalog, state, side, skill_id, replacement_slot, opponent_replacement_slot=None):
    """Check caller choice before payment/damage without changing state or RNG."""
    program = programs(catalog).get(skill_id)
    if program is None:
        raise ValueError("Skill is not a reviewed forced-switch whole description")
    spec = program["forced_switch_components"]
    if spec.get('timing') == 'round.end':
        return {'timing':'round.end','source_hash':program['source_hash']}
    if spec['target'] == 'both':
        return {'selections': [forced.preflight_departure(catalog, state, target, spec['cause'], choice)
            for target, choice in ((('b' if side == 'a' else 'a'), opponent_replacement_slot), (side, replacement_slot))],
            'source_hash': program['source_hash'], 'policy': program['forced_switch_policies']['dual_order']}
    target_side = side if spec["target"] == "self" else "b" if side == "a" else "a"
    team = state["teams"][target_side]
    actor = team["members"][team["active_slot"]]
    switches = prepare_rules(catalog)._components()[2]
    eligibility = switches.departure(spec["cause"], actor["entered_turn"], state["turn"],
                                      actor["charge"] is not None, actor["rooted"])
    if eligibility["status"] == "unresolved":
        raise ValueError(eligibility["reason"])
    candidates = [i for i, member in enumerate(team["members"])
                  if i != team["active_slot"] and member["hp"] > 0]
    if spec["cause"] == "detach" and eligibility["status"] == "allowed" and candidates and (
            type(replacement_slot) is not int or replacement_slot not in candidates):
        raise ValueError("Reviewed detach skill requires an explicit living replacement_slot before damage")
    return {"eligibility": eligibility, "living_candidates": candidates,
            "replacement_slot": replacement_slot, "source_hash": program["source_hash"]}


def after_skill(catalog, state, side, skill_id, *, replacement_slot, event_token, context, opponent_replacement_slot=None):
    """Return a component result; callers retain prior committed skill damage on failure."""
    program = programs(catalog).get(skill_id)
    if program is None:
        raise ValueError("Unknown reviewed forced-switch skill")
    spec = program["forced_switch_components"]
    if spec.get('response_only') and context.get('response_success') is not True:
        return {'status':'applied','state':deepcopy(state),'events':[],'blockers':[]}
    if spec.get('timing') == 'round.end':
        from lab.defense_runtime import schedule_round_end_departure
        target_side = side if spec['target'] == 'self' else 'b' if side == 'a' else 'a'
        return schedule_round_end_departure(state, target_side, program, event_token=event_token)

    if spec['target'] == 'both':
        selection = preflight_selection(catalog, state, side, skill_id, replacement_slot, opponent_replacement_slot)
        return forced.execute_departures(catalog, state, selection['selections'],
            event_token=event_token, context=context, source_skill_id=skill_id,
            source_hash=program['source_hash'], order_policy=selection['policy'])
    target_side = side if spec["target"] == "self" else "b" if side == "a" else "a"
    team = state["teams"][target_side]
    if team["members"][team["active_slot"]]["hp"] <= 0:
        return {"status": "applied", "state": deepcopy(state), "events": [{"op": "switch.forced_skipped",
                "side": target_side, "cause": spec["cause"], "reason": "exhausted_target"}], "blockers": []}
    inherited = ({'buff_inheritance': {'source_skill_id':skill_id, 'source_hash':program['source_hash'], 'token':event_token}}
                 if spec.get('inherit_buffs') else {})
    fragment = forced.execute_forced_switch_fragment(catalog, state, target_side, spec["cause"],
        target_slot=replacement_slot if spec["cause"] == "detach" else None,
        context={**deepcopy(context), **inherited, "snapshot_id": prepare_rules(catalog).snapshot_id,
                 "forced_switch_policies": forced.policies(), "event_token": event_token})
    if fragment["status"] != "applied" or not fragment.get("switch_fragment_executed"):
        return fragment
    try:
        current, events = deepcopy(fragment["state"]), deepcopy(fragment["events"])
        owner = current["teams"][target_side]
        incoming = owner["members"][owner["active_slot"]]
        for operation in spec["after_operations"]:
            if operation != {"op": "energy.restore", "target": "incoming", "amount": 8}:
                raise ValueError("Unreviewed forced-switch follow-up operation")
            if incoming["hp"] <= 0:
                events.append({"op": "switch.followup_skipped", "reason": "incoming_exhausted",
                               "member_id": incoming["member_id"], "skill_id": skill_id})
                continue
            energy, maximum = incoming.get("energy"), incoming.get("max_energy")
            from lab.trait_runtime import energy_allows_overflow, after_energy_gain
            overflow = energy_allows_overflow(incoming)
            if type(energy) is not int or type(maximum) is not int or energy < 0 or maximum < 0 or (energy > maximum and not overflow):
                raise ValueError("Incoming follow-up needs valid explicit energy/max_energy")
            from lab.duration_runtime import recovery_amount
            requested = recovery_amount(incoming, 8, current["turn"])["amount"]
            amount = requested if overflow else min(requested, maximum - energy)
            incoming["energy"] += amount
            events.extend({**e, "target_side": target_side, "target_member_id": incoming["member_id"]} for e in after_energy_gain(incoming, amount, {"turn":current["turn"]}))
            events.append({"op": "energy.restore", "target": "self", "target_side": target_side,
                           "target_member_id": incoming["member_id"], "requested": 8,
                           "amount": amount, "before": energy, "after": incoming["energy"],
                           "source_skill_id": skill_id, "source_hash": program["source_hash"],
                           "phase": "after_forced_entry", "policy": program["forced_switch_policies"]["post_followup"]})
        fragment.update(state=current, events=events)
        return fragment
    except (ValueError, KeyError, TypeError) as exc:
        return {"status": "blocked", "state": deepcopy(state), "events": [], "blockers": [str(exc)],
                "training_eligible": False, "post_switch_rolled_back": True}
