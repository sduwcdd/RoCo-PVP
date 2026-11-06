"""Source-bound cast-local cute gains over the shared PVP effect executor."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

from lab.ruleset import canonical_hash
from lab.effect_runtime import _integer, _preflight_header, execute_effects

CONFIG = Path(__file__).resolve().parents[1] / 'data/rules/reviewed-cute-components-1.json'
POLICY = 'user_confirmed_cast_local_gain_and_alive_party_layers_20261030'


@lru_cache(maxsize=2)
def _configuration(stamp):
    data = json.loads(CONFIG.read_text(encoding='utf-8'))
    if data.get('schema') != 'reviewed-cute-components-1' or data.get('policy') != POLICY:
        raise ValueError('Unknown reviewed cute configuration')
    return data


def _data():
    return _configuration(CONFIG.stat().st_mtime_ns)


def validate(member):
    value = member.get('cute_layers', 0)
    _integer(value, 'cute layers')
    if member.get('cute_policy', POLICY) != POLICY:
        raise ValueError('Cute state belongs to another rules version')
    return value


def gain_cute(member, amount, *, source, context=None):
    """Mutate an owned member, preserving all unrelated runtime state and ledgers."""
    _integer(amount, 'cute gain')
    if not isinstance(source, dict) or not source:
        raise ValueError('Cute gain requires an explicit source')
    before = validate(member)
    if amount == 0 or member['hp'] == 0:
        return {'before': before, 'after': before, 'gained': 0, 'events': []}
    from lab import battle_data, live_damage
    catalog, rules = live_damage._rules()
    if context and context.get('snapshot_id', catalog['snapshot_id']) != catalog['snapshot_id']:
        raise ValueError('Cute snapshot differs from the shared HUD rules')
    form = rules.form(member['form_id'])
    stage = form.get('stage')
    if type(stage) is not int or stage < 1:
        raise ValueError('Cute needs an exact evolution stage')
    unlimited = member.get('trait_id') == _data()['unlimited_trait']['id']
    if unlimited and canonical_hash(catalog['traits'][str(member['trait_id'])]) != _data()['unlimited_trait']['record_hash']:
        raise ValueError('Unlimited cute trait source changed')
    gained = amount if unlimited else min(amount, stage - 1)
    if not gained:
        return {'before': before, 'after': before, 'gained': 0, 'events': []}
    lower = battle_data.lower_stage_form(member['form_id'], min(amount, stage - 1)) if stage > 1 else {}
    if stage > 1:
        if not lower or lower.get('steps') != min(amount, stage - 1):
            raise ValueError('Cute evolution predecessor cannot be uniquely source-matched')
        target = rules.form(lower['base_conf_id'])
        if target.get('trait_id') != form.get('trait_id'):
            raise ValueError('Cute predecessor changes trait; transfer has not been reviewed')
        record = member.get('original_configuration')
        if not isinstance(record, dict):
            raise ValueError('Cute panel recalculation needs the exact original configuration')
        from lab.simulation import _estimate
        panels, provenance, notes = _estimate(catalog, record, target)
        old_form, old_hp, old_max = member['form_id'], member['hp'], member['max_hp']
        member.update(form_id=target['id'], name=target['name']['zh'], types=deepcopy(target['types']),
            hp=max(1, old_hp * panels['hp'] // old_max), max_hp=panels['hp'],
            stats={dim: value for dim, value in panels.items() if dim != 'hp'}, speed=panels['spd'])
        member['panel_provenance'] = {'mode': 'cute_recalculation', 'fields': provenance,
            'source_policy': _data()['hp_transfer_policy'], 'previous_form': old_form}
    member['cute_layers'] = before + gained
    member['cute_policy'] = POLICY
    event = {'op': 'cute.gain', 'before': before, 'after': member['cute_layers'],
        'gained': gained, 'source': deepcopy(source), 'policy': POLICY,
        'target_member_id': member['member_id']}
    member.setdefault('cute_sources', []).append(deepcopy(event))
    return {'before': before, 'after': member['cute_layers'], 'gained': gained, 'events': [event]}


def programs(prepared):
    data = _data()
    if prepared.snapshot_id != data['snapshot_id']:
        raise ValueError('Cute configuration snapshot changed')
    out = {}
    for key, row in data['skills'].items():
        record = prepared._rules.skill(int(key))
        if canonical_hash(record) != row['record_hash']:
            raise ValueError('Cute whole skill source changed')
        program = deepcopy(prepared._rules.program(int(key)))
        program.pop('native_rule', None)
        program.update(status='compiled', blockers=[], execution_blockers=[], operations=[],
            cute_components=deepcopy(row), cute_config_hash=canonical_hash(data), cute_policy=POLICY)
        out[int(key)] = program
    return out


def _row(program):
    row = _data()['skills'].get(str(program.get('game_id')))
    if (not row or row != program.get('cute_components') or program.get('source_hash') != row['record_hash']
            or program.get('cute_policy') != POLICY or program.get('cute_config_hash') != canonical_hash(_data())):
        raise ValueError('Cute program source or components changed')
    return row


def alive_party_layers(member):
    roster = member.get('trait_team_roster')
    if not isinstance(roster, dict) or set(roster) != {'self', 'opponent'}:
        raise ValueError('Moonlight ensemble needs both complete owned rosters')
    total = 0
    for team in roster.values():
        if not isinstance(team, list) or not team:
            raise ValueError('Moonlight ensemble needs complete rosters')
        for pet in team:
            _integer(pet.get('hp'), 'party HP')
            if pet['hp'] == 0:
                continue
            if 'cute_layers' not in pet or pet['cute_layers'] is None:
                raise ValueError('Party cute layers must be explicit, never guessed as zero')
            total += validate(pet)
    return total


def preflight(program, state, context, damage_resolver=None):
    _preflight_header(program, state, context)
    row = _row(program)
    for member in state.values():
        validate(member)
    if row['raw']['kind'] in ('physical', 'magical') and not callable(damage_resolver):
        raise ValueError('Cute attack needs the shared damage resolver')
    if row.get('hits_per_alive_cute_layer'):
        alive_party_layers(state['self'])


def execute(program, state, context, damage_resolver=None):
    result = {'status': 'blocked', 'state': deepcopy(state), 'events': [], 'blockers': [],
              'training_eligible': False, 'calibrated': False, 'real_game_verified': False}
    try:
        preflight(program, state, context, damage_resolver)
        current, row, events = deepcopy(state), _row(program), []
        source = {'skill_id': program['game_id'], 'source_hash': program['source_hash']}
        gains = {}
        for target in row['gain']:
            gained = gain_cute(current[target], 1, source=source, context=context)
            gains[target] = gained['gained'] > 0
            events.extend({**event, 'target': target} for event in gained['events'])
        own_gained = gains.get('self', False)
        from lab import mechanism_runtime
        if own_gained:
            for field, op in (('speed_if_gained', 'speed.flat'), ('permanent_power_if_gained', 'power.flat')):
                if field in row:
                    events.append(mechanism_runtime.grant_modifier(current['self'],
                        {'op': op, 'amount': row[field], 'target': 'self'}, program, context))
            if 'cost_if_gained' in row:
                events.append(mechanism_runtime._change_cost(current['self'],
                    {'skill_selector': 'all', 'amount': row['cost_if_gained'], 'target': 'self'}, program, context))
        operations = []
        raw = row['raw']
        if raw['kind'] in ('physical', 'magical'):
            power = raw['power'] + (row.get('bonus_power_if_gained', 0) if own_gained else 0)
            hits = row.get('base_hits', 1)
            if row.get('hits_per_alive_cute_layer'):
                hits += alive_party_layers(current['self']) * row['hits_per_alive_cute_layer']
            operations.append({'op': 'damage.sequence' if hits > 1 else 'damage', 'params': {
                'target': 'opponent', 'kind': raw['kind'], 'type': raw['type'], 'power': power,
                **({'hits': hits} if hits > 1 else {})}})
        if row.get('heal_if_gained') and gains and all(gains.values()):
            operations.append({'op': 'hp.restore', 'params': {'target': 'self',
                'percent': {'numerator': row['heal_if_gained'][0], 'denominator': row['heal_if_gained'][1]}}})
        fragment = deepcopy(program)
        fragment['operations'] = operations
        if any(op['op'] == 'damage.sequence' for op in operations):
            fragment['dependency_ids'] = sorted(set(fragment.get('dependency_ids', [])) | {3005})
        applied = execute_effects(fragment, current, {**context, 'cute_cast_gains': gains, 'component_sequence_payment': 'reviewed_component_sequence_v1'}, damage_resolver=damage_resolver)
        if applied['status'] != 'applied':
            raise ValueError('; '.join(applied['blockers']))
        result.update(applied)
        result['events'] = events + applied['events']
        result['cute_cast_gains'] = gains
        result['cute_cast_order_policy'] = _data()['cast_order_policy']
    except Exception as exc:
        result['blockers'] = [str(exc)]
    return result
