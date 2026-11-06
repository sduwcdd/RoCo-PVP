"""Source-bound position locks, interior neighbor swaps and whole-slot bundles."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from lab.game_runtime_defaults import ROOT
from lab.phase_config import fingerprint
from lab.prepared_rules import prepare_rules

CONFIG = ROOT / 'data/rules/reviewed-slot-components-1.json'
CONFIG_SHA256 = 'c264b0c2c89d30d8aef328851f6ee800b31df07c5cb4f3ba3434f6be9af61fb4'
POLICY = 'source_bound_slot_permutation_and_bundle_transfer_v1'
POLICIES = {'neighbors': 'interior_left_and_right_only_edge_wrap_unresolved',
    'locks': 'never_move_locked_indices_unknown_collision_blocks',
    'bundle': 'swap_live_bindings_rebind_member_keep_original_owner_and_pool_history',
    'charge': 'source_target_two_cleanup_cancels_opponent_charge_before_bundle_swap',
    'modifiers': 'unknown_cost_or_live_defense_transfer_blocks',
    'timing': 'after_original_skill_and_temporary_transformation_return_before_departure'}


@lru_cache(maxsize=2)
def _configuration(stamp):
    raw = CONFIG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONFIG_SHA256:
        raise ValueError('Slot component configuration changed; source review required')
    return json.loads(raw)


@lru_cache(maxsize=16)
def _source_hash(path, size, stamp):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _data():
    data = _configuration(CONFIG.stat().st_mtime_ns)
    for relative, expected in data['sources'].items():
        path = (ROOT / relative).resolve()
        stat = path.stat()
        if not path.is_relative_to(ROOT) or _source_hash(str(path), stat.st_size, stat.st_mtime_ns) != expected:
            raise ValueError('Slot extracted source changed')
    return data


def research_context():
    return {'slot_policy': POLICY, 'slot_policies': deepcopy(POLICIES)}


def locked_skill_ids():
    return {int(key) for key, row in _data()['skills'].items() if row['component']['op'] == 'position.lock'}


def validate_slot_permutation(member, previous_slots):
    """Called by the shared remapper after IDs move, before binding mutation."""
    slots = member['skill_slots']
    before = [slots[previous_slots.index(old)] for old in range(4)]
    locked = locked_skill_ids()
    if any(before[old] in locked and previous_slots[old] != old for old in range(4)):
        raise ValueError('Position-locked skill would move; transmission/lock collision rule is unresolved')


def programs(catalog):
    prepared, config = prepare_rules(catalog), _data()
    if prepared.snapshot_id != config['snapshot_id']:
        raise ValueError('Slot component snapshot changed')
    result = {}
    for key, row in config['skills'].items():
        record = prepared._rules.skill(int(key))
        if fingerprint(record) != row['record_hash'] or record != row['record']:
            raise ValueError('Slot whole description changed')
        program = deepcopy(prepared._rules.program(int(key)))
        program.pop('native_rule', None)
        program.update(status='compiled', blockers=[], operations=deepcopy(row['before_operations']),
            slot_components=deepcopy(row['component']), slot_evidence=deepcopy(row),
            slot_config_hash=CONFIG_SHA256, slot_policies=deepcopy(POLICIES), response_kinds=[],
            executable=False, training_eligible=False, real_game_verified=False)
        result[int(key)] = program
    return result


def _active(state, side):
    team = state['teams'][side]
    return team['members'][team['active_slot']]


def _program(prepared, program, context):
    expected = programs(prepared).get(program.get('game_id'))
    if expected is None or fingerprint(expected) != fingerprint(program):
        raise ValueError('Slot program differs from source-bound compilation')
    if context.get('slot_policy') != POLICY or context.get('slot_policies') != POLICIES:
        raise ValueError('Explicit slot movement policies required')
    return program['slot_components']['op']


def _neighbors(slot):
    if type(slot) is not int or slot not in (1, 2):
        raise ValueError('Lever edge slot has no proved two-sided/wrap rule')
    permutation = list(range(4))
    permutation[slot - 1], permutation[slot + 1] = permutation[slot + 1], permutation[slot - 1]
    return permutation


def _check_exchange(state, actor, opponent):
    from lab import dynamic_skills as dynamic
    if actor.get('charge') is not None:
        raise ValueError('A different selected skill cannot exchange a pending caster charge')
    for member in (actor, opponent):
        if member['hp'] <= 0:
            raise ValueError('Whole-bundle exchange requires two living participants')
        if any(sid in locked_skill_ids() for sid in member['skill_slots']):
            raise ValueError('Cross-member exchange with position locks is not source-resolved')
        if member.get('skill_modifiers') or member.get('pending_modifiers'):
            raise ValueError('Skill-cost modifier transfer/cleanup during exchange is unresolved')
        if member.get('skill_history'):
            from lab.skill_history_runtime import has_armed_listener
            if has_armed_listener(member):
                raise ValueError('Use-installed round listener ownership during bundle exchange is unresolved')
        defense = member.get('defense_runtime')
        if defense and defense.get('cooldown_through_turn', state['turn']) >= state['turn']:
            raise ValueError('Live shared-defense/cooldown transfer during exchange is unresolved')
    snapshot = deepcopy(state)
    dynamic.initialize_dynamic_skills(snapshot, seed=snapshot.get('dynamic_skills', {}).get('prng', {}).get('seed', 0))
    dynamic._validate_root(snapshot)


def preflight_selection(catalog, state, side, action, *, context):
    prepared = prepare_rules(catalog)
    op = _program(prepared, action['program'], context)
    actor, other = _active(state, side), 'b' if side == 'a' else 'a'
    if state.get('snapshot_id') != prepared.snapshot_id or actor['member_id'] != action['actor_member_id']:
        raise ValueError('Slot selection actor/snapshot changed')
    if op == 'position.swap_neighbors':
        slot = action['slot']
        permutation = _neighbors(slot)
        if actor['skill_slots'][slot] != action['skill_id']:
            raise ValueError('Position-dependent selected skill no longer occupies its declared slot')
        moved = {**actor, 'skill_slots': [actor['skill_slots'][old] for old in permutation]}
        validate_slot_permutation(moved, permutation)
    elif op == 'bundle.swap_opponent':
        _check_exchange(state, actor, _active(state, other))
    binding = {'policy': POLICY, 'config_sha256': CONFIG_SHA256, 'turn': state['turn'],
        'side': side, 'actor_member_id': actor['member_id'], 'opponent_member_id': _active(state, other)['member_id'],
        'skill_id': action['skill_id'], 'slot': action['slot'], 'source_hash': action['program']['source_hash'], 'op': op}
    binding['binding_hash'] = fingerprint(binding)
    return binding


def after_skill(catalog, state, side, action, *, event_token, context):
    """Mutate owned full state after normal prefix and transformation return."""
    from lab import dynamic_skills as dynamic
    prepared = prepare_rules(catalog)
    op = _program(prepared, action['program'], context)
    if op == 'position.lock':
        return []
    binding = context.get('_slot_selection_binding')
    if (not isinstance(binding, dict) or binding.get('binding_hash') != fingerprint({k: v for k, v in binding.items() if k != 'binding_hash'})
            or binding.get('policy') != POLICY or binding.get('config_sha256') != CONFIG_SHA256
            or binding.get('side') != side or binding.get('actor_member_id') != action['actor_member_id']
            or binding.get('skill_id') != action['skill_id'] or binding.get('slot') != action['slot']
            or binding.get('turn') != state['turn'] or binding.get('source_hash') != action['program']['source_hash']
            or binding.get('op') != op or not isinstance(event_token, str) or not event_token):
        raise ValueError('Slot after-action requires the intact pre-payment selection binding')
    ledger = state.get('slot_runtime', {'policy': POLICY, 'applied_tokens': {}})
    if ledger.get('policy') != POLICY or not isinstance(ledger.get('applied_tokens'), dict):
        raise ValueError('Malformed slot-action replay ledger')
    if event_token in ledger['applied_tokens']:
        if ledger['applied_tokens'][event_token] != binding['binding_hash']:
            raise ValueError('Slot action token reused for a different selected action')
        return []
    current, events = deepcopy(state), []
    actor, other = _active(current, side), 'b' if side == 'a' else 'a'
    opponent = _active(current, other)
    if actor['member_id'] != binding['actor_member_id'] or opponent['member_id'] != binding['opponent_member_id']:
        raise ValueError('Slot participants changed before the source-owned follow-up')
    if op == 'position.swap_neighbors':
        permutation = _neighbors(binding['slot'])
        before = list(actor['skill_slots'])
        actor['skill_slots'] = [before[old] for old in permutation]
        events.extend(dynamic.remap_member_slots(actor, permutation, turn=current['turn'], event_token=event_token))
        events.append({'op': 'slot.neighbors_swapped', 'side': side, 'member_id': actor['member_id'],
            'source_slot': binding['slot'], 'before': before, 'after': list(actor['skill_slots']), 'permutation': permutation})
    elif op == 'bundle.swap_opponent':
        _check_exchange(current, actor, opponent)
        dynamic.initialize_dynamic_skills(current, seed=current.get('dynamic_skills', {}).get('prng', {}).get('seed', 0))
        if opponent.get('charge') is not None:
            events.append({'op': 'slot.charge_cancelled', 'side': other, 'member_id': opponent['member_id'],
                'before_charge': deepcopy(opponent['charge']), 'cleanup_effect_id': 1004076})
            opponent['charge'] = None
        snapshots = [deepcopy(actor), deepcopy(opponent)]
        fields = ('skill_slots', 'carried_slot_order', 'dynamic_skill_origins', 'transformation_skill_origins', 'skill_history')
        transfer = {'policy': POLICY, 'turn': current['turn'], 'source_skill_id': action['skill_id'],
                    'source_hash': action['program']['source_hash'], 'event_token': event_token}
        for receiver, donor in ((actor, snapshots[1]), (opponent, snapshots[0])):
            before = list(receiver['skill_slots'])
            for field in fields:
                receiver.pop(field, None)
                if field in donor:
                    receiver[field] = deepcopy(donor[field])
            receiver['carried_slot_owner'] = dynamic.carried_slot_owner(donor)
            dynamic.remap_member_slots(receiver, [0, 1, 2, 3],
                previous_member_id=donor['member_id'], transfer_source=transfer)
            events.append({'op': 'slot.bundle_swapped', 'member_id': receiver['member_id'],
                'from_member_id': donor['member_id'], 'original_bundle_owner': receiver['carried_slot_owner'],
                'before': before, 'after': list(receiver['skill_slots'])})
        dynamic._validate_root(current)
    if 'dynamic_skills' in current:
        dynamic._validate_root(current)
    current['slot_runtime'] = {**deepcopy(ledger), 'applied_tokens': {**ledger['applied_tokens'], event_token: binding['binding_hash']}}
    state.clear(); state.update(current)
    return [{**event, 'source_skill_id': action['skill_id'], 'source_hash': action['program']['source_hash'],
        'slot_policy': POLICY, 'slot_policies': deepcopy(POLICIES), 'event_token': event_token} for event in events]
