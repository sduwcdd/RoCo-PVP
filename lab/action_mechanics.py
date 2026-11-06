"""Source-bound action candidate metadata, never a server battle evaluator.

Descriptions stay whole in ``raw``. Recognising a candidate-pool clause does not
compile, discard, or claim to execute the other clauses of that description.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
GAME_EVIDENCE = ROOT / "artifacts/action_mechanics_20261025/random_skill_pools.json"
CLEVER_TERM = "使用后会变为指定范围内的随机技能，且能耗-1。使用该随机技能后会变回原技能。"
GENERATORS = {
    7020840: ("borrow", "other_allies_carried", 0, "每回合随机变成己方队伍中其他精灵的技能。"),
    7020850: ("mind_read", "opponent_original_carried", -2, "每回合随机变成敌方任意精灵的技能，且该技能能耗-2。"),
    7020860: ("rewrite", "self_learnset_minus_carried", -2, "每回合随机变成自己未携带的技能，且该技能能耗-2。"),
}
# Full reviewed descriptions: edits and added clauses require review again.
CLEVER = {
    7021220: ("造成魔法伤害，巧变：魔攻技能。", "魔攻技能", None, {"magical"}),
    7040680: ("驱散自己所有印记，每驱散1层，获得物攻+50%。巧变：火系攻击技能。", "火系攻击技能", "火系", {"physical", "magical"}),
    7050510: ("驱散自己的减益，自己每有1层减益，本技能能耗-1，巧变：水系攻击技能。", "水系攻击技能", "水系", {"physical", "magical"}),
    7070290: ("使己方队伍中的所有精灵携带的技能跨精灵向下移动1个位置，巧变：机械系技能。", "机械系技能", "机械系", None),
    7090440: ("造成魔伤，敌方获得1层冻结，应对状态：额外获得4层冻结，巧变：冻结相关技能。", "冻结相关技能", None, None),
    7100320: ("减伤90%，应对攻击。巧变：龙系状态技能。", "龙系状态技能", "龙系", {"status"}),
    7120300: ("减伤70%，巧变：毒系状态技能，应对攻击。", "毒系状态技能", "毒系", {"status"}),
    7150380: ("造成魔伤，3连击。巧变：翼系防御技能。", "翼系防御技能", "翼系", {"defense"}),
    7180430: ("造成魔伤，巧变：吸血相关技能。", "吸血相关技能", None, None),
    7180440: ("自己的生命比例变为与敌方生命比例相同，巧变：恶系攻击技能。", "恶系攻击技能", "恶系", {"physical", "magical"}),
    7190430: ("自己获得随机16层属性增益，巧变：幻系攻击技能。", "幻系攻击技能", "幻系", {"physical", "magical"}),
}
REPLACEMENTS = {
    7060150: ("减伤70%，应对攻击：本技能变为被应对的技能。", "self_slot", "attack", False),
    7060260: ("造成物伤，选择：敌方携带光系技能时威力+50或应对状态时被应对的技能变为透射。", "opponent_slot", "status", True),
}
WEATHER_NAMES = {"雨天": "rain", "沙暴": "sandstorm", "暴风雪": "blizzard", "雷鸣": "thunder"}


def _zh(value):
    return value.get("zh") if isinstance(value, dict) else value


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _records(catalog):
    moves = catalog.get("moves", {})
    rows = moves.values() if isinstance(moves, dict) else moves
    return {str(row["id"]): row for row in rows
            if isinstance(row, dict) and type(row.get("id")) is int and row["id"] > 0}


def _evidence():
    if not GAME_EVIDENCE.is_file():
        return None
    raw = GAME_EVIDENCE.read_bytes()
    if len(raw) > 1024 * 1024:
        raise ValueError("Action mechanics evidence exceeds the bounded size")
    data = json.loads(raw)
    if data.get("schema_version") != "action-mechanics-game-evidence-1":
        raise ValueError("Unknown action mechanics evidence schema")
    return data, {"path": str(GAME_EVIDENCE.relative_to(ROOT)).replace("\\", "/"),
                  "sha256": hashlib.sha256(raw).hexdigest()}


def _base(record, catalog):
    return {"id": record["id"], "name": _zh(record.get("name")),
            "status": "supported", "blockers": [], "uncertainty": [],
            "snapshot_id": catalog.get("snapshot_id"),
            "source_version": catalog.get("source_version"),
            "source": {key: deepcopy(record[key]) for key in
                       ("source_url", "source_module", "wiki_id") if key in record},
            "source_hash": _sha(record), "raw": deepcopy(record),
            "server_semantics_verified": False, "automatic_resolution": False}


def _block(row, message):
    row["status"] = "blocked"
    row["blockers"].append(message)


def build_action_mechanics(catalog):
    """Return JSON-safe generators, transformations and weather keyed by skill ID.

    ``supported`` means suitable for a manually confirmed action record, not an
    executable whole-skill implementation. General clever pools are explicitly
    current-catalog candidates. Special semantic pools expose explicitly labelled
    historical candidates for observation, if saved extraction evidence exists.
    """
    moves = _records(catalog)
    result = {"schema_version": "action-mechanics-1", "snapshot_id": catalog.get("snapshot_id"),
              "source_version": catalog.get("source_version"), "generators": {},
              "transformations": {}, "weather": {}, "response_energy": {}, "server_semantics_verified": False,
              "uncertainty": ["记录与候选池元数据；不代表完整技能或服务器回合结算。"],
              "source": {"url": catalog.get("source"), "provenance": deepcopy(catalog.get("provenance", {}))}}
    game = _evidence()
    if game:
        result["game_evidence"] = game[1]
    glossary = {t.get("key"): t for t in catalog.get("glossary", []) if isinstance(t, dict)}
    clever_term = glossary.get(3011)
    for sid, (kind, scope, delta, description) in GENERATORS.items():
        record = moves.get(str(sid))
        if not record:
            continue
        row = _base(record, catalog)
        row.update(kind=kind, scope=scope, energy_delta=delta, trigger={"event": "each_round"},
                   interpretation_source="user_requirement", pool_ids=[])
        row["uncertainty"].append("候选池按用户明确规则取本局携带槽或学习池；每回合变化的服务器精确时点未校准。")
        if _zh(record.get("desc")) != description:
            _block(row, "生成技能的完整描述已变化，需要重新核对。")
        result["generators"][str(sid)] = row

    for sid, record in moves.items():
        description = _zh(record.get("desc")) or ""
        if "巧变" in description:
            row = _base(record, catalog)
            row.update(kind="clever_change", scope="catalog_filtered", pool_ids=[],
                       trigger={"event": "after_use"}, temporary_return=True, energy_delta=-1,
                       return_trigger={"event": "after_generated_skill_use"},
                       other_effects="retained_in_raw_not_resolved")
            row["term"] = deepcopy(clever_term)
            spec = CLEVER.get(record["id"])
            if not clever_term or clever_term.get("definition") != CLEVER_TERM:
                _block(row, "巧变术语3011缺失或定义改变，无法确认临时变化与返回规则。")
            if not spec or description != spec[0]:
                _block(row, "未审阅的巧变完整描述，不能推测范围或忽略额外句子。")
            elif spec[2] is None and spec[3] is None:
                row["pool_label"] = spec[1]
                row["pool_basis"] = "unavailable_current_special_pool"
                row["uncertainty"].append("当前提取的SKILLFULLY_EXCHANGE_CONF _3_P仅有id，缺skillid；无法确认当前相关技能完整池。")
                if game:
                    pool_key = "21" if record["id"] == 7090440 else "24"
                    historical = game[0]["versions"][1]
                    raw_pool = historical["rows"].get(pool_key, {})
                    row["historical_pool_ids"] = [i for i in raw_pool.get("skillid", []) if str(i) in moves]
                    if row["status"] == "supported":
                        row["pool_ids"] = list(row["historical_pool_ids"])
                        row["pool_authority"] = "historical_game_file_candidates"
                    row["historical_pool"] = {"table": "SKILLFULLY_EXCHANGE_CONF", "pool_id": int(pool_key),
                                              "schema_pak": historical["schema_pak"], "binary_pak": historical["binary_pak"],
                                              "raw": deepcopy(raw_pool), "source": deepcopy(game[1])}
                if not row["pool_ids"] and row["status"] == "supported":
                    _block(row, "缺少可追溯的相关技能池候选；不能以全部技能代替。")
                row["uncertainty"].append("历史_2_P精确表项只能作为历史候选参考，不能冒充当前完整池。")
            else:
                _, label, type_name, kinds = spec
                row.update(pool_label=label, pool_basis="catalog_metadata_candidates",
                           pool_authority="catalog_metadata_candidates",
                           pool_filter={"type": type_name, "kinds": sorted(kinds) if kinds else None})
                if row["status"] == "supported":
                    row["pool_ids"] = sorted(r["id"] for r in moves.values()
                                             if (type_name is None or r.get("type") == type_name)
                                             and (kinds is None or r.get("kind") in kinds))
                if not row["pool_ids"] and row["status"] == "supported":
                    _block(row, "当前目录中没有满足已确认系别/类别的候选。")
                row["uncertainty"].append("按当前目录系别/类别筛出的候选；未证明等于当前包或服务器精确巧变池。")
            result["transformations"][sid] = row

        if record["id"] in REPLACEMENTS:
            expected, scope, response_kind, choice = REPLACEMENTS[record["id"]]
            row = _base(record, catalog)
            row.update(kind="slot_replace", scope=scope, pool_ids=[],
                       trigger={"event": "response_success", "response_kind": response_kind, "choice_required": choice},
                       temporary_return=False, permanence="not_explicitly_stated",
                       record_policy="update_battle_slot_only_after_confirmed_response",
                       replacement_source="opponent_selected_skill" if not choice else "named_skill")
            if description != expected:
                _block(row, "替换技能的完整描述变化，不能从应对关键词推测替换。")
            if choice:
                targets = [m["id"] for m in moves.values() if _zh(m.get("name")) == "透射"]
                if len(targets) == 1:
                    row["replacement_id"] = targets[0]
                    row["pool_ids"] = targets
                else:
                    _block(row, "命名目标透射缺失或名称不唯一，无法定位替换技能。")
            if game:
                row["slot_update_source"] = deepcopy(game[0]["slot_update"])
            row["uncertainty"].append("描述未明说永久时长；客户端确认收到替换数据后直接更新本局技能槽，不足以推断服务器时序或持续性。")
            result["transformations"][sid] = row

        if "将天气改为" in description:
            row = _base(record, catalog)
            row.update(kind=None, duration=None, trigger={"event": "observed_weather_set"})
            match = re.fullmatch(r"将天气改为(雨天|沙暴|暴风雪|雷鸣)，持续([1-9][0-9]*)回合。", description)
            if match:
                row.update(kind=WEATHER_NAMES[match[1]], label=match[1], duration=int(match[2]))
            else:
                _block(row, "天气完整描述未匹配；不能丢弃条件或臆测天气时长。")
            row["uncertainty"].append("仅记录已观察天气及原文回合数；不声明天气伤害、减耗、回合边界或刷新结算。")
            result["weather"][sid] = row

    # Reuse reviewed executable components; never infer an energy effect from prose here.
    from lab.mechanism_runtime import programs
    from lab.prepared_rules import PreparedRules
    reviewed = programs(PreparedRules(catalog)) if (catalog.get("types") and catalog.get("forms")
        and catalog.get("chart_schema") == "defender_type_combination_to_attacker_weak_resist; explicit double-type multiplier") else {}
    for sid, program in reviewed.items():
        effects = [deepcopy(component) for component in program.get("mechanism_components", [])
                   if component.get("when") == "response.success"
                   and component.get("op") in {"energy.reduce", "energy.restore", "energy.transfer"}]
        if effects:
            evidence = program["mechanism_evidence"]
            result["response_energy"][str(sid)] = {
                "skill_id": sid, "name": _zh(moves[str(sid)].get("name")),
                "response_kinds": deepcopy(program.get("response_kinds", [])),
                "effects": effects, "record_hash": evidence["record_hash"],
                "source": deepcopy(evidence.get("source", evidence.get("evidence", {}))),
                "policy": program["mechanism_policy"],
            }
    return result
