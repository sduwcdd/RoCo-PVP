"""Fail-closed, declarative BWIKI skill programs.

``compiled`` means the entire supplied short description has a known declarative
translation. It does not prove execution timing, rounding, stat stacking, or game
fidelity. No original NRC_AI effect table is consulted. Every program remains
non-executable until its dependencies and the battle engine are calibrated.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import re


COMPILER_VERSION = "bwiki-declarative-6"
SWIFT_TERMS_SHA256 = 'a7a4ad3bc1e30e154cdbc52b9e350ec75cbca04bb39e1b9e7012fa4a220ca822'
SWIFT_TERM = {"key": 1005, "zh": "迅捷", "definition": "通过主动更换精灵的方式入场时，使用第一个能量满足要求，并带有迅捷的技能。"}
STAT_NAMES = {"物攻": "patk", "魔攻": "matk", "物防": "pdef", "魔防": "mdef", "速度": "spd"}
STATUS_NAMES = {"中毒": "poison", "灼烧": "burn", "冻结": "freeze", "寄生": "leech"}
STATUS_TERMS = {"poison": 1001, "burn": 1002, "freeze": 1004, "leech": 1008}
KINDS = {"physical", "magical", "status", "defense"}
EXECUTION_BLOCKERS = [
    "尚未通过当前版本的真实对战校准。",
    "操作顺序仅保留描述顺序，不声明回合时序、取整或叠加规则。",
]


def _zh(value):
    return value.get("zh") if isinstance(value, dict) else value


def _hash(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _positive_integer(value):
    return type(value) is int and value > 0


def _base(record, category):
    if not isinstance(record, dict):
        raise ValueError("技能或特性记录必须为对象")
    return {
        "game_id": record.get("game_id", record.get("id")),
        "name": _zh(record.get("name")), "category": category,
        "compiler_version": COMPILER_VERSION,
        "source_description": _zh(record.get("desc")),
        "source_details": {key: deepcopy(record[key]) for key in ("effect_details", "desc_notes") if key in record},
        "source_hash": _hash(record),
        "source": {key: deepcopy(record[key]) for key in ("wiki_id", "source_url", "source_module") if key in record},
        "static_fields": {key: deepcopy(record[key]) for key in ("kind", "type", "power", "energy") if key in record},
        "status": "unsupported", "operations": [], "blockers": [],
        "dependency_ids": [], "snapshot_id": None, "source_version": None,
        "order_semantics": "source_text_order_not_validated_timing",
        "executable": False, "real_game_verified": False,
        "execution_blockers": list(EXECUTION_BLOCKERS),
    }


def _operation(op, **params):
    return {"op": op, "params": params}


def _energy_condition(description):
    """Only three reviewed whole descriptions; no expression evaluation.

    ``after_use`` is retained as source wording, NOT silently translated to
    after-payment timing. Damage multiplication is distinct from adding power.
    Construct fresh nested records so callers cannot mutate future programs.
    """
    if description == "造成魔伤，使用后若能量耗尽，本次技能威力+120。":
        return ("magical",
                {"target": "self", "attribute": "energy", "comparison": "eq", "value": 0,
                 "source_timing": "after_use"},
                {"kind": "power_add", "amount": 120})
    if description == "造成物伤，若敌方能量小于等于2，造成5倍伤害。":
        return ("physical",
                {"target": "opponent", "attribute": "energy", "comparison": "lte", "value": 2,
                 "source_timing": "unspecified"},
                {"kind": "damage_multiply", "amount": 5})
    if description == "造成魔伤，若敌方能量等于0，造成20倍伤害。":
        return ("magical",
                {"target": "opponent", "attribute": "energy", "comparison": "eq", "value": 0,
                 "source_timing": "unspecified"},
                {"kind": "damage_multiply", "amount": 20})
    return None


def _effect_clause(clause):
    """One complete, unconditional clause; never discard unmatched suffixes."""
    restore = re.fullmatch(r"自己回复([1-9][0-9]*)能量", clause)
    heal = re.fullmatch(r"自己回复([1-9][0-9]*)%生命(?:和([1-9][0-9]*)能量)?", clause)
    stats = re.fullmatch(r"(自己|敌方)获得((?:物攻|魔攻|物防|魔防|速度)(?:和(?:物攻|魔攻|物防|魔防|速度))*)([+-])([1-9][0-9]*)%", clause)
    status = re.fullmatch(r"敌方获得([1-9][0-9]*)层(中毒|灼烧|冻结|寄生)", clause)
    if restore:
        return [_operation("energy.restore", target="self", amount=int(restore[1]))], []
    if heal:
        operations = [_operation("hp.restore", target="self", percent={"numerator": int(heal[1]), "denominator": 100})]
        if heal[2]:
            operations.append(_operation("energy.restore", target="self", amount=int(heal[2])))
        return operations, []
    if stats:
        attributes = [STAT_NAMES[x] for x in stats[2].split("和")]
        if len(set(attributes)) != len(attributes):
            return None
        return [_operation("stat.modify", target="self" if stats[1] == "自己" else "opponent",
                           attributes=attributes, percent={"numerator": int(stats[4]) * (1 if stats[3] == "+" else -1), "denominator": 100})], []
    if status:
        name = STATUS_NAMES[status[2]]
        return [_operation("status.add", target="opponent", status=name, stacks=int(status[1]))], [STATUS_TERMS[name]]
    return None


def _unconditional_sequence(description, skill):
    """Bounded grammar: optional leading attack, then fully matched clauses.

    A comma only separates whole supported clauses; periods, conditions,
    selectors, timing modifiers and incomplete clauses are never removed.
    The one implicit subject form is exactly the BWIKI energy-then-stat phrase.
    """
    if not description.endswith("。"):
        return None
    body = description[:-1]
    energy_stat = re.fullmatch(r"自己回复([1-9][0-9]*)能量，并获得(.+)", body)
    if energy_stat:
        stat = _effect_clause("自己获得" + energy_stat[2])
        if stat is None or any(op["op"] != "stat.modify" for op in stat[0]):
            return None
        return [_operation("energy.restore", target="self", amount=int(energy_stat[1]))] + stat[0], stat[1], "status"

    clauses = body.split("，")
    attack = re.fullmatch(r"(?:对敌方精灵)?造成(物理|魔法)伤害|造成(物|魔)伤", clauses[0])
    operations, dependencies, expected_kind = [], [], "status"
    if attack:
        expected_kind = "physical" if (attack[1] or attack[2]) in ("物理", "物") else "magical"
        if not _positive_integer(skill.get("power")):
            return None
        operations.append(_operation("damage", target="opponent", kind=expected_kind,
                                     power=skill["power"], type=skill["type"]))
        clauses = clauses[1:]
    for clause in clauses:
        parsed = _effect_clause(clause)
        if parsed is None:
            return None
        operations.extend(parsed[0])
        for dependency in parsed[1]:
            if dependency not in dependencies:
                dependencies.append(dependency)
    if not operations:
        return None
    return operations, dependencies, expected_kind


def compile_skill(skill: dict) -> dict:
    """Translate exact whole descriptions; unsupported records emit no operations.

    Explanatory text and unknown notes block compilation. A known status term is
    retained as an unresolved execution dependency, never silently implemented as
    just the visible stack count. Its immunity, cooldown and timing still require
    the versioned rule interpreter and real-game calibration.
    """
    out = _base(skill, "skill")
    blockers = out["blockers"]
    description, kind = out["source_description"], skill.get("kind")
    if not _positive_integer(out["game_id"]):
        blockers.append("invalid_game_id")
    if kind not in KINDS:
        blockers.append("unsupported_skill_kind")
    if not isinstance(description, str) or not description:
        blockers.append("missing_chinese_description")
    if type(skill.get("energy")) is not int or skill["energy"] < 0:
        blockers.append("missing_or_invalid_energy")
    if not isinstance(skill.get("type"), str) or not skill["type"]:
        blockers.append("missing_skill_type")
    if skill.get("effect_details"):
        blockers.append("unresolved_effect_details")
    if blockers:
        return out

    operations = []
    # A whole match prevents dropping appended conditionals, punctuation, or text.
    attack = re.fullmatch(r"(?:对敌方精灵造成(物理|魔法)伤害|造成(物|魔)伤)(?:，自己回复([1-9][0-9]*)能量)?。", description)
    swift_attack = re.fullmatch(r"造成(物|魔)伤，迅捷。", description)
    energy_condition = _energy_condition(description)
    fixed_hits = re.fullmatch(r"造成(物|魔)伤，([1-9][0-9]*)连击。", description)
    restore = re.fullmatch(r"自己回复([1-9][0-9]*)能量。", description)
    stats = re.fullmatch(r"(自己|敌方)获得((?:物攻|魔攻|物防|魔防|速度)(?:和(?:物攻|魔攻|物防|魔防|速度))*)([+-])([1-9][0-9]*)%。", description)
    status = re.fullmatch(r"敌方获得([1-9][0-9]*)层(中毒|灼烧|冻结|寄生)。", description)
    defense = re.fullmatch(r"减伤([1-9][0-9]*)%，应对攻击。", description)
    expected_kind = None
    if attack:
        damage_kind = "physical" if (attack[1] or attack[2]) in ("物理", "物") else "magical"
        expected_kind = damage_kind
        if not _positive_integer(skill.get("power")):
            blockers.append("missing_or_invalid_fixed_power")
        else:
            operations.append(_operation("damage", target="opponent", kind=damage_kind, power=skill["power"], type=skill["type"]))
            if attack[3]:
                operations.append(_operation("energy.restore", target="self", amount=int(attack[3])))
    elif swift_attack:
        expected_kind = "physical" if swift_attack[1] == "物" else "magical"
        if not _positive_integer(skill.get("power")):
            blockers.append("missing_or_invalid_fixed_power")
        else:
            # Swift is a source property plus an entry trigger, not an extra
            # damage operation on every manual use of the skill.
            out.update(intrinsic_swift=True,
                       entry_trigger={"kind": "voluntary_switch", "term_id": 1005},
                       dependency_ids=[1005])
            operations.append(_operation("damage", target="opponent", kind=expected_kind,
                                         power=skill["power"], type=skill["type"]))
    elif energy_condition:
        expected_kind, condition, modifier = energy_condition
        if not _positive_integer(skill.get("power")):
            blockers.append("missing_or_invalid_fixed_power")
        else:
            operations.append(_operation("damage.conditional", target="opponent", kind=expected_kind,
                                         power=skill["power"], type=skill["type"],
                                         condition=condition, modifier=modifier))
    elif fixed_hits:
        expected_kind = "physical" if fixed_hits[1] == "物" else "magical"
        if not _positive_integer(skill.get("power")):
            blockers.append("missing_or_invalid_fixed_power")
        else:
            out["dependency_ids"] = [3005]
            # Keep source power unchanged: whether it applies to each hit or
            # the whole sequence is a separate, unresolved execution policy.
            # Even a one-hit sequence stays distinct from an ordinary attack.
            operations.append(_operation("damage.sequence", target="opponent", kind=expected_kind,
                                         power=skill["power"], type=skill["type"], hits=int(fixed_hits[2])))
    elif restore:
        expected_kind = "status"
        operations.append(_operation("energy.restore", target="self", amount=int(restore[1])))
    elif description == "敌方获得魔防-50%，且失去3能量。":
        expected_kind = "status"
        # Retain both effects and the shared opponent target. Losing energy is
        # not stealing it: no self restoration or team-wide expansion is added.
        operations.extend([
            _operation("stat.modify", target="opponent", attributes=["mdef"],
                       percent={"numerator": -50, "denominator": 100}),
            _operation("energy.reduce", target="opponent", amount=3),
        ])
    elif stats:
        expected_kind = "status"
        attributes = [STAT_NAMES[x] for x in stats[2].split("和")]
        if len(attributes) != len(set(attributes)):
            blockers.append("duplicate_stat_attributes")
        else:
            operations.append(_operation("stat.modify", target="self" if stats[1] == "自己" else "opponent",
                                         attributes=attributes, percent={"numerator": int(stats[4]) * (1 if stats[3] == "+" else -1), "denominator": 100}))
    elif status:
        expected_kind = "status"
        status_name = STATUS_NAMES[status[2]]
        out["dependency_ids"] = [STATUS_TERMS[status_name]]
        operations.append(_operation("status.add", target="opponent", status=status_name, stacks=int(status[1])))
    elif defense:
        expected_kind = "defense"
        if int(defense[1]) > 100:
            blockers.append("invalid_damage_reduction")
        else:
            out["dependency_ids"] = [1016]
            operations.append(_operation("defense.plan", target="self", reduction={"numerator": int(defense[1]), "denominator": 100}, response="attack"))
    else:
        sequence = _unconditional_sequence(description, skill)
        if sequence is None:
            blockers.append("description_not_fully_supported")
        else:
            operations, out["dependency_ids"], expected_kind = sequence
    if expected_kind is not None and kind != expected_kind:
        blockers.append("description_kind_conflict")
    notes = skill.get("desc_notes")
    if notes and (not isinstance(notes, list) or any(type(n) is not int or n not in out["dependency_ids"] for n in notes)):
        blockers.append("unresolved_desc_notes")
    if out["dependency_ids"]:
        out["execution_blockers"].append("关联术语的免疫、公共冷却、数值及结算时序需由绑定版本的规则解释器核验。")
    if any(op["op"] == "hp.restore" for op in operations):
        out["execution_blockers"].append("生命回复的百分比基数、取整与溢出处理必须显式解析；没有默认最大生命公式。")
    if any(op["op"] == "damage.sequence" for op in operations):
        out["execution_blockers"].append("连击威力作用域、逐击触发和力竭边界尚未核实；保留来源威力和固定次数，不默认每击使用整段威力。")
    if any(op["op"] == "damage.conditional" for op in operations):
        out["execution_blockers"].append("条件读取时点尚未核实；原文的使用后不等于已验证的支付费用后，必须显式声明实验时序策略。威力加值与伤害倍数不能互换。")
    if any(op["op"] == "energy.reduce" for op in operations):
        out["execution_blockers"].append("失去能量的低能量边界和复合效果结算顺序未核实；必须显式提供实验政策，不默认负能量、截零或转移给施法者。")
    if out.get("intrinsic_swift"):
        out["execution_blockers"].append("迅捷的入场选槽、最终能耗及与入场触发链的顺序须由换人阶段显式解析；普通使用不自动增加一次入场攻击。")
    if blockers:
        return out
    out.update(status="compiled", operations=operations)
    return out


def _records(value, label):
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, list):
        return value
    raise ValueError(label + "应为对象表或数组")


def compile_catalog(catalog: dict) -> dict:
    """Account for every current game ID, including all unsupported traits."""
    if not isinstance(catalog, dict) or not isinstance(catalog.get("snapshot_id"), str) or not catalog["snapshot_id"]:
        raise ValueError("需要明确的数据快照 ID")
    skills, traits = {}, {}
    for record in _records(catalog.get("moves"), "技能"):
        program = compile_skill(record)
        program.update(snapshot_id=catalog["snapshot_id"], source_version=catalog.get("source_version"),
                       term_source=deepcopy(catalog.get("provenance", {}).get("Terms")),
                       skill_source=deepcopy(catalog.get("provenance", {}).get("Skills")))
        if program.get("intrinsic_swift"):
            matches = [term for term in catalog.get("glossary", [])
                       if isinstance(term, dict) and term.get("key") == 1005]
            source = catalog.get("provenance", {}).get("Terms")
            if (len(matches) != 1 or matches[0] != SWIFT_TERM or not isinstance(source, dict)
                    or source.get("content_sha256") != SWIFT_TERMS_SHA256):
                program["blockers"].append("swift_term_missing_ambiguous_or_changed")
                program.update(status="unsupported", operations=[])
            else:
                program["swift_term"] = deepcopy(matches[0])
        key = str(program["game_id"])
        if key in skills:
            raise ValueError("重复技能游戏 ID：" + key)
        skills[key] = program
    for record in _records(catalog.get("traits"), "特性"):
        program = _base(record, "trait")
        program.update(snapshot_id=catalog["snapshot_id"], source_version=catalog.get("source_version"),
                       skill_source=deepcopy(catalog.get("provenance", {}).get("Skills")))
        program["blockers"].append("trait_semantics_not_implemented")
        key = str(program["game_id"])
        if key in traits:
            raise ValueError("重复特性游戏 ID：" + key)
        traits[key] = program
    def counts(values):
        statuses = Counter(x["status"] for x in values.values())
        return {"total": len(values), "compiled": statuses["compiled"], "unsupported": statuses["unsupported"],
                "executable": 0, "real_game_verified": 0}
    return {"compiler_version": COMPILER_VERSION, "snapshot_id": catalog["snapshot_id"],
            "source_version": catalog.get("source_version"),
            "source_provenance": deepcopy(catalog.get("provenance", {})),
            "source_hash": _hash({"snapshot_id": catalog["snapshot_id"], "source_version": catalog.get("source_version"),
                                  "provenance": catalog.get("provenance", {}), "moves": catalog.get("moves"), "traits": catalog.get("traits")}),
            "skills": skills, "traits": traits, "counts": {"skills": counts(skills), "traits": counts(traits)},
            "training_allowed": False, "executable": False, "real_game_verified": False}
