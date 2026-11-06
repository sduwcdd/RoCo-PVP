"""Source-bound departure, field-mark and Swift selection components.

These functions do not settle a complete switch: entry/exit traits, cleanup,
damage and follow-up triggers remain the caller's unresolved dependencies.
Unknown replacement and charging-cancellation rules never receive defaults.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path


TERMS_SHA256 = 'a7a4ad3bc1e30e154cdbc52b9e350ec75cbca04bb39e1b9e7012fa4a220ca822'
REVIEWED_TERMS = {
    1003: "精灵离场，并选择队伍里一只其他精灵替换入场。本回合入场的精灵免疫此效果。",
    1005: "通过主动更换精灵的方式入场时，使用第一个能量满足要求，并带有迅捷的技能。",
    1007: "该技能需要先蓄力1回合，下回合才能释放。蓄力期间免疫所有离场效果。",
    1024: "精灵离场，并立即入场。本回合入场的精灵免疫此效果。",
    1026: "精灵离场，并随机选择队伍里一只其他精灵替换入场。本回合入场的精灵免疫此效果。",
    3009: "通过主动更换精灵或触发脱离效果的方式下场。（不包括精灵力竭后下场）",
    3010: "精灵下场后印记不会消失，新入场的精灵会继承印记效果。精灵最多同时拥有1种正面印记和1种负面印记。",
    3023: "处于禁足状态时，精灵无法离场，且无法获得新的禁足状态。",
}
EFFECT_TERMS = {"detach": 1003, "return": 1024, "emergency": 1026}
SKILLS_SHA256 = '58ec4e67d14ff9bdaab615e2b32d8bede0fd3b7180dc2e33179047bcd8803de5'

# The client exposes the cooldown formula, but the PVP configuration rows
# currently available to this project omit both cooldown values.
GAME_SWITCH_SOURCE = "artifacts/unpack_probe_20261025/battle_analysis/pakchunk4-WindowsNoEditor_14_P/BattleUtils.luac.decompiled.lua"
GAME_SWITCH_SOURCE_SHA256 = "9a4615926d2ff4037198845943ec9952bde197a9169457e54dab0f6eb35ec4b9"
GAME_SWITCH_ENUM_SOURCE = "artifacts/unpack_probe_20261025/battle_analysis/pakchunk4-WindowsNoEditor_27_P/ProtoEnum.luac.disassembly.txt"
GAME_SWITCH_ENUM_SHA256 = "2785fe414873eeea8ae83d4000163eecab14b18dc49b4e23315b33a8d362ae5b"
GAME_SWITCH_UI_SOURCE = "artifacts/unpack_probe_20261025/battle_analysis/pakchunk4-WindowsNoEditor_3_P/RoundSwapAction.luac.decompiled.lua"
GAME_SWITCH_UI_SHA256 = "135a263eecae3ee8b4ab438794ff59804629b9dc768c0eb86a7cc39d509ecf27"
GAME_SWITCH_POLICY = "client_check_can_change_pet_v1"
CHANGE_PET_BAN_BIT = 16
_MISSING = object()
GAME_SWITCH_SYNC_SOURCE = "artifacts/switch_source_followup_20261026/pakchunk4-WindowsNoEditor_10_P/BattleManager.decompiled.lua"
GAME_SWITCH_HASHES = {GAME_SWITCH_SYNC_SOURCE: "16e82256fb993896ac2e37d704e7ad4dd522c4119a5d6ce4cdc46a9b1163db23",
                      GAME_SWITCH_SOURCE: GAME_SWITCH_SOURCE_SHA256,
                      GAME_SWITCH_ENUM_SOURCE: GAME_SWITCH_ENUM_SHA256,
                      GAME_SWITCH_UI_SOURCE: GAME_SWITCH_UI_SHA256}


def _verify_client_switch_sources():
    root = Path(__file__).resolve().parents[1]
    for relative, expected in GAME_SWITCH_HASHES.items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
            raise ValueError("Client switch evidence changed; review required: " + relative)



def _integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _boolean(value, label):
    if type(value) is not bool:
        raise ValueError(f"{label} must be an explicit boolean")


def _change_pet_banned_from_state_bits(info, *, state_bits_indexing="lua_one_based"):
    """Decode BT_BAN_STATUS_CHANGE_PET through the client's state_bits layout.

    A scalar ``state_bit`` belongs to a different client helper; refusing it
    here prevents silently mixing the two wire representations.
    """
    if state_bits_indexing != "lua_one_based":
        raise ValueError("state_bits indexing must explicitly be lua_one_based")
    if info is None:
        return False
    if not isinstance(info, dict):
        raise ValueError("battle_inside_pet_info must be an object or null")
    bits = info.get("state_bits")
    if bits is None:
        return False
    if isinstance(bits, dict):
        word = bits.get("1", bits.get(1, 0))
    elif isinstance(bits, list):
        word = bits[0] if bits else 0
    else:
        raise ValueError("state_bits must be a list or an object")
    if type(word) is not int or word < 0:
        raise ValueError("state_bits[1] must be a nonnegative integer")
    return bool(word & (1 << CHANGE_PET_BAN_BIT))


class SwitchRules:
    def __init__(self, catalog):
        if not isinstance(catalog, dict) or not isinstance(catalog.get("snapshot_id"), str) or not catalog["snapshot_id"]:
            raise ValueError("A versioned BWIKI catalog is required")
        source = catalog.get("provenance", {}).get("Terms", {})
        if source.get("content_sha256") != TERMS_SHA256:
            raise ValueError("BWIKI Terms changed or are missing; switch semantics require review")
        entries = catalog.get("glossary", [])
        for key, definition in REVIEWED_TERMS.items():
            matches = [x for x in entries if x.get("key") == key]
            if len(matches) != 1 or matches[0].get("definition") != definition:
                raise ValueError(f"BWIKI term {key} is missing, ambiguous or changed")
        self.snapshot_id = catalog["snapshot_id"]
        self._source = deepcopy(source)
        self._terms = {x["key"]: deepcopy(x) for x in entries if x.get("key") in REVIEWED_TERMS}
        self._marks = {x["key"]: deepcopy(x) for x in entries
                       if isinstance(x.get("definition"), str) and (x["definition"].startswith("印记效果")
                           or x.get("key") == 3012 and x.get("definition") == "获得增益时，会额外获得1层。")}
        # The older departure/mark helpers do not depend on Skills. Validate
        # this separate source lazily only when intrinsic Swift is queried.
        self._skill_source = deepcopy(catalog.get("provenance", {}).get("Skills", {}))
        from lab.phase_config import source_payload
        self._phase_catalog = source_payload(catalog)
        self._phase_config = None

    def change_pet_banned(self, battle_inside_pet_info):
        """Read the client-defined switch-ban bit from its packed word array."""
        _verify_client_switch_sources()
        return _change_pet_banned_from_state_bits(battle_inside_pet_info)

    def skill_swift_metadata(self, skill_id):
        """Return reviewed intrinsic metadata from data, with no prose parsing."""
        _integer(skill_id, "skill_id", 1)
        if self._skill_source.get("content_sha256") != SKILLS_SHA256:
            raise ValueError("BWIKI Skills changed or are missing; intrinsic Swift needs source review")
        if self._phase_config is None:
            from lab.phase_config import load_phase_config
            self._phase_config = load_phase_config(self._phase_catalog)
        entry = self._phase_config["skills"].get(str(skill_id))
        if entry is None:
            raise ValueError("Skill ID must uniquely match the owned source snapshot")
        return deepcopy(entry["swift_metadata"])

    def swift_candidates(self, skill_ids, effective_costs):
        """Build four source-bound candidates without sorting or cost defaults."""
        if (not isinstance(skill_ids, list) or len(skill_ids) != 4
                or not isinstance(effective_costs, list) or len(effective_costs) != 4):
            raise ValueError("Swift candidates require four ordered skill IDs and four explicit costs")
        candidates = []
        filled = set()
        for skill_id, cost in zip(skill_ids, effective_costs):
            _integer(skill_id, "skill_id")
            if cost is not None:
                _integer(cost, "effective_cost")
            if skill_id == 0:
                if cost is not None:
                    raise ValueError("Empty skill slots must have an explicit null cost")
                candidates.append(None)
                continue
            if skill_id in filled:
                raise ValueError("Duplicate carried skill IDs need validation before Swift selection")
            filled.add(skill_id)
            metadata = self.skill_swift_metadata(skill_id)
            candidates.append({"skill_id": skill_id, "swift": metadata["swift"],
                               "effective_cost": cost, "source_metadata": metadata})
        return candidates

    def _result(self, term_ids, **fields):
        return {"scope": "source_bound_switch_component", "snapshot_id": self.snapshot_id,
                "term_ids": list(term_ids), "evidence": {**deepcopy(self._source),
                "terms": [deepcopy(self._terms[k]) for k in term_ids]},
                "training_eligible": False, "real_game_verified": False,
                "full_switch_executed": False, **fields}

    def change_eligibility(self, *, current_round=_MISSING, exchange_initial_cold=_MISSING,
                           exchange_cold=_MISSING, last_change_round_index=_MISSING,
                           can_changepet=_MISSING, ban_change_pet=_MISSING):
        """Apply the installed client's voluntary-switch gate.

        The two cooldown values and the runtime last-change round are inputs
        from the battle session.  They are deliberately never defaulted from
        the incomplete parsed BATTLE_CONF rows.
        """
        _verify_client_switch_sources()
        missing = []
        for value, label, minimum in ((current_round, "current_round", 1),
                                      (exchange_initial_cold, "exchange_initial_cold", 0)):
            if value is _MISSING or value is None:
                missing.append(label)
            else:
                _integer(value, label, minimum)
        if last_change_round_index is _MISSING:
            missing.append("last_change_round_index")
        elif last_change_round_index is not None:
            _integer(last_change_round_index, "last_change_round_index")
        if (last_change_round_index is not _MISSING
                and last_change_round_index not in (None, 0)):
            if exchange_cold is _MISSING or exchange_cold is None:
                missing.append("exchange_cold")
            else:
                _integer(exchange_cold, "exchange_cold")
        if can_changepet is _MISSING:
            missing.append("can_changepet")
        elif can_changepet is None:
            can_changepet = 0  # BattleUtils.GetCanChangePetConfig uses `or 0`.
        else:
            _integer(can_changepet, "can_changepet")
        if ban_change_pet is _MISSING:
            missing.append("ban_change_pet")
        else:
            _boolean(ban_change_pet, "ban_change_pet")
        evidence = {"policy": GAME_SWITCH_POLICY, "source": GAME_SWITCH_SOURCE,
                    "source_sha256": deepcopy(GAME_SWITCH_HASHES),
                    "formula": "initial>=round; round<=last_change+cooldown",
                    "ban_bit": CHANGE_PET_BAN_BIT,
                    "runtime_values_verified": False}
        base = {"current_round": None if current_round is _MISSING else current_round,
                "exchange_initial_cold": None if exchange_initial_cold is _MISSING else exchange_initial_cold,
                "exchange_cold": None if exchange_cold is _MISSING else exchange_cold,
                "last_change_round_index": None if last_change_round_index is _MISSING else last_change_round_index,
                "can_changepet": None if can_changepet is _MISSING else can_changepet,
                "ban_change_pet": None if ban_change_pet is _MISSING else ban_change_pet,
                "source_evidence": evidence}
        if can_changepet is not _MISSING and can_changepet <= 0:
            return self._result([], status="blocked", reason="battle_mode_disallows_switch",
                                blocked_by="can_changepet", **base)
        if ban_change_pet is not _MISSING and ban_change_pet:
            return self._result([], status="blocked", reason="pet_state_bans_switch",
                                blocked_by="BT_BAN_STATUS_CHANGE_PET", **base)
        if missing:
            return self._result([], status="unresolved", reason="runtime_switch_cooldown_values_missing",
                                missing_inputs=missing, **base)
        if exchange_initial_cold >= current_round:
            remaining = exchange_initial_cold - current_round + 1
            return self._result([], status="blocked", reason="initial_switch_cooldown",
                                blocked_by="exchange_initial_cold", remaining_rounds=remaining,
                                **base)
        if last_change_round_index not in (None, 0) and current_round <= last_change_round_index + exchange_cold:
            remaining = last_change_round_index + exchange_cold - current_round + 1
            return self._result([], status="blocked", reason="switch_cooldown",
                                blocked_by="exchange_cold", remaining_rounds=remaining,
                                **base)
        return self._result([], status="allowed", reason="switch_cooldown_passed",
                            remaining_rounds=0, **base)

    def departure(self, cause, entered_turn, current_turn, charging, rooted=False):
        """Check departure eligibility; an allowed result does not perform it."""
        if not isinstance(cause, str) or cause not in {*EFFECT_TERMS, "voluntary", "faint"}:
            raise ValueError("Unknown departure cause")
        _integer(current_turn, "current_turn")
        if entered_turn is not None:
            _integer(entered_turn, "entered_turn")
            if entered_turn > current_turn:
                raise ValueError("Entry cannot occur after the current turn")
        _boolean(charging, "charging")
        _boolean(rooted, "rooted")
        terms = [3009]
        if cause in EFFECT_TERMS:
            terms.append(EFFECT_TERMS[cause])
        if cause == "faint":
            return self._result(terms, status="allowed", emits_departure=False,
                                reason="力竭下场不属于普通离场；不触发普通离场事件。")
        if rooted:
            return self._result([*terms, 3023], status="immune", emits_departure=False,
                                reason="禁足状态禁止离场。")
        if charging:
            if cause == "voluntary":
                return self._result([*terms, 1007], status="allowed", emits_departure=True,
                                    abandon_charge=True, rule_basis="user_confirmed_20261030",
                                    reason="用户确认主动换人放弃蓄力；强制离场仍受蓄力免疫。")
            return self._result([*terms, 1007], status="immune", emits_departure=False,
                                reason="蓄力期间免疫离场效果。")
        if cause in EFFECT_TERMS:
            if entered_turn is None:
                return self._result(terms, status="unresolved", emits_departure=None,
                                    reason="入场回合未知，无法判断本回合入场免疫。")
            if entered_turn == current_turn:
                return self._result(terms, status="immune", emits_departure=False,
                                    reason="本回合入场的精灵免疫该离场效果。")
        return self._result(terms, status="allowed", emits_departure=True,
                            reason="已知离场资格条件允许；目标选择及完整触发链尚未结算。")

    def _validate_marks(self, marks):
        if not isinstance(marks, dict) or set(marks) != {"positive", "negative"}:
            raise ValueError("Field marks require exactly one positive and one negative slot")
        json.dumps(marks, allow_nan=False)
        used = set()
        for value in marks.values():
            if value is None:
                continue
            if not isinstance(value, dict):
                raise ValueError("A field mark must be an object or None")
            mark_id = _integer(value.get("id"), "mark id", 1)
            _integer(value.get("stacks"), "mark stacks", 1)
            if mark_id not in self._marks or mark_id in used:
                raise ValueError("Mark ID is unknown or appears in both polarity slots")
            used.add(mark_id)

    def transfer_field_marks(self, marks):
        """Return independent incoming field slots; never clear them on switching."""
        self._validate_marks(marks)
        return self._result([3010], status="applied", marks=deepcopy(marks),
                            reason="印记属于场上继承状态；不因精灵离场而清除。",
                            mark_effects_resolved=False)

    def apply_mark(self, marks, mark_id, stacks, polarity=None, stack_policy=None):
        """Apply only an explicitly parameterized stack experiment.

        Classification and stack limits are not asserted as BWIKI facts. A
        different mark already in the same slot always remains unresolved.
        ``stack_policy`` must be {"mode":"add", "cap": int | None}; None cap
        is an explicitly uncapped experiment, never an inferred game default.
        """
        self._validate_marks(marks)
        _integer(mark_id, "mark_id", 1)
        _integer(stacks, "stacks", 1)
        if mark_id not in self._marks:
            raise ValueError("Unknown mark ID; classification cannot be guessed")
        base = self._result([3010], status="unresolved", marks=deepcopy(marks),
                            mark_id=mark_id, mark_definition=deepcopy(self._marks[mark_id]),
                            mark_effects_resolved=False)
        if polarity is None:
            return base | {"reason": "印记正负分类缺失，不能自动选择槽位。"}
        if polarity not in ("positive", "negative"):
            raise ValueError("Unknown mark polarity")
        other = marks["negative" if polarity == "positive" else "positive"]
        if other is not None and other["id"] == mark_id:
            raise ValueError("Mark polarity conflicts with existing placement")
        current = marks[polarity]
        if current is not None and current["id"] != mark_id:
            return base | {"reason": "同类已有不同印记，覆盖或替换规则尚未核实。"}
        if stack_policy is None:
            return base | {"reason": "层数叠加及上限未指定，不能自动假定无上限。"}
        if not isinstance(stack_policy, dict) or set(stack_policy) != {"mode", "cap"} or stack_policy["mode"] != "add":
            raise ValueError("Only explicit add/cap mark experiments are supported")
        cap = stack_policy["cap"]
        if cap is not None:
            _integer(cap, "cap", 1)
        before = current["stacks"] if current else 0
        if cap is not None and before > cap:
            raise ValueError("Existing mark count exceeds the supplied cap")
        after = before + stacks
        if cap is not None:
            after = min(after, cap)
        result = deepcopy(marks)
        result[polarity] = {**deepcopy(current or {}), "id": mark_id, "stacks": after}
        return base | {"status": "applied", "marks": result,
                       "reason": "仅按调用者明确提供的分类与层数策略更新；未结算印记效果。",
                       "assumptions": {"polarity": polarity, "stack_policy": deepcopy(stack_policy)},
                       "polarity_and_stacking_verified": False}

    def swift_first_slot(self, slots, energy):
        """Find the first affordable Swift slot after a voluntary switch.

        Caller-supplied effective costs and Swift flags must already account for
        their dependencies; None represents unknown, not false or zero. This
        selector does not execute the selected skill or any entry effect.
        """
        _integer(energy, "energy")
        if not isinstance(slots, list) or len(slots) != 4:
            raise ValueError("Swift selection requires four ordered slots, including empty slots")
        for slot in slots:
            if slot is None:
                continue
            if not isinstance(slot, dict):
                raise ValueError("Skill slot must be an object or None")
            _integer(slot.get("skill_id"), "skill_id", 1)
            if "swift" not in slot or slot["swift"] is not None and type(slot["swift"]) is not bool:
                raise ValueError("Swift flag must be an explicit bool or None")
            if "effective_cost" not in slot:
                raise ValueError("Effective cost must be explicit, including None for unknown")
            if slot["effective_cost"] is not None:
                _integer(slot["effective_cost"], "effective_cost")
        for index, slot in enumerate(slots):
            if slot is None or slot["swift"] is False:
                continue
            if slot["effective_cost"] is not None and slot["effective_cost"] > energy:
                continue
            if slot["swift"] is None or slot["effective_cost"] is None:
                return self._result([1005], status="unresolved", slot=None, skill_id=None,
                                    blocking_slot=index, reason="靠前技能的迅捷或最终能耗未知，不能跳过后直接选后面的技能。")
            return self._result([1005], status="selected", slot=index, skill_id=slot["skill_id"],
                                reason="按保留的技能槽顺序选中首个能量满足的迅捷技能。",
                                effective_cost=slot["effective_cost"], skill_executed=False)
        return self._result([1005], status="none", slot=None, skill_id=None,
                            reason="四个技能槽中没有能量满足的迅捷技能。")
