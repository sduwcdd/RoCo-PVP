"""Source-bound adjacency power aura (减压阀 7070250).

Description: "主动：本技能被动永久额外+20威力，被动：两侧技能威力+10，传动1。"
Same adjacency contract as the cost aura: immediate neighbours by slot index,
no wrap. The own growth raises this skill's own outgoing power by 20 per
committed use; the aura raises the power of the two adjacent slots' skills by 10
while the source occupies its slot. 传动1 is a recorded tag only.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from lab.game_runtime_defaults import ROOT
from lab.phase_config import fingerprint
from lab.prepared_rules import prepare_rules

CONFIG = ROOT / "data/rules/reviewed-adjacent-power-aura-1.json"
CONFIG_SHA256 = '6c553f700c0edb1da594b4b440a853ddca35472eacb1a8a84ca606624a3b79e6'
POLICY = "source_bound_adjacent_power_aura_v1"
POLICIES = {
    "adjacency": "immediate_neighbours_by_slot_index_without_wrap_edge_slots_use_existing_neighbours",
    "aura": "always_on_while_the_source_skill_occupies_its_slot",
    "own_growth": "plus_twenty_permanent_per_committed_use",
    "own_scope": "the_source_skill_outgoing_power_only",
    "power": "sum_reviewed_aura_and_growth_then_floor_at_zero",
    "transmission": "recorded_tag_only_no_further_formula",
}
UNCERTAINTIES = (
    "环绕是否属于相邻、永久威力是否在退场/换位后保留、替换进同一槽位的技能是否继承，客户端表均未给出；"
    "威力加成的结算顺序假定为“在既有权重修正之后、最终伤害之前加总”，未做实战校准。",
)


@lru_cache(maxsize=2)
def _configuration(stamp):
    raw = CONFIG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONFIG_SHA256:
        raise ValueError("Adjacent-power aura configuration changed; source review required")
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
            raise ValueError("Adjacent-power aura extracted source changed")
    return data


def research_context():
    return {"adjacent_power_aura_policy": POLICY, "adjacent_power_aura_policies": deepcopy(POLICIES),
            "adjacent_power_aura_uncertainties": list(UNCERTAINTIES)}


def _context(context):
    if (context.get("adjacent_power_aura_policy") != POLICY
            or context.get("adjacent_power_aura_policies") != POLICIES):
        raise ValueError("Explicit adjacent-power aura policies required")


def _spec(skill_id):
    return _data()["skills"].get(str(skill_id))


def programs(catalog):
    prepared, config = prepare_rules(catalog), _data()
    if prepared.snapshot_id != config["snapshot_id"]:
        raise ValueError("Adjacent-power aura snapshot differs")
    result = {}
    for key, row in config["skills"].items():
        record = prepared._rules.skill(int(key))
        if fingerprint(record) != row["record_hash"] or record != row["record"]:
            raise ValueError("Adjacent-power aura whole source changed")
        program = deepcopy(prepared._rules.program(int(key)))
        program.pop("native_rule", None)
        program.update(status="compiled", blockers=[], operations=[{"op": "adjacent_power.plan", "params": {}}],
                       adjacent_power_components=deepcopy(row["components"]),
                       adjacent_power_evidence=deepcopy(row), adjacent_power_config_hash=CONFIG_SHA256,
                       adjacent_power_policies=deepcopy(POLICIES),
                       adjacent_power_uncertainties=list(UNCERTAINTIES), response_kinds=[],
                       executable=False, real_game_verified=False, training_eligible=False)
        result[int(key)] = program
    return result


def _ledgers(member):
    ledgers = member.get("adjacent_power_ledgers")
    if ledgers is None:
        return {}
    if not isinstance(ledgers, dict):
        raise ValueError("Adjacent-power ledgers must be a mapping")
    for key, row in ledgers.items():
        spec = _spec(key)
        if spec is None:
            raise ValueError("Adjacent-power ledger references an unreviewed skill")
        per_use = spec["components"].get("own_power", {}).get("per_use", 0)
        if (not isinstance(row, dict) or row.get("policy") != POLICY or row.get("config_sha256") != CONFIG_SHA256
                or row.get("source_skill_id") != int(key) or row.get("source_hash") != spec["record_hash"]
                or row.get("ledger_hash") != fingerprint({k: v for k, v in row.items() if k != "ledger_hash"})
                or type(row.get("uses")) is not int or row["uses"] < 0
                or not isinstance(row.get("tokens"), list) or len(row["tokens"]) != row["uses"]
                or len(set(row["tokens"])) != len(row["tokens"])
                or row.get("bonus") != per_use * row["uses"]):
            raise ValueError("Adjacent-power ledger changed")
    return ledgers


def validate_member(member):
    _ledgers(member)
    _grants(member)
    slots = member.get("skill_slots")
    if slots is not None and (not isinstance(slots, list) or len(slots) != 4):
        raise ValueError("Adjacent-power aura requires the four reviewed skill slots")
    return True


def own_bonus(member, skill_id):
    row = _ledgers(member).get(str(skill_id))
    return row["bonus"] if row else 0


def neighbours(slot):
    if type(slot) is not int or slot not in (0, 1, 2, 3):
        raise ValueError("Adjacent-power aura requires a reviewed slot index")
    return [index for index in (slot - 1, slot + 1) if 0 <= index <= 3]


def aura_sources(member, slot):
    slots = member.get("skill_slots") or []
    rows = []
    for index in neighbours(slot):
        if index >= len(slots):
            continue
        skill_id = slots[index]
        spec = _spec(skill_id) if skill_id else None
        aura = spec["components"].get("adjacent_power") if spec is not None else None
        if aura is not None:
            rows.append((index, int(skill_id), aura["amount"]))
    return rows


def modify_power(member, value, slot):
    """Raise this skill's outgoing power by the reviewed growth and adjacent auras.

    Without a reviewed slot index the firing skill cannot be attributed, so the
    power is returned unchanged instead of guessing a position.
    """
    if not isinstance(value, (int, float)):
        raise ValueError("Adjacent-power aura requires numeric power")
    if type(slot) is not int or slot not in (0, 1, 2, 3):
        return value
    sources = aura_sources(member, slot)
    slots = member.get("skill_slots") or []
    skill_id = slots[slot] if slot < len(slots) and slots[slot] else None
    own = own_bonus(member, skill_id) if skill_id else 0
    granted = grant_total(member, slot)
    if not own and not sources and not granted:
        return value
    return max(0, value + own + granted + sum(amount for _, _, amount in sources))


def _grants(member):
    grants = member.get("adjacent_power_grants")
    if grants is None:
        return {}
    if not isinstance(grants, dict):
        raise ValueError("Adjacent-power grants must be a mapping")
    for key, row in grants.items():
        if (not isinstance(row, dict) or row.get("policy") != POLICY
                or row.get("config_sha256") != CONFIG_SHA256 or row.get("target_slot") != int(key)
                or row.get("grant_hash") != fingerprint({k: v for k, v in row.items() if k != "grant_hash"})
                or not isinstance(row.get("entries"), list)
                or len({entry.get("token") if isinstance(entry, dict) else None
                        for entry in row["entries"]}) != len(row["entries"])
                or row.get("total") != sum(_grant_amount(entry) for entry in row["entries"])):
            raise ValueError("Adjacent-power grant ledger changed")
    return grants


def _grant_amount(entry):
    if not isinstance(entry, dict) or type(entry.get("amount")) is not int or entry["amount"] <= 0:
        raise ValueError("Adjacent-power grant entry must carry a positive integer amount")
    spec = _spec(entry.get("source_skill_id"))
    if spec is None:
        raise ValueError("Adjacent-power grant references an unreviewed source")
    allowed = {spec["components"]["neighbor_grant"]["amount"],
               spec["components"]["neighbor_grant"]["response_amount"]}
    if entry["amount"] not in allowed:
        raise ValueError("Adjacent-power grant amount differs from its reviewed source")
    if not isinstance(entry.get("token"), str) or not entry["token"]:
        raise ValueError("Adjacent-power grant entry needs a token")
    return entry["amount"]


def grant_total(member, slot):
    row = _grants(member).get(str(slot))
    return row["total"] if row else 0


def grant(member, side, skill_id, slot, *, response_success, turn, token):
    """Permanently raise both immediate neighbours' power; +30 when the use answered a defense."""
    spec = _spec(skill_id)
    if spec is None:
        return []
    components = spec["components"]["neighbor_grant"]
    if type(response_success) is not bool:
        raise ValueError("Neighbor power grant requires an explicit response classification")
    if not isinstance(token, str) or not token or type(turn) is not int:
        raise ValueError("Neighbor power grant requires a token and turn")
    amount = components["response_amount"] if response_success else components["amount"]
    grants = deepcopy(_grants(member))
    events = []
    for index in neighbours(slot):
        row = grants.get(str(index)) or {"policy": POLICY, "config_sha256": CONFIG_SHA256,
                                         "target_slot": index, "entries": []}
        entry = {"source_skill_id": int(skill_id), "amount": amount, "turn": turn,
                 "token": f"{token}:{index}"}
        if any(item.get("token") == entry["token"] for item in row["entries"]):
            continue
        row["entries"] = list(row["entries"]) + [entry]
        row["total"] = sum(_grant_amount(item) for item in row["entries"])
        row["grant_hash"] = fingerprint({k: v for k, v in row.items() if k != "grant_hash"})
        grants[str(index)] = row
        events.append({"op": "adjacent_power.granted", "side": side, "target_slot": index,
                       "source_skill_id": int(skill_id), "amount": amount,
                       "response_success": response_success, "total": row["total"],
                       "adjacent_power_aura_policy": POLICY})
    if grants:
        member["adjacent_power_grants"] = grants
        validate_member(member)
    return events


def record_use(member, skill_id, *, turn, token):
    spec = _spec(skill_id)
    if spec is None or "own_power" not in spec["components"]:
        return []
    if not isinstance(token, str) or not token or type(turn) is not int:
        raise ValueError("Adjacent-power growth requires an explicit token and turn")
    ledgers = deepcopy(_ledgers(member))
    row = ledgers.get(str(skill_id)) or {"policy": POLICY, "config_sha256": CONFIG_SHA256,
                                         "source_skill_id": int(skill_id), "source_hash": spec["record_hash"],
                                         "tokens": [], "uses": 0, "bonus": 0}
    if token in row["tokens"]:
        return []
    row["tokens"] = list(row["tokens"]) + [token]
    row["uses"] = len(row["tokens"])
    row["bonus"] = spec["components"]["own_power"]["per_use"] * row["uses"]
    row["ledger_hash"] = fingerprint({k: v for k, v in row.items() if k != "ledger_hash"})
    ledgers[str(skill_id)] = row
    member["adjacent_power_ledgers"] = ledgers
    validate_member(member)
    return [{"op": "adjacent_power.grew", "skill_id": int(skill_id), "uses": row["uses"],
             "bonus": row["bonus"], "adjacent_power_aura_policy": POLICY}]


def preflight(program, state, context, damage_resolver=None):
    from lab.effect_runtime import _preflight_header
    _preflight_header(program, state, context)
    _context(context)
    if "adjacent_power_components" not in program:
        raise ValueError("Adjacent-power plan requires reviewed components")
    return {"status": "preflight", "components": deepcopy(program["adjacent_power_components"])}


def execute(program, state, context, damage_resolver=None):
    preflight(program, state, context, damage_resolver)
    owned = deepcopy(state)
    cost = context["resolved_energy_cost"]
    if type(cost) is not int or cost < 0:
        raise ValueError("Adjacent-power aura requires an integer non-negative resolved cost")
    owned["self"]["energy"] -= cost
    events = [{"op": "energy.pay", "target": "self", "amount": cost,
               "source": "adjacent_power_aura"}]
    return {"status": "applied",
            "state": {"self": deepcopy(owned["self"]), "opponent": deepcopy(owned["opponent"])},
            "events": events, "blockers": [], "adjacent_power_aura_policy": POLICY,
            "adjacent_power_aura_policies": deepcopy(POLICIES),
            "adjacent_power_aura_uncertainties": list(UNCERTAINTIES)}
