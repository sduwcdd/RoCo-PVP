"""Source-bound self-cost ledger (气沉丹田 7140170).

The whole description is one unit:
  * 自己回复60%生命      -> hp.restore 60% of declared max HP;
  * 获得物攻+130%        -> stat.modify patk 13 layers x 10%;
  * 每次应对后本技能能耗-3 -> the ledger grows by -3 per successful response;
  * 使用后能耗重置        -> the ledger is cleared after this skill is used.

Percent basis and rounding are *not* in the client table, so they are declared
experimentally (declared_max_hp / floor) and written into every event, never
inferred as a game default.
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

CONFIG = ROOT / "data/rules/reviewed-response-cost-1.json"
CONFIG_SHA256 = 'd996cc1896a4e0f7f46bb4677f54f7d376d6b523ae55eb1c02afa4975f9ae192'
POLICY = "source_bound_response_cost_ledger_v1"
POLICIES = {
    "discount": "minus_three_per_successful_response_for_the_owning_skill_only",
    "floor": "resolved_cost_floored_at_zero",
    "reset": "cleared_after_use_of_the_same_skill",
    "response": "successful_defense_response_of_the_ledger_owner",
    "heal": "declared_max_hp_floor_clamped_to_max_experiment",
}
UNCERTAINTIES = (
    "HP 百分比取整方式与“应对”的精确定义（是否含未命中/被中断）未在客户端表中给出；"
    "换位、退场后账本是否保留未校准；本模块只做显式实验策略，不代表真实校准。",
)
HP_POLICY = {"percentage_basis": "declared_max_hp", "rounding": "floor", "cap": "clamp_to_declared_max"}


@lru_cache(maxsize=2)
def _configuration(stamp):
    raw = CONFIG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONFIG_SHA256:
        raise ValueError("Response-cost configuration changed; source review required")
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
            raise ValueError("Response-cost extracted source changed")
    return data


def research_context():
    return {"response_cost_policy": POLICY, "response_cost_policies": deepcopy(POLICIES),
            "response_cost_uncertainties": list(UNCERTAINTIES)}


def _context(context):
    if context.get("response_cost_policy") != POLICY or context.get("response_cost_policies") != POLICIES:
        raise ValueError("Explicit response-cost ledger policies required")


def _spec(skill_id):
    return _data()["skills"].get(str(skill_id))


def programs(catalog):
    prepared, config = prepare_rules(catalog), _data()
    if prepared.snapshot_id != config["snapshot_id"]:
        raise ValueError("Response-cost snapshot differs")
    result = {}
    for key, row in config["skills"].items():
        record = prepared._rules.skill(int(key))
        if fingerprint(record) != row["record_hash"] or record != row["record"]:
            raise ValueError("Response-cost whole source changed")
        components = row["components"]
        operations = [
            {"op": "hp.restore", "params": {"target": "self", "percent": deepcopy(components["heal"]["percent"])}},
            {"op": "stat.modify", "params": {"target": "self", "attributes": [components["stat"]["attribute"]],
                                             "percent": {"numerator": components["stat"]["layers"] * components["stat"]["percent_per_layer"],
                                                         "denominator": 100}}},
            {"op": "response_cost.plan", "params": {}},
        ]
        program = deepcopy(prepared._rules.program(int(key)))
        program.pop("native_rule", None)
        program.update(status="compiled", blockers=[], operations=operations,
                       response_cost_components=deepcopy(components),
                       response_cost_evidence=deepcopy(row), response_cost_config_hash=CONFIG_SHA256,
                       response_cost_policies=deepcopy(POLICIES), response_cost_uncertainties=list(UNCERTAINTIES),
                       response_kinds=[], executable=False, real_game_verified=False, training_eligible=False)
        result[int(key)] = program
    return result


def _active(state, side):
    team = state["teams"][side]
    return team["members"][team["active_slot"]]


def _ledgers(member):
    ledgers = member.get("response_cost_ledgers")
    if ledgers is None:
        return {}
    if not isinstance(ledgers, dict):
        raise ValueError("Response-cost ledgers must be a mapping")
    for key, row in ledgers.items():
        spec = _spec(key)
        if spec is None:
            raise ValueError("Response-cost ledger references an unreviewed skill")
        components = spec["components"]["cost"]
        if (not isinstance(row, dict) or row.get("policy") != POLICY or row.get("config_sha256") != CONFIG_SHA256
                or row.get("source_skill_id") != int(key) or row.get("source_hash") != spec["record_hash"]
                or row.get("ledger_hash") != fingerprint({k: v for k, v in row.items() if k != "ledger_hash"})
                or not isinstance(row.get("entries"), list)
                or row.get("discount") != components["per_response"] * len(row["entries"])
                or len(set(row["entries"])) != len(row["entries"])
                or not all(isinstance(token, str) and token for token in row["entries"])):
            raise ValueError("Response-cost ledger changed")
    return ledgers


def validate_member(member):
    _ledgers(member)
    return True


def discount(member, skill_id):
    row = _ledgers(member).get(str(skill_id))
    return row["discount"] if row else 0


def resolved_cost(state, side, skill_id, value):
    """Apply the accumulated self discount for this exact skill; floor at zero."""
    spec = _spec(skill_id)
    if spec is None:
        return value
    member = _active(state, side)
    if not member.get("response_cost_ledgers"):
        return value
    if not isinstance(value, int):
        raise ValueError("Response-cost ledger requires an integer resolved cost")
    floor = spec["components"]["cost"]["floor"]
    return max(floor, value + discount(member, skill_id))


def record_response(member, side, *, turn, token):
    """Successful defense response by the ledger owner: -3 for each reviewed owned skill."""
    if not isinstance(token, str) or not token or type(turn) is not int:
        raise ValueError("Response-cost record requires an explicit token and turn")
    slots = member.get("skill_slots") or []
    owned = {int(skill_id) for skill_id in slots if skill_id and _spec(skill_id) is not None}
    if not owned:
        return []
    ledgers = deepcopy(_ledgers(member))
    events = []
    for skill_id in sorted(owned):
        spec = _spec(skill_id)
        row = ledgers.get(str(skill_id)) or {"policy": POLICY, "config_sha256": CONFIG_SHA256,
                                             "source_skill_id": skill_id, "source_hash": spec["record_hash"],
                                             "entries": []}
        if token in row["entries"]:
            continue
        row["entries"] = list(row["entries"]) + [token]
        row["discount"] = spec["components"]["cost"]["per_response"] * len(row["entries"])
        row["ledger_hash"] = fingerprint({k: v for k, v in row.items() if k != "ledger_hash"})
        ledgers[str(skill_id)] = row
        events.append({"op": "response_cost.recorded", "side": side, "member_id": member["member_id"],
                       "source_skill_id": skill_id, "amount": spec["components"]["cost"]["per_response"],
                       "entries": len(row["entries"]), "discount": row["discount"],
                       "response_cost_policy": POLICY})
    member["response_cost_ledgers"] = ledgers
    validate_member(member)
    return events


def consume(member, side, skill_id, *, token):
    """Using the skill resets its accumulated discount back to the base cost."""
    if not isinstance(token, str) or not token:
        raise ValueError("Response-cost consume requires an explicit token")
    spec = _spec(skill_id)
    if spec is None:
        return []
    ledgers = deepcopy(_ledgers(member))
    row = ledgers.pop(str(skill_id), None)
    if not row:
        return []
    if row["entries"]:
        events = [{"op": "response_cost.reset", "side": side, "member_id": member["member_id"],
                   "source_skill_id": int(skill_id), "cleared_entries": len(row["entries"]),
                   "discount_before": row["discount"], "token": token, "response_cost_policy": POLICY}]
    else:
        events = []
    if ledgers:
        member["response_cost_ledgers"] = ledgers
    else:
        member.pop("response_cost_ledgers", None)
    validate_member(member)
    return events


def preflight(program, state, context, damage_resolver=None):
    _preflight_header(program, state, context)
    _context(context)
    if "response_cost_components" not in program:
        raise ValueError("Response-cost plan requires reviewed components")
    return {"status": "preflight", "components": deepcopy(program["response_cost_components"])}


def execute(program, state, context, damage_resolver=None):
    """Run only the reviewed effect ops; the ledger plan op carries no state."""
    preflight(program, state, context, damage_resolver)
    inner = {**context, "hp_policy": deepcopy(HP_POLICY),
             "hp_policy_source": "response_cost_runtime_experiment_declared"}
    inner["_response_cost_policy"] = deepcopy(POLICIES)
    runnable = {**program, "operations": [op for op in program["operations"] if op["op"] in OPS]}
    result = execute_effects(runnable, state, inner)
    for event in result.get("events", []):
        if event.get("op") == "hp.restore":
            event.update(hp_policy=deepcopy(HP_POLICY),
                         hp_policy_uncertainty=UNCERTAINTIES[0])
    result["response_cost_policy"] = POLICY
    result["response_cost_policies"] = deepcopy(POLICIES)
    result["response_cost_uncertainties"] = list(UNCERTAINTIES)
    return result
