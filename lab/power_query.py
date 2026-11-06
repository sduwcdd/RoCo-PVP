"""Pure skill-power stage shared by damage and source-bound slot quotations."""
from copy import deepcopy
from fractions import Fraction
import math


def quote_damage_power(rules, params, state, context):
    """Resolve power before hit distribution, panels, type damage and HP clipping."""
    rules = rules._rules if hasattr(rules, '_rules') else rules
    actors, params = deepcopy(state), deepcopy(params)
    if context.get('snapshot_id') != rules.snapshot_id:
        raise ValueError('Power query requires its exact source snapshot')
    snapshots = context.get('trait_carried_costs', {})
    if snapshots:
        if not isinstance(snapshots, dict) or set(snapshots) != {'self', 'opponent'}:
            raise ValueError('Power query trait costs must cover both relative actors')
        for key in ('self', 'opponent'):
            actors[key]['trait_carried_costs'] = deepcopy(snapshots[key])
    attacker, defender = actors['self'], actors[params['target']]
    kind, power = params.get('kind'), params.get('power')
    if (kind not in ('physical', 'magical') or type(power) not in (int, float)
            or not math.isfinite(power) or not 0 < power <= 1_000_000):
        raise ValueError('Power query requires positive finite actual attack source power')
    from lab import weather_runtime as weather, mechanism_runtime, trait_runtime, mark_runtime
    from lab import pressure_runtime, adjacent_power_aura_runtime
    from lab.skill_history_runtime import modify_power as history_power
    skill_id, weather_state = context.get('weather_skill_id'), context.get('weather')
    params['type'] = weather.resolved_skill_type(weather_state, skill_id, params['type'])
    if skill_id:
        from lab.power_rule_runtime import rule_power
        power = rule_power(attacker, defender, skill_id, power, context=context)
    power = history_power(power, context.get('skill_history_power'))
    power = pressure_runtime.modify_power(attacker, power)
    power = adjacent_power_aura_runtime.modify_power(attacker, power, context.get('selected_skill_slot'))
    if 'choice_power_factor' in params:
        from lab.choice_runtime import current_power_factor
        power *= current_power_factor(skill_id,params,context)
    skill = {**rules.skill(skill_id), 'type': params['type']} if skill_id is not None else None
    power = mechanism_runtime.modify_power(attacker, power, skill=skill)
    power = weather.modify_power(weather_state, params['type'], power, skill_id, attacker)
    if skill_id is not None:
        power_opponent = {**defender, 'trait_current_skill_types':
            [rules.skill(mid)['type'] if mid else None for mid in defender['skill_slots']]}
        power = float(trait_runtime.modify_power(attacker, skill, power, opponent=power_opponent,
            first_attack=context.get('mark_first_attack', False)))
    raw = context.get('core_magic_power_multiplier', {'numerator': 1, 'denominator': 1})
    if (not isinstance(raw, dict) or set(raw) != {'numerator', 'denominator'}
            or type(raw['numerator']) is not int or type(raw['denominator']) is not int or raw['denominator'] <= 0):
        raise ValueError('Core magic power ratio must retain exact integers')
    ratio = Fraction(raw['numerator'], raw['denominator'])
    if ratio not in (Fraction(1), Fraction(5, 2)):
        raise ValueError('Unsupported core magic power multiplier')
    power *= float(ratio)
    before_marks = power
    power = float(mark_runtime.modify_power(attacker, power, kind,
        first_attack=context.get('mark_first_attack', False), first_action=context.get('mark_first_action')))
    return {'params': params, 'power': power, 'before_marks': before_marks, 'after_marks': power,
            'stage': 'effective_skill_power_before_hit_distribution_panels_type_damage_and_hp_clip'}
