"""Reviewed next-attack power and persistent skill lifesteal source ledgers."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from lab.effect_runtime import execute_effects, _preflight_header, _preflight
from lab.phase_config import fingerprint
from lab.prepared_rules import prepare_rules

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'data/rules/reviewed-attack-grants-1.json'
CONFIG_HASH = '4920686aaf9db02c0865548f46fc9e71a8e80f6433330d586a52e8bbe30a2d6a'
POLICY = 'source_bound_attack_grants_with_historical_layers_experiment_v1'
POLICIES = {'lifesteal': 'same_buff_add_source_layers_cap99_ten_percent_each_experiment',
    'power': 'same_buff_refresh_max1_other_buff_overlap_rejected_experiment',
    'timing': 'install_after_successful_skill_old_token_consumption_experiment',
    'departure': 'clear_source_flagged_grants_on_actual_departure',
    'power_order': 'multiply_after_flat_power_before_weather_traits_marks_experiment'}


@lru_cache(maxsize=16)
def _hash(path, size, stamp):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rules():
    data = json.loads(CONFIG.read_text(encoding='utf8'))
    if fingerprint(data) != CONFIG_HASH:
        raise ValueError('Attack grant configuration changed')
    for source in data['sources']:
        path = (ROOT / source['path']).resolve()
        stat = path.stat()
        if not path.is_relative_to(ROOT) or _hash(str(path), stat.st_size, stat.st_mtime_ns) != source['sha256']:
            raise ValueError('Attack grant current/historical source changed')
    return data


def research_context():
    return {'attack_grant_policies': deepcopy(POLICIES)}


def _power_entry(row, response_success=None):
    if 'response_variant' in row and type(response_success) is not bool:
        raise ValueError('Variant power grant needs an explicit resolved response')
    selected = row['response_variant'] if row.get('response_variant') and response_success else row
    return {'kind': row['kind'], 'amount': selected['amount'], 'buff_id': selected['buff_id'], 'base_id': selected['base_id'],
        ('source_trait_id' if row.get('source_kind') == 'trait' else 'source_skill_id'): row['record']['id'],
        'source_hash': row['record_hash'],
        'policy': POLICY, 'config_hash': CONFIG_HASH, 'clear_on_departure': selected['clear_on_departure'],
        **({'resolved_response_success':response_success} if 'response_variant' in row else {})}


def _life_entry(grants, layers):
    return {'kind': 'lifesteal', 'buff_id': 20540010, 'base_id': 2054001, 'layers': layers,
        'per_layer_percent': 10, 'grants': grants, 'policy': POLICY, 'config_hash': CONFIG_HASH,
        'clear_on_departure': True}


def validate_member(member):
    entries = member.get('skill_attack_grants', [])
    if not isinstance(entries, list):
        raise ValueError('Attack grants require a source ledger')
    data, kinds = rules(), set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get('kind') in kinds:
            raise ValueError('Overlapping or malformed attack grant')
        kinds.add(entry.get('kind'))
        if entry.get('kind') == 'next_attack_power':
            row = (data.get('traits', {}).get(str(entry.get('source_trait_id'))) if 'source_trait_id' in entry
                   else data['skills'].get(str(entry.get('source_skill_id'))))
            if row is None or entry != _power_entry(row,entry.get('resolved_response_success')):
                raise ValueError('Pending power source changed')
        elif entry.get('kind') == 'lifesteal':
            total = 0
            grants = entry.get('grants')
            if not isinstance(grants, list) or not grants:
                raise ValueError('Lifesteal requires historical layer grants')
            for grant in grants:
                if grant.get('transform') == 'reduce':
                    source = data.get('reductions',{}).get(str(grant.get('source_skill_id')))
                    removed = grant.get('removed_layers')
                    if (source is None or type(removed) is not int or not 0 < removed < total
                            or removed > source['max_layers'] or grant != {'transform':'reduce',
                            'source_skill_id':source['record']['id'],'source_hash':source['record_hash'],
                            'before_layers':total,'after_layers':total-removed,'removed_layers':removed}):
                        raise ValueError('Lifesteal reduction source changed')
                    total -= removed
                    continue
                if grant.get('transform') == 'double':
                    source = data['transformations'].get(str(grant.get('source_skill_id')))
                    if source is None or grant != {'transform': 'double',
                            'source_skill_id': source['record']['id'], 'source_hash': source['record_hash'],
                            'before_layers': total, 'after_layers': min(99, total * 2)}:
                        raise ValueError('Lifesteal transformation source changed')
                    total = grant['after_layers']
                    continue
                row = data['skills'].get(str(grant.get('source_skill_id')))
                if row is None or row['kind'] != 'lifesteal':
                    raise ValueError('Unknown lifesteal skill source')
                layers = row['amount'] // 10
                added = min(layers, 99 - total)
                if grant != {'source_skill_id': row['record']['id'], 'source_hash': row['record_hash'],
                             'requested_layers': layers, 'added_layers': added}:
                    raise ValueError('Lifesteal layer provenance changed')
                total += added
            if entry != _life_entry(grants, total):
                raise ValueError('Lifesteal total/rate changed')
        else:
            raise ValueError('Unknown attack grant kind')
    return entries


def install_trait_power(member, trait_id, source_hash):
    row = rules().get('traits', {}).get(str(trait_id))
    if row is None or source_hash != row['record_hash']:
        raise ValueError('Trait power grant source changed')
    entries = deepcopy(validate_member(member))
    previous = next((e for e in entries if e['kind'] == 'next_attack_power'), None)
    if previous and previous['buff_id'] != row['buff_id']:
        raise ValueError('Trait and other power buffs overlap; multiplication rule unverified')
    entry = _power_entry(row)
    member['skill_attack_grants'] = [e for e in entries if e['kind'] != 'next_attack_power'] + [entry]
    return {'op': 'attack.grant', 'target': 'self', 'before':previous, 'after':deepcopy(entry), 'policy':POLICY}


def transform_lifesteal(entry, new_layers, source_skill_id, source_hash):
    validate_member({'skill_attack_grants': [entry]})
    source = rules()['transformations'].get(str(source_skill_id))
    if (entry['kind'] != 'lifesteal' or source is None or source_hash != source['record_hash']
            or type(new_layers) is not int or new_layers != min(99, entry['layers'] * 2)):
        raise ValueError('Only source-bound capped lifesteal doubling is supported')
    history = deepcopy(entry['grants']) + [{'transform': 'double', 'source_skill_id': source_skill_id,
        'source_hash': source_hash, 'before_layers': entry['layers'], 'after_layers': new_layers}]
    return _life_entry(history, new_layers)


def reduce_lifesteal(entry, removed_layers, source_skill_id, source_hash):
    validate_member({'skill_attack_grants':[entry]})
    source = rules().get('reductions',{}).get(str(source_skill_id))
    if (source is None or source_hash != source['record_hash'] or entry['kind'] != 'lifesteal'
            or type(removed_layers) is not int or not 0 < removed_layers < entry['layers']
            or removed_layers > source['max_layers']):
        raise ValueError('Invalid source-bound partial lifesteal removal')
    history = deepcopy(entry['grants']) + [{'transform':'reduce','source_skill_id':source_skill_id,
        'source_hash':source_hash,'before_layers':entry['layers'],'after_layers':entry['layers']-removed_layers,
        'removed_layers':removed_layers}]
    return _life_entry(history,entry['layers']-removed_layers)


def install(member, program, context):
    data = rules()
    row = data['skills'].get(str(program.get('game_id')))
    if (row is None or program.get('source_hash') != row['record_hash']
            or program.get('snapshot_id') != data['snapshot_id']
            or context.get('attack_grant_policies') != POLICIES):
        raise ValueError('Attack grant source or explicit policy changed')
    entries = deepcopy(validate_member(member))
    existing = next((e for e in entries if e['kind'] == row['kind']), None)
    if row['kind'] == 'next_attack_power':
        entry = _power_entry(row,context.get('response_success'))
        if existing and existing['buff_id'] != entry['buff_id']:
            raise ValueError('Different pending power buffs overlap; multiplication rule unverified')
    else:
        before = existing['layers'] if existing else 0
        requested = row['amount'] // 10
        grants = deepcopy(existing['grants']) if existing else []
        grants.append({'source_skill_id': program['game_id'], 'source_hash': program['source_hash'],
                       'requested_layers': requested, 'added_layers': min(requested, 99 - before)})
        entry = _life_entry(grants, min(99, before + requested))
    entries = [e for e in entries if e['kind'] != row['kind']] + [entry]
    member['skill_attack_grants'] = entries
    return {'op': 'attack.grant', 'target': 'self', 'before': existing, 'after': deepcopy(entry),
            'source_skill_id': program['game_id'], 'source_hash': program['source_hash'], 'policies': deepcopy(POLICIES)}


def power_factor(member):
    return next((e['amount'] for e in validate_member(member) if e['kind'] == 'next_attack_power'), 1)


def consume_power(member, *, attacked):
    entries = validate_member(member)
    consumed = [e for e in entries if attacked and e['kind'] == 'next_attack_power']
    if consumed:
        member['skill_attack_grants'] = [deepcopy(e) for e in entries if e not in consumed]
    return [{'op': 'attack.power.consume', 'target': 'self', 'grant': deepcopy(e), 'policy': POLICY} for e in consumed]


def lifesteal_source(member):
    entry = next((e for e in validate_member(member) if e['kind'] == 'lifesteal'), None)
    if entry is None:
        return None
    return {'trait_id': None, 'source_kind': 'skill_buff', 'source_buff_id': entry['buff_id'],
            'record_hash': fingerprint(entry), 'when': 'skill_grant', 'percent': entry['layers'] * 10,
            'skill_lifesteal_grant': deepcopy(entry)}


def depart(member):
    current = deepcopy(member)
    current['skill_attack_grants'] = [deepcopy(e) for e in validate_member(member) if not e['clear_on_departure']]
    return current


def programs(catalog):
    prepared, data = prepare_rules(catalog), rules()
    if prepared.snapshot_id != data['snapshot_id']:
        raise ValueError('Attack grant snapshot changed')
    output = {}
    for key, row in data['skills'].items():
        if row['record']['kind'] == 'defense':
            continue
        if fingerprint(prepared._rules.skill(int(key))) != row['record_hash']:
            raise ValueError('Attack grant whole source changed')
        program = deepcopy(prepared._rules.program(int(key)))
        program.pop('native_rule', None)
        program.update(status='compiled', blockers=[], operations=deepcopy(row['operations']),
            attack_grant_components={'kind':row['kind'], 'when':row['when']}, attack_grant_config_hash=CONFIG_HASH,
            response_kinds=deepcopy(row['responses']), dependency_ids=deepcopy(row['record'].get('desc_notes', [])),
            executable=False, real_game_verified=False, training_eligible=False)
        output[int(key)] = program
    return output


def preflight(program, state, context, damage_resolver=None):
    _preflight_header(program, state, context)
    row = rules()['skills'].get(str(program.get('game_id')))
    if (row is None or program.get('operations') != row['operations'] or
            program.get('attack_grant_components') != {'kind':row['kind'], 'when':row['when']} or
            program.get('attack_grant_config_hash') != CONFIG_HASH or
            program.get('source_hash') != row['record_hash'] or context.get('attack_grant_policies') != POLICIES):
        raise ValueError('Attack grant source, components or explicit policies changed')
    if (row['when'] == 'response.success' or 'response_variant' in row) and type(context.get('response_success')) is not bool:
        raise ValueError('Attack grant requires explicit response classification')
    grant = row['when'] == 'always' or context['response_success']
    if grant:
        after_old_consumption = deepcopy(state['self'])
        consume_power(after_old_consumption, attacked=row['record']['kind'] in ('physical', 'magical'))
        install(after_old_consumption, program, context)
    _preflight(program, state, {**context, 'component_sequence_payment':'reviewed_component_sequence_v1'}, damage_resolver)
    return {'grant': grant}


def execute(program, state, context, *, damage_resolver=None):
    result = {'status':'blocked','state':deepcopy(state),'events':[],'blockers':[], 'training_eligible':False}
    try:
        grant = preflight(program, state, context, damage_resolver)['grant']
        result = execute_effects(program, state, {**context,
            'component_sequence_payment':'reviewed_component_sequence_v1'}, damage_resolver=damage_resolver)
        if result['status'] == 'applied' and grant:
            result['events'].append(install(result['state']['self'], program, context))
        result['training_eligible'] = False
    except (ValueError, KeyError, TypeError) as exc:
        result = {'status':'blocked','state':deepcopy(state),'events':[],'blockers':[str(exc)], 'training_eligible':False}
    return result
