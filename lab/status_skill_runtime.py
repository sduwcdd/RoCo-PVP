"""Reviewed status components sharing ordinary effects and conductive weather code."""
from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from lab.game_runtime_defaults import ROOT
from lab.phase_config import fingerprint
from lab.prepared_rules import prepare_rules
from lab.skill_execution import execute_skill, preflight_skill
from lab import weather_runtime as weather

CONFIG = ROOT / 'data/rules/reviewed-status-skill-components-1.json'
CONFIG_SHA256 = '2d7b020723b24ab34d89091f6b4adaa379f9efd62363dd3e112f5b47eade1a06'
POLICY = 'source_bound_normal_status_with_shared_conductive_lifecycle_v1'
CATALOG = ROOT / 'data/bwiki/20261105T124140+0800/catalog.json'


@lru_cache(maxsize=2)
def _configuration(stamp):
    raw = CONFIG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONFIG_SHA256:
        raise ValueError('Status skill configuration changed; source review required')
    return json.loads(raw)


@lru_cache(maxsize=16)
def _source_hash(path, size, stamp):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _data():
    data = _configuration(CONFIG.stat().st_mtime_ns)
    for relative, expected in data['sources'].items():
        path = (ROOT / relative).resolve(); stat = path.stat()
        if not path.is_relative_to(ROOT) or _source_hash(str(path), stat.st_size, stat.st_mtime_ns) != expected:
            raise ValueError('Status skill extracted source changed')
    return data


@lru_cache(maxsize=2)
def _chart(stamp):
    return prepare_rules(json.loads(CATALOG.read_text(encoding='utf8')))


def _type_ratio(element, member):
    result = _chart(CATALOG.stat().st_mtime_ns)._rules.type_multiplier(element, member['form_id'])
    return Fraction(result['multiplier']['numerator'], result['multiplier']['denominator'])


def research_context():
    return {'status_skill_policy': POLICY, 'conductive_policy': weather.NUMERIC_POLICY}


def programs(catalog):
    prepared, config = prepare_rules(catalog), _data()
    if prepared.snapshot_id != config['snapshot_id']:
        raise ValueError('Status skill snapshot differs')
    out = {}
    for key, row in config['skills'].items():
        record = prepared._rules.skill(int(key))
        if fingerprint(record) != row['record_hash']:
            raise ValueError('Status skill complete description changed')
        program = deepcopy(prepared._rules.program(int(key)))
        program.pop('native_rule', None)
        program.update(status='compiled', blockers=[], operations=[{'op': 'damage', 'params': {
            'target': 'opponent', 'kind': record['kind'], 'power': record['power'], 'type': record['type']}}],
            status_skill_components=deepcopy(row['components']), status_skill_evidence=deepcopy(row),
            status_skill_config_hash=CONFIG_SHA256, status_skill_policy=POLICY, response_kinds=[],
            executable=False, training_eligible=False, real_game_verified=False)
        program['status_skill_program_hash'] = fingerprint(program)
        out[int(key)] = program
    return out


def preflight(program, state, context, damage_resolver=None):
    config = _data()
    row = config['skills'].get(str(program.get('game_id')))
    if (row is None or program.get('source_hash') != row['record_hash']
            or program.get('status_skill_components') != row['components']
            or program.get('status_skill_config_hash') != CONFIG_SHA256
            or program.get('status_skill_program_hash') != fingerprint({k: v for k, v in program.items() if k != 'status_skill_program_hash'})
            or context.get('status_skill_policy') != POLICY or context.get('conductive_policy') != weather.NUMERIC_POLICY):
        raise ValueError('Source-bound status skill program/policy changed')
    preflight_skill(program, state, context, damage_resolver)
    for component in row['components']:
        member = state[component['target']]
        if component['status'] == 'conductive':
            count = member.get('weather_statuses', {}).get('conductive', 0)
            if type(count) is not int or not 0 <= count <= 1:
                raise ValueError('Conductive skill requires the existing shared 0..1 layer state')
            _type_ratio('电系', member)


def execute(program, state, context, damage_resolver=None):
    original = deepcopy(state)
    try:
        preflight(program, state, context, damage_resolver)
        result = execute_skill(program, state, context, damage_resolver=damage_resolver)
        if result['status'] != 'applied':
            return result
        current, events = result['state'], result['events']
        for component in program['status_skill_components']:
            target = component['target']
            if current[target]['hp'] <= 0:
                continue
            if component['status'] == 'conductive':
                extra = weather.add_conductive(current[target], target, component['stacks'], _type_ratio,
                    turn=context.get('turn'), opponent=current['opponent' if target == 'self' else 'self'])
                for event in extra:
                    affected = event.get('target_side', target)
                    if affected not in ('self', 'opponent'):
                        raise ValueError('Conductive status event lost its actual relative target')
                    event = {**event, 'target': affected, 'target_member_id': current[affected]['member_id'],
                        'source_skill_id': program['game_id'], 'source_hash': program['source_hash'],
                        'status_skill_policy': POLICY}
                    actor_side = context.get('actor_side')
                    if actor_side in ('a', 'b'):
                        event['target_side'] = actor_side if affected == 'self' else 'b' if actor_side == 'a' else 'a'
                    else:
                        event.pop('target_side', None)
                    events.append(event)
            else:
                ordinary = deepcopy(program)
                ordinary['operations'] = [{'op': 'status.add', 'params': deepcopy(component)}]
                ordinary['operations'][0]['params'].pop('op', None)
                policies = {**context, 'resolved_energy_cost': 0}
                fragment = execute_skill(ordinary, current, policies)
                if fragment['status'] != 'applied':
                    raise ValueError('; '.join(fragment['blockers']))
                current = fragment['state']
                events.extend(e for e in fragment['events'] if e['op'] != 'energy.pay')
        result.update(state=current, events=events)
        return result
    except (ValueError, KeyError, TypeError) as exc:
        return {'status': 'blocked', 'state': original, 'events': [], 'blockers': [str(exc)],
                'training_eligible': False, 'real_game_verified': False}
