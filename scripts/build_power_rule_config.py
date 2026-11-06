"""Build reviewed-power-rule-1.json for the five weight/stat-diff power skills."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARSED = ROOT / "artifacts/unpack_probe_20261025/battle_analysis/tables/parsed"
CATALOG = ROOT / "data/bwiki/20261025T013619+0800/catalog.json"
CONFIG = ROOT / "data/rules/reviewed-power-rule-1.json"

sk = json.loads((PARSED / "SKILL_CONF.json").read_text(encoding="utf8"))
catalog = json.loads(CATALOG.read_text(encoding="utf8"))

SKILLS = {
    "7160150": {"rule": 35, "stat": None, "bucket": 10},
    "7020990": {"rule": 35, "stat": None, "bucket": 10},
    "7021000": {"rule": 35, "stat": None, "bucket": 10},
    "7150250": {"rule": 38, "stat": "spd", "bucket": None},
    "7080320": {"rule": 38, "stat": "pdef", "bucket": None},
}


def fp(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


skills = {}
for mid, spec in SKILLS.items():
    game = sk[mid]
    raw = catalog["moves"][mid]
    entry = {
        "record_hash": fp(raw),
        "raw": raw,
        "rule": spec["rule"],
        "stat": spec["stat"],
        "bucket": spec["bucket"],
        "dam_para": game["dam_para"],
        "energy_cost": game["energy_cost"],
        "skill_dam_type": game["skill_dam_type"],
        "installation_evidence": {"skill": game},
        "installation_uncertainty": (
            "rule 35: bucket width 10 kg per level is experimental (no weight field in any unpacked "
            "table or catalog); rule 38: level = floor(max(stat_diff,0)/dam_para[1]), "
            "power = dam_para[0] + dam_para[2+level], experimental."
        ),
    }
    skills[mid] = entry

data = {
    "schema": "reviewed-power-rule-1",
    "policy": "source_bound_damage_rule_35_38_table_power_experiment_v1",
    "skills": skills,
    "installation_sources": ["unpacked SKILL_CONF (snapshot 20261025T013619+0800)", "bwiki catalog"],
}
CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
print("wrote", len(skills), "skills; sha256", hashlib.sha256(CONFIG.read_bytes()).hexdigest())
