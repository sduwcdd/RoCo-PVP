"""Single-skill workbench preview through the current shared HUD resolver.

Only explicitly prepared panels and manual terms are projected; unresolved HUD
state remains a blocked slot, never a legacy formula fallback.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction

from .hud_damage_runtime import make_hud_damage_resolver
from . import live_damage
from .ruleset import BwikiRuleset
from .skill_hits import base_hits, SOURCE_PARSED
from .simulation import DEFAULT_SETTINGS, DIMS, prepare_simulation, settings as validate_settings


EXCLUDED_EFFECTS = [
    "对方换人",
    "对方使用防御技能（减伤按 raw*(100-n)//100 自行乘算）",
    "聚能（+5 能量）",
    "应对成功后的威力加成与段数变化（威力按倍率自行乘算，段数按描述自行加）",
    "天气",
    "印记与状态层（灼烧、中毒、寄生等按层结算的伤害一律不计）",
    "未在「本回合状态修正」里填写的增益与减益：只算你手动填入的面板百分比，其余状态层不推断",
    "特性",
    "核心魔法",
    "暴击与随机浮动（本平台无随机浮动）",
]

POLICY_NOTE = (
    "与当前HUD及PVP执行器共用skill_math与_damage_case查询；每段完整威力，逐段结算后求和。"
    "仅使用本次明确给出的面板和修正；未知HUD状态、范围或机制保留阻断原因，不回退旧候选公式。"
    "共享实现仍未完成全量实战校准。"
)

_STATS = ("patk", "matk", "pdef", "mdef", "speed")


def _stat_terms(payload):
    """Percent terms per side/stat; each term is one source, summed linearly."""
    raw = payload.get("stat_terms") or {}
    if not isinstance(raw, dict) or set(raw) - {"a", "b"}:
        raise ValueError("状态修正指定无效")
    out = {}
    for side_key, entries in raw.items():
        if not isinstance(entries, dict) or set(entries) - set(_STATS):
            raise ValueError("状态修正含未知属性")
        parsed = {}
        for stat, value in entries.items():
            terms = value if isinstance(value, list) else [value]
            if len(terms) > 32:
                raise ValueError("同一属性的状态修正来源过多")
            clean = []
            for term in terms:
                if type(term) not in (int, float) or isinstance(term, bool) or not -1000 <= term <= 1000:
                    raise ValueError("状态修正必须是 -1000 到 1000 之间的数字")
                if term:
                    clean.append(Fraction(str(term)))
            if clean:
                parsed[stat] = clean
        if parsed:
            out[side_key] = parsed
    return out


def _panel_with_terms(base, terms):
    """Effective panel = base × (1 + Σ%), the engine's linear signed-term policy."""
    if not terms:
        return float(base), None
    total = sum(terms, Fraction(0))
    ratio = Fraction(1) + total / 100
    if ratio <= 0:
        raise ValueError("状态修正把面板压到 0 或以下，本预估无法给出伤害")
    return float(base * ratio), float(total)



def _active(state, side, override):
    team = state["teams"][side]
    if override in (None, ""):
        return team["members"][team["active_slot"]], team["active_slot"]
    if type(override) is not int or not 0 <= override < len(team["members"]):
        raise ValueError("在场精灵序号超出该方阵容")
    return team["members"][override], override


def _hp_override(member, value):
    if value is None:
        return member["hp"]
    if type(value) is not int or not 0 <= value <= member["max_hp"]:
        raise ValueError("当前生命必须是 0 到最大生命之间的整数")
    return value


def _hp_from_percent(member, value):
    """A visible HP percentage is an interval; keep the surviving body at >= 1 HP."""
    if value is None:
        return member["hp"]
    if type(value) not in (int, float) or isinstance(value, bool) or not 0 <= value <= 100:
        raise ValueError("生命百分比必须在 0 到 100 之间")
    if value == 0:
        return 0
    scaled = member["max_hp"] * float(value) / 100
    return min(member["max_hp"], max(1, int(scaled) if scaled == int(scaled) else int(scaled) + 1))


def _pick_hp(member, key, hp_input, percent_input):
    if key in hp_input:
        return _hp_override(member, hp_input[key])
    if key in percent_input:
        return _hp_from_percent(member, percent_input[key])
    return member["hp"]


def preview_damage(catalog, payload):
    """Return per-slot naked damage for one side's on-field pet."""
    if not isinstance(payload, dict):
        raise ValueError("请求应为对象")
    teams = payload.get("teams")
    if not isinstance(teams, dict) or set(teams) != {"my", "opponent"}:
        raise ValueError("请先准备双方阵容")
    raw_settings = payload.get("settings")
    chosen_settings = deepcopy(DEFAULT_SETTINGS) if raw_settings is None else validate_settings(raw_settings)
    side = payload.get("side", "a")
    if side not in ("a", "b"):
        raise ValueError("预估方向必须是 a 或 b")
    other = "b" if side == "a" else "a"

    prepared = prepare_simulation(catalog, {"teams": teams, "settings": chosen_settings})
    state = prepared["state"]
    active_override = payload.get("active_slot") or {}
    if not isinstance(active_override, dict):
        raise ValueError("在场精灵指定无效")
    if set(active_override) - {"a", "b"}:
        raise ValueError("在场精灵指定含未知阵营")
    attacker, attacker_slot = _active(state, side, active_override.get(side))
    defender, defender_slot = _active(state, other, active_override.get(other))

    hp_input = payload.get("hp") or {}
    if not isinstance(hp_input, dict) or set(hp_input) - {"a", "b"}:
        raise ValueError("当前生命指定无效")
    percent_input = payload.get("hp_percent") or {}
    if not isinstance(percent_input, dict) or set(percent_input) - {"a", "b"}:
        raise ValueError("生命百分比指定无效")
    if set(hp_input) & set(percent_input):
        raise ValueError("同一方同时给出绝对生命与百分比生命，观测冲突，请先确认")
    attacker_hp = _pick_hp(attacker, side, hp_input, percent_input)
    defender_hp = _pick_hp(defender, other, hp_input, percent_input)
    terms = _stat_terms(payload)

    rules = BwikiRuleset(catalog)
    resolver = make_hud_damage_resolver(catalog)
    same_type_policy = chosen_settings["same_type_multiplier"]

    results, non_damage, blocked = [], [], []
    for slot, skill_id in enumerate(attacker["skill_slots"]):
        if not skill_id:
            continue
        skill = rules.skill(skill_id)
        name = skill.get("name", {}).get("zh") or str(skill_id)
        base = {
            "slot": slot,
            "skill_id": skill_id,
            "name": name,
            "type": skill.get("type"),
            "kind": skill.get("kind"),
            "power": skill.get("power"),
            "energy_cost": skill.get("energy"),
            "affordable": isinstance(skill.get("energy"), int) and attacker["energy"] >= skill["energy"],
        }
        profile = live_damage.skill_math(skill_id, attacker["form_id"], defender["form_id"])
        if profile.get("reason"):
            base["reason"] = profile["reason"]
            (non_damage if skill.get("kind") not in ("physical", "magical", "higher") else blocked).append(base)
            continue
        power = profile["power"]
        kind = profile["kind"]
        if kind == "higher":
            pa, _ = _panel_with_terms(attacker["stats"]["patk"], terms.get(side, {}).get("patk"))
            ma, _ = _panel_with_terms(attacker["stats"]["matk"], terms.get(side, {}).get("matk"))
            kind = "physical" if pa >= ma else "magical"
        base.update(power=power, kind=kind, type=profile["skillType"])
        if kind not in ("physical", "magical") or not isinstance(power, (int, float)) or power <= 0:
            base["reason"] = "变化技能或未登记威力，本预估只覆盖直接伤害技能"
            non_damage.append(base)
            continue
        attack_stat, defense_stat = ("patk", "pdef") if kind == "physical" else ("matk", "mdef")
        attack_base = attacker["stats"][attack_stat]
        defense_base = defender["stats"][defense_stat]
        attack, attack_terms = _panel_with_terms(attack_base, terms.get(side, {}).get(attack_stat))
        defense, defense_terms = _panel_with_terms(defense_base, terms.get(other, {}).get(defense_stat))
        type_ratio = Fraction(str(profile["multiplier"]))
        matchup = {"multiplier": {"numerator": type_ratio.numerator, "denominator": type_ratio.denominator}}
        same_type = profile["stab"]
        multiplier = profile["combined"]
        hits = profile["hits"]
        _, hits_source = base_hits(catalog, skill_id)
        per_hit_power = power
        execution = {"self": deepcopy(attacker), "opponent": deepcopy(defender)}
        execution["self"]["hp"], execution["opponent"]["hp"] = attacker_hp, defender_hp
        for who, key in (("self", side), ("opponent", other)):
            for stat in ("patk", "matk", "pdef", "mdef", "speed"):
                field = "spd" if stat == "speed" else stat
                adjusted, _ = _panel_with_terms(execution[who]["stats"][field], terms.get(key, {}).get(stat))
                execution[who]["stats"][field] = adjusted
            execution[who]["speed"] = execution[who]["stats"]["spd"]
        context = {"snapshot_id": rules.snapshot_id, "turn": state["turn"], "weather": state.get("weather"),
                   "weather_skill_id": skill_id, "selected_skill_slot": slot,
                   "mark_first_attack": True, "mark_first_action": True}
        params = {"target": "opponent", "kind": kind, "power": power,
                  "type": profile["skillType"], "power_basis": chosen_settings["multi_hit_power"],
                  "ignore_type_resistance": bool(profile.get("ignoreResistance"))}
        remaining, hits_detail, total_nominal, first_trace, candidate_id = defender_hp, [], 0, None, None
        for hit_index in range(hits):
            if remaining <= 0:  # the engine stops the sequence once a side is exhausted
                break
            execution["opponent"]["hp"] = remaining
            try:
                prediction = resolver.explain(params, execution, context)
            except ValueError as exc:
                base["reason"] = str(exc)
                blocked.append(base)
                break
            nominal = prediction["nominal_damage"]
            applied = prediction["actual_hp_loss"]
            remaining -= applied
            total_nominal += nominal
            if first_trace is None:
                first_trace, candidate_id = prediction, chosen_settings["damage_candidate"]
            hits_detail.append({"index": hit_index, "power": per_hit_power, "nominal_damage": nominal,
                                "applied": applied, "defender_hp_after": remaining})
        if base.get("reason"):
            continue
        per_hit_damage = hits_detail[0]["nominal_damage"] if hits_detail else 0
        applied_damage = defender_hp - remaining
        after = remaining
        percent = round(total_nominal * 100 / defender["max_hp"], 1) if defender["max_hp"] else 0.0
        results.append({
            **base,
            "attack_stat": attack_stat,
            "attack_panel": attack,
            "attack_panel_base": attack_base,
            "attack_stat_modifier_percent": attack_terms,
            "defense_stat": defense_stat,
            "defense_panel": defense,
            "defense_panel_base": defense_base,
            "defense_stat_modifier_percent": defense_terms,
            "type_multiplier": {"numerator": matchup["multiplier"]["numerator"],
                                "denominator": matchup["multiplier"]["denominator"]},
            "same_type_bonus": same_type,
            "combined_multiplier": multiplier,
            "hit_count": hits,
            "hit_count_source": hits_source,
            "power_basis": chosen_settings["multi_hit_power"],
            "per_hit_power": per_hit_power,
            "per_hit_damage": per_hit_damage,
            "hits_detail": hits_detail,
            "hits_executed": len(hits_detail),
            "damage": total_nominal,
            "applied_damage": applied_damage,
            "damage_percent_of_max": percent,
            "lethal": applied_damage >= defender_hp and defender_hp > 0,
            "defender_hp_before": defender_hp,
            "defender_hp_after": after,
            "defender_hp_after_percent": round(after * 100 / defender["max_hp"], 1),
            "formula_trace": first_trace,
            "candidate_id": candidate_id,
        })

    warnings = list(prepared["warnings"])
    if terms:
        applied = []
        for side_key, entries in terms.items():
            for stat, values in entries.items():
                applied.append(("我方" if side_key == side else "对方") + " " + stat
                               + " Σ" + ("%+.0f%%" % float(sum(values, Fraction(0)))))
        warnings.append("本预估已按你填写的状态修正改面板：" + "、".join(applied)
                        + "。有效面板 = 基础面板 × (1 + Σ%)，与引擎 stat_modifier_policy 的线性相加口径一致；"
                        "未填写的状态层不在其中。")
    multi = [row for row in results if row["hit_count"] > 1]
    if multi:
        parsed = [row for row in multi if row["hit_count_source"] == SOURCE_PARSED]
        warnings.append(
            "多段技能逐段取整后求和：段数来自技能描述解析（" + str(len(parsed)) + "/" + str(len(multi))
            + " 条本次预估）；实际段数复用HUD查询，每段都按完整威力结算（source_power_per_hit），不提供旧总威力均分模式。"
            "描述里的「应对成功改变段数」「位置连击+1」等条件加成一律不计。")

    return {
        "snapshot_id": rules.snapshot_id,
        "catalog_content_hash": rules.catalog_content_hash,
        "side": side,
        "attacker": {
            "member_id": attacker["member_id"],
            "slot_index": attacker_slot,
            "form_id": attacker["form_id"],
            "name": name_of(attacker),
            "types": list(attacker["types"]),
            "hp": attacker_hp,
            "max_hp": attacker["max_hp"],
            "energy": attacker["energy"],
            "max_energy": attacker.get("max_energy"),
            "stats": {dim: attacker["stats"][dim] for dim in DIMS if dim != "hp"},
            "setup_notes": list(attacker.get("setup_notes", [])),
        },
        "defender": {
            "member_id": defender["member_id"],
            "slot_index": defender_slot,
            "form_id": defender["form_id"],
            "name": name_of(defender),
            "types": list(defender["types"]),
            "hp": defender_hp,
            "max_hp": defender["max_hp"],
            "stats": {dim: defender["stats"][dim] for dim in DIMS if dim != "hp"},
            "setup_notes": list(defender.get("setup_notes", [])),
        },
        "results": results,
        "non_damage_slots": non_damage,
        "blocked_slots": blocked,
        "stat_terms": {side_key: {stat: [float(term) for term in values] for stat, values in entries.items()}
                       for side_key, entries in terms.items()},
        "warnings": warnings,
        "excluded_effects": list(EXCLUDED_EFFECTS),
        "policy": {
            "candidate_id": chosen_settings["damage_candidate"],
            "same_type_multiplier": same_type_policy,
            "expression": POLICY_NOTE,
            "defense_mitigation": "raw * (100 - n) // 100（引擎同式，需自行乘算）",
            "calibrated": False,
        },
        "calibrated": False,
        "training_eligible": False,
    }


def name_of(member):
    return member.get("name") or str(member.get("form_id"))
