"""Build reviewed configuration for the adjacency cost aura of 轴承支撑 7070060.

Description (client table, desc_id 1033 = 传动):
  "主动：本技能被动永久额外-1能耗，被动：两侧技能能耗-1，传动1。"
Current patch table says energy_cost [6] (the older mirror build says [3]); the
catalog `energy` field also says 6, so the current value is taken as authoritative.
The three applied effects (21150010, 21200010, 20640610) are recorded as evidence
carriers of the own-growth, the adjacency aura and the transmission tag.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "artifacts/unpack_probe_20261025/battle_analysis/tables/parsed"
FULL_SKILL = ROOT / "artifacts/strength_buff_probe_20261025/mirror/versions/pakchunk4-WindowsNoEditor_2_P/SKILL_CONF.json"
CATALOG = ROOT / "data/bwiki/20261025T013619+0800/catalog.json"
OUT = ROOT / "data/rules/reviewed-adjacent-cost-1.json"
POLICY = "source_bound_adjacent_cost_aura_v1"

catalog = json.loads(CATALOG.read_text(encoding="utf8"))
parsed = json.loads((TABLES / "SKILL_CONF.json").read_text(encoding="utf8"))
full = json.loads(FULL_SKILL.read_text(encoding="utf8"))
eff = json.loads((TABLES / "EFFECT_CONF.json").read_text(encoding="utf8"))

MID = 7070060
record = catalog["moves"][str(MID)]
game, mirror = parsed[str(MID)], full[str(MID)]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fp(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


skills = {
    str(MID): {
        "record_hash": fp(record),
        "record": record,
        "components": {
            "base_cost": game["energy_cost"][0],
            "own_cost": {"per_use": -1, "permanent": True, "floor": 0, "scope": "this_skill_only"},
            "adjacent_cost": {"amount": -1, "targets": "both_immediate_slots_without_wrap"},
            "transmission": 1,
            "effect_ids": [row["effect_id"] for row in game["skill_result"]],
        },
        "installation_evidence": {
            "skill_parsed": game,
            "skill_mirror": mirror,
            "catalog_record": record,
            "effects": {str(row["effect_id"]): eff.get(str(row["effect_id"])) for row in game["skill_result"]},
            "cost_version_note": {
                "parsed_and_catalog": game["energy_cost"][0],
                "older_mirror_build": mirror["energy_cost"][0],
                "adopted": game["energy_cost"][0],
            },
        },
        "installation_uncertainty": (
            "相邻定义取“按槽位序号相邻、不环绕”，边缘槽位只有实际存在的一侧邻居；客户端表未给出环绕规则。"
            "“本技能被动永久额外-1能耗”按每次成功使用本技能永久-1、可叠加、下限0实现；"
            "该永久减费是否在退场/换位后保留、以及是否对替换进同一槽位的技能生效，尚无实战证据。"
            "传动1 只作为标签记录，未参与任何威力公式。"
        ),
    }
}

config = {
    "schema": "reviewed-adjacent-cost-1",
    "policy": POLICY,
    "snapshot_id": "20261025T013619+0800",
    "sources": {str(CATALOG.relative_to(ROOT)).replace("\\", "/"): sha(CATALOG),
                str(FULL_SKILL.relative_to(ROOT)).replace("\\", "/"): sha(FULL_SKILL)},
    "installation_sources": {
        name: {"path": str((TABLES / f"{name}.json").relative_to(ROOT)).replace("\\", "/"),
               "sha256": sha(TABLES / f"{name}.json")} for name in ("SKILL_CONF", "EFFECT_CONF")
    },
    "skills": skills,
}
OUT.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
print("written", OUT)
print("file_sha256", sha(OUT))
