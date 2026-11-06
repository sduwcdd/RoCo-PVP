"""Whole-description team energy effects over explicit owned roster targets."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from lab.effect_runtime import execute_effects, HOOKS
from lab.game_runtime_defaults import ROOT
from lab.phase_config import fingerprint
from lab.prepared_rules import prepare_rules

CONFIG = ROOT / 'data/rules/reviewed-team-targets-1.json'
CONFIG_SHA256 = 'ab9c8fa8ba1a214e079e6b9665fa34d4ea181212df70cdcb97d4f5a6b7931515'
POLICY = 'whole_state_team_energy_after_committed_skill_living_targets_v1'
POLICIES = {'timing': 'after_committed_skill_before_next_action',
    'targets': 'declared_side_and_active_or_reserve_slots_from_owned_current_roster',
    'exhausted': 'skip_zero_hp_targets_without_revive', 'energy_cap': 'clamp_to_declared_max',
    'energy_floor': 'clamp_to_zero', 'source': 'original_caster_skill_not_recipient_skill_use',
    'repeated_source_slots': 'whole_description_per_member_amount_once_not_slot_count'}


@lru_cache(maxsize=2)
def _configuration(stamp):
    raw = CONFIG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONFIG_SHA256:
        raise ValueError('Team-target configuration changed; source review required')
    return json.loads(raw)


@lru_cache(maxsize=16)
def _source_hash(path, size, stamp):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _data():
    config = _configuration(CONFIG.stat().st_mtime_ns)
    for relative, expected in config['sources'].items():
        path = (ROOT / relative).resolve()
        stat = path.stat()
        if not path.is_relative_to(ROOT) or _source_hash(str(path), stat.st_size, stat.st_mtime_ns) != expected:
            raise ValueError('Team-target extracted source changed')
    return config


def research_context():
    return {'team_target_policy': POLICY, 'team_target_policies': deepcopy(POLICIES)}


def programs(catalog):
    prepared = prepare_rules(catalog)
    config = _data()
    if prepared.snapshot_id != config['snapshot_id']:
        raise ValueError('Team-target source snapshot changed')
    result = {}
    for key, row in config['skills'].items():
        record = prepared._rules.skill(int(key))
        if fingerprint(record) != row['record_hash'] or record != row['record']:
            raise ValueError('Team-target complete description changed: ' + key)
        program = deepcopy(prepared._rules.program(int(key)))
        program.pop('native_rule', None)
        program.update(status='compiled', blockers=[], operations=deepcopy(row['before_operations']),
            team_target_components={'targets': deepcopy(row['targets']), 'effect': deepcopy(row['effect'])},
            team_target_evidence=deepcopy(row), team_target_config_hash=CONFIG_SHA256,
            team_target_policies=deepcopy(POLICIES), response_kinds=[],
            executable=False, real_game_verified=False, training_eligible=False)
        result[int(key)] = program
    return result


def _program(prepared, program):
    expected = programs(prepared).get(program.get('game_id'))
    if expected is None or fingerprint(expected) != fingerprint(program):
        raise ValueError('Team-target program differs from its reviewed source compilation')
    return program['team_target_components']


def _targets(state, side, spec):
    if side not in ('a', 'b') or type(state.get('turn')) is not int or state['turn'] < 1:
        raise ValueError('Team-target phase needs an owned side and positive turn')
    target_side = side if spec['targets']['side'] == 'self' else 'b' if side == 'a' else 'a'
    team = state['teams'][target_side]
    active = team['active_slot']
    if (not isinstance(team.get('members'), list) or not team['members']
            or type(active) is not int or not 0 <= active < len(team['members'])):
        raise ValueError('Malformed team-target roster/active slot')
    selected, seen = [], set()
    for slot, member in enumerate(team['members']):
        mid = member.get('member_id')
        if not isinstance(mid, str) or not mid or mid in seen:
            raise ValueError('Team-target roster needs unique owned member IDs')
        seen.add(mid)
        for field in ('hp', 'max_hp', 'energy', 'max_energy'):
            if type(member.get(field)) is not int or member[field] < 0:
                raise ValueError('Team energy targets require explicit integer resource bounds')
        from lab.trait_runtime import energy_allows_overflow
        if member['hp'] > member['max_hp'] or (member['energy'] > member['max_energy'] and not energy_allows_overflow(member)):
            raise ValueError('Team energy target exceeds its declared resource bound')
        if spec['targets']['positions'] == 'reserve' and slot == active:
            continue
        if member['hp'] > 0:
            selected.append((target_side, slot, mid))
    return selected


def preflight_targets(catalog, state, side, program, *, context):
    prepared = prepare_rules(catalog)
    spec = _program(prepared, program)
    if (state.get('snapshot_id') != prepared.snapshot_id
            or context.get('team_target_policy') != POLICY
            or context.get('team_target_policies') != POLICIES):
        raise ValueError('Explicit source-bound team-target policies required')
    return _targets(state, side, spec)


def after_skill(catalog, state, side, program, *, event_token, context):
    """Post-hook transaction; original skill payment/damage is owned upstream."""
    result = {'status': 'blocked', 'state': deepcopy(state), 'events': [], 'blockers': [],
              'training_eligible': False, 'real_game_verified': False}
    try:
        prepared = prepare_rules(catalog)
        selected = preflight_targets(prepared, state, side, program, context=context)
        if not isinstance(event_token, str) or not event_token:
            raise ValueError('Team-target application needs an explicit action token')
        spec = program['team_target_components']
        actor_team = state['teams'][side]
        actor = actor_team['members'][actor_team['active_slot']]
        identity = {'token': event_token, 'turn': state['turn'], 'side': side,
                    'actor_member_id': actor['member_id'], 'skill_id': program['game_id'],
                    'source_hash': program['source_hash'], 'config_sha256': CONFIG_SHA256}
        token_hash = fingerprint(identity)
        ledger = state.get('team_target_events', [])
        if (not isinstance(ledger, list) or any(not isinstance(item, dict)
                or set(item) != set(identity) | {'event_hash'}
                or item.get('event_hash') != fingerprint({k: v for k, v in item.items() if k != 'event_hash'})
                or item.get('config_sha256') != CONFIG_SHA256 for item in ledger)
                or len({item['token'] for item in ledger}) != len(ledger)):
            raise ValueError('Malformed team-target event ledger')
        prior = next((item for item in ledger if item['token'] == event_token), None)
        if prior:
            if prior['event_hash'] != token_hash:
                raise ValueError('Team-target action token reused for a different source')
            result.update(status='applied')
            return result
        current, events = deepcopy(state), []
        for target_side, slot, mid in selected:
            target = current['teams'][target_side]['members'][slot]
            receiver = deepcopy(target)
            receiver['types'] = deepcopy(prepared._rules.form(target['form_id'])['types'])
            effect_program = {'game_id': program['game_id'], 'category': 'skill', 'status': 'compiled',
                'blockers': [], 'snapshot_id': prepared.snapshot_id, 'source_hash': program['source_hash'],
                'operations': [{'op': spec['effect']['op'], 'params': {'target': 'self', 'amount': spec['effect']['amount']}}]}
            primitive_context = {'mode': 'isolated_skill_experiment', 'snapshot_id': prepared.snapshot_id,
                'source_hash': program['source_hash'], 'excluded_hooks': sorted(HOOKS),
                'unresolved_dependencies': [], 'operation_order': 'source_text_order_experiment',
                'turn': state['turn'], 'energy_policy': 'clamp_to_declared_max', 'energy_reduction_policy': 'clamp_to_zero_experiment'}
            fragment = execute_effects(effect_program, {'self': receiver, 'opponent': deepcopy(receiver)}, primitive_context)
            if fragment['status'] != 'applied':
                raise ValueError('Team recipient primitive blocked: ' + '; '.join(fragment['blockers']))
            # Primitive effects do not dispatch skill.use on the recipient.
            target['energy'] = fragment['state']['self']['energy']
            target['hp'] = fragment['state']['self']['hp']
            for event in fragment['events']:
                events.append({**event, 'target': spec['targets']['side'], 'target_side': target_side,
                    'target_slot': slot, 'target_member_id': mid, 'actor_side': side,
                    'actor_member_id': actor['member_id'], 'source_skill_id': program['game_id'],
                    'source_hash': program['source_hash'], 'requested_amount': spec['effect']['amount'],
                    'actual_amount': abs(event['after'] - event['before']), 'phase': 'team_target.after_skill',
                    'team_target_policy': POLICY, 'team_target_config_hash': CONFIG_SHA256,
                    'team_target_policies': deepcopy(POLICIES), 'action_token': event_token})
        current['team_target_events'] = [*deepcopy(ledger), {**identity, 'event_hash': token_hash}]
        result.update(status='applied', state=current, events=events)
    except (ValueError, KeyError, TypeError) as exc:
        result['blockers'] = [str(exc)]
    return result
