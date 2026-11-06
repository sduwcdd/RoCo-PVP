"""Source-bound charged components; all scheduling remains a named experiment."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json

from lab.game_runtime_defaults import ROOT
from lab.phase_config import fingerprint
from lab.skill_execution import execute_skill, preflight_skill

CONFIG = ROOT / 'data/rules/reviewed-charge-components-1.json'
CONFIG_SHA256 = '02466cf6d70a197de93d7529f8c33d5a4ed45513d538ed222296c2faa7a8c059'
POLICY = 'charge-observed-attack-and-file-layers-v1'


def _configuration():
    raw = CONFIG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONFIG_SHA256:
        raise ValueError('Reviewed charge configuration changed; source review required')
    config = json.loads(raw)
    for relative, expected in config['source_files'].items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
            raise ValueError('Historical charge source changed: ' + relative)
    return config


@lru_cache(maxsize=2)
def _flat_components(stamp):
    config = _configuration()
    return {row['skill_id']: (row['record_hash'], component)
            for row in config['skills'] for component in row['components']
            if component['op'] == 'stat.flat.layers'}


def component_programs(catalog, tables, hashes, phase):
    """Compile reviewed data, without matching names or parsing sentences."""
    config = _configuration()
    records = catalog['moves']
    records = records.values() if isinstance(records, dict) else records
    records = {record['id']: record for record in records}
    out = {}
    for row in config['skills']:
        mid, record = row['skill_id'], records[row['skill_id']]
        if fingerprint(record) != row['record_hash'] or catalog['snapshot_id'] != config['snapshot_id']:
            raise ValueError('Reviewed charge record changed')
        game = tables['SKILL_CONF'][str(mid)]
        if (game['energy_cost'] != [record['energy']]
                or game['dam_para'] != [record.get('power', 0)]
                or not phase['skills'][str(mid)]['charge']['declared']):
            raise ValueError('Charge game numeric/phase source differs')
        operations = []
        if record['kind'] in ('physical', 'magical'):
            operations.append({'op': 'damage', 'params': {'target': 'opponent',
                'kind': record['kind'], 'power': record['power'], 'type': record['type']}})
        evidence = {**deepcopy(row['evidence']), 'game_source_hashes': deepcopy(hashes),
            'game_skill_raw': deepcopy(game), 'record_hash': row['record_hash'],
            'config_sha256': CONFIG_SHA256, 'component_policy': POLICY}
        buff = tables['BUFF_CONF'][str(row['charge_buff_id'])]
        evidence['game_charge_buff_raw'] = deepcopy(buff)
        evidence['game_charge_bases_raw'] = [deepcopy(tables['BUFFBASE_CONF'][str(key)])
                                             for key in buff['buff_base_ids']]
        program = {'game_id': mid, 'name': record['name']['zh'], 'category': 'skill',
            'compiler_version': POLICY, 'snapshot_id': catalog['snapshot_id'],
            'source_version': catalog.get('source_version'), 'source_hash': row['record_hash'],
            'source_description': record['desc']['zh'], 'source_details': {'desc_notes': record['desc_notes']},
            'source': {key: deepcopy(record[key]) for key in ('wiki_id', 'source_url', 'source_module')},
            'static_fields': {key: deepcopy(record[key]) for key in ('kind', 'type', 'energy', 'power') if key in record},
            'skill_source': deepcopy(catalog['provenance']['Skills']),
            'term_source': deepcopy(catalog['provenance']['Terms']),
            'status': 'compiled', 'blockers': [], 'dependency_ids': deepcopy(record['desc_notes']),
            'operations': operations, 'charge_components': deepcopy(row['components']),
            'response_kinds': deepcopy(row['responses']), 'charge_component_policy': POLICY,
            'charge_adapter_evidence': evidence,
            'order_semantics': 'release_after_source_bound_charge_phase_experiment',
            'execution_scope': 'charge_release_payload_requires_external_charge_phase',
            'executable': False, 'real_game_verified': False, 'training_eligible': False,
            'whole_game_skill_verified': False,
            'execution_blockers': ['Requires explicit research charge phase; authoritative server semantics remain unverified.']}
        program['charge_adapter_program_sha256'] = fingerprint(program)
        out[mid] = program
    return out


def _attacks(charge):
    attacks = charge.get('incoming_attacks', [])
    if not isinstance(attacks, list):
        raise ValueError('Charged incoming attacks must be an explicit event list')
    tokens = set()
    for attack in attacks:
        if (not isinstance(attack, dict) or attack.get('policy') != POLICY
                or type(attack.get('skill_id')) is not int or attack['skill_id'] <= 0
                or attack.get('kind') not in ('physical', 'magical')
                or type(attack.get('turn')) is not int
                or not charge['started_turn'] <= attack['turn'] <= charge['release_turn']
                or not isinstance(attack.get('token'), str) or not attack['token']
                or attack['token'] in tokens
                or not isinstance(attack.get('powers'), list) or not attack['powers']
                or any(type(p) is not int or p < 0 for p in attack['powers'])):
            raise ValueError('Invalid charged incoming attack provenance')
        tokens.add(attack['token'])
    return attacks


def observe_attack(member, *, skill_id, skill_kind, turn, events, action_token):
    """Call after an actual committed opponent skill; poison/marks are excluded.

    Zero HP loss still counts as an observed damage attempt. No damage event
    means no hit observation. Multiple differing powers stay explicitly unknown.
    """
    charge = member.get('charge')
    if charge is None or skill_kind not in ('physical', 'magical'):
        return []
    if type(turn) is not int or not charge['started_turn'] <= turn <= charge['release_turn']:
        raise ValueError('Incoming attack falls outside the charge interval')
    attacks = _attacks(charge)
    powers = []
    for event in events:
        if event.get('op') != 'damage' or event.get('target') != 'opponent':
            continue
        params = event.get('resolved_params', event.get('params', {}))
        if params.get('kind') not in ('physical', 'magical'):
            continue
        power = params.get('power')
        if type(power) is not int or power < 0:
            raise ValueError('Observed charged attack requires resolved skill power')
        if power not in powers:
            powers.append(power)
    if not powers or any(a['token'] == action_token for a in attacks):
        return []
    attack = {'skill_id': skill_id, 'kind': skill_kind, 'turn': turn,
        'powers': powers, 'token': action_token, 'policy': POLICY}
    candidate = {**deepcopy(charge), 'incoming_attacks': [*deepcopy(attacks), attack]}
    _attacks(candidate)
    charge['incoming_attacks'] = candidate['incoming_attacks']
    return [{'op': 'research.charge_attack_observed', 'target': 'opponent', **deepcopy(attack)}]


def _payload(program, state, context):
    expected = program.get('charge_adapter_program_sha256')
    if (program.get('charge_component_policy') != POLICY
            or expected != fingerprint({k: v for k, v in program.items() if k != 'charge_adapter_program_sha256'})):
        raise ValueError('Source-bound charge component program was modified')
    charge = state['self'].get('charge')
    bypass = context.get('execution_phase') == 'bypass_charge_pending_execution'
    if context.get('execution_phase')=='jealousy_release_pending_execution':
        from lab.charge_program_adapter import validate_jealousy_release
        validate_jealousy_release(program,state['self'],context)
        attacks=_attacks(charge)
    elif bypass:
        from lab.duration_runtime import charge_bypass
        if charge is not None or not charge_bypass(state['self'], context.get('turn')):
            raise ValueError('Charge bypass requires an actual active token and no existing charge')
        attacks = []
    elif (not isinstance(charge, dict) or charge.get('skill_id') != program['game_id']
            or charge.get('snapshot_id') != program['snapshot_id']
            or charge.get('source_skill_hash') != program['source_hash']
            or context.get('turn') != charge.get('release_turn')):
        raise ValueError('Charged components require the owned release-turn charge record')
    else:
        attacks = _attacks(charge)
    base, flat = deepcopy(program), []
    for component in program['charge_components']:
        condition = component.get('when')
        if condition == 'response.success':
            if type(context.get('response_success')) is not bool:
                raise ValueError('Charged response requires explicit success classification')
            if not context['response_success']:
                continue
        elif condition == 'charge.attacked' and not attacks:
            continue
        op = component['op']
        if op.startswith('damage.power.'):
            factor = component['factor']
            powers = {p for attack in attacks for p in attack['powers']}
            if op == 'damage.power.from_charge_attack' and len(powers) != 1:
                raise ValueError('Different incoming skill powers: first/last/max/sum selection is not source-verified')
            for operation in base['operations']:
                if operation['op'] == 'damage':
                    value = next(iter(powers)) if op == 'damage.power.from_charge_attack' else operation['params']['power']
                    operation['params']['power'] = value * factor
        elif op == 'stat.percent.layers':
            base['operations'].append({'op': 'stat.modify', 'params': {'target': component['target'],
                'attributes': component['attributes'], 'percent': {'numerator': component['layers'] * component['per_layer_basis_points'], 'denominator': 10000}}})
        elif op == 'stat.flat.layers':
            from lab import mark_runtime as marks
            if context.get('mark_policies') != marks.research_context()['mark_policies']:
                raise ValueError('Explicit layer policy required for flat charged stat effects')
            layers = marks.extra_buff_layers(state[component['target']], component['layers'])
            evidence = {'policy': deepcopy(marks.POLICIES), 'base_layers': component['layers'],
                'marks': deepcopy(state[component['target']].get('field_marks', marks.EMPTY))}
            flat.append({**deepcopy(component), 'applied_layers': layers,
                         'amount': layers * component['per_layer'], 'layer_evidence': evidence})
        else:
            raise ValueError('Unknown reviewed charged component')
    return base, flat


def preflight(program, state, context, damage_resolver=None):
    base, _ = _payload(program, state, context)
    preflight_skill(base, state, context, damage_resolver)


def execute(program, state, context, damage_resolver=None):
    base, flat = _payload(program, state, context)
    result = execute_skill(base, state, context, damage_resolver=damage_resolver)
    if result['status'] == 'applied':
        for component in flat:
            actor = result['state'][component['target']]
            modifier = {'attribute': component['attribute'], 'amount': component['amount'],
                'layers': component['applied_layers'], 'per_layer': component['per_layer'],
                'policy': POLICY, 'source_skill_id': program['game_id'], 'source_hash': program['source_hash'],
                'config_sha256': CONFIG_SHA256, 'layer_evidence': deepcopy(component['layer_evidence'])}
            actor.setdefault('charge_flat_modifiers', []).append(modifier)
            result['events'].append({'op': 'stat.flat.modify', 'target': component['target'], **deepcopy(modifier)})
    return result


def modify_speed(member, speed):
    modifiers = member.get('charge_flat_modifiers', [])
    if not isinstance(modifiers, list):
        raise ValueError('Charged flat modifiers require a source-bound ledger')
    if not modifiers:
        return speed
    from lab import mark_runtime as marks
    sources = _flat_components(CONFIG.stat().st_mtime_ns)
    for modifier in modifiers:
        if (not isinstance(modifier, dict) or modifier.get('policy') != POLICY
                or type(modifier.get('source_skill_id')) is not int
                or modifier['source_skill_id'] not in sources):
            raise ValueError('Invalid charged flat-speed source')
        source_hash, component = sources[modifier['source_skill_id']]
        evidence = modifier.get('layer_evidence')
        if (modifier.get('source_hash') != source_hash or modifier.get('config_sha256') != CONFIG_SHA256
                or modifier.get('attribute') != component['attribute']
                or type(modifier.get('per_layer')) is not int or modifier['per_layer'] != component['per_layer']
                or not isinstance(evidence, dict) or set(evidence) != {'policy', 'base_layers', 'marks'}
                or evidence['policy'] != marks.POLICIES
                or type(evidence['base_layers']) is not int or evidence['base_layers'] != component['layers']):
            raise ValueError('Invalid charged flat-speed layer source')
        layers = marks.extra_buff_layers({'field_marks': evidence['marks']}, component['layers'])
        if (type(modifier.get('amount')) is not int or type(modifier.get('layers')) is not int
                or modifier['layers'] != layers or modifier['amount'] != layers * component['per_layer']):
            raise ValueError('Invalid charged flat-speed modifier')
        speed += modifier['amount']
    return speed
