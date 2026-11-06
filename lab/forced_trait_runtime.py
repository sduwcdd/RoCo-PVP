"""Source-bound descriptions that trigger reviewed departure components."""
from copy import deepcopy
import json
from pathlib import Path

from lab import forced_switch_runtime as forced
from lab.prepared_rules import prepare_rules
from lab.ruleset import canonical_hash

CONFIG = Path(__file__).resolve().parents[1] / "data/rules/reviewed-forced-switch-traits-1.json"
CONFIG_HASH = 'ceee9970e98061fb59db260e7a0f04246107cbc8a03c07cf9806e99a503fb4f1'


def _config():
    config = json.loads(CONFIG.read_text(encoding="utf8"))
    if canonical_hash(config) != CONFIG_HASH:
        raise ValueError("Forced-trait source configuration changed")
    return config


def policies():
    return deepcopy(_config()["policies"])


def source_evidence(rules, member):
    """Shared exact-form/source validation for departures and HUD admission."""
    from lab.trait_runtime import POLICY as TRAIT_POLICY, CONFIG_HASH as TRAIT_CONFIG_HASH
    config = _config()
    if rules.snapshot_id != config['snapshot_id']:
        raise ValueError('Forced-trait snapshot differs from its reviewed source')
    tid = rules.form(member['form_id']).get('trait_id')
    if member.get('trait_id', tid) != tid:
        raise ValueError('Forced-trait identity conflicts with its exact form')
    row = config['traits'].get(str(tid))
    if row is None:
        return None
    raw = rules._catalog['traits'].get(str(tid))
    if raw != row['record'] or canonical_hash(raw) != row['record_hash']:
        raise ValueError('Forced-trait whole source changed')
    if (member.get('trait_source_hash', row['record_hash']) != row['record_hash']
            or member.get('trait_policy', TRAIT_POLICY) != TRAIT_POLICY
            or member.get('trait_config_hash', TRAIT_CONFIG_HASH) != TRAIT_CONFIG_HASH):
        raise ValueError('Forced-trait member source binding changed')
    return {'trait_id': tid, 'source_hash': row['record_hash'], 'record': deepcopy(raw),
            'config_hash': CONFIG_HASH, 'policies': deepcopy(config['policies']),
            'components': {'cause': 'return' if tid == 200290 else 'detach'}}


def evidence(catalog, state, member):
    from lab.trait_runtime import POLICY as TRAIT_POLICY
    if 'trait_policy' not in state:
        return None
    if state['trait_policy'] != TRAIT_POLICY:
        raise ValueError('Unknown trait research policy')
    prepared = prepare_rules(catalog)
    if state.get('snapshot_id') != prepared.snapshot_id:
        raise ValueError('Forced-trait snapshot differs from its reviewed source')
    return source_evidence(prepared._rules, member)


def _active(state, side):
    team = state["teams"][side]
    return team["members"][team["active_slot"]]


def preflight_selection(catalog, state, side, replacement_slot, action=None):
    """Require choices before committed actions, including possible energy-zero triggers."""
    actor = _active(state, side)
    source = evidence(catalog, state, actor)
    if source is None or source["trait_id"] == 200290 or actor["hp"] <= 0:
        return source
    if isinstance(action, dict):
        if action.get("suppressed_action") and source["trait_id"] != 200092:
            return source
        if action.get("kind") == "switch":
            return source
        if source["trait_id"] == 200105:
            skill_id = action.get("skill_id")
            if skill_id is None and action.get("kind") == "skill" and type(action.get("slot")) is int:
                skill_id = actor["skill_slots"][action["slot"]]
            if (action.get("kind") != "skill" or skill_id is None
                    or prepare_rules(catalog)._rules.skill(skill_id)["kind"] != "defense"
                    or action.get("execution_phase") == "charge_setup_not_attack_release"):
                return source
    switches = prepare_rules(catalog)._components()[2]
    eligibility = switches.departure("detach", actor["entered_turn"], state["turn"],
                                      actor["charge"] is not None, actor["rooted"])
    candidates = [i for i, m in enumerate(state["teams"][side]["members"])
                  if i != state["teams"][side]["active_slot"] and m["hp"] > 0]
    if eligibility["status"] == "unresolved":
        raise ValueError(eligibility["reason"])
    if eligibility["status"] == "allowed" and candidates and (
            type(replacement_slot) is not int or replacement_slot not in candidates):
        raise ValueError("Forced-departure trait requires explicit living replacement_slot before action")
    return source


def _apply(catalog, state, side, source, choice, token, context):
    return forced.execute_forced_switch_fragment(catalog, state, side, source["components"]["cause"],
        target_slot=None if source["trait_id"] == 200290 else choice,
        context={**deepcopy(context), "snapshot_id": prepare_rules(catalog).snapshot_id,
                 "forced_switch_policies": forced.policies(), "event_token": token})


def bind_round_choices(catalog, state, actions):
    """Bind watchful's round-end choice even when its ordinary action is skipped."""
    current = deepcopy(state)
    for side in ("a", "b"):
        actor = _active(current, side)
        choice = actions[side].get("replacement_slot")
        source = preflight_selection(catalog, current, side, choice, actions[side])
        if actions[side].get("kind") == "switch":
            continue
        if source and source["trait_id"] == 200092 and actor["hp"] > 0:
            actor["forced_trait_pending"] = {"turn": current["turn"], "trait_id": 200092,
                "member_id": actor["member_id"], "source_hash": source["source_hash"],
                "config_hash": CONFIG_HASH, "replacement_slot": choice,
                "action_token": f"{current['turn']}:{side}:{actor['member_id']}:watchful"}
    state.clear()
    state.update(current)
    return state


def after_action(catalog, state, side, action, *, replacement_slot, context):
    """Record deferred triggers or execute protection after this committed actor acts."""
    current = deepcopy(state)
    actor = _active(current, side)
    result = {"status": "applied", "state": current, "events": [], "blockers": [], "training_eligible": False}
    if actor["hp"] <= 0 or action.get("actor_member_id") != actor["member_id"]:
        return result
    source = evidence(catalog, current, actor)
    if source is None:
        return result
    tid = source["trait_id"]
    token = f"{current['turn']}:{side}:{actor['member_id']}:{action.get('skill_id')}:{action.get('slot')}"
    if tid == 200262:
        pending=actor.get('sentry_prediction')
        if not pending or pending.get('turn')!=current['turn'] or pending.get('triggered') is not True:
            return result
        actor.pop('sentry_prediction',None)
        return _apply(catalog,current,side,source,replacement_slot,'trait-action:'+token,context)
    if tid == 200165:
        return _apply(catalog, current, side, source, replacement_slot, "trait-action:" + token, context)
    if tid == 200092:
        trigger = True
    elif action.get("kind") == "skill" and action.get("execution_phase") != "charge_setup_not_attack_release":
        skill = prepare_rules(catalog)._rules.skill(action["skill_id"])
        from lab.weather_runtime import resolved_skill_type
        kind, skill_type = skill["kind"], resolved_skill_type(current.get("weather"), action["skill_id"], skill["type"])
        trigger = tid == 200105 and kind == "defense" or tid == 200290 and skill_type == "光系"
    else:
        trigger = False
    if trigger:
        actor["forced_trait_pending"] = {"turn": current["turn"], "trait_id": tid,
            "member_id": actor["member_id"], "source_hash": source["source_hash"],
            "config_hash": CONFIG_HASH, "replacement_slot": replacement_slot, "action_token": token}
        result["events"].append({"op": "trait.forced_departure_pending", "side": side,
            "member_id": actor["member_id"], "trait_id": tid, "source_hash": source["source_hash"], "policies": policies()})
    return result


def end_round(catalog, state, *, context):
    """Process a then b; a later failure retains earlier committed departure events."""
    current = deepcopy(state)
    events = []
    for side in ("a", "b"):
        actor = _active(current, side)
        source = evidence(catalog, current, actor)
        pending = actor.get("forced_trait_pending")
        if not pending or pending.get("turn") != current["turn"] or actor["hp"] <= 0:
            continue
        if (source is None or pending.get("trait_id") != source["trait_id"]
                or pending.get("source_hash") != source["source_hash"]
                or pending.get("config_hash") != CONFIG_HASH or pending.get("member_id") != actor["member_id"]):
            return {"status": "blocked", "state": current, "events": events,
                    "blockers": ["Deferred forced-trait source binding changed"], "training_eligible": False}
        if source["trait_id"] == 200290 and actor.get('other_automatic_departure_turn') == current['turn']:
            actor.pop('forced_trait_pending',None)
            events.append({'op':'trait.return.suppressed','side':side,'member_id':actor['member_id'],
                'reason':'other_automatic_departure','source':'user_confirmation_20261030'})
            continue
        if source["trait_id"] == 200092 and actor["energy"] != 0:
            actor.pop("forced_trait_pending")
            continue
        fragment = _apply(catalog, current, side, source, pending["replacement_slot"],
                          "trait-round-end:" + pending["action_token"], context)
        if fragment["status"] != "applied":
            return {"status": "blocked", "state": current, "events": events,
                    "blockers": fragment["blockers"], "training_eligible": False}
        current = fragment["state"]
        events.extend(fragment["events"])
        for member in current["teams"][side]["members"]:
            if member["member_id"] == pending["member_id"]:
                member.pop("forced_trait_pending", None)
    return {"status": "applied", "state": current, "events": events, "blockers": [], "training_eligible": False}
