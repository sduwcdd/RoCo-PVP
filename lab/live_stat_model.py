"""Shared, source-scoped live panel candidates; no implicit world talent scaling."""
import math
import hashlib
import json
from pathlib import Path

from .numeric_candidates import captured_stat60
from .trait_runtime import cached_source_query, _source_hash


STAT_KEYS = {"hp": "hp", "patk": "phyAtk", "matk": "magAtk",
             "pdef": "phyDef", "mdef": "magDef", "spd": "spd"}
WORLD_SOURCE = "data/reference/world-panel-20261101.json"
WORLD_SOURCE_SHA256 = "887c78c6e5d29fcde211d3329d3143623af8436de46fb7106dbf38b9e95f0bf4"
NPC_CONFIG = Path(__file__).resolve().parents[1] / "data/rules/reviewed-world-npc-stats-1.json"
NPC_CONFIG_SHA256 = "197ab3898b9f5b0c58b325fec1adb9704f0a702210d08359c8925bc5d55d1ca5"


@cached_source_query
def world_npc_rules():
    raw = NPC_CONFIG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != NPC_CONFIG_SHA256:
        raise ValueError("NPC成长候选配置已变化，需重新核对")
    data = json.loads(raw)
    if data.get("schema") != "reviewed-world-npc-stats-1":
        raise ValueError("NPC成长候选配置版本不匹配")
    for source in data["sources"]:
        path = (NPC_CONFIG.parents[2] / source["path"]).resolve()
        if not path.is_relative_to(NPC_CONFIG.parents[2]):
            raise ValueError("NPC成长来源路径越界")
        stamp = path.stat()
        if _source_hash(str(path), stamp.st_size, stamp.st_mtime_ns) != source["sha256"]:
            raise ValueError("NPC成长来源已变化，需重新核对")
    return data


def npc_profile(pet):
    if not is_world(pet) or not pet.get("worldNpc"):
        return None
    profile = world_npc_rules()["npcs"].get(str(pet.get("confId")))
    if not profile or str(profile["base_id"]) != str(pet.get("petBaseId")):
        raise ValueError("该NPC成长配置尚未核对，不能套用玩家资质模型")
    growth = profile["growth_by_level"].get(str(pet.get("level")))
    if not growth:
        raise ValueError("该NPC等级的成长配置尚未核对")
    return profile, growth


def damage_value(attacker, attack, defense, power, multiplier):
    from .numeric_candidates import arena_documented_damage60, native_world_level_damage
    if not is_world(attacker) or attacker.get("level") == 60:
        return arena_documented_damage60(attack, defense, power, multiplier)["nominal_damage"]
    data = world_npc_rules()
    source = {"path": "data/rules/reviewed-world-npc-stats-1.json", "candidate_id": data["candidate_id"],
              "calibrated": False, "sources": data["sources"]}
    return native_world_level_damage(attack, defense, power, multiplier, attacker.get("level"),
                                     data["level_damage"], source)["nominal_damage"]


def is_world(pet):
    return (pet.get("battleMode") == "world"
            or str((pet.get("natureStatsPolicy") or {}).get("source", "")).startswith("world"))


def star_candidates(pet):
    if not is_world(pet):
        return [5]
    level = pet.get("level")
    if type(level) is int and 0 < level < 60:
        return [0]
    stars = (pet.get("natureStatsPolicy") or {}).get("stars")
    if stars is not None:
        if type(stars) is not int or not 0 <= stars <= 10:
            raise ValueError("大世界星级必须为0–10的整数")
        return [stars]
    return list(range(11))


def _number(value, *, zero=False):
    return (type(value) in (int, float) and 0 <= value <= 1_000_000 and math.isfinite(value)
            and (value >= 0 if zero else value > 0))


def _zero_base(level, race, dim, raw_talent):
    if type(level) is not int or not 1 <= level <= 60:
        raise ValueError("大世界0星候选仅接受1–60级，其他等级未核实")
    if not _number(race) or type(raw_talent) is not int or not 0 <= raw_talent <= 60:
        raise ValueError("大世界面板缺少有效种族值或原始资质")
    # Four owned pets / 24 dimensions match; this is a captured candidate,
    # not a claim of complete level or float-boundary calibration.
    factor, constant = (2 * level + 50, level + 10) if dim == "hp" else (level + 50, 10)
    return math.floor(factor * (race / 100 + raw_talent / 200) + constant + .5)


def _natured(pet, dim, base, effort, up, down, stars):
    from .live_battle import nature_adjusted_stat
    direction = "up" if dim == up else "down" if dim == down else None
    # The existing adapter removes the five-star fixed bonus before nature.
    # Supply that offset, then retain the actual protocol effort separately.
    offset = (100 if dim == "hp" else 50) if stars >= 5 else 0
    value = nature_adjusted_stat(pet.get("level") or 60, STAT_KEYS[dim], base + offset,
                                 direction, stars=stars) - offset + effort
    if not _number(value):
        raise ValueError("原始面板与成长加成无法构成有效能力值")
    return int(value)


def stat_candidates(pet, race, dim, talent, up, down, stars):
    """Return one dimension for one shared star/talent/nature hypothesis.

    Positive-star world candidates require a downlinked base panel, or the
    already supported level-60 core with explicit raw talent and effort.
    No display*(stars+1), intermediate-star bonus or above-five boost is made up.
    """
    if dim not in STAT_KEYS or type(talent) is not int or not 0 <= talent <= 10:
        raise ValueError("能力维度或展示资质无效")
    if type(stars) is not int or not 0 <= stars <= 10:
        raise ValueError("星级候选无效")
    species = race.get(dim) if isinstance(race, dict) else race
    multiplier = 1.2 if dim == up else .9 if dim == down else 1
    if not is_world(pet):
        if pet.get("level") not in (None, 60):
            raise ValueError("缺少该等级面板：60级公式不能代算其他等级")
        return captured_stat60(species, talent * 6, multiplier, dim)["stat_values"]

    npc = npc_profile(pet)
    if npc:
        profile, growth = npc
        if stars != growth["nature_world_below60_stars"]:
            raise ValueError("NPC星级与已审成长候选不匹配")
        base = _zero_base(pet.get("level"), species, dim, talent)
        return [_natured(pet, dim, base, growth["effort"][dim], up, down, stars)]

    key = STAT_KEYS[dim]
    row = ((pet.get("talentEvidence") or {}).get("dimensions") or {}).get(key) or {}
    displayed = row.get("talent_add_value")
    if type(displayed) is int and 0 <= displayed <= 10 and displayed != talent:
        return []
    raw = row.get("talent")
    if raw is not None and (type(raw) is not int or raw < 0):
        raise ValueError("下发原始资质不在已支持范围；不能按星级猜测换算")
    if stars == 0 and raw is not None and displayed is None and raw != talent:
        return []
    base, effort = row.get("base_value"), row.get("effort_add")
    if _number(base) and _number(effort, zero=True):
        if stars == 0 and raw is None and displayed is None:
            if _zero_base(pet.get("level"), species, dim, talent) != base:
                return []
        return [_natured(pet, dim, base, effort, up, down, stars)]

    initial = (pet.get("initialStats") or pet.get("stats") or {}).get(key)
    if _number(initial):
        if _number(effort, zero=True):
            if initial <= effort:
                raise ValueError("基础总面板不高于下发成长加成")
            return [_natured(pet, dim, initial - effort, effort, up, down, stars)]
        if stars == 0:
            if raw is None and _zero_base(pet.get("level"), species, dim, talent) != initial:
                return []
            return [_natured(pet, dim, initial, 0, up, down, stars)]
        from .live_battle import nature_adjusted_stat
        direction = "up" if dim == up else "down" if dim == down else None
        return [nature_adjusted_stat(pet.get("level") or 60, key, initial, direction, stars=stars)]

    if stars == 0:
        base = _zero_base(pet.get("level"), species, dim, talent if raw is None else raw)
        return [_natured(pet, dim, base, 0, up, down, stars)]
    if pet.get("level") == 60 and raw is not None and _number(effort, zero=True):
        offset = 100 if dim == "hp" else 50
        cores = captured_stat60(species, raw, 1, dim)["stat_values"]
        return sorted({_natured(pet, dim, value - offset, effort, up, down, stars) for value in cores})
    raise ValueError("大世界正星成长/资质换算尚未核实，缺少下发原始资质及成长加成或基础面板")
