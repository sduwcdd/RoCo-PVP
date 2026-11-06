"""Build reviewed configuration for outgoing power suppression (排气 7070260).

Evidence chain read from the parsed client tables:
  7070260.skill_result -> buff 20190470 (cast_moment 24)
  buff 20190470 -> buffbase 2019047 -> param[6] = buff 20641380
  buff 20641380 -> bases 2064138 + 2064139
  base 2064138: param[4] = [20230750, 20230750]  -> two stacks of "技能威力-10"
  base 2064139: param[4] = effect 1004116, param[5] = 12 -> trigger on resisted damage
  effect 1004116: param[1] = 20641380 -> re-applies the same -10 stack pair
  20230750.desc = "技能威力-10", add_max 99
So: install -20, one additional -20 per completed resisted direct attack packet.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "artifacts/unpack_probe_20261025/battle_analysis/tables/parsed"
CATALOG = ROOT / "data/bwiki/20261025T013619+0800/catalog.json"
OUT = ROOT / "data/rules/reviewed-pressure-1.json"

POLICY = "source_bound_outgoing_power_suppression_v1"

catalog = json.loads(CATALOG.read_text(encoding="utf8"))
skill_tab = json.loads((TABLES / "SKILL_CONF.json").read_text(encoding="utf8"))
eff_tab = json.loads((TABLES / "EFFECT_CONF.json").read_text(encoding="utf8"))
buff_tab = json.loads((TABLES / "BUFF_CONF.json").read_text(encoding="utf8"))
base_tab = json.loads((TABLES / "BUFFBASE_CONF.json").read_text(encoding="utf8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fp(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


MID = 7070260
record = catalog["moves"][str(MID)]
game = skill_tab[str(MID)]

evidence = {
    "skill": game,
    "buffs": {k: buff_tab[k] for k in ("20190470", "20641380", "20230750") if k in buff_tab},
    "buff_bases": {k: base_tab[k] for k in ("2019047", "2064138", "2064139", "2023075") if k in base_tab},
    "effects": {k: eff_tab[k] for k in ("1004116",) if k in eff_tab},
}

skills = {
    str(MID): {
        "record_hash": fp(record),
        "record": record,
        "components": {
            "install": {"target": "opponent", "amount": -20, "stack_amount": -10, "stacks": 2, "scope": "all_skills"},
            "escalation": {"per_resisted_packet": -20, "stack_amount": -10, "stacks": 2, "require_resisted": True,
                           "combo_counts_once": True},
            "reset": "on_use_before_install",
        },
        "installation_evidence": evidence,
        "installation_uncertainty": (
            "减伤链以外的数值全部来自客户端表：2064138 明确给出两份 20230750（每份 技能威力-10，合计-20），"
            "2064139 以 param[5]=12 作为受击触发并调用 effect 1004116 再次施加 20641380，与描述“每受到1次抵抗伤害额外-20”一致。"
            "“抵抗伤害”按 属性倍率<1 且未无视抵抗 判定；“不含连击”按一次攻击动作只计一次实现；"
            "buff 2023075 的 trigger_type=12 是否与我的受击判定完全等价、以及离场后是否保留，尚未实战校准。"
        ),
    }
}

config = {
    "schema": "reviewed-pressure-components-1",
    "policy": POLICY,
    "snapshot_id": "20261025T013619+0800",
    "sources": {str(CATALOG.relative_to(ROOT)).replace("\\", "/"): sha(CATALOG)},
    "installation_sources": {
        name: {"path": str((TABLES / f"{name}.json").relative_to(ROOT)).replace("\\", "/"),
               "sha256": sha(TABLES / f"{name}.json")}
        for name in ("SKILL_CONF", "BUFF_CONF", "BUFFBASE_CONF", "EFFECT_CONF")
    },
    "skills": skills,
}

OUT.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
print("written", OUT)
print("config_hash", fp(config))
