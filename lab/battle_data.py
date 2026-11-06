"""对局中「显示层」需要的数据查询：形态名、特性文本、愿力冲击。

公开数值与文本优先读取进程固定的 BWIKI 快照。解包数据保留为历史证据，
为快照未收录的 ID 提供标记过来源的兼容查询，并保留已校对的效果关联。

三条已核实的规则（证据见 docs/RKPP_LIVE.md）：

1. 报文里的 ``conf_name`` 是基础名（迪莫），真正形态要看 ``base_conf_id``
   （5026 → 圣草迪莫）。所以 HUD 不能只信 ``conf_name``。
2. 迪莫四形态各带一条特性，特性描述里明确写了「首个技能替换为X系愿力冲击」：

   ========  ======  ==================
   形态      特性    替换结果
   ========  ======  ==================
   5025 圣光  280025  光系愿力冲击
   5026 圣草  280026  草系愿力冲击
   5027 圣火  280027  火系愿力冲击
   5028 圣水  280028  水系愿力冲击
   ========  ======  ==================

   触发条件是「造成克制伤害后」，所以开局不该替换 —— 这是游戏文本的原文，不是推断。

3. 愿力冲击按属性有 18 个 id（7700001..7700019），靠 ``skill_dam_type`` 区分；
   ``7700006`` 在数据里标注「愿力冲击（废弃）」，必须跳过。
"""
from __future__ import annotations

import json
import re
from hashlib import sha256
from functools import lru_cache
from pathlib import Path
from typing import Any

from .catalog_store import runtime_catalog

_ROOT = Path(__file__).resolve().parent.parent
_EXTERNAL = _ROOT / "data" / "external"
_SPECIALITY_TABLE = _ROOT / "artifacts/pet_talent_probe_20261106/PET_TALENT_CONF.json"
_SPECIALITY_TABLE_HASH = "40875307c7d78e140a8d634c7001f8800aef55c91bd9e5b0a3c20d438a207f3e"
_PHYSICAL_EVIDENCE = _ROOT / "artifacts/pet_physical_probe_20261106/findings.json"


def _physical_integer(value):
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r"-?\d{1,20}", value):
        return int(value)
    return None


def physical_info(base_conf_id, *, height=None, weight=None, voice=None, worn_medal_id=None):
    """Client unit formatting; medal conditions are predictions, not award receipts.

    Source: pet_physical_probe_20261106/findings.json. Voice is an RTPC pitch
    parameter, not Hz/dB. Exact server 2% boundary comparisons remain unknown.
    """
    result = {"medals": []}
    height, weight, voice = map(_physical_integer, (height, weight, voice))
    if height is not None and height > 0:
        result["height"] = {"raw": height, "text": f"{height * 0.01:.2f}米"}
    if weight is not None and weight > 0:
        result["weight"] = {"raw": weight, "text": f"{weight * 0.001:.2f}千克"}
    if voice is not None:
        if 2**63 <= voice < 2**64:
            voice -= 2**64
        elif 2**31 <= voice < 2**32:
            voice -= 2**32
        if -(2**31) <= voice < 2**31:
            result["voice"] = {"value": voice, "text": f"{voice:+d}" if voice else "0"}
        else:
            voice = None
    medals = {1001: ("height", "大块头"), 1002: ("height", "小不点"),
              1025: ("voice", "粗嗓门"), 1026: ("voice", "婉转声")}
    worn = medals.get(_physical_integer(worn_medal_id))
    if worn:
        result["medals"].append({"id": _physical_integer(worn_medal_id), "attribute": worn[0],
                                 "name": worn[1], "status": "confirmed"})
    try:
        base = _pet_record(str(int(base_conf_id)))
    except (ValueError, TypeError):
        base = {}
    ranges = (("height", height, _physical_integer(base.get("height_low")),
               _physical_integer(base.get("height_high")), 1002, 1001),
              ("voice", voice, -100, 100, 1025, 1026))
    for attribute, value, low, high, low_id, high_id in ranges:
        if worn and worn[0] == attribute:
            continue
        if value is None or low is None or high is None or high <= low or not low <= value <= high:
            continue
        position, width = 100 * (value - low), high - low
        medal_id = low_id if position <= 2 * width else high_id if position >= 98 * width else None
        if medal_id:
            result["medals"].append({"id": medal_id, "attribute": attribute, "name": medals[medal_id][1],
                "status": "boundary" if position in (2 * width, 98 * width) else "predicted",
                "basis": "已存身高范围／音调范围与奖牌范围2%描述；捕获结算前不是获得确认"})
    return result


@lru_cache(maxsize=1)
def _specialities():
    raw = _SPECIALITY_TABLE.read_bytes()
    if sha256(raw).hexdigest() != _SPECIALITY_TABLE_HASH:
        raise ValueError("Speciality definition source hash mismatch")
    return json.loads(raw)


def speciality_info(speciality_id):
    """PetData field 82 is an individual specialty; zero is not confirmed '无' (ID 1)."""
    if type(speciality_id) is not int or speciality_id <= 0:
        return {}
    info = {"id": speciality_id, "confirmed": True, "source": "PetData.speciality_id"}
    try:
        row = _specialities().get(str(speciality_id), {})
        info.update(name=(row.get("name") or {}).get("text"),
                    description=(row.get("desc") or {}).get("text"))
    except (OSError, ValueError):
        # A missing display dictionary must not stop the shared battle engine.
        info["mappingIssue"] = "特长名称来源不可用，保留报文编号"
    return info

# 属性中文名 → skill_dam_type。
# 锚点全部来自真实数据，不是猜的：
#   草=3 (7030170 荆棘爪 / 7700002 愿力冲击)
#   火=4 (7040260 引燃 / 7040430 炎打 / 7700003)
#   水=5 (7050230 蓄水 / 7700004)
#   光=6 (7060200 虹光冲击 / 7700005)
#   其余由 7700007..7700019 的 skill_dam_type 与属性名一一对上得到。
TYPE_CODES: dict[str, int] = {
    "普通": 2, "草": 3, "火": 4, "水": 5, "光": 6,
    "地": 8, "冰": 9, "龙": 10, "电": 11, "毒": 12,
    "虫": 13, "武": 14, "翼": 15, "萌": 16, "幽": 17,
    "恶": 18, "机械": 19, "幻": 20,
}

# 游戏文本/玩家口语里的别名（desc 里用「X系」，但也可能写成飞行系之类）。
TYPE_ALIASES: dict[str, str] = {
    "战斗": "武", "格斗": "武", "武斗": "武",
    "飞": "翼", "飞行": "翼",
    "可爱": "萌",
    "幽灵": "幽",
    "暗": "恶", "邪恶": "恶", "黑暗": "恶",
    "机器": "机械", "机甲": "机械",
    "幻象": "幻", "超能": "幻", "念力": "幻",
    "地面": "地", "岩": "地", "土": "地",
}

_WILL_RE = re.compile(r"首个技能替换为(.{1,4}?)系愿力冲击")
_WILL_ID_PREFIX = 7700000


_cache: dict[str, Any] = {}


def _load(name: str) -> dict[str, Any]:
    key = f"file:{name}"
    if key not in _cache:
        path = _EXTERNAL / name
        data: dict[str, Any] = {}
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                if isinstance(raw, dict):
                    data = raw
            except (OSError, ValueError):
                data = {}
        _cache[key] = data
    return _cache[key]


def _petbase() -> dict[str, Any]:
    """Historical raw evidence, kept unchanged for effect/source verification."""
    return _load("petbase.json")


def _skills() -> dict[str, Any]:
    """Historical raw evidence, kept unchanged for effect/source verification."""
    return _load("skill.json")


def _catalog_forms() -> dict[str, Any]:
    if "catalog:forms" not in _cache:
        _cache["catalog:forms"] = {
            str(row.get("id")): row for row in runtime_catalog()[0].get("forms", [])
        }
    return _cache["catalog:forms"]


def _zh(value: Any) -> str:
    return (value.get("zh") or "") if isinstance(value, dict) else (value or "")


def _pet_record(key: str) -> dict[str, Any]:
    """Project current catalog fields onto a copy of historical effect metadata."""
    historical = _petbase().get(key)
    row = dict(historical) if isinstance(historical, dict) else {}
    form = _catalog_forms().get(key)
    if form is None:
        return row
    row.update(name=_zh(form.get("name")), stage=form.get("stage"),
               pet_feature=form.get("trait_id"),
               unit_type=[type_code_of(name) for name in form.get("types") or []])
    stats = form.get("stats") or {}
    for short, field in (("hp", "hp_max_race"), ("patk", "phy_attack_race"),
                         ("matk", "spe_attack_race"), ("pdef", "phy_defence_race"),
                         ("mdef", "spe_defence_race"), ("spd", "speed_race")):
        row[field] = stats.get(short)
    return row


def type_code_of(name: str) -> int | None:
    """属性中文名（含别名）→ skill_dam_type。查不到返回 None。"""
    text = str(name or "").strip()
    if not text:
        return None
    text = text.replace("系", "")
    if text in TYPE_CODES:
        return TYPE_CODES[text]
    alias = TYPE_ALIASES.get(text)
    if alias:
        return TYPE_CODES.get(alias)
    return None


def pet_form(base_conf_id: Any) -> dict[str, Any]:
    """``base_conf_id`` → ``{name, feature_id, feature_name, feature_desc}``。

    拿到的是**形态**信息（圣草迪莫），而报文里的 ``conf_name`` 只是基础名（迪莫）。
    """
    try:
        key = str(int(base_conf_id))
    except (TypeError, ValueError):
        return {}
    cache_key = f"form:{key}"
    if cache_key in _cache:
        return _cache[cache_key]

    pet = _pet_record(key)
    out: dict[str, Any] = {}
    if pet:
        out["name"] = pet.get("name") or ""
        out["data_source"] = "BWIKI" if key in _catalog_forms() else "historical_external"
        feature_id = pet.get("pet_feature")
        if feature_id:
            out["feature_id"] = feature_id
            feature = skill_info(feature_id)
            if feature:
                out["feature_name"] = feature.get("name") or ""
                out["feature_desc"] = feature.get("desc") or ""
                out["feature_data_source"] = feature["data_source"]
    _cache[cache_key] = out
    return out


def pet_unit_types(base_conf_id: Any) -> tuple[int, ...]:
    """BWIKI 精灵属性编码，未收录的 ID 回退历史 unit_type，用于本系加成。

    实测 5026 圣草迪莫 → (6, 3) = 光 + 草，与它的愿力冲击走草系一致。
    """
    try:
        key = str(int(base_conf_id))
    except (TypeError, ValueError):
        return ()
    cache_key = f"types:{key}"
    if cache_key in _cache:
        return _cache[cache_key]
    pet = _pet_record(key)
    out: tuple[int, ...] = ()
    if isinstance(pet, dict):
        raw = pet.get("unit_type")
        codes = []
        for item in raw if isinstance(raw, list) else ([raw] if raw is not None else []):
            if isinstance(item, int) and not isinstance(item, bool):
                codes.append(item)
        out = tuple(codes)
    _cache[cache_key] = out
    return out


def pet_race_stats(base_conf_id: Any) -> dict[str, int]:
    """``base_conf_id`` → 六维种族值。

    BWIKI 已收录的形态仅使用当前 stats，未收录的 ID 回退历史 _race 字段。
    用途：对方攻击面板没下发时，用种族值 + 性格推伤害区间。
    """
    try:
        key = str(int(base_conf_id))
    except (TypeError, ValueError):
        return {}
    cache_key = f"race:{key}"
    if cache_key in _cache:
        return _cache[cache_key]
    pet = _pet_record(key)
    out: dict[str, int] = {}
    if isinstance(pet, dict):
        fields = (("hp", "hp_max_race"), ("patk", "phy_attack_race"), ("matk", "spe_attack_race"),
                  ("pdef", "phy_defence_race"), ("mdef", "spe_defence_race"), ("spd", "speed_race"))
        for short, field in fields:
            value = pet.get(field)
            if isinstance(value, (int, float)) and value > 0:
                out[short] = int(value)
    _cache[cache_key] = out
    return out


def skill_info(skill_id: Any) -> dict[str, Any]:
    """BWIKI 技能基础信息，未收录的 ID 显式标记为历史解包回退。

    已收录技能缺失或动态的威力保持未知。历史 damage_rule 仅作为已校对的
    动态效果关联保留，来源单列；原始行保持不变，以供来源哈希校验。

    ``damage_type`` 实测对应：1 变化 · 2 物理 · 3 魔法 · 4 取双攻更高
    （愿力冲击的原文就是「伤害类型取决于精灵双攻更高的一项」）。
    """
    try:
        key = str(int(skill_id))
    except (TypeError, ValueError):
        return {}
    cache_key = f"skill:{key}"
    if cache_key in _cache:
        return _cache[cache_key]
    node = _skills().get(key)
    out: dict[str, Any] = {}
    if isinstance(node, dict):
        para = node.get("dam_para") or []
        power = para[0] if para and isinstance(para[0], (int, float)) else None
        dtype = node.get("damage_type")
        kind = {1: "status", 2: "physical", 3: "magical", 4: "higher"}.get(dtype)
        cost = node.get("energy_cost") or []
        out = {
            "skill_id": int(key),
            "name": node.get("name") or "",
            "power": power,
            "type_code": node.get("skill_dam_type"),
            "energy": cost[0] if cost and isinstance(cost[0], int) else None,
            "kind": kind,
            "damage_type": dtype,
            "category": node.get("type"),
            "damage_rule": node.get("damage_rule"),
            "desc": node.get("desc") or "",
            "data_source": "historical_external",
        }
    catalog = runtime_catalog()[0]
    move = catalog.get("moves", {}).get(key)
    trait = catalog.get("traits", {}).get(key)
    record = move if move is not None else trait
    if record is not None:
        kind = record.get("kind")
        power = record.get("power")
        out = {
            "skill_id": int(key),
            "name": _zh(record.get("name")),
            "power": power if type(power) in (int, float) else None,
            "type_code": type_code_of(record.get("type")),
            "energy": record.get("energy"),
            "kind": kind,
            "damage_type": {"status": 1, "physical": 2, "magical": 3, "higher": 4}.get(kind),
            "category": 1 if move is not None else 2,
            "damage_rule": out.get("damage_rule"),
            "desc": _zh(record.get("desc")),
            "data_source": "BWIKI",
            "snapshot_id": catalog.get("snapshot_id"),
            "historical_fields": ["damage_rule"] if out.get("damage_rule") is not None else [],
        }
    _cache[cache_key] = out
    return out


@lru_cache(maxsize=1)
def _response_bases():
    effects = json.loads((_ROOT / "artifacts/unpack_probe_20261025/battle_analysis/tables/parsed/EFFECT_CONF.json").read_text(encoding="utf-8"))
    links = {}
    for raw_id, skill in _skills().items():
        if not isinstance(skill, dict) or (skill.get("name") or "").startswith("应对！"):
            continue
        for result in skill.get("skill_result") or []:
            effect = effects.get(str(result.get("effect_id"))) or {}
            params = effect.get("effect_param") or []
            if effect.get("effect_order") == 31 and params:
                for dest in params[0].get("params", []):
                    if (_skills().get(str(dest)) or {}).get("name") == "应对！" + (skill.get("name") or ""):
                        links.setdefault(dest, set()).add(int(raw_id))
    return links


def canonical_skill(skill_id: Any) -> dict[str, Any]:
    """Canonical carried move, retaining the resolved variant as evidence elsewhere."""
    info = skill_info(skill_id)
    if not info and isinstance(skill_id, int) and skill_id > 9_999_999:
        info = skill_info(skill_id // 100)
    if not info or not info["name"].startswith("应对！"):
        return info
    name = info["name"][3:]
    candidates = _response_bases().get(info["skill_id"], set())
    source = "EFFECT_CONF.order31"
    if not candidates:
        source = "unique_native_name_and_type"
        candidates = {int(k) for k, row in _skills().items() if isinstance(row, dict)
                      and row.get("name") == name and row.get("skill_dam_type") == info["type_code"]}
        if len(candidates) > 1:
            published = {sid for sid in candidates if str(sid) in runtime_catalog()[0]["moves"]}
            if len(published) == 1:
                candidates = published
                source = "native_name_type_and_published_BWIKI_id"
    if len(candidates) == 1:
        return {**skill_info(next(iter(candidates))), "resolved_variant_id": info["skill_id"],
                "canonical_source": source}
    return {**info, "name": name, "canonical_issue": "普通版技能ID不能唯一匹配", "canonical_candidates": sorted(candidates)}


def pet_stage_info(base_conf_id: Any) -> dict[str, Any]:
    """``base_conf_id`` → ``{stage, family, name}``，双方均未收录则返回 ``{}``。

    ``stage`` 优先读取 BWIKI，``family`` 是历史 ``ai_group_info_id``。
    实测：迪莫 3004 stage=1 family=3004；圣草迪莫 5026 stage=4 family=3004。
    """
    try:
        key = str(int(base_conf_id))
    except (TypeError, ValueError):
        return {}
    cache_key = f"stage:{key}"
    if cache_key in _cache:
        return _cache[cache_key]
    pet = _pet_record(key)
    out: dict[str, Any] = {}
    if pet:
        out = {
            "stage": pet.get("stage"),
            "family": str(pet.get("ai_group_info_id") or ""),
            "name": pet.get("name") or "",
            "data_source": "BWIKI" if key in _catalog_forms() else "historical_external",
            "historical_fields": ["family"] if pet.get("ai_group_info_id") else [],
        }
    _cache[cache_key] = out
    return out


# 萌化 buff：buff.json 里 id=20010791 / 21020040，名字「萌化」，
# 描述「退化到上一阶，种族资质相应降低。」—— 每 1 层退一阶。
CUTE_BUFF_IDS: tuple[str, ...] = ("20010791", "21020040")


def is_cute_buff(buff_id: Any) -> bool:
    return str(buff_id) in CUTE_BUFF_IDS


def lower_stage_form(base_conf_id: Any, steps: int = 1) -> dict[str, Any]:
    """Follow explicit reverse evolution edges, never an AI/spawn family grouping.

    The server's reported current form takes precedence; this is only a projection
    until a form acknowledgement arrives. Ambiguous predecessors are unresolved.
    """
    try:
        key = str(int(base_conf_id))
    except (TypeError, ValueError):
        return {}
    steps = max(1, int(steps or 1))
    cache_key = f"lower:{key}:{steps}"
    if cache_key in _cache:
        return _cache[cache_key]

    rows = {key: _pet_record(key) for key in _petbase().keys() | _catalog_forms().keys()}
    current = rows.get(key)
    out: dict[str, Any] = {}
    if isinstance(current, dict):
        stage = current.get("stage")
        if isinstance(stage, int):
            pid = key
            predecessors = evolution_predecessors()
            for _ in range(steps):
                parents = predecessors.get(pid, [])
                if not parents and rows[pid].get("stage") == 1:
                    break
                if len(parents) != 1:
                    _cache[cache_key] = {}
                    return {}
                pid = parents[0]
            if pid != key:
                node = rows[pid]
                best_stage = node["stage"]
                out = {
                    "base_conf_id": int(pid),
                    "name": node.get("name") or "",
                    "stage": best_stage,
                    "from_stage": stage,
                    "steps": stage - best_stage,
                    "data_source": "BWIKI" if pid in _catalog_forms() else "historical_external",
                    "historical_fields": ["evolution_predecessors"],
                    "stats": {
                        "hp": node.get("hp_max_race"),
                        "atk": node.get("phy_attack_race"),
                        "spAtk": node.get("spe_attack_race"),
                        "def": node.get("phy_defence_race"),
                        "spDef": node.get("spe_defence_race"),
                        "spd": node.get("speed_race"),
                    },
                }
    _cache[cache_key] = out
    return out


def evolution_predecessors():
    """Reverse PETBASE evolution/boss references, preferring declared playable rows."""
    if "evolution_predecessors" in _cache:
        return _cache["evolution_predecessors"]
    rows = {key: _pet_record(key) for key in _petbase().keys() | _catalog_forms().keys()}
    edges = {}
    for pid, node in rows.items():
        for child in set((node.get("evolution_pet_id") or []) + (node.get("bosspetbase_id_arry") or [])):
            target = rows.get(str(child), {})
            if isinstance(node.get("stage"), int) and node["stage"] < (target.get("stage") or 0):
                edges.setdefault(str(child), set()).add(pid)
    result = {}
    for child, parents in edges.items():
        playable = [pid for pid in parents if rows[pid].get("legal_petbase") == 1]
        result[child] = sorted(playable or parents, key=int)
    _cache["evolution_predecessors"] = result
    return result

def will_impact_type_from_feature(feature_desc: str) -> int | None:
    """从特性文本里取出「首个技能替换为X系愿力冲击」的 X 的属性编码。"""
    match = _WILL_RE.search(str(feature_desc or ""))
    if not match:
        return None
    return type_code_of(match.group(1))


def will_impact_skill(type_code: int) -> dict[str, Any]:
    """按属性编码找普通版「愿力冲击」。

    跳过 name 里带「应对！」的强化版，也跳过数据里标了「废弃」的那条。
    """
    cache_key = f"will:{type_code}"
    if cache_key in _cache:
        return _cache[cache_key]

    found: dict[str, Any] = {}
    ids = dict.fromkeys([*_skills(), *runtime_catalog()[0].get("moves", {})])
    for raw_id in ids:
        try:
            sid = int(raw_id)
        except (TypeError, ValueError):
            continue
        if sid < _WILL_ID_PREFIX or sid >= _WILL_ID_PREFIX + 100:
            continue          # 只要 77000xx 这一档（77001xx 是「应对！」版）
        info = skill_info(sid)
        name = info.get("name") or ""
        if "愿力冲击" not in name or "应对" in name or "废弃" in name:
            continue
        if info.get("type_code") != type_code:
            continue
        historical = _skills().get(raw_id) or {}
        found = {
            "skill_id": sid,
            "skillId": sid,
            "skillName": name,
            "moveName": name,
            "name": name,
            "energy_cost": info.get("energy"),
            "damage_type": info.get("type_code"),
            "skill_desc": info.get("desc") or "",
            "power": info.get("power"),
            "cd": (historical.get("cd_round") or [0])[0] if isinstance(historical.get("cd_round"), list) else historical.get("cd_round"),
            "data_source": info.get("data_source"),
            "historical_fields": ["cd"] if "cd_round" in historical else [],
            "from_feature": True,
        }
        break
    _cache[cache_key] = found
    return found
