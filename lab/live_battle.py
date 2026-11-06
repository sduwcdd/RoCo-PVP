"""把 rkpp 抓到的战斗消息翻译成工作台/HUD 用的对局快照。

与 ``lab.live_bridge`` 的区别：那个模块吃的是人读的 ``summary_text`` 正则，
字段名一变就失效；这里直接吃 relay 的 ``content`` —— schema 解出来的原始结构，
字段含义已经用真实抓包核对过（见 ``artifacts/_probe_battle.txt``）：

``ZoneBattleEnterNotify`` (0x1316)
    content.init_info.player_team[0].pets[] 每只带 ``battle_inside_pet_info``（战斗内）
    与 ``battle_common_pet_info``（养成面板）。已核对：
      * ``battle_attr[1]`` = 最大生命（与 FinishNotify 的 ``battle_max_hp`` 一致）
      * ``skill_round_data`` 里 ``pos`` 1..4 就是四个技能槽（pos 0/12/13 是聚能、道具、被动）
      * ``conf_name`` 是正式名，``name`` 是十六进制 UTF-8 的昵称
``ZoneBattleCmdSyncNotify`` (0x1322)
    ``req.cast_skill`` = 本次选择（skill_id / caster_pet_id）。
``ZoneBattlePerformStartNotify`` (0x1324)
    ``perform_cmd.perform_info[]`` 按 ``exec_index`` 逐段执行（数组按表现分组，非结算顺序）：
      * ``type=1 skill_cast`` 谁放了什么
      * ``type=4 damage_info`` 命中/暴击/克制
      * ``sync_data.pet_sync_info[]`` 结算量：``original_damage``/``damage_result``、
        ``hp_change``（uint64 补码，需转有符号）/``hp_result``、``energy_change``/``energy_result``
``ZoneBattleFinishNotify`` (0x132C)
    ``settle_info.result`` + ``pet_info[]``（``remain_hp``/``battle_max_hp``）。

敌方隐私：抓包能看到对手完整配招，但快照里敌方只暴露**已经打出来过的**技能，
其余槽位标记为未知，避免策略接口拿到对手未公开信息。
"""
from __future__ import annotations

import json
from hashlib import sha256
from copy import deepcopy
from pathlib import Path
from typing import Any

from lab import battle_data
from lab.constants import SINGLE_HIT

SCHEMA = "workbench-hud-1"

# opcode -> 语义
OP_BATTLE_ENTER = "0x1316"
OP_ROUND_START = "0x131A"
OP_CMD_SYNC = "0x1322"
OP_PERFORM_START = "0x1324"
OP_ROUND_FINISH = "0x1314"
OP_FINISH = "0x132C"

BATTLE_OPCODES = {
    OP_BATTLE_ENTER: "battle_enter",
    OP_ROUND_START: "round_start",
    OP_CMD_SYNC: "cmd_sync",
    OP_PERFORM_START: "perform_start",
    OP_ROUND_FINISH: "round_finish",
    OP_FINISH: "battle_finish",
}

# battle_attr 的槽位（第一条是占位，剩下的顺序与常见属性表一致）
_ATTR_HP = 1
_ATTR_ATK = 2
_ATTR_SP_ATK = 3
_ATTR_DEF = 4
_ATTR_SP_DEF = 5
_ATTR_SPD = 6
_ATTR_CURRENT_HP = 25  # PetUtils.GetHP -> AT_HPCUR; rkpp_proto_core.ds[25].

# 道具改写性格时的属性下标 → 与 catalog natures 的 up/down 同一套短名
_NATURE_ATTR_KEYS = {1: "hp", 2: "patk", 3: "matk", 4: "pdef", 5: "mdef", 6: "spd"}

# natures 里的短名 → 面板 key（用来把性格增减套到六维上）
_NATURE_KEY_TO_STAT = {"hp": "hp", "patk": "phyAtk", "matk": "magAtk",
                       "pdef": "phyDef", "mdef": "magDef", "spd": "spd"}

# 性格倍率：减益恒 −10%；增益按星级递增，0 星 +10%，每多一星再 +2%，5 星 +20%。
# （用户确认的规则；5 星以上本系/系别极化另有加成，PVP 恒为 5 星，此处不涉及）
STAR_NATURE_UP = {0: 0.10, 1: 0.12, 2: 0.14, 3: 0.16, 4: 0.18, 5: 0.20}
_NATURE_DOWN_MULT = 0.9

# arena_stat60 里不参与性格缩放的固定成长值：生命 100，其余 50
_NATURE_BONUS = {"hp": 100}
_NATURE_BONUS_DEFAULT = 50

# 5 星以上：每多一星，本系伤害强化 +15%、系别极化 +45%（用户口径，PVP 不触发，仅登记）
STAR_STAB_STEP = 0.15
STAR_POLARIZE_STEP = 0.45


def nature_up_multiplier(stars: int) -> float:
    """增益性格倍率：0 星 1.10，每多一星 +0.02，5 星及以后 1.20。"""
    return 1.0 + STAR_NATURE_UP.get(max(0, min(5, int(stars))), 0.20)


def stars_from_level(level: int) -> int:
    """报文没有星级字段，只能退而用等级判：PVP 恒为 60 级 5 星，其余按 0 星。"""
    return 5 if int(level or 0) >= 60 else 0


def nature_adjusted_stat(level: int, key: str, value: int, direction: str | None,
                         stars: int | None = None) -> int:
    """把面板值换算成"含性格、不含战斗内 buff"的实际值。

    用户确认的规则：**减益恒 −10%；增益 0 星 +10%，每多一星再 +2%，5 星 +20%**。

    两种换算结构（都已实测验证）：
    - **5 星**：性格只缩放 core，成长值不参与缩放：
      ``round((value − K) × 倍率 + K)``，K 生命 100、其余 50。
      实证：魔力猫 60 级 5 星六维 6/6 精确。
    - **0~4 星**：按总值缩放 ``round(value × 倍率)``。
      实证：白金独角兽/怂猫/石冠王蜥/恶魔狼四只 51 级共 8 个维度 0 误差（均为 0 星，倍率 1.10 / 0.9）。

    调用方按战斗模式显式传星级；inspire_lv 仅对应额外成长阶段，
    不能直接当总星数。省略 stars 仅保留旧的PVP兼容默认。
    """
    if not direction or not value or value <= 0:
        return int(value)
    if stars is None:
        stars = stars_from_level(level)
    stars = max(0, min(10, int(stars)))
    multiplier = nature_up_multiplier(stars) if direction == "up" else _NATURE_DOWN_MULT
    if stars >= 5:
        bonus = _NATURE_BONUS.get(key, _NATURE_BONUS_DEFAULT)
        return int((value - bonus) * multiplier + bonus + 0.5)
    return int(value * multiplier + 0.5)

# 养成面板 attribute_info 的键
_PANEL_STATS = (
    ("hp", "hp"),
    ("attack", "phyAtk"),
    ("special_attack", "magAtk"),
    ("defense", "phyDef"),
    ("special_defense", "magDef"),
    ("speed", "spd"),
)


def _signed(value: Any) -> int | None:
    """把 uint64 补码转成有符号整数（协议里 -26 会编码成 2**64-26）。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number >= 2 ** 63:
        number -= 2 ** 64
    return number


def _hex_name(value: Any) -> str:
    """``name`` 字段是昵称的 UTF-8 十六进制，解不出来就原样返回。"""
    if not isinstance(value, str) or not value:
        return ""
    try:
        return bytes.fromhex(value).decode("utf-8", errors="replace")
    except ValueError:
        return value


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _execution_order(value: Any) -> list:
    """perform_info is grouped for presentation; exec_index orders nested effects."""
    items = _as_list(value)
    indices = [_as_dict(item).get("exec_index") for item in items]
    # shortcut: legacy/incomplete packets retain wire order; do not invent missing indices.
    if all(type(index) is int and index >= 0 for index in indices) and len(set(indices)) == len(indices):
        return sorted(items, key=lambda item: item["exec_index"])
    return items


def _perform_token(cmd, round_no):
    if not cmd.get("perform_info"):
        return None
    data = {"round": round_no, "seq": cmd.get("seq_num"), "items": cmd["perform_info"]}
    return sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _same_band_as_enemy(pet_id: Any, enemy_team: list) -> bool:
    """新出现的 pet_id 是否与已有敌方宠物同一编号段（真实样本 401~406）。

    观战里 owner_uin 双方都是 0，只能退到编号段这一层；宁可漏判记 pending，
    也不能把对方精灵塞进我方队伍。
    """
    try:
        target = int(pet_id)
    except (TypeError, ValueError):
        return False
    enemy_ids = [p.pet_id for p in enemy_team if isinstance(p.pet_id, int)]
    if not enemy_ids:
        return False
    if target in enemy_ids:
        return False
    return target // 100 in {eid // 100 for eid in enemy_ids}


def _pos_is_field(pos: Any) -> bool:
    """``pos`` 是队内位置；真实报文里未上场的替补是 uint64 最大值。"""
    try:
        value = int(pos)
    except (TypeError, ValueError):
        return False
    return 0 < value < (1 << 63)


def _walk_pet_infos(node: Any, _depth: int = 0):
    """深度找出报文里所有 ``battle_inside_pet_info``。

    换人时新精灵可能挂在任意层级（perform_cmd / sync_data / others…），
    只按固定路径取会漏。
    """
    if _depth > 8:
        return
    if isinstance(node, dict):
        inside = node.get("battle_inside_pet_info")
        if isinstance(inside, dict):
            yield inside, _as_dict(node.get("battle_common_pet_info"))
        for value in node.values():
            yield from _walk_pet_infos(value, _depth + 1)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_pet_infos(value, _depth + 1)


def _panel_stats(common: dict) -> dict[str, int]:
    info = _as_dict(common.get("attribute_info"))
    stats: dict[str, int] = {}
    for source_key, out_key in _PANEL_STATS:
        entry = _as_dict(info.get(source_key))
        if not entry:
            continue
        base = entry.get("base_value")
        effort = entry.get("effort_add")
        if base is None:
            continue
        try:
            stats[out_key] = int(base) + int(effort or 0)
        except (TypeError, ValueError):
            continue
    return stats


def _attr_stats(inside: dict) -> dict[str, int]:
    """Captured nature-adjusted base attributes; percentage BUFF layers are separate."""
    attrs = _as_list(inside.get("battle_attr"))
    def at(index: int) -> int | None:
        if index < len(attrs):
            value = attrs[index]
            if isinstance(value, int):
                return value
        return None
    out: dict[str, int] = {}
    mapping = (("hp", _ATTR_HP), ("phyAtk", _ATTR_ATK), ("magAtk", _ATTR_SP_ATK),
               ("phyDef", _ATTR_DEF), ("magDef", _ATTR_SP_DEF), ("spd", _ATTR_SPD))
    for key, index in mapping:
        value = at(index)
        if value is not None:
            out[key] = value
    return out


def _current_hp(inside):
    attrs = _as_list(inside.get("battle_attr"))
    value = _signed(attrs[_ATTR_CURRENT_HP]) if len(attrs) > _ATTR_CURRENT_HP else None
    return value if value is not None and value >= 0 else None


def _talent_evidence(common: dict) -> dict:
    info = _as_dict(common.get("attribute_info"))
    dimensions = {}
    for source_key, stat in _PANEL_STATS:
        row = _as_dict(info.get(source_key))
        fields = {k: row[k] for k in ("talent", "talent_add_value", "base_value", "effort_add", "total_race") if k in row}
        if fields:
            dimensions[stat] = fields
    return {"source": "battle_common_pet_info.attribute_info", "selected_ids": info.get("break_enhance_enum"),
            "dimensions": dimensions} if info else {}


def _skill_slots(inside: dict) -> list[dict[str, Any]]:
    """取四个战斗技能槽；pos 1..4 是槽位，其余（聚能/道具/被动）不进槽。"""
    slots: dict[int, dict[str, Any]] = {}
    for raw in _as_list(inside.get("skill_round_data")):
        if not isinstance(raw, dict):
            continue
        pos = raw.get("pos")
        if not isinstance(pos, int) or not 1 <= pos <= 4:
            continue
        cost = raw.get("cost_energy")
        cost_list = _as_list(raw.get("skill_energy_cost"))
        slots[pos] = {
            "slot": pos,
            "skill_id": raw.get("skill_id") or raw.get("id"),
            "skillId": raw.get("skill_id") or raw.get("id"),
            "skillName": raw.get("skill_name") or "",
            "moveName": raw.get("skill_name") or "",
            "name": raw.get("skill_name") or "",
            "energy_cost": cost if isinstance(cost, int) else (cost_list[0] if cost_list else None),
            "damage_type": raw.get("skill_damage_type"),
            "skill_desc": raw.get("skill_desc") or "",
            "cd": raw.get("cd_round"),
            "state": raw.get("state"),
        }
    return [slots[pos] for pos in sorted(slots)]


def _buffs(inside: dict) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in _as_list(inside.get("buffs")):
        if not isinstance(raw, dict):
            continue
        out.append({
            "id": raw.get("buff_id"),
            "layers": raw.get("stack"),
            "leftRounds": raw.get("buff_left_round"),
            "hidden": bool(raw.get("is_hidden")),
        })
    return out


class _Pet:
    """一只精灵在本次对局里的状态。"""

    def __init__(self, *, side: int, roster_index: int, inside: dict, common: dict, assume_full: bool = True) -> None:
        self.side = side
        self.roster_index = roster_index
        self.pet_id = inside.get("pet_id")
        self.conf_id = inside.get("conf_id") or common.get("conf_id")
        self.base_conf_id = inside.get("base_conf_id") or common.get("base_conf_id")
        self.original_base_conf_id = common.get("base_conf_id") or self.base_conf_id
        self.runtime_feature_id = inside.get("cur_passive_skill") if type(inside.get("cur_passive_skill")) is int and inside["cur_passive_skill"] > 0 else None
        self.conf_name = inside.get("conf_name") or common.get("conf_name") or ""
        self.nickname = _hex_name(inside.get("name")) or _hex_name(common.get("name"))
        self.level = common.get("level")
        self.energy = common.get("energy", 10)
        self.max_energy = inside.get("max_energy", 10)
        self.entered_turn = None
        self.entry_action_count = None
        self.entry_count = None
        self.skill_use_counts = {}
        self.skill_type_use_counts = {}
        self.response_success_count = 0
        self.skill_use_history_complete = False
        self.history_start_round = None
        self.history_incomplete_reason = '尚未确认从首回合完整观测'
        self.skills = _skill_slots(inside)
        self.buffs = _buffs(inside)
        self._form_cute_layers = self.cute_stacks
        self.initial_buff_ids = {str(buff.get("id")) for buff in self.buffs if buff.get("id") is not None}
        self.panel_stats = _panel_stats(common)
        self.talent_evidence = _talent_evidence(common)
        self.attr_stats = _attr_stats(inside)
        self.revealed_base_stats = {k:v for k,v in self.attr_stats.items() if v > 0}
        attrs = _as_list(inside.get("battle_attr"))
        self.max_hp = attrs[_ATTR_HP] if len(attrs) > _ATTR_HP and isinstance(attrs[_ATTR_HP], int) else None
        self.frozen_hp = 0
        self.apply_kill_info(inside)
        current = _current_hp(inside)
        self.hp = current if current is not None else self.max_hp if assume_full else None
        self.hp_source = "battle_attr[25]" if current is not None else "fresh_battle_full" if assume_full else "unknown"
        self.alive = self.hp > 0 if self.hp is not None else None
        self.blood_id = common.get("blood_id")
        self.nature = common.get("nature")
        self.speciality_id = common.get("speciality_id")
        self.real_speciality_ids = deepcopy(common.get("real_speciality_ids"))
        for field in ("height", "weight", "voice", "wear_medal_conf_id"):
            setattr(self, field, common.get(field))
        # 性格可能被道具改写：报文另给 changed_nature_pos_attr_type / neg_attr_type。
        # 显式0表示未改写；敌方缺失字段不能当作确认0。
        # 非 0 时按 battle_attr 下标口径（1生命 2物攻 3魔攻 4物防 5魔防 6速度）理解。
        self.nature_pos_override = common.get("changed_nature_pos_attr_type") or 0
        self.nature_neg_override = common.get("changed_nature_neg_attr_type") or 0
        self.nature_override_known = {
            "up": "changed_nature_pos_attr_type" in common,
            "down": "changed_nature_neg_attr_type" in common,
        }
        # 报文里的 conf_name 只是基础名（迪莫），真正形态看 base_conf_id（5026=圣草迪莫）。
        self._update_form_identity()
        # 实机核对：首领化入场时首槽就已经是愿力冲击（抓包里玩家提交的技能就是
        # 7700002），不是等打出克制之后才换。这里保留字段只作"是否已生效"的标记。
        self.first_slot_replaced = bool(self.feature_will_type)

    def _update_form_identity(self):
        self.form = battle_data.pet_form(self.base_conf_id)
        self.feature_id = self.runtime_feature_id or self.form.get("feature_id")
        self.feature_desc = ((battle_data.skill_info(self.runtime_feature_id).get("desc") or "")
                             if self.runtime_feature_id else self.form.get("feature_desc") or "")
        self.feature_will_type = battle_data.will_impact_type_from_feature(self.feature_desc)

    def display_name(self) -> str:
        # 萌化后退化到上一阶，名字要跟着变（圣草迪莫 → 迪莫），否则场上是谁都认错。
        lowered = self.lowered_form()
        if lowered.get("name"):
            return lowered["name"]
        # 形态名优先：玩家看到的是「圣草迪莫」，而不是基础名「迪莫」。
        form_name = self.form.get("name") or ""
        return form_name or self.conf_name or self.nickname or (
            f"#{self.conf_id}" if self.conf_id else "?")

    def hp_percent(self) -> int | None:
        if self.hp is None:
            return None
        # 存活精灵至少显示 1%，避免 HUD 上 1/200 显示成 0%。
        if self.hp <= 0:
            return 0
        if not self.max_hp:
            return None
        return max(1, min(100, round(self.hp * 100 / self.max_hp)))

    def apply_hp(self, hp_result: Any, source="sync.hp_result") -> None:
        value = _signed(hp_result)
        if value is None or value < 0:
            return
        self.hp = value
        self.hp_source = source
        self.alive = value > 0

    def apply_energy(self, energy_result: Any) -> None:
        value = _signed(energy_result)
        if value is not None:
            self.energy = value

    def apply_kill_info(self, data: dict) -> bool:
        if 'kill_info' not in data:
            return False
        # PetUtils.GetFrozenPercent reads this server threshold, not stacks × max HP.
        value = _signed(_as_dict(data['kill_info']).get('kill_at_hp', 0))
        if value is None or value < 0 or value == self.frozen_hp:
            return False
        self.frozen_hp = value
        return True

    def refresh_stats(self, inside: dict, common: dict) -> None:
        self.apply_kill_info(inside)
        base_id = inside.get("base_conf_id")
        form_changed = type(base_id) is int and base_id > 0 and base_id != self.base_conf_id
        if form_changed:
            self.base_conf_id = base_id
            self.attr_stats = {}
            self.panel_stats = {}
            self.revealed_base_stats = {}
        if "cur_passive_skill" in inside:
            passive = inside["cur_passive_skill"]
            self.runtime_feature_id = passive if type(passive) is int and passive > 0 else None
        elif form_changed:
            self.runtime_feature_id = None
        if form_changed or "cur_passive_skill" in inside:
            self._update_form_identity()
            self.first_slot_replaced = bool(self.feature_will_type)
        if (any(k in common and common[k] != getattr(self, k) for k in ("nature", "level")) or
            any(k in common and (common[k] or 0) != getattr(self, attr) for k,attr in
                (("changed_nature_pos_attr_type","nature_pos_override"),("changed_nature_neg_attr_type","nature_neg_override")))):
            self.revealed_base_stats = {}
        self.attr_stats.update(_attr_stats(inside))
        self.revealed_base_stats.update({k:v for k,v in _attr_stats(inside).items() if v > 0})
        if common.get("base_conf_id", self.base_conf_id) == self.base_conf_id:
            self.panel_stats.update(_panel_stats(common))
        if common.get("attribute_info"):
            fresh = _talent_evidence(common)
            dimensions = self.talent_evidence.setdefault("dimensions", {})
            for stat, fields in fresh["dimensions"].items():
                dimensions.setdefault(stat, {}).update(fields)
            self.talent_evidence["source"] = fresh["source"]
            if fresh.get("selected_ids") is not None:
                self.talent_evidence["selected_ids"] = fresh["selected_ids"]
        if self.attr_stats.get("hp", 0) > 0:
            self.max_hp = self.attr_stats["hp"]
        current = _current_hp(inside)
        if current is not None:
            self.apply_hp(current, "battle_attr[25]")
        if "buffs" in inside:
            self.buffs = _buffs(inside)
        if type(base_id) is int and base_id > 0:
            # The reported form already includes the reported cute layers.
            self._form_cute_layers = self.cute_stacks
        if "skill_round_data" in inside:
            slots = {s["slot"]: s for s in self.skills}
            slots.update({s["slot"]: s for s in _skill_slots(inside)})
            if [(s["slot"], s.get("skill_id")) for s in self.skills] != [(pos, slots[pos].get("skill_id")) for pos in sorted(slots)]:
                # Copied/exchanged slots may carry a different growth history.
                self.entry_count = None
                self.skill_use_history_complete = False
                self.history_incomplete_reason = '技能槽发生变化，无法确认新技能携带前的累计历史'
            self.skills = [slots[pos] for pos in sorted(slots)]
        if type(inside.get("max_energy")) is int and inside["max_energy"] > 0:
            self.max_energy = inside["max_energy"]
        for key in ("nature", "level", "energy", "height", "weight", "voice", "wear_medal_conf_id"):
            if key in common:
                setattr(self, key, common[key])
        if "speciality_id" in common:
            if common["speciality_id"] != self.speciality_id:
                self.real_speciality_ids = None
            self.speciality_id = common["speciality_id"]
        if "real_speciality_ids" in common:
            self.real_speciality_ids = deepcopy(common["real_speciality_ids"])
        if "blood_id" in common:
            self.blood_id = common["blood_id"]
        for field, attr in (("changed_nature_pos_attr_type", "nature_pos_override"), ("changed_nature_neg_attr_type", "nature_neg_override")):
            if field in common:
                setattr(self, attr, common[field] or 0)
                self.nature_override_known["up" if attr == "nature_pos_override" else "down"] = True

    def set_buff(self, buff_id: Any, layers: Any, name: str = "") -> bool:
        """按 sync 里的 ``buff_stack_result`` 更新层数；0 层表示移除。"""
        count = _signed(layers)
        if buff_id is None or count is None:
            return False
        if not name:
            name = _buff_name(buff_id)
        if count > 0:
            from lab.mark_runtime import mark_identity
            incoming = mark_identity(buff_id)
            if incoming and not incoming['independent']:
                # Ordered updates replace only the normal slot, never ordinary statuses or bard marks.
                self.buffs = [b for b in self.buffs if b.get('id') == buff_id or
                    not ((old := mark_identity(b.get('id'))) and not old['independent'] and
                         old['polarity'] == incoming['polarity'])]
        for index, buff in enumerate(self.buffs):
            if buff.get("id") == buff_id:
                if count <= 0:
                    self.buffs.pop(index)
                else:
                    buff["layers"] = count
                    if name:
                        buff["name"] = name
                return True
        if count > 0:
            entry = {"id": buff_id, "layers": count}
            if name:
                entry["name"] = name
            self.buffs.append(entry)
            return True
        return False

    @staticmethod
    def _id_matches(cast_id: Any, slot_id: Any) -> bool:
        """``skill_cast.skill_id`` 是 9 位（槽位 id × 100 + 后缀），槽位里是 7 位。

        真实样本：我方热砂 槽位 7080300 / 施法 708030000；
        敌方「应对！电磁偏转」槽位 7110421 / 施法 711042100。
        所以不能直接比，必须允许「同一基准 id」。
        """
        try:
            a = int(cast_id)
            b = int(slot_id)
        except (TypeError, ValueError):
            return False
        return a == b or a // 100 == b or b // 100 == a

    def _match_observed(self, observed: dict, slot: dict[str, Any]) -> dict[str, Any] | None:
        """在敌方已观测到的招式里找这个槽位对应的那一条。"""
        slot_id = slot.get("skill_id")
        slot_name = slot.get("skillName") or ""
        for info in observed.values():
            if self._id_matches(info.get("id"), slot_id):
                return info
            name = info.get("name") or ""
            if name and slot_name and name == slot_name:
                return info
        return None

    # ---- 萌化（退化）------------------------------------------------------
    @property
    def cute_stacks(self) -> int:
        """萌化层数。buff.json：20010791 / 21020040「萌化 · 退化到上一阶」。

        同一效果在这份数据里有两个 id，两个都出现时按最大值取，不累加。
        """
        layers = []
        for buff in self.buffs:
            if battle_data.is_cute_buff(buff.get("id")):
                value = buff.get("layers")
                layers.append(value if isinstance(value, int) and value > 0 else 1)
        return max(layers) if layers else 0

    def lowered_form(self) -> dict[str, Any]:
        """萌化后实际显示/结算的形态（退化到上一阶）。没萌化就是空。"""
        stacks = max(0, self.cute_stacks - self._form_cute_layers)
        if stacks <= 0:
            return {}
        return battle_data.lower_stage_form(self.base_conf_id, stacks)

    def effective_will_type(self) -> int | None:
        """Use the server's passive override, otherwise its reported form's trait."""
        return battle_data.will_impact_type_from_feature(self.effective_feature_info().get("feature_desc") or "")

    def effective_feature_info(self):
        if self.runtime_feature_id:
            info = battle_data.skill_info(self.runtime_feature_id)
            return {"feature_id": self.runtime_feature_id, "feature_name": info.get("name"), "feature_desc": info.get("desc")}
        return self.form

    def will_impact_slot(self) -> dict[str, Any] | None:
        """首个技能槽应该显示成对应属性的「愿力冲击」。

        素材来自特性原文（``首个技能替换为草系愿力冲击``）。实机核对结论：
        **首领化入场时首槽就已经是愿力冲击了** —— 抓包里玩家提交的技能就是
        ``7700002``，不是等打出克制之后才换。所以这里不再要求先打出克制伤害。
        """
        will_type = self.effective_will_type()
        if not will_type:
            return None
        return battle_data.will_impact_skill(will_type) or None

    def to_payload(self, *, hide_unobserved: bool, observed: dict) -> dict[str, Any]:
        moves: list[dict[str, Any]] = []
        if hide_unobserved:
            matched: list[str] = []
            for skill in self.skills:
                info = self._match_observed(observed, skill)
                if info is None or str(info.get("id")) in matched:
                    continue
                entry = dict(skill)
                # 敌方槽位里的 skill_name 常常是空的，命中后用施法报文里的名字补上
                if info.get("name"):
                    entry["skillName"] = entry["moveName"] = entry["name"] = info["name"]
                if info.get("id") is not None:
                    entry["observedSkillId"] = info["id"]
                    entry["skill_id"] = entry["skillId"] = info["id"]
                entry["observedVariants"] = list(info.get("resolved_variants", []))
                moves.append(entry)
                matched.append(str(info.get("id")))
            # 敌方进场报文经常一条技能槽都不给（真实样本：石肤蜥 skills=[]），
            # 这时没法「匹配槽位」，只能把已经打出来的招式按出现顺序列成行。
            # 仍然只显示它真用过的，没打过的技能一个都不出现。
            for info in observed.values():
                if str(info.get("id")) in matched:
                    continue
                if len(moves) >= 4:
                    break
                name = info.get("name") or ""
                moves.append({
                    "slot": len(moves) + 1,
                    "skill_id": info.get("id"),
                    "skillId": info.get("id"),
                    "skillName": name,
                    "moveName": name,
                    "name": name,
                    "energy_cost": None,
                    "observedOnly": True,
                    "observedVariants": list(info.get("resolved_variants", [])),
                })
            moves = moves[:4]
        else:
            moves = [dict(skill) for skill in self.skills[:4]]

        for move in moves:
            raw_id = move.get("skillId")
            canonical = battle_data.canonical_skill(raw_id)
            name = move.get("skillName") or move.get("name") or ""
            if canonical.get("resolved_variant_id") or name.startswith("应对！"):
                move["resolvedSkillId"] = raw_id
                if not canonical.get("canonical_issue"):
                    move["skill_id"] = move["skillId"] = canonical.get("skill_id", raw_id)
                normal_name = name.removeprefix("应对！") or canonical.get("name") or ""
                move["skillName"] = move["moveName"] = move["name"] = normal_name

        will = self.will_impact_slot()
        if will and moves and not hide_unobserved:
            slot_id = moves[0].get("skill_id")
            # 报文里第一槽本身已经是愿力冲击时，以报文为准，不再叠加。
            already = isinstance(slot_id, int) and 7700000 <= slot_id < 7700100
            if not already:
                first = dict(moves[0])
                first.update(will)
                first["slot"] = moves[0].get("slot") or 1
                first["replacedByFeature"] = self.feature_id
                first["replacedByFeatureName"] = self.effective_feature_info().get("feature_name") or ""
                moves[0] = first

        lowered = self.lowered_form()
        return {
            "memberId": f"{'my' if self.side == 0 else 'enemy'}-{self.roster_index}",
            "id": self.conf_id,
            "iconId": self.base_conf_id or self.conf_id,
            "petBaseId": self.base_conf_id,
            "originalFormId": self.original_base_conf_id,
            "petId": self.pet_id,
            "confId": self.conf_id,
            "rosterIndex": self.roster_index,
            "side": self.side,
            "petName": self.display_name(),
            "name": self.display_name(),
            "nickname": self.nickname,
            "level": self.level,
            "currentHp": self.hp,
            "hpSource": self.hp_source,
            "maxHp": self.max_hp,
            "frozenHp": self.frozen_hp,
            "hpPercent": self.hp_percent(),
            "energy": self.energy,
            "maxEnergy": self.max_energy,
            "stats": {**self.panel_stats},
            # 初始六维（进场面板，不含战斗内增减益）——雷达图用这一份。
            # Captured attack/defense fields include nature but keep percentage BUFF layers separate.
            "initialStats": {**self.panel_stats},
            "battleStats": {**self.attr_stats},
            "battleStatsBasis": "natured_base",
            "revealedBaseStats": dict(self.revealed_base_stats) if not lowered else {},
            "talentEvidence": self.talent_evidence,
            "moves": moves,
            "selectedMoves": moves,
            "slotCount": 4,
            "buffs": self.visible_buffs(),
            "battleBuffs": [dict(b) for b in self.buffs],
            "effectiveTraitId": self.effective_feature_info().get("feature_id"),
            "enteredTurn": self.entered_turn,
            "entryActionCount": self.entry_action_count,
            "entryCount": self.entry_count,
            "entryHistoryComplete": self.entry_count is not None,
            "skillUseCounts": dict(self.skill_use_counts),
            "skillTypeUseCounts": deepcopy(self.skill_type_use_counts),
            "skillUseHistoryComplete": self.skill_use_history_complete,
            "responseSuccessCount": self.response_success_count,
            "responseHistoryComplete": self.skill_use_history_complete,
            "historyStartRound": self.history_start_round,
            "historyIncompleteReason": self.history_incomplete_reason,
            "carriedSkillIds": [next((s.get("skill_id") for s in self.skills if s.get("slot") == i), 0) or 0 for i in range(1, 5)] if self.side == 0 else None,
            "carriedSkillCosts": [next((s.get("energy_cost") for s in self.skills if s.get("slot") == i), None) for i in range(1, 5)] if self.side == 0 else None,
            "bloodId": self.blood_id,
            "nature": self.nature,
            "speciality": {**battle_data.speciality_info(self.speciality_id),
                           "rawId": self.speciality_id,
                           "realIds": deepcopy(self.real_speciality_ids)},
            "physical": battle_data.physical_info(self.base_conf_id, height=self.height, weight=self.weight,
                voice=self.voice, worn_medal_id=self.wear_medal_conf_id),
            "naturePosOverride": self.nature_pos_override,
            "natureNegOverride": self.nature_neg_override,
            "natureOverrideKnown": dict(self.nature_override_known),
            "alive": self.alive,
            # 萌化：层数 + 退化后的形态。萌化会让精灵"退化到上一阶、种族资质降低"，
            # 所以名字/阶段/种族值都要按退化后算，不能还按进场时的形态。
            "cuteStacks": self.cute_stacks,
            "stage": (lowered.get("stage") if lowered else battle_data.pet_stage_info(
                self.base_conf_id).get("stage")),
            "stageFrom": (lowered.get("from_stage") if lowered else None),
            "stageName": lowered.get("name") or "",
            "stageBaseConfId": lowered.get("base_conf_id") if lowered else None,
            "stageLowered": bool(lowered),
            "stageRace": lowered.get("stats") if lowered else None,
        }

    def visible_buffs(self) -> list[dict[str, Any]]:
        """入场就带着的那批 buff 是特性/装备被动。

        以前这里只给一个 ``passive`` 标记、前端把它折叠成「被动 ×9」，玩家看不到
        任何内容 —— 名字其实都能查到（报文 buff_trigger/show_letters 里带，
        buff.json 里也有），所以一律补上名字，前端展开显示。
        """
        out: list[dict[str, Any]] = []
        for buff in self.buffs:
            item = dict(buff)
            from lab.mark_runtime import mark_identity
            identity = mark_identity(item.get('id'))
            if identity:
                item['independent'] = identity['independent']
            item["passive"] = str(item.get("id")) in self.initial_buff_ids
            if not item.get("name"):
                item["name"] = _buff_name(item.get("id"))
            if battle_data.is_cute_buff(item.get("id")):
                item["cute"] = True
            out.append(item)
        return out

    @staticmethod
    def _skill_key(skill: dict[str, Any]) -> str:
        skill_id = skill.get("skill_id")
        name = skill.get("skillName") or ""
        return f"{skill_id}" if skill_id is not None else name


class BattleTracker:
    """按顺序吃战斗消息，随时能吐出一份对局快照。"""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.battle_id: Any = None
        self.round: int | None = None
        self.max_round: int | None = None
        self.weather_id: Any = None
        self.live_weather = None
        self.core_magic_skill_ids = {0: None, 1: None}
        self.npc_id: Any = None
        self.is_npc_battle = False
        self.is_observer = False
        self.finished = False
        self.result: Any = None
        self.my_name = ""
        self.teams: dict[int, list[_Pet]] = {0: [], 1: []}
        self.active: dict[int, int] = {0: 0, 1: 0}
        self._active_confirmed = {0: False, 1: False}
        self._entry_history_complete = False
        self.observation_start_round = 1
        # 敌方已打出来的招式，**按精灵分开存**：{pet_id: {skill_key: {id, name, round}}}。
        # 以前这里是一个全局集合，换人之后新上场的精灵会继承上一只的观测结果 ——
        # 界面上表现为「换了只精灵，技能栏还是那几条」。
        self.observed_enemy_skills: dict[str, dict[str, dict[str, Any]]] = {}
        # 0x131A 先报过、0x1324 又报一次的同一手，用来去重（别把流水记两遍）。
        self._pre_casts: set[tuple] = set()
        self._pre_commands = set()
        self._cast_use_before = {}
        self._cast_response_before = {}
        self._cast_energy_before = {}
        self._pre_cast_energy = {}
        # 报文里带出来的 buff 名字（buff_trigger / show_letters），比查表更准。
        self.buff_names: dict[str, str] = {}
        self.timeline: list[dict[str, Any]] = []
        self._pet_by_id: dict[Any, _Pet] = {}
        # 双方玩家 uin。换人报文里的新精灵靠 owner_uin 判归属，判不出来的宁可不加。
        self._owners: dict[int, str | None] = {0: None, 1: None}
        # 最近收到的战斗报文（只留 opcode 与顶层键），用来在实机上定位换人走哪条。
        self.recent_raw: list[dict[str, Any]] = []
        # 报文里出现了、但归属判不出来的精灵（诊断用，不上界面）。
        self.pending_pets: list[dict[str, Any]] = []
        # 由实测伤害反推出来的面板：{pet_id: {"phyDef": [样本…], …}}。
        # These remain model-conditional candidates, never observed combat panels.
        self.learned_panels: dict[str, dict[str, list[float]]] = {}
        self.learned_panel_ranges: dict[str, dict[str, list[int]]] = {}
        self.damage_evidence: dict[str, list[dict[str, Any]]] = {}
        self._configuration_cache = {}
        self.party_life = {0: {}, 1: {}}
        self._party_dead_status = {}
        self._party_message_sequence = None
        self._party_versions = {0: None, 1: None}
        self._party_summary_stamps = {}
        self.world_star_overrides = {}
        self._turns_seen = 0
        self._cast_power_context = {}
        self._consumed_power_triggers = set()
        self._recent_cast_estimates = {}
        self._last_live_damage_preview = None

    # -- 入口 ---------------------------------------------------------
    def handle_event(self, opcode: Any, content: dict) -> bool:
        """喂一条消息；返回 True 表示快照发生了变化。"""
        text = str(opcode or "").strip().lower()
        try:
            value = int(text, 16) if text.startswith("0x") else int(text, 16)
        except (TypeError, ValueError):
            return False
        # 统一成 "0x132C"（前缀小写、十六进制大写）；否则 opcode 里带字母的
        # （0x132C 结束、0x131A 回合开始）永远匹配不上表，对局结束都不结算。
        code = f"0x{value:04X}"
        kind = BATTLE_OPCODES.get(code)
        if kind is None:
            return False
        content = _as_dict(content)
        if kind == "battle_enter":
            return self._on_enter(content)
        message_battle = (content.get("battle_id")
                          or _as_dict(content.get("state_info")).get("battle_id")
                          or _as_dict(content.get("settle_info")).get("battle_id"))
        if message_battle is not None and str(message_battle) != str(self.battle_id):
            return False
        if not self.teams[0] and not self.teams[1]:
            # 没有开场信息就先不臆造队伍。
            return False
        # 每条报文都扫一遍有没有「没见过的精灵」：换人就是靠这里补进来的。
        self._party_message_sequence = _as_dict(content.get("perform_cmd")).get("seq_num", content.get("data_seq_num"))
        absorbed = self._absorb_pets(content)
        self._remember_raw(code, kind, content)
        changed = False
        if kind == "round_start":
            changed = self._on_round_start(content)
        elif kind == "cmd_sync":
            changed = self._on_cmd_sync(content)
        elif kind == "perform_start":
            changed = self._on_perform(content)
        elif kind == "battle_finish":
            changed = self._on_finish(content)
        return changed or absorbed

    def _remember_raw(self, code: str, kind: Any, content: dict) -> None:
        """留一小段原始结构，用来在实机上定位「换人到底走哪条报文」。

        只记 opcode、顶层键、以及哪些位置出现了 battle_inside_pet_info，不存全量内容。
        """
        inside_paths = []
        for inside, _common in _walk_pet_infos(content):
            inside_paths.append({
                "pet_id": inside.get("pet_id"),
                "owner_uin": inside.get("owner_uin"),
                "conf_name": inside.get("conf_name"),
                "pet_change_status": inside.get("pet_change_status"),
                "pos": inside.get("pos"),
            })
            if len(inside_paths) >= 8:
                break
        self.recent_raw.append({
            "opcode": code,
            "kind": kind,
            "round": self.round,
            "top_keys": sorted(content.keys())[:14],
            "pets": inside_paths,
        })
        if len(self.recent_raw) > 60:
            del self.recent_raw[:-60]

    # -- 各消息处理 ---------------------------------------------------
    def _on_enter(self, content: dict) -> bool:
        init = _as_dict(content.get("init_info"))
        if not init:
            return False
        # pet_id is reused between battles (e.g. 401); every battle owns its observations.
        self.reset()
        self.battle_id = init.get("battle_id")
        self._party_message_sequence = content.get("data_seq_num")
        self.max_round = content.get("max_round")
        self.weather_id = content.get("weather_id")
        self.round = content.get("round") or 1
        self.observation_start_round = self.round
        self._entry_history_complete = self.round == 1 and not _as_dict(init.get("observe_battle")).get("is_observer")
        self.is_observer = bool(_as_dict(init.get('observe_battle')).get('is_observer'))
        # 野外/NPC 对局带 npc_id；玩家对战（PVP）没有。PVP 不触发暴击，
        # 所以这条判据直接决定 HUD 要不要把暴击值摆出来。
        self.npc_id = content.get("npc_id") or None
        self.is_npc_battle = bool(_as_list(self.npc_id) if isinstance(self.npc_id, list) else self.npc_id)
        self.teams = {0: [], 1: []}
        self._pet_by_id = {}
        for side_key, side in (("player_team", 0), ("enemy_team", 1)):
            for member in _as_list(init.get(side_key)):
                member = _as_dict(member)
                magic = _as_dict(member.get("magic_skill_info"))
                if magic.get("skill_id"):
                    self.core_magic_skill_ids[side] = magic["skill_id"]
                base = _as_dict(member.get("base"))
                if self._owners[side] is None and base.get("role_uin") is not None:
                    self._owners[side] = str(base.get("role_uin"))
                self._update_party_life(side, _as_dict(member.get("role_addi_info")))
                if side == 0 and not self.my_name:
                    self.my_name = _hex_name(base.get("name"))
                for index, raw_pet in enumerate(_as_list(member.get("pets"))):
                    raw_pet = _as_dict(raw_pet)
                    pet = _Pet(
                        side=side,
                        roster_index=index,
                        inside=_as_dict(raw_pet.get("battle_inside_pet_info")),
                        common=_as_dict(raw_pet.get("battle_common_pet_info")),
                        assume_full=self.round == 1 and not _as_dict(init.get("observe_battle")).get("is_observer"),
                    )
                    self.teams[side].append(pet)
                    pet.entry_count = 0 if self._entry_history_complete else None
                    pet.skill_use_history_complete = self.round == 1 and not _as_dict(init.get("observe_battle")).get("is_observer")
                    self._set_history_origin(pet)
                    if _pos_is_field(_as_dict(raw_pet.get("battle_inside_pet_info")).get("pos")):
                        self.active[side] = pet.roster_index
                        self._active_confirmed[side] = True
                        if self.round == 1:
                            pet.entered_turn, pet.entry_action_count = 1, 0
                        if pet.entry_count is not None:
                            pet.entry_count += 1
                    if pet.pet_id is not None:
                        # relay 会把 64 位整数序列化成字符串，键统一用 str，查表时也转 str。
                        self._pet_by_id[str(pet.pet_id)] = pet
        self.timeline = [{
            "round": self.round,
            "kind": "battle_enter",
            "text": (f"进入对局 · 我方 {len(self.teams[0])} 只 / 敌方 {len(self.teams[1])} 只"
                     if self.is_npc_battle else "进入对局 · 我方 6 只 / 敌方 6 只"),
            "observedRosterCounts": {"my": len(self.teams[0]), "enemy": len(self.teams[1])},
        }]
        # 进场报文里对方往往只给「当前在场」那一只（真实样本：6 打 1），
        # 所以整队要靠后续报文慢慢补 —— 见 _absorb_pets。
        self._absorb_pets(content)
        self._anchor_party_deaths()
        return True

    def _anchor_party_deaths(self, side=None):
        for pet in self._pet_by_id.values():
            if (side is None or pet.side == side) and type(pet.hp) is int:
                self._party_dead_status[str(pet.pet_id)] = pet.hp == 0

    def _update_party_life(self, side, info):
        """Role snapshots are absolute totals, independent of hidden roster details."""
        current = self.party_life[side]
        candidate = dict(current)
        fields = {"pet_num": "total", "dead_pet_num": "dead", "random_pet_num": "randomTotal", "dead_random_pet_num": "randomDead"}
        seq, version = self._party_message_sequence, self._party_versions[side]
        if type(seq) is int and type(version) is int and seq < version:
            return False
        stamp = (seq, tuple((key, info[key]) for key in fields if key in info))
        if type(seq) is int and self._party_summary_stamps.get(side) == stamp:
            return False
        for key, field in fields.items():
            if key in info:
                value = info[key]
                if type(value) is not int or not 0 <= value <= 6:
                    current.update(dead=None, issue="队伍存活计数无效，等待后续同步")
                    return True
                candidate[field] = value
        if not any(key in info for key in fields):
            return False
        if candidate.get("dead", 0) > candidate.get("total", 6):
            current.update(dead=None, issue="队伍倒下数超过总数，等待后续同步")
            return True
        candidate.update(source="role_addi_info/role_simple", issue=None)
        self.party_life[side] = candidate
        self._party_versions[side] = seq if type(seq) is int else version
        self._party_summary_stamps[side] = stamp
        if "dead_pet_num" in info:
            self._anchor_party_deaths(side)
        return candidate != current

    def _record_party_death(self, pet, dead):
        seq, version = self._party_message_sequence, self._party_versions[pet.side]
        if type(seq) is int and type(version) is int and seq < version:
            return False
        key = str(pet.pet_id)
        old = self._party_dead_status.get(key)
        self._party_dead_status[key] = dead
        if old == dead:
            return False
        self._party_versions[pet.side] = seq if type(seq) is int else version
        current = self.party_life[pet.side]
        count = current.get("dead")
        if type(count) is int and (dead or old is True):
            count += 1 if dead else -1
            if not 0 <= count <= current.get("total", 6):
                current.update(dead=None, issue="队伍倒下变化与总数冲突，等待后续绝对同步")
            else:
                current.update(dead=count, source="role_totals+observed_death/revival")
        return True

    def _party_counts_context(self, side):
        if not any(self.party_life[s] for s in (0, 1)):
            return {}
        counts = {}
        for label, s in (("self", side), ("opponent", 1 - side)):
            life = self.party_life[s]
            if life.get("randomTotal", 0):
                continue  # The contribution of random pets to these mechanics is unverified.
            if type(life.get("dead")) is int:
                counts[label] = life["dead"]
            elif not life.get("issue") and len(self.teams[s]) == 6 and all(type(p.hp) is int for p in self.teams[s]):
                counts[label] = sum(p.hp == 0 for p in self.teams[s])
        return {"faintedCounts": counts}

    def _absorb_pets(self, node: Any) -> bool:
        """把报文里出现的、还没登记过的精灵收进队伍。

        PVP 里对手的完整阵容是隐藏信息，进场只下发在场那只；换人之后新精灵才随
        报文出现。以前只认进场报文，于是「对面换了精灵，面板还是上一只」。
        归属靠 ``owner_uin`` 与双方玩家 uin 比对，对不上就不加（绝不猜）。
        """
        changed = False
        for inside, common in _walk_pet_infos(node):
            pet_id = inside.get("pet_id")
            if pet_id is None or str(pet_id) in self._pet_by_id:
                continue
            owner = inside.get("owner_uin")
            owner_key = str(owner) if owner is not None else None
            side = None
            # **只收敌方**。观战样本里 owner_uin=0 同时出现在双方精灵上
            # （我方宠物 owner_uin=0，对方在场精灵也是 0），按 owner 判 side 会
            # 把对方换上来的精灵塞进我方队伍、还把「我方在场」改成它 —— 实机出过。
            # 我方六只进场就齐了，换人时 pet_id 本来就在队伍里，不需要"吸收"。
            if inside.get("is_player_enemy") is True:
                side = 1
            elif owner_key and self._owners[1] not in (None, "0") and owner_key == self._owners[1]:
                side = 1
            elif _same_band_as_enemy(pet_id, self.teams[1]):
                # 最后一条启发式：对手的 pet_id 与已有敌方宠物同一量级（真实样本 401~406）。
                side = 1
            if side is None:
                self.pending_pets.append({
                    "pet_id": pet_id,
                    "owner_uin": owner_key,
                    "conf_name": inside.get("conf_name"),
                    "pos": inside.get("pos"),
                    "round": self.round,
                })
                del self.pending_pets[:-20]
                continue
            pet = _Pet(side=side, roster_index=len(self.teams[side]), inside=inside, common=common, assume_full=False)
            pet.entry_count = 0 if self._entry_history_complete else None
            pet.skill_use_history_complete = self._entry_history_complete
            self._set_history_origin(pet)
            # 同一只精灵可能已经以别的 pet_id 占了一个位（复活的场合），按 pet_id 去重即可。
            self.teams[side].append(pet)
            self._pet_by_id[str(pet_id)] = pet
            if type(pet.hp) is int:
                self._party_dead_status[str(pet_id)] = pet.hp == 0
            changed = True
            # Discovery scans the entire packet; only ordered switch/sync items set the active pet.
            self.timeline.append({
                "round": self.round,
                "kind": "pet_seen",
                "side": side,
                "petName": pet.display_name(),
                "text": f"发现{'我方' if side == 0 else '敌方'}精灵 {pet.display_name()}",
            })
        return changed

    def _on_round_start(self, content: dict) -> bool:
        state = _as_dict(content.get("state_info"))
        round_no = state.get("round")
        if isinstance(round_no, int):
            self._set_round(round_no)
        changed = isinstance(round_no, int)
        # Round headers carry complete current attributes independently of perform_cmd.
        for key, node in content.items():
            if key == "perform_cmd":
                continue
            for inside, common in _walk_pet_infos(node):
                pet = self._pet_by_id.get(str(inside.get("pet_id")))
                if pet is not None:
                    pet.refresh_stats(inside, common)
                    changed = True
                    if _pos_is_field(inside.get("pos")):
                        changed = self._confirm_active(pet) or changed
        # 0x131A（回合开始）也带 perform_cmd：野外/NPC 的预演动作走这条，
        # 只认 0x1324 会把野外对手的出手整段漏掉（HUD 上永远是"未观测"）。
        cmd = _as_dict(content.get("perform_cmd"))
        token = _perform_token(cmd, self.round)
        if token:
            self._pre_commands.add(token)
        self._cast_use_before.clear()
        self._cast_response_before.clear()
        self._cast_energy_before.clear()
        self._prepare_power_context(cmd)
        for item in _execution_order(cmd.get("perform_info")):
            item = _as_dict(item)
            if self._apply_perform_item(item, from_round_start=True):
                changed = True
        return changed

    def _on_cmd_sync(self, content: dict) -> bool:
        req = _as_dict(content.get("req"))
        cast = _as_dict(req.get("cast_skill"))
        caster_id = cast.get("caster_pet_id")
        if caster_id is None:
            return False
        pet = self._pet_by_id.get(str(caster_id))
        if pet is None:
            return False
        # 玩家自己的选择不写进 timeline（避免把"想放什么"当成"打出了什么"），
        # 但对手的选择同样不写 —— 只有 perform 里真正结算的才算观测。
        return False

    def _on_perform(self, content: dict) -> bool:
        cmd = _as_dict(content.get("perform_cmd"))
        round_no = cmd.get("round")
        if isinstance(round_no, int):
            self._set_round(round_no)
        changed = False
        token = _perform_token(cmd, self.round)
        if token in self._pre_commands:
            self._pre_commands.discard(token)
            self._pre_casts = {signature for signature in self._pre_casts if signature[0] != self.round}
            self._pre_cast_energy = {signature: value for signature, value in self._pre_cast_energy.items() if signature[0] != self.round}
            return False  # The complete ordered packet was already applied at round start.
        self._cast_use_before.clear()
        self._cast_response_before.clear()
        self._cast_energy_before.clear()
        self._prepare_power_context(cmd)
        for item in _execution_order(cmd.get("perform_info")):
            item = _as_dict(item)
            changed = self._apply_perform_item(item) or changed
        if changed and isinstance(round_no, int) and self._turns_seen != round_no:
            self._turns_seen = round_no
        return changed

    def _prepare_power_context(self, cmd):
        self._cast_power_context.clear()
        self._consumed_power_triggers = {
            (str(trigger.get("caster_id")), trigger.get("buff_id"))
            for item in _as_list(cmd.get("perform_info"))
            if (trigger := _as_dict(_as_dict(item).get("buff_trigger"))).get("buff_id") == 20230350
        }

    def _remember_power_context(self, caster, cast, skill_id):
        # Replay 2079 proves heat-up is consumed before its single hit is reported.
        # Keep only this source-bound modifier, never a stale copy of all combat state.
        buffs = [deepcopy(b) for b in caster.buffs if b.get("id") == 20230350 and b.get("layers", 0) > 0]
        if not buffs or (str(caster.pet_id), 20230350) not in self._consumed_power_triggers:
            return
        from lab import live_damage
        try:
            for target_id in _as_list(cast.get("target_id")):
                target = self._pet_by_id.get(str(target_id))
                if target is not None and live_damage.skill_math(skill_id, caster.base_conf_id, target.base_conf_id).get("hits") == SINGLE_HIT:
                    self._cast_power_context[(str(caster.pet_id), str(skill_id), str(target_id))] = (buffs, None)
            snapshot = self.snapshot()["runtime"]
            pets = snapshot["myTeam"] + snapshot["enemyTeam"]
            attacker = deepcopy(next(p for p in pets if p["petId"] == caster.pet_id))
            carried = [m for m in attacker.get('moves', []) if m.get('skillId') == skill_id]
            attacker['moves'] = carried if len(carried) == 1 else [{'slot': None, 'skillId': skill_id, 'observedOnly': True}]
            for target_id in _as_list(cast.get("target_id")):
                defender = next((p for p in pets if str(p["petId"]) == str(target_id)), None)
                if defender is None:
                    continue
                estimate = live_damage.estimate_incoming(attacker, defender)[0]
                if estimate.get("reason") or estimate.get("hits") != 1:
                    if estimate.get("hits", 1) != 1:
                        self._cast_power_context.pop((str(caster.pet_id), str(skill_id), str(target_id)), None)
                    continue  # Unknown panels do not erase a source-proven consumed modifier.
                preview = {"round": self.round, "targetName": defender["petName"],
                           "normalMin": estimate["normalMin"], "normalMax": estimate["normalMax"]}
                self._cast_power_context[(str(caster.pet_id), str(skill_id), str(target_id))] = (buffs, preview)
        except (OSError, ValueError, KeyError, TypeError, StopIteration):
            return  # A missing preview must not prevent authoritative packet consumption.

    def _apply_perform_item(self, item: dict, *, from_round_start: bool = False) -> bool:
        changed = False
        model = _as_dict(item.get("change_model"))
        if model:
            model_id = model.get("pet_id")
            inside = _as_dict(_as_dict(model.get("pet_info")).get("battle_inside_pet_info"))
            pet = self._pet_by_id.get(str(model_id))
            if pet is not None and str(inside.get("pet_id")) == str(model_id):
                old_id, old_name = pet.base_conf_id, pet.display_name()
                common = _as_dict(_as_dict(model.get("pet_info")).get("battle_common_pet_info"))
                pet.refresh_stats(inside, common)
                changed = True
                if old_id != pet.base_conf_id:
                    self.timeline.append({"round": self.round, "kind": "form_change", "side": pet.side,
                        "petId": pet.pet_id, "oldFormId": old_id, "newFormId": pet.base_conf_id,
                        "petName": pet.display_name(), "text": old_name + " → " + pet.display_name()})
            else:
                self.pending_pets.append({"round": self.round, "reason": "形态变更ID缺失或不一致", "pet_id": model_id})
                del self.pending_pets[:-20]
        # Supply after a knockout is a separate event from voluntary change_pet.
        for supplied in _as_list(_as_dict(item.get("supply_pet")).get("pet_infos")):
            supplied = _as_dict(supplied)
            pet_id = supplied.get("pet_id")
            inside = _as_dict(_as_dict(supplied.get("pet_info")).get("battle_inside_pet_info"))
            if inside.get("pet_id") is not None and str(inside["pet_id"]) != str(pet_id):
                continue
            pet = self._pet_by_id.get(str(pet_id))
            if pet is not None:
                for current_inside, common in _walk_pet_infos(supplied.get("pet_info")):
                    if str(current_inside.get("pet_id")) == str(pet_id):
                        pet.refresh_stats(current_inside, common)
            if pet is not None and _pos_is_field(supplied.get("pet_pos")):
                changed = self._confirm_active(pet) or changed
        # Full server replacements carry authoritative positions too (WriteDataUpdate/WritePetInfo).
        for node in (item.get("data_update"), _as_dict(item.get("sync_data")).get("pet_info")):
            for inside, common in _walk_pet_infos(node):
                pet = self._pet_by_id.get(str(inside.get("pet_id")))
                if pet is not None:
                    pet.refresh_stats(inside, common)
                    changed = True
                    if _pos_is_field(inside.get("pos")):
                        changed = self._confirm_active(pet) or changed
        change = _as_dict(item.get("change_pet"))
        if change:
            # BattleChangePetPlayer: battle_pet_id is New; rest_pet_id is Old.
            incoming_id = change.get("battle_pet_id")
            info_id = _as_dict(_as_dict(change.get("battle_pet_info")).get("battle_inside_pet_info")).get("pet_id")
            if incoming_id is not None and (info_id is None or str(info_id) == str(incoming_id)):
                pet = self._pet_by_id.get(str(incoming_id))
                if pet is not None:
                    for inside, common in _walk_pet_infos(change.get("battle_pet_info")):
                        if str(inside.get("pet_id")) == str(incoming_id):
                            pet.refresh_stats(inside, common)
                    changed = self._confirm_active(pet) or changed
            else:
                self.pending_pets.append({"round": self.round, "reason": "换人通知的入场ID缺失或与精灵信息冲突",
                                          "battle_pet_id": incoming_id, "info_pet_id": info_id})
                del self.pending_pets[:-20]
        cast = _as_dict(item.get("skill_cast"))
        if cast:
            caster = self._pet_by_id.get(str(cast.get("caster_id")))
            skill_id = cast.get("skill_id")
            skill_name = cast.get("skill_name") or ""
            skill_info = battle_data.canonical_skill(skill_id)
            is_move = skill_info.get("category") == 1
            response_success = is_move and (skill_name.startswith('应对！') or
                battle_data.skill_info(skill_id).get('name', '').startswith('应对！'))
            restraint = _as_list(cast.get("restraint_type"))
            # 0x131A 与 0x1324 可能都报同一次出手，只记一次流水，避免时间线重复。
            signature = (self.round, cast.get("caster_id"), skill_id, skill_name)
            duplicate = False
            if from_round_start:
                self._pre_casts.add(signature)
            elif signature in self._pre_casts:
                self._pre_casts.discard(signature)
                duplicate = True
            if caster is not None:
                # A delayed/borrowed cast must not override an explicit entry/switch position.
                if is_move:
                    history_id = str(skill_info["skill_id"])
                    if not duplicate:
                        self._remember_power_context(caster, cast, skill_info["skill_id"])
                    energy_key = (str(caster.pet_id), history_id)
                    self._cast_energy_before[energy_key] = self._pre_cast_energy.pop(signature, caster.energy) if duplicate else caster.energy
                    if from_round_start:
                        self._pre_cast_energy[signature] = caster.energy
                    count = caster.skill_use_counts.get(history_id, 0)
                    self._cast_use_before[(str(caster.pet_id), history_id)] = max(0, count - 1) if duplicate else count
                    if not duplicate:
                        self._cast_response_before[(str(caster.pet_id), history_id)] = caster.response_success_count
                        if response_success:
                            caster.response_success_count += 1
                    if not duplicate:
                        caster.skill_use_counts[history_id] = count + 1
                        from lab import weather_runtime
                        skill_type = next((name + '系' for name, code in battle_data.TYPE_CODES.items()
                                           if code == skill_info.get('type_code')), None)
                        skill_type = weather_runtime.resolved_skill_type(self.live_weather, skill_info['skill_id'], skill_type)
                        if skill_type:
                            types = caster.skill_type_use_counts.setdefault(history_id, {})
                            types[skill_type] = types.get(skill_type, 0) + 1
                        else:
                            caster.skill_use_history_complete = False
                if is_move and not self._active_confirmed[caster.side]:
                    self._confirm_active(caster)
                # Passive/buff casts also use skill_cast; keep their timeline, not a carried slot.
                if caster.side == 1 and is_move:
                    canonical_id = skill_info.get("skill_id")
                    normal_name = skill_name.removeprefix("应对！") if skill_name else skill_info.get("name") or ""
                    key = f"name:{normal_name}:{skill_info.get('type_code')}"
                    # 归到**出手的那只精灵**名下。换人后新精灵的观测集合是空的，
                    # 旧精灵换回来仍能看到它自己打过什么。
                    bucket = self.observed_enemy_skills.setdefault(str(caster.pet_id), {})
                    if key and key not in bucket:
                        bucket[key] = {
                            "id": canonical_id,
                            "name": normal_name,
                            "round": self.round,
                            "resolved_variants": [],
                        }
                        changed = True
                    elif not skill_name.startswith("应对！") and not skill_info.get("resolved_variant_id"):
                        bucket[key]["id"] = canonical_id
                    variants = bucket[key].setdefault("resolved_variants", [])
                    if skill_id not in variants:
                        variants.append(skill_id)
                # 「造成克制伤害后，首个技能替换为X系愿力冲击」——
                # restraint_type 首值非 0 就是这次打出了克制，只在这一刻置位。
                if caster.feature_will_type and not caster.first_slot_replaced and restraint:
                    first = restraint[0]
                    if isinstance(first, int) and first > 0:
                        caster.first_slot_replaced = True
                        changed = True
                if not duplicate:
                    if is_move and caster.entry_action_count is not None:
                        caster.entry_action_count += 1
                    if is_move:
                        from lab import weather_runtime
                        self.live_weather, _events = weather_runtime.apply_weather_skill(self.live_weather, skill_info["skill_id"], self.round,
                            response_success=response_success)
                    self.timeline.append({
                        "round": self.round,
                        "kind": "skill_cast",
                        "isMove": is_move,
                        "petId": caster.pet_id,
                        "side": caster.side,
                        "petName": caster.display_name(),
                        "skillId": skill_id,
                        "skillName": skill_name,
                        "text": f"{'我方' if caster.side == 0 else '敌方'} {caster.display_name()} 使用 {skill_name}",
                    })
                changed = True
        buff_change = _as_dict(item.get("buff_change"))
        buff_target = self._pet_by_id.get(str(buff_change.get("target_id")))
        if buff_target is not None:
            buff_info = _as_dict(buff_change.get("buff_info"))
            layers = 0 if buff_change.get("type") == 3 else buff_info.get("stack")
            changed = buff_target.set_buff(buff_change.get("buff_id"), layers, buff_change.get("buff_name") or buff_info.get("buff_name") or "") or changed
        damage = _as_dict(item.get("damage_info"))
        observation_context = None
        damage_event = None
        cast_preview = None
        if damage:
            target = self._pet_by_id.get(str(damage.get("target_id")))
            caster = self._pet_by_id.get(str(damage.get("caster_id")))
            if caster is not None and target is not None:
                from lab.live_damage import _pet_types
                roster = {side: [{"member_id": str(p.pet_id), "types": _pet_types(p.to_payload(hide_unobserved=True, observed={})), "hp": p.hp, "cute_layers": p.cute_stacks}
                                 for p in team] for side, team in self.teams.items()}
                observation_context = {}
                for label, member in (("attacker", caster), ("defender", target)):
                    payload = member.to_payload(hide_unobserved=member.side == 1, observed={})
                    self._apply_stat_policy(payload)
                    payload["liveContext"] = {"turn": self.round, "weather": self.live_weather,
                        "rosters": {"self": roster[member.side], "opponent": roster[1 - member.side]},
                        **self._party_counts_context(member.side)}
                    if label == "attacker" and type(payload.get("entryActionCount")) is int:
                        payload["entryActionCount"] = max(0, payload["entryActionCount"] - 1)
                    if label == "attacker":
                        source_id = str(battle_data.canonical_skill(damage.get("source_id")).get("skill_id", damage.get("source_id")))
                        before = self._cast_use_before.get((str(member.pet_id), source_id))
                        if before is not None:
                            payload["skillUseCounts"][source_id] = before
                        response_before = self._cast_response_before.get((str(member.pet_id), source_id))
                        if response_before is not None:
                            payload['responseSuccessCount'] = response_before
                        energy_key = (str(member.pet_id), source_id)
                        if energy_key in self._cast_energy_before:
                            payload["energyBeforeCast"] = self._cast_energy_before[energy_key]
                        saved = self._cast_power_context.pop((str(member.pet_id), source_id, str(target.pet_id)), None)
                        if saved is not None:
                            consumed, cast_preview = saved
                            for field in ("buffs", "battleBuffs"):
                                # New buffs and current defender state remain authoritative.
                                present = {b.get("id") for b in payload.get(field, [])}
                                payload.setdefault(field, []).extend(deepcopy(b) for b in consumed if b["id"] not in present)
                    observation_context[label] = payload
            if target is not None:
                source_id = damage.get("source_id")
                source_info = battle_data.skill_info(source_id) or battle_data.skill_info(source_id // 100 if isinstance(source_id, int) else None)
                damage_event = {
                    "round": self.round,
                    "kind": "damage",
                    "side": caster.side if caster is not None else None,
                    "casterName": caster.display_name() if caster is not None else "",
                    "targetName": target.display_name(),
                    "casterPetId": caster.pet_id if caster is not None else None,
                    "targetPetId": target.pet_id,
                    "petName": target.display_name(),
                    "skillId": damage.get("source_id"),
                    "skillName": source_info.get("name") or _buff_name(source_id),
                    # is_critical 是列表（多目标各一位），要取元素本身：
                    # 直接 bool(列表) 恒为真，会把每一击都当成暴击。
                    "critical": bool((_as_list(damage.get("is_critical")) or [False])[0]),
                    "hit": bool(damage.get("is_hit")),
                    "text": f"{target.display_name()} 受到伤害"
                            + ("（未命中）" if damage.get("is_hit") is False else ""),
                }
                self.timeline.append(damage_event)
                if cast_preview is not None:
                    damage_event["castEstimate"] = deepcopy(cast_preview)
                    canonical = battle_data.canonical_skill(damage.get("source_id")).get("skill_id")
                    self._recent_cast_estimates[(str(caster.pet_id), canonical)] = deepcopy(cast_preview)
                changed = True
        sync = _as_dict(item.get("sync_data"))
        # buff_trigger / show_letters 这两类项带 buff_name + buff_desc，
        # 是名字最可靠的来源（buff.json 只有基础名，报文里有「亲和【弱】」这种带后缀的）。
        for source in (_as_dict(item.get("buff_trigger")), _as_dict(item.get("show_letters"))):
            buff_id = source.get("buff_id")
            buff_name = source.get("buff_name") or ""
            if buff_id is None or not buff_name:
                continue
            self.buff_names[str(buff_id)] = buff_name
            for pet in self.teams[0] + self.teams[1]:
                for buff in pet.buffs:
                    if str(buff.get("id")) == str(buff_id):
                        buff["name"] = buff_name
            changed = True
        for entry in _as_list(sync.get("pet_sync_info")):
            entry = _as_dict(entry)
            pet = self._pet_by_id.get(str(entry.get("pet_id")))
            if pet is None:
                continue
            changed = pet.apply_kill_info(entry) or changed
            if _pos_is_field(entry.get("pos")):
                changed = self._confirm_active(pet) or changed
            hp_result = entry.get("hp_result")
            if hp_result is not None:
                pet.apply_hp(hp_result)
                changed = True
            elif entry.get("damage_result") is not None and pet.hp is not None:
                dealt = _signed(entry.get("damage_result")) or 0
                pet.apply_hp(pet.hp - dealt)
                changed = True
            energy_result = entry.get("energy_result")
            if energy_result is not None:
                pet.apply_energy(energy_result)
                changed = True
            # type=2 的同步项就是 buff 层数变化（含名称），HUD 的状态行靠它动起来。
            if entry.get("buff_id") is not None and entry.get("buff_stack_result") is not None:
                if pet.set_buff(entry.get("buff_id"), entry.get("buff_stack_result"),
                                str(entry.get("buff_name") or "")):
                    changed = True
                    self.timeline.append({
                        "round": self.round,
                        "kind": "buff",
                        "side": pet.side,
                        "petName": pet.display_name(),
                        "buffId": entry.get("buff_id"),
                        "buffName": entry.get("buff_name") or "",
                        "layers": _signed(entry.get("buff_stack_result")),
                        "text": f"{pet.display_name()} 状态变化："
                                f"{entry.get('buff_name') or entry.get('buff_id')}"
                                f" ×{_signed(entry.get('buff_stack_result'))}",
                    })
            if item.get("type") == 4 and damage_event is not None and str(pet.pet_id) == str(damage.get("target_id")):
                if entry.get("damage_result") is not None:
                    damage_event["damageFinal"] = _signed(entry["damage_result"])
                if entry.get("original_damage") is None:
                    continue
                damage_event["damage"] = _signed(entry["original_damage"])
                damage_info = _as_dict(item.get("damage_info"))
                self._learn_panel(
                    caster=self._pet_by_id.get(str(damage_info.get("caster_id"))),
                    target=pet,
                    skill_id=damage_info.get("source_id"),
                    damage=_signed(entry.get("original_damage")),
                    critical=bool((_as_list(damage_info.get("is_critical")) or [False])[0]),
                    resolved_kind=damage_info.get("dam_type"),
                    observation_context=observation_context,
                )
        dead_info = _as_dict(item.get("dead_info"))
        dead_pet = self._pet_by_id.get(str(dead_info.get("target_id")))
        if dead_pet is not None and dead_info.get("dead_type") == 0:
            changed = self._record_party_death(dead_pet, True) or changed
            dead_pet.apply_hp(0, "dead_info")
        # Explicit positive-HP updates after a recorded death are revivals, not new slots.
        for pet in self._pet_by_id.values():
            if self._party_dead_status.get(str(pet.pet_id)) is True and type(pet.hp) is int and pet.hp > 0:
                changed = self._record_party_death(pet, False) or changed
        update = _as_dict(item.get("data_update"))
        if "role_simple" in update:
            side = next((s for s, owner in self._owners.items() if owner is not None and owner == str(update.get("uin"))), None)
            if side is not None:
                changed = self._update_party_life(side, _as_dict(update["role_simple"])) or changed
        return changed

    def _set_history_origin(self, pet: _Pet) -> None:
        pet.history_start_round = self.observation_start_round
        pet.history_incomplete_reason = ('' if self._entry_history_complete else
            f'中途观战（第{self.observation_start_round}回合接入）' if self.observation_start_round > 1 else
            '第1回合观战接入，尚未确认已包含开场及此前所有行动')

    def _confirm_active(self, pet: _Pet) -> bool:
        was_confirmed = self._active_confirmed[pet.side]
        self._active_confirmed[pet.side] = True
        if not was_confirmed or self.active[pet.side] != pet.roster_index:
            pet.entered_turn, pet.entry_action_count = self.round, 0
            if pet.entry_count is not None:
                pet.entry_count += 1
        if self.active[pet.side] == pet.roster_index:
            return False
        self.active[pet.side] = pet.roster_index
        self.timeline.append({"round": self.round, "kind": "switch", "side": pet.side,
                              "petId": pet.pet_id, "petName": pet.display_name(),
                              "text": f"{'我方' if pet.side == 0 else '敌方'} {pet.display_name()} 上场"})
        return True

    def _set_round(self, round_no):
        if isinstance(self.round, int) and round_no > self.round and self.live_weather:
            from lab.weather_runtime import advance_weather
            for turn in range(self.round, round_no):
                self.live_weather, _members, _events = advance_weather(self.live_weather, {}, turn)
                if self.live_weather is None:
                    break
        self.round = round_no

    # -- 由实测伤害反推面板 -------------------------------------------
    def _learn_panel(self, *, caster, target, skill_id, damage, critical: bool, resolved_kind=None, observation_context=None) -> None:
        """一次真实结算 → 把「对方那一侧的面板」反解出来。

        我方打对方：攻方面板已知 → 解对方防御；
        对方打我：我方防御已知 → 解对方攻击。
        只在校验通过时记样本（多段技能只取单段，避免把总和当成一次）。
        """
        if caster is None or target is None or skill_id is None:
            return
        try:
            damage_value = float(damage)
        except (TypeError, ValueError):
            return
        if damage_value <= 0:
            if caster.side != target.side:
                enemy = target if caster.side == 0 else caster
                event = {"turn": self.round, "skill_id": skill_id, "damage": damage_value, "form_id": enemy.base_conf_id,
                         "blocker": "零伤害可能来自免疫、未命中或其他机制，不能唯一约束攻防"}
                bucket = self.damage_evidence.setdefault(str(enemy.pet_id), [])
                if event not in bucket:
                    bucket.append(event)
                    self._configuration_cache.pop(str(enemy.pet_id), None)
            return
        if caster.side != target.side:
            from lab.live_inference import damage_observation
            enemy = target if caster.side == 0 else caster
            try:
                pet_id, event = damage_observation(caster, target, skill_id, damage_value, critical, self.round, resolved_kind,
                                                  context=observation_context)
            except (OSError, ValueError, KeyError, ImportError, TypeError) as error:
                pet_id, event = enemy.pet_id, {"turn": self.round, "skill_id": skill_id, "damage": damage_value,
                    "form_id": enemy.base_conf_id, "blocker": str(error)}
            bucket = self.damage_evidence.setdefault(str(pet_id), [])
            if event not in bucket:
                bucket.append(event)
                self._configuration_cache.pop(str(pet_id), None)
        if self.is_npc_battle:
            return  # World constraints already use the shared level-aware forward query.
        try:
            from lab import live_damage
            mathinfo = live_damage.skill_math(skill_id, caster.base_conf_id, target.base_conf_id)
        except (OSError, ValueError, KeyError, ImportError):   # 规则不可用就不学
            return
        if mathinfo.get("reason") or mathinfo.get("damageRule") not in (None, 0, 15):
            return
        kind = mathinfo.get("kind")
        if kind == "physical":
            atk_key, def_key = "phyAtk", "phyDef"
        elif kind == "magical":
            atk_key, def_key = "magAtk", "magDef"
        elif (caster.attr_stats.get("phyAtk") or 0) > 0 and (caster.attr_stats.get("magAtk") or 0) > 0:
            if (caster.attr_stats.get("phyAtk") or 0) >= (caster.attr_stats.get("magAtk") or 0):
                atk_key, def_key = "phyAtk", "phyDef"
            else:
                atk_key, def_key = "magAtk", "magDef"
        else:
            return  # Unknown dual attacks cannot determine the higher-attack branch.
        # Each damage_info sync contains one segment, not the full skill's hit total.
        per_hit = damage_value
        if caster.side == 0 and (caster.attr_stats.get(atk_key) or 0) > 0:
            # 我方 → 对方：解对方那一项防御。
            estimate = live_damage.panel_from_hit(
                attack=float(caster.attr_stats[atk_key]), power=mathinfo["power"],
                combined=mathinfo["combined"], damage=per_hit, critical=critical)
            value = estimate.get("defense")
            if value and value > 0:
                import math
                self._record_panel(target.pet_id, def_key, value,
                                   math.floor(estimate["defenseLow"]) + 1, math.floor(estimate["defenseHigh"]))
        elif caster.side == 1 and (target.attr_stats.get(def_key) or 0) > 0:
            # 对方 → 我方：解对方那一项攻击。
            estimate = live_damage.panel_from_hit(
                defense=float(target.attr_stats[def_key]), power=mathinfo["power"],
                combined=mathinfo["combined"], damage=per_hit, critical=critical)
            value = estimate.get("attack")
            if value and value > 0:
                self._record_panel(caster.pet_id, atk_key, value,
                                   estimate["attackLow"], estimate["attackHigh"])

    def _record_panel(self, pet_id: Any, key: str, value: float, lower=None, upper=None) -> None:
        if pet_id is None:
            return
        bucket = self.learned_panels.setdefault(str(pet_id), {})
        bucket.setdefault(key, []).append(float(value))
        del bucket[key][:-6]          # 只留最近 6 个样本
        if lower is not None and upper is not None and 0 < lower <= upper:
            # Keep the latest interval; different turns may have different buffs.
            self.learned_panel_ranges.setdefault(str(pet_id), {})[key] = [lower, upper]

    def _learned_for(self, pet_id: Any) -> dict[str, float]:
        """取中位数：单个样本会被 buff/暴击/多段干扰，中位数更稳。"""
        bucket = self.learned_panels.get(str(pet_id)) or {}
        out: dict[str, float] = {}
        for key, samples in bucket.items():
            if not samples:
                continue
            ordered = sorted(samples)
            middle = len(ordered) // 2
            if len(ordered) % 2:
                out[key] = ordered[middle]
            else:
                out[key] = (ordered[middle - 1] + ordered[middle]) / 2
        return out

    def _on_finish(self, content: dict) -> bool:
        settle = _as_dict(content.get("settle_info"))
        if settle:
            self.result = settle.get("result")
            self.finished = True
            rounds = settle.get("rounds")
            if isinstance(rounds, int):
                self.round = rounds
        for entry in _as_list(content.get("pet_info")):
            entry = _as_dict(entry)
            pet = self._pet_by_id.get(str(entry.get("pet_gid")))
            if pet is None:
                continue
            remain = entry.get("remain_hp")
            if remain is not None:
                pet.apply_hp(remain)
            max_hp = entry.get("battle_max_hp")
            if isinstance(max_hp, int) and max_hp > 0:
                pet.max_hp = max_hp
        label = {1: "胜利", 2: "失败", 0: "未知"}.get(self.result, f"结果={self.result}")
        self.timeline.append({
            "round": self.round,
            "kind": "battle_finish",
            "text": f"对局结束 · {label}" if self.finished else "对局结束",
        })
        return True

    # -- 输出 ---------------------------------------------------------
    def _retain_knockout_preview(self, my_team, my_active, enemy_team, enemy_active):
        if not my_team or not enemy_team:
            return
        pair = (my_team[my_active], enemy_team[enemy_active])
        key = tuple((str(p.get('petId')), p.get('stageBaseConfId') or p.get('petBaseId')) for p in pair)
        def preview_fields(move):
            return {k: deepcopy(v) for k, v in move.items()
                    if k.startswith('damage') or k in ('oneShot', 'lethal')}
        if all(p.get('alive') is not False and p.get('currentHp') != 0 for p in pair):
            self._last_live_damage_preview = (key, [
                {(m.get('slot'), m.get('skillId')): preview_fields(m) for m in p.get('moves', [])}
                for p in pair], [{k: deepcopy(p[k]) for k in
                    ('traitDamagePreview', 'markDamage', 'attackMarkDamage', 'wishPreview', 'wishScenarios') if k in p}
                    for p in pair])
            return
        cached = self._last_live_damage_preview
        matched = cached is not None and cached[0] == key
        for index, pet in enumerate(pair):
            quotes = cached[1][index] if matched else {}
            if matched:
                pet.update(deepcopy(cached[2][index]))
            for move in pet.get('moves', []):
                old = quotes.get((move.get('slot'), move.get('skillId')))
                for field in list(preview_fields(move)):
                    move.pop(field, None)
                if old is None:
                    move['damageNote'] = '未记录这组对战精灵力竭前的伤害估计'
                    move['damageBeforeKnockoutMissing'] = True
                    continue  # Never borrow another matchup or invent a prior value.
                move.update(deepcopy(old), damageBeforeKnockout=True)
                # The old value is historical, not a new zero-HP knockout prediction.
                move.pop('oneShot', None)
                move.pop('lethal', None)

    def snapshot(self) -> dict[str, Any] | None:
        from lab.trait_runtime import query_scope
        with query_scope():
            return self._snapshot()

    def _apply_stat_policy(self, entry):
        """World user assumptions are local to this battle; never alter PVP rules."""
        world = self.is_npc_battle
        entry["battleMode"] = "world" if world else "pvp"
        entry["worldNpc"] = bool(world and entry.get("side") == 1)
        if not world:
            stars, source = 5, "pvp_five_star_rule"
        elif 0 < int(entry.get("level") or 0) < 60:
            stars, source = 0, "world_below_60_user_rule"
        elif entry.get("side") == 0 and str(entry.get("petId")) in self.world_star_overrides:
            stars, source = self.world_star_overrides[str(entry["petId"])], "world_user_selection"
        else:
            stars, source = None, "world_star_unknown"
        entry["natureStatsPolicy"] = {"stars": stars, "source": source}

    def _snapshot(self) -> dict[str, Any] | None:
        if not self.teams[0] and not self.teams[1]:
            return None
        # 报文里带出来的 buff 名字优先（进场时那批被动 buff 只有 id，名字全靠这里补）。
        for pet in self.teams[0] + self.teams[1]:
            for buff in pet.buffs:
                if not buff.get("name"):
                    fallback = self.buff_names.get(str(buff.get("id")))
                    if fallback:
                        buff["name"] = fallback
        my_team = [pet.to_payload(hide_unobserved=False, observed={}) for pet in self.teams[0]]
        enemy_team = [pet.to_payload(hide_unobserved=True,
                                     observed=self.observed_enemy_skills.get(str(pet.pet_id), {}))
                      for pet in self.teams[1]]
        my_active = self.active.get(0, 0)
        enemy_active = self.active.get(1, 0)
        my_active = my_active if 0 <= my_active < len(my_team) else 0
        enemy_active = enemy_active if 0 <= enemy_active < len(enemy_team) else 0

        from lab import live_modifiers, live_damage
        def roster(team):
            return [{"member_id": str(p.get("petId")), "types": live_damage._pet_types(p), "hp": p.get("currentHp"), "cute_layers": p.get("cuteStacks")} for p in team]
        for team, other in ((my_team, enemy_team), (enemy_team, my_team)):
            side = 0 if team is my_team else 1
            context = {"turn": self.round, "weather": self.live_weather, "rosters": {"self": roster(team), "opponent": roster(other)},
                       **self._party_counts_context(side)}
            for entry in team:
                entry["liveContext"] = context
                entry["coreMagicSkillId"] = self.core_magic_skill_ids[entry["side"]]
                magic = battle_data.skill_info(entry['coreMagicSkillId'])
                entry['coreMagicName'] = magic.get('name') or ('核心魔法未确认' if not entry['coreMagicSkillId'] else str(entry['coreMagicSkillId']))

        # 性格：报文里其实**直接下发**了 nature id（对方也下发），所以不需要推断；
        # 这里只把 id 翻成名字和增减方向。个体值不在报文里，只能靠实测面板反推，
        # 见下面 battleStatsEstimated。
        try:
            from lab import live_damage
            for team in (my_team, enemy_team):
                for entry in team:
                    nature = live_damage.nature_info(entry.get("nature"))
                    if nature:
                        entry["natureName"] = nature.get("name")
                        entry["natureUp"] = nature.get("up")
                        entry["natureDown"] = nature.get("down")
                        entry["natureOriginalUp"] = nature.get("up")
                        entry["natureOriginalDown"] = nature.get("down")
                    # 道具改写后的方向优先：非 0 时覆盖 nature 自带的增减。
                    pos_idx = entry.get("naturePosOverride") or 0
                    neg_idx = entry.get("natureNegOverride") or 0
                    if pos_idx or neg_idx:
                        entry["natureRewritten"] = True
                        if pos_idx:
                            entry["natureUp"] = _NATURE_ATTR_KEYS.get(pos_idx)
                        if neg_idx:
                            entry["natureDown"] = _NATURE_ATTR_KEYS.get(neg_idx)
                    known = entry.get("natureOverrideKnown") or {}
                    if known.get("up") is False:
                        entry["natureUp"] = None
                    if known.get("down") is False:
                        entry["natureDown"] = None
        except (OSError, ValueError, KeyError, ImportError):
            pass

        # 含性格、不含战斗内 buff 的六维（雷达图用这一份）：
        # 以进场面板 ``initialStats`` 为基数，按等级口径换算性格加成。
        # 大世界复用共享等级/星级候选；PVP保持固定60级五星口径。
        for team in (my_team, enemy_team):
            for entry in team:
                self._apply_stat_policy(entry)
                base = entry.get("initialStats") or {}
                if not base:
                    continue
                up_key = _NATURE_KEY_TO_STAT.get(entry.get("natureUp") or "")
                down_key = _NATURE_KEY_TO_STAT.get(entry.get("natureDown") or "")
                level = int(entry.get("level") or 0)
                from lab.live_stat_model import star_candidates
                stars = star_candidates(entry)
                if self.is_npc_battle:
                    from lab.live_stat_model import stat_candidates
                    race, _ = live_damage._race_stats(live_damage._effective_base(entry))
                    pairs = live_damage._nature_pairs(entry)
                    ranges = {}
                    for key in base:
                        dim = live_damage._ATTR_TO_SHORT.get(key)
                        if dim is None:
                            continue
                        try:
                            values = {v for star in stars for up, down in pairs
                                      for talent in live_damage._talent_values(entry, dim)
                                      for v in stat_candidates(entry, race, dim, talent, up, down, star)}
                            if values:
                                ranges[key] = [min(values), max(values)]
                        except ValueError as error:
                            entry.setdefault("worldStatIssues", {})[key] = str(error)
                    if ranges and all(lo == hi for lo, hi in ranges.values()):
                        entry["naturedStats"] = {key: bounds[0] for key, bounds in ranges.items()}
                    elif ranges:
                        entry["naturedStatsRange"] = ranges
                    continue
                if False in (entry.get("natureOverrideKnown") or {}).values():
                    pairs = live_damage._nature_pairs(entry)
                    entry["naturedStatsRange"] = {}
                    for key, value in base.items():
                        values = [nature_adjusted_stat(level, key, value,
                            "up" if key == _NATURE_KEY_TO_STAT.get(up) else
                            "down" if key == _NATURE_KEY_TO_STAT.get(down) else None, stars=s)
                            for up, down in pairs for s in stars]
                        if values:
                            entry["naturedStatsRange"][key] = [min(values), max(values)]
                    continue
                natured: dict[str, int] = {}
                for key, value in base.items():
                    direction = None
                    if up_key and key == up_key:
                        direction = "up"
                    elif down_key and key == down_key:
                        direction = "down"
                    natured[key] = nature_adjusted_stat(level, key, value, direction, stars=stars[0])
                entry["naturedStats"] = natured

        # Inverting bare damage does not prove a live panel: buffs/mitigation may be missing.
        # Preserve candidates separately; never feed them back into the radar or next prediction.
        for team in (my_team, enemy_team):
            for entry in team:
                learned = self._learned_for(entry.get("petId"))
                if not learned:
                    continue
                entry["panelInference"] = {
                    "calibrated": False,
                    "scope": "bare_damage_model_candidates",
                    "ranges": self.learned_panel_ranges.get(str(entry.get("petId")), {}).copy(),
                    "notice": "仅为裸伤害公式下的候选，未验证状态与减伤，不作为实时面板或后续预测输入。",
                }
        for entry in my_team + enemy_team:
            entry.update(live_damage.stat_summary(entry))
            evidence = self.damage_evidence.get(str(entry.get("petId")), [])
            from lab.live_inference import infer_configuration
            key = json.dumps({name: entry.get(name) for name in ("petBaseId", "stageBaseConfId", "level", "nature", "natureUp", "natureDown",
                "naturePosOverride", "natureNegOverride", "natureOverrideKnown", "maxHp", "talent_selection", "battleStats", "revealedBaseStats", "talentEvidence", "initialStats", "battleMode", "natureStatsPolicy", "worldNpc", "confId")}, sort_keys=True)
            cached = self._configuration_cache.get(str(entry.get("petId")))
            if cached is None or cached[0] != key:
                cached = (key, infer_configuration(entry, evidence))
                self._configuration_cache[str(entry.get("petId"))] = cached
            entry["configurationInference"] = cached[1]
            if cached[1].get("protocol_selection"):
                entry["talent_selection"] = cached[1]["protocol_selection"]
            if cached[1]["status"] in ("conditional", "protocol", "damage_conflict"):
                entry["panelStatRanges"].update(cached[1]["panel_ranges"])
                entry["panelStatSources"].update({dim: "面板/实战伤害约束（当前公式条件候选）" for dim in cached[1]["panel_ranges"]})
        enemy_active = enemy_active if 0 <= enemy_active < len(enemy_team) else 0

        def hp_block(team: list[dict], index: int) -> dict[str, Any]:
            entry = team[index] if team and index < len(team) else {}
            return {"hpAfter": entry.get("currentHp"), "percent": entry.get("hpPercent")}

        # 伤害预估：我方在场 → 敌方在场的每一槽。算不出来就留空，绝不编数。
        damage: list[dict[str, Any]] = []
        try:
            from lab import live_damage
            if my_team and enemy_team:
                damage = live_damage.estimate_moves(my_team[my_active], enemy_team[enemy_active])
        except (OSError, ValueError, KeyError):      # 规则快照不可用不该拖垮 HUD
            damage = []
        if damage and my_team:
            by_slot = {move.get("slot"): move for move in my_team[my_active].get("moves") or []}
            for item in damage:
                move = by_slot.get(item.get("slot"))
                if not move:
                    continue
                move['damageChoices'] = item.get('choices')
                move['damageTraitScenarios'] = item.get('traitScenarios')
                move['damageCounterPreview'] = bool(item.get('counterPreview'))
                move["damageNonDamaging"] = bool(item.get("nonDamaging"))
                if item.get("reason"):
                    move["damageNote"] = item["reason"]
                elif "normal" in item:
                    move["damageBasis"] = item.get("atkSource", "") + " / " + item.get("defSource", "")
                    move["damageNormal"] = item["normal"]
                    move["damageCritical"] = item.get("critical")
                    # 保留旧字段，老前端/脚本还在读它；但它两端是「不暴击 / 暴击」，
                    # 不是随机浮动，新前端不要把它当区间渲染。
                    move["damageRange"] = [item["normal"], item.get("critical", item["normal"])]
                    move["damagePct"] = [item.get("normalPct"), item.get("criticalPct")]
                    if item.get("hits", 1) > 1:
                        move["damageHits"] = item["hits"]
                    if item.get("lethal"):
                        move["lethal"] = True
                else:
                    move["damageBasis"] = item.get("atkSource", "") + " / " + item.get("defSource", "")
                    move["damageNormalMin"] = item["normalMin"]
                    move["damageNormalMax"] = item["normalMax"]
                    move["damageNormalRange"] = True
                    move["damageCriticalMin"] = item.get("criticalMin")
                    move["damageCriticalMax"] = item.get("criticalMax")
                    move["damageHits"] = item.get("hits", 1)
                    move["lethal"] = item.get("lethal", False)
                if not item.get("reason"):
                    move.update(damagePerHitMin=item["perHitMin"], damagePerHitMax=item["perHitMax"],
                                damageHits=item["hits"], damageEffects=item.get("effects"), oneShot=item.get("oneShot", False),
                                damageResponse=item.get("response"))

        # 反向：敌方**已观测**的技能打我方会掉多少血。
        # 对方攻击面板已下发 → 确定单值；没下发 → 用种族值 + 性格推最低/最高区间
        # （报文不含个体值，所以两端取个体 0~60，这不是随机浮动）。
        incoming: list[dict[str, Any]] = []
        try:
            from lab import live_damage
            if my_team and enemy_team:
                incoming = live_damage.estimate_incoming(enemy_team[enemy_active], my_team[my_active])
        except (OSError, ValueError, KeyError):
            incoming = []
        if incoming and enemy_team:
            by_skill: dict[Any, dict[str, Any]] = {}
            for move in enemy_team[enemy_active].get("moves") or []:
                sid = move.get("skillId")
                if isinstance(sid, int):
                    by_skill.setdefault(sid, move)
            for item in incoming:
                move = by_skill.get(item.get("skillId"))
                if not move:
                    continue
                move['damageChoices'] = item.get('choices')
                move['damageTraitScenarios'] = item.get('traitScenarios')
                move['damageCounterPreview'] = bool(item.get('counterPreview'))
                move["damageNonDamaging"] = bool(item.get("nonDamaging"))
                if item.get("reason"):
                    move["damageNote"] = item["reason"]
                    continue
                move["damageSource"] = "incoming"
                move["damageBasis"] = item.get("atkSource", "") + " / " + item.get("defSource", "")
                if item.get("exact"):
                    move["damageNormal"] = item["normal"]
                    move["damageCritical"] = item.get("critical")
                else:
                    # 区间：对方攻击面板未知，按种族值 + 性格推出来的可能范围。
                    move["damageNormalMin"] = item["normalMin"]
                    move["damageNormalMax"] = item["normalMax"]
                    move["damageNormalRange"] = True
                    move["damageCriticalMin"] = item.get("criticalMin")
                    move["damageCriticalMax"] = item.get("criticalMax")
                    if item.get("atkRange"):
                        move["damageAtkRange"] = item["atkRange"]
                if item.get("hits", 1) > 1:
                    move["damageHits"] = item["hits"]
                if item.get("lethal"):
                    move["lethal"] = True
                move.update(damagePerHitMin=item["perHitMin"], damagePerHitMax=item["perHitMax"],
                            damageHits=item["hits"], damageEffects=item.get("effects"), oneShot=item.get("oneShot", False),
                            damageResponse=item.get("response"))

        for team, index, other, other_index in ((my_team, my_active, enemy_team, enemy_active), (enemy_team, enemy_active, my_team, my_active)):
            if not team or not other:
                continue
            entry, target = team[index], other[other_index]
            entry["traitDamagePreview"] = live_modifiers.snow_bear_trait_damage(entry, target)
            try:
                entry["markDamage"] = live_modifiers.mark_damage(entry, target)
                entry["attackMarkDamage"] = [row for row in live_modifiers.mark_damage(target, entry) if row.get("phase") == "after_attack"]
            except ValueError as error:
                entry["markDamage"] = [{"name": "印记", "reason": str(error)}]
            wish = live_modifiers.wish_move(entry)
            if entry['side'] == 1 and entry.get('coreMagicSkillId') in (None, 7010020):
                try:
                    entry['wishScenarios'] = live_damage.wish_scenarios(entry, target)
                except (ValueError, KeyError, TypeError) as error:
                    entry['wishScenarios'] = {'reason': str(error)}
            elif wish:
                quote = live_damage.estimate_moves({**entry, "moves": [wish]}, target)
                entry["wishPreview"] = {**wish, "estimate": quote[0] if quote else {"reason": "缺少伤害条件"}}

        for entry in my_team + enemy_team:
            for move in entry.get("moves", []):
                recent = self._recent_cast_estimates.get((str(entry.get("petId")), move.get("skillId")))
                if recent is not None:
                    move["recentCastEstimate"] = deepcopy(recent)
        self._retain_knockout_preview(my_team, my_active, enemy_team, enemy_active)
        return {
            "schema": SCHEMA,
            "source": "rkpp-live",
            "runtime": {
                "sessionId": str(self.battle_id or ""),
                "battleId": self.battle_id,
                # PVP 不触发暴击；野外/NPC 才有。前端据此决定要不要摆出暴击值。
                "mode": "world" if self.is_npc_battle else "pvp",
                "myTeam": my_team,
                "enemyTeam": enemy_team,
                "active": {"my": {"rosterIndex": my_active}, "enemy": {"rosterIndex": enemy_active}},
                "hp": {"my": hp_block(my_team, my_active), "enemy": hp_block(enemy_team, enemy_active)},
                # 只报**当前在场那只**打过什么。全队汇总会让玩家误以为是这只会的。
                "observedEnemyMoves": sorted(
                    (info.get("name") or str(info.get("id")))
                    for info in (self.observed_enemy_skills.get(
                        str(enemy_team[enemy_active].get("petId")) if enemy_team else "", {}) or {}).values()
                    if info.get("name") or info.get("id") is not None),
                "battleTimeline": self.timeline[-40:],
                "battleHistory": [event for event in self.timeline if event["kind"] in
                                  ("battle_enter", "skill_cast", "switch", "damage", "form_change", "battle_finish")
                                  and event.get("isMove") is not False],
                "round": self.round,
                "maxRound": self.max_round,
                "weatherId": self.weather_id,
                "weather": self.live_weather,
                "finished": self.finished,
                "result": self.result,
                "playerName": self.my_name,
                # 每槽一个区间：normal=不暴击、critical=暴击（引擎 critical_dam=20000）。
                # 口径与工作台预估一致：不算换人/防御减伤/聚能/应对加成/天气/印记/特性。
                "damageEstimate": damage,
                "damagePolicy": live_damage.PREVIEW_POLICY,
            },
            "state": {
                "myTeam": my_team,
                "enemyTeam": enemy_team,
                "myActiveIndex": my_active,
                "enemyActiveIndex": enemy_active,
            },
            "enemyPreview": {"enemyTeam": enemy_team},
        }


_BUFF_NAME_CACHE: dict[str, str] | None = None


def _buff_name(buff_id: Any) -> str:
    """buff_id → 中文名；查不到就返回空串（前端会显示成"状态"）。"""
    global _BUFF_NAME_CACHE
    if _BUFF_NAME_CACHE is None:
        table: dict[str, str] = {}
        root = Path(__file__).resolve().parent.parent
        for rel in ("data/external/buff.json",
                    "vendor/洛克PVP助手/app/wwwroot/native-data/authority/buff.json"):
            path = root / rel
            if not path.exists():
                continue
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
            except (OSError, ValueError):
                continue
            for key, value in raw.items() if isinstance(raw, dict) else ():
                if isinstance(value, dict) and value.get("name"):
                    table[str(key)] = str(value["name"])
            if table:
                break
        _BUFF_NAME_CACHE = table
    return _BUFF_NAME_CACHE.get(str(buff_id), "") if _BUFF_NAME_CACHE else ""


def snapshot_from_events(events: list[dict]) -> dict[str, Any] | None:
    """离线回放：一串 ``{opcode, content}`` 直接跑出场快照。"""
    tracker = BattleTracker()
    for event in events:
        if not isinstance(event, dict):
            continue
        tracker.handle_event(event.get("opencode") or event.get("opcode"), _as_dict(event.get("content")))
    return tracker.snapshot()


# ---------------------------------------------------------------------------
# 实时订阅：轮询中继 /latest，把战斗消息喂给 tracker，有变化就发快照。
# ---------------------------------------------------------------------------
import json as _json
import os as _os
import threading as _threading
import time as _time
import urllib.error as _urlerror
import urllib.request as _urlrequest

DEFAULT_RELAY = "http://127.0.0.1:8765"

_CAPTURE_DIAG_CACHE: tuple[float, dict[str, Any]] = (0.0, {})


def capture_diag(max_age: float = 3.0) -> dict[str, Any]:
    """读 rkpp 最新一次抓包会话的 ``[capture-diag] summary``。

    用户"什么都没解析到"时，靠这几个数字就能分清卡在哪一层：
    ``target_packets`` 有数说明网卡抓到了；``decoded_rows`` 有数说明 TCP 流解开了；
    ``key_hits=0`` 说明没拿到会话密钥（0x1002），业务帧一条都解不开——
    这才是最常见的原因，而且不看日志根本发现不了。
    """
    global _CAPTURE_DIAG_CACHE
    if _CAPTURE_DIAG_CACHE[0] > 0 and _time.time() - _CAPTURE_DIAG_CACHE[0] < max_age:
        return _CAPTURE_DIAG_CACHE[1]

    base = Path(__file__).resolve().parent.parent / "vendor" / "rkpp"
    from lab.release_paths import user_root
    private = user_root()
    if private:
        base = private / 'rkpp'
    info: dict[str, Any] = {}
    try:
        sessions = sorted((p for p in base.glob("rkpp_*") if p.is_dir()),
                          key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        sessions = []
    for session in sessions[:4]:
        log = session / "capture.log"
        if not log.exists():
            continue
        try:
            with open(log, "rb") as fh:
                fh.seek(0, 2)
                size = fh.tell()
                fh.seek(max(0, size - 400_000))
                chunk = fh.read().decode("utf-8", "replace")
        except OSError:
            continue
        for line in reversed(chunk.splitlines()):
            marker = "[capture-diag]"
            pos = line.find(marker)
            if pos < 0:
                continue
            try:
                data = _json.loads(line[pos + len(marker):].strip())
            except ValueError:
                continue
            if not isinstance(data, dict) or data.get("event") != "summary":
                continue
            info = {
                "session": session.name,
                "updated_at": session.stat().st_mtime,
                "target_packets": data.get("target_packets"),
                "decoded_rows": data.get("decoded_rows"),
                "parsed_business_records": data.get("parsed_business_records"),
                "key_hits": data.get("key_hits"),
                "worker_errors": data.get("worker_errors"),
            }
            break
        if info:
            break
    _CAPTURE_DIAG_CACHE = (_time.time(), info)
    return info


class LiveBattleFeed:
    """后台线程：只读中继，不写游戏；可将对战观测保存为本地回放。

    ``on_snapshot(payload, meta)`` 在快照变化时被调用一次；``state()`` 让工作台
    能查"到底接上没有"。
    """

    def __init__(self, base: str = DEFAULT_RELAY, *, interval: float = 0.3,
                 on_snapshot=None, page: int = 200, archive=None) -> None:
        self.base = base.rstrip("/")
        self.interval = max(0.3, float(interval))
        self.on_snapshot = on_snapshot
        self.page = max(20, min(int(page), 500))
        self.tracker = BattleTracker()
        self.archive = archive
        self.archive_error = ''
        self.archive_failures = 0
        self.cursor = 0
        self.events_seen = 0
        self.battle_events = 0
        self.unknown_opcodes: dict[str, int] = {}
        self.last_error = ""
        self.last_poll_at = 0.0
        self.snapshot_at = 0.0
        self.relay_ok = False
        self._stop = _threading.Event()
        self._thread: _threading.Thread | None = None
        self._capture_cache: tuple[float, dict[str, Any]] = (0.0, {})
        self._published_snapshot = None
        import queue
        self._world_star_requests = queue.SimpleQueue()
        self._more_pending = False
        self.processing_ms = 0.0

    # -- 控制 ---------------------------------------------------------
    def start(self) -> "LiveBattleFeed":
        if self._thread and self._thread.is_alive():
            return self
        self._thread = _threading.Thread(target=self._run, name="roco-live-battle", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:  # 线程不能因为一次网络抖动就死掉
                self.last_error = f"{type(exc).__name__}: {exc}"
            if not self._more_pending:
                self._stop.wait(self.interval)

    # -- 抓取 ---------------------------------------------------------
    def _get(self, path: str, timeout: float = 3.0):
        with _urlrequest.urlopen(self.base + path, timeout=timeout) as response:
            body = response.read()
        return _json.loads(body.decode("utf-8")) if body else None

    def poll_once(self) -> dict[str, Any] | None:
        self._more_pending = False
        from lab.trait_runtime import query_scope
        with query_scope():
            return self._poll_once()

    def set_world_stars(self, request):
        """Queue a user assumption; only the feed thread mutates its tracker."""
        if not isinstance(request, dict):
            raise ValueError("星级设置应为对象")
        runtime = (self.snapshot() or {}).get("runtime") or {}
        if (not runtime.get("snapshotToken") or request.get("snapshotToken") != runtime["snapshotToken"]
                or request.get("sessionId") != runtime.get("sessionId")):
            raise ValueError("对局已更新，请在当前精灵上重新选择星级")
        if runtime.get("mode") != "world":
            raise ValueError("PVP固定双方60级五星，不接受大世界星级设置")
        pet_id = str(request.get("petId", ""))
        pet = next((p for p in runtime.get("myTeam", []) if str(p.get("petId")) == pet_id), None)
        if pet is None:
            raise ValueError("只能设置本局己方精灵星级")
        stars = request.get("stars")
        if stars is not None and (type(stars) is not int or not 0 <= stars <= 10):
            raise ValueError("星级必须为0–10的整数或未指定")
        if int(pet.get("level") or 0) < 60 and stars not in (None, 0):
            raise ValueError("未满60级固定按0星估计")
        self._world_star_requests.put((str(runtime.get("sessionId")), pet_id, stars))
        return {"ok": True, "queued": True, "stars": stars}

    def _apply_world_star_requests(self):
        import queue
        changed = False
        while True:
            try:
                session, pet_id, stars = self._world_star_requests.get_nowait()
            except queue.Empty:
                return changed
            pet = self.tracker._pet_by_id.get(pet_id)
            if (not self.tracker.is_npc_battle or str(self.tracker.battle_id or "") != session
                    or pet is None or pet.side != 0):
                continue
            if stars is None:
                self.tracker.world_star_overrides.pop(pet_id, None)
            else:
                self.tracker.world_star_overrides[pet_id] = stars
            changed = True

    def _poll_once(self) -> dict[str, Any] | None:
        self._more_pending = False
        self.last_poll_at = _time.time()
        try:
            # A service restart needs the retained entry, not just the last few mid-battle packets.
            limit = 5000 if self.cursor == 0 else self.page
            rows = self._get(f"/latest?limit={limit}&after={self.cursor}")
            self.relay_ok = True
            self.last_error = ""
        except (_urlerror.URLError, OSError, ValueError) as exc:
            self.relay_ok = False
            self.last_error = f"relay: {exc}"
            return None
        if not isinstance(rows, list):
            rows = []
        self._more_pending = len(rows) >= limit
        started = _time.perf_counter()

        changed = False
        for row in rows:
            if not isinstance(row, dict):
                continue
            self.events_seen += 1
            event_id = row.get("_relay_event_id")
            if isinstance(event_id, int) and event_id > self.cursor:
                self.cursor = event_id
            opcode = row.get("opencode") or row.get("opcode")
            code = str(opcode or "").strip()
            if not _is_battle_code(code):
                if code:
                    self.unknown_opcodes[code] = self.unknown_opcodes.get(code, 0) + 1
                continue
            if self.tracker.handle_event(opcode, _as_dict(row.get("content"))):
                changed = True
                self.battle_events += 1
            if self.archive is not None:
                try:
                    self.archive.record(self.tracker, opcode, _as_dict(row.get('content')), event_id)
                except Exception as error:
                    self.archive_failures += 1
                    self.archive_error = f'{type(error).__name__}: {error}'
        changed = self._apply_world_star_requests() or changed
        if not changed:
            return None
        payload = deepcopy(self.tracker.snapshot())
        if payload is None:
            return None
        payload['runtime']['replayArchive'] = {'enabled': self.archive is not None,
            'path': str(self.archive.path) if self.archive is not None else None,
            'failedPackets': self.archive_failures, 'error': self.archive_error}
        self.snapshot_at = _time.time()
        payload['runtime']['snapshotToken'] = self.snapshot_at
        # Readers consume this detached publication; they must never rescan the tracker.
        self._published_snapshot = payload
        self.processing_ms = round((_time.perf_counter() - started) * 1000, 2)
        if self.on_snapshot is not None:
            try:
                self.on_snapshot(payload, self.state())
            except Exception as exc:
                self.last_error = f"on_snapshot: {exc}"
        return payload

    def snapshot(self):
        return self._published_snapshot

    # -- 状态 ---------------------------------------------------------
    def _capture(self) -> dict[str, Any]:
        if self._capture_cache[0] > 0 and _time.time() - self._capture_cache[0] < 3.0:
            return self._capture_cache[1]
        info = capture_diag()
        self._capture_cache = (_time.time(), info)
        return info

    def state(self) -> dict[str, Any]:
        capture = self._capture()
        key_missing = bool(
            capture.get("target_packets")
            and not capture.get("key_hits")
            and not capture.get("parsed_business_records")
        )
        hint = ""
        if key_missing:
            hint = ("抓到了 {p} 个包，但本次会话的密钥还没拿到（key_hits=0），"
                    "所以一条业务记录都解不开。0x1002 密钥只在客户端建连时发一次，"
                    "抓包要在建连之前就开着：请在游戏里退回登录界面重新进入，"
                    "或重启游戏客户端。密钥到手后中继会自动开始解码，不用重启抓包。"
                    ).format(p=capture.get("target_packets"))
        elif capture and not capture.get("parsed_business_records") and not self.relay_ok:
            hint = "中继未连接：请在 APP 中点击“启动抓包”。"
        return {
            "relay": self.base,
            "relay_ok": self.relay_ok,
            "cursor": self.cursor,
            "events_seen": self.events_seen,
            "battle_events": self.battle_events,
            "last_error": self.last_error,
            "last_poll_at": self.last_poll_at,
            "snapshot_at": self.snapshot_at,
            "processing_ms": self.processing_ms,
            "replay_archive": {'enabled': self.archive is not None,
                'path': str(self.archive.path) if self.archive is not None else None,
                'failed_packets': self.archive_failures, 'error': self.archive_error},
            "backlog_pending": self._more_pending,
            "has_battle": bool(self.tracker.teams[0] or self.tracker.teams[1]),
            "battle_id": self.tracker.battle_id,
            "round": self.tracker.round,
            "finished": self.tracker.finished,
            "result": self.tracker.result,
            "capture": capture,
            "key_missing": key_missing,
            "hint": hint,
            "unknown_opcodes": dict(sorted(self.unknown_opcodes.items(),
                                           key=lambda item: -item[1])[:12]),
            # 换人走哪条报文还没在实机上定死，这里把最近 60 条的结构摊开，
            # 出问题时一眼能看到是哪条带来了新精灵。
            "recent_raw": self.tracker.recent_raw[-20:],
            "pending_pets": self.tracker.pending_pets[-10:],
            "checks": {
                "my_team": len(self.tracker.teams[0]),
                "enemy_team": len(self.tracker.teams[1]),
                "observed_enemy_skills": sum(len(bucket) for bucket in self.tracker.observed_enemy_skills.values()),
                "timeline": len(self.tracker.timeline),
            },
        }


def _is_battle_code(code: str) -> bool:
    text = str(code or "").strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    try:
        # 键的写法是 "0x1316"：前缀小写、十六进制大写，这里必须生成同一种写法。
        normalized = f"0x{int(text, 16):04X}"
    except (TypeError, ValueError):
        return False
    return normalized in BATTLE_OPCODES


_SHARED_FEED: LiveBattleFeed | None = None


def shared_feed(on_snapshot=None, base: str = "") -> LiveBattleFeed:
    """进程内单例，server 启动时拿它起线程。

    地址优先级：显式参数 → ``ROCO_RELAY`` 环境变量 → 默认 8765。
    """
    global _SHARED_FEED
    base = base or _os.environ.get("ROCO_RELAY") or DEFAULT_RELAY
    if _SHARED_FEED is None:
        from lab.replay_store import ReplayStore
        from sqlite3 import Error as SQLiteError
        try:
            archive = ReplayStore()
            error = ''
        except (OSError, SQLiteError) as exc:
            archive, error = None, f'{type(exc).__name__}: {exc}'
        _SHARED_FEED = LiveBattleFeed(base, on_snapshot=on_snapshot, archive=archive)
        _SHARED_FEED.archive_error = error
    elif on_snapshot is not None:
        _SHARED_FEED.on_snapshot = on_snapshot
    return _SHARED_FEED
