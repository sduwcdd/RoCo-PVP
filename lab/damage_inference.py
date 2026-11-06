"""Enumerate opponent nature/talent candidates from recorded direct damage.

This is a compact inverse of the existing Arena research candidate.  It uses
the fixed BWIKI species values and configured ally nature/talents; callers do
not supply ally panel numbers.  Results are grouped without inventing a prior:
every listed value remains possible and no popularity probability is claimed.
"""
from __future__ import annotations

from copy import deepcopy
from itertools import combinations

from .numeric_candidates import arena_documented_damage60, arena_stat60
from .ruleset import BwikiRuleset
from .simulation import _estimate


DIMS = ("hp", "patk", "matk", "pdef", "mdef", "spd")
MODIFIERS = (None, "hp", "patk", "matk", "pdef", "mdef", "spd")


def _member(teams, side, member_id):
    rows = teams.get(side)
    if not isinstance(rows, list):
        return None
    return next((row for row in rows if isinstance(row, dict) and row.get("member_id") == member_id), None)


def _observed_member_id(action):
    if not isinstance(action, dict):
        return None
    return action.get("hp_observed_member_id") or (action.get("target_member_id") if action.get("kind") == "switch" else action.get("member_id"))


def _nature_directions(member, nature):
    correction = member.get("nature_modifiers") or {"up_id": 0, "down_id": 0}
    if not isinstance(correction, dict):
        raise ValueError("后天性格修正格式无效")
    ids = []
    for key in ("up_id", "down_id"):
        value = correction.get(key, 0)
        if type(value) is not int or not 0 <= value <= 6:
            raise ValueError("后天性格修正编号无效")
        ids.append(value)
    up, down = MODIFIERS[ids[0]] or nature["up"], MODIFIERS[ids[1]] or nature["down"]
    if up == down:
        return None
    return up, down


def _opponent_panel(form, member, nature, dim, talent):
    directions = _nature_directions(member, nature)
    if directions is None:
        return None
    up, down = directions
    multiplier = 1.2 if dim == up else .9 if dim == down else 1
    return arena_stat60(form["stats"][dim], talent * 6, multiplier, dim)["stat_value"]


def _single_damage(rules, move_id, target_form_id):
    plan = rules.plan(move_id, target_form_id)
    program = plan["program"]
    operations = program.get("operations", [])
    damage = [row for row in operations if row.get("op") == "damage"]
    if program.get("status") != "compiled" or len(damage) != 1 or operations[0] is not damage[0]:
        return None, "技能不是当前结构化规则中的单段直接伤害，未用于反推"
    params = damage[0].get("params", {})
    if set(params) != {"target", "kind", "power", "type"} or params["target"] != "opponent" or params["kind"] not in ("physical", "magical") or type(params["power"]) not in (int, float) or params["power"] <= 0:
        return None, "技能伤害参数含条件、连击或未知字段，未用于反推"
    return {"move": plan["skill"], "params": params, "matchup": plan["type_matchup"]}, None


def _ally_panels(catalog, member, form):
    selection = member.get("talent_selection")
    if not isinstance(selection, dict) or len(selection.get("selected", [])) != 3:
        raise ValueError("我方三项资质尚未完整配置")
    panels, _, notes = _estimate(catalog, member, form)
    if notes:
        raise ValueError("；".join(notes))
    return panels


def _selection_cases(member, options):
    """Factorized exact configurations: one three-stat selection plus independent value domains."""
    selection = member.get("talent_selection") or {}
    required = set(selection.get("selected", []))
    fixed = dict(selection.get("values", {}))
    for dim, known in member.get("confirmed", {}).get("talents", {}).items():
        if known and member.get("talents", {}).get(dim) is not None:
            fixed[dim] = member["talents"][dim]
            if fixed[dim] > 0:
                required.add(dim)
    cases = []
    for selected in combinations(DIMS, 3):
        if not required.issubset(selected):
            continue
        domains, count = {}, 1
        for dim in DIMS:
            values = options.get(dim, list(range(11))) if dim in selected else [0]
            if dim in fixed:
                values = [v for v in values if v == fixed[dim]]
            if dim not in selected and 0 not in options.get(dim, [0]):
                values = []
            if not values:
                break
            if dim in selected:
                domains[dim] = values
                count *= len(values)
        else:
            cases.append({"selected": list(selected), "value_options": domains,
                          "combination_count": count, "unselected_value": 0})
    return cases


def _prediction(rules, damage, actor_form, target_form, attack, defense):
    ratio = damage["matchup"]["multiplier"]
    multiplier = ratio["numerator"] / ratio["denominator"]
    if damage["params"]["type"] in actor_form.get("types", []):
        multiplier *= 1.25
    return arena_documented_damage60(attack, defense, damage["params"]["power"], multiplier)["nominal_damage"]


def _event(catalog, rules, turn, teams, source_side, source_action, target_side, target_action):
    observed = target_action.get("received_damage") if isinstance(target_action, dict) else None
    if observed is None:
        return None, None
    if type(observed) is not int or observed < 0:
        return None, "第 %s 回合伤害不是非负整数" % turn
    if not isinstance(source_action, dict) or source_action.get("kind") != "move" or type(source_action.get("move_id")) is not int:
        return None, "第 %s 回合有伤害但来源不是已记录的技能" % turn
    actor = _member(teams, source_side, source_action.get("member_id"))
    target = _member(teams, target_side, _observed_member_id(target_action))
    if actor is None or target is None:
        return None, "第 %s 回合缺少伤害双方的当时配置" % turn
    actor_form, target_form = rules.form(actor.get("form_id")), rules.form(target.get("form_id"))
    damage, blocker = _single_damage(rules, source_action["move_id"], target_form["id"])
    if blocker:
        return None, "第 %s 回合：%s" % (turn, blocker)
    kind = damage["params"]["kind"]
    if source_side == "my":
        panels = _ally_panels(catalog, actor, actor_form)
        dimension, fixed_stat = (("pdef", panels["patk"]) if kind == "physical" else ("mdef", panels["matk"]))
        opponent, role = target, "defender"
    else:
        panels = _ally_panels(catalog, target, target_form)
        dimension, fixed_stat = (("patk", panels["pdef"]) if kind == "physical" else ("matk", panels["mdef"]))
        opponent, role = actor, "attacker"
    return {"turn": turn, "opponent_member_id": opponent["member_id"], "opponent_form_id": opponent["form_id"],
            "role": role, "dimension": dimension, "observed_damage": observed,
            "move_id": damage["move"]["id"], "move_name": damage["move"]["name"]["zh"],
            "fixed_stat": fixed_stat, "actor_form": actor_form, "target_form": target_form,
            "damage": damage}, None


def _matches(rules, event, opponent_form, member, nature, talent):
    panel = _opponent_panel(opponent_form, member, nature, event["dimension"], talent)
    if panel is None:
        return False
    attack, defense = (panel, event["fixed_stat"]) if event["role"] == "attacker" else (event["fixed_stat"], panel)
    return _prediction(rules, event["damage"], event["actor_form"], event["target_form"], attack, defense) == event["observed_damage"]


def infer_damage_candidates(catalog, session):
    if not isinstance(session, dict) or session.get("snapshot_id") != catalog.get("snapshot_id"):
        raise ValueError("对局资料快照与当前图鉴不一致")
    rounds = session.get("rounds")
    if not isinstance(rounds, list) or len(rounds) > 2000:
        raise ValueError("回合记录格式无效或过大")
    rules = BwikiRuleset(catalog)
    events, blockers = [], []
    for row in rounds:
        if not isinstance(row, dict):
            raise ValueError("回合记录必须为对象")
        turn, teams = row.get("turn"), row.get("teams_snapshot")
        if type(turn) is not int or turn < 1:
            raise ValueError("回合编号无效")
        if not isinstance(teams, dict):
            blockers.append("第 %s 回合没有保存当时阵容配置" % turn)
            continue
        for args in (("my", row.get("my"), "opponent", row.get("opponent")),
                     ("opponent", row.get("opponent"), "my", row.get("my"))):
            try:
                event, blocker = _event(catalog, rules, turn, teams, *args)
            except ValueError as exc:
                event, blocker = None, "第 %s 回合：%s" % (turn, exc)
            if event:
                events.append(event)
            elif blocker:
                blockers.append(blocker)
    current = {m.get("member_id"): m for m in session.get("teams", {}).get("opponent", []) if isinstance(m, dict)}
    results = []
    for member_id, member in current.items():
        relevant = [event for event in events if event["opponent_member_id"] == member_id and event["opponent_form_id"] == member.get("form_id")]
        if not relevant:
            continue
        form = rules.form(member.get("form_id"))
        dimensions = sorted({event["dimension"] for event in relevant}, key=DIMS.index)
        confirmed_nature = member.get("nature_id") if member.get("confirmed", {}).get("nature") is True else None
        natures = [n for n in catalog["natures"] if confirmed_nature is None or n["id"] == confirmed_nature]
        groups, total = [], 0
        for nature in natures:
            options = {}
            for dim in dimensions:
                dim_events = [event for event in relevant if event["dimension"] == dim]
                values = [value for value in range(11) if all(_matches(rules, event, form, member, nature, value) for event in dim_events)]
                if not values:
                    break
                options[dim] = values
            if len(options) != len(dimensions):
                continue
            cases = _selection_cases(member, options)
            count = sum(case["combination_count"] for case in cases)
            if count:
                groups.append({"nature_id": nature["id"], "nature_name": nature["name"]["zh"],
                               "directions": dict(zip(("up", "down"), _nature_directions(member, nature))),
                               "talent_value_options": options, "selection_cases": cases,
                               "combination_count": count})
                total += count
        results.append({"member_id": member_id, "form_id": form["id"], "form_name": form["name"]["zh"],
                        "status": "ready" if groups else "model_mismatch", "observed_dimensions": dimensions,
                        "observations": [{key: event[key] for key in ("turn", "role", "dimension", "observed_damage", "move_id", "move_name")} for event in relevant],
                        "groups": groups, "combination_count": total})
    return {"status": "ready", "members": results, "blockers": list(dict.fromkeys(blockers)),
            "snapshot_id": catalog["snapshot_id"], "candidate_id": "arena_stat60_v1+arena_documented_damage60_v1",
            "same_type_multiplier": 1.25, "probability_available": False,
            "talent_domain": {"selected_dimensions": 3, "display_value_min": 0, "display_value_max": 10,
                              "unobserved_dimensions": "all_values_retained_in_selection_cases", "zero": "selected_zero_or_unselected"},
            "calibrated": False, "real_game_verified": False,
            "notice": "按性格和三选六维度分组列出全部相容配置；每组 value_options 的笛卡尔积是全部数值组合，未观测维度保留0–10。仅适用于当前裸伤害公式，未记录的增减伤等会干扰反推，不生成联合概率。"}
