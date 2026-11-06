"""Carry unpacked buff percentages into the damage preview's stat terms.

The preview panel used to need four hand-typed percentages. This module reads the
reviewed skill -> buff units (already bound to game records) plus the unpacked
buff percentage table, so the panel can offer "use 力量增效 → 我方物攻 +10%".

Sources
  data/rules/reviewed-modifier-source-units-1.json   技能 -> BUFF 单位（91/579 技能，带分数单位）
  data/external/roco_buff_calc_map.json              buff id -> 百分比字段（220 条）
  data/external/skill.json                           技能描述，用于判定作用方（自己/敌方）

Only the four channels the preview understands are exposed: patk / matk / pdef / mdef.
Everything else (速度、威力、受伤、连击) stays out of the preview on purpose.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "data" / "rules"
EXTERNAL = ROOT / "data" / "external"

CHANNELS = ("patk", "matk", "pdef", "mdef")
CALC_FIELDS = {
    "patk": "phyAtkPercent",
    "matk": "magAtkPercent",
    "pdef": "phyDefPercent",
    "mdef": "magDefPercent",
}
SELF_WORDS = ("自己", "自身", "我方")
ENEMY_WORDS = ("敌方", "对手")


class BuffTable:
    """Lazily loaded, immutable view over the reviewed buff units."""

    def __init__(self, rules= RULES, external=EXTERNAL):
        self._rules_path = Path(rules) / "reviewed-modifier-source-units-1.json"
        self._calc_path = Path(external) / "roco_buff_calc_map.json"
        self._skill_path = Path(external) / "skill.json"
        self._loaded = False
        self.moves: dict[str, dict] = {}

    def load(self) -> "BuffTable":
        if self._loaded:
            return self
        rules = json.loads(self._rules_path.read_text(encoding="utf-8"))
        calc = json.loads(self._calc_path.read_text(encoding="utf-8"))
        skills = json.loads(self._skill_path.read_text(encoding="utf-8"))
        for move_id, record in (rules.get("skills") or {}).items():
            buffs = []
            for unit in record.get("buffs") or []:
                buff_id = unit.get("buff_id")
                percents = _percents(unit.get("units") or {}, calc.get(str(buff_id)) or {})
                if not percents:
                    continue
                desc = str((skills.get(str(move_id)) or {}).get("desc") or "")
                buffs.append({
                    "buff_id": buff_id,
                    "name": str(unit.get("raw", {}).get("name") or f"buff {buff_id}"),
                    "type": int(unit.get("type") or 0),
                    "target": _target(desc),
                    "percents": percents,
                    "desc": str(unit.get("raw", {}).get("desc") or "")[:120],
                })
            if buffs:
                self.moves[str(move_id)] = {
                    "move_id": int(move_id),
                    "move_name": str((skills.get(str(move_id)) or {}).get("name") or ""),
                    "buffs": buffs,
                }
        self._loaded = True
        return self

    def for_move(self, move_id) -> list[dict]:
        self.load()
        return list((self.moves.get(str(move_id)) or {}).get("buffs") or [])

    def summary(self) -> dict:
        self.load()
        return {
            "source": {
                "units": str(self._rules_path.relative_to(ROOT)).replace("\\", "/"),
                "percentages": str(self._calc_path.relative_to(ROOT)).replace("\\", "/"),
            },
            "skills": len(self.moves),
            "channels": list(CHANNELS),
            "moves": self.moves,
        }


def _target(desc: str) -> str:
    if any(word in desc for word in ENEMY_WORDS):
        return "opponent"
    if any(word in desc for word in SELF_WORDS):
        return "self"
    return "unknown"


def _percents(units: dict, calc: dict) -> dict[str, float]:
    """Fraction units become percent numbers the preview already sums linearly."""
    out: dict[str, float] = {}
    for channel in CHANNELS:
        value = units.get(channel)
        if isinstance(value, (list, tuple)) and len(value) == 2 and value[1]:
            out[channel] = round(float(value[0]) * 100 / float(value[1]), 4)
        elif isinstance(value, (int, float)):
            out[channel] = float(value)
        elif isinstance(calc.get(CALC_FIELDS[channel]), (int, float)):
            out[channel] = float(calc[CALC_FIELDS[channel]])
    return out


TABLE = BuffTable()


def move_buffs(move_id) -> list[dict]:
    return TABLE.for_move(move_id)


def buff_summary() -> dict:
    return TABLE.summary()
