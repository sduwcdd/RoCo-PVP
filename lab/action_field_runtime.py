"""Reviewed action fields kept separate from priority, response and turn order."""
from copy import deepcopy
import json
from pathlib import Path
from lab.prepared_rules import prepare_rules
from lab.ruleset import canonical_hash

CONFIG = Path(__file__).resolve().parents[1] / 'data/rules/reviewed-action-fields-1.json'
CONFIG_HASH = '2323ce5c6bd6dd1bd08417001bff176bdb9afb55067f544100e03453f4067d4b'


def rules():
    data = json.loads(CONFIG.read_text(encoding='utf8'))
    if canonical_hash(data) != CONFIG_HASH:
        raise ValueError('Reviewed action fields changed')
    return data


def programs(catalog):
    prepared, data = prepare_rules(catalog), rules()
    if prepared.snapshot_id != data['snapshot_id']:
        raise ValueError('Action-field source snapshot differs')
    result = {}
    for key, row in data['skills'].items():
        record = prepared._rules.skill(int(key))
        if record != row['record'] or canonical_hash(record) != row['record_hash']:
            raise ValueError('Action-field whole source differs')
        if row.get('modifier_only'):
            continue
        program = deepcopy(prepared._rules.program(int(key)))
        program.pop('native_rule', None)
        operations = ([{'op':'damage','params':{'target':'opponent', 'kind':record['kind'],
            'power':record['power'], 'type':record['type']}}] if record['kind'] in ('physical','magical')
            else [{'op':'energy.restore','params':{'target':'self','amount':1}}])
        operations = deepcopy(row.get('operations', operations))
        program.update(status='compiled', blockers=[], operations=operations,
            action_field_components=deepcopy(row['component']), action_field_policy=data['policy'],
            action_field_config_hash=CONFIG_HASH, executable=False, real_game_verified=False)
        if "opponent_cost_power_factor" in row["component"]:
            program["requires_opponent_cost_snapshot"] = True
        result[int(key)] = program
    return result


def fixed_cost(skill_id, normal):
    row = rules()['skills'].get(str(skill_id))
    return row['component'].get('fixed_cost', normal) if row else normal


def priority(skill_id, slot, normal):
    row = rules()['skills'].get(str(skill_id))
    spec = row['component'] if row else {}
    return normal + (spec['priority_add'] if spec.get('priority_all_slots') or spec.get('priority_slot') == slot else 0)


def resolve(program, context, state=None):
    data = rules()
    row = data['skills'].get(str(program.get('game_id')))
    if (not row or program.get('source_hash') != row['record_hash']
            or program.get('action_field_components') != row['component']
            or program.get('action_field_config_hash') != CONFIG_HASH
            or program.get('action_field_policy') != data['policy']):
        raise ValueError('Action fields differ from reviewed source')
    record = row['record']
    expected = row.get('operations', ([{'op':'damage','params':{'target':'opponent','kind':record['kind'],
        'power':record['power'],'type':record['type']}}] if record['kind'] in ('physical','magical')
        else [{'op':'energy.restore','params':{'target':'self','amount':1}}]))
    if program.get('operations') != expected:
        raise ValueError('Action-field effects differ from the reviewed complete source')
    output = deepcopy(program)
    factor = row['component'].get('opponent_cost_power_factor')
    if factor:
        costs = context.get('opponent_effective_skill_costs')
        slots = state.get('opponent',{}).get('skill_slots') if isinstance(state,dict) else None
        if (not isinstance(costs,list) or len(costs)!=4 or not isinstance(slots,list) or len(slots)!=4
                or any((type(costs[i]) is not int or costs[i]<0) if mid else costs[i] is not None for i,mid in enumerate(slots))):
            raise ValueError('Enemy cost-derived power requires four explicit occupied-slot current costs')
        power = sum(value for value in costs if value is not None) * factor
        if power == 0:
            raise ValueError('Zero total enemy cost produces zero source power; zero-power damage semantics are not calibrated')
        output['operations'][0]['params']['power'] = power
    divisor = row['component'].get('restore_opponent_cost_divisor')
    if divisor:
        cost = context.get('opponent_effective_cost')
        if type(cost) is not int or cost < 0:
            raise ValueError('Energy response needs the opponent total-cost snapshot')
        amount = cost // divisor
        output['operations'] = ([{'op':'energy.restore','params':{'target':'self','amount':amount}}]
                                if amount else [])
    condition = row['component'].get('previous_turn')
    if condition:
        from lab.action_outcome_runtime import committed_history
        if not isinstance(state, dict):
            raise ValueError('Previous-turn query requires the owned actor history')
        turn = context.get('turn')
        if type(turn) is not int or turn < 1:
            raise ValueError('Previous-turn query requires explicit turn')
        history = committed_history(state['self'])
        matched = any(e['turn'] == turn - 1 and (e['kind'] == condition if condition == 'status' else e['response_success']) for e in history)
        if matched:
            output['operations'][0]['params']['power'] += row['component']['power_add']
    previous_type = row['component'].get('previous_turn_type')
    if previous_type:
        history = state.get('self', {}).get('battle_skill_history') if isinstance(state, dict) else None
        turn = context.get('turn')
        if not isinstance(history, list) or type(turn) is not int or turn < 1:
            raise ValueError('Previous-turn team skill query requires the complete owned battle history')
        if any(e['turn'] == turn - 1 and e['effective_type'] == previous_type for e in history):
            output['operations'].extend(deepcopy(row['component']['conditional_operations']))
    return output
