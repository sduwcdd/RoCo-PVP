"""damage_rule 35/38 power stage: weight-difference and stat-difference table lookups.

Evidence (unpacked SKILL_CONF, snapshot 20261025T013619+0800):
- rule 35 (weight): 7160150 砂糖弹球 dam_para [0,20,40,60,80,100,120,0] "双方体重差越大";
  7020990 吨位压制 [0,160,140,120,100,90,80,1] "敌方体重越低"; 7021000 以重制重 [0,80,90,100,120,140,160,1] "敌方体重越高".
  Shape: index 0 unused, indices 1..6 = power per bucket, index 7 = quantity flag (0 = |diff|, 1 = enemy weight).
- rule 38 (stat diff): 7150250 闪击 [60,6,0,20,40,60,80,90,100,110,120,130,140] "速度比敌方越高";
  7080320 鸣沙陷阱 [60,4,0,20,...] "物防比敌方越高".
  Shape: index 0 = base power; index 1 matches the defense/speed attribute numbers (4/6),
  but its wire semantics are unproven. It provides no evidence for /4 or /6 buckets.
  Indices 2..12 contain the additive table per level.

Uncalibrated parts (explicit, not fabricated):
- weight bucket unit: no weight field exists in any unpacked table or the catalog forms
  (forms carry hp/patk/matk/pdef/mdef/spd only). Bucket width defaults to 10 kg per bucket;
  battle members expose an explicit "weight" field so calibrated data can be supplied.
- stat-diff buckets use the source-bound third-party 30-point candidate; not official calibration.
"""
import hashlib
import json
from pathlib import Path
from functools import lru_cache
from math import ceil

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data/rules/reviewed-power-rule-1.json"
POLICY = "source_bound_damage_rule_35_38_table_power_experiment_v1"
POLICIES = {
    "rule35_bucket": "weight_quantity_bucketed_10_per_level_experiment",
    "rule38_level": "positive_stat_difference_ceil_30_vendor_candidate_v2",
    "weight_source": "battle_member_weight_field_default_zero_uncalibrated",
}
UNCERTAINTIES = (
    "No unpacked table or catalog field carries pet weight; bucket width 10 kg and the "
    "stat-diff step interpretation are experimental and uncalibrated until a weight source "
    "or Lua evidence is provided. Stat-difference buckets now use a separately identified third-party candidate.",
)


def _configuration(stamp):
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    if data.get("schema") != "reviewed-power-rule-1":
        raise ValueError("Power rule configuration schema mismatch")
    return data


def _data():
    return _configuration(CONFIG.stat().st_mtime_ns)


def fingerprint(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def research_context():
    return {"power_rule": {"policy": POLICY, "policies": deepcopy(POLICIES)}}


def deepcopy(value):
    import copy
    return copy.deepcopy(value)


def validate_member(member):
    weight = member.get("weight", 0)
    if type(weight) not in (int, float) or weight < 0:
        raise ValueError("Battle member weight must be a nonnegative number")
    return []


@lru_cache(maxsize=2)
def _candidate_file_hash(path, size, stamp):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stat_difference_candidate():
    candidate = _data().get('stat_difference_candidate') or {}
    path = (ROOT / candidate.get('source_path', '')).resolve()
    if (not path.is_relative_to(ROOT) or not path.is_file() or candidate.get('step') != 30
            or candidate.get('positive_rounding') != 'ceil' or candidate.get('cap_level') != 10
            or candidate.get('powers') != [60,80,100,120,140,150,160,170,180,190,200]
            or candidate.get('source_sha256') != 'a894f23db520d0c1f71e8f2fd04a689b865dca56ad362ba21d4ee3bf5c7d2181'):
        raise ValueError('属性差档位缺少已核对的第三方候选配置')
    stat = path.stat()
    if _candidate_file_hash(str(path), stat.st_size, stat.st_mtime_ns) != candidate['source_sha256']:
        raise ValueError('属性差档位候选来源文件已变化，需重新核对')
    return deepcopy(candidate)


def rule_power(attacker, defender, skill_id, base_power, context=None):
    """Return the rule-computed power or None when the skill has no rule 35/38."""
    data = _data()
    spec = data["skills"].get(str(skill_id))
    if spec is None:
        return base_power
    rule = spec["rule"]
    para = spec["dam_para"]
    if rule == 35:
        flag = para[7]
        if flag == 0:
            qty = abs((attacker.get("weight", 0) or 0) - (defender.get("weight", 0) or 0))
        elif flag == 1:
            qty = defender.get("weight", 0) or 0
        else:
            raise ValueError("Unsupported rule-35 weight flag")
        level = min(5, int(qty // spec.get("bucket", 10)))
        power = para[1 + level]
    elif rule == 38:
        stat = spec["stat"]
        diff = (attacker.get(stat, 0) or 0) - (defender.get(stat, 0) or 0)
        candidate = stat_difference_candidate()
        if para[1] != {'pdef':4, 'spd':6}.get(stat) or spec.get('expected_native_parameter_1') != para[1]:
            raise ValueError('属性差参数的属性选择器不符，不能作为档宽')
        level = min(candidate['cap_level'], max(0, ceil(diff / candidate['step'])))
        power = para[0] + para[2 + level]
        if power != candidate['powers'][level]:
            raise ValueError('原生属性差威力表与候选不符')
    else:
        raise ValueError("Unsupported damage rule in power rule config")
    return int(power)


def resolve(program, state, context):
    """Resolve the rule 35/38 attack into an executable damage op (mirrors adjacent_power.resolve)."""
    program = deepcopy(program)
    spec = program["power_rule_components"]
    mid = program["game_id"]
    attacker, defender = state["self"], state["opponent"]
    power = rule_power(attacker, defender, mid, program.get("power", 0) or 0, context=context)
    raw = spec["raw"]
    program["operations"] = [{"op": "damage", "params": {
        "target": "opponent", "kind": raw.get("kind", "physical"),
        "power": int(power), "type": raw.get("type", "普通系")}}]
    program["resolved_rule_power"] = int(power)
    return program


def programs(prepared):
    data = _data()
    out = {}
    for mid in sorted(data["skills"]):
        spec = data["skills"][mid]
        record = prepared._rules._catalog["moves"][mid]
        program = deepcopy(prepared._rules.program(int(mid)))
        program.pop("native_rule", None)
        program.update(
            status="compiled",
            blockers=[],
            power_rule_components=deepcopy(spec),
            power_rule_policy=POLICY,
            operations=deepcopy(program.get("operations") or program.get("program", {}).get("operations", [])),
        )
        if not program["operations"]:
            program["operations"] = [{"op": "power_rule.plan", "params": {}}]
        out[int(mid)] = program
    return out
