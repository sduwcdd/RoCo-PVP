"""Build the b4 wave configs: positional stats 7070170 and neighbor power grant 7070070.

7070170 啮合传递: "自己获得速度+30，本技能位于1号或3号位时额外获得物攻+80%，传动1。"
  证据: BUFF 20010100 = "速度+10"（每层10，add_max 99）=> +30 = 3 层;
        buff 20640740 / 20640750 各带两个 base，2064074/2064075 是位置分支, 21150010 为被动载体。
7070070 联动装置: "使用后两侧技能的威力永久+20，应对防御：变为威力永久+30。"
  证据: skill_result 20640720 + effect 1031131(type 2, param[0]=7070071 子技能)。
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "artifacts/unpack_probe_20261025/battle_analysis/tables/parsed"
FULL_SKILL = ROOT / "artifacts/strength_buff_probe_20261025/mirror/versions/pakchunk4-WindowsNoEditor_2_P/SKILL_CONF.json"
CATALOG = ROOT / "data/bwiki/20261025T013619+0800/catalog.json"

catalog = json.loads(CATALOG.read_text(encoding="utf8"))
parsed = json.loads((TABLES / "SKILL_CONF.json").read_text(encoding="utf8"))
full = json.loads(FULL_SKILL.read_text(encoding="utf8"))
eff = json.loads((TABLES / "EFFECT_CONF.json").read_text(encoding="utf8"))
buff = json.loads((TABLES / "BUFF_CONF.json").read_text(encoding="utf8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fp(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def sources():
    return {str(CATALOG.relative_to(ROOT)).replace("\\", "/"): sha(CATALOG),
            str(FULL_SKILL.relative_to(ROOT)).replace("\\", "/"): sha(FULL_SKILL)}


def installation_sources(names=("SKILL_CONF", "EFFECT_CONF", "BUFF_CONF")):
    return {name: {"path": str((TABLES / f"{name}.json").relative_to(ROOT)).replace("\\", "/"),
                   "sha256": sha(TABLES / f"{name}.json")} for name in names}


# ---- 7070170 positional stats -------------------------------------------------
SLOT_STAT = ROOT / "data/rules/reviewed-slot-stat-1.json"
MID = 7070170
record = catalog["moves"][str(MID)]
game = parsed[str(MID)]
slot_stat = {
    "schema": "reviewed-slot-stat-1",
    "policy": "source_bound_positional_stat_skill_v1",
    "snapshot_id": "20261025T013619+0800",
    "sources": sources(),
    "installation_sources": installation_sources(),
    "skills": {
        str(MID): {
            "record_hash": fp(record),
            "record": record,
            "components": {
                "base_stats": [{"attribute": "spd", "percent": None, "layers": 3, "per_layer": 10,
                                "buff_id": 20010100}],
                "positional_stats": {"slots": [0, 2], "attribute": "patk", "layers": 8, "per_layer": 10,
                                     "buff_id": 20010010},
                "transmission": 1,
                "effect_ids": [row["effect_id"] for row in game["skill_result"]],
            },
            "installation_evidence": {
                "skill_parsed": game,
                "skill_mirror": full.get(str(MID)),
                "catalog_record": record,
                "buffs": {k: buff[k] for k in ("20010100", "20640740", "20640750", "21150010") if k in buff},
                "effects": {k: eff[k] for k in ("1031131",) if k in eff},
            },
            "installation_uncertainty": (
                "位置条件取“按槽位序号 1号位=0、3号位=2”，与相邻选择器同一套索引约定；"
                "速度+30 按 BUFF 20010100 每层+10、三层实现；物攻+80% 按 8 层×10% 实现；"
                "buff 2064074/2064075 两个 base 的具体分工未逐字段解码，因此位置分支只按描述结构实现，未做实战校准。"
            ),
        }
    },
}
SLOT_STAT.write_text(json.dumps(slot_stat, ensure_ascii=False, indent=2) + "\n", encoding="utf8")

# ---- 7070070 neighbor power grant --------------------------------------------
AURA = ROOT / "data/rules/reviewed-adjacent-power-aura-1.json"
aura = json.loads(AURA.read_text(encoding="utf8"))
GRANT = 7070070
grant_record = catalog["moves"][str(GRANT)]
grant_game = parsed[str(GRANT)]
aura["skills"][str(GRANT)] = {
    "record_hash": fp(grant_record),
    "record": grant_record,
    "components": {
        "neighbor_grant": {"amount": 20, "response_amount": 30, "permanent": True,
                           "targets": "both_immediate_slots_without_wrap"},
        "transmission": 0,
        "effect_ids": [row["effect_id"] for row in grant_game["skill_result"]],
    },
    "installation_evidence": {
        "skill_parsed": grant_game,
        "skill_mirror": full.get(str(GRANT)),
        "catalog_record": grant_record,
        "effects": {k: eff[k] for k in ("1031131",) if k in eff},
    },
    "installation_uncertainty": (
        "“应对防御”按本技能的使用被对手攻击命中并成功响应（response_success）判定，+30 走同一账本；"
        "“永久”按不因退场清除、每次使用叠加实现；effect 1031131 子技能 7070071 的逐字段语义未解码，"
        "因此只按描述结构实现并写入事件，未做实战校准。"
    ),
}
AURA.write_text(json.dumps(aura, ensure_ascii=False, indent=2) + "\n", encoding="utf8")


def pin(module_path, digest, marker='CONFIG_SHA256 = "'):
    path = ROOT / module_path
    text = path.read_text(encoding="utf8")
    start = text.index(marker)
    end = text.index('"', start + len(marker))
    path.write_text(text[:start] + marker + digest + text[end:], encoding="utf8")


pin("lab/slot_stat_runtime.py", sha(SLOT_STAT))
pin("lab/adjacent_power_aura_runtime.py", sha(AURA))
print(json.dumps({"slot_stat": sha(SLOT_STAT), "adjacent_power_aura": sha(AURA)}, ensure_ascii=False))
