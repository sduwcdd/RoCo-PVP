"""Committed direct-defeat proofs and narrowly matched pending interruptions."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from lab.game_runtime_defaults import ROOT
from lab.phase_config import fingerprint
from lab.prepared_rules import prepare_rules

CONFIG = ROOT / 'data/rules/reviewed-action-outcomes-1.json'
CONFIG_SHA256 = 'efdc05b59003e9df28e2b077e257b48b0c99d89bfb08d56a0f0a6e47983b1799'
POLICY = 'committed_direct_attack_defeat_and_matching_pending_interrupt_v1'
POLICIES = {'proof': 'committed_direct_damage_living_to_zero_with_actor_target_and_occurrence',
    'interrupt': 'cancel_only_matching_uncommitted_declared_skill_this_turn',
    'payment': 'interrupted_release_is_not_executed_and_pays_nothing',
    'charge': 'clear_interrupted_pending_charge_release_experiment',
    'committed_action': 'never_rollback_an_already_committed_opponent'}


@lru_cache(maxsize=2)
def _configuration(stamp):
    raw = CONFIG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONFIG_SHA256:
        raise ValueError('Action outcome configuration changed; review required')
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
            raise ValueError('Action outcome extracted source changed')
    return config


def programs(catalog):
    prepared, config = prepare_rules(catalog), _data()
    if prepared.snapshot_id != config['snapshot_id']:
        raise ValueError('Action outcome source snapshot differs')
    out = {}
    for key, row in config['interrupt_skills'].items():
        record = prepared._rules.skill(int(key))
        if record != row['record'] or fingerprint(record) != row['record_hash']:
            raise ValueError('Interrupt whole description changed')
        program = deepcopy(prepared._rules.program(int(key)))
        if row.get('runtime')=='duration':
            from lab.duration_runtime import programs as duration_programs
            program=duration_programs(prepared)[int(key)]
        program.pop('native_rule', None)
        program.update(status='compiled', blockers=[], operations=deepcopy(program['operations']) if row.get('runtime')=='duration' else [{'op': 'damage', 'params': {
            'target': 'opponent', 'kind': record['kind'], 'power': record['power'], 'type': record['type']}}],
            interrupt_components=deepcopy(row['components']), response_kinds=deepcopy(row.get('response_kinds',['status'])),
            interrupt_evidence=deepcopy(row), action_outcome_config_hash=CONFIG_SHA256,
            action_outcome_policies=deepcopy(POLICIES), executable=False,
            training_eligible=False, real_game_verified=False)
        out[int(key)] = program
    return out


def _active(state, side):
    team = state['teams'][side]
    return team['members'][team['active_slot']]


def _identity(member, config):
    form = config['forms'].get(str(member.get('form_id')))
    if form is None or member.get('trait_id', form['trait_id']) != form['trait_id']:
        raise ValueError('Action outcome member form/trait source differs')
    return {'member_id': member['member_id'], 'form_id': member['form_id'],
            'form_hash': form['record_hash'], 'trait_id': form['trait_id']}


def _skill_catalog_hash(skill_id, config):
    expected = config['skill_hashes'].get(str(skill_id))
    if expected is not None:
        return expected
    from lab.core_magic_runtime import reviewed_wish_skill
    skill = reviewed_wish_skill(skill_id)
    if skill is None:
        raise ValueError('Unreviewed action-outcome skill source: ' + str(skill_id))
    return fingerprint(skill)


def validate_direct_defeat(proof):
    """Validate a detached proof; live occurrence matching is owned by victory."""
    config = _data()
    if (not isinstance(proof, dict) or proof.get('policy') != POLICY
            or proof.get('config_sha256') != CONFIG_SHA256
            or proof.get('proof_hash') != fingerprint({k: v for k, v in proof.items() if k != 'proof_hash'})
            or proof.get('attacker_side') not in ('a', 'b')
            or proof.get('target_side') != ('b' if proof['attacker_side'] == 'a' else 'a')
            or type(proof.get('turn')) is not int or proof['turn'] < 1
            or not isinstance(proof.get('action_token'), str) or not proof['action_token']
            or type(proof.get('occurrence')) is not int or proof['occurrence'] < 1
            or proof.get('accounting_scope') not in ('victory', 'direct_action_only')
            or _skill_catalog_hash(proof.get('skill_id'), config) != proof.get('skill_catalog_hash')
            or not isinstance(proof.get('skill_source_hash'), str) or not proof['skill_source_hash']):
        raise ValueError('Invalid source-bound direct-defeat proof')
    for key in ('attacker', 'target'):
        identity = proof.get(key)
        if (not isinstance(identity, dict) or not isinstance(identity.get('member_id'), str)
                or not identity['member_id'] or identity != _identity(identity, config)):
            raise ValueError('Direct-defeat member identity/source differs')
    event = proof.get('damage_event', {})
    params = event.get('resolved_params', event.get('params', {}))
    if (event.get('op') not in ('damage', 'damage.hit') or event.get('target') != 'opponent'
            or params.get('kind') not in ('physical', 'magical')
            or any(type(event.get(k)) is not int for k in ('before', 'after', 'damage'))
            or event['before'] <= 0 or event['after'] != 0 or event['damage'] != event['before']):
        raise ValueError('Direct-defeat proof requires an actual lethal direct-attack HP-loss event')
    return True


def record_committed_action(catalog, state, side, action, events, *, event_token,
                            opponent_action=None, opponent_committed=False, response_success=False):
    """Call immediately after skill state commit, before switching or KO accounting.

    Mutates owned full state and returns only new outcome events. Periodic and
    mark deaths never become direct kills merely because an enemy is on field.
    """
    prepared, config = prepare_rules(catalog), _data()
    if state.get('snapshot_id') != config['snapshot_id'] or prepared.snapshot_id != config['snapshot_id']:
        raise ValueError('Committed action outcome snapshot differs')
    if action.get('kind') != 'skill' or action.get('execution_phase') == 'charge_setup_not_attack_release':
        return []
    if not isinstance(event_token, str) or not event_token or side not in ('a', 'b'):
        raise ValueError('Committed action needs its unique token and owned side')
    program = action['program']
    skill_id = action['skill_id']
    prepared._rules.skill(skill_id)
    actor, other = _active(state, side), 'b' if side == 'a' else 'a'
    if actor['member_id'] != action['actor_member_id'] or program['game_id'] != skill_id:
        raise ValueError('Committed action actor or skill changed before attribution')
    trace = [e for e in events if e.get('op') not in ('action.direct_defeat',
        'action.interrupt.scheduled', 'action.interrupt.noop')]
    signature = fingerprint({'turn': state['turn'], 'side': side, 'actor': actor['member_id'],
        'skill_id': skill_id, 'source_hash': program['source_hash'], 'events': trace})
    ledger = state.get('committed_action_outcomes', {})
    if (not isinstance(ledger, dict) or any(not isinstance(key, str) or not isinstance(value, str)
                                         for key, value in ledger.items())):
        raise ValueError('Malformed committed action outcome ledger')
    if event_token in ledger:
        if ledger[event_token] != signature:
            raise ValueError('Committed action token reused for a different trace')
        return []
    current, emitted = deepcopy(state), []
    target = _active(current, other)
    for event in trace:
        params = event.get('resolved_params', event.get('params', {}))
        if (event.get('op') not in ('damage', 'damage.hit') or event.get('target') != 'opponent'
                or params.get('kind') not in ('physical', 'magical') or event.get('after') != 0):
            continue
        if target['hp'] != 0:
            continue
        if (event.get('actor_side', side) != side
                or event.get('actor_member_id', actor['member_id']) != actor['member_id']
                or event.get('skill_id', skill_id) != skill_id
                or event.get('source_hash', program['source_hash']) != program['source_hash']
                or event.get('target_side', other) != other):
            raise ValueError('Lethal event does not belong to the committed action source')
        if event.get('target_member_id', target['member_id']) != target['member_id']:
            raise ValueError('Lethal event target differs from the committed active member')
        victory = current.get('victory')
        if victory is not None and victory['observed_alive'][other][target['member_id']] is not True:
            raise ValueError('Direct defeat requires an uncounted observed living-to-zero edge')
        counts = current.setdefault('direct_defeat_counts', {}).setdefault(other, {})
        occurrence = (victory['knockouts'][other][target['member_id']] + 1 if victory is not None
                      else counts.get(target['member_id'], 0) + 1)
        proof = {'policy': POLICY, 'config_sha256': CONFIG_SHA256, 'turn': current['turn'],
            'trait_policy': current.get('trait_policy'),
            'action_token': event_token, 'attacker_side': side, 'target_side': other,
            'attacker': _identity(actor, config), 'target': _identity(target, config),
            'skill_id': skill_id, 'skill_catalog_hash': _skill_catalog_hash(skill_id, config),
            'skill_source_hash': program['source_hash'], 'damage_event': deepcopy(event),
            'occurrence': occurrence, 'accounting_scope': 'victory' if victory is not None else 'direct_action_only'}
        proof['proof_hash'] = fingerprint(proof)
        validate_direct_defeat(proof)
        proofs = current.setdefault('knockout_provenance', {}).setdefault(other, {})
        prior = proofs.get(target['member_id'])
        if (prior and prior.get('occurrence') == proof['occurrence']
                and prior.get('accounting_scope') == proof['accounting_scope'] and prior != proof):
            raise ValueError('Conflicting direct-defeat traces for the same knockout')
        proofs[target['member_id']] = proof
        counts[target['member_id']] = occurrence
        emitted.append({'op': 'action.direct_defeat', 'target': 'opponent', 'proof': deepcopy(proof)})
    if 'interrupt_components' in program:
        expected = programs(prepared).get(skill_id)
        if expected is None or fingerprint(expected) != fingerprint(program):
            raise ValueError('Interrupt program differs from reviewed whole description')
        if type(response_success) is not bool or type(opponent_committed) is not bool:
            raise ValueError('Interrupt requires explicit response and commit classifications')
        if response_success:
            if (not isinstance(opponent_action, dict) or opponent_action.get('kind') != 'skill'
                    or opponent_action.get('execution_phase') == 'charge_setup_not_attack_release'
                    or prepared._rules.skill(opponent_action['skill_id'])['kind'] not in program.get('response_kinds',['status'])):
                raise ValueError('Successful interrupt must match the source response kind and opposing declared skill')
            if opponent_committed:
                emitted.append({'op': 'action.interrupt.noop', 'target': 'opponent', 'reason': 'opponent_already_committed'})
            else:
                target = _active(current, other)
                if target['member_id'] != opponent_action['actor_member_id']:
                    raise ValueError('Interrupt target member changed before declaration matching')
                marker = {'policy': POLICY, 'config_sha256': CONFIG_SHA256, 'turn': current['turn'],
                    'target_side': other, 'target_member_id': target['member_id'],
                    'target_skill_id': opponent_action['skill_id'], 'target_slot': opponent_action['slot'],
                    'source_skill_id': skill_id, 'source_hash': program['source_hash'],
                    'source_actor_side': side, 'source_actor_member_id': actor['member_id'],
                    'action_token': event_token, 'status': 'pending'}
                marker['marker_hash'] = fingerprint(marker)
                current.setdefault('pending_action_interrupts', {})[other] = marker
                emitted.append({'op': 'action.interrupt.scheduled', 'target': 'opponent', **deepcopy(marker)})
    history_actor = _active(current, side)
    if 'committed_skill_history' in history_actor:
        committed_history(history_actor)
        from lab.weather_runtime import resolved_skill_type
        skill = prepared._rules.skill(skill_id)
        kind = skill['kind']
        if kind == 'higher':
            from lab.core_magic_runtime import reviewed_wish_skill
            reviewed = reviewed_wish_skill(skill_id)
            if reviewed is None or program['source_hash'] != fingerprint(reviewed):
                raise ValueError('Committed adaptive attack lacks its reviewed wish source')
            kinds = {event.get('resolved_params', event.get('params', {})).get('kind') for event in trace
                     if event.get('op') in ('damage', 'damage.hit') and event.get('target') == 'opponent'}
            if len(kinds) != 1 or not kinds <= {'physical', 'magical'}:
                raise ValueError('Committed wish history needs one actually resolved damage kind')
            kind = kinds.pop()
        row = {'turn': current['turn'], 'member_id':actor['member_id'], 'skill_id':skill_id,
            'kind':kind, 'response_success':response_success,
            'effective_type':resolved_skill_type(current.get('weather'), skill_id, skill['type']),
            'source_hash':program['source_hash'], 'token':event_token, 'outcome_signature':signature}
        row['hash'] = fingerprint(row)
        history_actor['committed_skill_history'].append(row)
    current.setdefault('committed_action_outcomes', {})[event_token] = signature
    state.clear(); state.update(current)
    return emitted


def consume_interrupt(state, side, action):
    """Check exact turn/member/slot/skill; a replacement never inherits a cancel."""
    result = {'cancelled': False, 'events': []}
    markers = state.get('pending_action_interrupts', {})
    if not isinstance(markers, dict):
        raise ValueError('Malformed pending interrupt ledger')
    marker = markers.get(side)
    if marker is None:
        return result
    if (not isinstance(marker, dict) or marker.get('policy') != POLICY
            or marker.get('config_sha256') != CONFIG_SHA256
            or marker.get('marker_hash') != fingerprint({k: v for k, v in marker.items() if k != 'marker_hash'})
            or marker.get('status') not in ('pending', 'consumed')
            or marker.get('source_hash') != _data()['interrupt_skills'].get(str(marker.get('source_skill_id')), {}).get('record_hash')):
        raise ValueError('Pending interrupt source/marker changed')
    member = _active(state, side)
    matches = (marker['turn'] == state['turn'] and marker['target_side'] == side
        and member['member_id'] == marker['target_member_id'] == action.get('actor_member_id')
        and action.get('kind') == 'skill' and action.get('skill_id') == marker['target_skill_id']
        and action.get('slot') == marker['target_slot'])
    slots = member.get('skill_slots')
    if (not isinstance(slots, list) or type(action.get('slot')) is not int
            or not 0 <= action['slot'] < len(slots) or slots[action['slot']] != action.get('skill_id')):
        matches = False
    if not matches:
        return result
    result['cancelled'] = True
    if marker['status'] == 'consumed':
        return result
    if action.get('execution_phase') == 'charge_release_pending_execution':
        charge = member.get('charge')
        if charge is None or charge.get('skill_id') != action['skill_id'] or charge.get('slot') != action['slot']:
            raise ValueError('Interrupted pending release no longer matches its charge')
        member['charge'] = None
    marker['status'] = 'consumed'
    marker['marker_hash'] = fingerprint({k: v for k, v in marker.items() if k != 'marker_hash'})
    result['events'] = [{'op': 'action.interrupted', 'actor_side': side,
        'actor_member_id': member['member_id'], 'skill_id': action['skill_id'], 'skill_slot': action['slot'],
        'paid_energy': 0, 'source_skill_id': marker['source_skill_id'], 'source_hash': marker['source_hash'],
        'action_token': marker['action_token'], 'policy': POLICY, 'policies': deepcopy(POLICIES)}]
    return result


def committed_history(member):
    rows = member.get('committed_skill_history')
    if not isinstance(rows, list):
        raise ValueError('Committed skill history is missing; start a fresh simulation')
    tokens = set()
    for row in rows:
        if (not isinstance(row, dict) or row.get('member_id') != member['member_id']
                or type(row.get('turn')) is not int or row['turn'] < 1
                or type(row.get('response_success')) is not bool
                or not isinstance(row.get('effective_type'),str)
                or row.get('kind') not in ('physical', 'magical', 'status', 'defense')
                or not isinstance(row.get('token'), str) or row['token'] in tokens
                or row.get('hash') != fingerprint({k:v for k,v in row.items() if k != 'hash'})):
            raise ValueError('Committed skill history identity or trace changed')
        tokens.add(row['token'])
    return rows
