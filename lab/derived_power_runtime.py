"""Source-bound cost-delta expressions, resolved before the common executor."""
from copy import deepcopy
import json
from pathlib import Path
from lab.prepared_rules import prepare_rules
from lab.ruleset import canonical_hash

CONFIG = Path(__file__).resolve().parents[1] / 'data/rules/reviewed-derived-power-1.json'
CONFIG_HASH = '9054fc001716893555efca1a672492fb17e5081c5d89bae5c2e6ca9a81533374'


def rules():
    config = json.loads(CONFIG.read_text(encoding='utf8'))
    if canonical_hash(config) != CONFIG_HASH:
        raise ValueError('Derived power source configuration changed')
    return config


def programs(catalog):
    prepared, config = prepare_rules(catalog), rules()
    if prepared.snapshot_id != config['snapshot_id']:
        raise ValueError('Derived power snapshot differs')
    result = {}
    for key, row in config['skills'].items():
        record = prepared._rules.skill(int(key))
        if record != row['record'] or canonical_hash(record) != row['record_hash']:
            raise ValueError('Derived power whole source differs')
        program = deepcopy(prepared._rules.program(int(key)))
        program.pop('native_rule', None)
        params = {'target':'opponent','kind':record['kind'],'type':record['type'],'power':record['power']}
        if row['hits'] is not None:
            params['hits'] = row['hits']
        program.update(status='compiled', blockers=[], operations=[{
            'op':'damage.sequence' if row['hits'] else 'damage', 'params':params}],
            derived_power_components={'base_cost':record['energy'], 'direction':row['direction'],
                'power_per_cost':row['power_per_cost']}, derived_power_policy=config['policy'],
            derived_power_config_hash=CONFIG_HASH, executable=False, real_game_verified=False)
        result[int(key)] = program
    return result


def resolve(program, context):
    config = rules()
    row = config['skills'].get(str(program.get('game_id')))
    if (not row or program.get('source_hash') != row['record_hash']
            or program.get('snapshot_id') != config['snapshot_id']
            or program.get('derived_power_config_hash') != CONFIG_HASH
            or program.get('derived_power_policy') != config['policy']):
        raise ValueError('Derived power program source differs')
    record = row['record']
    params = {'target':'opponent','kind':record['kind'],'type':record['type'],'power':record['power']}
    if row['hits'] is not None:
        params['hits'] = row['hits']
    if (program.get('operations') != [{'op':'damage.sequence' if row['hits'] else 'damage', 'params':params}]
            or program.get('derived_power_components') != {'base_cost':record['energy'],
                'direction':row['direction'], 'power_per_cost':row['power_per_cost']}):
        raise ValueError('Derived power expression differs from reviewed source')
    cost = context.get('health_payment', {}).get('total_cost', context.get('resolved_energy_cost'))
    if type(cost) is not int or cost < 0:
        raise ValueError('Derived power requires final total cost before energy substitution')
    delta = max(0, (cost - row['record']['energy']) * row['direction'])
    result = deepcopy(program)
    for operation in result['operations']:
        operation['params']['power'] = row['record']['power'] + delta * row['power_per_cost']
    return result
