"""Live damage constraints -> factorized nature / exactly-three-talent candidates."""
from functools import lru_cache
from copy import deepcopy
import json
from pathlib import Path

from .damage_inference import DIMS, _nature_directions, _selection_cases
from .numeric_candidates import arena_documented_damage60
from .live_stat_model import WORLD_SOURCE, WORLD_SOURCE_SHA256, is_world, star_candidates, stat_candidates, npc_profile, damage_value

STAT_KEYS = {"hp": "hp", "patk": "phyAtk", "matk": "magAtk", "pdef": "phyDef", "mdef": "magDef", "spd": "spd"}


@lru_cache(maxsize=1)
def _buffs():
    return json.loads((Path(__file__).resolve().parents[1] / "data/external/roco_buff_calc_map.json").read_text(encoding="utf-8"))


def _modifier(pet, dim):
    from .buff_preview import CALC_FIELDS
    from .live_modifiers import calc_buff, _buff_layers
    percent, unknown = 0, []
    for buff in pet.buffs:
        data = calc_buff(buff.get("id"))
        if not data:
            unknown.append(buff.get("id"))
        else:
            field = CALC_FIELDS.get(dim)
            if field in data:
                percent += data[field] * _buff_layers(buff)
    return 1 + percent / 100, percent, unknown


def damage_observation(caster, target, skill_id, damage, critical, turn, resolved_kind=None, context=None):
    from . import live_damage, live_modifiers, battle_data
    enemy = target if caster.side == 0 else caster
    ally = caster if caster.side == 0 else target
    role = "defender" if caster.side == 0 else "attacker"
    form = lambda pet: (pet.lowered_form() or {}).get("base_conf_id") or pet.base_conf_id
    event = {"turn": turn, "skill_id": skill_id, "damage": damage, "role": role, "form_id": form(enemy),
             "critical": critical, "ally_pet_id": ally.pet_id, "unmodeled_buffs": []}
    profile = live_damage.skill_math(skill_id, form(caster), form(target))
    if profile.get("reason"):
        event["blocker"] = profile["reason"]
        return enemy.pet_id, event
    kind = profile["kind"]
    payloads = context or {"attacker": caster.to_payload(hide_unobserved=caster.side == 1, observed={}),
                           "defender": target.to_payload(hide_unobserved=target.side == 1, observed={})}
    attacker, defender = deepcopy(payloads["attacker"]), deepcopy(payloads["defender"])
    for pet in (attacker, defender):
        pet.setdefault("liveContext", {"turn": turn})
    try:
        live_modifiers.validate_damage_support(attacker, defender, skill_id, profile)
    except ValueError as error:
        event["blocker"] = str(error)
        return enemy.pet_id, event
    if kind == "higher":
        patk, _ = live_modifiers.panel_candidates(attacker, "phyAtk", defender)
        matk, _ = live_modifiers.panel_candidates(attacker, "magAtk", defender)
        if min(patk) >= max(matk):
            kind = "physical"
        elif min(matk) > max(patk):
            kind = "magical"
        else:
            event["blocker"] = "高攻技能的物魔结算分支未确定"
            return enemy.pet_id, event
    # damage_info.dam_type is an elemental type (5=water, 9=ice), not physical/magical.
    event["observed_type_code"] = resolved_kind
    attack, defense = ("patk", "pdef") if kind == "physical" else ("matk", "mdef")
    dim, fixed = (defense, attack) if role == "defender" else (attack, defense)
    ally_payload, enemy_payload = (attacker, defender) if caster.side == 0 else (defender, attacker)
    fixed_values, fixed_source = live_modifiers.panel_candidates(ally_payload, STAT_KEYS[fixed], enemy_payload)
    factor, percent, event["unmodeled_buffs"] = _modifier(enemy, dim)
    info = battle_data.skill_info(skill_id) or battle_data.skill_info(skill_id // 100)
    profile.update(skillId=info.get("skill_id", skill_id), kind=kind)
    selected = [m.get("slot") for m in attacker.get("moves", []) if not m.get("observedOnly")
                and battle_data.canonical_skill(m.get("skillId")).get("skill_id") ==
                battle_data.canonical_skill(profile["skillId"]).get("skill_id")]
    profile["selectedSlot"] = selected[0] if len(selected) == 1 else None
    if critical:
        profile["combined"] *= 2
    event.update(dimension=dim, fixed_values=fixed_values, fixed_source=fixed_source,
                 attacker_level=attacker.get("level"), battle_mode=attacker.get("battleMode"),
                 power=profile["power"], combined=profile["combined"], stat_factor=factor, modifier_percent=percent,
                 calculation={"attacker": attacker, "defender": defender, "profile": profile},
                 policy="shared_live_forward_query_v2")
    if event["stat_factor"] <= 0:
        event["blocker"] = "属性倍率非正，缺少低值边界结算依据"
    return enemy.pet_id, event


def _predicted_range(event, panel):
    calculation = event.get("calculation")
    if calculation:
        from .live_damage import _damage_case
        attacker, defender = deepcopy(calculation["attacker"]), deepcopy(calculation["defender"])
        unknown = attacker if event["role"] == "attacker" else defender
        unknown.pop("configurationInference", None)
        unknown["battleStats"] = {**unknown.get("battleStats", {}), STAT_KEYS[event["dimension"]]: panel}
        unknown["battleStatsBasis"] = "natured_base"
        profile = calculation["profile"]
        case = _damage_case(attacker, defender, profile, profile["kind"])
        return case["minimum"], case["maximum"]
    current = panel * event["stat_factor"]
    values = [damage_value({"level": event.get("attacker_level", 60), "battleMode": event.get("battle_mode", "pvp")},
              fixed if event["role"] == "defender" else current,
              current if event["role"] == "defender" else fixed, event["power"], event["combined"])
              for fixed in event["fixed_values"]]
    return min(values), max(values)


def _protocol_selection(pet):
    evidence = pet.get("talentEvidence") or {}
    ids = evidence.get("selected_ids")
    if not isinstance(ids, list) or len(ids) != 3 or len(set(ids)) != 3 or any(type(i) is not int or not 1 <= i <= 6 for i in ids):
        return None
    values = {}
    for index in ids:
        dim = DIMS[index - 1]
        row = evidence.get("dimensions", {}).get(STAT_KEYS[dim], {})
        value = row.get("talent_add_value")
        if type(value) is not int or not 0 <= value <= 10:
            return None
        raw = row.get("talent")
        if raw is not None and (type(raw) is not int or raw < 0):
            raise ValueError(f"协议{dim}原始资质字段无效")
        if not is_world(pet) and raw is not None and raw != value * 6:
            raise ValueError(f"协议{dim}个体值与原始资质字段冲突")
        values[dim] = value
    return {"selected": list(values), "values": values}


def infer_configuration(pet, evidence):
    from . import live_damage
    form_id = live_damage._effective_base(pet)
    relevant = [dict(e) for e in evidence if str(e.get("form_id")) == str(form_id)]
    accepted = [e for e in relevant if not e.get("blocker")]
    result = {"status": "unresolved", "calibrated": False, "probability_available": False,
              "observations": [{k:v for k,v in e.items() if k != "calculation"} for e in relevant],
              "used_observations": len(accepted), "groups": [], "combination_count": 0,
              "panel_ranges": {}, "talent_value_options": {}, "determined": {},
              "issues": list(dict.fromkeys(e["blocker"] for e in relevant if e.get("blocker"))),
              "notice": "先匹配下发面板，再用受击前的状态、特性和天气通过同一正算查询筛选；未知条件保留区间，未全量实战校准。"}
    try:
        protocol = _protocol_selection(pet)
    except ValueError as error:
        protocol = None
        result["issues"].append(str(error))
    result["protocol_selection"] = protocol
    world = is_world(pet)
    if (not world and pet.get("level") != 60) or (world and (type(pet.get("level")) is not int or pet["level"] < 1)):
        result["issues"].append("当前配置反推缺少有效等级；PVP仅支持60级，大世界使用独立候选")
        return result
    try:
        stars_to_check = star_candidates(pet)
    except ValueError as error:
        result["issues"].append(str(error))
        return result
    race, source = live_damage._race_stats(form_id)
    result["source"] = source
    if not world and any(not race.get(dim) for dim in DIMS):
        result["issues"].append("缺少当前形态的完整六维种族值")
        return result
    catalog, _ = live_damage._rules()
    result["snapshot_id"] = catalog.get("snapshot_id")
    result["candidate_id"] = "captured_stat60_precision_bounds_v1+shared_live_forward_query_v2"
    if world:
        result["candidate_id"] = "captured_world_zero_star_or_protocol_panels_v1+shared_live_forward_query_v2"
        result["stat_source"] = WORLD_SOURCE
        result["stat_source_sha256"] = WORLD_SOURCE_SHA256
        if any(stars > 0 for stars in stars_to_check):
            result["issues"].append("大世界正星资质换算与成长系数未普遍核实；仅使用下发原始资质/基础面板，性格沿用已知倍率上限。")
    result["modifier_source"] = "lab/live_modifiers.py; source-bound trait/weather/BUFFBASE queries"
    nature_id = pet.get("nature")
    known = next((n for n in catalog["natures"] if str(n["id"]) == str(nature_id)), None)
    if not known and nature_id not in (None, 0, "0"):
        result["issues"].append(f"报文性格编号{nature_id}未匹配当前快照，保留所有相容方向")
    natures = [known] if known else catalog["natures"]
    result["nature_source"] = "protocol" if known else "damage_model"
    member = {"nature_modifiers": {"up_id": pet.get("naturePosOverride") or 0, "down_id": pet.get("natureNegOverride") or 0}}
    if pet.get("talent_selection"):
        member["talent_selection"] = pet["talent_selection"]
    if protocol:
        member["talent_selection"] = protocol
    npc = None
    if world and pet.get("worldNpc"):
        try:
            npc = npc_profile(pet)
        except (OSError, ValueError) as error:
            result["issues"].append(str(error))
            return result
        member["talent_selection"] = {"selected": npc[0]["historical_selected_dimensions"]}
        result["candidate_id"] = "historical_world_npc_growth_attacker_level_v1"
        result["npc_configuration_candidate"] = {"conf_id": pet.get("confId"), "growth": npc[1],
            "selected": npc[0]["historical_selected_dimensions"], "online_verified": False}
        result["issues"].append("NPC成长和三项采用原包历史配置候选；与已观测伤害一致不代表完整资质与当前服务器规则已确认。")
    unknown_override = any(value is False for value in (pet.get("natureOverrideKnown") or {}).values())
    if unknown_override:
        result["nature_source"] = "protocol_original_effective_directions_unconfirmed"
        result["original_nature_id"] = nature_id
        result["issues"].append("性格改写方向未下发，保留原始性格，当前增减方向待核实。")
        direction_candidates = [(known or {"id": None, "name": {"zh": None}}, pair)
                                for pair in live_damage._nature_pairs(pet)]
    else:
        direction_candidates = [(nature, _nature_directions(member, nature)) for nature in natures]
    observed = {dim: pet.get("revealedBaseStats", {}).get(key) for dim, key in STAT_KEYS.items()}
    observed.update({dim:value for dim,key in STAT_KEYS.items()
                     if isinstance(value := pet.get("battleStats", {}).get(key), (int,float)) and value > 0})
    observed = {d: v for d, v in observed.items() if isinstance(v, (int, float)) and v > 0}
    if pet.get("maxHp", 0):
        observed.setdefault("hp", pet["maxHp"])
    result["used_panels"] = len(observed)
    if not observed and not accepted and not protocol:
        return result
    predicted = {}
    values_by_direction = {}
    blocked_stars, stat_issues = set(), set()
    def prediction(event, panel):
        key = (id(event), panel)
        if key not in predicted:
            try:
                predicted[key] = _predicted_range(event, panel)
            except (ValueError, KeyError, TypeError) as error:
                event["blocker"] = str(error)
                predicted[key] = None
        return predicted[key]

    def collect(use_damage, events=None):
        groups, panels, talents = [], {d: set() for d in DIMS}, {d: set() for d in DIMS}
        diagnostics = {d: set() for d in DIMS}
        for stars, nature, directions in ((s, n, dirs) for s in stars_to_check for n, dirs in direction_candidates):
            if not directions:
                continue
            up, down = directions
            if not unknown_override and (pet.get("natureUp") and pet["natureUp"] != up or pet.get("natureDown") and pet["natureDown"] != down):
                continue
            cache_key = (stars, up, down)
            if cache_key not in values_by_direction:
                values_by_direction[cache_key] = {d: {} for d in DIMS}
                for dim in DIMS:
                    for talent in range(11):
                        try:
                            values_by_direction[cache_key][dim][talent] = stat_candidates(
                                pet, race, dim, talent, up, down, stars)
                        except ValueError as error:
                            values_by_direction[cache_key][dim][talent] = []
                            blocked_stars.add(stars)
                            stat_issues.add(str(error))
            values = values_by_direction[cache_key]
            options = {}
            eligible = {d: {} for d in DIMS}
            for dim in DIMS:
                options[dim] = []
                domain = [protocol["values"].get(dim, 0)] if protocol else range(11)
                for talent in domain:
                    diagnostics[dim].update(values[dim][talent])
                    matching_panels = []
                    for panel in values[dim][talent]:
                        if dim in observed and panel != observed[dim]:
                            continue
                        fits = True
                        for event in (accepted if events is None else events) if use_damage else []:
                            if event["dimension"] != dim or event.get("blocker"):
                                continue
                            bounds = prediction(event, panel)
                            if bounds and not bounds[0] <= event["damage"] <= bounds[1]:
                                fits = False
                                break
                        if fits:
                            matching_panels.append(panel)
                    if protocol and not world and not matching_panels:
                        matching_panels = [observed[dim]] if dim in observed else values[dim][talent]
                    if matching_panels:
                        options[dim].append(talent)
                        eligible[dim][talent] = matching_panels
            cases = _selection_cases(member, options)
            if not cases:
                continue
            count = sum(c["combination_count"] for c in cases)
            groups.append({"nature_id": nature["id"], "nature_name": None if unknown_override else nature["name"]["zh"],
                           "directions": {"up": up, "down": down}, "selection_cases": cases, "combination_count": count})
            if world:
                groups[-1]["stars"] = stars
            for case in cases:
                for dim in DIMS:
                    domain = case["value_options"].get(dim, [0])
                    talents[dim].update(domain)
                    panels[dim].update(panel for v in domain for panel in eligible[dim][v])
        return groups, panels, talents, diagnostics

    groups, panels, talents, diagnostics = collect(not protocol)
    kept_events = [e for e in accepted if not e.get("blocker")]
    result["status"] = ("protocol" if protocol else "conditional") if groups else "model_mismatch"
    if not groups and accepted and not protocol:
        baseline = collect(False)
        if baseline[0]:
            retained, conflicts = [], []
            current = baseline
            # An unexplained newer hit must not erase earlier compatible evidence.
            for event in accepted:
                if event.get("blocker"):
                    continue
                trial = collect(True, [*retained, event])
                if trial[0]:
                    retained.append(event)
                    current = trial
                else:
                    conflicts.append(event)
            groups, panels, talents, diagnostics = current
            kept_events = retained
            result["status"] = "damage_conflict"
            result["issues"].append(f"新伤害与已有约束冲突：保留{len(retained)}条一致伤害和已知面板的结果，冲突观测未应用，未覆盖实际配置。")
            result["damage_conflicts"] = []
            for event in conflicts:
                bounds = [prediction(event, value) for value in panels[event["dimension"]]]
                bounds = [b for b in bounds if b]
                result["damage_conflicts"].append({"turn": event["turn"], "skill_id": event["skill_id"], "damage": event["damage"],
                    "predicted_range": [min(b[0] for b in bounds), max(b[1] for b in bounds)] if bounds else None})
    result["groups"] = groups
    result["combination_count"] = sum(g["combination_count"] for g in groups)
    result["used_observations"] = len(kept_events) if not protocol and result["status"] in ("conditional", "damage_conflict") else 0
    result["issues"].extend(e["blocker"] for e in accepted if e.get("blocker") and e["blocker"] not in result["issues"])
    result["panel_fit"] = [{"dimension": d, "observed": v, "predicted_values": sorted(diagnostics[d]),
                            "matches": v in diagnostics[d]} for d, v in observed.items()]
    if not groups:
        result["issues"].append("下发面板与当前形态、性格和恰好三项资质的公式不匹配；查看逐维实测/预测值，不归因于用户加点错误。")
    if protocol:
        result["notice"] = "三项加点和数值由协议直接下发；性格来源与面板公式核对分别列出，不把协议事实称为伤害推断。"
        for row in result["panel_fit"]:
            if not row["matches"]:
                result["issues"].append(f"{row['dimension']}下发{row['observed']}，模型预测{row['predicted_values']}，保留下发值与原始资质。")
    for dim, rows in panels.items():
        if rows:
            result["panel_ranges"][STAT_KEYS[dim]] = [min(rows), max(rows)]
            result["talent_value_options"][dim] = sorted(talents[dim])
            if len(rows) == 1:
                result["determined"][STAT_KEYS[dim]] = min(rows)
    result["observations"] = [{k:v for k,v in e.items() if k != "calculation"} for e in relevant]
    cases = [case for group in groups for case in group["selection_cases"]]
    result["known_talents"] = {d: {"selected": True, "values": sorted(talents[d]),
                                  "source": "protocol" if protocol else "model_consensus"}
                               for d in DIMS if cases and all(d in c["selected"] for c in cases)}
    if protocol:
        result["known_talents"] = {d: {"selected": True, "values": [v], "source": "protocol"}
                                   for d, v in protocol["values"].items()}
    elif npc:
        for row in result["known_talents"].values():
            row["source"] = "historical_npc_candidate"
    if groups:
        ups, downs = {g["directions"]["up"] for g in groups}, {g["directions"]["down"] for g in groups}
        result["known_nature"] = {"up": next(iter(ups)) if len(ups) == 1 else None,
                                  "down": next(iter(downs)) if len(downs) == 1 else None,
                                  "name": groups[0]["nature_name"] if len(groups) == 1 else None,
                                  "source": result["nature_source"]}
    if world:
        if protocol and result["status"] == "model_mismatch":
            # A changed live stat must not invalidate three directly downlinked talents.
            result["status"] = "protocol_model_mismatch"
        result["star_coverage"] = {"requested": stars_to_check,
                                   "evaluated": [s for s in stars_to_check if s not in blocked_stars],
                                   "blocked": sorted(blocked_stars)}
        result["issues"].extend(sorted(stat_issues))
        if blocked_stars:
            result["status"] = "unresolved"
            result["panel_ranges"] = {}
            result["determined"] = {}
            result["talent_value_options"] = {}
            if not protocol:
                result["known_talents"] = {}
            result.pop("known_nature", None)
            result["issues"].append("部分星级缺少可靠正算依据；现有分组仅为局部候选，不能作为完整星级范围或反推结论。")
    return result
