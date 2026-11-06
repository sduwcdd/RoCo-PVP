"""Source-bound adjacency cost aura and permanent own discount (轴承支撑 7070060).

Whole description:
  * 主动：本技能被动永久额外-1能耗 -> every committed use permanently lowers this
    skill's own cost by 1 (stacking, floored at 0);
  * 被动：两侧技能能耗-1           -> while the source skill occupies its slot, the
    skills in the immediately adjacent slots cost 1 less;
  * 传动1                          -> recorded as a tag only, never used in a formula.

Adjacency is by slot index without wrap; an edge slot simply has one neighbour.
Nothing here infers an edge-wrap rule, a cost floor other than the declared one,
or any power effect.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from lab.game_runtime_defaults import ROOT
from lab.phase_config import fingerprint
from lab.prepared_rules import prepare_rules

CONFIG = ROOT / "data/rules/reviewed-adjacent-cost-1.json"
CONFIG_SHA256 = '35656eec1d73621e3a335b27ef1c37c8255b7a7b8e474cfd38b55d70dac95a7c'
POLICY = "source_bound_adjacent_cost_aura_v1"
POLICIES = {
    "adjacency": "immediate_neighbours_by_slot_index_without_wrap_edge_slots_use_existing_neighbours",
    "aura": "always_on_while_the_source_skill_occupies_its_slot",
    "own_growth": "minus_one_permanent_per_committed_use_floor_zero",
    "own_scope": "the_source_skill_cost_only_never_its_neighbours",
    "cost": "sum_reviewed_sources_then_floor_at_zero",
    "transmission": "recorded_tag_only_no_power_formula",
}
UNCERTAINTIES = (
    "环绕是否属于相邻、永久减费是否在退场/换位后保留、替换进同一槽位的技能是否继承永久减费，"
    "客户端表均未给出；本模块只用显式实验策略，未做真实校准。",
)


@lru_cache(maxsize=2)
def _configuration(stamp):
    raw = CONFIG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONFIG_SHA256:
        raise ValueError("Adjacent-cost configuration changed; source review required")
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
            raise ValueError("Adjacent-cost extracted source changed")
    return data


def research_context():
    return {"adjacent_cost_policy": POLICY, "adjacent_cost_policies": deepcopy(POLICIES),
            "adjacent_cost_uncertainties": list(UNCERTAINTIES)}


def _context(context):
    if context.get("adjacent_cost_policy") != POLICY or context.get("adjacent_cost_policies") != POLICIES:
        raise ValueError("Explicit adjacent-cost aura policies required")


def _spec(skill_id):
    return _data()["skills"].get(str(skill_id))


def programs(catalog):
    prepared, config = prepare_rules(catalog), _data()
    if prepared.snapshot_id != config["snapshot_id"]:
        raise ValueError("Adjacent-cost snapshot differs")
    result = {}
    for key, row in config["skills"].items():
        record = prepared._rules.skill(int(key))
        if fingerprint(record) != row["record_hash"] or record != row["record"]:
            raise ValueError("Adjacent-cost whole source changed")
        program = deepcopy(prepared._rules.program(int(key)))
        program.pop("native_rule", None)
        program.update(status="compiled", blockers=[], operations=[{"op": "adjacent_cost.plan", "params": {}}],
                       adjacent_cost_components=deepcopy(row["components"]),
                       adjacent_cost_evidence=deepcopy(row), adjacent_cost_config_hash=CONFIG_SHA256,
                       adjacent_cost_policies=deepcopy(POLICIES),
                       adjacent_cost_uncertainties=list(UNCERTAINTIES), response_kinds=[], executable=False,
                       real_game_verified=False, training_eligible=False)
        result[int(key)] = program
    return result


def _active(state, side):
    team = state["teams"][side]
    return team["members"][team["active_slot"]]


def _ledgers(member):
    ledgers = member.get("adjacent_cost_ledgers")
    if ledgers is None:
        return {}
    if not isinstance(ledgers, dict):
        raise ValueError("Adjacent-cost ledgers must be a mapping")
    for key, row in ledgers.items():
        spec = _spec(key)
        if spec is None:
            raise ValueError("Adjacent-cost ledger references an unreviewed skill")
        per_use = spec["components"]["own_cost"]["per_use"]
        if (not isinstance(row, dict) or row.get("policy") != POLICY or row.get("config_sha256") != CONFIG_SHA256
                or row.get("source_skill_id") != int(key) or row.get("source_hash") != spec["record_hash"]
                or row.get("ledger_hash") != fingerprint({k: v for k, v in row.items() if k != "ledger_hash"})
                or type(row.get("uses")) is not int or row["uses"] < 0
                or not isinstance(row.get("tokens"), list) or len(row["tokens"]) != row["uses"]
                or len(set(row["tokens"])) != len(row["tokens"])
                or not all(isinstance(token, str) and token for token in row["tokens"])
                or row.get("discount") != per_use * row["uses"]):
            raise ValueError("Adjacent-cost ledger changed")
    return ledgers


def validate_member(member):
    _ledgers(member)
    _grants(member)
    slots = member.get("skill_slots")
    if slots is not None and (not isinstance(slots, list) or len(slots) != 4):
        raise ValueError("Adjacent-cost aura requires the four reviewed skill slots")
    return True


def own_discount(member, skill_id):
    row = _ledgers(member).get(str(skill_id))
    return row["discount"] if row else 0


def neighbours(slot):
    if type(slot) is not int or slot not in (0, 1, 2, 3):
        raise ValueError("Adjacent-cost aura requires a reviewed slot index")
    return [index for index in (slot - 1, slot + 1) if 0 <= index <= 3]


def aura_sources(member, slot):
    """Reviewed source skills occupying the immediately adjacent slots."""
    slots = member.get("skill_slots") or []
    rows = []
    for index in neighbours(slot):
        if index >= len(slots):
            continue
        skill_id = slots[index]
        spec = _spec(skill_id) if skill_id else None
        if spec is not None:
            rows.append((index, int(skill_id), spec["components"]["adjacent_cost"]["amount"]))
    return rows


def transmission(member):
    """Recorded transmission tags per occupied slot; never used in a formula."""
    slots = member.get("skill_slots") or []
    tags = {}
    for index, skill_id in enumerate(slots):
        spec = _spec(skill_id) if skill_id else None
        if spec is not None and spec["components"].get("transmission"):
            tags[index] = {"skill_id": int(skill_id), "transmission": spec["components"]["transmission"]}
    return tags


def resolved_cost(state, side, skill_id, slot, value):
    """Apply the permanent own discount and any adjacent aura; floor at zero."""
    spec = _spec(skill_id)
    member = _active(state, side)
    own = own_discount(member, skill_id) if spec is not None else 0
    sources = aura_sources(member, slot) if type(slot) is int and slot in (0, 1, 2, 3) else []
    if not own and not sources:
        return value
    if not isinstance(value, int):
        raise ValueError("Adjacent-cost aura requires an integer resolved cost")
    floor = spec["components"]["own_cost"]["floor"] if spec is not None else 0
    granted = grant_total(member, slot) if type(slot) is int and slot in (0, 1, 2, 3) else 0
    return max(floor, 0, value + own + granted + sum(amount for _, _, amount in sources))


def _grants(member):
    grants = member.get("adjacent_cost_grants")
    if grants is None:
        return {}
    if not isinstance(grants, dict):
        raise ValueError("Adjacent-cost grants must be a mapping")
    for index, row in grants.items():
        if type(index) is not int or index not in (0, 1, 2, 3):
            raise ValueError("Adjacent-cost grant slot index invalid")
        if not isinstance(row, dict) or not isinstance(row.get("entries"), list) or type(row.get("total")) is not int:
            raise ValueError("Adjacent-cost grant row invalid")
        entries = row["entries"]
        if len({entry.get("token") if isinstance(entry, dict) else None for entry in entries}) != len(entries):
            raise ValueError("Adjacent-cost grant tokens must be unique")
        if not all(isinstance(entry, dict) and type(entry.get("amount")) is int and entry["amount"] < 0
                   and isinstance(entry.get("source_skill_id"), int)
                   and isinstance(entry.get("turn"), int) and isinstance(entry.get("token"), str)
                   for entry in entries):
            raise ValueError("Adjacent-cost grant entry invalid")
        total = sum(entry["amount"] for entry in entries)
        if row["total"] != total or row.get("grant_hash") != fingerprint(
                {k: v for k, v in row.items() if k != "grant_hash"}):
            raise ValueError("Adjacent-cost grant ledger changed")
    return grants


def grant_total(member, slot):
    if type(slot) is not int or slot not in (0, 1, 2, 3):
        raise ValueError("Adjacent-cost grant requires a reviewed slot index")
    row = _grants(member).get(slot)
    return row["total"] if row else 0


def grant(member, side, skill_id, slot, *, amount, response_success, turn, token):
    """Permanently adjust the energy cost of both neighbour slots' skills.

    Evidence: 7070080 能量守恒 "应对攻击：两侧技能能耗永久-1" with skill_result
    [20110310, 1031111, 20620060]; buff 20640730 base 2064073 params
    [8],[5],[2],[1],[-1],[6],[0],[0] (op 8 neighbour-side mechanism, amount -1).
    """
    if not isinstance(response_success, bool):
        raise ValueError("Neighbour cost grant requires an explicit response_success")
    if not isinstance(amount, int) or amount >= 0:
        raise ValueError("Neighbour cost grant amount must be a negative integer")
    if type(slot) is not int or slot not in (0, 1, 2, 3):
        raise ValueError("Neighbour cost grant requires a reviewed source slot")
    if not isinstance(token, str) or not token:
        raise ValueError("Neighbour cost grant requires a token")
    grants = member.setdefault("adjacent_cost_grants", {})
    for index in neighbours(slot):
        row = grants.setdefault(index, {"entries": [], "total": 0})
        if any(entry.get("token") == token for entry in row["entries"]):
            continue
        row["entries"].append({"source_skill_id": int(skill_id), "amount": amount, "turn": int(turn), "token": token})
        row["total"] = sum(entry["amount"] for entry in row["entries"])
        row["grant_hash"] = fingerprint({k: v for k, v in row.items() if k != "grant_hash"})
    return [{"op": "adjacent_cost.grant", "amount": amount, "neighbour_slots": neighbours(slot),
             "response_success": response_success, "source_skill_id": int(skill_id), "turn": int(turn)}]


def record_use(member, side, skill_id, *, turn, token):
    """A committed use permanently lowers this skill's own cost by one."""
    spec = _spec(skill_id)
    if spec is None:
        return []
    if not isinstance(token, str) or not token or type(turn) is not int:
        raise ValueError("Adjacent-cost growth requires an explicit token and turn")
    ledgers = deepcopy(_ledgers(member))
    row = ledgers.get(str(skill_id)) or {"policy": POLICY, "config_sha256": CONFIG_SHA256,
                                         "source_skill_id": int(skill_id), "source_hash": spec["record_hash"],
                                         "tokens": [], "uses": 0, "discount": 0}
    if token in row["tokens"]:
        return []
    row["tokens"] = list(row["tokens"]) + [token]
    row["uses"] = len(row["tokens"])
    row["discount"] = spec["components"]["own_cost"]["per_use"] * row["uses"]
    row["ledger_hash"] = fingerprint({k: v for k, v in row.items() if k != "ledger_hash"})
    ledgers[str(skill_id)] = row
    member["adjacent_cost_ledgers"] = ledgers
    validate_member(member)
    return [{"op": "adjacent_cost.grew", "side": side, "skill_id": int(skill_id),
             "per_use": spec["components"]["own_cost"]["per_use"], "uses": row["uses"],
             "discount": row["discount"], "adjacent_cost_policy": POLICY}]


def preflight(program, state, context, damage_resolver=None):
    from lab.effect_runtime import _preflight_header
    _preflight_header(program, state, context)
    _context(context)
    if "adjacent_cost_components" not in program:
        raise ValueError("Adjacent-cost plan requires reviewed components")
    return {"status": "preflight", "components": deepcopy(program["adjacent_cost_components"])}


def execute(program, state, context, damage_resolver=None):
    """The aura plan has no effect ops; its cost lives in the shared resolution."""
    preflight(program, state, context, damage_resolver)
    return {"status": "applied",
            "state": {"self": deepcopy(state["self"]), "opponent": deepcopy(state["opponent"])},
            "events": [], "blockers": [], "adjacent_cost_policy": POLICY,
            "adjacent_cost_policies": deepcopy(POLICIES),
            "adjacent_cost_uncertainties": list(UNCERTAINTIES)}
