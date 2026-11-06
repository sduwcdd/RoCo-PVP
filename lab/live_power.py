"""Reviewed current-state power components, shared by live forecasts and inversion.

Natural language is retained as evidence in the offline configuration, never parsed
here. Response variants are scenarios, not an assumed opponent action or probability.
"""
from fractions import Fraction
from functools import lru_cache
import json
from pathlib import Path

from . import battle_data
from .ruleset import canonical_hash

CONFIG = Path(__file__).resolve().parents[1] / "data/rules/reviewed-live-power-1.json"


@lru_cache(maxsize=64)
def _choice_specification(sid, stamp):
    from .choice_runtime import rules as choice_rules
    from .live_damage import _rules
    data = choice_rules()
    row = data['skills'].get(str(sid))
    if row is None or not any(op['op'] in ('damage', 'damage.sequence')
                              for option in row['options'] for op in option):
        return None
    catalog, rules = _rules()
    if data['snapshot_id'] != catalog['snapshot_id'] or canonical_hash(rules.skill(sid)) != row['record_hash']:
        raise ValueError('选择技能的伤害来源已变化，需重新核对')
    return row


def choice_specification(sid):
    from .choice_runtime import CONFIG as choice_config
    sid = battle_data.canonical_skill(sid).get('skill_id', sid)
    return _choice_specification(sid, choice_config.stat().st_mtime_ns)


def choice_damage_parameters(attacker, defender, sid, profile):
    """Read the execution configuration; unknown public predicates retain alternatives."""
    row = choice_specification(sid)
    if row is None:
        return None
    execution = attacker.get('_execution_context', {})
    option = execution.get('choice_option') if '_simulation_actor' in attacker else profile.get('choiceOption')
    if option is not None and (type(option) is not int or option not in (0, 1)):
        raise ValueError('选择伤害需要选项0或1')
    if '_simulation_actor' in attacker and option is None:
        raise ValueError('执行选择伤害缺少已提交的选项')
    response = execution.get('response_success') if '_simulation_actor' in attacker else profile.get('choiceResponse')
    slot = execution.get('selected_skill_slot') if '_simulation_actor' in attacker else profile.get('selectedSlot')
    if '_simulation_actor' not in attacker and slot is not None:
        slot -= 1
    from .rule_expressions import evaluate_condition
    state = {target: {key: pet.get(field) for key, field in
                     (('hp', 'currentHp'), ('max_hp', 'maxHp'), ('energy', 'energy'))
                     if type(pet.get(field)) is int}
             for target, pet in (('self', attacker), ('opponent', defender))}
    candidates = []
    for index in ((option,) if option is not None else (0, 1)):
        for operation in row['options'][index]:
            if operation['op'] not in ('damage', 'damage.sequence'):
                continue
            if 'when_response' in operation and type(response) is bool and response != operation['when_response']:
                continue
            if 'when' in operation:
                try:
                    if not evaluate_condition(operation['when'], state):
                        continue
                except ValueError:
                    pass  # Missing public HP keeps both source-defined alternatives.
            if 'when_carried_type' in operation:
                condition = operation['when_carried_type']
                pet = attacker if condition['target'] == 'self' else defender
                carried = pet.get('carriedSkillIds')
                if isinstance(carried, list) and len(carried) == 4:
                    present = any(battle_data.canonical_skill(mid).get('skill_id', mid)
                                  in row['carried_type_ids'][condition['type']] for mid in carried)
                    if present != condition['present']:
                        continue
            params = dict(operation['params'])
            params['preview_power_factors'] = [1]
            if 'power_factor_on_response' in operation:
                factor = operation['power_factor_on_response']
                params['preview_power_factors'] = [factor] if response is True else [1] if response is False else [1, factor]
            bonus = operation.get('power_if_slot')
            additions = [0]
            if bonus:
                additions = [bonus['amount']] if slot == bonus['slot'] else [0] if slot is not None else [0, bonus['amount']]
            candidates.extend({**params, 'power': params['power'] + add} for add in additions)
    if not candidates:
        raise ValueError('当前选择分支没有可确认的直接伤害')
    return candidates


@lru_cache(maxsize=2)
def _configuration(stamp):
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    if data.get("schema") != "reviewed-live-power-1":
        raise ValueError("实时威力配置格式不符")
    return data


@lru_cache(maxsize=256)
def _checked(sid, stamp):
    from .live_damage import _rules
    data = _configuration(stamp)
    alias = data.get("aliases", {}).get(str(sid))
    if alias:
        if canonical_hash(battle_data._skills().get(str(sid))) != alias["native_hash"]:
            raise ValueError(f"技能 {sid} 的实时威力别名来源已变化")
        sid = alias["skill_id"]
    row = data["skills"].get(str(sid))
    if row is None:
        return None
    catalog, rules = _rules()
    record_hash = None if row.get('native_only') else canonical_hash(rules.skill(sid))
    if (data["snapshot_id"] != catalog["snapshot_id"]
            or record_hash != row["record_hash"]
            or canonical_hash(battle_data._skills().get(str(sid))) != row["native_hash"]):
        raise ValueError(f"技能 {sid} 的实时威力来源已变化，需重新核对")
    response = row.get("response")
    if response and (canonical_hash(battle_data._skills().get(str(response["id"]))) != response["native_hash"]
                     or battle_data._response_bases().get(response["id"]) != {sid}):
        raise ValueError(f"技能 {sid} 的应对变体来源已变化")
    return row


def specification(sid):
    info = battle_data.canonical_skill(sid)
    row = _checked(info.get("skill_id", sid), CONFIG.stat().st_mtime_ns)
    if row and row.get("response", {}).get("id") == sid:
        return row["response"]
    return row


def response_variant(sid):
    row = _checked(sid, CONFIG.stat().st_mtime_ns)
    return (row or {}).get("response", {}).get("id")


def _hp_ratios(pet):
    hp, maximum = pet.get("currentHp"), pet.get("maxHp")
    if type(hp) in (int, float) and type(maximum) in (int, float) and maximum > 0 and 0 <= hp <= maximum:
        return [Fraction(str(hp)) / Fraction(str(maximum))]
    percent = pet.get("hpPercent")
    if type(percent) in (int, float) and 0 <= percent <= 100:
        # Display rounding is not calibrated; cover floor/round/ceil, never infer exact HP.
        return [Fraction(str(max(0, percent - 1))) / 100,
                Fraction(str(min(100, percent + 1))) / 100]
    raise ValueError("动态威力缺少当前生命或生命百分比")


def _energy(pet):
    value = pet.get("energy")
    if type(value) not in (int, float) or value < 0:
        raise ValueError("动态威力缺少当前能量")
    return value


def _missing_history(pet, kind):
    reason = pet.get('historyIncompleteReason') or '未取得完整开场及技能携带历史'
    observed = pet.get('responseSuccessCount')
    if kind == '应对' and type(observed) is int and observed >= 0:
        reason += f'；接入后该精灵已记录{observed}次应对成功，此前次数未知'
    return ValueError(f'{kind}历史不完整：{reason}，不能把缺失次数当作零')


def _stacks(pet, selector):
    from .live_modifiers import captured_buffs, _raw_buffs
    if "_simulation_actor" in pet:
        from .live_modifiers import canonical_buff_layers
        buffs = canonical_buff_layers(pet["_simulation_actor"])
    else:
        buffs = captured_buffs(pet)
    if "battleBuffs" not in pet and "buffs" not in pet:
        raise ValueError("动态威力缺少当前状态列表，不能视为零层")
    total = 0
    for buff in buffs:
        raw = _raw_buffs().get(str(buff.get("id")), {})
        matches = (selector.get("id") == buff.get("id") if "id" in selector else
                   selector["group"] in raw.get("buff_groupsigns", []) if "group" in selector else
                   selector.get("type") == raw.get("type"))
        if matches:
            layers = buff.get("layers")
            if type(layers) is not int or layers < 0:
                raise ValueError("动态威力的状态层数未知或无效")
            total += layers
    return total


def entry_burst_powers(attacker, sid, profile):
    """Shared HUD/execution query for reviewed first-entry-action power additions."""
    from . import mechanism_runtime as mechanisms
    from .live_damage import _rules
    config = mechanisms._configuration(mechanisms.CONFIG.stat().st_mtime_ns)
    row = next((row for row in config['skills'] if row['skill_id'] == sid), None)
    components = (row or {}).get('components', [])
    if (len(components) != 1 or components[0].get('op') != 'damage.power.add'
            or components[0].get('when') != 'entry.first_action'
            or components[0].get('target') != 'self'):
        return None
    record = _rules()[1].skill(sid)
    if (canonical_hash(record) != row['record_hash'] or row.get('raw') != record
            or profile['power'] != record['power'] or type(components[0].get('amount')) is not int):
        raise ValueError('HUD entry-burst mechanism source changed')
    program = {'game_id': sid, 'mechanism_components': components,
               'operations': mechanisms._operations(record, row)}
    if len(program['operations']) != 1 or program['operations'][0]['op'] != 'damage':
        raise ValueError('HUD entry-burst requires one reviewed direct damage operation')
    first = attacker.get('_resolved_first_action')
    if '_simulation_actor' in attacker and type(first) is not bool:
        raise ValueError('Entry-burst execution requires explicit owned first-action state')
    if type(first) is not bool:
        count = attacker.get('entryActionCount')
        if count is not None and (type(count) is not int or count < 0):
            raise ValueError('HUD entry action count must be a nonnegative integer')
        first = count == 0 if count is not None else None
    options = (first,) if type(first) is bool else (False, True)
    return sorted({mechanisms._base(program, {}, {'mark_first_action': flag})['operations'][0]['params']['power']
                   for flag in options})


def source_power(attacker, defender, sid, profile):
    """Return possible intrinsic powers and final damage factors without mutation."""
    spec = specification(sid)
    components = (spec or {}).get("components", [])
    rule = profile.get("damageRule")
    if rule == 35 and not components:
        raise ValueError("体重/体重差威力的单位及分档阈值尚未核对，不能按实验档宽估计")
    if rule not in (None, 0, 15, 38) and not components:
        raise ValueError(f"动态伤害规则 {rule} 缺少可核对的当前参数，不能按首项威力代算")
    powers, factors = entry_burst_powers(attacker, sid, profile) or [profile["power"]], [1]
    choices = choice_damage_parameters(attacker, defender, sid, profile)
    if choices is not None:
        from . import skill_history_runtime as history
        canonical = battle_data.canonical_skill(sid).get('skill_id', sid)
        if '_simulation_actor' not in attacker and history._data()['skills'].get(str(canonical), {}).get('components'):
            raise ValueError('该选择技能的累计威力或连击历史尚未完整接入，不能按初始值代算')
        if any(p['kind'] != profile['kind'] or p['type'] != profile['skillType'] for p in choices):
            raise ValueError('选择分支的伤害类型与当前技能不符')
        powers = sorted({p['power'] for p in choices})
    for component in components:
        op = component["op"]
        pet = attacker if component.get("target") == "self" else defender
        additions = [0]
        if op == "hp_steps":
            step = component["step_bp"]
            if type(step) is not int or step <= 0:
                raise ValueError("生命威力步长无效")
            additions = [int((1 - ratio) * 10000 // step) * component["add"] for ratio in _hp_ratios(pet)]
        elif op in ("entry_history", "carried_type_history", "response_history", "distinct_type_history"):
            from . import skill_history_runtime as history
            canonical = battle_data.canonical_skill(sid).get("skill_id", sid)
            row = history._data()["skills"].get(str(canonical), {})
            terms = row.get("components", [])
            trigger = {'entry_history': 'member.enter', 'carried_type_history': 'carried.other_type.use',
                       'response_history': 'carried.response.success',
                       'distinct_type_history': 'carried.distinct_other_type.use'}[op]
            if (row.get("record_hash") != spec["record_hash"] or len(terms) != 1
                    or terms[0].get("when") != trigger or terms[0].get("op") != "power.add"):
                raise ValueError("累计威力缺少一致的共享技能历史配置")
            if "_simulation_actor" in attacker:
                resolved = attacker.get("_execution_context", {}).get("skill_history_power")
                if not resolved or resolved.get("skill_id") != canonical:
                    raise ValueError("累计威力缺少当前原始槽位的完整来源历史")
                # The shared history replay applies this once in live_modifiers.
                continue
            if op == 'distinct_type_history':
                observed = attacker.get('skillTypeUseCounts', {})
                if not isinstance(observed, dict) or any(not isinstance(types, dict) for types in observed.values()):
                    raise ValueError('不同属性技能使用历史格式无效')
                allowed = {name + '系' for name in battle_data.TYPE_CODES} - {terms[0]['excluded_type']}
                seen = set()
                for types in observed.values():
                    for kind, n in types.items():
                        if type(n) is not int or n < 0 or kind not in allowed | {terms[0]['excluded_type']}:
                            raise ValueError('不同属性技能使用历史含未知属性或无效次数')
                        if n and kind in allowed:
                            seen.add(kind)
                carried = attacker.get('carriedSkillIds')
                complete = attacker.get('skillUseHistoryComplete') is True
                if carried is not None:
                    if (not isinstance(carried, list) or len(carried) != 4
                            or any(type(mid) is not int or mid < 0 for mid in carried)):
                        raise ValueError('当前真实携带技能必须保留四个有序槽位')
                    carried = [battle_data.canonical_skill(mid).get('skill_id', mid) if mid else 0 for mid in carried]
                    if canonical not in carried:
                        raise ValueError('累计威力技能不在已确认的原始携带槽位，需核对技能替换历史')
                if complete:
                    counts = [len(seen)] if carried is not None else [0, len(seen)]
                else:
                    if carried is None:
                        raise ValueError('缺少当前真实四槽配招，不能按全部属性猜测过曝上界')
                    from . import weather_runtime
                    carried_types = set()
                    for mid in carried:
                        if not mid:
                            continue
                        info = battle_data.canonical_skill(mid)
                        if info.get('skill_id') == canonical:
                            continue
                        skill_type = next((name + '系' for name, code in battle_data.TYPE_CODES.items()
                                           if code == info.get('type_code')), None)
                        skill_type = weather_runtime.resolved_skill_type(
                            attacker.get('liveContext', {}).get('weather'), info.get('skill_id', mid), skill_type)
                        if skill_type not in allowed | {terms[0]['excluded_type']}:
                            raise ValueError('当前携带技能属性未确认，不能可靠估计过曝上界')
                        if skill_type in allowed:
                            carried_types.add(skill_type)
                    if not seen.issubset(carried_types):
                        raise ValueError('已确认的本人属性历史超出当前配招，不能用当前配招覆盖真实累计')
                    counts = [len(seen), len(carried_types)]
                additions = [n * terms[0]['amount'] for n in counts]
            elif op == 'entry_history':
                count = attacker.get("entryCount")
                if attacker.get("entryHistoryComplete") is not True or type(count) is not int or count < 0:
                    raise _missing_history(attacker, '入场')
            elif op == 'response_history':
                count = attacker.get('responseSuccessCount')
                if attacker.get('responseHistoryComplete') is not True or type(count) is not int or count < 0:
                    raise _missing_history(attacker, '应对')
            else:
                observed = attacker.get('skillTypeUseCounts')
                if attacker.get('skillUseHistoryComplete') is not True or not isinstance(observed, dict):
                    raise _missing_history(attacker, '属性技能使用')
                if any(not isinstance(types, dict) for types in observed.values()):
                    raise ValueError('属性技能使用历史格式无效')
                counts = [types.get(terms[0]['type'], 0) for mid, types in observed.items()
                          if int(mid) != terms[0]['excluded_skill_id']]
                if any(type(n) is not int or n < 0 for n in counts):
                    raise ValueError('属性技能使用次数无效')
                count = sum(counts)
            if op != 'distinct_type_history':
                carried = attacker.get("carriedSkillIds")
                if carried is not None and canonical not in carried:
                    raise ValueError("累计威力技能不在已确认的原始携带槽位，需核对技能替换历史")
                # Enemy carried history is hidden; acquiring a skill after entry is possible.
                counts = [count] if carried is not None else [0, count]
                additions = [value * terms[0]["amount"] for value in counts]
        elif op == "per_use":
            if "_simulation_actor" in attacker:
                terms = attacker.get("_execution_context", {}).get("skill_history_power")
                if not terms or terms.get("skill_id") != battle_data.canonical_skill(sid).get("skill_id", sid):
                    raise ValueError("累计技能威力缺少当前原始槽位的完整来源历史")
                # Applied once below by the shared history replay, not a synthetic use count.
                continue
            if attacker.get("skillUseHistoryComplete") is not True:
                raise _missing_history(attacker, '累计技能使用')
            canonical = battle_data.canonical_skill(sid).get("skill_id", sid)
            count = attacker.get("skillUseCounts", {}).get(str(canonical), 0)
            if type(count) is not int or count < 0:
                raise ValueError("累计技能使用次数无效")
            if (attacker.get("carriedSkillIds") or []).count(canonical) > 1:
                raise ValueError("重复技能槽的累计威力历史不能唯一匹配")
            additions = [count * component["add"]]
        elif op == "hp_above":
            additions = [component["add"] if ratio * 100 > component["percent"] else 0 for ratio in _hp_ratios(pet)]
        elif op in ("per_stack", "if_buff"):
            count = _stacks(pet, component["selector"])
            additions = [component["add"] * (count if op == "per_stack" else int(count > 0))]
        elif op == "mixed_blood_damage":
            from .live_modifiers import actor
            from .trait_runtime import bloodline_relation
            current = actor(pet)
            declared = [current.get("bloodline_id"), current.get("bloodId"),
                        current.get("original_configuration", {}).get("bloodline_id")]
            if all(value in (None, 0) for value in declared):
                alternatives = [False, True]
            else:
                alternatives = [bloodline_relation(current)["mixed"]]
            factors = sorted({factor * (Fraction(*component["damage_factor"]) if active else 1)
                              for factor in factors for active in alternatives})
        elif op == "cute_gain_on_cast":
            gains = attacker.get("_execution_context", {}).get("cute_cast_gains")
            if gains is not None:
                if not isinstance(gains, dict) or type(gains.get("self")) is not bool:
                    raise ValueError("萌化增伤需要本次施放的明确获得结果")
                active = gains["self"]
            else:
                stage = battle_data.pet_stage_info(pet.get("petBaseId")).get("stage")
                trait = pet.get("effectiveTraitId", pet.get("_simulation_actor", {}).get("trait_id"))
                if type(stage) is not int:
                    raise ValueError("萌化条件增伤需要当前精灵的明确阶段")
                active = stage > 1 or trait == 200182
            additions = [component["add"] if active else 0]
        elif op == "per_energy":
            additions = [_energy(pet) * component["add"]]
        elif op == 'countered_power':
            values = profile.get('counteredPowers')
            if (not isinstance(values, list) or not values or
                    any(type(v) not in (int, float) or not 0 <= v < float('inf') for v in values)):
                raise ValueError('听桥需要已选择的被应对技能威力，不能按默认威力代算')
            powers = sorted(set(values))
        elif op == "energy_table":
            if "_simulation_actor" in attacker and "energyBeforeCast" not in pet:
                raise ValueError("能量档位需要扣费前 energy_before_cast，不能从付款后能量反推")
            energy = _energy({"energy": pet["energyBeforeCast"]}) if "energyBeforeCast" in pet else _energy(pet)
            if type(energy) is not int:
                raise ValueError("能量档位需要当前非负整数能量")
            if energy >= len(component["powers"]):
                if component.get("overflow") != "clamp_to_last_user_confirmed":
                    raise ValueError("当前能量超出已核对威力表且缺少溢出规则")
                energy = len(component["powers"]) - 1
            powers = [component["powers"][energy]]
        elif op == "if_energy":
            energy = _energy(pet)
            active = energy <= component["value"] if component["comparison"] == "le" else energy == component["value"]
            factors = [v * (component["damage_factor"] if active else 1) for v in factors]
        elif op == "slot":
            slot = profile.get("selectedSlot")
            additions = [component["add"] if slot in component["slots"] else 0] if slot in (1, 2, 3, 4) else [0, component["add"]]
        elif op == "per_fainted":
            context = attacker.get("liveContext", {})
            roster = context.get("rosters", {}).get(component["target"])
            if "faintedCounts" not in context and (not roster or len(roster) != 6 and "_simulation_actor" not in attacker):
                raise ValueError("动态威力缺少完整队伍力竭情况")
            from lab.trait_runtime import party_fainted_count
            member = {"trait_team_roster": context.get("rosters", {})}
            if "faintedCounts" in context:
                member["trait_team_fainted_counts"] = context["faintedCounts"]
            additions = [party_fainted_count(member, (component["target"],)) * component["add"]]
        elif op == "carried_cost_sum":
            costs = pet.get("carriedSkillCosts")
            if not isinstance(costs, list) or len(costs) != 4 or any(type(c) is not int or c < 0 for c in costs):
                raise ValueError("动态威力缺少敌方四槽当前能耗，不能把未观测技能补零")
            powers = [sum(costs) * component["factor"]]
        else:
            raise ValueError(f"未知实时威力组件 {op}")
        powers = sorted({max(0, power + add) for power in powers for add in additions})
    return powers, factors


def resolved_hits(attacker, profile):
    """Shared Moonlight count: living active and reserve members on both sides."""
    sid = battle_data.canonical_skill(profile.get("skillId")).get("skill_id", profile.get("skillId"))
    if sid != 7160280:
        return profile["hits"]
    from lab.cute_runtime import _data, alive_party_layers
    from .live_damage import _rules
    row = _data()["skills"][str(sid)]
    if canonical_hash(_rules()[1].skill(sid)) != row["record_hash"]:
        raise ValueError("Moonlight source changed")
    rosters = attacker.get("liveContext", {}).get("rosters")
    return row["base_hits"] + alive_party_layers({"trait_team_roster": rosters}) * row["hits_per_alive_cute_layer"]
