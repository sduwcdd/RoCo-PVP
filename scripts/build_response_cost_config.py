"""Build reviewed configuration for the self-cost ledger of 气沉丹田 7140170.

Evidence read from the full client table (the simplified parsed table omits the
layer count): SKILL_CONF[7140170].skill_result carries
  {effect 1005060, buff_group_level 1}   -> 自己回复60%生命
  {effect 20010010, buff_group_level 13} -> 物攻 +13 layers x 10% (+130%)
BUFF_CONF[20010010].desc = "物攻+10%", add_max 99 -> one layer is +10%.
energy_rule 9 / energy_cost [10, -3, 1, 1] is the self cost ledger:
  base 10, -3 per response, reset after use.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "artifacts/unpack_probe_20261025/battle_analysis/tables/parsed"
FULL_SKILL = ROOT / "artifacts/strength_buff_probe_20261025/mirror/versions/pakchunk4-WindowsNoEditor_2_P/SKILL_CONF.json"
CATALOG = ROOT / "data/bwiki/20261025T013619+0800/catalog.json"
OUT = ROOT / "data/rules/reviewed-response-cost-1.json"
POLICY = "source_bound_response_cost_ledger_v1"

catalog = json.loads(CATALOG.read_text(encoding="utf8"))
full = json.loads(FULL_SKILL.read_text(encoding="utf8"))
eff = json.loads((TABLES / "EFFECT_CONF.json").read_text(encoding="utf8"))
buff = json.loads((TABLES / "BUFF_CONF.json").read_text(encoding="utf8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fp(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


MID = 7140170
record = catalog["moves"][str(MID)]
game = full[str(MID)]
results = {int(row["effect_id"]): row["buff_group_level"] for row in game["skill_result"]}
heal_level, stat_level = results[1005060], results[20010010]

skills = {
    str(MID): {
        "record_hash": fp(record),
        "record": record,
        "components": {
            "heal": {"percent": {"numerator": 60, "denominator": 100}, "effect_id": 1005060,
                     "buff_group_level": heal_level},
            "stat": {"attribute": "patk", "layers": stat_level, "percent_per_layer": 10,
                     "buff_id": 20010010, "effect_id": 20010010},
            "cost": {"per_response": -3, "floor": 0, "reset": "on_use", "energy_rule": game.get("energy_rule")},
        },
        "installation_evidence": {
            "skill_full": game,
            "skill_parsed": json.loads((TABLES / "SKILL_CONF.json").read_text(encoding="utf8"))[str(MID)],
            "effects": {k: eff[k] for k in ("1005060",) if k in eff},
            "buffs": {k: buff[k] for k in ("20010010",) if k in buff},
        },
        "installation_uncertainty": (
            "回复比例 60% 与物攻 13 层（+130%）来自完整表 skill_result.buff_group_level；"
            "百分比按 declared_max_hp 取整方式未在客户端表中出现，本实现显式声明为 floor 并在事件中记录 policy；"
            "“每次应对后-3”的应对判定沿用成功响应防御；能耗下限 0；重置时机取“使用后”，"
            "跨回合/换位后是否保留尚未实战校准。"
        ),
    }
}

config = {
    "schema": "reviewed-response-cost-1",
    "policy": POLICY,
    "snapshot_id": "20261025T013619+0800",
    "sources": {str(CATALOG.relative_to(ROOT)).replace("\\", "/"): sha(CATALOG),
                str(FULL_SKILL.relative_to(ROOT)).replace("\\", "/"): sha(FULL_SKILL)},
    "installation_sources": {
        name: {"path": str((TABLES / f"{name}.json").relative_to(ROOT)).replace("\\", "/"),
               "sha256": sha(TABLES / f"{name}.json")} for name in ("SKILL_CONF", "EFFECT_CONF", "BUFF_CONF")
    },
    "skills": skills,
}

OUT.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
print("written", OUT, "heal_level", heal_level, "stat_level", stat_level)
print("file_sha256", sha(OUT))
