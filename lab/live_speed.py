"""Public action-order evidence; candidates reuse the shared live stat model."""
from copy import deepcopy
from functools import lru_cache
import json
import math
import re

from . import battle_data, live_modifiers, trait_runtime, weather_runtime

ORDER_TEXT = re.compile(r"先手|后手|迅捷|应对|蓄力|借用|取念|复写|听桥|行动顺序|反转")


@lru_cache(maxsize=1)
def _listener_effect(stamp):
    path = live_modifiers.ROOT / "artifacts/unpack_probe_20261025/battle_analysis/tables/parsed/EFFECT_CONF.json"
    return json.loads(path.read_text(encoding="utf-8"))["1085006"]


def _reviewed_listener(buff_id, raw):
    if buff_id != 20170880:
        return False
    from .ruleset import canonical_hash
    path = live_modifiers.ROOT / "artifacts/unpack_probe_20261025/battle_analysis/tables/parsed/EFFECT_CONF.json"
    # EFFECT order 85 is a skill reference; it is not BUFFBASE order 85 (priority inversion).
    rows = [(raw, "2c3aed9780de0229f6a2850d57ae73784058a0e0525fb5857c10af16f5fcb03c"),
        (live_modifiers._buff_bases().get("2017088"), "da715150ece7049ed7feb07a8db68f601d875404f7e15edf28023d3de452472d"),
        (_listener_effect(path.stat().st_mtime_ns), "e36f059fe31f528d2c2dab730372c9f37e10581a26b2ab75ccd394b0a9013f6b"),
        (battle_data._skills().get("7060220"), "25a9131790940effe83f29a902c3185f7fd98567def0d483255635beb01cf7e3")]
    return all(canonical_hash(row) == digest for row, digest in rows)


def _validate_buff_order(buff_id, seen=()):
    raw = live_modifiers._raw_buffs().get(str(buff_id))
    if raw is None or buff_id in seen or ORDER_TEXT.search(raw.get("desc", "") + raw.get("name", "")):
        raise ValueError("状态可能改变先手度或尚未识别")
    if _reviewed_listener(buff_id, raw):
        return
    for base_id in raw.get("buff_base_ids", []):
        base = live_modifiers._buff_bases().get(str(base_id), {})
        if not base or base.get("buffbase_order") in (35, 85, 108):
            raise ValueError("状态含先手、额外释放或尚未核对的派生效果")
        if base.get("buffbase_order") == 17:
            for child in base["buffbase_param"][0]["params"]:
                _validate_buff_order(child, (*seen, buff_id))


def speed_values(pet, opponent, base_panel=None):
    reported = (pet.get("battleStats") or {}).get("spd")
    if base_panel is None and type(reported) in (int, float) and reported > 0:
        # AT_SPEED already contains live flat speed grants; never add them twice.
        return [reported]
    if base_panel is not None:
        pet = {**pet, "_referenceBaseStats": {"spd": [base_panel]}}
    values, _ = live_modifiers.panel_candidates(pet, "spd", opponent)
    member, other = live_modifiers.actor(pet), live_modifiers.actor(opponent)
    represented = live_modifiers._observed_entry_buffs(member, pet, ["speedFlat"], required=True)
    bonus = 0 if represented else trait_runtime.speed_bonus(member, opponent=other)
    weather = pet.get("liveContext", {}).get("weather")
    return [weather_runtime.modify_speed(weather, math.floor(value) + bonus, member) for value in values]


@trait_runtime.query_scope()
def _speed_signature(pet, opponent):
    reported = (pet.get("battleStats") or {}).get("spd")
    if type(reported) in (int, float) and reported > 0:
        return [reported]
    low, high = speed_values(pet, opponent, 100), speed_values(pet, opponent, 200)
    if len(low) != 1 or len(high) != 1 or high[0] - low[0] != 100:
        raise ValueError("未知速度含百分比修正，内部精度尚未核实")
    return low, high


@trait_runtime.query_scope()
def _priority(pet, skill_id):
    info = battle_data.canonical_skill(skill_id)
    native = battle_data._skills().get(str(info.get("skill_id")), {})
    priority = native.get("skill_priority")
    if type(priority) is not int or ORDER_TEXT.search(info.get("desc", "")):
        raise ValueError("技能先手度或特殊释放条件尚未确认")
    trait_id = pet.get("effectiveTraitId")
    trait = battle_data.skill_info(trait_id)
    if trait_id and (not trait or ORDER_TEXT.search(trait.get("desc", ""))):
        raise ValueError("特性可能改变先手度或释放方式")
    row = trait_runtime._rows().get(trait_id, {})
    if any("priority" in c.get("op", "") or "swift" in c.get("op", "")
           for c in row.get("components", [])):
        raise ValueError("特性含额外先手或迅捷行动")
    for buff in live_modifiers.captured_buffs(pet):
        _validate_buff_order(buff.get("id"))
        raw = live_modifiers._raw_buffs()[str(buff["id"])]
        calc = live_modifiers.calc_buff(buff.get("id"))
        if "速度" in raw.get("desc", "") and not any(k in calc for k in ("speedFlat", "speedPercent")):
            raise ValueError("速度状态尚未完整解析")
    weather = pet.get("liveContext", {}).get("weather")
    return weather_runtime.modify_priority(weather, info["skill_id"], priority, live_modifiers.actor(pet))


def _root(item):
    return (item.get("type") == 1 and (item.get("skill_cast") or {}).get("type") == 1
            and item.get("cast_moment") == 0 and item.get("is_group_head") is True
            and item.get("group_ref") == 0)


def _context(tracker):
    from .live_damage import _pet_types
    active = [tracker.teams[side][tracker.active[side]] for side in (0, 1)]
    rosters = {side: [{"member_id": str(p.pet_id), "types": _pet_types(p.to_payload(hide_unobserved=True, observed={})),
                       "hp": p.hp, "cute_layers": p.cute_stacks} for p in team]
               for side, team in tracker.teams.items()}
    result = []
    for pet in active:
        payload = deepcopy(pet.to_payload(hide_unobserved=pet.side == 1,
            observed=tracker.observed_enemy_skills.get(str(pet.pet_id), {}) if pet.side == 1 else {}))
        tracker._apply_stat_policy(payload)
        payload["liveContext"] = {"turn": tracker.round, "weather": deepcopy(tracker.live_weather),
            "rosters": {"self": rosters[pet.side], "opponent": rosters[1 - pet.side]},
            **tracker._party_counts_context(pet.side)}
        result.append(payload)
    return result


class SpeedOrderObserver:
    def __init__(self):
        self.evidence = {}
        self.round = None
        self.state = {}

    def _block(self, tracker, reason):
        self.state["blocker"] = reason
        event = self.state.pop("event", None)
        if event is not None:
            bucket = self.evidence[str(event["pet_id"])]
            bucket.remove(event)
            tracker._configuration_cache.pop(str(event["pet_id"]), None)

    def begin(self, tracker, cmd):
        if self.round != tracker.round:
            self.round, self.state = tracker.round, {"casts": [], "seen": {}}
        self.state["ignore"] = False
        if self.state.get("blocker") or not cmd.get("perform_info"):
            return
        items = cmd["perform_info"]
        for item in items:
            if any(item.get(key) for key in ("change_pet", "supply_pet", "change_model")):
                self._block(tracker, "换人或形态变化回合不用于速度推断")
                return
            if any(item.get(key) for key in ("combo_skill_cast", "role_skill_cast", "feature_resonance")):
                self._block(tracker, "特殊释放回合不用于速度推断")
                return
            cast = item.get("skill_cast") or {}
            info = battle_data.canonical_skill(cast.get("skill_id"))
            if cast and (cast.get("type") == 3 or cast.get("is_interupt")
                    or cast.get("resonance_pet_id") not in (None, 0, "0")
                    or info.get("category") == 1 and not _root(item)):
                self._block(tracker, "应对或额外释放回合不用于速度推断")
                return
        if not any(_root(item) for item in items):
            return  # Environment-only round headers do not order the players' actions.
        seq = cmd.get("seq_num")
        indices = [item.get("exec_index") for item in items]
        if (type(seq) is not int or any(type(i) is not int or i < 0 for i in indices)
                or len(set(indices)) != len(indices)):
            self._block(tracker, "缺少可核对的执行顺序")
            return
        from .ruleset import canonical_hash
        token = canonical_hash(cmd)
        if self.state["seen"].get(seq) == token:
            self.state["ignore"] = True
            return
        if self.state["seen"] and seq <= max(self.state["seen"]):
            self._block(tracker, "同轮重复或乱序报文，不重复推断速度")
            return
        self.state["seen"][seq] = token
        if "initial" not in self.state:
            if not all(tracker.teams.values()) or not all(tracker._active_confirmed.values()):
                self._block(tracker, "双方在场精灵尚未确认")
                return
            self.state["initial"] = _context(tracker)

    def cast(self, tracker, item):
        if self.state.get("blocker") or self.state.get("ignore") or not _root(item) or "initial" not in self.state:
            return
        cast = item["skill_cast"]
        try:
            info = battle_data.canonical_skill(cast.get("skill_id"))
            if info.get("category") != 1:
                raise ValueError("聚能等特殊行动不用于速度推断")
            initial = self.state["initial"]
            side = next(i for i, p in enumerate(initial) if str(p["petId"]) == str(cast.get("caster_id")))
            if any(c["side"] == side for c in self.state["casts"]):
                raise ValueError("同一方出现多次主行动")
            current = _context(tracker)
            for i in (0, 1):
                if (current[i]["petId"], current[i]["petBaseId"], current[i]["level"]) != (
                        initial[i]["petId"], initial[i]["petBaseId"], initial[i]["level"]):
                    raise ValueError("排序期间精灵身份或等级发生变化")
                if _speed_signature(initial[i], initial[1-i]) != _speed_signature(current[i], current[1-i]):
                    raise ValueError("两次行动之间速度修正发生变化")
            priority = _priority(initial[side], info["skill_id"])
            if priority != _priority(current[side], info["skill_id"]):
                raise ValueError("排序期间先手度发生变化")
            self.state["casts"].append({"side": side, "skill_id": info["skill_id"], "priority": priority})
        except (OSError, ValueError, KeyError, TypeError, StopIteration) as error:
            self._block(tracker, str(error))

    def finish(self, tracker):
        casts = self.state.get("casts", [])
        if self.state.get("blocker") or self.state.get("event") or len(casts) != 2:
            return
        if casts[0]["priority"] != casts[1]["priority"]:
            self._block(tracker, "双方先手度不同")
            return
        try:
            ally, enemy = self.state["initial"]
            speeds = speed_values(ally, enemy)
            from .live_damage import _effective_base, _rules
            event = {"kind": "speed_order", "turn": self.round, "dimension": "spd", "role": "speed",
                "pet_id": enemy["petId"], "form_id": _effective_base(enemy), "subject_level": enemy["level"],
                "subject_first": casts[0]["side"] == 1, "opponent_speed": [min(speeds), max(speeds)],
                "skill_id": next(c["skill_id"] for c in casts if c["side"] == 1),
                "skills": deepcopy(casts), "snapshot_id": _rules()[0]["snapshot_id"],
                "calculation": {"subject": enemy, "opponent": ally}, "policy": "public_equal_priority_order_v1"}
            self.evidence.setdefault(str(enemy["petId"]), []).append(event)
            self.state["event"] = event
            tracker._configuration_cache.pop(str(enemy["petId"]), None)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self._block(tracker, str(error))
