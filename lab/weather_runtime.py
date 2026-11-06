"""Source-bound weather lifecycle shared by simulation and observation replay.

The configuration is extracted offline. Timing, rounding and consumption are
named experiments, not inferred server behavior. Observation mode never edits HP.
"""
from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
from lab.ruleset import canonical_hash

POLICY = "weather_actions_then_status_then_weather_count_current_round_v1"
NUMERIC_POLICY = "sand_cost_ceil_freeze_strict_less_conductive_floor_min_one_type_consume_pairs_v1"

@lru_cache(maxsize=2)
def _rules_version(stamp):
    from lab.weather_rules import get_weather_rules
    return get_weather_rules()

def rules():
    from lab.weather_rules import RULES_PATH
    return _rules_version(RULES_PATH.stat().st_mtime_ns)

def is_weather_skill(skill_id):
    return str(skill_id) in rules()["setters"]

def validate_weather(weather):
    if weather is None:
        return
    if not isinstance(weather, dict) or weather.get("kind") not in rules()["weather"]:
        raise ValueError("Unknown weather state")
    if type(weather.get("remaining_rounds")) is not int or not 1 <= weather["remaining_rounds"] <= 10000:
        raise ValueError("Weather remaining rounds must be 1–10000")
    if weather.get("lifecycle_policy") != POLICY:
        raise ValueError("Weather lifecycle version is not supported")
    if weather.get("rules_hash") != canonical_hash(rules()):
        raise ValueError("Weather source changed; restart or replay the battle")
    setter = rules()["setters"].get(str(weather.get("source_skill_id")))
    spec = rules()["weather"][weather["kind"]]
    if not setter or setter["weather"] != weather["kind"] or weather.get("name") != spec["name"]:
        raise ValueError("Weather source identity conflicts with its kind")
    if type(weather.get("applied_turn")) is not int or weather["applied_turn"] < 1:
        raise ValueError("Weather creation turn is invalid")

def validate_weather_members(state):
    validate_weather(state.get("weather"))
    for team in state["teams"].values():
        for member in team["members"]:
            statuses = member.get("weather_statuses", {})
            if not isinstance(statuses, dict) or set(statuses) - {"freeze", "conductive"}:
                raise ValueError("Unknown weather-derived status")
            for name, count in statuses.items():
                if type(count) is not int or not 0 <= count <= (99 if name == "freeze" else 1):
                    raise ValueError("Weather status stacks exceed the executable range")

def set_weather(weather, skill_id, turn):
    validate_weather(weather)
    data = rules()
    setter = data["setters"].get(str(skill_id))
    if setter is None:
        raise ValueError("Skill is not a source-bound weather setter")
    kind = setter["weather"]
    spec = data["weather"][kind]
    current = {"kind": kind, "name": spec["name"], "remaining_rounds": spec.get("duration", 8),
        "applied_turn": turn, "source_skill_id": int(skill_id), "source": {**deepcopy(setter.get("source", {})), "weather_configuration": deepcopy(spec["source"])},
        "effect_summary": [spec["description"]], "lifecycle_policy": POLICY,
        "numeric_policy": NUMERIC_POLICY, "rules_hash": canonical_hash(data)}
    return current, [{"op": "weather.set", "before": deepcopy(weather), "after": deepcopy(current),
                      "skill_id": int(skill_id), "source": deepcopy(current["source"]), "policy": POLICY}]

def _alive(member):
    return member.get("hp", member.get("hp_percent", 100)) != 0

def check_freeze(member, side):
    from lab.status_lifecycle import check_freeze as unified_freeze
    return unified_freeze(member, side)


def apply_status(member, side, status, amount, *, apply_effects, type_multiplier=None, turn=None, opponent=None):
    # Discharge may mutate both real combatants through fatal protection. Commit
    # this small pair only after every dependency succeeds, never fabricate a foe.
    if opponent is not None and not isinstance(opponent, dict):
        raise ValueError("Weather damage opponent must be an actual member object")
    spec = rules()["status_rules"].get(status)
    if (apply_effects and status == "conductive" and spec and type(amount) is int and amount >= 0
            and member.get("weather_statuses", {}).get(status, 0) + amount >= spec["threshold_stacks"]):
        if opponent is member:
            raise ValueError("Conductive damage needs distinct actual opposing members")
        current = deepcopy(member)
        other = deepcopy(opponent) if opponent is not None else None
        events = _apply_status_owned(current, side, status, amount, apply_effects=apply_effects,
            type_multiplier=type_multiplier, turn=turn, opponent=other)
        member.clear(); member.update(current)
        if opponent is not None:
            opponent.clear(); opponent.update(other)
        return events
    return _apply_status_owned(member, side, status, amount, apply_effects=apply_effects,
        type_multiplier=type_multiplier, turn=turn, opponent=opponent)


def _apply_status_owned(member, side, status, amount, *, apply_effects, type_multiplier=None, turn=None, opponent=None):
    spec = rules()["status_rules"].get(status)
    if spec is None or type(amount) is not int or amount < 0:
        raise ValueError("Unknown weather status effect")
    immune = spec.get("immune_types", [])
    event = {"op": "weather.effect", "effect_op": "add_status", "status": status,
        "target_side": side, "member_id": member.get("member_id"), "source": spec["source"],
        "applied": apply_effects, "predicted": not apply_effects, "policy": NUMERIC_POLICY}
    from lab.trait_switch_components import status_immune
    if set(immune) & set(member.get("types", [])) or status_immune(member, status):
        return [{**event, "immune": True, "amount": 0}]
    statuses = member.setdefault("weather_statuses", {})
    before = statuses.get(status, 0)
    after = min(spec["max_stacks"], before + amount)
    statuses[status] = after
    events = [{**event, "before": before, "after": after, "amount": amount}]
    if status == "freeze":
        if apply_effects:
            events += check_freeze(member, side)
        elif member.get("hp_percent") is not None and member["hp_percent"] < after * spec["per_stack_max_hp_ratio"] * 100:
            events.append({**event, "effect_op": "freeze.exhaust", "amount": None,
                "description": "当前显示生命低于冻结比例，预计触发力竭；以实战状态为准"})
    elif after >= spec["threshold_stacks"]:
        statuses[status] -= spec["threshold_consume_policy"]
        if apply_effects:
            if type_multiplier is None:
                raise ValueError("Conductive discharge requires the source electric type chart")
            ratio = type_multiplier(spec["damage_type"], member)
            nominal = member["max_hp"] * Fraction(str(spec["damage_max_hp_ratio"])) * ratio
            damage = min(member["hp"], max(1, nominal.numerator // nominal.denominator) if nominal > 0 else 0)
            from lab.defense_runtime import prevent_lethal
            protection = prevent_lethal(member, damage, turn)
            damage = protection["damage"]
            if protection["event"]:
                events.append(protection["event"])
            from lab.trait_runtime import before_hp_loss_relative, _confirmed_member
            row = _confirmed_member(member)
            if (opponent is None and row and row["trait_id"] in (200151, 200195)
                    and 0 < member["hp"] <= damage
                    and len(member.get("fatal_protection_events", [])) < row["components"][0]["limit"]):
                raise ValueError("Conductive lethal protection requires the actual opposing member")
            relative = {"self": member}
            if opponent is not None:
                relative["opponent"] = opponent
            packet = member.get("weather_damage_packet_counter", 0)
            if type(packet) is not int or packet < 0:
                raise ValueError("Conductive damage packet counter is invalid")
            fatal = before_hp_loss_relative(relative, "self", damage, {"turn": turn},
                f"weather.conductive:{turn}:{member.get('member_id')}:{packet}")
            damage = fatal["damage"]
            member["weather_damage_packet_counter"] = packet + 1
            other_side = ("b" if side == "a" else "a") if side in ("a", "b") else ("opponent" if side == "self" else "self")
            events.extend({**event, "target_side": side if event.get("target") == "self" else other_side}
                          for event in fatal["events"])
            before_hp = member["hp"]
            member["hp"] -= damage
            events.append({**event, "effect_op": "conductive.damage", "amount": damage,
                "before": before_hp, "after": member["hp"], "consumed_stacks": spec["threshold_consume_policy"],
                "type_multiplier": {"numerator": ratio.numerator, "denominator": ratio.denominator}})
            events += check_freeze(member, side)
        else:
            events.append({**event, "effect_op": "conductive.damage", "damage_percent": spec["damage_max_hp_ratio"] * 100,
                "type": spec["damage_type"], "amount": None, "consumed_stacks": spec["threshold_consume_policy"],
                "description": "预计按最大生命25%结算电系伤害；实际伤害以记录为准"})
    return events

def on_departure(member, side):
    events = []
    for name, count in list(member.get("weather_statuses", {}).items()):
        spec = rules()["status_rules"][name]
        if count and spec["switch_policy"] == "clear":
            member["weather_statuses"][name] = 0
            events.append({"op": "weather.effect", "effect_op": "status.clear", "status": name,
                "target_side": side, "member_id": member.get("member_id"), "before": count, "after": 0,
                "policy": "conductive_clean_when_rest_1_clear_on_switch_experiment", "source": spec["source"]})
    return events

def advance_weather(weather, active_members, turn, *, apply_effects=False, type_multiplier=None):
    """One end-of-round call. Only simulation mode mutates cloned member resources."""
    validate_weather(weather)
    current, members, events = deepcopy(weather), deepcopy(active_members), []
    if current is None:
        return None, members, events
    spec = rules()["weather"][current["kind"]]
    for side, member in members.items():
        if not _alive(member):
            continue
        for effect in spec.get("effects", []):
            if effect.get("phase") != "round_end":
                continue
            if effect["op"] != "add_status":
                raise ValueError("Unimplemented weather end effect: " + effect["op"])
            if set(effect.get("when", {}).get("exclude_target_types", [])) & set(member.get("types", [])):
                events.append({"op": "weather.effect", "effect_op": "add_status", "weather": current["kind"],
                    "target_side": side, "member_id": member.get("member_id"), "status": effect["status"],
                    "immune": True, "amount": 0, "applied": apply_effects, "source": deepcopy(current["source"])})
                continue
            events += [{**e, "weather": current["kind"], "weather_source": deepcopy(current["source"])}
                for e in apply_status(member, side, effect["status"], effect["value"],
                    apply_effects=apply_effects, type_multiplier=type_multiplier, turn=turn,
                    opponent=members.get("b" if side == "a" else "a"))]
    before = current["remaining_rounds"]
    current["remaining_rounds"] -= 1
    events.append({"op": "weather.tick", "kind": current["kind"], "before": before,
                   "after": current["remaining_rounds"], "turn": turn, "policy": POLICY})
    if current["remaining_rounds"] == 0:
        events.append({"op": "weather.expired", "kind": current["kind"], "turn": turn, "policy": POLICY})
        current = None
    return current, members, events


def weather_programs(prepared):
    """A shared field-effect program, retaining the original source description."""
    out = {}
    for key, setter in rules()["setters"].items():
        mid = int(key)
        program = deepcopy(prepared._rules.program(mid))
        program.pop("native_rule", None)
        program.update(status="compiled", blockers=[], execution_blockers=[], operations=[],
            source_hash=canonical_hash({"source": setter, "rules": rules()}),
            weather_components=[{"op": "weather.set", "kind": setter["weather"]}],
            weather_source=deepcopy(setter), real_game_verified=False)
        out[mid] = program
    for key, effects in rules().get("skill_modifiers", {}).items():
        if not effects or any(e["op"] != "extend_weather" for e in effects):
            continue
        mid = int(key)
        try:
            program = deepcopy(prepared._rules.program(mid))
        except ValueError:
            continue
        program.pop("native_rule", None)
        program.update(status="compiled", blockers=[], execution_blockers=[], operations=[],
            source_hash=canonical_hash({"source": effects, "rules": rules()}),
            weather_components=deepcopy(effects), weather_source=deepcopy(effects), real_game_verified=False)
        out[mid] = program
    return out

def preflight_weather_skill(program, state, context):
    from lab.effect_runtime import _preflight_header
    _preflight_header(program, state, context)
    cost=context.get("resolved_energy_cost")
    if type(cost) is not int or cost<0 or cost>state["self"]["energy"]:
        raise ValueError("Invalid or unaffordable weather skill cost")
    expected = rules()["setters"].get(str(program["game_id"]))
    expected_components = ([{"op": "weather.set", "kind": expected["weather"]}] if expected else
        rules().get("skill_modifiers", {}).get(str(program["game_id"])))
    if not expected_components or program.get("weather_components") != expected_components:
        raise ValueError("Weather components do not match their source-bound definition")

def execute_weather_skill(program, state, context, weather, turn):
    preflight_weather_skill(program, state, context)
    owned = deepcopy(state)
    cost = context["resolved_energy_cost"]
    owned["self"]["energy"] -= cost
    current, events = apply_weather_skill(weather, program["game_id"], turn, response_success=context.get("weather_response_success", False))
    validate_weather(current)
    from lab.mechanism_runtime import consume_skill_tokens
    events.extend(consume_skill_tokens(owned["self"],attacked=False,turn=turn))
    return {"status": "applied", "state": owned, "weather": current,
            "events": [{"op": "energy.pay", "amount": cost, "source": "caller_resolved_cost"}] + events}

def _matches(effect, weather, skill_type=None, actor=None):
    when = effect.get("when", {})
    kind = weather.get("kind") if weather else None
    if "weather" in when and when["weather"] != kind:
        return False
    if "skill_type" in when and when["skill_type"] != skill_type:
        return False
    if "weather_or_environment" in when:
        choices = when["weather_or_environment"]
        if kind not in choices and (actor or {}).get("environment_type") not in choices:
            return False
    return True

def modifiers(weather, phase, skill_id=None, skill_type=None, actor=None):
    data, candidates = rules(), []
    if weather:
        candidates += data["weather"][weather["kind"]].get("effects", [])
    candidates += data.get("skill_modifiers", {}).get(str(skill_id), [])
    candidates += data.get("trait_modifiers", {}).get(str((actor or {}).get("weather_trait_id")), [])
    return [e for e in candidates if e.get("phase") == phase and _matches(e, weather, skill_type, actor)]

def resolved_skill_type(weather, skill_id, skill_type):
    for effect in rules().get("skill_modifiers", {}).get(str(skill_id), []):
        if effect["op"] == "skill_type_from_weather" and weather:
            return rules()["weather"][weather["kind"]]["type"]
    return skill_type

def modify_cost(weather, skill_type, base_cost, skill_id=None, actor=None):
    validate_weather(weather)
    skill_type = resolved_skill_type(weather, skill_id, skill_type)
    effects = modifiers(weather, "before_cost", skill_id, skill_type, actor)
    cost = Fraction(base_cost + sum(e["value"] for e in effects if e["op"] == "energy_add"))
    for effect in effects:
        if effect["op"] == "energy_multiplier":
            cost *= Fraction(str(effect["value"]))
    from lab.trait_runtime import cost_delta
    rounded = -(-cost.numerator // cost.denominator)
    return max(0, base_cost + (cost_delta(actor, rounded - base_cost) if actor is not None else rounded - base_cost))

def modify_power(weather, skill_type, power, skill_id=None, actor=None):
    validate_weather(weather)
    effects = modifiers(weather, "before_damage", skill_id, skill_type, actor)
    value = Fraction(str(power)) + sum(Fraction(str(e["value"])) for e in effects if e["op"] == "power_add")
    for effect in effects:
        if effect["op"] == "power_multiplier":
            value *= Fraction(str(effect["value"]))
    return float(value)

def modify_priority(weather, skill_id, priority, actor=None):
    return priority + sum(e["value"] for e in modifiers(weather, "action_order", skill_id, actor=actor)
                          if e["op"] == "priority_add")

def modify_speed(weather, speed, actor):
    return speed + sum(e["value"] for e in modifiers(weather, "action_order", actor=actor)
                       if e["op"] == "stat_add" and "speed" in e.get("stats", []))

def weather_attack_programs(prepared):
    """Only complete source-described attack + weather modifier combinations."""
    out = {}
    allowed = {"energy_add", "skill_type_from_weather", "priority_add", "power_add"}
    for key, effects in rules().get("skill_modifiers", {}).items():
        if any(e["op"] not in allowed for e in effects):
            continue
        mid = int(key)
        try:
            skill = prepared._rules.skill(mid)
            program = deepcopy(prepared._rules.program(mid))
        except ValueError:
            continue
        if skill["kind"] not in ("physical", "magical") or type(skill.get("power")) is not int:
            continue
        program.pop("native_rule", None)
        program.update(status="compiled", blockers=[], execution_blockers=[],
            operations=[{"op": "damage", "params": {"target": "opponent", "kind": skill["kind"],
                "type": skill["type"], "power": skill["power"]}}],
            source_hash=canonical_hash({"source": effects, "catalog_skill": skill}),
            weather_modifiers=deepcopy(effects), real_game_verified=False)
        out[mid] = program
    return out

def after_skill(weather, skill_id, actor, opponent, events, *, side, type_multiplier, skill_type=None, turn=None):
    """Weather trait hooks reuse actual skill damage and the same stack executor."""
    emitted = []
    skill_type = skill_type or next((e.get("params", {}).get("type") for e in events if e.get("op", "").startswith("damage")), None)
    skill_type = resolved_skill_type(weather, skill_id, skill_type)
    for effect in modifiers(weather, "after_damage", skill_id, skill_type, actor):
        if effect["op"] == "drain" and actor["hp"] > 0:
            lost = sum(e.get("actual_hp_loss", e.get("damage", 0)) for e in events if e.get("op", "").startswith("damage"))
            requested = int(lost * effect["value"])
            before = actor["hp"]
            actor["hp"] = min(actor["max_hp"], before + requested)
            from lab.trait_runtime import after_hp_restore
            emitted.extend(after_hp_restore({"self":actor,"opponent":opponent}, "self", requested, actor["hp"] - before, {"turn":turn}))
            emitted.append({"op": "weather.effect", "effect_op": "hp.restore", "target_side": side,
                "amount": actor["hp"] - before, "before": before, "after": actor["hp"], "source": effect.get("source")})
    # Trait-derived stacks are processed without advancing the weather clock.
    for effect in modifiers(weather, "after_skill", skill_id, skill_type, actor):
        if effect["op"] == "add_status" and opponent["hp"] > 0:
            target_side = "b" if side == "a" else "a"
            extra = add_conductive(opponent, target_side, effect["value"], type_multiplier, turn=turn, opponent=actor)
            emitted.extend({**event, **({"target": "opponent" if event["target"] == "self" else "self"}
                if event.get("target") in ("self", "opponent") else {})} for event in extra)
    return emitted

def add_conductive(member, side, amount, type_multiplier, *, turn=None, opponent=None):
    if member["hp"] == 0:
        return []
    return apply_status(member, side, "conductive", amount, apply_effects=True,
                        type_multiplier=type_multiplier, turn=turn, opponent=opponent)


def apply_weather_skill(weather, skill_id, turn, *, response_success=False):
    if is_weather_skill(skill_id):
        return set_weather(weather, skill_id, turn)
    validate_weather(weather)
    current, events = deepcopy(weather), []
    effects = rules().get("skill_modifiers", {}).get(str(skill_id), [])
    for effect in effects:
        if effect["op"] == "extend_weather" and _matches(effect, current):
            value = effect.get("response_success_value", effect["value"]) if response_success else effect["value"]
            before = current["remaining_rounds"]
            current["remaining_rounds"] += value
            events.append({"op": "weather.extend", "kind": current["kind"], "before": before,
                "after": current["remaining_rounds"], "amount": value, "skill_id": int(skill_id),
                "response_success": response_success, "source": deepcopy(effect["source"]), "policy": POLICY})
    return current, events
