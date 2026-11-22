"""Recover source-bound permanent power from actual hits, never fill missing history with zero."""
from copy import deepcopy

from . import battle_data, skill_history_runtime
from .ruleset import canonical_hash
from .trait_runtime import query_scope

TRIGGERS = {'after.use', 'after.use.no_previous_attack', 'member.enter',
            'carried.response.success', 'carried.other_type.use', 'carried.action.first'}
QUERY_BUDGET = 192


def descriptor(sid):
    sid = battle_data.canonical_skill(sid).get('skill_id', sid)
    data = skill_history_runtime._data()
    row = data['skills'].get(str(sid), {})
    components = row.get('components', [])
    if (len(components) != 1 or components[0].get('op') != 'power.add'
            or components[0].get('when') not in TRIGGERS or components[0].get('amount', 0) <= 0):
        return None
    from .live_damage import _rules
    catalog, rules = _rules()
    if data['snapshot_id'] != catalog['snapshot_id'] or canonical_hash(rules.skill(sid)) != row['record_hash']:
        raise ValueError('累计威力来源与当前图鉴不符')
    return {'skill_id': sid, 'when': components[0]['when'], 'amount': components[0]['amount'],
            'record_hash': row['record_hash'], 'history_hash': skill_history_runtime.CONFIG_SHA256,
            'snapshot_id': catalog['snapshot_id']}


def counter(pet, spec):
    sid, trigger = str(spec['skill_id']), spec['when']
    if trigger == 'after.use':
        return [pet.get('skillUseCounts', {}).get(sid, 0), 0]
    if trigger == 'after.use.no_previous_attack':
        return [pet.get('conditionalPowerCounts', {}).get(sid, 0), 0]
    if trigger == 'member.enter':
        return [pet.get('observedEntryCount', 0), 0]
    if trigger == 'carried.response.success':
        return [pet.get('responseSuccessCount', 0), 0]
    if trigger == 'carried.action.first':
        return list(pet.get('observedFirstActions', [0, 0]))
    row = skill_history_runtime._data()['skills'][sid]['components'][0]
    counts = pet.get('skillTypeUseCounts', {})
    return [sum(types.get(row['type'], 0) for mid, types in counts.items()
                if int(mid) != row['excluded_skill_id']), 0]


def _marker_count(pet, spec):
    row = skill_history_runtime._data()['skills'][str(spec['skill_id'])]
    evidence = row.get('evidence', {})
    bases = evidence.get('buff_bases', {})
    from .live_modifiers import _buff_bases, _raw_buffs, captured_buffs
    for bid, buff in evidence.get('buffs', {}).items():
        for base_id in buff.get('buff_base_ids', []):
            base = bases.get(str(base_id), {})
            params = [p['params'] for p in base.get('buffbase_param', [])]
            if (base.get('buffbase_order') != 64 or len(params) < 5 or params[:5] !=
                    [[7], [spec['skill_id']], [1], [1], [spec['amount']]]):
                continue
            raw = _raw_buffs().get(bid, {})
            if raw.get('buff_base_ids') != buff['buff_base_ids'] or _buff_bases().get(str(base_id)) != base:
                raise ValueError('原生累计威力标记来源已变化')
            counts = [b.get('layers') for b in captured_buffs(pet) if str(b.get('id')) == bid]
            if counts:
                if len(counts) != 1 or type(counts[0]) is not int or counts[0] < 0:
                    raise ValueError('原生累计威力层数无效')
                return [counts[0], counts[0]]
    return None


def _delta(now, before):
    known, unknown = now[0] - before[0], now[1] - before[1]
    if known < 0 or unknown < 0:
        raise ValueError('技能累计记录已重置，不能沿用旧反推')
    return known, known + unknown


def _conditional_extra(pet, spec):
    if spec['when'] != 'after.use.no_previous_attack':
        return 0, 0
    turn = pet.get('liveContext', {}).get('turn')
    if type(turn) is not int:
        raise ValueError('条件累计缺少当前回合')
    if pet.get('lastMoveRound') == turn:
        turn += 1
    if (pet.get('skillUseHistoryComplete') is not True
            and turn - 1 < (pet.get('historyStartRound') or turn)):
        return 0, 1
    value = skill_history_runtime.conditional_power_bonus(
        spec['skill_id'], turn - 1 in pet.get('observedAttackRounds', [])) // spec['amount']
    return value, value


def additions(pet, sid):
    if '_simulation_actor' in pet:
        return None
    spec = descriptor(sid)
    if spec is None:
        return None
    carried = pet.get('carriedSkillIds')
    if carried is not None and [battle_data.canonical_skill(mid).get('skill_id', mid) for mid in carried].count(spec['skill_id']) != 1:
        raise ValueError('累计技能无法匹配唯一的真实携带槽位')
    query = pet.get('_growthQuery')
    if query and query.get('skill_id') == spec['skill_id']:
        if {key: query.get(key) for key in spec} != spec:
            raise ValueError('累计威力正算查询的规则来源已变化')
        counts = query['counts']
    else:
        counts = _marker_count(pet, spec)
        if counts is None:
            anchor = pet.get('powerHistoryInference', {}).get(str(spec['skill_id']))
            if anchor is None:
                if (spec['when'] == 'carried.action.first' and pet.get('skillUseHistoryComplete') is True
                        and 'observedFirstActions' in pet):
                    known, uncertain = counter(pet, spec)
                    counts = [known if pet.get('carriedSkillIds') is not None else 0, known + uncertain]
                else:
                    return None
            else:
                if anchor.get('binding') != spec:
                    raise ValueError('累计伤害反推的规则来源已变化')
                lo, hi = _delta(counter(pet, spec), anchor['counter'])
                if pet.get('carriedSkillIds') is None:
                    lo = 0  # An observed enemy skill does not prove its original acquisition time.
                extra_lo, extra_hi = _conditional_extra(pet, spec)
                counts = [anchor['counts'][0] + lo + extra_lo, anchor['counts'][1] + hi + extra_hi]
    return [count * spec['amount'] for count in counts]


@query_scope()
def recover(attacker, defender, current, sid, damage, critical=False):
    """Enumerate a finite compatible range with the exact existing forward query.

    The budget is a query limit, not a game cap. Exhaustion remains unresolved.
    Only positive linear intrinsic growth with unchanged combat factors qualifies.
    """
    spec = descriptor(sid)
    if spec is None or attacker.get('skillUseHistoryComplete') is True:
        return None
    if _marker_count(attacker, spec) is not None:
        return None  # A source-proven native layer count takes precedence over hit inversion.
    if type(damage) not in (int, float) or damage <= 0:
        raise ValueError('零伤害不能反推累计威力')
    from . import live_damage
    profile = live_damage.skill_math(sid, live_damage._effective_base(attacker), live_damage._effective_base(defender))
    if profile.get('reason') or profile.get('kind') not in ('physical', 'magical', 'higher'):
        raise ValueError('该累计技能缺少可用的直接伤害模型')
    resolved = battle_data.skill_info(sid)
    if not resolved and type(sid) is int and sid > 9_999_999:
        resolved = battle_data.skill_info(sid // 100)
    profile['skillId'] = (resolved or {}).get('skill_id', spec['skill_id'])
    if profile.get('resolvedVariant'):
        from .live_power import specification
        variant = specification(profile['skillId'])
        if not variant or variant.get('id') != profile['skillId']:
            raise ValueError('该应对变体的累计规则尚未核对，不能反推次数')
    allowed = (live_damage._higher_attack_values(attacker, defender) if profile['kind'] == 'higher'
               else {profile['kind']: None})
    candidate = deepcopy(attacker)
    candidate.pop('configurationInference', None)
    defender = deepcopy(defender)
    defender.pop('configurationInference', None)
    counts, baseline, previous = [], None, None
    from .weather_runtime import rules as weather_rules
    weather_traits = {int(mid) for mid in weather_rules().get('trait_modifiers', {})}
    for count in range(QUERY_BUDGET):
        candidate['_growthQuery'] = {**spec, 'counts': [count, count]}
        cases = [live_damage._damage_case(candidate, defender, profile, kind, values, reference=False)
                 for kind, values in allowed.items() if values is None or values]
        if any(set(c['effects'].get('unreviewed_trait_ids', [])) - weather_traits for c in cases):
            raise ValueError('本次伤害含尚未接入的特性，不能把其增伤当作累计次数')
        shape = [(c['atkRange'], c['defRange'], c['finalMultiplierRange']) for c in cases]
        bounds = (min(c['criticalMinimum' if critical else 'minimum'] for c in cases),
                  max(c['criticalMaximum' if critical else 'maximum'] for c in cases))
        if baseline is None:
            baseline = shape
        if shape != baseline or previous and (bounds[0] < previous[0] or bounds[1] < previous[1]):
            raise ValueError('威力变化同时改变伤害条件，不能按线性累计反推')
        if bounds[0] <= damage <= bounds[1]:
            counts.append(count)
        if bounds[0] > damage:
            break
        previous = bounds
    else:
        raise ValueError('查询预算内无法确定累计次数上界，保留未确认状态')
    if not counts:
        raise ValueError('本次伤害与当前攻防和累计规则不相容')
    before, after = counter(attacker, spec), counter(current, spec)
    lo, hi = _delta(after, before)
    # Conditional growth is applied on this use; other growth affects future uses.
    if spec['when'] in ('after.use.no_previous_attack', 'member.enter', 'carried.other_type.use'):
        lo = hi = 0
    anchor = {'binding': spec, 'counts': [min(counts) + lo, max(counts) + hi], 'counter': after,
              'turn': attacker.get('liveContext', {}).get('turn'), 'observed_damage': damage,
              'damage_counts': [min(counts), max(counts)], 'calibrated': False,
              'source': 'shared_forward_hit_constraint', 'notice': '攻击、防御或状态未确定时保留相容累计次数范围。'}
    previous_anchor = current.get('powerHistoryInference', {}).get(str(spec['skill_id']))
    if previous_anchor and previous_anchor.get('binding') == spec:
        old_lo, old_hi = _delta(after, previous_anchor['counter'])
        if current.get('carriedSkillIds') is None:
            old_lo = 0
        overlap = [max(anchor['counts'][0], previous_anchor['counts'][0] + old_lo),
                   min(anchor['counts'][1], previous_anchor['counts'][1] + old_hi)]
        if overlap[0] > overlap[1]:
            raise ValueError('新伤害与已有累计约束冲突，保留之前的结果')
        anchor['counts'] = overlap
    return anchor
