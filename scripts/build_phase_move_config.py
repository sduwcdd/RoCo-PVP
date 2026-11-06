"""Add 相位移动 7070270 to the reviewed defense config and pin hashes.

Description: "减伤50%，本技能位于1号位或3号位时，额外减伤40%，应对攻击，传动1。"
Base reduction 50% is positional-independent; the extra 40% applies only from
slot 1 or 3 (index 0 or 2). Both come from the skill text and the client record;
the buff base split for the positional branch is not decoded field by field.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "artifacts/unpack_probe_20261025/battle_analysis/tables/parsed"
FULL = ROOT / "artifacts/strength_buff_probe_20261025/mirror/versions/pakchunk4-WindowsNoEditor_2_P/SKILL_CONF.json"
CONFIG = ROOT / "data/rules/reviewed-defense-components-1.json"
MODULE = ROOT / "lab/defense_runtime.py"
MID = 7070270

catalog = json.loads((ROOT / "data/bwiki/20261025T013619+0800/catalog.json").read_text(encoding="utf8"))
parsed = json.loads((TABLES / "SKILL_CONF.json").read_text(encoding="utf8"))
full = json.loads(FULL.read_text(encoding="utf8"))
eff = json.loads((TABLES / "EFFECT_CONF.json").read_text(encoding="utf8"))
buff = json.loads((TABLES / "BUFF_CONF.json").read_text(encoding="utf8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fp(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


data = json.loads(CONFIG.read_text(encoding="utf8"))
record = catalog["moves"][str(MID)]
game = parsed[str(MID)]
data["skills"][str(MID)] = {
    "record_hash": fp(record),
    "raw": record,
    "components": {
        "reduction": {"numerator": 50, "denominator": 100},
        "responses": ["attack"],
        "response_effects": [],
        "shared_cooldown_rounds": 1,
        "reduction_slot_bonus": {"slots": [0, 2], "amount": 40,
                                 "policy": "additive_at_activation_cap_100_experiment"},
        "transmission": 1,
    },
    "installation_evidence": {
        "skill": game,
        "skill_mirror": full.get(str(MID)),
        "effects": {str(row["effect_id"]): eff.get(str(row["effect_id"])) for row in game["skill_result"]},
        "buffs": {k: buff[k] for k in ("20641030", "20641040", "20620060", "21150010") if k in buff},
    },
    "installation_uncertainty": (
        "“位于1号位或3号位”按槽位索引 0 与 2 判定，未命中时只保留基础50%减伤；"
        "两段减伤按加法在激活时快照并封顶100%（沿用既有 reduction_status_count 的实验策略）；"
        "位置分支对应的 buff base 未逐字段解码，未做实战校准。"
    ),
}
CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf8")

file_sha = sha(CONFIG)
canonical = fp(data)
text = MODULE.read_text(encoding="utf8")
line = next(l for l in text.splitlines() if l.startswith("CONFIG_HASH"))
current = line.split("=", 1)[1].strip().strip('"').strip("'")
chosen = file_sha if current == file_sha else canonical
new_text = text.replace(line, f'CONFIG_HASH = "{chosen}"', 1)
MODULE.write_text(new_text, encoding="utf8")
print(json.dumps({"file_sha256": file_sha, "canonical": canonical, "previous": current, "adopted": chosen,
                  "skills": len(data["skills"])}, ensure_ascii=False))
