"""Build 减压阀 7070250 config and pin its file hash into the runtime module."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "artifacts/unpack_probe_20261025/battle_analysis/tables/parsed"
FULL_SKILL = ROOT / "artifacts/strength_buff_probe_20261025/mirror/versions/pakchunk4-WindowsNoEditor_2_P/SKILL_CONF.json"
CATALOG = ROOT / "data/bwiki/20261025T013619+0800/catalog.json"
OUT = ROOT / "data/rules/reviewed-adjacent-power-aura-1.json"
MODULE = ROOT / "lab/adjacent_power_aura_runtime.py"

catalog = json.loads(CATALOG.read_text(encoding="utf8"))
parsed = json.loads((TABLES / "SKILL_CONF.json").read_text(encoding="utf8"))
full = json.loads(FULL_SKILL.read_text(encoding="utf8"))
eff = json.loads((TABLES / "EFFECT_CONF.json").read_text(encoding="utf8"))

MID = 7070250
record = catalog["moves"][str(MID)]
game, mirror = parsed[str(MID)], full.get(str(MID))


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
            "base_power": game["dam_para"][0],
            "own_power": {"per_use": 20, "permanent": True, "scope": "this_skill_only"},
            "adjacent_power": {"amount": 10, "targets": "both_immediate_slots_without_wrap"},
            "transmission": 1,
            "effect_ids": [row["effect_id"] for row in game["skill_result"]],
        },
        "installation_evidence": {
            "skill_parsed": game,
            "skill_mirror": mirror,
            "catalog_record": record,
            "effects": {str(row["effect_id"]): eff.get(str(row["effect_id"])) for row in game["skill_result"]},
        },
        "installation_uncertainty": (
            "“两侧技能威力+10”按按槽位序号相邻、不环绕实现；本技能自身永久+20 每次使用累加；"
            "环与退场后的保留规则、以及威力加总在其他修正中的先后顺序缺少客户端证据。"
        ),
    }
}

config = {
    "schema": "reviewed-adjacent-power-aura-1",
    "policy": "source_bound_adjacent_power_aura_v1",
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
digest = sha(OUT)

text = MODULE.read_text(encoding="utf8")
old = 'CONFIG_SHA256 = "PENDING"'
assert text.count(old) == 1
MODULE.write_text(text.replace(old, f'CONFIG_SHA256 = "{digest}"'), encoding="utf8")
print("written", OUT)
print("file_sha256", digest)
