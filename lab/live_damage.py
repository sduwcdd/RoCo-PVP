"""HUD 用的「这一手大概打多少」：复用平台自己的伤害表达式，不另立一套公式。

当前版本把捕获的含性格基础面板、状态层数与来源绑定的特性、天气和印记查询组合。
印记引爆/回合损血及愿力强化预览单列，避免占用四槽或重复算进每段连击。
应对成功单独给出条件分支；不预设对方行动，排除防御选择、其他条件连击、首领化及光合治愈。
未知条件给出区间或具体阻断原因；公式、状态叠加和触发顺序仍未全量实战校准。

数值口径（与 ``arena_documented_damage60_v1`` 相同）：

    numerator = round(攻方面板 × 每段威力 × 属性倍率 × 本系倍率 × 37/41)
    damage    = floor(numerator / 守方面板)

多段技能按段数逐段取整后求和，**每段都用完整威力**（40 威力 3 连击 = 打 3 次）。
"""
from __future__ import annotations

import math
from fractions import Fraction
from functools import lru_cache
from typing import Any

from .pvp_rules import SAME_TYPE_MULTIPLIER, CRITICAL_MULTIPLIER
from . import battle_data
from .numeric_candidates import arena_documented_damage60
from .live_stat_model import is_world, star_candidates, stat_candidates

# skill_dam_type 数字 ↔ 属性名。battle_data 里是「草」，规则快照里是「草系」，
# 这里统一成规则侧写法，属性倍率才查得到。
_CODE_TO_TYPE = {code: f"{name}系" for name, code in battle_data.TYPE_CODES.items()}

# PVP用户确认无暴击；保留字段兼容旧调用，但倍率由统一PVP配置设为1。
_CRIT_MULTIPLIER = CRITICAL_MULTIPLIER

_PANEL_KEYS = {
    "physical": ("phyAtk", "phyDef"),
    "magical": ("magAtk", "magDef"),
}

PREVIEW_POLICY = {
    "calibrated": False,
    "scope": "known_current_effects_with_separate_response_scenario",
    "excluded_effects": ["防御减伤", "其他条件连击", "首领化", "光合治愈"],
    "notice": "计入当前已知状态、特性、天气和印记；未知条件保持区间或具体原因，仍未完成实战校准。",
}


@lru_cache(maxsize=1)
def _rules():
    """延迟拿规则快照（catalog 在 server 启动时加载，这里只借用不修改）。

    ``server.load_catalog()`` 返回 ``(catalog, digest, path)``，规则对象只要第一个。
    """
    from .catalog_store import runtime_catalog
    from .ruleset import BwikiRuleset
    catalog, _digest, _path = runtime_catalog()
    rules = BwikiRuleset(catalog)
    return catalog, rules


def _stats_of(pet: dict, want: str) -> float | None:
    """Read raw panels; live_modifiers handles their explicit basis and status layers."""
    for source in (pet.get("battleStats") or {}, pet.get("stats") or {}):
        value = source.get(want)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None


def _pet_types(pet: dict) -> list[str]:
    """精灵自身属性（用于本系加成）。萌化退化后按退化形态算。"""
    base = pet.get("stageBaseConfId") or pet.get("petBaseId") or pet.get("iconId")
    codes = battle_data.pet_unit_types(base)
    return [_CODE_TO_TYPE[code] for code in codes if code in _CODE_TO_TYPE]


def _effective_base(pet: dict) -> Any:
    return pet.get("stageBaseConfId") or pet.get("petBaseId") or pet.get("iconId")


@lru_cache(maxsize=64)
def nature_info(nature_id: Any) -> dict[str, Any]:
    """nature id → 名字与增减方向（报文直接下发 id，不需要推断）。"""
    try:
        catalog, _rules_obj = _rules()
    except Exception:                     # noqa: BLE001
        return {}
    for entry in catalog.get("natures") or []:
        if entry.get("id") == nature_id:
            return {
                "name": (entry.get("name") or {}).get("zh"),
                "up": entry.get("up"),
                "down": entry.get("down"),
            }
    return {}


@lru_cache(maxsize=512)
def _estimate_one(attacker_base: Any, attacker_stats_key: str, defender_base: Any,
                  defender_stats_key: str, skill_id: int) -> dict[str, Any]:
    """纯计算，参数全部是可哈希的原始值，方便缓存。"""
    catalog, rules = _rules()
    # BWiki 快照优先（它的威力/属性经过校对），实机新增技能退到解包数据。
    info = battle_data.skill_info(skill_id)
    kind = info.get("kind")
    power = info.get("power")
    skill_type = _CODE_TO_TYPE.get(info.get("type_code"))
    try:
        catalog_skill = rules.skill(skill_id)
        if catalog_skill.get("kind") in _PANEL_KEYS or catalog_skill.get("kind") == "higher":
            kind = catalog_skill["kind"]
        if isinstance(catalog_skill.get("power"), (int, float)) and catalog_skill["power"] > 0:
            power = catalog_skill["power"]
        if isinstance(catalog_skill.get("type"), str) and catalog_skill["type"]:
            skill_type = catalog_skill["type"]
    except Exception:                     # noqa: BLE001 - 不在快照里就用解包值
        pass
    if kind not in ("physical", "magical", "higher"):
        return {"reason": "变化技能或未登记威力，不算伤害"}
    if not isinstance(power, (int, float)) or power < 0 or (power == 0 and not info.get("damage_rule")):
        return {"reason": "缺威力，不算伤害"}
    attacker_stats = _decode_stats(attacker_stats_key)
    defender_stats = _decode_stats(defender_stats_key)
    if kind == "physical":
        atk_key, def_key = "phyAtk", "phyDef"
    elif kind == "magical":
        atk_key, def_key = "magAtk", "magDef"
    else:
        # 愿力冲击：先用双攻更高的那一项，守方取对应那一项防御。
        if (attacker_stats.get("phyAtk") or 0) >= (attacker_stats.get("magAtk") or 0):
            atk_key, def_key = "phyAtk", "phyDef"
        else:
            atk_key, def_key = "magAtk", "magDef"
    attack = attacker_stats.get(atk_key)
    defense = defender_stats.get(def_key)
    if not attack or not defense:
        # 野外/NPC 对局里，敌方 battle_attr 只下发生命，攻防都是 0；
        # 没有守方面板就算不出伤害，绝不能拿种族值凑一个数字出来冒充。
        return {"reason": "对方攻防面板未下发，算不出伤害"}

    if not skill_type:
        return {"reason": "缺属性，无法判断克制"}
    try:
        raw = rules.type_multiplier(skill_type, defender_base)
        frac = raw.get("multiplier") or {}
        multiplier = float(Fraction(int(frac.get("numerator", 1)), int(frac.get("denominator", 1))))
    except Exception as exc:              # noqa: BLE001
        # 拿不到克制表就明说，不能当成 1 倍糊过去（那会给出错误的低估值）。
        return {"reason": f"克制表不可用（{exc}）"}
    stab = SAME_TYPE_MULTIPLIER if skill_type in _pet_types_from_base(attacker_base) else 1.0
    combined = multiplier * stab

    hits = 1
    try:
        hits = int(_base_hits(catalog, skill_id)) or 1
    except Exception:                     # noqa: BLE001
        hits = int(info.get("hits") or 1) or 1
    if hits < 1:
        hits = 1

    single = arena_documented_damage60(attack, defense, power, combined)["nominal_damage"]
    normal = int(single) * hits
    critical = int(math.floor(
        arena_documented_damage60(attack, defense, power, combined * _CRIT_MULTIPLIER)["nominal_damage"]
    )) * hits
    return {
        "perHit": int(single),
        "hits": hits,
        "normal": normal,
        "critical": critical,
        "multiplier": round(multiplier, 3),
        "stab": stab,
        "kind": kind,
        "attackStat": atk_key,
        "skillType": skill_type,
    }


def _decode_stats(key: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for part in (key or "").split(","):
        if ":" not in part:
            continue
        name, _, value = part.partition(":")
        try:
            out[name] = float(value)
        except ValueError:
            continue
    return out


def _stats_key(pet: dict) -> str:
    keys = ("phyAtk", "magAtk", "phyDef", "magDef")
    parts = []
    for name in keys:
        value = _stats_of(pet, name)
        if value is not None:
            parts.append(f"{name}:{value:.0f}")
    return ",".join(parts)


@lru_cache(maxsize=64)
def _pet_types_from_base(base: Any) -> tuple[str, ...]:
    codes = battle_data.pet_unit_types(base)
    return tuple(_CODE_TO_TYPE[code] for code in codes if code in _CODE_TO_TYPE)


@lru_cache(maxsize=1)
def _base_hits_fn():
    from .skill_hits import base_hits
    return base_hits


def _base_hits(catalog, skill_id):
    return _base_hits_fn()(catalog, skill_id)[0]


# -- 由实测伤害反推面板 ---------------------------------------------------
# 野外/NPC 对局里敌方 battle_attr 往往只下发生命（攻防全 0），所以「对方攻防未
# 下发」时只能给出候选；裸伤害公式反解仍受未建模的增减伤影响，不能当作真实面板。

_FACTOR = Fraction(37, 41)


def skill_math(skill_id: int, attacker_base: Any, defender_base: Any) -> dict[str, Any]:
    """技能的静态部分：类型（物/魔/取高）、威力、属性倍率 × 本系倍率。

    结算报文里的 ``source_id`` 是 9 位写法（槽位 id ×100 + 后缀），图鉴里是 7 位，
    所以查不到时按 7 位再试一次。
    """
    for candidate in _skill_variants(skill_id):
        result = _skill_math_one(candidate, attacker_base, defender_base)
        if not result.get("reason") or "变化技能" not in str(result.get("reason")):
            return result
    return _skill_math_one(skill_id, attacker_base, defender_base)


def _skill_variants(skill_id: Any):
    yield skill_id
    try:
        value = int(skill_id)
    except (TypeError, ValueError):
        return
    if value > 9_999_999:
        yield value // 100


def _skill_math_one(skill_id: int, attacker_base: Any, defender_base: Any, *, preview_power=None) -> dict[str, Any]:
    catalog, rules = _rules()
    info = battle_data.skill_info(skill_id)
    if info and info.get("category") != 1:
        return {"reason": "被动或状态效果，不是携带技能的直接伤害"}
    kind = info.get("kind")
    power = info.get("power")
    skill_type = _CODE_TO_TYPE.get(info.get("type_code"))
    try:
        catalog_skill = rules.skill(skill_id)
        if catalog_skill.get("kind") in _PANEL_KEYS or catalog_skill.get("kind") == "higher":
            kind = catalog_skill["kind"]
        if isinstance(catalog_skill.get("power"), (int, float)) and catalog_skill["power"] > 0:
            power = catalog_skill["power"]
        if isinstance(catalog_skill.get("type"), str) and catalog_skill["type"]:
            skill_type = catalog_skill["type"]
    except Exception:                     # noqa: BLE001
        pass
    if preview_power is not None:
        power = preview_power  # Only source-validated dynamic previews supply this internal input.
    if kind not in ("physical", "magical", "higher"):
        return {"reason": "变化技能，不产生面板线索"}
    if not isinstance(power, (int, float)) or power <= 0:
        return {"reason": "缺威力"}
    if not skill_type:
        return {"reason": "缺属性"}
    try:
        raw = rules.type_multiplier(skill_type, defender_base)
        frac = raw.get("multiplier") or {}
        multiplier = float(Fraction(int(frac.get("numerator", 1)), int(frac.get("denominator", 1))))
    except Exception as exc:              # noqa: BLE001
        return {"reason": f"克制表不可用（{exc}）"}
    from .live_power import specification
    ignore_resistance = bool((specification(info.get("skill_id", skill_id)) or {}).get("ignore_resistance"))
    if ignore_resistance and 0 < multiplier < 1:
        multiplier = 1
    stab = SAME_TYPE_MULTIPLIER if skill_type in _pet_types_from_base(attacker_base) else 1.0
    return {
        "kind": kind,
        "power": float(power),
        "multiplier": multiplier,
        "stab": stab,
        "combined": multiplier * stab,
        "skillType": skill_type,
        "hits": _hits_of(catalog, skill_id, info),
        "resolvedVariant": (info.get("name") or "").startswith("应对！"),
        "ignoreResistance": ignore_resistance,
        "damageRule": info.get("damage_rule"),
    }


def _hits_of(catalog, skill_id: int, info: dict) -> int:
    from .live_power import specification
    spec = specification(info.get("skill_id", skill_id))
    if spec and spec.get("hits"):
        return spec["hits"]
    try:
        return max(1, int(_base_hits(catalog, skill_id)) or 1)
    except Exception:                     # noqa: BLE001
        try:
            return max(1, int(info.get("hits") or 1) or 1)
        except (TypeError, ValueError):
            return 1


def panel_from_hit(*, attack: float | None = None, defense: float | None = None,
                   power: float, combined: float, damage: float,
                   critical: bool = False) -> dict[str, float]:
    """已知一侧面板 + 一次实测伤害 → 反推另一侧面板。

    结算式：``damage = floor(round(攻 × 威力 × 倍率 × 37/41) / 防)``，
    所以 ``防 ∈ (num/(damage+1), num/damage]``，取区间中点为估计值。
    """
    if damage is None or damage <= 0 or power <= 0 or combined <= 0:
        return {}
    if critical:
        combined = combined * _CRIT_MULTIPLIER
    if attack and attack > 0:
        num = arena_documented_damage60(attack, 1, power, combined)["nominal_damage"]
        if num <= 0:
            return {}
        low = num / (damage + 1)
        high = num / damage
        return {"defense": (low + high) / 2, "defenseLow": low, "defenseHigh": high}
    if defense and defense > 0:
        # Invert the same integer expression, including rounding before division.
        upper = max(2, math.ceil((damage + 1) * defense / (power * combined * float(_FACTOR))) + 4)
        def first_above(threshold):
            left, right = 1, upper
            while left < right:
                mid = (left + right) // 2
                dealt = arena_documented_damage60(mid, defense, power, combined)["nominal_damage"]
                if dealt >= threshold:
                    right = mid
                else:
                    left = mid + 1
            return left
        low, high = first_above(damage), first_above(damage + 1) - 1
        if low > high:
            return {}
        return {"attack": (low + high) / 2, "attackLow": low, "attackHigh": high}
    return {}


def estimate_moves(attacker: dict, defender: dict) -> list[dict[str, Any]]:
    """攻方每个技能槽打守方的伤害。

    与 ``estimate_incoming`` 同一套逻辑：任一侧面板缺失都给区间，两侧都确定才给单值。
    """
    return estimate_incoming(attacker, defender)


_ATTR_TO_SHORT = {"hp": "hp", "phyAtk": "patk", "magAtk": "matk", "phyDef": "pdef", "magDef": "mdef", "spd": "spd"}


def _skill_damage_profile(skill_id: int, attacker_base: Any, defender_base: Any) -> dict[str, Any]:
    # Use the same ID normalization and static parameters as inverse damage calculations.
    return skill_math(skill_id, attacker_base, defender_base)


def _nature_pairs(pet):
    dims = ("hp", "patk", "matk", "pdef", "mdef", "spd")
    nat = nature_info(pet.get("nature")) or {}
    up = pet.get("natureUp") or nat.get("up")
    down = pet.get("natureDown") or nat.get("down")
    known = pet.get("natureOverrideKnown") or {}
    for direction, field in (("up", "naturePosOverride"), ("down", "natureNegOverride")):
        value = None if known.get(direction) is False else (
            dims[pet[field] - 1] if pet.get(field) in range(1, 7) else (up if direction == "up" else down))
        if direction == "up":
            up = value
        else:
            down = value
    return [(u, d) for u in dims for d in dims if u != d
            and (not up or u == up) and (not down or d == down)]


@lru_cache(maxsize=512)
def _race_stats(base):
    if base is None:
        return {}, "形态未知"
    catalog, _ = _rules()
    for form in catalog.get("forms", []):
        if any(value is not None and str(base) == str(value) for value in (form.get("id"), form.get("game_id"))):
            return form.get("stats") or {}, "BWIKI种族值"
    return battle_data.pet_race_stats(base), "解包种族值（BWIKI未匹配）"


def _talent_values(pet, dim):
    selection = pet.get("talent_selection")
    if isinstance(selection, dict):
        selected = selection.get("selected", [])
        if dim in selected:
            value = selection.get("values", {}).get(dim)
            if type(value) is not int or not 0 <= value <= 10:
                raise ValueError("已选个体值必须为0–10的整数")
            return [value]
        if len(selected) == 3:
            return [0]
    individuals = pet.get("individuals") or {}
    key = next((k for k in (dim, next((k for k, d in _ATTR_TO_SHORT.items() if d == dim), dim))
                if k in individuals and individuals[k] is not None), None)
    if key is not None:
        value = individuals[key]
        if type(value) is not int or not 0 <= value <= 10:
            raise ValueError("个体值必须为0–10的整数")
        return [value]
    return list(range(11))


def panel_values(pet, stat):
    """Return all allowed values for one combat stat; never promote an inferred midpoint."""
    value = (pet.get("battleStats") or {}).get(stat)
    if isinstance(value, (int, float)) and math.isfinite(value) and value > 0 and stat not in (pet.get("battleStatsEstimated") or {}):
        return [float(value)], "实时面板"
    inference = pet.get("configurationInference") or {}
    if inference.get("status") == "model_mismatch":
        raise ValueError("下发面板与当前配置候选冲突，不能沿用冲突性格估计未知面板")
    constrained = inference.get("panel_ranges", {}).get(stat)
    if inference.get("status") in ("conditional", "protocol", "damage_conflict") and constrained:
        return list(constrained), "面板与实战伤害约束（未校准条件候选）"
    bounds = (pet.get("battleStatsRanges") or {}).get(stat)
    if bounds is not None:
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 2 or not 0 < bounds[0] <= bounds[1]:
            raise ValueError("面板候选范围无效")
        return [float(bounds[0]), float(bounds[1])], "观测约束面板范围"
    value = (pet.get("naturedStats") or {}).get(stat)
    if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
        return [float(value)], "已确定性格面板"
    bounds = (pet.get("naturedStatsRange") or {}).get(stat)
    if bounds and len(bounds) == 2 and 0 < bounds[0] <= bounds[1]:
        return [float(bounds[0]), float(bounds[1])], "星级候选范围"
    dim = _ATTR_TO_SHORT[stat]
    # An unmodified panel is not a combat panel: apply every still-possible direction.
    raw = (pet.get("initialStats") or pet.get("stats") or {}).get(stat)
    pairs = _nature_pairs(pet)
    if not pairs:
        raise ValueError("性格增减方向冲突")
    if isinstance(raw, (int, float)) and raw > 0 and not is_world(pet):
        from .live_battle import nature_adjusted_stat
        stars = star_candidates(pet)
        values = {nature_adjusted_stat(pet.get("level") or 60, stat, raw,
                                      "up" if up == dim else "down" if down == dim else None, stars=s)
                  for up, down in pairs for s in stars}
        return sorted(values), "基础面板+性格/星级候选"
    if not is_world(pet) and pet.get("level") not in (None, 60):
        raise ValueError("缺少该等级面板：60级公式不能代算其他等级")
    race, source = _race_stats(_effective_base(pet))
    base = race.get(dim)
    if not base and not is_world(pet):
        raise ValueError("缺少当前形态种族值")
    values, failures = set(), set()
    for stars in star_candidates(pet):
        try:
            values.update(value for up, down in pairs for talent in _talent_values(pet, dim)
                          for value in stat_candidates(pet, race, dim, talent, up, down, stars))
        except ValueError as error:
            failures.add(str(error))
    if failures:
        raise ValueError("；".join(sorted(failures)) + "；不能将局部星级候选当作完整范围")
    if not values:
        raise ValueError("基础面板与当前性格/资质候选不匹配")
    return sorted(values), source + "+性格/个体候选"


def stat_summary(pet: dict) -> dict[str, Any]:
    """Keep fixed species stats separate from uncertain, unbuffed panel candidates."""
    result = {"raceStats": {}, "panelStatRanges": {}, "panelStatSources": {}, "panelStatIssues": {}}
    try:
        race, source = _race_stats(_effective_base(pet))
        result["raceStats"] = {key: race[dim] for key, dim in _ATTR_TO_SHORT.items() if dim in race}
        result["raceStatsSource"] = source
    except (OSError, ValueError, KeyError, ImportError, TypeError) as error:
        result["raceStatsSource"] = str(error)
    # Radar values exclude battle buffs and the uncalibrated inverse-damage candidates.
    baseline = {**pet, "battleStats": {}, "battleStatsRanges": {}}
    for key in _ATTR_TO_SHORT:
        try:
            values, source = panel_values(baseline, key)
            result["panelStatRanges"][key] = [min(values), max(values)]
            result["panelStatSources"][key] = source
        except (OSError, ValueError, KeyError, ImportError, TypeError) as error:
            result["panelStatIssues"][key] = str(error)
    return result


def attack_bounds(pet: dict, stat: str):
    """Compatibility entry point; both attack and defense now use the same candidate path."""
    key = next((key for key, short in _ATTR_TO_SHORT.items() if short == stat), None)
    if not key:
        return None
    try:
        values, _ = panel_values(pet, key)
        return min(values), max(values)
    except (ValueError, KeyError):
        return None


def _damage_case(attacker, defender, profile, kind, attack_values=None):
    from .live_modifiers import damage_profile, panel_candidates
    profile = damage_profile(attacker, defender, profile["skillId"], {**profile, "kind": kind})
    attack_key, defense_key = _PANEL_KEYS[kind]
    attack, attack_source = panel_candidates(attacker, attack_key, defender)
    if attack_values is not None:
        attack = attack_values
    defense, defense_source = panel_candidates(defender, defense_key, attacker)
    def hit(a, d, power, final_factor, critical=1):
        from .live_stat_model import damage_value
        nominal = damage_value(attacker, a, d, power, profile["combined"] * critical)
        return math.floor(nominal * final_factor)
    low_power, high_power = profile["powerRange"]
    low_final, high_final = profile["finalMultiplierRange"]
    critical_multiplier = 2 if is_world(attacker) else _CRIT_MULTIPLIER
    return {
        "minimum": hit(min(attack), max(defense), low_power, low_final),
        "maximum": hit(max(attack), min(defense), high_power, high_final),
        "criticalMinimum": hit(min(attack), max(defense), low_power, low_final, critical_multiplier),
        "criticalMaximum": hit(max(attack), min(defense), high_power, high_final, critical_multiplier),
        "atkRange": [min(attack), max(attack)], "defRange": [min(defense), max(defense)],
        "attackStat": attack_key, "defenseStat": defense_key,
        "atkSource": attack_source, "defSource": defense_source,
        "powerRange": profile["powerRange"], "finalMultiplierRange": profile["finalMultiplierRange"], "effects": profile["effects"],
    }


def _higher_attack_values(pet, opponent):
    """Keep both attacks on the same nature and feasible three-talent configuration."""
    result = {"physical": set(), "magical": set()}
    from .live_modifiers import panel_candidates
    physical, _ = panel_candidates(pet, "phyAtk", opponent)
    magical, _ = panel_candidates(pet, "magAtk", opponent)
    if len(physical) == len(magical) == 1:
        result["physical" if physical[0] >= magical[0] else "magical"].add(max(physical[0], magical[0]))
        return result
    required = set((pet.get("talent_selection") or {}).get("selected", []))
    for up, down in _nature_pairs(pet):
        pairs = []
        for dim, stat in (("patk", "phyAtk"), ("matk", "magAtk")):
            values = []
            for talent in _talent_values(pet, dim):
                fixed = {**pet, "natureUp": up, "natureDown": down,
                         "individuals": {**(pet.get("individuals") or {}), dim: talent}}
                panels, _ = panel_candidates(fixed, stat, opponent)
                values.extend((talent, value) for value in panels)
            pairs.append(values)
        for physical_talent, physical in pairs[0]:
            for magical_talent, magical in pairs[1]:
                selected = required | ({"patk"} if physical_talent > 0 else set()) | ({"matk"} if magical_talent > 0 else set())
                if len(selected) <= 3:
                    result["physical" if physical >= magical else "magical"].add(max(physical, magical))
    return result


def _estimate_profile(attacker, defender, profile, higher_values=None):
    if profile.get("reason"):
        raise ValueError(profile["reason"])
    if profile["kind"] == "higher":
        cases = [_damage_case(attacker, defender, profile, kind, allowed)
                 for kind, allowed in (higher_values if higher_values is not None else _higher_attack_values(attacker, defender)).items() if allowed]
        if not cases:
            raise ValueError("双攻候选与三选六配置冲突")
    else:
        cases = [_damage_case(attacker, defender, profile, profile["kind"])]
    from .live_power import resolved_hits
    hits = resolved_hits(attacker, profile)
    minimum, maximum = min(c["minimum"] for c in cases) * hits, max(c["maximum"] for c in cases) * hits
    crit_low, crit_high = min(c["criticalMinimum"] for c in cases) * hits, max(c["criticalMaximum"] for c in cases) * hits
    exact = all(c["atkRange"][0] == c["atkRange"][1] and c["defRange"][0] == c["defRange"][1]
                and c["powerRange"][0] == c["powerRange"][1]
                and c["finalMultiplierRange"][0] == c["finalMultiplierRange"][1] for c in cases) and len(cases) == 1
    entry = {"normalMin": minimum, "normalMax": maximum, "criticalMin": crit_low, "criticalMax": crit_high,
             "hits": hits, "exact": exact, "branches": cases, "multiplier": profile["multiplier"], "stab": profile["stab"],
             "atkRange": cases[0]["atkRange"], "defRange": cases[0]["defRange"],
             "atkSource": cases[0]["atkSource"], "defSource": cases[0]["defSource"],
             "perHitMin": minimum // hits, "perHitMax": maximum // hits,
             "criticalPerHitMin": crit_low // hits, "criticalPerHitMax": crit_high // hits,
             "effects": [c["effects"] for c in cases]}
    if exact:
        entry.update(normal=minimum, critical=crit_low, perHit=minimum // hits)
    hp, max_hp = defender.get("currentHp"), defender.get("maxHp")
    if isinstance(hp, (int, float)):
        entry.update(lethal=minimum >= hp, possibleLethal=maximum >= hp, oneShot=hp > 0 and minimum > hp)
    if isinstance(max_hp, (int, float)) and max_hp > 0:
        entry.update(normalPct=round(minimum * 100 / max_hp, 1),
                     criticalPct=round(crit_low * 100 / max_hp, 1), maxPct=round(maximum * 100 / max_hp, 1))
    if '_simulation_actor' not in attacker and '_resolved_first_attack' not in attacker:
        trait_id = attacker.get('effectiveTraitId')
        if trait_id is None:
            trait_id = battle_data.pet_form(_effective_base(attacker)).get('feature_id')
        if trait_id == 200124:
            entry['traitScenarios'] = [
                {'triggered': flag, 'label': '触发顺风' if flag else '未触发顺风',
                 'condition': '先于敌方攻击' if flag else '未先于敌方攻击',
                 **_estimate_profile({**attacker, '_resolved_first_attack': flag}, defender, profile, higher_values)}
                for flag in (False, True)]
    return entry


def wish_scenarios(attacker, defender):
    """Explicit unknown-bloodline scenarios, never an inferred enemy configuration."""
    from .live_power import response_variant
    higher = _higher_attack_values(attacker, defender)
    groups = {label: {'label': label, 'multiplier': multiplier, 'types': [], False: [], True: []}
              for label, multiplier in (('抵抗', .5), ('正常', 1), ('克制', 2), ('3倍克制', 3))}
    for code in battle_data.TYPE_CODES.values():
        move = battle_data.will_impact_skill(code)
        if not move:
            continue
        sid = move['skillId']
        normal_profile = skill_math(sid, _effective_base(attacker), _effective_base(defender))
        multiplier = normal_profile.get('multiplier')
        label = '抵抗' if multiplier is not None and 0 < multiplier < 1 else {1:'正常', 2:'克制', 3:'3倍克制'}.get(multiplier)
        if label is None:
            continue
        group = groups[label]
        group['types'].append(normal_profile['skillType'])
        for response in (False, True):
            resolved = response_variant(sid) if response else sid
            if not resolved:
                raise ValueError('愿力应对配置未核对')
            profile = {**skill_math(resolved, _effective_base(attacker), _effective_base(defender)), 'skillId': resolved}
            if profile.get('reason'):
                raise ValueError(profile['reason'])
            group[response].append(_estimate_profile(attacker, defender, profile, higher))
    rows = []
    for group in groups.values():
        def bounds(quotes):
            if not quotes:
                return {'normalMin': None, 'normalMax': None}
            return {'normalMin': min(q['normalMin'] for q in quotes), 'normalMax': max(q['normalMax'] for q in quotes),
                    'oneShot': all(q.get('oneShot', False) for q in quotes)}
        rows.append({'label': group['label'], 'multiplier': group['multiplier'], 'types': group['types'],
                     **bounds(group[False]), 'response': bounds(group[True])})
    return {'hypothetical': True, 'rows': rows, 'note': '按当前目标实际可出现的愿力属性倍率分组；未知血脉，不代表已确认携带属性。'}


def preview_target(snapshot, request):
    """On-demand single-move forecast from one immutable published observation."""
    runtime = (snapshot or {}).get('runtime') or {}
    if request.get('sessionId') != runtime.get('sessionId') or request.get('snapshotToken') != runtime.get('snapshotToken'):
        raise ValueError('对局状态已更新，请重新选择目标')
    side = request.get('side')
    if side not in ('my', 'enemy'):
        raise ValueError('请选择己方或敌方技能')
    own_key, other_key = ('myTeam', 'enemyTeam') if side == 'my' else ('enemyTeam', 'myTeam')
    own, other = runtime.get(own_key) or [], runtime.get(other_key) or []
    active = ((runtime.get('active') or {}).get(side) or {}).get('rosterIndex', 0)
    if type(active) is not int or not 0 <= active < len(own):
        raise ValueError('当前在场精灵尚未确认')
    attacker = own[active]
    if str(request.get('actorPetId')) != str(attacker.get('petId')):
        raise ValueError('当前在场精灵已变化')
    targets = [p for p in other if str(p.get('petId')) == str(request.get('targetPetId'))]
    if len(targets) != 1 or targets[0].get('alive') is False or targets[0].get('currentHp') == 0:
        raise ValueError('目标不存在、尚未识别或已经倒下')
    hypothetical = request.get('previewMode') == 'skill-pool'
    if hypothetical:
        from .server import form_skill_pool
        if side != 'enemy':
            raise ValueError('图鉴候选试算仅适用于敌方技能查询')
        opposite_active = ((runtime.get('active') or {}).get('my') or {}).get('rosterIndex', 0)
        if type(opposite_active) is not int or not 0 <= opposite_active < len(other) or targets[0] is not other[opposite_active]:
            raise ValueError('图鉴候选只能对当前我方在场精灵试算')
        catalog = _rules()[0]
        pool = form_skill_pool(catalog, attacker.get('stageBaseConfId') or attacker.get('petBaseId'))
        if type(request.get('skillId')) is not int or not any(s['skillId'] == request['skillId'] for s in pool['skills']):
            raise ValueError('该技能不在当前具体形态的图鉴学习范围')
        moves = [{'skillId': request['skillId'], 'slot': None, 'observedOnly': True}]
    else:
        moves = [m for m in attacker.get('moves', []) if m.get('skillId') == request.get('skillId') and m.get('slot') == request.get('slot')]
    if len(moves) != 1:
        raise ValueError('该技能未携带或尚未观测，不能从技能池补入')
    if request.get('previewMode') == 'listening':
        opposite = 'enemy' if side == 'my' else 'my'
        target_active = ((runtime.get('active') or {}).get(opposite) or {}).get('rosterIndex', 0)
        if type(target_active) is not int or not 0 <= target_active < len(other) or targets[0] is not other[target_active]:
            raise ValueError('听桥只能选择对方当前在场精灵的技能')
        result = _preview_listening(attacker, targets[0], moves[0], request)
        return {'snapshotToken': runtime.get('snapshotToken'), **result}
    result = estimate_moves({**attacker, 'moves': moves}, targets[0])
    return {'snapshotToken': runtime.get('snapshotToken'), 'targetPetId': targets[0].get('petId'),
            'targetName': targets[0].get('petName') or targets[0].get('name'),
            'estimate': result[0] if result else {'reason': '缺少计算条件'},
            'hypothetical': hypothetical,
            'note': ('假设携带该技能，学习条件及实际携带未确认；不计入已观测四槽。' if hypothetical else
                     '目标按当前已知面板与状态试算；未执行换人及入场触发。')}


def _preview_listening(attacker, defender, move, request):
    from .live_power import specification, response_variant
    from .live_modifiers import damage_profile
    spec = specification(move['skillId']) or {}
    if not spec.get('counter_preview'):
        raise ValueError('该技能没有来源已校验的听桥反击配置')
    if attacker.get('alive') is False or attacker.get('currentHp') == 0:
        raise ValueError('已倒下，不能使用听桥')
    observed = {}
    for candidate in defender.get('moves') or []:
        sid = battle_data.canonical_skill(candidate.get('skillId')).get('skill_id')
        if sid is not None:
            observed[sid] = battle_data.skill_info(sid)
    options = [{'value': f'move:{sid}', 'label': info['name'],
                'disabled': info.get('kind') not in ('physical', 'magical', 'higher')}
               for sid, info in observed.items()]
    groups = {label: [] for label in ('抵抗', '正常', '克制', '3倍克制')}
    for code in battle_data.TYPE_CODES.values():
        wish = battle_data.will_impact_skill(code)
        if not wish:
            continue
        profile = skill_math(wish['skillId'], _effective_base(defender), _effective_base(attacker))
        multiplier = profile.get('multiplier')
        label = '抵抗' if multiplier is not None and 0 < multiplier < 1 else {1: '正常', 2: '克制', 3: '3倍克制'}.get(multiplier)
        if label:
            groups[label].append((wish['skillId'], profile.get('skillType')))
    options.extend({'value': 'wish:' + label, 'label': '愿力冲击·' + label,
                    'types': [kind for _, kind in skills], 'disabled': not skills}
                   for label, skills in groups.items())
    result = {'counterOptions': options, 'note': '仅试算应对攻击成功后的武系物理反击；未应对时无反击。愿力四档为属性情景，不表示已确认敌方血脉；愿力应对状态不因听桥这一防御技能而触发。当前按共享有效威力试算，加成的精确拷贝阶段仍待实战校准。'}
    selected, group = request.get('counterSkillId'), request.get('counterWishGroup')
    if selected is None and group is None:
        return result
    if selected is not None and group is not None:
        raise ValueError('每次只能选择一个被听桥的技能或愿力情景')
    if selected is not None:
        if type(selected) is not int or selected not in observed:
            raise ValueError('只能选择当前精灵已经携带或观测到的技能')
        if observed[selected].get('kind') not in ('physical', 'magical', 'higher'):
            raise ValueError('所选技能不属于可被听桥应对的攻击技能')
        skills = [selected]
        result['selectionLabel'] = observed[selected]['name']
    else:
        if not isinstance(group, str) or group not in groups or not groups[group]:
            raise ValueError('当前精灵没有该档愿力属性情景')
        skills = [sid for sid, _ in groups[group]]
        result['selectionLabel'] = '愿力冲击·' + group
    powers, higher_kinds = set(), None
    for sid in skills:
        # The submitted opponent attack faces a defense move, not a status move.
        row = _rules()[0]['moves'].get(str(sid), {})
        if 1017 in row.get('desc_notes', []):
            sid = response_variant(sid)
            if sid is None:
                raise ValueError('被听桥技能的应对防御威力尚未核对')
        profile = {**skill_math(sid, _effective_base(defender), _effective_base(attacker)), 'skillId': sid}
        if profile.get('reason'):
            raise ValueError(profile['reason'])
        if profile.get('kind') not in ('physical', 'magical', 'higher'):
            raise ValueError('所选技能不属于可被听桥应对的攻击技能')
        if profile['kind'] == 'higher' and higher_kinds is None:
            higher_kinds = [kind for kind, values in _higher_attack_values(defender, attacker).items() if values]
        kinds = [profile['kind']] if profile['kind'] != 'higher' else higher_kinds
        for kind in kinds:
            powers.update(damage_profile(defender, attacker, sid, {**profile, 'kind': kind})['powerRange'])
    response_id = spec['response']['id']
    profile = {**_skill_math_one(response_id, _effective_base(attacker), _effective_base(defender), preview_power=1),
               'skillId': response_id, 'counteredPowers': sorted(powers)}
    result['estimate'] = _estimate_profile(attacker, defender, profile)
    result['estimate']['condition'] = '听桥应对攻击成功'
    result['copiedPowerRange'] = [min(powers), max(powers)]
    return result


def _estimate_choices(attacker, defender, profile, spec):
    from .live_power import choice_damage_parameters
    choices = []
    for option in (0, 1):
        branch = {'option': option, 'label': '选择一' if option == 0 else '选择二'}
        notes = [f"使用后生命-{op['params']['percent']}%" for op in spec['options'][option]
                 if op['op'] == 'hp.recoil_percent']
        branch['note'] = '；'.join(notes)
        try:
            def quote(response):
                selected = {**profile, 'choiceOption': option, 'choiceResponse': response}
                parameters = choice_damage_parameters(attacker, defender, profile['skillId'], selected)
                hits = {p.get('hits', 1) for p in parameters}
                if len(hits) != 1:
                    raise ValueError('该选择分支的连击数仍有未解决条件')
                return _estimate_profile(attacker, defender, {**selected, 'hits': hits.pop()})
            branch.update(quote(False))
            response = quote(True)
            if any(response[k] != branch[k] for k in ('normalMin', 'normalMax', 'hits')):
                branch['response'] = response
        except (ValueError, KeyError, TypeError) as error:
            branch['reason'] = str(error)
        choices.append(branch)
    if any(c.get('reason') for c in choices):
        return {'choices': choices, 'reason': '选择分支存在待核实项，请查看各分支'}
    def signature(c):
        return (c['normalMin'], c['normalMax'], c['hits'],
                (c.get('response') or {}).get('normalMin'), (c.get('response') or {}).get('normalMax'),
                (c.get('response') or {}).get('hits'))
    if signature(choices[0]) == signature(choices[1]):
        return {k: v for k, v in choices[0].items() if k not in ('option', 'label', 'note')}
    # The legacy aggregate remains a bound; the UI shows the two choices separately.
    low, high = min(c['normalMin'] for c in choices), max(c['normalMax'] for c in choices)
    result = {**choices[0], 'choices': choices, 'normalMin': low, 'normalMax': high, 'exact': False,
              'oneShot': all(c.get('oneShot', False) for c in choices),
              'lethal': all(c.get('lethal', False) for c in choices),
              'possibleLethal': any(c.get('possibleLethal', False) for c in choices),
              'criticalMin': min(c['criticalMin'] for c in choices),
              'criticalMax': max(c['criticalMax'] for c in choices)}
    for key in ('normal', 'critical', 'perHit', 'response', 'option', 'label', 'note', 'normalPct', 'criticalPct', 'maxPct'):
        result.pop(key, None)
    result.update(perHitMin=low // result['hits'], perHitMax=high // result['hits'],
                  criticalPerHitMin=result['criticalMin'] // result['hits'],
                  criticalPerHitMax=result['criticalMax'] // result['hits'])
    return result


def estimate_incoming(attacker: dict, defender: dict) -> list[dict[str, Any]]:
    """Symmetric preview: exact combat panels give one value, unknown panels give extrema."""
    if not attacker or not defender:
        return []
    out = []
    for move in attacker.get("moves") or []:
        sid = move.get("skillId")
        if not isinstance(sid, int):
            continue
        entry = {"slot": move.get("slot"), "skillId": sid,
                 "calibrated": False, "scope": PREVIEW_POLICY["scope"]}
        hp = attacker.get("currentHp")
        if attacker.get("alive") is False or (type(hp) in (int, float) and hp <= 0):
            out.append({**entry, "reason": "已倒下，不能使用技能"})
            continue
        try:
            canonical = battle_data.canonical_skill(sid)
            if canonical.get("canonical_issue"):
                raise ValueError(canonical["canonical_issue"])
            normal_id = canonical.get("skill_id", sid)
            from .live_power import specification
            if (specification(normal_id) or {}).get('counter_preview'):
                entry.update(counterPreview=True, reason='选择对方技能后估计听桥反击；未应对攻击时无反击')
                out.append(entry)
                continue
            profile = {**_skill_damage_profile(normal_id, _effective_base(attacker), _effective_base(defender)),
                       "skillId": normal_id, "selectedSlot": None if move.get("observedOnly") else move.get("slot")}
            if profile.get("reason"):
                entry["reason"] = profile["reason"]
                entry["nonDamaging"] = battle_data.skill_info(normal_id).get("kind") == "status"
                out.append(entry)
                continue
            if profile.get("resolvedVariant"):
                entry["reason"] = "这是已发生的应对成功结算变体；下次应对条件未确定，不能沿用强化威力。"
                out.append(entry)
                continue
            from .live_power import choice_specification
            choice = choice_specification(normal_id)
            if choice is not None:
                entry.update(_estimate_choices(attacker, defender, profile, choice))
                out.append(entry)
                continue
            entry.update(_estimate_profile(attacker, defender, profile))
            from .live_power import response_variant, specification
            response_id = response_variant(normal_id)
            if response_id:
                try:
                    response_profile = {**skill_math(response_id, _effective_base(attacker), _effective_base(defender)),
                                        "skillId": response_id, "selectedSlot": profile.get("selectedSlot")}
                    response = _estimate_profile(attacker, defender, response_profile)
                    spec = specification(normal_id)
                    if (any(response[k] != entry[k] for k in ("normalMin", "normalMax", "hits"))
                            or spec["dam_para"] != spec["response"]["dam_para"]):
                        entry["response"] = {**response, "skillId": response_id, "condition": "应对成功"}
                except (ValueError, KeyError, TypeError) as error:
                    entry["response"] = {"skillId": response_id, "condition": "应对成功", "reason": str(error)}
        except (ValueError, KeyError, TypeError) as error:
            entry["reason"] = str(error)
        out.append(entry)
    return out
