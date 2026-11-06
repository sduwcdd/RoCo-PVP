"""Version-bound BWIKI rules, with no fallback to the historical engine.

This is the source boundary of the replacement battle core. A field or chart
lookup is not a calibrated battle result, and missing rules fail explicitly.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from threading import Lock


class RuleUnavailable(ValueError):
    pass


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _game_id(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise RuleUnavailable("游戏 ID 必须为整数或数字文本")
    if isinstance(value, str) and (not value.isascii() or not value.isdigit()):
        raise RuleUnavailable("游戏 ID 不是规范数字文本")
    number = int(value)
    if number <= 0:
        raise RuleUnavailable("空槽不能当作精灵或技能")
    return number


class BwikiRuleset:
    def __init__(self, catalog):
        self._catalog = deepcopy(catalog)
        # All derived indices must describe the same owned snapshot, rather
        # than rereading the caller's potentially changing source mapping.
        catalog = self._catalog
        self.snapshot_id = catalog.get("snapshot_id")
        if not isinstance(self.snapshot_id, str) or not self.snapshot_id:
            raise RuleUnavailable("规则必须绑定数据快照")
        try:
            self.catalog_content_hash = canonical_hash(self._catalog)
        except (ValueError, TypeError) as exc:
            raise RuleUnavailable("规则快照含非有限数值或非 JSON 数据") from exc
        self._types = frozenset(catalog.get("types", []))
        if not self._types:
            raise RuleUnavailable("属性名单缺失")
        self._forms = self._index(catalog.get("forms", []))
        self._skills = self._index(catalog.get("moves", {}))
        self._traits = self._index(catalog.get("traits", {}))
        self._chart = self._catalog.get("chart", {})
        if catalog.get("chart_schema") != "defender_type_combination_to_attacker_weak_resist; explicit double-type multiplier":
            raise RuleUnavailable("未识别的属性关系表结构")
        self._programs = None
        self._programs_lock = Lock()

    @staticmethod
    def _index(records):
        values = records.values() if isinstance(records, dict) else records
        out = {}
        for record in values:
            key = _game_id(record.get("game_id", record.get("id")))
            if key in out:
                raise RuleUnavailable(f"游戏 ID {key} 无法唯一匹配")
            out[key] = deepcopy(record)
        return out

    def _record(self, index, value, label):
        key = _game_id(value)
        if key not in index:
            raise RuleUnavailable(f"当前快照中没有{label}游戏 ID {key}")
        return deepcopy(index[key])

    def form(self, game_id):
        return self._record(self._forms, game_id, "精灵")

    def skill(self, game_id):
        key = _game_id(game_id)
        if key not in self._skills:
            from lab.core_magic_runtime import reviewed_wish_skill
            reviewed = reviewed_wish_skill(key)
            if reviewed is not None:
                return reviewed
        return self._record(self._skills, game_id, "技能")

    def trait(self, game_id):
        return self._record(self._traits, game_id, "特性")

    def evidence(self, module):
        source = self._catalog.get("provenance", {}).get(module)
        if not source:
            raise RuleUnavailable(f"缺少 {module} 模块的版本来源")
        return {"snapshot_id": self.snapshot_id, "module": module, **deepcopy(source)}

    def type_multiplier(self, attacking_type, defender_form_id):
        if attacking_type not in self._types:
            raise RuleUnavailable("未知攻击属性，不能按无克制处理")
        form = self.form(defender_form_id)
        relation_key = form.get("relation_key")
        chart = self._chart.get(relation_key)
        if not isinstance(chart, dict) or any(not isinstance(chart.get(k), list) for k in ("weak", "resist")):
            raise RuleUnavailable(f"形态 {defender_form_id} 的属性组合表缺失；不会拼乘单属性表")
        seen = set()
        factor = Fraction(1)
        for kind in ("weak", "resist"):
            for item in chart[kind]:
                attack = item.get("type")
                if attack not in self._types or attack in seen:
                    raise RuleUnavailable("属性组合表含未知或重复进攻属性")
                seen.add(attack)
                value = item.get("multiplier")
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise RuleUnavailable("属性倍率不是有效数值")
                try:
                    numeric = Fraction(str(value))
                except (ValueError, ZeroDivisionError) as exc:
                    raise RuleUnavailable("属性倍率不是有限有理数") from exc
                if numeric < 0 or (kind == "weak" and numeric <= 1) or (kind == "resist" and numeric >= 1):
                    raise RuleUnavailable("属性倍率与弱点/抵抗分类冲突")
                if attack == attacking_type:
                    factor = numeric
        return {"attacking_type": attacking_type, "defender_form_id": _game_id(defender_form_id),
                "relation_key": relation_key,
                "multiplier": {"numerator": factor.numerator, "denominator": factor.denominator},
                "basis": "explicit_defender_combination_table", "evidence": self.evidence("Types"),
                "real_game_verified": False}

    def term(self, term_id):
        matches = [t for t in self._catalog.get("glossary", []) if t.get("key") == term_id]
        if len(matches) != 1:
            raise RuleUnavailable("术语无法唯一匹配")
        return {**deepcopy(matches[0]), "evidence": self.evidence("Terms")}

    def _compiled_programs(self):
        """Publish one complete cache per ruleset; never expose it publicly."""
        with self._programs_lock:
            if self._programs is None:
                from lab.rule_config import load_config
                self._programs = load_config(self._catalog)
            return self._programs

    def configuration(self, skill_id):
        """Detached structured data; runtime never reparses skill prose."""
        key = _game_id(skill_id)
        if key not in self._skills:
            raise RuleUnavailable(f"当前快照中没有技能游戏 ID {key}")
        from lab.rule_config import load_bundle
        return deepcopy(load_bundle(self._catalog)["records"]["skills"][str(key)])

    def programs(self):
        return deepcopy(self._compiled_programs())

    def program(self, skill_id):
        """Return only the requested skill program as a detached copy."""
        key = _game_id(skill_id)
        if key not in self._skills:
            from lab.core_magic_runtime import reviewed_wish_program
            reviewed = reviewed_wish_program(self, key)
            if reviewed is not None:
                return reviewed
            raise RuleUnavailable(f"当前快照中没有技能游戏 ID {key}")
        return deepcopy(self._compiled_programs()["skills"][str(key)])

    def plan(self, skill_id, defender_form_id=None):
        skill = self.skill(skill_id)
        compiled = self.program(skill_id)
        result = {"snapshot_id": self.snapshot_id, "catalog_content_hash": self.catalog_content_hash,
                  "skill": skill, "program": compiled, "source": self.evidence("Skills"),
                  "training_eligible": False, "battle_executable": False,
                  "missing_battle_dependencies": ["当前局面的特性、印记、天气和触发链", "实战校准的数值公式及结算顺序"]}
        if defender_form_id is not None:
            result["type_matchup"] = self.type_multiplier(skill["type"], defender_form_id)
        return result
