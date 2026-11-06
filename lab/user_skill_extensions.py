"""Reviewed conditional effects; unresolved multicast/random clauses stay blocked."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from fractions import Fraction

from lab.ruleset import canonical_hash

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'data/rules/reviewed-user-skill-extensions-1.json'
POLICY = 'source_bound_conditional_damage_with_explicit_unresolved_releases_v1'


@lru_cache(maxsize=16)
def _hash_file(path, size, stamp):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@lru_cache(maxsize=2)
def _configuration(stamp):
    data = json.loads(CONFIG.read_text(encoding='utf-8'))
    if data.get('schema') != 'reviewed-user-skill-extensions-1' or data.get('policy') != POLICY:
        raise ValueError('Unknown skill extension configuration')
    return data


def rules():
    data = _configuration(CONFIG.stat().st_mtime_ns)
    for source in data['sources']:
        path = (ROOT / source['path']).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError('Skill evidence path escaped project')
        stat = path.stat()
        if _hash_file(str(path), stat.st_size, stat.st_mtime_ns) != source['sha256']:
            raise ValueError('Skill extension original table evidence changed')
    return deepcopy(data)


def programs(prepared):
    data = rules()
    if prepared.snapshot_id != data['snapshot_id']:
        raise ValueError('Skill extension snapshot changed')
    if next(t for t in prepared._rules._catalog['glossary'] if t['key'] == 3015) != data['term']:
        raise ValueError('Mixed-blood source term changed')
    out = {}
    for key, row in data['skills'].items():
        if canonical_hash(prepared._rules.skill(int(key))) != row['record_hash']:
            raise ValueError('Skill extension whole record changed')
        if row['status'] not in ('reviewed', 'reviewed_repeat_driver_required', 'reviewed_conditional_mark', 'reviewed_per_type_power'):
            continue
        record = row['raw']
        program = deepcopy(prepared._rules.program(int(key)))
        program.pop('native_rule', None)
        program.update(status='compiled', blockers=[], execution_blockers=[], operations=[])
        if record['kind'] in ('physical', 'magical', 'higher'):
            program['operations'] = [{'op': 'damage', 'params': {'target': 'opponent', 'kind': record['kind'],
                         'type': record['type'], 'power': record['power']}}]
        if row['status'] == 'reviewed_per_type_power':
            program.update(per_type_power_components=deepcopy(row['components']), per_type_power_config_hash=canonical_hash(data))
        elif row['status'] == 'reviewed_repeat_driver_required':
            program.update(repeat_cast_components=deepcopy(row['components']), repeat_cast_config_hash=canonical_hash(data))
        elif row['status'] == 'reviewed_conditional_mark':
            program.update(conditional_mark_components=deepcopy(row['components']),
                           conditional_mark_config_hash=canonical_hash(data))
        else:
            program.update(conditional_damage_components=deepcopy(row['components']),
                           conditional_damage_config_hash=canonical_hash(data))
        out[int(key)] = program
    return out


def _conditional_mark_row(program):
    data = rules()
    row = data['skills'].get(str(program.get('game_id')))
    if (not row or row['status'] != 'reviewed_conditional_mark' or program.get('source_hash') != row['record_hash']
            or program.get('conditional_mark_components') != row['components']
            or program.get('conditional_mark_config_hash') != canonical_hash(data)):
        raise ValueError('Conditional mark whole source or components changed')
    return row


def _previous_turn_type(state, context, skill_type):
    turn = context.get('turn')
    if type(turn) is not int or turn < 1:
        raise ValueError('Previous-turn condition requires the actual battle round')
    if turn == 1:
        return False
    history = state['self'].get('battle_skill_history')
    if not isinstance(history, list):
        raise ValueError('Previous-turn condition requires complete owned team skill history')
    for event in history:
        if (not isinstance(event, dict) or type(event.get('turn')) is not int
                or not isinstance(event.get('effective_type'), str)
                or event.get('hash') != canonical_hash({k: v for k, v in event.items() if k != 'hash'})):
            raise ValueError('Previous-turn committed skill type/source record changed')
    return any(event['turn'] == turn - 1 and event['effective_type'] == skill_type for event in history)


def preflight_conditional_mark(program, state, context, damage_resolver=None):
    from lab.skill_execution import preflight_skill
    row = _conditional_mark_row(program)
    for component in row['components']:
        if component['condition'] != 'previous_turn.any_team_skill_type':
            raise ValueError('Unknown reviewed conditional-mark predicate')
        _previous_turn_type(state, context, component['type'])
    preflight_skill(program, state, context, damage_resolver)


def execute_conditional_mark(program, state, context, damage_resolver=None):
    from lab.skill_execution import execute_skill
    from lab.mark_runtime import change_marks
    preflight_conditional_mark(program, state, context, damage_resolver)
    row = _conditional_mark_row(program)
    selected = [component for component in row['components']
                if _previous_turn_type(state, context, component['type'])]
    result = execute_skill(program, state, context, damage_resolver=damage_resolver)
    if result['status'] != 'applied':
        return result
    for component in selected:
        actor = result['state'][component['target']]
        actor['field_marks'], events = change_marks(actor['field_marks'], component['mark_id'], component['layers'],
            context=context, source={'skill_id': program['game_id'], 'source_hash': program['source_hash'],
                                     'condition': deepcopy(component), 'condition_turn': context['turn'] - 1})
        result['events'].extend({**event, 'target': component['target']} for event in events)
    return result


def _per_type_row(program):
    data = rules()
    row = data['skills'].get(str(program.get('game_id')))
    if (not row or row['status'] != 'reviewed_per_type_power' or row['record_hash'] != program.get('source_hash')
            or program.get('per_type_power_components') != row['components']
            or program.get('per_type_power_config_hash') != canonical_hash(data)):
        raise ValueError('Per-type power source or components changed')
    return row


def _per_type_candidates(member, component, context):
    from lab.live_damage import _rules
    from lab.weather_runtime import resolved_skill_type
    groups = {}
    for slot, sid in enumerate(member['skill_slots']):
        if not sid:
            continue
        skill = _rules()[1].skill(sid)
        if skill['kind'] in component['candidate_kind']:
            kind = resolved_skill_type(context.get('weather'), sid, skill['type'])
            groups.setdefault(kind, []).append((slot, sid))
    return groups


def preflight_per_type_power(program, state, context, damage_resolver=None):
    from lab.effect_runtime import _preflight_header, _integer
    from lab.skill_history_runtime import validate_member
    _preflight_header(program, state, context)
    row = _per_type_row(program)
    _integer(context.get('random_devotion_seed'), 'per-type selection episode seed')
    validate_member(state['self'])
    casts = state['self'].get('per_type_power_casts', 0)
    history = state['self'].get('per_type_power_cast_history', [])
    if type(casts) is not int or casts < 0 or not isinstance(history, list) or len(history) != casts:
        raise ValueError('Per-type power use count has no matching source history')
    for event in history:
        if (event.get('source_hash') != row['record_hash'] or event.get('policy') != POLICY
                or event.get('record_hash') != canonical_hash({k: v for k, v in event.items() if k != 'record_hash'})):
            raise ValueError('Per-type power use history changed')
    if casts >= row['components'][0]['cap']:
        raise ValueError('Per-type selection at the installed 99-use BUFF cap needs a verified boundary rule')
    _per_type_candidates(state['self'], row['components'][0], context)


def execute_per_type_power(program, state, context, damage_resolver=None):
    """Select once on this successful cast; grants live in transferable skill identities."""
    preflight_per_type_power(program, state, context)
    row = _per_type_row(program)
    current, events = deepcopy(state), []
    actor = current['self']
    cost = context.get('resolved_energy_cost')
    if type(cost) is not int or not 0 <= cost <= actor['energy']:
        raise ValueError('Per-type power requires its exact actual energy payment')
    if actor.get('per_type_power_casts', 0) >= row['components'][0]['cap']:
        raise ValueError('Per-type selection at the installed 99-use BUFF cap needs a verified boundary rule')
    actor['energy'] -= cost
    events.append({'op': 'energy.pay', 'target': 'self', 'amount': cost})
    seed = int(canonical_hash({'namespace': 'per_type_power', 'seed': context['random_devotion_seed'],
                             'member_id': actor['member_id']}), 16)
    cursor = actor.setdefault('per_type_power_prng', {'seed': seed, 'counter': 0, 'policy': POLICY})
    if (cursor.get('seed') != seed or cursor.get('policy') != POLICY
            or type(cursor.get('counter')) is not int or cursor['counter'] < 0):
        raise ValueError('Per-type power selection source/cursor changed')
    from lab.dynamic_skills import _draw
    from lab.skill_history_runtime import _row
    for skill_type, pool in _per_type_candidates(actor, row['components'][0], context).items():
        slot, sid = pool[_draw(cursor, len(pool))]
        identity = _row(actor, slot, create=True)
        grant = {'source_skill_id': program['game_id'], 'source_hash': program['source_hash'],
            'source_actor_member_id': actor['member_id'], 'skill_id': sid,
            'original_owner': identity['original_owner'], 'original_slot': identity['original_slot'],
            'amount': row['components'][0]['amount'], 'selected_type': skill_type,
            'applied_turn': context['turn'], 'draw_counter': cursor['counter'], 'policy': POLICY}
        grant['record_hash'] = canonical_hash(grant)
        identity.setdefault('per_type_power_grants', []).append(grant)
        identity['record_hash'] = canonical_hash({k: v for k, v in identity.items() if k != 'record_hash'})
        events.append({'op': 'skill.power_selected', 'target': 'self', 'selected_slot': slot, **deepcopy(grant)})
    actor['per_type_power_casts'] = actor.get('per_type_power_casts', 0) + 1
    record = {'source_hash': program['source_hash'], 'turn': context['turn'],
              'draw_counter': cursor['counter'], 'policy': POLICY,
              'selection': [event['record_hash'] for event in events if event['op'] == 'skill.power_selected']}
    record['record_hash'] = canonical_hash(record)
    actor.setdefault('per_type_power_cast_history', []).append(record)
    return {'status': 'applied', 'state': current, 'events': events, 'blockers': [],
            'training_eligible': False, 'calibrated': False, 'real_game_verified': False}


def _power_grants(member):
    from lab.skill_history_runtime import validate_member
    validate_member(member)
    source = rules()['skills']['7060140']['record_hash']
    for identity in member.get('skill_history', {}).values():
        for grant in identity.get('per_type_power_grants', []):
            if (grant.get('policy') != POLICY or grant.get('source_skill_id') != 7060140
                    or grant.get('source_hash') != source or grant.get('amount') != 35
                    or grant.get('original_owner') != identity['original_owner']
                    or grant.get('original_slot') != identity['original_slot']
                    or grant.get('record_hash') != canonical_hash({k: v for k, v in grant.items() if k != 'record_hash'})):
                raise ValueError('Per-type skill identity/grant source changed')
            yield identity['slot'], grant


def bound_skill_power(member, skill_id, slot, value):
    if not any(row.get('per_type_power_grants') for row in member.get('skill_history', {}).values()):
        return value
    from lab.battle_data import canonical_skill
    skill_id = canonical_skill(skill_id).get('skill_id', skill_id)
    grants = list(_power_grants(member))
    if not grants:
        return value
    if type(slot) is not int or not 0 <= slot < 4:
        raise ValueError('Frozen per-type power needs the actual selected original skill slot')
    return value + sum(grant['amount'] for position, grant in grants
                       if position == slot and grant['skill_id'] == skill_id)


def clear_per_type_power(state, departing_member_id):
    """The source BUFF clears on its holder's departure, including moved skill grants."""
    events = []
    for team in state['teams'].values():
        for member in team['members']:
            list(_power_grants(member))
            for identity in member.get('skill_history', {}).values():
                old = identity.get('per_type_power_grants', [])
                kept = [grant for grant in old if grant['source_actor_member_id'] != departing_member_id]
                if len(kept) != len(old):
                    identity['per_type_power_grants'] = kept
                    identity['record_hash'] = canonical_hash({k: v for k, v in identity.items() if k != 'record_hash'})
                    events.append({'op': 'skill.power_selected_cleared', 'target_member_id': member['member_id'],
                                   'source_actor_member_id': departing_member_id, 'removed': len(old) - len(kept)})
            if member['member_id'] == departing_member_id:
                member.pop('per_type_power_casts', None)
                member.pop('per_type_power_cast_history', None)
    return events


def resolve_program(program, state, context):
    if program.get('repeat_cast_components'):
        row = rules()['skills'].get(str(program.get('game_id')))
        phase = context.get('repeat_cast_phase')
        if (not row or row['record_hash'] != program.get('source_hash')
                or row['components'] != program['repeat_cast_components']
                or program.get('repeat_cast_config_hash') != canonical_hash(rules())):
            raise ValueError('Repeat-cast whole source changed')
        if (not isinstance(phase, dict) or phase.get('policy') != POLICY
                or type(phase.get('release_index')) is not int or type(phase.get('release_count')) is not int
                or not 0 <= phase['release_index'] < phase['release_count'] <= 11):
            raise ValueError('Repeated releases require the full per-release payment/hook driver')
        return program
    if not program.get('conditional_damage_components'):
        return program
    data = rules()
    row = data['skills'].get(str(program.get('game_id')))
    if (not row or row['status'] != 'reviewed' or program.get('source_hash') != row['record_hash']
            or program['conditional_damage_components'] != row['components']
            or program.get('conditional_damage_config_hash') != canonical_hash(data)):
        raise ValueError('Conditional damage source or component changed')
    from lab.trait_runtime import bloodline_relation
    out = deepcopy(program)
    for component in row['components']:
        if component['op'] != 'damage.multiply' or component['condition'] != 'opponent.mixed_blood':
            raise ValueError('Unknown reviewed conditional damage component')
        mixed = bloodline_relation(state['opponent'])['mixed']
        if mixed:
            n, d = component['factor']
            out['operations'][0]['params']['damage_multiplier'] = {'numerator': n, 'denominator': d}
    return out


def initialize_repeats(state):
    """Initialize only for a fresh full battle; never reconstruct unobserved history."""
    source = rules()['skills']['7110380']['record_hash']
    if state.get('turn') not in (0, 1) and any('repeat_cast_history' not in m
            for t in state['teams'].values() for m in t['members']):
        raise ValueError('Cannot initialize complete repeat history in a battle already in progress')
    for team in state['teams'].values():
        for member in team['members']:
            if 'repeat_cast_history' in member:
                continue
            member['repeat_cast_history'] = {'policy': POLICY, 'source_hash': source,
                'history_complete': True, 'departures': [], 'releases': []}


def _repeat_history(member):
    row = member.get('repeat_cast_history')
    if (not isinstance(row, dict) or row.get('policy') != POLICY or row.get('history_complete') is not True
            or row.get('source_hash') != rules()['skills']['7110380']['record_hash']
            or not isinstance(row.get('departures'), list) or not isinstance(row.get('releases'), list)):
        raise ValueError('Repeated releases need complete source-owned departure history')
    events = [(kind, event) for kind in ('departures', 'releases') for event in row[kind]]
    indices = []
    tokens = set()
    for kind, event in events:
        if (not isinstance(event, dict) or event.get('source_hash') != row['source_hash']
                or type(event.get('sequence')) is not int or type(event.get('turn')) is not int
                or not isinstance(event.get('token'), str) or not event['token']
                or event['token'] in tokens or event.get('record_hash') != canonical_hash({
                    k: value for k, value in event.items() if k != 'record_hash'})):
            raise ValueError('Repeat history source, event sequence or digest changed')
        if kind == 'departures' and (type(event.get('carried')) is not bool
                or type(event.get('after_first_release')) is not bool):
            raise ValueError('Repeat departure must retain its exact carried/use snapshot')
        tokens.add(event['token']); indices.append(event['sequence'])
    if sorted(indices) != list(range(len(events))):
        raise ValueError('Repeat history has missing or duplicate sequence records')
    for event in row['departures']:
        expected = any(release['sequence'] < event['sequence'] for release in row['releases'])
        if event['after_first_release'] != expected:
            raise ValueError('Repeat first-use history was altered')
    return row


def repeat_departure(member, *, turn, token):
    row = _repeat_history(member)
    if type(turn) is not int or turn < 0 or not isinstance(token, str) or not token:
        raise ValueError('Repeat growth needs the actual source-owned departure token')
    if any(event['token'] == token for event in row['departures']):
        return []
    if any(event['token'] == token for event in row['releases']):
        raise ValueError('Repeat token reused across departure/release phases')
    event = {'token': token, 'turn': turn, 'carried': 7110380 in member['skill_slots'],
             'after_first_release': bool(row['releases']), 'source_hash': row['source_hash'],
             'sequence': len(row['departures']) + len(row['releases'])}
    event['record_hash'] = canonical_hash(event)
    row['departures'].append(event)
    return [{'op': 'skill.repeat_departure', 'target_member_id': member['member_id'], **deepcopy(event)}]


def repeat_release(member, *, turn, token):
    row = _repeat_history(member)
    if type(turn) is not int or turn < 0 or not isinstance(token, str) or not token:
        raise ValueError('Repeat release needs an actual unique execution token')
    if any(event['token'] == token for event in row['releases'] + row['departures']):
        raise ValueError('Repeat release token already committed')
    event = {'token': token, 'turn': turn, 'source_hash': row['source_hash'],
             'sequence': len(row['departures']) + len(row['releases'])}
    event['record_hash'] = canonical_hash(event)
    row['releases'].append(event)
    return [{'op': 'skill.repeat_release', 'target_member_id': member['member_id'], **deepcopy(event)}]


def repeat_count(member):
    row = _repeat_history(member)
    departures = [event for event in row['departures'] if event['carried']]
    return 1 + min(10, len(departures))


def _random_row(program):
    row = rules()['skills'].get(str(program.get('game_id')))
    if (not row or row['status'] != 'reviewed_composite'
            or row['record_hash'] != program.get('source_hash')
            or program.get('transformation_components', {}).get('random_stat_components') != row['components']):
        raise ValueError('Random-stat whole skill/source differs from its reviewed composite')
    return row


def _buff_layers(member, spec):
    """Count the exact same source BUFF; unrelated trait/mark modifiers are excluded."""
    if spec['flat']:
        records = [r for r in member.get('mechanism_flat_modifiers', [])
                   if r.get('op') == 'speed.flat' and r.get('buff_id') == spec['buff_id']]
        from lab.modifier_ledger import flat_info
        for record in records:
            flat_info(record, 'mechanism_flat_modifiers')
        total = sum(r['amount'] for r in records)
    else:
        terms = member.get('stat_modifiers', {}).get(spec['stat'], [])
        records = {r['index']: r for r in member.get('stat_modifier_sources', {}).get(spec['stat'], [])}
        total = Fraction(0)
        for index, term in enumerate(terms):
            amount = Fraction(**term)
            if amount <= 0:
                continue
            record = records.get(index)
            if record is None or record.get('term') != term:
                raise ValueError('Random-stat cap cannot classify an unsourced positive stat term')
            from lab.modifier_ledger import POLICY as ledger_policy, _verify_stat_record
            if record.get('policy') != ledger_policy:
                raise ValueError('Random-stat cap source ledger version changed')
            if record.get('source_kind') == 'skill' or 'buff_id' in record:
                _verify_stat_record(spec['stat'], record)
            classification = record.get('classification', {})
            if record.get('buff_id') == spec['buff_id'] or spec['buff_id'] in classification.get('buff_ids', []):
                total += amount
            elif classification.get('category') == 'unknown':
                raise ValueError('Random-stat cap cannot classify this legacy positive BUFF')
    layers = Fraction(total) / Fraction(*spec['unit'])
    if layers.denominator != 1 or layers < 0 or layers > spec['cap']:
        raise ValueError('Random-stat same-BUFF layer count exceeds its reviewed source')
    return layers.numerator


def preflight_random(program, state, context):
    from lab.effect_runtime import _preflight_header, _integer
    _preflight_header(program, state, context)
    row = _random_row(program)
    _integer(context.get('random_devotion_seed'), 'episode random-stat seed')
    for spec in row['random_pool']:
        _buff_layers(state['self'], spec)
    cursor = state['self'].get('random_stat_prng')
    if cursor is not None:
        expected = int(canonical_hash({'namespace': 'random_stats', 'seed': context['random_devotion_seed'],
                                     'member_id': state['self']['member_id']}), 16)
        if (not isinstance(cursor, dict) or cursor.get('seed') != expected
                or cursor.get('policy') != POLICY or type(cursor.get('counter')) is not int or cursor['counter'] < 0):
            raise ValueError('Random-stat episode source/cursor changed')


def execute_random(program, state, context):
    result = {'status': 'blocked', 'state': deepcopy(state), 'events': [], 'blockers': [],
              'training_eligible': False, 'calibrated': False, 'real_game_verified': False}
    try:
        preflight_random(program, state, context)
        row = _random_row(program)
        current, events = deepcopy(state), []
        actor = current['self']
        cost = context.get('resolved_energy_cost', 0)
        if type(cost) is not int or not 0 <= cost <= actor['energy']:
            raise ValueError('Random-stat skill needs its resolved actual energy payment')
        actor['energy'] -= cost
        events.append({'op': 'energy.pay', 'target': 'self', 'amount': cost})
        cursor = actor.setdefault('random_stat_prng', {'seed': int(canonical_hash({
            'namespace': 'random_stats', 'seed': context['random_devotion_seed'], 'member_id': actor['member_id']}), 16),
            'counter': 0, 'policy': POLICY})
        from lab.dynamic_skills import _draw
        from lab.modifier_ledger import enhance_buff_amount, register_stat
        from lab.mechanism_runtime import POLICY as modifier_policy
        for _ in range(row['components'][0]['count']):
            counter = cursor['counter']
            index = _draw(cursor, len(row['random_pool']))
            spec = row['random_pool'][index]
            before = _buff_layers(actor, spec)
            requested = enhance_buff_amount(actor, spec['buff_id'],
                'speed.flat' if spec['flat'] else spec['stat'], Fraction(*spec['unit'])) / Fraction(*spec['unit'])
            if requested.denominator != 1 or requested < 1:
                raise ValueError('Random-stat layer enhancement must remain positive integral layers')
            applied = min(requested.numerator, max(0, spec['cap'] - before))
            if applied:
                amount = Fraction(*spec['unit']) * applied
                if spec['flat']:
                    actor.setdefault('mechanism_flat_modifiers', []).append({'op': 'speed.flat',
                        'amount': amount.numerator, 'buff_id': spec['buff_id'], 'policy': modifier_policy,
                        'source_skill_id': program['game_id'], 'source_hash': program['source_hash']})
                else:
                    actor.setdefault('stat_modifiers', {}).setdefault(spec['stat'], []).append({
                        'numerator': amount.numerator, 'denominator': amount.denominator})
                    register_stat(actor, spec['stat'], source_kind='skill', source_id=program['game_id'],
                                  source_hash=program['source_hash'], buff_id=spec['buff_id'])
            event = {'op': 'stat.random_gain', 'target': 'self', 'draw_index': counter,
                'pool_index': index, 'buff_id': spec['buff_id'], 'stat': spec['stat'], 'before_layers': before,
                'applied_layers': applied, 'wasted_layers': requested.numerator - applied,
                'source_skill_id': program['game_id'], 'source_hash': program['source_hash'],
                'policy': POLICY, 'sampling_source': 'user_confirmation_20261030'}
            actor.setdefault('random_stat_sources', []).append(deepcopy(event))
            events.append(event)
        result.update(status='applied', state=current, events=events)
    except (ValueError, KeyError, TypeError) as exc:
        result['blockers'] = [str(exc)]
    return result


def native_per_type_power_bounds(pet):
    """A captured BUFF proves its layers, not the hidden random skill selections."""
    count = 0
    for buff in pet.get('battleBuffs', pet.get('buffs', [])) or []:
        if str(buff.get('id')) != '20640130':
            continue
        layers = buff.get('layers')
        if type(layers) is not int or not 0 <= layers <= 99:
            raise ValueError('Captured diffuse-reflection layers are not exactly known')
        count += layers
    return 0, 35 * count
