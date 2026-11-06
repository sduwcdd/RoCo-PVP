"""Source-bound absolute-turn durations and delayed effects, explicitly experimental."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from lab.effect_runtime import _preflight_header, execute_effects
from lab.phase_config import fingerprint, load_phase_config
from lab.prepared_rules import prepare_rules

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data/rules/reviewed-duration-components-1.json"
CONFIG_HASH = '5330a9ea2da4cbb6f8f09499c40cbef7694caf1f3ae3d02792f8609e5c07d095'
POLICY = "source_bound_absolute_turn_duration_experiment_v1"
POLICIES = {"duration": "application_turn_counts_in_declared_duration_experiment",
    "refresh": "same_buff_kind_replaces_previous_max_one_experiment",
    "delayed": "absolute_next_turn_even_if_benched_experiment",
    "recovery": "each_requested_gain_minus_suppression_floor_zero_before_cap_experiment",
    "cooldown": "block_two_turns_after_application_experiment",
    "stun": "skip_all_selected_actions_on_absolute_next_turn_experiment",
    "departure": "clear_only_source_flagged_effects_experiment",
    "charge_skip": "next_committed_skill_consumes_even_noncharge_two_turn_window_experiment"}
KINDS = {"attack_cost", "energy_recovery", "cooldown", "stun", "charge_skip"}


@lru_cache(maxsize=16)
def _hash(path, size, stamp):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rules():
    data = json.loads(CONFIG.read_text(encoding="utf8"))
    if fingerprint(data) != CONFIG_HASH:
        raise ValueError("Duration configuration changed")
    for source in data["sources"]:
        path = (ROOT / source["path"]).resolve()
        stat = path.stat()
        if not path.is_relative_to(ROOT) or _hash(str(path), stat.st_size, stat.st_mtime_ns) != source["sha256"]:
            raise ValueError("Duration extracted source changed")
    return data


def research_context():
    return {"duration_policies": deepcopy(POLICIES)}


def programs(catalog):
    prepared, data = prepare_rules(catalog), rules()
    source = prepared._rules._catalog
    load_phase_config(source)
    if source["snapshot_id"] != data["snapshot_id"]:
        raise ValueError("Duration snapshot changed")
    output = {}
    for key, row in data["skills"].items():
        if fingerprint(prepared._rules.skill(int(key))) != row["record_hash"]:
            raise ValueError("Duration whole source changed")
        program = deepcopy(prepared._rules.program(int(key)))
        program.pop("native_rule", None)
        program.update(status="compiled", blockers=[], operations=deepcopy(row["operations"]),
            duration_components=deepcopy(row["components"]), duration_config_hash=CONFIG_HASH,
            duration_policy=POLICY, response_kinds=deepcopy(row.get("responses", [])),
            dependency_ids=deepcopy(row["record"].get("desc_notes", [])),
            executable=False, real_game_verified=False, training_eligible=False)
        output[int(key)] = program
    return output


def _validate(program, context):
    data = rules()
    row = data["skills"].get(str(program.get("game_id")))
    if (row is None or program.get("source_hash") != row["record_hash"]
            or program.get("snapshot_id") != data["snapshot_id"]
            or program.get("duration_components") != row["components"]
            or program.get("operations") != row["operations"]
            or program.get("duration_config_hash") != CONFIG_HASH or program.get("duration_policy") != POLICY
            or context.get("duration_policies") != POLICIES):
        raise ValueError("Duration source/policy differs")


def _turn(turn):
    if type(turn) is not int or turn < 1:
        raise ValueError("Duration requires a positive absolute turn")


def validate_member(member):
    entries = member.get("timed_effects", [])
    if not isinstance(entries, list):
        raise ValueError("Timed effects must be a list")
    data = rules()
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Invalid timed effect")
        source_key = 'source_trait_id' if 'source_trait_id' in entry else 'source_skill_id'
        row = data.get('trait_templates',{}).get(str(entry.get(source_key))) if source_key=='source_trait_id' else data['skills'].get(str(entry.get(source_key)))
        candidates = [] if row is None else [c for c in row["components"] if c["kind"] == entry.get("kind")]
        if len(candidates) != 1:
            raise ValueError("Unknown timed effect source/kind")
        component = candidates[0]
        _turn(entry.get("applied_turn"))
        expected = {**deepcopy(component), "applied_turn": entry["applied_turn"],
            "starts_turn": entry["applied_turn"] + component["delay"],
            "ends_turn": entry["applied_turn"] + component["delay"] + component["rounds"] - 1,
            source_key: entry[source_key], "source_hash": row["record_hash"],
            "policy": POLICY, "config_hash": CONFIG_HASH}
        if component.get('skill_selector') == 'opponent.declared_skill':
            if type(entry.get('target_skill_id')) is not int or entry['target_skill_id']<=0:raise ValueError('Cooldown needs bound declared target skill')
            expected['target_skill_id']=entry['target_skill_id']
        key = (entry.get("buff_id"), entry.get("kind"))
        if entry != expected or key in seen:
            raise ValueError("Timed effect source or lifetime changed")
        seen.add(key)
    return entries


def install_trait_duration(member, trait_id, source_hash, turn):
    _turn(turn)
    row=rules().get('trait_templates',{}).get(str(trait_id))
    if row is None or source_hash!=row['record_hash']:
        raise ValueError('Trait duration source changed')
    entries=deepcopy(validate_member(member));events=[]
    for component in row['components']:
        entry={**deepcopy(component),'applied_turn':turn,'starts_turn':turn+component['delay'],
            'ends_turn':turn+component['delay']+component['rounds']-1,'source_trait_id':trait_id,
            'source_hash':source_hash,'policy':POLICY,'config_hash':CONFIG_HASH}
        entries=[e for e in entries if (e['buff_id'],e['kind'])!=(entry['buff_id'],entry['kind'])]+[entry]
        events.append({'op':'duration.install','effect':deepcopy(entry)})
    validate_member({'timed_effects':entries})
    member['timed_effects']=entries
    return events


def active_effects(member, turn, kind=None):
    _turn(turn)
    return [deepcopy(e) for e in validate_member(member)
            if e["starts_turn"] <= turn <= e["ends_turn"] and (kind is None or e["kind"] == kind)]


def cost(member, skill_kind, base, turn):
    if type(base) is not int or base < 0:
        raise ValueError("Invalid duration base cost")
    effects = active_effects(member, turn, "attack_cost")
    from lab.trait_runtime import cost_delta
    delta = sum(e["amount"] for e in effects) if skill_kind in ("physical", "magical") else 0
    return max(0,base + cost_delta(member,delta))


def check_cooldown(member, skill_id, turn):
    if any(e.get("target_skill_id",e["source_skill_id"]) == skill_id for e in active_effects(member, turn, "cooldown")):
        raise ValueError("Skill is cooling down under explicit duration policy")
    if any(e['skill_id'] == skill_id and e['applied_turn'] <= turn <= e['ends_turn']
           for e in trait_cooldowns(member)):
        raise ValueError("Skill is cooling down under sourced opponent trait")


def trait_cooldowns(member):
    entries = member.get('trait_skill_cooldowns', [])
    if not isinstance(entries, list):
        raise ValueError('Invalid trait cooldown ledger')
    seen = set()
    for entry in entries:
        row = rules().get('trait_cooldowns', {}).get(str(entry.get('source_trait_id'))) if isinstance(entry,dict) else None
        if row is None:
            raise ValueError('Unknown trait cooldown source')
        _turn(entry.get('applied_turn'))
        if (type(entry.get('skill_id')) is not int or entry['skill_id'] <= 0
                or not isinstance(entry.get('token'),str) or not entry['token']):
            raise ValueError('Invalid trait cooldown target/token')
        expected = {'source_trait_id':entry['source_trait_id'], 'source_hash':row['record_hash'],
            'skill_id':entry['skill_id'], 'applied_turn':entry['applied_turn'],
            'ends_turn':entry['applied_turn'] + row['blocked_following_turns'],
            'token':entry['token'], 'config_hash':CONFIG_HASH, 'policy':POLICY}
        key = (entry['source_trait_id'],entry['skill_id'])
        if entry != expected or key in seen:
            raise ValueError('Trait cooldown source/lifetime changed')
        seen.add(key)
    return entries


def install_trait_cooldown(member, trait_id, source_hash, skill_id, turn, *, token):
    _turn(turn)
    row = rules().get('trait_cooldowns', {}).get(str(trait_id))
    if row is None or source_hash != row['record_hash']:
        raise ValueError('Trait cooldown source changed')
    entries = trait_cooldowns(member)
    if any(e['token'] == token for e in entries):
        return None
    entry = {'source_trait_id':trait_id,'source_hash':source_hash,'skill_id':skill_id,
        'applied_turn':turn,'ends_turn':turn+row['blocked_following_turns'],
        'token':token,'config_hash':CONFIG_HASH,'policy':POLICY}
    retained = [deepcopy(e) for e in entries if (e['source_trait_id'],e['skill_id']) != (trait_id,skill_id)]
    candidate = {'trait_skill_cooldowns':retained+[entry]}
    trait_cooldowns(candidate)
    member['trait_skill_cooldowns'] = candidate['trait_skill_cooldowns']
    return {'op':'trait.skill.cooldown','effect':deepcopy(entry)}


def skip_action(member, turn):
    effects = active_effects(member, turn, "stun")
    return {"skip": bool(effects), "reason": "timed_stun" if effects else None,
            "effects": effects, "policy": POLICIES["stun"]}


def recovery_amount(member, requested, turn):
    """Every positive energy gain calls this before maximum-energy clipping."""
    if type(requested) is not int or requested < 0:
        raise ValueError("Energy recovery requires a nonnegative integer request")
    effects = active_effects(member, turn, "energy_recovery")
    return {"amount": max(0, requested + sum(e["amount"] for e in effects)),
            "requested": requested, "effects": effects, "policy": POLICIES["recovery"]}


def charge_bypass(member, turn):
    return bool(active_effects(member, turn, "charge_skip"))


def consume_charge_bypass(member, turn):
    """Call on committed skill, before installing that skill's newly granted token."""
    active = active_effects(member, turn, "charge_skip")
    current = deepcopy(member)
    current["timed_effects"] = [deepcopy(e) for e in validate_member(member) if e not in active]
    return {"member": current, "events": [{"op": "duration.consume_charge_skip", "effect": e,
        "policy": POLICIES["charge_skip"]} for e in active]}


def depart(member):
    """Return detached member; call on actual departure, not a blocked attempt."""
    current = deepcopy(member)
    current["timed_effects"] = [deepcopy(e) for e in validate_member(member) if not e["clear_on_departure"]]
    return current


def expire(member, turn):
    """Prune only effects whose end is before the new turn, including on the bench."""
    _turn(turn)
    current = deepcopy(member)
    current["timed_effects"] = [deepcopy(e) for e in validate_member(member) if e["ends_turn"] >= turn]
    if 'trait_skill_cooldowns' in member:
        current['trait_skill_cooldowns'] = [deepcopy(e) for e in trait_cooldowns(member) if e['ends_turn'] >= turn]
    return current


def execute_duration_skill(program, state, context, *, damage_resolver=None):
    result = {"status": "blocked", "state": deepcopy(state), "events": [], "blockers": [],
              "training_eligible": False, "calibrated": False, "real_game_verified": False}
    try:
        _preflight_header(program, state, context)
        _validate(program, context)
        if (any(c.get("when") == "response.success" for c in program["duration_components"])
                and type(context.get("response_success")) is not bool):
            raise ValueError("Conditional duration requires an explicit resolved response result")
        turn = context.get("turn")
        _turn(turn)
        check_cooldown(state["self"], program["game_id"], turn)
        for relative in ("self", "opponent"):
            validate_member(state[relative])
        payment = deepcopy(context)
        payment["component_sequence_payment"] = "reviewed_component_sequence_v1"
        fragment = execute_effects(program, state, payment, damage_resolver=damage_resolver)
        if fragment["status"] != "applied":
            return fragment
        current, events = fragment["state"], fragment["events"]
        for component in program["duration_components"]:
            if component.get("when") == "response.success" and not context["response_success"]:
                continue
            entry = {**deepcopy(component), "applied_turn": turn, "starts_turn": turn + component["delay"],
                "ends_turn": turn + component["delay"] + component["rounds"] - 1,
                "source_skill_id": program["game_id"], "source_hash": program["source_hash"],
                "policy": POLICY, "config_hash": CONFIG_HASH}
            if component.get('skill_selector') == 'opponent.declared_skill':
                declared=context.get('opponent_declared_skill')
                if type(declared) is not int or declared<=0:raise ValueError('Response cooldown needs current declared opposing skill')
                entry['target_skill_id']=declared
            target = current[component["target"]]
            entries = target.setdefault("timed_effects", [])
            entries[:] = [e for e in entries if (e["buff_id"], e["kind"]) != (component["buff_id"], component["kind"])]
            entries.append(entry)
            events.append({"op": "duration.install", **deepcopy(entry), "policies": deepcopy(POLICIES)})
        result.update(status="applied", state=current, events=events)
    except (ValueError, KeyError, TypeError) as exc:
        result["blockers"] = [str(exc)]
    return result
