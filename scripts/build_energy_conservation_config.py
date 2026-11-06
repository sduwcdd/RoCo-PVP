"""Add 能量守恒 7070080 to the defense config and sync hashes."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "artifacts/unpack_probe_20261025/battle_analysis/tables/parsed"
FULL = ROOT / "artifacts/strength_buff_probe_20261025/mirror/versions/pakchunk4-WindowsNoEditor_2_P/SKILL_CONF.json"
CONFIG = ROOT / "data/rules/reviewed-defense-components-1.json"
MODULE = ROOT / "lab/defense_runtime.py"
MID = 7070080


def fp(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


catalog = json.loads((ROOT / "data/bwiki/20261025T013619+0800/catalog.json").read_text(encoding="utf8"))
parsed = json.loads((TABLES / "SKILL_CONF.json").read_text(encoding="utf8"))
full = json.loads(FULL.read_text(encoding="utf8"))
eff = json.loads((TABLES / "EFFECT_CONF.json").read_text(encoding="utf8"))
buff = json.loads((TABLES / "BUFF_CONF.json").read_text(encoding="utf8"))

data = json.loads(CONFIG.read_text(encoding="utf8"))
record = catalog["moves"][str(MID)]
game = parsed[str(MID)]
data["skills"][str(MID)] = {
    "record_hash": fp(record),
    "raw": record,
    "components": {
        "reduction": {"numerator": 80, "denominator": 100},
        "responses": ["attack"],
        "response_effects": [{"op": "adjacent_cost.grant", "target": "self", "amount": -1}],
        "shared_cooldown_rounds": 1,
        "transmission": 1,
    },
    "installation_evidence": {
        "skill": game,
        "skill_mirror": full.get(str(MID)),
        "effects": {str(row["effect_id"]): eff.get(str(row["effect_id"])) for row in game["skill_result"]},
        "buffs": {k: buff[k] for k in ("20640730", "20110310", "20620060") if k in buff},
    },
    "installation_uncertainty": (
        "应对后两侧永久-1能耗按相邻槽位授予账本实现（每次应对再-1，可叠加）；"
        "子技能7070081为应对变体，效果等价不另立条目。"
    ),
}
CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf8")

file_sha = hashlib.sha256(CONFIG.read_bytes()).hexdigest()
canonical = fp(data)
text = MODULE.read_text(encoding="utf8")
line = next(l for l in text.splitlines() if l.startswith("CONFIG_HASH"))
current = line.split("=", 1)[1].strip().strip('"').strip("'")
chosen = file_sha if current == file_sha else canonical
MODULE.write_text(text.replace(line, f'CONFIG_HASH = "{chosen}"', 1), encoding="utf8")
print(json.dumps({"file_sha256": file_sha, "canonical": canonical, "adopted": chosen,
                  "previous": current, "skills": len(data["skills"])}))
