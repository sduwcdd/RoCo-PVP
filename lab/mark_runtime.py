"""Reviewed mark, fixed devotion and transmission research components.

Team ``marks`` is authoritative. Relative actors carry detached field_marks only
inside a fragment; attach/commit helpers prevent a second persistent mark store.
Star power uses the shared HUD damage resolver; unresolved attack attribution fails closed.
"""
from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from lab.effect_runtime import _integer, _preflight_header, _state, execute_effects
from lab.phase_config import fingerprint
from lab.prepared_rules import prepare_rules
from lab.trait_runtime import cached_source_query

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data/rules/reviewed-mark-components-1.json"
CONFIG_HASH = '9fbec75f8d84c2f25fbc6659e731d2fcf30860883ea8f127a29eefe4c8051aa4'
POLICY = "source_bound_marks_devotion_transmission_experiment_v1"
TRANSMISSION_POLICY = "original_slot_order_cyclic_remove_insert_experiment_v1"
POLICIES = {"marks": POLICY, "replacement": "different_kind_replaces_same_polarity_experiment",
    "layers": "linear_per_layer_floor_max_hp_clamp_resources_experiment",
    "ratio_damage": "declared_max_hp_floor_no_type_bonus_experiment",
    "devotion": "team_persistent_uncapped_fixed_enhancements_experiment",
    "transmission": TRANSMISSION_POLICY}
EMPTY = {"positive": None, "negative": None}
DEVOTIONS = {"power", "hits", "poison", "cost", "lifesteal"}
IDENTITIES = ROOT / 'data/rules/reviewed-mark-identities-1.json'
IDENTITIES_HASH = 'b843c1876c447a0d4790f14123f87daf942cfb8fb87c461e6be57d06a89890f4'
COMPONENTS = {"attack", "mark.add", "mark.clear", "mark.increment_existing", "mark.double",
              "devotion.add", "status", "energy", "heal"}


@lru_cache(maxsize=2)
def _configuration(stamp):
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    if data.get("schema") != "reviewed-mark-components-1" or fingerprint(data) != CONFIG_HASH:
        raise ValueError("Mark component configuration changed; review required")
    for source in data["sources"]:
        path = (ROOT / source["path"]).resolve()
        if not path.is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("Extracted mark evidence changed; review required")
    return data


def rules():
    # Return detached data: caller edits cannot alter cached executable rules.
    return deepcopy(_data())


def _data():
    data = _configuration(CONFIG.stat().st_mtime_ns)
    for source in data["sources"]:
        path = ROOT / source["path"]
        stat = path.stat()
        if _evidence_hash(str(path), stat.st_size, stat.st_mtime_ns) != source["sha256"]:
            raise ValueError("Extracted mark evidence changed; review required")
    return data


@lru_cache(maxsize=16)
def _evidence_hash(path, size, stamp):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def research_context():
    from lab.dark_surge_runtime import research_context as dark_context
    return {"mark_policies": deepcopy(POLICIES), **dark_context()}


@lru_cache(maxsize=2)
def _identities(stamp):
    data = json.loads(IDENTITIES.read_text(encoding='utf8'))
    if fingerprint(data) != IDENTITIES_HASH or data['snapshot_id'] != _data()['snapshot_id']:
        raise ValueError('Mark identity sources changed; review required')
    return data


@cached_source_query
def _identity_data():
    data = _identities(IDENTITIES.stat().st_mtime_ns)
    for relative, expected in data['sources'].items():
        path = ROOT / relative
        stat = path.stat()
        if _evidence_hash(str(path), stat.st_size, stat.st_mtime_ns) != expected:
            raise ValueError('Native independent mark mapping source changed')
    return data


def mark_identity(buff_id):
    identity = _identity_data()['buff_identities'].get(str(buff_id))
    return dict(identity) if identity else None


def iter_marks(member):
    """Normal polarity slots and bard marks are separate calculation instances."""
    normal = [m for m in _slots(member).values() if m is not None]
    independent = member.get('independent_field_marks', [])
    if (not isinstance(independent, list) or any(not isinstance(m, dict) for m in independent)
            or len({m.get('id') for m in independent}) != len(independent)):
        raise ValueError('Independent mark identities must be distinct')
    for mark in independent:
        spec = _data()['marks'].get(str(mark.get('id')))
        if spec is None or mark.get('independent') is not True:
            raise ValueError('Independent mark source channel is missing')
        identity = mark_identity(mark.get('buff_id'))
        if not identity or not identity['independent'] or identity['mark_id'] != mark['id']:
            raise ValueError('Independent mark differs from native replacement identity')
        if not 1 <= _integer(mark.get('stacks'), 'independent layers', 1) <= spec['cap']:
            raise ValueError('Independent mark layers exceed cap')
    return [*normal, *independent]


def _policy(context):
    if not isinstance(context, dict) or context.get("mark_policies") != POLICIES:
        raise ValueError("Explicit mark/devotion/transmission research policies required")


def validate_marks(marks):
    if not isinstance(marks, dict) or set(marks) != set(EMPTY):
        raise ValueError("Marks require exactly one positive and one negative slot")
    fingerprint(marks)
    for polarity, mark in marks.items():
        if mark is None:
            continue
        if not isinstance(mark, dict) or type(mark.get("id")) is not int:
            raise ValueError("A mark must have an integer term ID")
        spec = _data()["marks"].get(str(mark["id"]))
        if spec is None or spec["polarity"] != polarity:
            raise ValueError("Unknown mark or conflicting polarity")
        if not 1 <= _integer(mark.get("stacks"), "mark stacks", 1) <= spec["cap"]:
            raise ValueError("Mark layers exceed the reviewed installed cap")


def _slots(member):
    marks = member.get("field_marks", deepcopy(EMPTY))
    validate_marks(marks)
    return marks


def layer_count(member, mark_id=None):
    return sum(m["stacks"] for m in iter_marks(member)
               if m is not None and (mark_id is None or m["id"] == mark_id))


def _devotion(member):
    values = member.get("team_devotion", {})
    if not isinstance(values, dict) or set(values) - DEVOTIONS:
        raise ValueError("Unknown team devotion enhancement")
    for key, value in values.items():
        _integer(value, "devotion " + key)
    return values


def attach_relative_marks(current, side):
    """Build the existing relative actor state plus temporary team-owned fields."""
    from lab.action_runtime import _relative
    if side not in ("a", "b"):
        raise ValueError("Unknown battle side")
    from lab.cute_runtime import validate as validate_cute
    relative = _relative(current, side)
    for key, absolute in (("self", side), ("opponent", "b" if side == "a" else "a")):
        team = current["teams"][absolute]
        marks = team.get("marks")
        validate_marks(marks)
        relative[key]["field_marks"] = deepcopy(marks)
        if 'independent_marks' in team:
            relative[key]['independent_field_marks'] = deepcopy(team['independent_marks'])
            iter_marks(relative[key])
        relative[key]["team_devotion"] = deepcopy(team.get("devotion", {}))
        other = 'b' if absolute == 'a' else 'a'
        relative[key]['trait_team_roster'] = {
            label: [{'member_id':m['member_id'], 'types':deepcopy(m.get('types')), 'hp':m['hp'], 'skill_slots':deepcopy(m['skill_slots']),
                     'cute_layers': validate_cute(m)}
                    for m in current['teams'][team_side]['members']]
            for label, team_side in (('self', absolute), ('opponent', other))}
        if all('committed_skill_history' in m for t in current['teams'].values() for m in t['members']):
            from lab.action_outcome_runtime import committed_history
            relative[key]['battle_skill_history'] = [deepcopy(e) for t in current['teams'].values()
                for m in t['members'] for e in committed_history(m)]

        _devotion(relative[key])
    return relative


def commit_marks(current, side, fragment):
    """Commit team fields and strip temporary fields before normal actor commit.

    Mutates only the explicitly supplied current/fragment commit targets. Call
    after a successful fragment and before assigning fragment actors to members.
    """
    if fragment.get("status") != "applied" or side not in ("a", "b"):
        raise ValueError("Only an applied mark fragment can be committed")
    for key in ("self", "opponent"):
        validate_marks(_slots(fragment["state"][key]))
        _devotion(fragment["state"][key])
    for key, absolute in (("self", side), ("opponent", "b" if side == "a" else "a")):
        actor = fragment["state"][key]
        actor.pop('trait_team_roster', None)
        actor.pop('battle_skill_history', None)
        if "field_marks" in actor:
            current["teams"][absolute]["marks"] = actor.pop("field_marks")
        if 'independent_field_marks' in actor:
            current['teams'][absolute]['independent_marks'] = actor.pop('independent_field_marks')
        if "team_devotion" in actor:
            current["teams"][absolute]["devotion"] = actor.pop("team_devotion")
    return fragment


def _programs(catalog, blocked):
    prepared = prepare_rules(catalog)
    source, data = prepared._rules._catalog, _data()
    if (source["snapshot_id"] != data["snapshot_id"]
            or source.get("provenance", {}).get("Terms", {}).get("content_sha256") != data["terms_hash"]):
        raise ValueError("Mark skill snapshot/Terms require review")
    glossary = {str(x["key"]): x for x in source["glossary"]}
    if any(glossary.get(k) != row for k, row in data["terms"].items()):
        raise ValueError("Reviewed mark/devotion/transmission terms differ")
    records = source["moves"]
    records = records if isinstance(records, dict) else {str(x["id"]): x for x in records}
    output = {}
    for key, row in data["skills"].items():
        if bool(row["component_blockers"]) != blocked:
            continue
        if (fingerprint(records.get(key)) != row["record_hash"]
                or any(x.get("op") not in COMPONENTS for x in row["components"])):
            continue
        program = deepcopy(prepared._rules.program(int(key)))
        program.pop("native_rule", None)
        program.update(status="compiled", blockers=[], execution_blockers=[], operations=[],
            mark_components=deepcopy(row["components"]), mark_source_record=deepcopy(row["raw"]),
            mark_config_hash=CONFIG_HASH, mark_policy=POLICY,
            mark_installation_evidence=deepcopy(row["installation_evidence"]),
            mark_policy_uncertainties=deepcopy(data["uncertainties"]),
            response_kinds=deepcopy(row.get("response_kinds", [])),
            executable=False, real_game_verified=False, training_eligible=False)
        if blocked:
            program.update(status="blocked", blockers=[x["detail"] for x in row["component_blockers"]],
                execution_blockers=deepcopy(row["component_blockers"]),
                mark_component_blockers=deepcopy(row["component_blockers"]))
        output[int(key)] = program
    return output


def mark_programs(catalog):
    """Only complete reviewed components become executable program overrides."""
    return _programs(catalog, False)


def blocked_mark_programs(catalog):
    return _programs(catalog, True)


def mark_capabilities(catalog):
    programs = {**mark_programs(catalog), **blocked_mark_programs(catalog)}
    return {key: {"status": p["status"], "component_blockers": deepcopy(p.get("mark_component_blockers", [])),
                  "components": deepcopy(p["mark_components"]), "raw": deepcopy(p["mark_source_record"]),
                  "evidence": deepcopy(p["mark_installation_evidence"]), "real_game_verified": False}
            for key, p in programs.items()}


def _program(program):
    row = _data()["skills"].get(str(program.get("game_id")))
    if (not row or row["component_blockers"] or program.get("mark_components") != row["components"]
            or program.get("mark_source_record") != row["raw"]
            or program.get("source_hash") != row["record_hash"]
            or program.get("mark_config_hash") != CONFIG_HASH or program.get("mark_policy") != POLICY
            or program.get("snapshot_id") != _data()["snapshot_id"]
            or program.get("term_source", {}).get("content_sha256") != _data()["terms_hash"]
            or program.get("response_kinds") != row.get("response_kinds", [])
            or program.get("mark_installation_evidence") != row["installation_evidence"]
            or program.get("operations") != [] or "native_rule" in program):
        raise ValueError("Mark program/source drift requires review")
    return row


def preflight_mark_skill(program, state, context, damage_resolver=None, mark_damage_resolver=None):
    _preflight_header(program, state, context)
    _policy(context)
    row = _program(program)
    if "resolved_energy_cost" not in context:
        raise ValueError("An explicit mark skill energy payment is required")
    for member in (state["self"], state["opponent"]):
        _slots(member)
        _devotion(member)
    for component in row["components"]:
        if component["op"] == "attack" and not callable(damage_resolver):
            raise ValueError("An explicit damage resolver is required")
        if component.get("response") and type(context.get("response_success")) is not bool:
            raise ValueError("Response mark effects require explicit response_success")
        if component.get("slot_bonus"):
            _skill_slot(state["self"], program["game_id"], context)


def preflight_with_marks(program, state, context, *, damage_resolver=None,
                         mark_damage_resolver=None, preflight_base=None):
    """One header/mark dependency gate before any dispatcher spends resources."""
    if program.get("wish_adaptive_damage"):
        from lab.hud_damage_runtime import resolve_adaptive_program
        program = resolve_adaptive_program(program, state, context)
        context = {**context, "skill_kind": program["wish_resolved_damage_kind"]}
    _preflight_header(program, state, context)
    _policy(context)
    for member in state["self"], state["opponent"]:
        _slots(member)
        _devotion(member)
    kind, skill_type = _skill_identity(program, context)
    if layer_count(state["opponent"], 1035) and kind is None:
        raise ValueError("Star preflight requires explicit attacking skill kind before execution")
    attacks = kind in ("physical", "magical")
    if attacks and layer_count(state["opponent"], 1035):
        if not isinstance(skill_type, str):
            raise ValueError("Star preflight requires resolved skill type before execution")
        if skill_type != "幻系" and not callable(mark_damage_resolver):
            raise ValueError("Star 20-power damage requires the shared damage resolver")
    if "mark_components" in program:
        preflight_mark_skill(program, state, context, damage_resolver, mark_damage_resolver)
    elif preflight_base is not None:
        preflight_base(deepcopy(program), deepcopy(state), deepcopy(context), damage_resolver=damage_resolver)


def _skill_identity(program, context):
    """Skill kind/type from the runtime context, falling back to the program.

    The turn dispatcher does not always put ``skill_kind``/``skill_type`` into
    the fragment context; when it is absent the compiled program's own damage
    params are authoritative. ``None`` therefore means "look at the program",
    not "unknown" — an absent key and an explicit ``None`` behave the same.
    """
    record = program.get("mark_source_record", {})
    damage = [x.get("params", {}) for x in program.get("operations", [])
              if x.get("op") in {"damage", "damage.sequence", "damage.conditional"}]
    source = record or (damage[0] if damage else {})
    kind = context.get("skill_kind")
    skill_type = context.get("skill_type")
    return (kind if kind is not None else source.get("kind"),
            skill_type if skill_type is not None else source.get("type"))


def execute_with_marks(program, state, context, *, damage_resolver=None,
                       mark_damage_resolver=None, execute_base=None, preflight_base=None):
    """Atomic dispatcher with pre-existing mark triggers and after-skill phase.

    Parent supplies its existing defense/weather/native dispatcher as execute_base
    if needed. It accepts (program, state, context, *, damage_resolver). Power,
    cost and speed hooks remain explicit parent inputs to avoid applying twice.
    """
    result = {"status": "blocked", "state": deepcopy(state), "events": [], "blockers": [],
              "training_eligible": False, "real_game_verified": False, "calibrated": False}
    try:
        context = deepcopy(context)
        if program.get("wish_adaptive_damage"):
            from lab.hud_damage_runtime import resolve_adaptive_program
            program = resolve_adaptive_program(program, state, context)
            context["skill_kind"] = program["wish_resolved_damage_kind"]
        kind, skill_type = _skill_identity(program, context)
        context.update(skill_kind=kind, skill_type=skill_type)
        preflight_with_marks(program, state, context, damage_resolver=damage_resolver,
            mark_damage_resolver=mark_damage_resolver, preflight_base=preflight_base)
        if "mark_components" in program:
            fragment = execute_mark_skill(program, state, context, damage_resolver=damage_resolver,
                                          mark_damage_resolver=mark_damage_resolver)
        else:
            if execute_base is None:
                from lab.skill_execution import execute_skill
                execute_base = execute_skill
            fragment = execute_base(deepcopy(program), deepcopy(state), deepcopy(context), damage_resolver=damage_resolver)
        if fragment["status"] != "applied":
            raise ValueError("; ".join(fragment["blockers"]))
        current, events = deepcopy(fragment["state"]), deepcopy(fragment["events"])
        if "mark_components" not in program and any(e.get("op") == "damage" for e in events):
            trigger = mark_phase(current, "after_attack", context=context, damage_resolver=mark_damage_resolver)
            if trigger["status"] != "applied":
                raise ValueError("; ".join(trigger["blockers"]))
            current, extra = trigger["state"], trigger["events"]
            events += extra
        after = mark_phase(current, "after_skill", context=context, damage_resolver=mark_damage_resolver)
        if after["status"] != "applied":
            raise ValueError("; ".join(after["blockers"]))
        result.update(deepcopy(fragment))
        result.update(status="applied", state=after["state"], events=events + after["events"],
                      training_eligible=False, real_game_verified=False, calibrated=False)
    except Exception as exc:
        result["blockers"] = [str(exc)]
    return result


def _skill_slot(member, skill_id, context):
    slots = member.get("skill_slots")
    if not isinstance(slots, list) or len(slots) != 4 or slots.count(skill_id) != 1:
        raise ValueError("Position effects require four ordered, unique carried skill IDs")
    slot = slots.index(skill_id)
    if "skill_slot" in context and context["skill_slot"] != slot:
        raise ValueError("Selected slot conflicts with carried skill order")
    return slot


def _mark_add(member, mark_id, amount, source):
    _integer(amount, "mark amount")
    if source.get('granting_trait_id') == 200225:
        config = _identities(IDENTITIES.stat().st_mtime_ns)
        if source.get('granting_trait_hash') != config['trait_hash']:
            raise ValueError('Independent mark granting trait source changed')
        existing = [m for m in iter_marks(member) if m.get('independent') and m['id'] == mark_id]
        old = existing[0] if existing else None
        if not amount:
            return []
        spec = _data()['marks'][str(mark_id)]
        bid = next(int(k) for k, v in config['buff_identities'].items() if v['mark_id'] == mark_id and v['independent'])
        before = old['stacks'] if old else 0
        after = min(spec['cap'], before + amount)
        value = {'id': mark_id, 'stacks': after, 'buff_id': bid, 'independent': True,
                 'sources': [*(old.get('sources', []) if old else []), deepcopy(source)]}
        member['independent_field_marks'] = [m for m in member.get('independent_field_marks', []) if m['id'] != mark_id] + [value]
        return [{'op': 'mark.add', 'mark_id': mark_id, 'independent': True, 'before': deepcopy(old),
                 'after': deepcopy(value), 'source': deepcopy(source)}]
    slots = deepcopy(_slots(member))
    spec = _data()["marks"][str(mark_id)]
    old = deepcopy(slots[spec["polarity"]])
    if not amount:
        return []
    before = old["stacks"] if old and old["id"] == mark_id else 0
    after = min(spec["cap"], before + amount)
    sources = deepcopy(old.get("sources", [])) if old and old["id"] == mark_id else []
    sources.append({**deepcopy(source), "requested_layers": amount, "added_layers": after - before})
    slots[spec["polarity"]] = {"id": mark_id, "stacks": after, "sources": sources}
    member["field_marks"] = slots
    return [{"op": "mark.add", "mark_id": mark_id, "polarity": spec["polarity"],
             "before": old, "after": deepcopy(slots[spec["polarity"]]), "cap": spec["cap"],
             "source": deepcopy(source), "replacement_policy": POLICIES["replacement"]}]


def _increase_existing(member, mark, amount, source):
    bound = {k: v for k, v in source.items() if k not in ('granting_trait_id', 'granting_trait_hash')}
    if mark.get('independent'):
        bound.update(granting_trait_id=200225,
                     granting_trait_hash=_identities(IDENTITIES.stat().st_mtime_ns)['trait_hash'])
    return _mark_add(member, mark['id'], amount, bound)


def change_marks(marks, mark_id, amount, *, context, source):
    """Pure generic signed-layer edit; zero removes a slot and never creates it."""
    _policy(context)
    validate_marks(marks)
    if type(amount) is not int or type(mark_id) is not int or str(mark_id) not in _data()["marks"]:
        raise ValueError("Known mark ID and signed integer amount required")
    if not isinstance(source, dict) or not source:
        raise ValueError("Mark source must be explicit")
    fingerprint(source)
    if source.get('granting_trait_id') == 200225:
        raise ValueError('Independent grants require a member-owned channel, not normal-slot-only change_marks')
    member = {"field_marks": deepcopy(marks)}
    if amount >= 0:
        events = _mark_add(member, mark_id, amount, source)
    else:
        polarity = _data()["marks"][str(mark_id)]["polarity"]
        old = deepcopy(member["field_marks"][polarity])
        if old is None or old["id"] != mark_id:
            events = []
        else:
            after = max(0, old["stacks"] + amount)
            member["field_marks"][polarity] = {**old, "stacks": after} if after else None
            events = [{"op": "mark.consume", "mark_id": mark_id, "before": old["stacks"],
                       "after": after, "consumed": old["stacks"] - after, "source": deepcopy(source)}]
    return member["field_marks"], events


def steal_one_mark(state, *, context, source, eligible_buff_ids):
    """Conservative transfer: no guessed polarity, replacement or layer lineage."""
    _policy(context)
    current = deepcopy(state)
    donor, receiver = current['opponent'], current['self']
    donor_marks, receiver_marks = deepcopy(_slots(donor)), deepcopy(_slots(receiver))
    candidates = [(polarity, mark) for polarity, mark in donor_marks.items() if mark is not None]
    if not candidates:
        return {'status': 'applied', 'state': current, 'events': [], 'blockers': []}
    if len(candidates) != 1:
        raise ValueError('Stealing among both enemy mark polarities has no source-resolved selection order')
    polarity, mark = candidates[0]
    spec = _data()['marks'][str(mark['id'])]
    if spec['buff_raw']['id'] not in eligible_buff_ids:
        raise ValueError('Enemy mark is absent from the extracted steal-effect candidate list')
    old = receiver_marks[polarity]
    if old is not None and old['id'] != mark['id']:
        raise ValueError('Stealing over a different same-polarity mark has unresolved replacement semantics')
    if old is not None and old['stacks'] >= spec['cap']:
        raise ValueError('Stealing into a capped mark has unresolved loss/transfer semantics')
    sources = mark.get('sources', [])
    if not isinstance(sources, list) or any(not isinstance(item, dict)
            or type(item.get('added_layers', 1)) is not int for item in sources):
        raise ValueError('Mark stealing requires preserved donor contribution records')
    contributions = [item for item in sources if item.get('added_layers', 1) > 0]
    if len(contributions) > 1:
        raise ValueError('Selecting one stolen layer among multiple donor source histories is unresolved')
    transfer = {**deepcopy(source), 'stolen_mark_id': mark['id'],
        'donor_sources': deepcopy(mark.get('sources', [])), 'transferred_layers': 1}
    donor['field_marks'], consumed = change_marks(donor_marks, mark['id'], -1, context=context, source=transfer)
    gained = _mark_add(receiver, mark['id'], 1, transfer)
    return {'status': 'applied', 'state': current, 'events': [
        *[{**event, 'target': 'opponent'} for event in consumed],
        *[{**event, 'target': 'self'} for event in gained]], 'blockers': [],
        'training_eligible': False, 'real_game_verified': False}


def _effect(program, state, context, operation, damage_resolver=None):
    fragment = deepcopy(program)
    fragment["operations"] = [operation]
    if operation["op"] == "damage.sequence":
        fragment["dependency_ids"] = sorted(set(fragment.get("dependency_ids", [])) | {3005})
    payment = deepcopy(context)
    payment.pop("resolved_energy_cost", None)
    result = execute_effects(fragment, state, payment, damage_resolver=damage_resolver)
    if result["status"] != "applied":
        raise ValueError("; ".join(result["blockers"]))
    return result["state"], result["events"]


def _primitive(op, target, **params):
    return {"op": op, "params": {"target": target, **params}}


def execute_mark_skill(program, state, context, *, damage_resolver=None, mark_damage_resolver=None):
    result = {"status": "blocked", "state": deepcopy(state), "events": [], "blockers": [],
              "training_eligible": False, "real_game_verified": False, "calibrated": False,
              "full_turn_executed": False, "mark_policy": POLICY}
    try:
        preflight_mark_skill(program, state, context, damage_resolver, mark_damage_resolver)
        current, events = deepcopy(state), []
        cost = context["resolved_energy_cost"]
        current["self"]["energy"] -= cost
        events.append({"op": "energy.pay", "target": "self", "amount": cost, "source": "caller_resolved_cost"})
        source = {"skill_id": program["game_id"], "source_hash": program["source_hash"],
                  "member_id": context.get("actor_member_id", state["self"].get("member_id"))}
        if current['self'].get('trait_id') == 200225:
            source.update(granting_trait_id=200225,
                granting_trait_hash=_identities(IDENTITIES.stat().st_mtime_ns)['trait_hash'])
        for component in program["mark_components"]:
            op = component["op"]
            if component.get("response") and not context["response_success"]:
                continue
            target = component.get("target", "self")
            member = current[target]
            if op == "attack":
                power, hits = component["power"], component["hits"]
                count = layer_count(current["opponent"])
                power += component.get("power_per_mark", 0) * count
                power += component.get("power_if_any_mark", 0) if count else 0
                hits += component.get("hits_per_star_layer", 0) * layer_count(current["opponent"], 1035)
                bonus = component.get("slot_bonus")
                if bonus and _skill_slot(current["self"], program["game_id"], context) in bonus["slots"]:
                    power += bonus["power"]
                    hits += bonus["hits"]
                devotion = deepcopy(_devotion(current["self"])) if component.get("devotion_consumer") else {}
                power += 20 * devotion.get("power", 0)
                hits += devotion.get("hits", 0)
                params = {"kind": component["kind"], "type": component["type"], "power": power}
                if hits > 1:
                    params["hits"] = hits
                operation = _primitive("damage.sequence" if hits > 1 else "damage", "opponent", **params)
                current, extra = _effect(program, current, context, operation, damage_resolver)
                events += extra
                if layer_count(current["opponent"], 1035) and component["type"] != "幻系":
                    trigger = mark_phase(current, "after_attack", context={**context,
                        "skill_kind": component["kind"], "skill_type": component["type"]},
                        damage_resolver=mark_damage_resolver)
                    if trigger["status"] != "applied":
                        raise ValueError("; ".join(trigger["blockers"]))
                    current = trigger["state"]
                    events += trigger["events"]
                if devotion.get("poison") and current["opponent"]["hp"]:
                    current, extra = _effect(program, current, context,
                        _primitive("status.add", "opponent", status="poison", stacks=2 * devotion["poison"]))
                    events += extra
                damage = sum(e.get("damage", 0) for e in events if e.get("op") == "damage")
                if devotion.get("lifesteal") and damage and current["self"]["hp"]:
                    actor = current["self"]
                    before = actor["hp"]
                    requested = damage * devotion["lifesteal"] // 10
                    actor["hp"] = min(actor["max_hp"], before + requested)
                    from lab.trait_runtime import after_hp_restore
                    events.extend(after_hp_restore(current, "self", requested, actor["hp"] - before, context))
                    events.append({"op": "devotion.lifesteal", "target": "self", "before": before,
                                   "after": actor["hp"], "damage_basis": damage})
            elif op == "mark.add":
                amount = layer_count(member) if component.get("amount_from_existing") else component["amount"]
                if component.get("if_absent") and layer_count(member, component["id"]):
                    continue
                if component.get("per_use_increment"):
                    uses = current["self"].setdefault("mark_skill_uses", {})
                    count = _integer(uses.get(str(program["game_id"]), 0), "permanent mark skill uses")
                    amount += count * component["per_use_increment"]
                    uses[str(program["game_id"])] = count + 1
                events += [{**e, "target": target} for e in _mark_add(member, component["id"], amount, source)]
            elif op == "mark.double":
                for old in iter_marks(member):
                    if old['id'] == component['id']:
                        events += [{**e, 'target': target} for e in _increase_existing(member, old, old['stacks'], source)]
            elif op == "mark.increment_existing":
                for relative in component["targets"]:
                    for old in iter_marks(current[relative]):
                        if old:
                            events += [{**e, "target": relative} for e in _increase_existing(current[relative], old, component['amount'], source)]
            elif op == "mark.clear":
                total = 0
                for relative in component["targets"]:
                    removed = deepcopy(_slots(current[relative]))
                    count = layer_count(current[relative])
                    total += count
                    current[relative]["field_marks"] = deepcopy(EMPTY)
                    if 'independent_field_marks' in current[relative]:
                        removed['independent'] = current[relative]['independent_field_marks']
                        current[relative]['independent_field_marks'] = []
                    events.append({"op": "mark.dispel", "target": relative, "removed": removed, "layers": count})
                reward = component["reward"]
                if total:
                    if reward["op"] == "stat":
                        operation = _primitive("stat.modify", "self", attributes=[reward["stat"]], percent={"numerator": total * reward["percent"], "denominator": 100})
                    elif reward["op"] == "burn":
                        operation = _primitive("status.add", "opponent", status="burn", stacks=total * reward["amount"])
                    else:
                        operation = _primitive("hp.restore", "self", percent={"numerator": total * reward["percent"], "denominator": 100})
                    current, extra = _effect(program, current, context, operation)
                    events += extra
            elif op == "devotion.add":
                values = deepcopy(_devotion(member))
                enhancement = component["enhancement"]
                values[enhancement] = values.get(enhancement, 0) + component["amount"]
                member["team_devotion"] = values
                events.append({"op": op, "target": "self", "enhancement": enhancement,
                               "after": values[enhancement], "source": source, "policy": POLICIES["devotion"]})
            else:
                if op == "status":
                    operation = _primitive("status.add", target, status=component["status"], stacks=component["amount"])
                elif op == "energy":
                    operation = _primitive("energy.restore", target, amount=component["amount"])
                elif op == "heal":
                    operation = _primitive("hp.restore", target, percent={"numerator": component["percent"], "denominator": 100})
                else:
                    raise ValueError("Unsupported mark component")
                current, extra = _effect(program, current, context, operation)
                events += extra
        result.update(status="applied", state=current, events=events)
    except Exception as exc:
        result["blockers"] = [str(exc)]
    return result


def modify_cost(member, base_cost, skill_id=None, opponent=None, skill_kind=None):
    _integer(base_cost, "base cost")
    value = base_cost
    row = _data()["skills"].get(str(skill_id), {})
    if skill_kind is None:
        skill_kind = row.get("raw", {}).get("kind")
    for mark in iter_marks(member):
        if mark:
            for effect in _data()["marks"][str(mark["id"])]["effects"]:
                if effect["op"] == "cost_add" or effect["op"] == "attack_cost_add" and skill_kind in ("physical", "magical"):
                    value += effect["value"] * mark["stacks"]
    if row.get("cost_per_opponent_layer"):
        if opponent is None:
            raise ValueError("Mark-scaled skill cost requires explicit opposing field marks")
        value += row["cost_per_opponent_layer"] * layer_count(opponent)
    devotion = _devotion(member)
    if skill_id in (7130100, 7130130):
        value -= 2 * devotion.get("cost", 0)
        if skill_id == 7130100:
            value += sum(devotion.values())
    for component in row.get("components", []):
        bonus = component.get("slot_bonus")
        if bonus and _skill_slot(member, skill_id, {}) in bonus["slots"]:
            value += bonus["cost"]
    from lab.trait_runtime import cost_delta
    return max(0, base_cost + cost_delta(member, value - base_cost))


def modify_power(member, power, skill_kind, *, first_attack=False, first_action=None):
    """Fractional power is retained for the caller's existing damage resolver."""
    value, percent = Fraction(power), 0
    if type(first_attack) is not bool:
        raise ValueError("First-attack flag must be explicit boolean")
    for mark in iter_marks(member):
        if not mark:
            continue
        for effect in _data()["marks"][str(mark["id"])]["effects"]:
            op = effect["op"]
            if (op == "power_percent" or op == "attack_power_percent" and skill_kind in ("physical", "magical")
                    or op == "first_power_percent" and first_attack and skill_kind in ("physical", "magical")):
                percent += effect["value"] * mark["stacks"]
            elif op == "burst_power" and skill_kind in ("physical", "magical"):
                if type(first_action) is not bool:
                    raise ValueError("Burst mark requires explicit first action after entry")
                if first_action:
                    value += effect["value"] * mark["stacks"]
    return value * Fraction(100 + percent, 100)


def modify_speed(member, speed):
    _integer(speed, "base speed")
    return max(0, speed - 10 * layer_count(member, 1032))


def extra_buff_layers(member, layers):
    _integer(layers, "buff layers")
    return layers + layer_count(member, 3012) if layers else 0


def ratio_damage(descriptor, state, context):
    """Known source ratios only; no unverified interpretation of star params."""
    _policy(context)
    if descriptor.get("op") != "mark.damage_ratio" or descriptor.get("mark_id") != 1014 or descriptor.get("rate") != [3, 100]:
        raise ValueError("No reviewed damage ratio exists for this mark component")
    member = state[descriptor["target"]]
    nominal = member["max_hp"] * descriptor["stacks"] * Fraction(*descriptor["rate"])
    return min(member["hp"], nominal.numerator // nominal.denominator)


def mark_phase(state, phase, *, context, damage_resolver=None, random_debuff_resolver=None):
    """Atomic relative phase. Unknown numeric rules never receive defaults.

    after_attack targets opponent's pre-existing stars (call after direct attack,
    before adding new skill marks); it requires skill_kind and skill_type.
    A star resolver gets (descriptor, relative_state, context), returning actual
    bounded HP loss. Dark-surge resolver returns five explicit signed stat terms.
    """
    result = {"status": "blocked", "state": deepcopy(state), "events": [], "blockers": [],
              "training_eligible": False, "calibrated": False, "real_game_verified": False}
    try:
        _policy(context)
        _state(state)
        if phase not in {"round_end", "after_switch", "after_skill", "after_attack"}:
            raise ValueError("Unknown mark phase")
        current, events = deepcopy(state), []
        sides = ["opponent"] if phase == "after_attack" else ["self"] if phase in {"after_skill", "after_switch"} else ["self", "opponent"]
        if "mark_phase_targets" in context:
            requested = context["mark_phase_targets"]
            if not isinstance(requested, list) or not requested or any(x not in sides for x in requested) or len(set(requested)) != len(requested):
                raise ValueError("Mark phase targets must be explicit distinct eligible relative actors")
            sides = requested
        for side in sides:
            member = current[side]
            for mark in iter_marks(member):
                if mark is None or not member["hp"]:
                    continue
                spec = _data()["marks"][str(mark["id"])]
                for effect in spec["effects"]:
                    if effect["phase"] != phase:
                        continue
                    event = {"op": "mark.trigger", "phase": phase, "target": side,
                        "mark_id": mark["id"], "stacks": mark["stacks"], "source": deepcopy(mark.get("sources", [])),
                        "term": deepcopy(spec["term"]), "policy": POLICY}
                    if mark.get('independent'):
                        event.update(independent=True, buff_id=mark['buff_id'],
                                     order_policy='normal_then_independent_unverified')
                    op = effect["op"]
                    if op in {"damage_ratio", "hp_loss_ratio"}:
                        value = member["max_hp"] * mark["stacks"] * Fraction(*effect["rate"])
                        if op == "damage_ratio":
                            descriptor = {**event, "op": "mark.damage_ratio", "type": effect["type"],
                                          "rate": deepcopy(effect["rate"]), "max_hp_basis": member["max_hp"]}
                            resolver = damage_resolver or ratio_damage
                            amount = resolver(deepcopy(descriptor), deepcopy(current), deepcopy(context))
                        else:
                            amount = min(member["hp"], value.numerator // value.denominator)
                        _integer(amount, "mark actual HP loss")
                        if amount > member["hp"]:
                            raise ValueError("Mark damage exceeds remaining HP")
                        if op != "hp_loss_ratio":
                            from lab.defense_runtime import prevent_lethal
                            protection = prevent_lethal(member, amount, context.get("turn"))
                            amount = protection["damage"]
                            if protection["event"]:
                                events.append(protection["event"])
                        from lab.trait_runtime import before_hp_loss_relative
                        fatal = before_hp_loss_relative(current, side, amount, context,
                            token=f"{fingerprint(context)}:{phase}:{side}:mark:{mark['id']}" + (":independent" if mark.get("independent") else ""))
                        amount = fatal["damage"]
                        events.extend(fatal["events"])
                        before = member["hp"]
                        member["hp"] -= amount
                        event.update(before=before, after=member["hp"], damage=amount)
                        if mark['id'] == 1014:
                            from lab.trait_runtime import after_periodic_loss_relative
                            events.append(event)
                            events.extend(after_periodic_loss_relative(current, side, 'poison_mark', amount, context))
                            continue

                    elif op == "energy_add":
                        before = member["energy"]
                        requested = effect['value'] * mark['stacks']
                        if requested > 0 and member.get('timed_effects'):
                            from lab.duration_runtime import recovery_amount
                            requested = recovery_amount(member, requested, context.get('turn'))['amount']
                        from lab.trait_runtime import energy_allows_overflow, after_energy_gain
                        total = max(0, before + requested)
                        member['energy'] = total if energy_allows_overflow(member) else min(member['max_energy'], total)
                        events.extend({**e, 'target': side} for e in after_energy_gain(member, max(0, member['energy'] - before), context))
                        event.update(before=before, after=member["energy"])
                    elif op == "cost_three_dual_attack":
                        _integer(context.get("resolved_energy_cost"), "released skill cost")
                        if context["resolved_energy_cost"] != 3:
                            continue
                        for stat in ("patk", "matk"):
                            member["stat_modifiers"].setdefault(stat, []).append({"numerator": effect["value"] * mark["stacks"], "denominator": 100})
                            from lab.modifier_ledger import register_stat
                            register_stat(member, stat, source_kind="mark", source_id=mark["id"], source_hash=fingerprint(spec))
                        event["percent"] = effect["value"] * mark["stacks"]
                    elif op == "star_consume_damage":
                        if context.get("skill_kind") not in ("physical", "magical"):
                            continue
                        if not isinstance(context.get("skill_type"), str):
                            raise ValueError("Star trigger requires the resolved attacking skill type")
                        if context["skill_type"] == effect["type"]:
                            continue
                        if not callable(damage_resolver):
                            raise ValueError("Star 20-power damage requires the shared damage resolver")
                        descriptor = {**event, "op": "mark.star_damage", "type": effect["type"],
                            "power": effect["power_per_stack"] * mark["stacks"],
                            "power_per_stack": effect["power_per_stack"],
                            "source_policy": effect["source_policy"],
                            "raw_buffbase": deepcopy(spec["buffbase_raw"])}
                        amount = damage_resolver(deepcopy(descriptor), deepcopy(current), deepcopy(context))
                        _integer(amount, "star actual HP loss")
                        if amount > member["hp"]:
                            raise ValueError("Star damage exceeds remaining HP")
                        if op != "hp_loss_ratio":
                            from lab.defense_runtime import prevent_lethal
                            protection = prevent_lethal(member, amount, context.get("turn"))
                            amount = protection["damage"]
                            if protection["event"]:
                                events.append(protection["event"])
                        from lab.trait_runtime import before_hp_loss_relative
                        fatal = before_hp_loss_relative(current, side, amount, context,
                            token=f"{fingerprint(context)}:{phase}:{side}:mark:{mark['id']}" + (":independent" if mark.get("independent") else ""))
                        amount = fatal["damage"]
                        events.extend(fatal["events"])
                        before = member["hp"]
                        member["hp"] -= amount
                        consumed = mark["stacks"] // 2 if current["self"].get("trait_id") == 200210 else mark["stacks"]
                        remaining = mark["stacks"] - consumed
                        if mark.get('independent'):
                            member['independent_field_marks'] = [
                                {**m, 'stacks': remaining} if m['id'] == mark['id'] else m
                                for m in member['independent_field_marks'] if m['id'] != mark['id'] or remaining]
                        else:
                            member["field_marks"][spec["polarity"]] = {**deepcopy(mark), "stacks": remaining} if remaining else None
                        event.update(damage=amount, before=before, after=member["hp"],
                                     power=descriptor["power"], consumed_stacks=consumed,
                                     remaining_stacks=remaining, source_policy=effect["source_policy"])
                    elif op == "random_debuff":
                        if not callable(random_debuff_resolver):
                            from lab.dark_surge_runtime import apply as apply_dark_surge
                            events.extend(apply_dark_surge(member, mark['stacks'], context=context))
                            event['policy'] = context.get('dark_surge_policy')
                            events.append(event)
                            continue
                        terms = random_debuff_resolver(deepcopy(event), deepcopy(current), deepcopy(context))
                        if not isinstance(terms, list) or len(terms) != effect["layers"] * mark["stacks"]:
                            raise ValueError("Dark-surge resolver must return five explicit layer terms per mark layer")
                        for term in terms:
                            if (not isinstance(term, dict) or set(term) != {"stat", "numerator", "denominator"}
                                    or term["stat"] not in {"patk", "matk", "pdef", "mdef", "spd"}
                                    or type(term["numerator"]) is not int or term["numerator"] >= 0
                                    or type(term["denominator"]) is not int or term["denominator"] < 1):
                                raise ValueError("Random debuff requires explicit negative rational stat terms")
                            member["stat_modifiers"].setdefault(term["stat"], []).append({k: term[k] for k in ("numerator", "denominator")})
                            from lab.modifier_ledger import register_stat
                            register_stat(member, term["stat"], source_kind="mark", source_id=mark["id"], source_hash=fingerprint(spec))
                        event["resolved_terms"] = deepcopy(terms)
                    else:
                        raise ValueError("Unsupported mark phase effect")
                    events.append(event)
        result.update(status="applied", state=current, events=events)
    except Exception as exc:
        result["blockers"] = [str(exc)]
    return result


def apply_battle_phase(state, side, phase, *, context, damage_resolver=None, random_debuff_resolver=None):
    """Pure battle helper: attach team fields, resolve one side, commit and strip.

    round_end/after_switch/after_skill apply only to ``side``. after_attack
    applies to the opposing field; context supplies the attacking skill kind/type.
    """
    result = {"status": "blocked", "state": deepcopy(state), "events": [], "blockers": [],
              "training_eligible": False, "real_game_verified": False, "calibrated": False}
    try:
        current = deepcopy(state)
        relative = attach_relative_marks(current, side)
        targets = ["opponent"] if phase == "after_attack" else ["self"]
        fragment = mark_phase(relative, phase, context={**context, "turn": current["turn"], "mark_phase_targets": targets},
            damage_resolver=damage_resolver, random_debuff_resolver=random_debuff_resolver)
        if fragment["status"] != "applied":
            raise ValueError("; ".join(fragment["blockers"]))
        commit_marks(current, side, fragment)
        other = "b" if side == "a" else "a"
        for key, absolute in (("self", side), ("opponent", other)):
            team = current["teams"][absolute]
            team["members"][team["active_slot"]] = deepcopy(fragment["state"][key])
        events = [{**event, "target_side": side if event.get("target") == "self" else other}
                  for event in fragment["events"]]
        result.update(status="applied", state=current, events=events)
    except Exception as exc:
        result["blockers"] = [str(exc)]
    return result


def advance_transmission(member, *, context):
    """Pure round-start movement; never claims simultaneous server ordering."""
    from lab.dynamic_skills import duplicate_slots_allowed, remap_member_slots
    from lab.slot_runtime import validate_slot_permutation
    _policy(context)
    current = deepcopy(member)
    slots = current.get("skill_slots")
    if (not isinstance(slots, list) or len(slots) != 4
            or any(type(x) is not int or x < 0 for x in slots)
            or not duplicate_slots_allowed(current)):
        raise ValueError("Transmission requires four valid carried skill slots")
    extras = context.get("transmission_extra", {})
    carried = {str(x) for x in slots if str(x) in _data()["transmission"]}
    if not isinstance(extras, dict) or set(extras) - carried:
        raise ValueError("Extra transmission must identify a carried transmission skill")
    for value in extras.values():
        _integer(value, "extra transmission")
    events = []
    identities = list(range(4))
    from lab.trait_switch_components import transmission_grants
    trait_grants = transmission_grants(current)
    for identity, skill_id in enumerate(list(slots)):
        definition = _data()["transmission"].get(str(skill_id))
        grant = trait_grants.get(identity)
        if definition is None and grant is None:
            continue
        before = list(slots)
        start = identities.index(identity)
        distance = (definition['amount'] if definition else 0) + extras.get(str(skill_id), 0) + (grant['amount'] if grant else 0)
        end = (start + distance) % 4
        step = list(range(4))
        step.insert(end, step.pop(start))
        validate_slot_permutation({'skill_slots': [slots[old] for old in step]}, step)
        slots.insert(end, slots.pop(start))
        identities.insert(end, identities.pop(start))
        events.append({"op": "transmission.move", "skill_id": skill_id, "from_slot": start,
            "to_slot": end, "distance": distance, "before": before, "after": list(slots),
            "policy": TRANSMISSION_POLICY, "source_hash": definition['record_hash'] if definition else grant['source_hash'],
            **({'trait_grant': deepcopy(grant)} if grant else {})})
    events.extend(remap_member_slots(current, identities, turn=context.get('turn')))
    return current, events


def _validate_transmission_owners(state, owners):
    from lab.dynamic_skills import _validate_root, validate_dynamic_member
    if "dynamic_skills" in state:
        _validate_root(state)
    for member in owners:
        validate_dynamic_member(member)
        if ("dynamic_skills" not in state
                and (member.get("dynamic_skill_origins") or member.get("transformation_skill_origins"))):
            raise ValueError("Moving generated/transformed slots require their original carried-slot snapshot")
        charge = member.get("charge")
        if charge is not None:
            slot = charge.get("slot") if isinstance(charge, dict) else None
            if (type(slot) is not int or not 0 <= slot < 4
                    or charge.get("skill_id") != member["skill_slots"][slot]):
                raise ValueError("Charging skill must match its moving slot")


def prepare_battle_transmission(state):
    """Mutate owned state before action selection, once per round.

    Live source/charge bindings move with slot identities. Original carried
    snapshots, historical pool evidence and the shared RNG remain unchanged.
    """
    transmission = _data()["transmission"]
    from lab.trait_switch_components import transmission_grants
    owners = [(side, member) for side, team in state["teams"].items() for member in team["members"]
              if member["hp"] and (any(str(mid) in transmission for mid in member["skill_slots"]) or transmission_grants(member))]
    if not owners:
        return []
    turn = _integer(state.get("turn"), "transmission turn", 1)
    previous = state.get("mark_transmission")
    if previous is not None and (not isinstance(previous, dict) or previous.get("policy") != TRANSMISSION_POLICY
            or type(previous.get("prepared_turn")) is not int or previous["prepared_turn"] not in (turn - 1, turn)):
        raise ValueError("Transmission phase ledger is invalid or skipped a round")
    _validate_transmission_owners(state, [member for _, member in owners])
    if previous and previous["prepared_turn"] == turn:
        return []
    updated, events = [], []
    for side, member in owners:
        moved, extra = advance_transmission(member, context={**research_context(), 'turn':turn})
        updated.append((member, moved))
        events += [{**event, "target_side": side, "target_member_id": member["member_id"], "turn": turn} for event in extra]
    for member, moved in updated:
        member.update(moved)
    state["mark_transmission"] = {"policy": TRANSMISSION_POLICY, "prepared_turn": turn}
    return events


def validate_battle_transmission(state):
    from lab.trait_switch_components import transmission_grants
    if any(member["hp"] and (any(str(mid) in _data()["transmission"] for mid in member["skill_slots"]) or transmission_grants(member))
            for team in state["teams"].values() for member in team["members"]):
        if state.get("mark_transmission") != {"policy": TRANSMISSION_POLICY, "prepared_turn": state["turn"]}:
            raise ValueError("Transmission must be prepared before skill selection; submitted slots cannot be silently rotated")
        _validate_transmission_owners(state, [member for team in state["teams"].values()
            for member in team["members"] if member["hp"] and (any(
                str(mid) in _data()["transmission"] for mid in member["skill_slots"]) or transmission_grants(member))])
