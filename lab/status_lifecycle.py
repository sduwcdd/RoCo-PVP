"""Composable status bookkeeping and explicitly named research consequences.

Only the small reviewed freeze/leech subset is adapted here. Generic lifecycle
parameters are caller declarations, not a claim to execute every BUFF_CONF row.
Weather and ordinary freeze share the reviewed weather threshold configuration.
"""
from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
import hashlib
import json
from pathlib import Path


POLICY = "source_bound_freeze_leech_lifecycle_v1"
LEECH_POLICY = "leech_target_max_hp_two_percent_per_layer_floor_source_member_actual_loss_v1"
SOURCE_REFRESH_POLICY = "latest_application_rebinds_all_layers_research_v1"
LEECH_SOURCE_PATH = Path(__file__).resolve().parents[1] / "artifacts/strength_buff_probe_20261025/historical/pakchunk4-WindowsNoEditor_3_P.pak/BUFF_CONF.json"
LEECH_SOURCE_HASH = "b3dc43c3181f5b07575b383969659070b07e9ceda4b3aa2e305f83340b2405e5"
LEECH_DEFINITION = "每回合受到2%伤害，并恢复敌方等量生命值。（草系精灵免疫此效果）"


def _count(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


@lru_cache(maxsize=2)
def _leech_source(stamp):
    raw = LEECH_SOURCE_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != LEECH_SOURCE_HASH:
        raise ValueError("Leech source changed; its transfer direction needs re-review")
    row = json.loads(raw)["20050010"]
    if row["desc"] != LEECH_DEFINITION or row["add_max"] != 99:
        raise ValueError("Leech source differs from the reviewed status")
    return {"buff_id": row["id"], "description": row["desc"], "max_stacks": row["add_max"],
            "raw_clean_when_rest": row["is_clean_when_rest"],
            "path": LEECH_SOURCE_PATH.relative_to(Path(__file__).resolve().parents[1]).as_posix(),
            "content_sha256": LEECH_SOURCE_HASH,
            "version_scope": "installed_patch3_not_verified_online_override"}


def leech_source():
    return deepcopy(_leech_source(LEECH_SOURCE_PATH.stat().st_mtime_ns))


def enabled(context):
    value = context.get("status_lifecycle_policy")
    if value is not None and value != POLICY:
        raise ValueError("Unknown status lifecycle capability policy")
    return value == POLICY


def research_context():
    """Optional bridge for trusted factories; legacy isolated contexts stay strict."""
    from lab.weather_runtime import rules
    return {"status_lifecycle_policy": POLICY, "leech_policy": LEECH_POLICY,
            "status_policies": {
                name: {"stacking": "add_to_declared_count", "cap": cap, "immunity_type": immunity}
                for name, immunity, cap in (("poison", "毒系", None), ("burn", "火系", None),
                    ("freeze", "冰系", rules()["status_rules"]["freeze"]["max_stacks"]),
                    ("leech", "草系", leech_source()["max_stacks"]))}}


def validate_lifecycles(member):
    records = member.get("status_lifecycles", {})
    if not isinstance(records, dict):
        raise ValueError("Status lifecycle records must be an object")
    for status, record in records.items():
        if not isinstance(status, str) or not isinstance(record, dict):
            raise ValueError("Malformed status lifecycle record")
        if record.get("policy") != POLICY:
            raise ValueError("Unknown status lifecycle record policy")
        if not {"remaining_rounds", "departure", "decay", "cap"} <= record.keys():
            raise ValueError("Status lifecycle record omits explicit duration/departure/decay/cap")
        remaining = record.get("remaining_rounds")
        if remaining is not None:
            _count(remaining, "remaining status rounds", 1)
        if record.get("departure") not in ("clear", "retain"):
            raise ValueError("Status departure policy must be clear or retain")
        if record.get("decay") not in ("none", "half_floor", "half_ceil", "subtract_one"):
            raise ValueError("Unknown declared status decay policy")
        cap = record.get("cap")
        if cap is not None:
            _count(cap, "status cap", 1)
            if member.get("statuses", {}).get(status, 0) > cap:
                raise ValueError("Status count exceeds its lifecycle cap")


def apply_layers(member, status, amount, *, cap=None, stacking="add", remaining_rounds=None,
                 refresh="replace", departure="retain", decay="none", source=None):
    """Mutate one owned member after validation; explicit refresh/expiry contract.

    Supported stacking is add/replace/max; duration refresh is replace/max/retain.
    ``None`` is indefinite. Nothing here interprets arbitrary raw BUFF enums.
    """
    validate_lifecycles(member)
    if not isinstance(status, str) or not status:
        raise ValueError("Status identifier must be a nonempty string")
    _count(amount, "status layers", 1)
    if cap is not None:
        _count(cap, "status cap", 1)
    if remaining_rounds is not None:
        _count(remaining_rounds, "remaining status rounds", 1)
    if stacking not in ("add", "replace", "max") or refresh not in ("replace", "max", "retain"):
        raise ValueError("Unknown status stacking/duration refresh policy")
    if departure not in ("clear", "retain") or decay not in ("none", "half_floor", "half_ceil", "subtract_one"):
        raise ValueError("Unknown status departure/decay policy")
    before = _count(member.get("statuses", {}).get(status, 0), "existing status layers")
    from lab.trait_switch_components import status_immune
    if status_immune(member, status):
        return {'op': 'status.layers', 'status': status, 'before': before, 'after': before,
                'immune': True, 'requested_layers': amount, 'policy': POLICY}
    if cap is not None and before > cap:
        raise ValueError("Existing status layers exceed the declared cap")
    after = before + amount if stacking == "add" else amount if stacking == "replace" else max(before, amount)
    if cap is not None:
        after = min(cap, after)
    previous = member.get("status_lifecycles", {}).get(status)
    if previous and refresh == "retain":
        remaining_rounds = previous["remaining_rounds"]
    elif previous and refresh == "max":
        old = previous["remaining_rounds"]
        remaining_rounds = None if old is None or remaining_rounds is None else max(old, remaining_rounds)
    record = {"policy": POLICY, "cap": cap, "remaining_rounds": remaining_rounds,
              "departure": departure, "decay": decay, "source": deepcopy(source)}
    member.setdefault("statuses", {})[status] = after
    member.setdefault("status_lifecycles", {})[status] = record
    return {"op": "status.layers", "status": status, "before": before, "after": after,
            "stacking": stacking, "refresh": refresh, "lifecycle": deepcopy(record)}


def clear_status(member, status, *, reason):
    before = member.get("statuses", {}).get(status, 0)
    member.setdefault("statuses", {})[status] = 0
    member.get("status_lifecycles", {}).pop(status, None)
    member.get("status_sources", {}).pop(status, None)
    return {"op": "status.clear", "status": status, "before": before, "after": 0,
            "reason": reason, "policy": POLICY}


def advance_lifecycles(member, side, *, decayed_statuses=()):
    """After that member's status ticks; caller schedules active/bench semantics."""
    validate_lifecycles(member)
    events = []
    for status, record in list(member.get("status_lifecycles", {}).items()):
        before = member.get("statuses", {}).get(status, 0)
        decay = "none" if status in decayed_statuses else record["decay"]
        after = (before // 2 if decay == "half_floor" else (before + 1) // 2 if decay == "half_ceil"
                 else max(0, before - 1) if decay == "subtract_one" else before)
        member["statuses"][status] = after
        remaining = record["remaining_rounds"]
        if remaining is not None:
            record["remaining_rounds"] -= 1
        if after == 0 or record["remaining_rounds"] == 0:
            event = clear_status(member, status, reason="expired" if after else "decayed_to_zero")
        elif after != before or remaining is not None:
            event = {"op": "status.lifecycle_tick", "status": status, "before": before, "after": after,
                     "remaining_rounds": record["remaining_rounds"], "policy": POLICY}
        else:
            continue
        events.append({**event, "target_side": side, "member_id": member.get("member_id")})
    return events


def on_departure(member, side):
    from lab.duration_runtime import depart
    from lab.attack_grant_runtime import depart as depart_grants
    from lab.trait_runtime import depart as depart_traits
    from lab.modifier_ledger import depart_modifiers
    cleaned = depart_traits(depart_grants(depart(member)))
    member.clear(); member.update(cleaned)
    modifier_events = depart_modifiers(member)
    validate_lifecycles(member)
    return modifier_events + [{**clear_status(member, status, reason="departure"), "target_side": side,
             "member_id": member.get("member_id")}
            for status, record in list(member.get("status_lifecycles", {}).items())
            if record["departure"] == "clear"]


def check_freeze(member, side):
    """One threshold for ordinary and weather layers; equality never exhausts.

    The combined cap is a named research policy. The two legacy counters remain
    separate for source attribution, and are never copied into each other.
    """
    from lab.weather_runtime import rules, NUMERIC_POLICY
    spec = rules()["status_rules"]["freeze"]
    ordinary = _count(member.get("statuses", {}).get("freeze", 0), "ordinary freeze")
    weather = _count(member.get("weather_statuses", {}).get("freeze", 0), "weather freeze")
    count = min(spec["max_stacks"], ordinary + weather)
    from lab.trait_switch_components import status_immune
    if not count or set(spec["immune_types"]) & set(member.get("types", [])) or status_immune(member, 'freeze'):
        return []
    threshold = count * Fraction(str(spec["per_stack_max_hp_ratio"])) * member["max_hp"]
    if 0 < member["hp"] < threshold:
        before = member["hp"]
        member["hp"] = 0
        return [{"op": "weather.effect" if not ordinary else "status.effect", "effect_op": "freeze.exhaust",
                 "status": "freeze", "target_side": side, "member_id": member.get("member_id"),
                 "before": before, "after": 0, "amount": before, "stacks": count,
                 "ordinary_stacks": ordinary, "weather_stacks": weather, "source": deepcopy(spec["source"]),
                 "policy": NUMERIC_POLICY, "combined_layers_policy": POLICY}]
    return []


def validate_leech_binding(member, side, state=None):
    binding = member.get("status_sources", {}).get("leech")
    if (not isinstance(binding, dict) or binding.get("side") not in ("a", "b")
            or binding["side"] == side or not isinstance(binding.get("member_id"), str)
            or not binding["member_id"] or binding.get("policy") != LEECH_POLICY
            or binding.get("refresh_policy") != SOURCE_REFRESH_POLICY):
        raise ValueError("Leech requires a source-bound opposing member and named transfer policy")
    if state is not None:
        found = [m for m in state["teams"][binding["side"]]["members"] if m["member_id"] == binding["member_id"]]
        if len(found) != 1:
            raise ValueError("Leech source identity must resolve to exactly one original member")
        _count(found[0].get("hp"), "leech source HP")
        _count(found[0].get("max_hp"), "leech source maximum HP", 1)
        if found[0]["hp"] > found[0]["max_hp"]:
            raise ValueError("Leech source HP exceeds its declared maximum")
        return found[0]
    return binding


def tick_leech(state, side, *, policy):
    """Damage infected target; heal its bound caster by ACTUAL loss, capped.

    Target max HP, layer multiplier, floor, healing a benched source, and binding
    all layers to the latest applier are research choices. An exhausted source
    never revives. No elemental factor is
    inferred from the raw handler parameters. Source direction/rate are retained
    independently from those unresolved arithmetic details.
    """
    if policy != LEECH_POLICY:
        raise ValueError("Leech HP basis, layers, rounding and recipient require the named research policy")
    team = state["teams"][side]
    target = team["members"][team["active_slot"]]
    source = validate_leech_binding(target, side, state)
    if "草系" in target.get("types", []):
        raise ValueError("Existing leech on a grass type needs an explicit removal policy")
    stacks = _count(target["statuses"].get("leech", 0), "leech stacks", 1)
    from lab.trait_switch_components import status_immune
    immune = status_immune(target, 'leech')
    nominal = target["max_hp"] * stacks * Fraction(2, 100) if not immune else Fraction(0)
    loss = min(target["hp"], nominal.numerator // nominal.denominator)
    from lab.defense_runtime import prevent_lethal
    protection = prevent_lethal(target, loss, state.get("turn"))
    loss = protection["damage"]
    other_side = "b" if side == "a" else "a"
    other_team = state["teams"][other_side]
    opponent = other_team["members"][other_team["active_slot"]]
    from lab.trait_runtime import before_hp_loss_relative
    fatal = before_hp_loss_relative({"self": target, "opponent": opponent}, "self", loss,
        {"turn": state.get("turn")},
        f"status.leech:{state.get('turn')}:{side}:{target['member_id']}:{source['member_id']}:{stacks}")
    loss = fatal["damage"]
    target_before, source_before = target["hp"], source["hp"]
    target["hp"] -= loss
    if source_before > 0:
        source["hp"] = min(source["max_hp"], source_before + loss)
    from lab.trait_runtime import after_hp_restore_full
    binding = target["status_sources"]["leech"]
    heal_events = after_hp_restore_full(state, binding["side"], loss if source_before > 0 else 0, source["hp"] - source_before, {"turn":state.get("turn")}, member_id=binding["member_id"])
    return {"op": "status.tick", "status": "leech", "target_side": side,
            "target_member_id": target["member_id"], "source_binding": deepcopy(target["status_sources"]["leech"]),
            "hp_before": target_before, "hp_after": target["hp"], "actual_hp_loss": loss,
            "source_hp_before": source_before, "source_hp_after": source["hp"],
            "lethal_protection": protection["event"], "healing_effects":heal_events,
            "trait_protection_events": [{**event, "target_side": side if event.get("target") == "self" else other_side}
                                        for event in fatal["events"]],
            "restored": source["hp"] - source_before, "rate": {"numerator": 2, "denominator": 100},
            "stacks_before": stacks, "stacks_after": stacks, "source": leech_source(), "immune": immune,
            "policy": policy, "calibrated": False, "real_game_verified": False}
