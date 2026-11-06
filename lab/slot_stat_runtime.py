"""Source-bound positional stat skill (啮合传递 7070170).

Whole description: "自己获得速度+30，本技能位于1号或3号位时额外获得物攻+80%，传动1。"
The unconditional part is a reviewed stat op; the positional part is decided at
execution time from the selected slot, never guessed when the slot is unknown.
传动1 is a recorded tag only.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from lab.effect_runtime import OPS, _preflight_header, execute_effects
from lab.game_runtime_defaults import ROOT
from lab.phase_config import fingerprint
from lab.prepared_rules import prepare_rules

CONFIG = ROOT / "data/rules/reviewed-slot-stat-1.json"
CONFIG_SHA256 = 'bea39de008947a9f38b4f495469cf017d06bdc263450c508d3676da6c9d6529b'
POLICY = "source_bound_positional_stat_skill_v1"
POLICIES = {
    "position": "slot_index_0_and_2_are_the_source_one_and_three_positions",
    "stats": "layers_times_ten_percent_per_layer_summed_into_one_modifier",
    "unknown_slot": "no_positional_stat_is_applied_when_the_slot_is_unknown",
    "transmission": "recorded_tag_only_no_further_formula",
}
UNCERTAINTIES = (
    "位置分支的 buff base 分工未逐字段解码；1号位=槽位0、3号位=槽位2 是索引约定；未做实战校准。",
)


@lru_cache(maxsize=2)
def _configuration(stamp):
    raw = CONFIG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONFIG_SHA256:
        raise ValueError("Slot-stat configuration changed; source review required")
    return json.loads(raw)


@lru_cache(maxsize=16)
def _source_hash(path, size, stamp):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _data():
    data = _configuration(CONFIG.stat().st_mtime_ns)
    for relative, expected in data["sources"].items():
        path = (ROOT / relative).resolve()
        stat = path.stat()
        if not path.is_relative_to(ROOT) or _source_hash(str(path), stat.st_size, stat.st_mtime_ns) != expected:
            raise ValueError("Slot-stat extracted source changed")
    return data


def research_context():
    return {"slot_stat_policy": POLICY, "slot_stat_policies": deepcopy(POLICIES),
            "slot_stat_uncertainties": list(UNCERTAINTIES)}


def _context(context):
    if context.get("slot_stat_policy") != POLICY or context.get("slot_stat_policies") != POLICIES:
        raise ValueError("Explicit positional stat policies required")


def _spec(skill_id):
    return _data()["skills"].get(str(skill_id))


def _stat_op(attribute, layers, per_layer):
    return {"op": "stat.modify", "params": {"target": "self", "attributes": [attribute],
                                            "percent": {"numerator": layers * per_layer, "denominator": 100}}}


def programs(catalog):
    prepared, config = prepare_rules(catalog), _data()
    if prepared.snapshot_id != config["snapshot_id"]:
        raise ValueError("Slot-stat snapshot differs")
    result = {}
    for key, row in config["skills"].items():
        record = prepared._rules.skill(int(key))
        if fingerprint(record) != row["record_hash"] or record != row["record"]:
            raise ValueError("Slot-stat whole source changed")
        components = row["components"]
        operations = [_stat_op(item["attribute"], item["layers"], item["per_layer"])
                      for item in components["base_stats"]]
        operations.append({"op": "slot_stat.plan", "params": {}})
        program = deepcopy(prepared._rules.program(int(key)))
        program.pop("native_rule", None)
        program.update(status="compiled", blockers=[], operations=operations,
                       slot_stat_components=deepcopy(components), slot_stat_evidence=deepcopy(row),
                       slot_stat_config_hash=CONFIG_SHA256, slot_stat_policies=deepcopy(POLICIES),
                       slot_stat_uncertainties=list(UNCERTAINTIES), response_kinds=[], executable=False,
                       real_game_verified=False, training_eligible=False)
        result[int(key)] = program
    return result


def validate_member(member):
    ledger = member.get("slot_stat_runtime")
    if ledger is None:
        return True
    if (not isinstance(ledger, dict) or ledger.get("policy") != POLICY
            or ledger.get("config_sha256") != CONFIG_SHA256
            or ledger.get("hash") != fingerprint({k: v for k, v in ledger.items() if k != "hash"})
            or not isinstance(ledger.get("tokens"), list)
            or len(set(ledger["tokens"])) != len(ledger["tokens"])):
        raise ValueError("Slot-stat runtime ledger changed")
    return True


def positional_op(program, slot):
    """The reviewed positional stat, only for a known reviewed slot."""
    components = program["slot_stat_components"]
    spec = components.get("positional_stats")
    if spec is None or type(slot) is not int or slot not in spec["slots"]:
        return None
    return _stat_op(spec["attribute"], spec["layers"], spec["per_layer"])


def preflight(program, state, context, damage_resolver=None):
    _preflight_header(program, state, context)
    _context(context)
    if "slot_stat_components" not in program:
        raise ValueError("Slot-stat plan requires reviewed components")
    return {"status": "preflight", "components": deepcopy(program["slot_stat_components"])}


def execute(program, state, context, damage_resolver=None):
    preflight(program, state, context, damage_resolver)
    slot = context.get("selected_skill_slot")
    inner = {**context}
    runnable = {**program, "operations": [op for op in program["operations"] if op["op"] in OPS]}
    result = execute_effects(runnable, state, inner)
    if result.get("status") != "applied":
        return result
    positional = positional_op(program, slot)
    if positional is None:
        result["events"].append({"op": "slot_stat.positional_skipped",
                                 "reason": "unknown_or_non_matching_slot", "slot": slot,
                                 "slot_stat_policy": POLICY})
        return result
    nested = execute_effects({**program, "operations": [positional]}, result["state"], inner)
    if nested.get("status") != "applied":
        raise ValueError("Positional stat failed: " + "; ".join(nested["blockers"]))
    result["state"] = nested["state"]
    result["events"].extend(nested["events"])
    result["events"].append({"op": "slot_stat.positional_applied", "slot": slot,
                             "attribute": program["slot_stat_components"]["positional_stats"]["attribute"],
                             "percent": positional["params"]["percent"], "slot_stat_policy": POLICY})
    result["slot_stat_policy"] = POLICY
    result["slot_stat_policies"] = deepcopy(POLICIES)
    result["slot_stat_uncertainties"] = list(UNCERTAINTIES)
    return result
