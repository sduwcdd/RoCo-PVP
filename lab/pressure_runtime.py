"""Source-bound outgoing power suppression (排气 7070260).

Semantics from the client tables, not from prose parsing:
  * use installs a two-stack "技能威力-10" pair on the opponent's *outgoing* power
    (install amount -20);
  * every completed *resisted* direct attack packet the caster receives installs
    one more such pair (-20), combos counted once per packet;
  * re-using the skill resets the accumulated entries back to the base pair.

The ledger lives on the debuffed member and is applied inside the shared power
query, so it affects that member's attacks only. Amounts are integers; power is
floored at zero. No timing, priority or damage formula is decided here.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from lab.game_runtime_defaults import ROOT
from lab.phase_config import fingerprint
from lab.prepared_rules import prepare_rules

CONFIG = ROOT / "data/rules/reviewed-pressure-1.json"
CONFIG_SHA256 = 'ca7a3da3d78c6c08ddc7c0ac9373ffb8cf1f558e0cb9949f4b960a4e837aad19'
POLICY = "source_bound_outgoing_power_suppression_v1"
POLICIES = {
    "install": "use_replaces_prior_entries_with_the_source_stack_pair_before_arming_one_listener",
    "escalation": "one_extra_stack_pair_per_completed_resisted_direct_attack_packet_combo_counts_once",
    "reset": "reuse_resets_accumulated_entries_to_the_base_pair_in_the_same_turn",
    "resisted": "type_multiplier_below_one_and_resistance_not_ignored",
    "target": "opponent_active_member_all_outgoing_skills",
    "persist": "no_documented_removal_listener_and_entries_retained_until_reset",
}


@lru_cache(maxsize=2)
def _configuration(stamp):
    raw = CONFIG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONFIG_SHA256:
        raise ValueError("Pressure component configuration changed; source review required")
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
            raise ValueError("Pressure extracted source changed")
    return data


def research_context():
    return {"pressure_policy": POLICY, "pressure_policies": deepcopy(POLICIES)}


def _context(context):
    if context.get("pressure_policy") != POLICY or context.get("pressure_policies") != POLICIES:
        raise ValueError("Explicit outgoing power suppression policies required")


def programs(catalog):
    prepared, config = prepare_rules(catalog), _data()
    if prepared.snapshot_id != config["snapshot_id"]:
        raise ValueError("Pressure snapshot differs")
    result = {}
    for key, row in config["skills"].items():
        record = prepared._rules.skill(int(key))
        if fingerprint(record) != row["record_hash"] or record != row["record"]:
            raise ValueError("Pressure whole source changed")
        program = deepcopy(prepared._rules.program(int(key)))
        program.pop("native_rule", None)
        program.update(status="compiled", blockers=[], operations=[{"op": "pressure.plan", "params": {}}],
                       pressure_components=deepcopy(row["components"]),
                       pressure_evidence=deepcopy(row), pressure_config_hash=CONFIG_SHA256,
                       pressure_policies=deepcopy(POLICIES), response_kinds=[], executable=False,
                       real_game_verified=False, training_eligible=False)
        result[int(key)] = program
    return result


def _active(state, side):
    team = state["teams"][side]
    return team["members"][team["active_slot"]]


def _spec(skill_id):
    return _data()["skills"].get(str(skill_id))


def _validate_entry(entry, skill_id):
    spec = _spec(skill_id)
    if spec is None:
        raise ValueError("Pressure ledger references an unreviewed source")
    components = spec["components"]
    if (not isinstance(entry, dict) or entry.get("kind") not in ("install", "resisted")
            or type(entry.get("amount")) is not int or entry.get("amount") >= 0
            or type(entry.get("turn")) is not int or entry["turn"] < 1
            or not isinstance(entry.get("token"), str) or not entry["token"]):
        raise ValueError("Invalid outgoing power suppression entry")
    expected = (components["install"]["amount"] if entry["kind"] == "install"
                else components["escalation"]["per_resisted_packet"])
    if entry["amount"] != expected:
        raise ValueError("Suppression entry amount differs from its reviewed source")
    return entry


def validate_member(member):
    """Structural validation used by the shared turn validator and power query."""
    ledger = member.get("pressure_ledger")
    if ledger is not None:
        if (not isinstance(ledger, dict) or ledger.get("policy") != POLICY
                or ledger.get("config_sha256") != CONFIG_SHA256
                or ledger.get("ledger_hash") != fingerprint({k: v for k, v in ledger.items() if k != "ledger_hash"})
                or not isinstance(ledger.get("entries"), list) or not ledger["entries"]):
            raise ValueError("Outgoing power suppression ledger changed")
        skill_id = ledger.get("source_skill_id")
        for entry in ledger["entries"]:
            _validate_entry(entry, skill_id)
    listeners = member.get("pressure_listeners", [])
    if not isinstance(listeners, list):
        raise ValueError("Outgoing power suppression listeners must be a list")
    for row in listeners:
        skill_id = row.get("source_skill_id") if isinstance(row, dict) else None
        spec = _spec(skill_id)
        if (spec is None or row.get("policy") != POLICY or row.get("config_sha256") != CONFIG_SHA256
                or row.get("source_hash") != spec["record_hash"] or row.get("armed") is not True
                or type(row.get("installed_turn")) is not int or row["installed_turn"] < 1
                or row.get("listener_hash") != fingerprint({k: v for k, v in row.items() if k != "listener_hash"})):
            raise ValueError("Outgoing power suppression listener changed")
    return True


def total(member):
    """Sum of every reviewed suppression entry currently held by this member."""
    ledger = member.get("pressure_ledger")
    if not ledger:
        return 0
    validate_member(member)
    return sum(entry["amount"] for entry in ledger["entries"])


def modify_power(member, value):
    """Apply the suppression ledger to this member's outgoing skill power."""
    if not member.get("pressure_ledger"):
        return value
    if not isinstance(value, (int, float)):
        raise ValueError("Outgoing power suppression requires numeric power")
    return max(0, value + total(member))


def _write_ledger(target, skill_id, entries, turn):
    spec = _spec(skill_id)
    ledger = {"policy": POLICY, "config_sha256": CONFIG_SHA256, "source_skill_id": skill_id,
              "source_hash": spec["record_hash"], "entries": deepcopy(entries)}
    ledger["ledger_hash"] = fingerprint(ledger)
    target["pressure_ledger"] = ledger
    validate_member(target)
    return ledger


def install(state, side, *, context, turn, token, skill_id=None):
    """After the caster's committed use: reset the opponent and arm one listener."""
    _context(context)
    current = deepcopy(state)
    actor, other = _active(current, side), "b" if side == "a" else "a"
    if skill_id is None:
        skill_id = int(next(iter(_data()["skills"])))
    if _spec(skill_id) is None:
        raise ValueError("Pressure install requires a reviewed source skill")
    if actor["hp"] <= 0:
        return []
    opponent = _active(current, other)
    if opponent["hp"] <= 0:
        return []
    entry = {"kind": "install", "amount": _spec(skill_id)["components"]["install"]["amount"],
             "turn": turn, "token": str(token) + ":pressure.install"}
    _validate_entry(entry, skill_id)
    _write_ledger(opponent, skill_id, [entry], turn)
    listener = {"policy": POLICY, "config_sha256": CONFIG_SHA256, "source_skill_id": skill_id,
                "source_hash": _spec(skill_id)["record_hash"], "armed": True, "installed_turn": turn}
    listener["listener_hash"] = fingerprint(listener)
    rows = [r for r in actor.get("pressure_listeners", []) if r.get("source_skill_id") != skill_id]
    actor["pressure_listeners"] = rows + [listener]
    validate_member(actor)
    state.clear()
    state.update(current)
    return [{"op": "pressure.installed", "side": side, "member_id": actor["member_id"],
             "target_side": other, "target_member_id": opponent["member_id"],
             "source_skill_id": skill_id, "amount": entry["amount"],
             "ledger_total": total(opponent), "pressure_policy": POLICY}]


def observe_received_attack(prepared, state, target_side, action, damage_events, *, action_token, context):
    """One completed resisted attack packet grows the attacker's suppression ledger."""
    _context(context)
    if not hasattr(prepared, "_rules"):
        prepared = prepare_rules(prepared)
    if action.get("kind") != "skill" or action.get("execution_phase") == "charge_setup_not_attack_release":
        return []
    record = prepared._rules.skill(action["skill_id"])
    if record["kind"] not in ("physical", "magical"):
        return []
    current = deepcopy(state)
    target = _active(current, target_side)
    armed = [r for r in target.get("pressure_listeners", []) if r["armed"] and r["source_skill_id"] in
             {int(k) for k in _data()["skills"]}]
    if not armed:
        return []
    other = "b" if target_side == "a" else "a"
    attacker = next((m for m in current["teams"][other]["members"] if m["member_id"] == action.get("actor_member_id")), None)
    if attacker is None or not isinstance(action_token, str) or not action_token:
        raise ValueError("Resisted-hit suppression requires the actual committed attacker/token")
    direct = [deepcopy(e) for e in damage_events
              if e.get("op") in ("damage", "damage.hit") and e.get("target") == "opponent" and e.get("before", 0) > 0]
    if not direct:
        return []
    types = {e.get("resolved_params", e.get("params", {})).get("type") for e in direct}
    if len(types) != 1:
        raise ValueError("Mixed-type attack packet needs an explicit resistance aggregation policy")
    attack_type = types.pop()
    ignored = set()
    for event in direct:
        params = event.get("resolved_params", event.get("params", {}))
        flag = params.get("ignore_type_resistance", False)
        if type(flag) is not bool:
            raise ValueError("Ignore-resistance flag must be explicit boolean")
        ignored.add(flag)
    if len(ignored) != 1:
        raise ValueError("Mixed ignore-resistance flags need an explicit per-packet policy")
    matchup = prepared._rules.type_multiplier(attack_type, target["form_id"])
    ratio = matchup["multiplier"]
    from fractions import Fraction
    resisted = 0 < Fraction(ratio["numerator"], ratio["denominator"]) < 1 and not ignored.pop()
    if not resisted:
        return []
    receipts = current.setdefault("pressure_received_receipts", {})
    if not isinstance(receipts, dict):
        raise ValueError("Malformed suppression receipts")
    receipt_key = action_token + ":" + target["member_id"]
    if receipt_key in receipts:
        return []
    skill_id = int(armed[0]["source_skill_id"])
    entry = {"kind": "resisted", "amount": _spec(skill_id)["components"]["escalation"]["per_resisted_packet"],
             "turn": current["turn"], "token": str(action_token) + ":pressure.resisted:" + target["member_id"]}
    _validate_entry(entry, skill_id)
    existing = attacker.get("pressure_ledger")
    entries = deepcopy(existing["entries"]) if existing and existing.get("source_skill_id") == skill_id else []
    entries.append(entry)
    _write_ledger(attacker, skill_id, entries, current["turn"])
    receipts[receipt_key] = entry["token"]
    state.clear()
    state.update(current)
    return [{"op": "pressure.escalated", "side": other, "member_id": attacker["member_id"],
             "target_side": target_side, "target_member_id": target["member_id"],
             "source_skill_id": skill_id, "amount": entry["amount"], "effective_type": attack_type,
             "matchup": matchup, "ledger_total": total(attacker), "pressure_policy": POLICY}]


class PressurePlan:
    """Admission placeholder: the plan op carries no state of its own."""


def preflight(program, state, context, damage_resolver=None):
    from lab.effect_runtime import _preflight_header
    _preflight_header(program, state, context)
    _context(context)
    if "pressure_components" not in program:
        raise ValueError("Pressure plan requires reviewed components")
    return {"status": "preflight", "components": deepcopy(program["pressure_components"])}


def execute(program, state, context, damage_resolver=None):
    """The install phase is a committed follow-up; execution itself changes nothing."""
    preflight(program, state, context, damage_resolver)
    return {"status": "applied", "state": {"self": deepcopy(state["self"]), "opponent": deepcopy(state["opponent"])},
            "events": [], "blockers": []}
