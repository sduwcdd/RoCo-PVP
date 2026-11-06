"""Reproducible lexical mechanism inventory, deliberately NOT a rule parser.

Hits are review candidates, including negation, quoted history and conditions.
They neither prove a complete parse nor predict executable coverage. This module
never edits sources or emits runtime rules. The frozen legacy artifact is only
used to measure overlap with the previous whole-description compilation set.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import re


AUDIT_VERSION = "mechanism-lexical-inventory-1"

# key, category, source-pattern, legacy component boundary, prerequisite groups
MECHANISMS = [
    ("damage", "effect", r"造成(?:物|魔)伤|造成(?:物理|魔法)伤害|伤害", "experimental", ["numeric_expression", "target_selector"]),
    ("healing", "effect", r"回复[^。；]*生命|生命[^。；]*回复|治疗|吸血", "experimental", ["numeric_expression", "target_selector"]),
    ("energy_restore", "effect", r"回复[^。；]*能量", "experimental", ["numeric_expression", "target_selector"]),
    ("energy_reduce", "effect", r"失去[^。；]*能量|扣除[^。；]*能量", "experimental", ["numeric_expression", "target_selector"]),
    ("energy_transfer", "effect", r"偷取[^。；]*能量|吸取[^。；]*能量", "missing", ["numeric_expression", "target_selector"]),
    ("stat_change", "effect", r"物攻|魔攻|物防|魔防|双攻|双防|攻防|速度", "experimental", ["numeric_expression", "target_selector"]),
    ("status", "effect", r"中毒|灼烧|冻结|寄生|禁足", "partial", ["target_selector", "duration", "event_dispatch"]),
    ("dispel", "effect", r"驱散|清除[^。；]*(?:增益|减益|状态)|解除[^。；]*(?:增益|减益|状态)", "missing", ["modifier_lifecycle", "target_selector"]),
    ("mark", "effect", r"印记", "partial", ["event_dispatch", "modifier_lifecycle", "target_selector"]),
    ("shield_defense", "effect", r"减伤|护盾|抵挡|免伤|伤害减免", "partial", ["modifier_lifecycle", "event_dispatch"]),
    ("target_self", "target", r"自己|自身|己方", "experimental", ["target_selector"]),
    ("target_opponent", "target", r"敌方|对手|对方", "experimental", ["target_selector"]),
    ("target_team", "target", r"队伍|全队|所有精灵|后备|替补", "missing", ["target_selector"]),
    ("target_slot", "target", r"槽位|位置|相邻|左侧|右侧|左右|第[一二三四1234]个|[1-6]号位|携带的", "partial", ["target_selector"]),
    ("target_random", "target", r"随机|任意", "missing", ["target_selector", "seeded_randomness"]),
    ("condition_explicit", "condition", r"若|如果|当|否则|每有|越[^。；]*越", "partial", ["predicate"]),
    ("condition_energy", "condition", r"能量(?:等于|小于|大于|不超过|为|耗尽)|每有[^。；]*能量", "partial", ["predicate", "numeric_expression"]),
    ("condition_health", "condition", r"生命(?:值)?(?:等于|小于|大于|低于|高于|不超过|为)|满生命|满血|残血", "missing", ["predicate", "numeric_expression"]),
    ("condition_history", "condition", r"上回合|本回合|曾经|此前|已经|上次|上一|累计", "missing", ["predicate", "battle_history"]),
    ("condition_first", "condition", r"先手(?!度|[+-])|先出手|先于", "missing", ["predicate", "action_order"]),
    ("condition_last", "condition", r"后手|后出手|后于", "missing", ["predicate", "action_order"]),
    ("response_success", "condition", r"应对(?:攻击|状态|防御)|应对成功", "partial", ["predicate", "action_order"]),
    ("trigger_entry", "trigger", r"入场|登场", "partial", ["event_dispatch", "switch_lifecycle"]),
    ("trigger_exit", "trigger", r"离场|下场", "partial", ["event_dispatch", "switch_lifecycle"]),
    ("trigger_turn_start", "trigger", r"回合开始|回合初", "missing", ["event_dispatch"]),
    ("trigger_turn_end", "trigger", r"回合结束|回合末", "partial", ["event_dispatch"]),
    ("trigger_attack", "trigger", r"攻击时|攻击后|使用[^。；]*技能后|释放[^。；]*后|命中后|造成[^。；]*后", "missing", ["event_dispatch"]),
    ("trigger_receive", "trigger", r"受到|受击|被攻击", "missing", ["event_dispatch"]),
    ("trigger_exhaustion", "trigger", r"力竭|击败|致命|复活|倒下", "missing", ["event_dispatch", "replacement_lifecycle"]),
    ("priority", "modifier", r"先手度|先手(?=[+-])", "partial", ["numeric_expression", "action_order"]),
    ("power_modifier", "modifier", r"威力", "partial", ["numeric_expression", "modifier_lifecycle"]),
    ("cost_modifier", "modifier", r"能耗|消耗[^。；]*能量|能量消耗", "missing", ["numeric_expression", "modifier_lifecycle"]),
    ("hit_count_modifier", "modifier", r"连击数|连击次数", "missing", ["numeric_expression", "modifier_lifecycle"]),
    ("type_relation", "modifier", r"克制|抵抗|本系|血脉|混血|系别|(?:草|火|水|光|地|冰|龙|电|毒|虫|武|翼|萌|幽|恶|机械|幻|普通)系", "partial", ["predicate", "modifier_lifecycle"]),
    ("duration_turns", "duration", r"持续|本回合|下回合|下[一二三四1234]回合|[1-9][0-9]*回合", "missing", ["event_dispatch", "modifier_lifecycle"]),
    ("duration_permanent", "duration", r"永久|整场|本场", "missing", ["modifier_lifecycle"]),
    ("cooldown", "cooldown", r"冷却", "partial", ["event_dispatch", "execution_limits"]),
    ("execution_limit", "restriction", r"仅限|只能|最多|不可|无法|不能|每回合.{0,8}次|每场.{0,8}次|免疫", "partial", ["execution_limits"]),
    ("swift", "special", r"迅捷", "partial", ["event_dispatch", "switch_lifecycle", "target_selector"]),
    ("charge", "special", r"蓄力", "partial", ["event_dispatch", "execution_limits"]),
    ("multihit", "special", r"连击|每次命中|每段", "partial", ["event_dispatch", "numeric_expression"]),
    ("switching", "special", r"脱离|返场|救场|更换精灵|替换入场|离场|下场", "partial", ["switch_lifecycle", "event_dispatch"]),
    ("copy_transform", "special", r"复制|借用|变成|替换[^。；]*技能|随机[^。；]*技能|重复释放", "missing", ["rule_reference", "event_dispatch", "execution_limits"]),
    ("field_weather", "special", r"天气|场地|雨天|沙尘|沙暴|暴风雪|晴天|雪天|暴雨", "missing", ["event_dispatch", "modifier_lifecycle"]),
    ("evolution", "special", r"进化|形态|萌化|首领", "missing", ["form_change", "event_dispatch"]),
    ("team_magic", "special", r"魔力|愿力|奉献", "missing", ["team_resource", "numeric_expression"]),
    ("randomness", "special", r"随机|概率|几率", "missing", ["seeded_randomness"]),
    ("stack_count", "special", r"层|叠加|叠层", "partial", ["modifier_lifecycle", "numeric_expression"]),
    ("burst", "special", r"迸发", "missing", ["predicate", "skill_usage_history"]),
    ("interrupt", "special", r"打断", "missing", ["event_dispatch", "action_order"]),
    ("relay", "special", r"传动", "missing", ["target_selector", "event_dispatch"]),
    ("choice", "special", r"选择", "missing", ["explicit_choice", "predicate"]),
    ("type_transform", "special", r"巧变|改变[^。；]*系别", "missing", ["form_change", "modifier_lifecycle"]),
    ("named_special_state", "special", r"雷鸣|引电|木桶状态|月陨星状态|透射", "missing", ["event_dispatch", "modifier_lifecycle"]),
]


def _hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _zh(value):
    return value.get("zh") if isinstance(value, dict) else value


def _values(value):
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, list):
        return value
    raise ValueError("Record collection must be an object or array")


def _text_leaves(value, path):
    """Keep table labels separate: concatenation could invent a source clause."""
    if isinstance(value, str):
        return [{"field": path, "text": value}]
    if isinstance(value, dict):
        return [part for key in sorted(value) for part in _text_leaves(value[key], path + "/" + key)]
    if isinstance(value, list):
        return [part for i, child in enumerate(value) for part in _text_leaves(child, path + "/" + str(i))]
    return []


def _spans(pattern, fragments):
    return [{"field": fragment["field"], "start": m.start(), "end": m.end(), "text": m.group()}
            for fragment in fragments for m in re.finditer(pattern, fragment["text"])]


def inventory_record(record):
    """Record exact matched spans without deleting or interpreting other text."""
    if not isinstance(record, dict) or type(record.get("id")) is not int or record["id"] <= 0:
        raise ValueError("A unique positive integer game ID is required")
    text = _zh(record.get("desc"))
    if not isinstance(text, str):
        raise ValueError("Missing source description; cannot inventory an empty substitute")
    fragments = [{"field": "desc.zh", "text": text}]
    for field in ("effect_details", "desc_notes"):
        if field in record:
            fragments.extend(_text_leaves(record[field], field))
    matches = []
    for key, category, pattern, state, dependencies in MECHANISMS:
        spans = _spans(pattern, fragments)
        if spans:
            matches.append({"mechanism": key, "category": category, "spans": spans,
                            "classification": "lexical_review_candidate", "baseline_component_state": state,
                            "dependencies": list(dependencies)})
    return {"game_id": record["id"], "name": _zh(record.get("name")), "source_description": text,
            "source_text_fragments": fragments,
            "source_details": {k: deepcopy(record[k]) for k in ("desc_notes", "effect_details") if k in record},
            "record_sha256": _hash(record), "source_url": record.get("source_url"),
            "source_module": record.get("source_module"), "matches": matches,
            "unparsed_source_preserved": True, "description_completely_parsed_by_inventory": False}


def audit_catalog(catalog, baseline):
    if not isinstance(catalog, dict) or not catalog.get("snapshot_id"):
        raise ValueError("Snapshot ID required")
    if not isinstance(baseline, dict) or baseline.get("snapshot_id") != catalog["snapshot_id"]:
        raise ValueError("Baseline artifact and snapshot must match")
    records = []
    terms = catalog.get("glossary", [])
    if (not isinstance(terms, list) or any(not isinstance(t, dict) or type(t.get("key")) is not int
                                         or not isinstance(t.get("zh"), str) or not t["zh"] for t in terms)
            or len({t["key"] for t in terms}) != len(terms)):
        raise ValueError("Term names and unique integer IDs required")
    for collection, category, artifact_key in (("moves", "skill", "skills"), ("traits", "trait", "traits")):
        seen = set()
        for raw in sorted(_values(catalog.get(collection)), key=lambda r: r["id"]):
            row = inventory_record(raw)
            key = str(row["game_id"])
            if key in seen:
                raise ValueError("Duplicate game ID in " + collection + ": " + key)
            seen.add(key)
            old = baseline.get(artifact_key, {}).get(key)
            if not isinstance(old, dict) or old.get("source_hash") != row["record_sha256"]:
                raise ValueError("Baseline missing or stale source: " + category + ":" + key)
            row.update(category=category, snapshot_id=catalog["snapshot_id"],
                       source_evidence=deepcopy(catalog.get("provenance", {}).get(raw.get("source_module"))),
                       baseline_description_structured=old.get("status") == "compiled")
            row["term_mentions"] = []
            for term in terms:
                spans = _spans(re.escape(term["zh"]), row["source_text_fragments"])
                declared_note = term["key"] in raw.get("desc_notes", []) if isinstance(raw.get("desc_notes"), list) else False
                if spans or declared_note:
                    row["term_mentions"].append({"term_id": term["key"], "name": term["zh"], "spans": spans,
                                                 "declared_desc_note": declared_note,
                                                 "meaning_resolved": False})
            records.append(row)
    stats = []
    for key, category, pattern, state, dependencies in MECHANISMS:
        rows = [r for r in records if any(m["mechanism"] == key for m in r["matches"])]
        ids = {kind: [r["game_id"] for r in rows if r["category"] == kind] for kind in ("skill", "trait")}
        missing_ids = {kind: [r["game_id"] for r in rows if r["category"] == kind and not r["baseline_description_structured"]]
                       for kind in ("skill", "trait")}
        stats.append({"mechanism": key, "category": category, "pattern": pattern,
                      "baseline_component_state": state, "dependencies": list(dependencies),
                      "candidate_ids": ids, "candidate_counts": {k: len(v) for k, v in ids.items()},
                      "baseline_unstructured_candidate_ids": missing_ids,
                      "baseline_unstructured_candidate_counts": {k: len(v) for k, v in missing_ids.items()},
                      "exclusive_unlock_count": None,
                      "exclusive_unlock_reason": "Lexical matches cannot prove that this is a record's only missing mechanism."})
    overlap = Counter()
    for row in records:
        keys = sorted(m["mechanism"] for m in row["matches"])
        for i, a in enumerate(keys):
            for b in keys[i+1:]:
                overlap[(a, b)] += 1
    # A union per prerequisite group avoids double-counting records containing
    # both an effect and its condition. These are review-benefit estimates only.
    dependency_stats = []
    for dependency in sorted({d for item in MECHANISMS for d in item[4]}):
        rows = [r for r in records if not r["baseline_description_structured"]
                and any(dependency in m["dependencies"] for m in r["matches"])]
        dependency_stats.append({"foundation": dependency,
                                 "unstructured_candidate_ids": {kind: [r["game_id"] for r in rows if r["category"] == kind]
                                                                for kind in ("skill", "trait")},
                                 "unstructured_candidate_count": len(rows)})
    dependency_stats.sort(key=lambda x: (-x["unstructured_candidate_count"], x["foundation"]))
    term_stats = []
    for term in sorted(terms, key=lambda t: t["key"]):
        ids = {kind: [r["game_id"] for r in records if r["category"] == kind
                      and any(m["term_id"] == term["key"] for m in r["term_mentions"])] for kind in ("skill", "trait")}
        term_stats.append({"term": deepcopy(term), "source": deepcopy(catalog.get("provenance", {}).get("Terms")),
                           "candidate_ids": ids, "candidate_counts": {kind: len(values) for kind, values in ids.items()},
                           "classification": "Lexical mention or declared note; invocation and timing not inferred"})
    return {"audit_version": AUDIT_VERSION, "snapshot_id": catalog["snapshot_id"],
            "catalog_content_sha256": _hash(catalog), "baseline_compiler": baseline.get("compiler_version"),
            "scope": "Complete skill/trait record inventory; conservative lexical candidates, NOT complete rule parsing or executable coverage",
            "counting": "Unique game IDs per category; overlapping mechanisms MUST NOT be summed as skill coverage",
            "total": {kind: sum(r["category"] == kind for r in records) for kind in ("skill", "trait")},
            "baseline_structured": {kind: sum(r["category"] == kind and r["baseline_description_structured"] for r in records)
                                    for kind in ("skill", "trait")},
            "unmatched_ids": {kind: [r["game_id"] for r in records if r["category"] == kind and not r["matches"]]
                              for kind in ("skill", "trait")},
            "mechanisms": stats, "terms": term_stats, "foundation_candidate_reach": dependency_stats,
            "overlap": [{"a": a, "b": b, "records": n} for (a, b), n in sorted(overlap.items())],
            "records": records, "full_battle_executable": False, "real_game_calibrated": False}


def markdown_report(report):
    lines = ["# BWIKI 机制候选审计", "", f"快照：`{report['snapshot_id']}`；对照：`{report['baseline_compiler']}`。",
             "", f"完整扫描 {report['total']['skill']} 个技能和 {report['total']['trait']} 个特性。",
             "词法命中仅用于安排人工审查与组件开发，不是完整解析、可执行覆盖或新增技能数量；否定句、历史引用和条件中的提及同样会命中。主描述、effect_details 和文字备注按独立字段扫描，表格标签不会拼接成虚构语句；未匹配的文字从未删除。",
             "", "## 按机制的候选收益", "", "技能／特性分别去重；机制之间有重叠，不可直接求和。‘未结构化’仅指旧编译器未完整表达该描述，不表示只缺本项机制。单机制独占解锁数量无法从词法扫描可靠确定，JSON 中明确为 null。",
             "", "| 机制 | 维度 | 技能候选 | 其中未结构化 | 特性候选 | 旧组件边界 |", "|---|---|---:|---:|---:|---|"]
    for row in sorted(report["mechanisms"], key=lambda r: (-r["baseline_unstructured_candidate_counts"]["skill"], r["mechanism"])):
        lines.append(f"| {row['mechanism']} | {row['category']} | {row['candidate_counts']['skill']} | {row['baseline_unstructured_candidate_counts']['skill']} | {row['candidate_counts']['trait']} | {row['baseline_component_state']} |")
    lines += ["", "旧组件边界：experimental=已有显式隔离实验操作；partial=有部分片段或资格检查；missing=旧框架没有通用执行组件。任何一项都不代表完整对战可执行。", "", "## 实现顺序", "",
              "1. 统一来源绑定的结构化配置、目标/数值/条件 AST 和静态校验；将现有操作迁移为数据，先保证旧行为等价。",
              "2. 统一事件调度、执行预算和来源链；先手度、应对成功、先/后手条件和入场事件分别建模。其覆盖收益跨技能和特性，不按单条技能增加分支。",
              "3. 修正项生命周期（持续、叠层、驱散、冷却）及选择器，之后批量表达状态/印记、能耗/威力/连击数修正。",
              "4. 历史条件与回合事件、入离场生命周期，再处理力竭替换、复制与形态等专用机制。",
              "数值公式、取整、低能量边界及未知事件顺序作为版本政策/显式实验配置，缺少这些政策就返回组件路径上的阻断原因。", "", "## 基础组件触达（未结构化记录并集）", "",
              "以下是依赖标注对应的审查候选并集，不是实现该组件便能立刻执行的记录数。", ""]
    for row in report["foundation_candidate_reach"]:
        ids = row["unstructured_candidate_ids"]
        lines.append(f"- `{row['foundation']}`：{len(ids['skill'])} 技能、{len(ids['trait'])} 特性。")
    lines += ["", f"另逐项审计 {len(report['terms'])} 个 BWIKI 命名术语，以正文提及或 desc_notes 引用分别留证。术语文本匹配不等于该记录调用了该机制；例如引用先前迅捷技能不会自动取得迅捷。", "", "JSON 保留全部原文、原始备注、来源模块/网址/哈希、命中字符区间、机制候选 ID 和两两重叠计数。未命中的记录也保留，不冒充无机制或合法配置。", ""]
    return "\n".join(lines)
