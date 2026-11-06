"""Read-only projection of captured BUFFs into the existing reviewed pure queries."""
from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
import json
import math
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta

from . import action_traits, battle_data, forced_trait_runtime, mark_runtime, trait_runtime, weather_runtime
from .live_inference import _buffs

ROOT = Path(__file__).resolve().parents[1]
STAT_DIM = {"hp": "hp", "phyAtk": "patk", "magAtk": "matk", "phyDef": "pdef", "magDef": "mdef", "spd": "spd"}
STAT_FIELD = {"phyAtk": "phyAtkPercent", "magAtk": "magAtkPercent", "phyDef": "phyDefPercent", "magDef": "magDefPercent", "spd": "speedPercent"}
ENTRY_BUFF_CONFIG = ROOT / "data/rules/reviewed-live-entry-buffs-1.json"
ENTRY_BUFF_CONFIG_HASH = '74c7d0fdc9261bb11a2e9d5976a0aa2f583448060b452a2364f99a9f20867382'
S5_HUD_GATES = ROOT / "data/rules/reviewed-s5-hud-gates-1.json"
S5_HUD_GATES_HASH = "7c56477faeb7db138f689cf54775d46044fd816719e5802e8119ad9c499fa47d"


@lru_cache(maxsize=2)
def _s5_hud_gates(stamp):
    raw = S5_HUD_GATES.read_bytes()
    if hashlib.sha256(raw).hexdigest() != S5_HUD_GATES_HASH:
        raise ValueError("S5伤害待接入清单已变化，需重新核对来源")
    return json.loads(raw)


def validate_damage_support(attacker, defender, skill_id, profile):
    """Block only source-bound S5 damage equations missing reviewed state mapping."""
    from .live_damage import _rules, _effective_base
    from .ruleset import canonical_hash
    gates = _s5_hud_gates(S5_HUD_GATES.stat().st_mtime_ns)
    catalog = None

    def current_catalog():
        nonlocal catalog
        if catalog is None:
            catalog = _rules()[0]
        return catalog

    def block(group, identity, row):
        data = current_catalog()
        if (data.get("snapshot_id") != gates["snapshot_id"]
                or canonical_hash(data.get(group, {}).get(str(identity))) != row["record_hash"]):
            raise ValueError(f"{row['name']}：S5伤害待接入条目与当前快照来源不符")
        raise ValueError(f"{row['name']}：{row['reason']}；暂不用于伤害估计或伤害反推")

    sid = battle_data.canonical_skill(skill_id).get("skill_id", skill_id)
    row = gates["moves"].get(str(sid))
    if row:
        block("moves", sid, row)
    for role, pet in (("attacker", attacker), ("defender", defender)):
        if "_simulation_actor" in pet:
            tid = pet["_simulation_actor"].get("trait_id")
        else:
            tid = pet.get("effectiveTraitId")
            if tid is None:
                form_id = _effective_base(pet)
                tid = battle_data.pet_form(form_id).get("feature_id")
                if tid is None and form_id is not None:
                    form = next((form for form in current_catalog().get("forms", [])
                                 if str(form_id) in (str(form.get("id")), str(form.get("game_id")))), {})
                    tid = form.get("trait_id")
        row = gates["traits"].get(str(tid))
        if row and role in row["damage_roles"] and profile.get("kind") in row["damage_kinds"]:
            block("traits", tid, row)


@lru_cache(maxsize=2)
def _entry_buff_configuration(stamp):
    raw = ENTRY_BUFF_CONFIG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ENTRY_BUFF_CONFIG_HASH:
        raise ValueError("原生入场特性BUFF映射已变化，需重新核对")
    return json.loads(raw)


@trait_runtime.cached_source_query
def _entry_buff_rules():
    data = _entry_buff_configuration(ENTRY_BUFF_CONFIG.stat().st_mtime_ns)
    from .live_damage import _rules
    if data["snapshot_id"] != _rules()[0]["snapshot_id"]:
        raise ValueError("原生入场特性BUFF映射与当前数据快照不匹配")
    for relative, expected in data["source_files"].items():
        path = (ROOT / relative).resolve()
        stat = path.stat()
        if (not path.is_relative_to(ROOT) or
                trait_runtime._source_hash(str(path), stat.st_size, stat.st_mtime_ns) != expected):
            raise ValueError("原生入场特性BUFF来源已变化，需重新核对")
    return data["traits"]


def _observed_entry_buffs(member, pet, fields, *, required=False):
    if "_simulation_actor" in pet:
        return set()
    row = _entry_buff_rules().get(str(member.get("trait_id")))
    if row is None or not set(fields).intersection(row["fields"]):
        return set()
    from .ruleset import canonical_hash
    if (member.get("trait_source_hash") != row["trait_record_hash"] or
            canonical_hash(battle_data._skills().get(str(member["trait_id"]))) != row["native_trait_hash"]):
        raise ValueError("入场特性与实际BUFF的来源不匹配")
    marker = row["marker_id"]
    present = [b for b in captured_buffs(pet) if b.get("id") == marker]
    if not present:
        if required:
            raise ValueError(f"{row['name']}：尚未观测到当前特性加成层数，无法可靠估计；不能将缺失层数当作0")
        return set()  # Missing is not evidence of zero entry-history effects.
    if (len(present) != 1 or type(present[0].get("layers")) is not int or
            not 0 <= present[0]["layers"] <= row["marker_cap"]):
        raise ValueError("原生入场特性BUFF层数未知、重复或超出来源范围")
    if (canonical_hash(_raw_buffs().get(str(marker))) != row["marker_hash"] or
            any(calc_buff(marker).get(k) != v for k, v in row["fields"].items())):
        raise ValueError("原生入场特性BUFF的数值映射已变化")
    return {str(marker)}


@lru_cache(maxsize=1)
def _raw_buffs():
    return json.loads((ROOT / "data/external/buff.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _buff_bases():
    return json.loads((ROOT / "artifacts/unpack_probe_20261025/battle_analysis/tables/parsed/BUFFBASE_CONF.json").read_text(encoding="utf-8"))


def _hp_condition(pet, threshold, above):
    hp, maximum = pet.get("currentHp"), pet.get("maxHp")
    if isinstance(hp, (int, float)) and isinstance(maximum, (int, float)) and maximum > 0:
        return [hp * 100 > maximum * threshold if above else hp * 100 < maximum * threshold]
    percent = pet.get("hpPercent")
    if isinstance(percent, (int, float)):
        # Integer display cannot settle a threshold boundary precisely.
        if percent > threshold + 1:
            return [above]
        if percent < threshold - 1:
            return [not above]
    return [False, True]


def _damage_buff_terms(buff, pet, skill, matchup, incoming=False):
    """Native ordered parameters, rather than description-derived unconditional bonuses.

    Conditional damage multipliers use the preview's explicit final-factor policy;
    their ordering and rounding still require live calibration.
    """
    data = calc_buff(buff.get("id"))
    raw = _raw_buffs().get(str(buff.get("id"))) or {}
    relevant = ("damageTakenPercent",) if incoming else ("flatPowerBonus", "powerPercent")
    if not any(field in data for field in relevant) and not (incoming and 2011048 in raw.get("buff_base_ids", [])):
        return 0, 0, [0, 0]
    flat, power_percent, damage = 0, 0, [0, 0]
    for base_id in raw.get("buff_base_ids", []):
        base = _buff_bases().get(str(base_id)) or {}
        params = [r["params"] for r in base.get("buffbase_param", [])]
        order = base.get("buffbase_order")
        additions = [0]
        if order == 23 and not incoming:
            types = [n for n in params[0] if n]
            codes = {name + "系": code for name, code in battle_data.TYPE_CODES.items()}
            if types and codes.get(skill["type"]) not in types:
                continue
            kinds = [n for n in params[1] if n]
            if kinds and {"physical": 2, "magical": 3}.get(skill["kind"]) not in kinds:
                continue
            if any(any(v for v in params[i]) for i in (2, 3, 7, 8, 9, 11)):
                raise ValueError(f"状态 {buff['id']} / 基础效果 {base_id} 的威力条件尚未接入")
            if params[4] == [2]:
                flat += params[5][0]
            elif params[4] == [1]:
                power_percent += params[5][0] / 100
            else:
                raise ValueError(f"基础效果 {base_id} 的威力运算类型未知")
        elif order == 53 and not incoming:
            if params[1] != [2] or any(any(v for v in p) for p in params[2:5]):
                raise ValueError(f"基础效果 {base_id} 的能耗条件尚未接入")
            cost = skill.get("energy")
            if not isinstance(cost, (int, float)):
                raise ValueError("能耗条件增伤缺少技能基础能耗")
            if cost > params[0][0]:
                flat += params[5][0]
        elif order == 29 and not incoming and base_id == 2029006:
            additions = [params[3][0] / 100 if active else 0
                         for active in _hp_condition(pet, params[2][0] / 100, True)]
        elif order == 42:
            # Native fields: outgoing super/resisted, incoming super/resisted.
            if params[1] != [0] or params[2] != [0]:
                raise ValueError(f"基础效果 {base_id} 的克制修正参数尚未核对")
            additions = [params[3 if incoming else 0][0] if (matchup < 1 if incoming else matchup > 1) else 0]
        elif order == 41 and incoming and base_id == 2041008:
            # The parent is an HP gate installing a separate -20% child BUFF.
            if any(b.get("id") in params[2] for b in captured_buffs(pet)):
                continue
            children = [_raw_buffs().get(str(child), {}).get("buff_base_ids", []) for child in params[2]]
            child_bases = [_buff_bases().get(str(b), {}) for ids in children for b in ids]
            if len(child_bases) != 1 or child_bases[0].get("buffbase_order") != 11:
                raise ValueError(f"基础效果 {base_id} 的条件子状态映射已变化")
            amount = child_bases[0]["buffbase_param"][4]["params"][0] / 100
            additions = [amount if active else 0 for active in _hp_condition(pet, params[1][0], False)]
        elif order == 40 and incoming:
            continue  # Periodic/turn-end protection is not a direct-hit modifier.
        elif order == 11 and incoming:
            additions = [params[4][0] / 100]
        elif order in (23, 29, 41, 53):
            continue
        elif any(field in data for field in relevant) and len(raw.get("buff_base_ids", [])) == 1:
            raise ValueError(f"状态 {buff['id']} 的伤害修正基础效果 {base_id} 尚未核对")
        damage = [damage[0] + min(additions), damage[1] + max(additions)]
    if flat == power_percent == 0 and damage == [0, 0]:
        return 0, 0, [0, 0]
    layers = _buff_layers(buff)
    return flat * layers, power_percent * layers, [v * layers for v in damage]


@lru_cache(maxsize=1)
def _mark_config():
    return mark_runtime.rules()["marks"]


def _simple_buff_base_fields(base):
    """Decode only established stat/power layouts; keep conditional power checks in execution."""
    order = base.get("buffbase_order")
    records = base.get("buffbase_param", [])
    if order not in (1, 23) or any(not isinstance(r.get("params"), list) for r in records):
        return None
    params = [r["params"] for r in records]
    if any(type(v) is not int for p in params for v in p):
        return None
    if order == 1 and len(params) == 3 and params[1] == [0]:
        fields = {29: ("phyAtkPercent", 1), 30: ("magAtkPercent", 1),
                  31: ("phyDefPercent", 1), 32: ("magDefPercent", 1),
                  33: ("phyAtkPercent", -1), 34: ("magAtkPercent", -1),
                  35: ("phyDefPercent", -1), 36: ("magDefPercent", -1)}
        if len(params[0]) == len(params[2]) == 1 and params[0][0] in fields:
            field, sign = fields[params[0][0]]
            return {field: sign * params[2][0] / 100}
    if (order == 23 and len(params) == 12 and len(params[5]) == 1
            and params[6] == [0] and params[10] == [1]):
        if params[4] == [1]:
            return {"powerPercent": params[5][0] / 100}
        if params[4] == [2]:
            return {"flatPowerBonus": params[5][0]}
    return None


@lru_cache(maxsize=4096)
def calc_buff(buff_id):
    known = _buffs().get(str(buff_id))
    if known is not None:
        return known
    raw = _raw_buffs().get(str(buff_id)) or {}
    bases = raw.get("buff_base_ids")
    if not bases:
        return {}
    fields = set(STAT_FIELD.values()) | {"speedFlat", "flatPowerBonus", "powerPercent", "damageTakenPercent", "allowedMoveTypes"}
    candidates = [{k: v for k, v in row.items() if k in fields} for row in _buffs().values() if row.get("baseIds") == bases]
    fingerprints = {json.dumps(c, sort_keys=True) for c in candidates if c}
    if len(fingerprints) == 1:
        return {**json.loads(next(iter(fingerprints))), "source": "identical_BUFFBASE_CONF_references", "baseIds": bases}
    _entry_buff_rules()  # Reuse the verified native tables and snapshot identity.
    combined = {}
    for base_id in bases:
        fields = _simple_buff_base_fields(_buff_bases().get(str(base_id), {}))
        if fields is None:
            return {}  # Do not present a partially understood composite as fully mapped.
        for field, value in fields.items():
            combined[field] = combined.get(field, 0) + value
    return {**combined, "source": "native_BUFFBASE_CONF_components", "baseIds": bases}


def captured_buffs(pet):
    return pet.get("battleBuffs", pet.get("buffs", [])) or []


def _buff_layers(buff):
    value = buff.get("layers")
    if type(value) is not int or value < 0:
        raise ValueError(f"状态{buff.get('id')}的加成层数未确认，不能按0计算")
    return value


def canonical_buff_layers(member):
    """Source identities for canonical stack queries; never install synthetic BUFFs."""
    from .modifier_ledger import status_info, _verify_stat_record, flat_info
    result, fields = {}, {}
    def add(info, field=None):
        ids, layers = info.get("buff_ids", []), info.get("layers")
        if len(ids) != 1 or type(layers) is not int or layers < 0:
            raise ValueError("Canonical stack query needs an unambiguous source BUFF and layer count")
        bid = ids[0]
        if field is not None:
            key = (bid, field)
            fields[key] = fields.get(key, 0) + layers
            layers = fields[key]
        # Repeated applications add within a field; multiple fields share the BUFF.
        result[bid] = max(result.get(bid, 0), layers)
    for status, count in member.get("statuses", {}).items():
        if not count:
            continue
        info = status_info(status)
        raw = _raw_buffs().get(str(info["buff_id"]))
        from .ruleset import canonical_hash
        if canonical_hash(raw) != info["record_hash"]:
            raise ValueError("Canonical status identity differs from the HUD BUFF source")
        add({"buff_ids": [info["buff_id"]], "layers": count})
    for status, count in member.get("weather_statuses", {}).items():
        if count:
            bid = weather_runtime.rules()["status_rules"][status]["buff_id"]
            # Freeze can be installed by both owners; its canonical threshold sums both.
            result[bid] = result.get(bid, 0) + count
    for stat, terms in member.get("stat_modifiers", {}).items():
        records = {r["index"]: r for r in member.get("stat_modifier_sources", {}).get(stat, [])}
        for index, term in enumerate(terms):
            record = records.get(index)
            if record is None:
                raise ValueError("Canonical stack query lacks stat modifier source attribution")
            if record.get("term") != term:
                raise ValueError("Canonical stat modifier source term changed")
            _verify_stat_record(stat, record)
            add(record["classification"], stat)
    for field in ("mechanism_flat_modifiers", "skill_modifiers"):
        for record in member.get(field, []):
            add(flat_info(record, field), record.get("op", field))
    for field in ("skill_attack_grants", "dark_surge_modifiers"):
        for record in member.get(field, []):
            add({"buff_ids": [record["buff_id"]], "layers": record["layers"]})
    if member.get("timed_effects"):
        raise ValueError("Canonical stack query has unresolved timed-effect layer identities")
    return [{"id": bid, "layers": layers} for bid, layers in result.items()]


def _mark_specs(pet):
    specs = _mark_config()
    result = {}
    for buff in captured_buffs(pet):
        identity = mark_runtime.mark_identity(buff.get('id'))
        if identity is None:
            raw = _raw_buffs().get(str(buff.get('id')), {})
            if raw.get('type') == 4 and 26 in raw.get('buff_groupsigns', []):
                raise ValueError(f"印记ID {buff.get('id')} 缺少经过核对的身份映射")
            continue  # type=4 also contains group-0 skill listeners; field marks use group 26.
        mid = str(identity['mark_id'])
        spec = specs[mid]
        layers = buff.get('layers')
        if type(layers) is not int or not 0 <= layers <= spec['cap']:
            raise ValueError('印记层数不符合来源配置，不能自动截断或补值')
        if not layers:
            continue
        key = mid + (':independent' if identity['independent'] else '')
        if key in result:
            raise ValueError('同一印记实例重复下发，不能擅自合并层数')
        result[key] = (layers, {**spec, 'mark_id': int(mid), 'independent': identity['independent'], 'buff_id': buff['id']})
    return result


def actor(pet):
    if "_simulation_actor" in pet:
        return deepcopy(pet["_simulation_actor"])
    from .live_damage import _effective_base, _pet_types
    form_id = _effective_base(pet)
    trait_id = pet.get("effectiveTraitId")
    if trait_id is None:
        trait_id = battle_data.pet_form(form_id).get("feature_id")
    row = trait_runtime._rows().get(trait_id)
    source_row = None
    if trait_id and row is None:
        from .live_damage import _rules
        identity = {'form_id': form_id, 'trait_id': trait_id,
                    'member_id': str(pet.get('petId', pet.get('memberId', form_id)))}
        source_row = (action_traits.source_evidence(_rules()[1], identity)
                      if trait_id in action_traits.ROWS
                      else forced_trait_runtime.source_evidence(_rules()[1], identity))
    member = {"member_id": str(pet.get("petId", pet.get("memberId", form_id))), "form_id": form_id,
        "bloodline_id": pet.get("bloodId"),
        "types": _pet_types(pet), "hp": pet.get("currentHp") if isinstance(pet.get("currentHp"), (int, float)) else (0 if pet.get("alive") is False else 1), "max_hp": pet.get("maxHp"),
        "energy": pet.get("energy"), "trait_id": trait_id, "weather_trait_id": trait_id,
        "trait_policy": trait_runtime.POLICY, "trait_config_hash": trait_runtime.CONFIG_HASH,
        "trait_source_hash": row["record_hash"] if row else source_row["source_hash"] if source_row else None,
        "entered_turn": pet.get("enteredTurn"), "mark_entry_actions": pet.get("entryActionCount"),
        "field_marks": {"positive": None, "negative": None}}
    for mid, (layers, spec) in _mark_specs(pet).items():
        if spec['independent']:
            member.setdefault('independent_field_marks', []).append({
                'id': spec['mark_id'], 'stacks': layers, 'sources': [], 'independent': True, 'buff_id': spec['buff_id']})
            continue
        polarity = spec["polarity"]
        if member["field_marks"][polarity] is not None:
            raise ValueError("同极性出现多种印记，不能擅自选择或累加")
        member["field_marks"][polarity] = {"id": spec['mark_id'], "stacks": layers, "sources": []}
    slots = pet.get("carriedSkillIds")
    if isinstance(slots, list) and len(slots) == 4:
        member["skill_slots"] = slots
        info = [battle_data.skill_info(sid) for sid in slots]
        member["trait_initial_skill_types"] = [next((name + "系" for name, code in battle_data.TYPE_CODES.items() if code == s.get("type_code")), None) for s in info]
        member["trait_carried_costs"] = [s.get("energy") if sid else None for sid, s in zip(slots, info)]
        captured_costs = pet.get("carriedSkillCosts")
        if (isinstance(captured_costs, list) and len(captured_costs) == 4
                and all((value is None if not sid else type(value) is int and value >= 0)
                        for sid, value in zip(slots, captured_costs))):
            member["trait_carried_costs"] = list(captured_costs)
    else:
        member["skill_slots"] = [0, 0, 0, 0]
    member["trait_current_skill_types"] = member.get("trait_initial_skill_types", [None] * 4)
    member["trait_team_roster"] = pet.get("liveContext", {}).get("rosters", {"self": [], "opponent": []})
    if "faintedCounts" in pet.get("liveContext", {}):
        member["trait_team_fainted_counts"] = dict(pet["liveContext"]["faintedCounts"])
    if row and any(c["op"] == "stat.calendar" for c in row.get("components", [])):
        date = pet.get("liveContext", {}).get("gameDate") or datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        policy = trait_runtime.policies()["calendar"]
        _, weekday = trait_runtime.validate_calendar({"date": date, "policy": policy})
        member["trait_calendar_binding"] = {"date": date, "weekday": weekday, "policy": policy, "source_hash": row["record_hash"]}
    return member


def _represented_trait_buffs(member, pet, fields):
    row = trait_runtime._rows().get(member.get("trait_id")) or {}
    installed = set((row.get("installation_evidence") or {}).get("buffs", {}))
    return {str(b["id"]) for b in captured_buffs(pet) if str(b.get("id")) in installed and
            any(field in calc_buff(b["id"]) for field in fields)}


def _buff_identities(pet):
    return {int(b["id"]): b.get("layers", 0) for b in captured_buffs(pet)
            if (_raw_buffs().get(str(b.get("id"))) or {}).get("type") == 1 and b.get("layers", 0) > 0}


def _stat_terms(member, other, pet, opponent, stat):
    if "_simulation_actor" in pet:
        return trait_runtime.stat_terms(member, stat, pet.get("liveContext", {}).get("turn"), opponent=other)
    row = trait_runtime._rows().get(member.get("trait_id")) or {}
    components = row.get("components", []) if row.get("event") == "stats.query" else row.get("stat_query_components", [])
    if components and all(c["op"] == "stat.field_buff_kinds" for c in components):
        kinds = set(_buff_identities(pet)) | set(_buff_identities(opponent))
        return [{"numerator": min(c["cap"], len(kinds)) * c["percent_per"], "denominator": 100}
                for c in components if stat in c["attributes"]]
    for c in components:
        if stat not in c.get("attributes", []):
            continue
        if c["op"] in ("stat.party_fainted", "stat.party_type_exists"):
            if c["op"] == "stat.party_fainted" and "trait_team_fainted_counts" in member:
                continue  # The shared executor validates the synchronized totals.
            rosters = member["trait_team_roster"]
            if c["op"] == "stat.party_type_exists" and any(c["type"] in p["types"] for p in rosters["self"]):
                continue
            scopes = ("self", "opponent") if c.get("scope") == "both" else ("self",)
            if any(len(rosters[side]) < 6 for side in scopes):
                raise ValueError("该特性依赖完整队伍/倒下数量，当前阵容未完整观测")
    return trait_runtime.stat_terms(member, stat, pet.get("liveContext", {}).get("turn"), opponent=other)


def _captured_cost_total(row, component, opponent):
    """Resolve the server's cost-count marker by its reviewed source reference.

    Do not alias by BUFFBASE: this marker shares a generic base with nature buffs.
    """
    markers = set()
    for base in (row.get("installation_evidence") or {}).get("bases", {}).values():
        params = [p["params"] for p in base.get("buffbase_param", [])]
        if (base.get("buffbase_order") == 63 and len(params) > 10
                and params[9] == [2] and params[10] == [component["percent_per"] * 100]):
            markers.update(params[3])
    values = {b.get("layers") for b in captured_buffs(opponent) if b.get("id") in markers}
    if not values:
        return None
    if len(values) != 1 or any(type(value) is not int or not 0 <= value <= component["cap"] for value in values):
        raise ValueError(f"{row['name']}同步能耗层数冲突或无效，不能擅自截断")
    return next(iter(values))


def _trait_powers(owner, other, pet, opponent, skill, power, first):
    if _observed_entry_buffs(owner, pet, ["flatPowerBonus"], required=True):
        return [power]  # Generic BUFF terms already included this observed entry power.
    """Source component bounds for hidden slots, without inventing carried IDs."""
    row = trait_runtime._rows().get(owner.get("trait_id")) or {}
    if "_simulation_actor" in pet:
        return [float(trait_runtime.modify_power(owner, skill, power, opponent=other, first_attack=first))]
    components = row.get("components", [])
    if row.get("event") == "power.query" and len(components) == 1 and trait_runtime._match(row, owner, {**skill, "first_attack": first}):
        c = components[0]
        if c["op"] == "power.opponent_buff_layers":
            layers = sum(_buff_identities(opponent).values())
            return [power * (1 + c["percent_per"] * layers / 100)]
        if c["op"] == "power.initial_carried" and "trait_initial_skill_types" not in owner:
            captured = _entry_buff_rules().get(str(owner.get('trait_id')), {})
            if captured.get('count_component') == c:
                from .ruleset import canonical_hash
                markers = [b for b in captured_buffs(pet) if b.get('id') == captured['marker_id']]
                if markers:
                    if (len(markers) != 1 or owner.get('trait_source_hash') != captured['trait_record_hash']
                            or canonical_hash(battle_data._skills().get(str(owner['trait_id']))) != captured['native_trait_hash']
                            or canonical_hash(_raw_buffs().get(str(captured['marker_id']))) != captured['marker_hash']):
                        raise ValueError('原生携带计数BUFF与特性来源不符')
                    count = _buff_layers(markers[0])
                    if count > captured['marker_cap']:
                        raise ValueError('原生携带计数BUFF超出四槽范围，不能擅自截断')
                    return [power * (1 + count * c['percent_per'] / 100)]
            return [power, power * (1 + 4 * c["percent_per"] / 100)]
        if c["op"] == "power.opponent_total_cost":
            total = _captured_cost_total(row, c, opponent)
            if total is not None:
                return [float(Fraction(str(power)) * (1 + Fraction(total * c["percent_per"], 100)))]
            if "trait_carried_costs" not in other:
                raise ValueError(f"{row['name']}：缺少敌方四槽能耗或同步能耗层数，暂不能可靠估计威力")
        if c["op"] == "power.opponent_types" and "trait_initial_skill_types" not in other:
            known = {t for t in other["trait_current_skill_types"] if t}
            return [power + len(known) * c["amount"], power + 4 * c["amount"]]
    return [float(trait_runtime.modify_power(owner, skill, power, opponent=other, first_attack=first))]


def panel_candidates(pet, stat, opponent):
    from .live_damage import panel_values
    values, source = panel_values(pet, stat)
    if source == "实时面板" and pet.get("battleStatsBasis", "effective") == "effective":
        return values, source  # Captured effective panels already contain their stat BUFFs.
    if source == "实时面板":
        source = "服务器基础面板（含性格，状态层数另算）"
        server_base = True
    else:
        server_base = False
    member, other = actor(pet), actor(opponent)
    field = STAT_FIELD.get(stat)
    percent = sum(data[field] * _buff_layers(b) for b in captured_buffs(pet)
                  if field in (data := calc_buff(b.get("id"))))
    terms = [] if (_represented_trait_buffs(member, pet, [field]) or
                   _observed_entry_buffs(member, pet, [field], required=True)) else _stat_terms(member, other, pet, opponent, STAT_DIM[stat])
    if "_simulation_actor" in pet:
        terms = [*member.get("stat_modifiers", {}).get(STAT_DIM[stat], []), *terms]
    factor = Fraction(1) + Fraction(str(percent)) / 100
    factor += sum((Fraction(t["numerator"], t["denominator"]) for t in terms), Fraction(0))
    if factor <= 0:
        raise ValueError("属性修正后非正，缺少最低面板边界依据")
    weather = pet.get("liveContext", {}).get("weather")
    for effect in weather_runtime.modifiers(weather, "before_damage", actor=member):
        if effect["op"] == "stat_multiplier" and STAT_DIM[stat] in {"attack": "patk", "sp_attack": "matk", "defense": "pdef", "sp_defense": "mdef"}.values():
            allowed = {"attack": "patk", "sp_attack": "matk", "defense": "pdef", "sp_defense": "mdef"}
            if STAT_DIM[stat] in [allowed.get(s) for s in effect.get("stats", [])]:
                # A visible weather installation is already included in generic BUFF terms.
                if not any(b.get("id") == effect.get("source_buff_id") for b in captured_buffs(pet)):
                    factor *= Fraction(str(effect["value"]))
    flat = sum(data["speedFlat"] * _buff_layers(b) for b in captured_buffs(pet)
               if "speedFlat" in (data := calc_buff(b.get("id")))) if stat == "spd" and not server_base else 0
    if "_simulation_actor" in pet and stat == "spd":
        from .mechanism_runtime import modify_speed
        return [modify_speed(member, float(v * factor)) for v in values], source + f"；状态/特性修正×{float(factor):g}"
    return [max(0, float(v * factor) + flat) for v in values], source + f"；状态/特性修正×{float(factor):g}" + (f"，固值{flat:+g}" if flat else "")


def damage_profile(attacker, defender, skill_id, profile):
    from .live_damage import _rules, _pet_types
    validate_damage_support(attacker, defender, skill_id, profile)
    if profile.get('retaliationTraitId') == 200103:
        from .trait_switch_components import retaliation_source
        source = retaliation_source(actor(attacker))
        if (source is None or profile.get('retaliationSource') != source or skill_id != 200103
                or profile.get('kind') != 'physical' or profile.get('power') != 50
                or profile.get('skillType') != '无系别'
                or any(profile.get(key) != 1 for key in ('stab', 'multiplier', 'combined'))):
            raise ValueError('Retaliation profile differs from its exact reviewed trait source')
        return {**profile, 'powerRange': [50, 50], 'finalMultiplierRange': [1, 1],
                'effects': [{'op': 'trait.retaliation', **source}]}
    if profile.get("markId") == 1035:
        return _star_profile(attacker, defender, profile)
    _, rules = _rules()
    owner, other = actor(attacker), actor(defender)
    weather = attacker.get("liveContext", {}).get("weather")
    skill_type = weather_runtime.resolved_skill_type(weather, skill_id, profile.get("skillType"))
    if not skill_type:
        skill_type = profile.get("skillType")
    info = battle_data.skill_info(skill_id)
    skill = {"id": skill_id, "type": skill_type, "kind": profile["kind"], "energy": info.get("energy")}
    from .live_power import source_power, choice_damage_parameters
    source_powers, intrinsic_factors = source_power(attacker, defender, skill_id, profile)
    if '_simulation_actor' not in attacker:
        from .user_skill_extensions import native_per_type_power_bounds
        bonuses = native_per_type_power_bounds(attacker)
        source_powers = sorted({power + bonus for power in source_powers for bonus in bonuses})
    choice_params = choice_damage_parameters(attacker, defender, skill_id, profile)
    choice_factors = sorted({factor for p in (choice_params or []) for factor in p['preview_power_factors']}) or [1]
    if profile.get("damageRule") == 38:
        from .power_rule_runtime import _data, rule_power
        spec = _data()["skills"].get(str(skill_id))
        if spec is None:
            raise ValueError("该属性差威力技能尚无已审配置")
        stat = spec["stat"]
        key = next(key for key, short in STAT_DIM.items() if short == stat)
        attack_values, _ = panel_candidates(attacker, key, defender)
        defense_values, _ = panel_candidates(defender, key, attacker)
        source_powers = sorted({rule_power({stat: a}, {stat: d}, skill_id, profile["power"])
                                for a in attack_values for d in defense_values})
    skip = _represented_trait_buffs(owner, attacker, ["powerPercent", "flatPowerBonus"])
    skip |= {str(e["source_buff_id"]) for e in weather_runtime.modifiers(weather, "before_damage", skill_id, skill_type, owner) if "source_buff_id" in e}
    mark_buff_ids = {str(b.get("id")) for b in captured_buffs(attacker) if _mark_specs({"battleBuffs": [b]})}
    flat, percent, outgoing = 0, 0, [0, 0]
    matchup = profile["multiplier"]
    if skill_type != profile.get("skillType"):
        ratio = rules.type_multiplier(skill_type, other["form_id"])["multiplier"]
        matchup = ratio["numerator"] / ratio["denominator"]
        if profile.get("ignoreResistance") and 0 < matchup < 1:
            matchup = 1
    for buff in captured_buffs(attacker):
        bid = str(buff.get("id"))
        if bid not in skip | mark_buff_ids:
            f, p, d = _damage_buff_terms(buff, attacker, skill, matchup)
            flat += f
            percent += p
            outgoing = [a + b for a, b in zip(outgoing, d)]
    powers = []
    from itertools import product
    for source_power, choice_factor in product(source_powers, [1] if '_simulation_actor' in attacker else choice_factors):
        if "_simulation_actor" in attacker:
            from . import skill_history_runtime
            source_power = skill_history_runtime.modify_power(source_power,
                attacker.get("_execution_context", {}).get("skill_history_power"))
            from .user_skill_extensions import bound_skill_power
            source_power = bound_skill_power(owner, skill_id,
                attacker.get("_execution_context", {}).get("selected_skill_slot"), source_power)
        power = (source_power + flat) * (1 + percent / 100)
        if "_simulation_actor" in attacker:
            from . import pressure_runtime, adjacent_power_aura_runtime, mechanism_runtime
            execution = attacker.get("_execution_context", {})
            params = attacker.get("_execution_params", {})
            power = pressure_runtime.modify_power(owner, power)
            power = adjacent_power_aura_runtime.modify_power(owner, power, execution.get("selected_skill_slot"))
            if "choice_power_factor" in params:
                from .choice_runtime import current_power_factor
                power *= current_power_factor(execution["weather_skill_id"], params, execution)
            power = mechanism_runtime.modify_power(owner, power, skill=skill)
        power = weather_runtime.modify_power(weather, skill_type, power * choice_factor, skill_id, owner)
        for first in ([attacker["_resolved_first_attack"]]
                      if type(attacker.get("_resolved_first_attack")) is bool else (False, True)):
            actions = owner.get("mark_entry_actions")
            for value in _trait_powers(owner, other, attacker, defender, skill, power, first):
                if "_simulation_actor" in attacker:
                    raw = attacker.get("_execution_context", {}).get("core_magic_power_multiplier", {"numerator": 1, "denominator": 1})
                    if (not isinstance(raw, dict) or set(raw) != {"numerator", "denominator"}
                            or type(raw["numerator"]) is not int or type(raw["denominator"]) is not int
                            or raw["denominator"] <= 0 or Fraction(**raw) not in (Fraction(1), Fraction(5, 2))):
                        raise ValueError("Unsupported core magic power multiplier")
                    value *= Fraction(**raw)
                for first_action in ([attacker["_resolved_first_action"]]
                                     if type(attacker.get("_resolved_first_action")) is bool
                                     else [actions == 0] if isinstance(actions, int) else [False, True]):
                    powers.append(float(mark_runtime.modify_power(owner, value, profile["kind"], first_attack=first, first_action=first_action)))
    own_types = _pet_types(attacker)
    carried_types = [t for t in other["trait_current_skill_types"] if t]
    alternatives = [carried_types] if "trait_initial_skill_types" in other else [carried_types, [*carried_types, skill_type]]
    trait_factors = [float(trait_runtime.damage_multiplier(other, owner, skill,
        carried_types=types, attacker_types=own_types)) for types in alternatives]
    skip_taken = _represented_trait_buffs(other, defender, ["damageTakenPercent"])
    taken = [0, 0]
    for buff in captured_buffs(defender):
        if str(buff.get("id")) not in skip_taken:
            _, _, d = _damage_buff_terms(buff, defender, skill, matchup, incoming=True)
            taken = [a + b for a, b in zip(taken, d)]
    result = {**profile, "powerRange": [min(powers), max(powers)],
              "finalMultiplierRange": [min(intrinsic_factors) * min(trait_factors) * max(0, 1 + taken[0] / 100) * max(0, 1 + outgoing[0] / 100),
                                       max(intrinsic_factors) * max(trait_factors) * max(0, 1 + taken[1] / 100) * max(0, 1 + outgoing[1] / 100)],
              "effects": {"state_flat_power": flat, "state_power_percent": percent, "trait_damage_factor": [min(trait_factors), max(trait_factors)],
                          "received_damage_percent": taken, "outgoing_damage_percent": outgoing, "weather": weather.get("name") if weather else None,
                          "attacker_trait": (trait_runtime._rows().get(owner.get("trait_id")) or {}).get("name"),
                          "defender_trait": (trait_runtime._rows().get(other.get("trait_id")) or {}).get("name"),
                          "power_range": [min(powers), max(powers)],
                          "intrinsic_power_range": [min(source_powers), max(source_powers)],
                          "intrinsic_damage_factors": intrinsic_factors}}
    from .live_damage import _rules
    result["effects"]["unreviewed_trait_ids"] = [m["trait_id"] for m in (owner, other) if m.get("trait_id")
        and m["trait_id"] not in trait_runtime._rows()
        and not (m["trait_id"] in action_traits.ROWS and action_traits.source_evidence(_rules()[1], m))
        and not forced_trait_runtime.source_evidence(_rules()[1], m)
        and str(m["trait_id"]) not in weather_runtime.rules().get("trait_modifiers", {})]
    from .live_power import specification
    power_spec = specification(skill_id) or {}
    if profile.get('damageRule') == 38:
        from .power_rule_runtime import stat_difference_candidate
        candidate = stat_difference_candidate()
        result['effects'].update(intrinsic_power_source=candidate['policy'],
            intrinsic_power_uncertainty='第三方30点档位候选，尚未完成实战校准；' + candidate['uncertainty'])
    if power_spec.get("source_policy"):
        result["effects"].update(intrinsic_power_source=power_spec["source_policy"],
                                  intrinsic_power_uncertainty=power_spec.get("uncertainty"))
    if any("trait_calendar_binding" in m for m in (owner, other)):
        result["effects"]["calendar_source"] = "本机北京时间（服务端日期边界未另行校准）"
    if skill_type and skill_type != profile.get("skillType"):
        matchup = rules.type_multiplier(skill_type, other["form_id"])["multiplier"]
        multiplier = matchup["numerator"] / matchup["denominator"]
        if profile.get("ignoreResistance") and 0 < multiplier < 1:
            multiplier = 1
        result.update(skillType=skill_type, multiplier=multiplier, stab=1.25 if skill_type in own_types else 1)
        result["combined"] = result["multiplier"] * result["stab"]
    return result


def _star_profile(attacker, defender, profile):
    """Fixed source power; share panel and final damage modifiers with skill math."""
    owner, other = actor(attacker), actor(defender)
    power = profile.get("power")
    if (profile.get("sourcePolicy") != "user_confirmed_star_power_20_once_per_skill_20261030"
            or type(power) is not int or power < 20 or power % 20):
        raise ValueError("Star damage requires source-bound 20-power layers")
    skill = {"id": 0, "kind": profile["kind"], "type": "幻系", "energy": 0}
    taken, outgoing = [0, 0], [0, 0]
    skip_taken = _represented_trait_buffs(other, defender, ["damageTakenPercent"])
    for pet, target, incoming in ((attacker, outgoing, False), (defender, taken, True)):
        for buff in captured_buffs(pet):
            if incoming and str(buff.get("id")) in skip_taken:
                continue
            _, _, terms = _damage_buff_terms(buff, pet, skill, profile["multiplier"], incoming=incoming)
            target[:] = [a + b for a, b in zip(target, terms)]
    from .live_damage import _pet_types
    carried = [t for t in other.get("trait_current_skill_types", []) if t]
    alternatives = [carried] if "trait_initial_skill_types" in other else [carried, [*carried, "幻系"]]
    factors = [float(trait_runtime.damage_multiplier(other, owner, skill,
        carried_types=types, attacker_types=_pet_types(attacker))) for types in alternatives]
    multipliers = [factor * max(0, 1 + a / 100) * max(0, 1 + b / 100)
                   for factor, a, b in ((min(factors), taken[0], outgoing[0]),
                                        (max(factors), taken[1], outgoing[1]))]
    return {**profile, "powerRange": [power, power],
        "finalMultiplierRange": multipliers,
        "effects": {"mark_id": 1035, "power_per_stack": 20,
                    "received_damage_percent": taken, "outgoing_damage_percent": outgoing,
                    "trait_damage_factor": [min(factors), max(factors)], "source_policy": profile["sourcePolicy"]}}


def star_damage_profile(attacker, defender, stacks, *, kind):
    from .live_damage import _rules, _effective_base, _pet_types
    if type(stacks) is not int or stacks < 1:
        raise ValueError("Star damage requires positive integer layers")
    if kind not in ("physical", "magical"):
        raise ValueError("星陨伤害的攻击属性归属尚未确认，不能擅自按物伤或魔伤计算")
    _, rules = _rules()
    ratio = rules.type_multiplier("幻系", _effective_base(defender))["multiplier"]
    multiplier = ratio["numerator"] / ratio["denominator"]
    stab = 1.25 if "幻系" in _pet_types(attacker) else 1
    return {"skillId": 0, "markId": 1035, "kind": kind, "skillType": "幻系",
        "power": 20 * stacks, "hits": 1, "multiplier": multiplier, "stab": stab,
        "combined": multiplier * stab,
        "sourcePolicy": "user_confirmed_star_power_20_once_per_skill_20261030"}


def snow_bear_trait_damage(attacker, defender):
    """Preview 月牙雪糕's combined star explosion without altering captured BUFFs."""
    from .live_damage import _damage_case, _effective_base, _rules
    if _effective_base(attacker) != 3457:
        return None
    if attacker.get("effectiveTraitId", 200205) not in (None, 200205):
        return None
    row = {"traitId": 200205, "name": "月牙雪糕", "freezeLayers": None,
           "trigger": "攻击前每层冻结增加1层星陨；非幻系攻击后按对应攻防引爆一次"}
    try:
        from .ruleset import canonical_hash
        from .modifier_ledger import status_info
        from .live_power import _stacks
        catalog, rules = _rules()
        source = catalog["traits"]["200205"]
        digest = "98eba40027b33f1e168cc232a709620c6de8d4b43c969e76ce41bab5b804028c"
        if rules.form(3457).get("trait_id") != 200205 or canonical_hash(source) != digest:
            raise ValueError("月牙雪糕来源已变化，需重新核对")
        freeze = _raw_buffs()[str(status_info("freeze")["buff_id"])]
        ids = [int(bid) for bid, buff in _raw_buffs().items()
               if buff.get("buff_base_ids") == freeze["buff_base_ids"]]
        layers = sum(_stacks(defender, {"id": bid}) for bid in ids)
        if not layers:
            return None
        existing = _mark_specs(defender).get("1035", (0, None))[0]
        total = min(existing + layers, _mark_config()["1035"]["cap"])
        kinds = set()
        for move in attacker.get("moves") or []:
            info = battle_data.skill_info(move.get("skillId"))
            if info.get("kind") in ("physical", "magical") and info.get("type_code") != 20:
                kinds.add(info["kind"])
            elif info.get("kind") == "higher" and info.get("type_code") != 20:
                kinds.update(("physical", "magical"))
        # Unobserved attacks remain conditional physical/magical branches.
        kinds = kinds or {"physical", "magical"}
        cases = {kind: _damage_case(attacker, defender,
                    star_damage_profile(attacker, defender, total, kind=kind), kind)
                 for kind in ("physical", "magical") if kind in kinds}
        row.update(freezeLayers=layers, existingStarLayers=existing,
                   addedStarLayers=total - existing, totalStarLayers=total,
                   power=20 * total, damageByKind=cases,
                   damageMin=min(c["minimum"] for c in cases.values()),
                   damageMax=max(c["maximum"] for c in cases.values()),
                   snapshotId=catalog["snapshot_id"], traitRecordHash=digest,
                   source=source["source_url"])
        row["trigger"] += f"；星陨合计{total}层（原有{existing}＋特性新增{total - existing}），不随连击重复"
    except ValueError as error:
        row["reason"] = str(error)
    return row


def mark_damage(pet, opponent):
    """Separate once-per-action mark damage using the same HUD damage formula."""
    rows = []
    for mid, (layers, spec) in _mark_specs(pet).items():
        mid = spec['mark_id']
        start = len(rows)
        for effect in spec["effects"]:
            if effect["op"] == "star_consume_damage":
                row = {"markId": int(mid), "name": spec["buff_raw"]["name"], "layers": layers,
                    "trigger": "受到非幻系攻击时引爆一次", "perLayerPower": effect["power_per_stack"],
                    "power": effect["power_per_stack"] * layers, "damage": None,
                    "phase": effect["phase"], "source": "reviewed-mark-components-1"}
                try:
                    if (effect.get("damage_owner") != "triggering_attacker"
                            or effect.get("damage_kind") != "triggering_skill_kind"):
                        raise ValueError("星陨伤害的攻防归属尚未确认")
                    from .live_damage import _damage_case
                    cases = {kind: _damage_case(opponent, pet,
                                star_damage_profile(opponent, pet, layers, kind=kind), kind)
                             for kind in ("physical", "magical")}
                    low = min(case["minimum"] for case in cases.values())
                    high = max(case["maximum"] for case in cases.values())
                    row.update(damageMin=low, damageMax=high, damageByKind=cases,
                               damageText=str(low) if low == high else f"{low}～{high}",
                               attackKindPolicy="按引爆技能的物伤/魔伤分支")
                    if low == high:
                        row["damage"] = low
                except ValueError as exc:
                    row["reason"] = str(exc)
                rows.append(row)
            elif effect["op"] in ("damage_ratio", "hp_loss_ratio"):
                maximum = pet.get("maxHp")
                amount = math.floor(maximum * layers * Fraction(*effect["rate"])) if isinstance(maximum, (int, float)) else None
                rows.append({"markId": int(mid), "name": spec["buff_raw"]["name"], "layers": layers,
                    "trigger": "本回合末" if effect["phase"] == "round_end" else "换人时", "damage": amount,
                    "phase": effect["phase"], "rate": effect["rate"], "source": "reviewed-mark-components-1"})
        for row in rows[start:]:
            row.update(buffId=spec['buff_id'], independent=spec['independent'])
            if spec['independent']:
                row['name'] += '（独立）'
    return rows


def wish_move(pet):
    # PetUtils.GetSkillDamTypeByPetBloodType uses these named bloodlines, not dex numbers.
    from .team_code import BLOODLINES
    if "coreMagicSkillId" in pet and pet["coreMagicSkillId"] != 7010020:
        return None
    blood = pet.get("bloodId")
    if blood not in range(1, 19):
        return None
    code = battle_data.TYPE_CODES.get(BLOODLINES[blood])
    move = deepcopy(battle_data.will_impact_skill(code)) if code else None
    if move:
        move.update(slot=5, skillName="愿力冲击（" + BLOODLINES[blood] + "）", name="愿力冲击（" + BLOODLINES[blood] + "）", from_feature=False,
                    previewOnly=True, magicId=104002, note="愿力强化选择预览；本回合替换首槽，不额外执行一次攻击")
    return move
