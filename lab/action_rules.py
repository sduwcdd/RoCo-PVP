"""Source-bound action precedence and charging timing, not a full turn engine.

Unresolved orders are alternatives without assigned probabilities. Charging
readiness never executes an attack, charges energy, or consumes first-action
effects. Those transitions require the eventual complete event interpreter.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json


TERMS_HASH = 'a7a4ad3bc1e30e154cdbc52b9e350ec75cbca04bb39e1b9e7012fa4a220ca822'
TERMS = {
    1007: "该技能需要先蓄力1回合，下回合才能释放。蓄力期间免疫所有离场效果。",
    1015: "若敌方使用状态技能，则本技能应对成功，本次行动必定先手，且触发应对效果。",
    1016: "若敌方使用攻击技能，则本技能应对成功，本次行动必定先手，且触发应对效果。使用后，携带的防御技能进入1回合冷却。",
    1017: "若敌方使用防御技能，则本技能应对成功，本次行动必定先手，且触发应对效果。",
    1020: "技能行动的优先级，先手度更高的技能忽略双方精灵速度差异，优先释放，先手度可叠加。",
}
SKILL_KINDS = frozenset({"physical", "magical", "higher", "status", "defense"})
RESPONSES = {"attack": 1016, "status": 1015, "defense": 1017}


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _int(value, label, minimum=None):
    if type(value) is not int:
        raise ValueError(f"{label} 必须为整数")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} 必须至少为 {minimum}")
    return value


class ActionRules:
    def __init__(self, catalog):
        if not isinstance(catalog, dict) or not isinstance(catalog.get("snapshot_id"), str) or not catalog["snapshot_id"]:
            raise ValueError("行动规则必须绑定数据快照")
        source = catalog.get("provenance", {}).get("Terms", {})
        if source.get("content_sha256") != TERMS_HASH:
            raise ValueError("Terms 修订未经过本行动规则核查")
        for key, definition in TERMS.items():
            matches = [x for x in catalog.get("glossary", []) if x.get("key") == key]
            if len(matches) != 1 or matches[0].get("definition") != definition:
                raise ValueError(f"术语 {key} 内容与已核查版本不符")
        self.snapshot_id = catalog["snapshot_id"]
        self._source = deepcopy(source)
        self._skills_source = deepcopy(catalog.get("provenance", {}).get("Skills", {}))
        from lab.phase_config import source_payload
        self._phase_catalog = source_payload(catalog)
        self._phase_config = None
        records = catalog.get("moves", {})
        records = records.values() if isinstance(records, dict) else records
        self._skills = {}
        for record in records:
            mid = _int(record.get("game_id", record.get("id")), "技能游戏 ID", 1)
            if mid in self._skills:
                raise ValueError("技能游戏 ID 不能重复")
            self._skills[mid] = deepcopy(record)

    def _result(self, term_ids, **data):
        return {"snapshot_id": self.snapshot_id, "training_eligible": False,
                "calibrated": False, "full_turn_executed": False,
                "evidence": {"terms": list(term_ids), "source": deepcopy(self._source)}, **data}

    @staticmethod
    def counter_matches(response, opponent_kind):
        if response not in RESPONSES or opponent_kind not in SKILL_KINDS:
            raise ValueError("应对类别或对方技能类别未知")
        return opponent_kind in {"physical", "magical", "higher"} if response == "attack" else opponent_kind == response

    @staticmethod
    def _action(action):
        if not isinstance(action, dict):
            raise ValueError("行动描述必须为对象")
        _hash(action)
        kind = action.get("kind")
        if kind not in SKILL_KINDS | {"switch", "charge", "unknown"}:
            raise ValueError("未知行动类型")
        _int(action.get("priority"), "已解析先手度")
        if action.get("speed") is not None:
            _int(action["speed"], "已解析速度", 0)
        if "speed" not in action:
            raise ValueError("速度必须显式提供；未知时使用 null")
        responses = action.get("responses")
        if not isinstance(responses, list) or any(x not in RESPONSES for x in responses) or len(set(responses)) != len(responses):
            raise ValueError("应对列表必须显式给出已知且不重复的类别")
        pending = action.get("unresolved_modifiers", [])
        if not isinstance(pending, list) or any(not isinstance(x, str) or not x for x in pending):
            raise ValueError("未解决的先手/速度修正必须是非空文本列表")
        return deepcopy(action)

    def order_candidates(self, action_a, action_b):
        a, b = self._action(action_a), self._action(action_b)
        base = {"status": "unresolved", "possible_orders": [["a", "b"], ["b", "a"]],
                "counter_success": {"a": None, "b": None}, "actions": {"a": a, "b": b}}
        if a.get("unresolved_modifiers") or b.get("unresolved_modifiers"):
            return self._result([1020], **base, reason="先手或速度修正尚未完整解析")
        if a["kind"] not in SKILL_KINDS or b["kind"] not in SKILL_KINDS:
            return self._result([1007, 1020], **base, reason="换人、蓄力步骤或未知行动与技能的统一顺序尚未核实")
        successful = {"a": any(self.counter_matches(r, b["kind"]) for r in a["responses"]),
                      "b": any(self.counter_matches(r, a["kind"]) for r in b["responses"])}
        base["counter_success"] = successful
        term_ids = sorted({1020, *(RESPONSES[r] for x in (a, b) for r in x["responses"])})
        if successful["a"] and successful["b"]:
            return self._result(term_ids, **base, reason="双方应对同时成功，冲突排序尚未核实")
        first = "a" if successful["a"] else "b" if successful["b"] else None
        if first:
            base.update(status="determined", possible_orders=[[first, "b" if first == "a" else "a"]])
            return self._result(term_ids, **base, reason="单方应对成功；对应术语明确本次行动先手")
        if a["priority"] != b["priority"]:
            first = "a" if a["priority"] > b["priority"] else "b"
            base.update(status="determined", possible_orders=[[first, "b" if first == "a" else "a"]])
            return self._result(term_ids, **base, reason="先手度不同；较高者忽略速度差异先行动")
        reason = "同先手度且速度未知，无法确定行动顺序" if a["speed"] is None or b["speed"] is None else "同先手度的速度排序和同速规则尚无直接核验依据"
        return self._result(term_ids, **base, reason=reason)

    def requires_charge(self, skill_id):
        """Reviewed source classification only; this does not execute charging."""
        _int(skill_id, "技能游戏 ID", 1)
        if skill_id not in self._skills:
            return False
        if self._phase_config is None:
            from lab.phase_config import load_phase_config
            self._phase_config = load_phase_config(self._phase_catalog)
        return self._phase_config["skills"][str(skill_id)]["charge"]["declared"]

    def charge_state(self, slot, skill_id, started_turn):
        _int(slot, "技能槽", 0)
        if slot > 3:
            raise ValueError("技能槽使用 0～3，不能压缩空槽")
        _int(skill_id, "技能游戏 ID", 1)
        _int(started_turn, "开始蓄力回合", 1)
        record = self._skills.get(skill_id)
        if not self.requires_charge(skill_id):
            raise ValueError("当前技能没有已支持的直接蓄力声明；不能从提及蓄力的其他效果推断")
        return {"snapshot_id": self.snapshot_id, "slot": slot, "skill_id": skill_id,
                "started_turn": started_turn, "release_turn": started_turn + 1,
                "source_skill_hash": _hash(record), "term_source_hash": TERMS_HASH,
                "training_eligible": False, "calibrated": False}

    def charge_transition(self, state, *, current_turn, slot, skill_id):
        result = self._result([1007], status="blocked", charge=deepcopy(state),
                              next_charge=deepcopy(state), release_allowed=False, execute_skill=False)
        try:
            _int(current_turn, "当前回合", 1)
            if not isinstance(state, dict):
                raise ValueError("蓄力记录必须为对象")
            _hash(state)
            expected = self.charge_state(state.get("slot"), state.get("skill_id"), state.get("started_turn"))
            for key in ("snapshot_id", "slot", "skill_id", "started_turn", "release_turn", "source_skill_hash", "term_source_hash"):
                if type(state.get(key)) is not type(expected[key]) or state[key] != expected[key]:
                    raise ValueError("蓄力记录的槽位、时序或来源已变化")
            _int(slot, "当前技能槽", 0)
            _int(skill_id, "当前技能 ID", 1)
            if slot != state["slot"] or skill_id != state["skill_id"]:
                raise ValueError("蓄力后的技能槽或技能已变化，需要核对，不能释放另一技能")
            if current_turn < state["started_turn"]:
                raise ValueError("当前回合早于开始蓄力回合")
            if current_turn > state["release_turn"]:
                raise ValueError("已越过预定释放回合，延迟释放规则未核实")
            if current_turn == state["started_turn"]:
                result.update(status="waiting", reason="先蓄力 1 回合，当前不能释放")
            else:
                result.update(status="ready", release_allowed=True, release_commit_required=True,
                              reason="已到下回合；仅具备释放时序条件，未执行技能或支付费用，蓄力记录保留至独立处理释放结果")
        except (ValueError, TypeError, KeyError) as exc:
            result["reason"] = str(exc)
        return result
