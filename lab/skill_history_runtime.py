"""Replayable per-original-slot skill growth and proof-gated kill rewards."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from fractions import Fraction

from lab.action_outcome_runtime import validate_direct_defeat
from lab.effect_runtime import execute_effects, HOOKS
from lab.game_runtime_defaults import ROOT
from lab.phase_config import fingerprint
from lab.prepared_rules import prepare_rules
from lab.trait_runtime import cached_source_query

CONFIG = ROOT / 'data/rules/reviewed-skill-history-1.json'
CONFIG_SHA256 = 'c9b0cfdf38dc75b0931c7b73e3bcc4b88b1a631f1f5942dbbe7cd25d79ea7e9b'
POLICY = 'source_bound_original_slot_skill_history_after_committed_events_v1'
POLICIES = {'identity': 'original_bundle_owner_and_original_slot_with_per_skill_history',
    'after_use': 'committed_successful_skill_once_before_future_uses',
    'entry': 'owned_entry_including_initial_carried_skill_occurrences',
    'round_end': 'use_installs_one_active_listener_clear_on_departure_keep_permanent_growth',
    'kill': 'same_committed_skill_direct_defeat_proof_only',
    'power': 'intrinsic_history_before_other_power_modifiers',
    'carried': 'observe_only_events_committed_while_currently_carried_no_retroactive_import',
    'first_action': 'top_level_committed_action_only_after_commit_swift_subactions_excluded',
    'reset': 'after_source_skill_commits_clear_its_observed_power_additions',
    'cost': 'intrinsic_history_before_external_cost_modifiers_floor_zero',
    'received': 'one_completed_direct_attack_packet_including_zero_loss_not_per_hit',
    'resistance': 'explicit_combination_zero_to_one_resistance_unless_attack_ignores_resistance_zero_immunity_excluded',
    'previous_turn': 'own_recorded_committed_attacks_only_absence_in_fresh_simulation_counts_none',
    'type_set': 'distinct_recorded_effective_types_except_catalog_own_type_once_while_carried',
    'choice': 'same_skill_history_preserved_across_branches_growth_only_selected_branch_after_commit',
    'position': 'use_installed_listener_any_actual_number_change_once_per_turn_clear_on_departure',
    'conditional_swift': 'previous_round_committed_effective_type_any_current_roster_member_both_sides',
    'generation': 'history_retained_per_original_slot_and_skill_id_experiment'}


@lru_cache(maxsize=2)
def _configuration(stamp):
    raw = CONFIG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONFIG_SHA256:
        raise ValueError('Skill history configuration changed; source review required')
    return json.loads(raw)


@lru_cache(maxsize=16)
def _source_hash(path, size, stamp):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@cached_source_query
def _data():
    data = _configuration(CONFIG.stat().st_mtime_ns)
    for relative, expected in data['sources'].items():
        path = (ROOT / relative).resolve()
        stat = path.stat()
        if not path.is_relative_to(ROOT) or _source_hash(str(path), stat.st_size, stat.st_mtime_ns) != expected:
            raise ValueError('Skill history extracted source changed')
    return data


def research_context():
    return {'skill_history_policy': POLICY, 'skill_history_policies': deepcopy(POLICIES)}


def _context(context):
    if context.get('skill_history_policy') != POLICY or context.get('skill_history_policies') != POLICIES:
        raise ValueError('Explicit skill history timing/identity policies required')


def _prepared(catalog):
    prepared, config = prepare_rules(catalog), _data()
    if prepared.snapshot_id != config['snapshot_id']:
        raise ValueError('Skill history snapshot differs')
    for key, row in config['skills'].items():
        if fingerprint(prepared._rules.skill(int(key))) != row['record_hash']:
            raise ValueError('Skill history whole source changed')
    return prepared


def programs(catalog):
    prepared, out = _prepared(catalog), {}
    for key, row in _data()['skills'].items():
        record = row['record']
        program = deepcopy(prepared._rules.program(int(key)))
        program.pop('native_rule', None)
        program.update(status='compiled', blockers=[], operations=[{'op': 'damage.sequence' if row.get('base_hits') else 'damage', 'params': {
            'target': 'opponent', 'kind': record['kind'], 'power': record['power'], 'type': record['type'],
            **({'hits': row['base_hits']} if row.get('base_hits') else {})}}],
            skill_history_components=deepcopy(row['components']), skill_history_evidence=deepcopy(row),
            skill_history_config_hash=CONFIG_SHA256, skill_history_policies=deepcopy(POLICIES),
            response_kinds=[], executable=False, real_game_verified=False, training_eligible=False)
        if row.get('base_hits'):
            program['dependency_ids'] = sorted(set(program['dependency_ids']) | {3005})
        if row.get('choice_history'):
            from lab.choice_runtime import choice_programs
            selected = choice_programs(prepared)[int(key)]
            program = {**selected, **{k:v for k,v in program.items() if k.startswith('skill_history_')}}
            if row.get('base_hits'):
                program['dependency_ids'] = sorted(set(program['dependency_ids']) | {3005})
        if row.get('conditional_swift'):
            program['conditional_swift_components'] = deepcopy(row['conditional_swift'])
            program['dependency_ids'] = sorted(set(program['dependency_ids']) | {1005})
        out[int(key)] = program
    return out


def _members(state):
    return [m for team in state['teams'].values() for m in team['members']]


def _active(state, side):
    team = state['teams'][side]
    return team['members'][team['active_slot']]


def _row(member, slot, *, create=False):
    from lab.dynamic_skills import carried_slot_owner, carried_slot_order
    rows = member.setdefault('skill_history', {}) if create else member.get('skill_history', {})
    key = str(slot)
    if key not in rows and create:
        row = {'policy': POLICY, 'config_sha256': CONFIG_SHA256, 'member_id': member['member_id'],
            'slot': slot, 'original_owner': carried_slot_owner(member),
            'original_slot': carried_slot_order(member)[slot], 'events': []}
        row['record_hash'] = fingerprint(row)
        rows[key] = row
    return rows.get(key)


@lru_cache(maxsize=2)
def _observed_sources(stamp):
    config = _data()
    path = next(ROOT / p for p in config['sources'] if p.startswith('data/bwiki/') and p.endswith('/catalog.json'))
    catalog = json.loads(path.read_text(encoding='utf8'))
    return {int(k): {'source_hash': fingerprint(row), 'kind': row['kind']} for k, row in catalog['moves'].items()}


def _observed_source_matches(row):
    expected = _observed_sources(CONFIG.stat().st_mtime_ns).get(row.get('skill_id'))
    if expected is not None:
        return expected == {'source_hash': row.get('source_hash'), 'kind': row.get('kind')}
    from lab.core_magic_runtime import reviewed_wish_skill
    wish = reviewed_wish_skill(row.get('skill_id'))
    return (wish is not None and row.get('source_hash') == fingerprint(wish)
            and row.get('kind') in ('physical', 'magical'))


def _validate_observation(observation):
    from lab.action_outcome_runtime import committed_history
    if (not isinstance(observation, dict) or observation.get('kind') not in ('skill', 'switch', 'recharge', 'charge_setup')
            or type(observation.get('turn')) is not int or observation['turn'] < 1
            or not isinstance(observation.get('actor_member_id'), str)
            or not isinstance(observation.get('token'), str) or not observation['token']
            or type(observation.get('action_is_later')) is not bool
            or observation.get('order_scope') not in ('top_level_action', 'entry_swift_subaction')
            or observation.get('observation_hash') != fingerprint({k: v for k, v in observation.items() if k != 'observation_hash'})):
        raise ValueError('Carried skill observation identity or committed order changed')
    row = observation.get('committed_skill')
    if observation['kind'] == 'skill':
        committed_history({'member_id': observation['actor_member_id'], 'committed_skill_history': [row]})
        if (row['turn'] != observation['turn'] or row['token'] != observation['token']
                or row['member_id'] != observation['actor_member_id']
                or not _observed_source_matches(row)):
            raise ValueError('Carried skill observation belongs to another committed skill')
    elif row is not None:
        raise ValueError('Non-skill observation cannot invent a committed skill')
    return row


def _selected_observation(component, observation):
    row = _validate_observation(observation)
    when = component['when']
    if when == 'carried.response.success':
        return row is not None and row['response_success']
    if when == 'carried.other_type.use':
        return row is not None and row['skill_id'] != component['excluded_skill_id'] and row['effective_type'] == component['type']
    if when == 'carried.distinct_other_type.use':
        return row is not None and row['effective_type'] != component['excluded_type']
    if when == 'carried.action.first':
        return observation['order_scope'] == 'top_level_action' and not observation['action_is_later']
    return False


@lru_cache(maxsize=2)
def _source_rules(stamp):
    from lab.ruleset import BwikiRuleset
    config = _data()
    path = next(ROOT / p for p in config['sources'] if p.startswith('data/bwiki/') and p.endswith('/catalog.json'))
    return BwikiRuleset(json.loads(path.read_text(encoding='utf8')))


def _validate_received(packet):
    if (not isinstance(packet, dict) or packet.get('packet_hash') != fingerprint({k:v for k,v in packet.items() if k != 'packet_hash'})
            or type(packet.get('turn')) is not int or packet['turn'] < 1
            or not isinstance(packet.get('token'), str) or not packet['token']
            or not isinstance(packet.get('events'), list) or not packet['events']):
        raise ValueError('Received-attack history packet changed')
    rules = _source_rules(CONFIG.stat().st_mtime_ns)
    source = rules.skill(packet.get('skill_id'))
    kinds = {source['kind']}
    if source['kind'] == 'higher':
        from lab.core_magic_runtime import reviewed_wish_skill
        if reviewed_wish_skill(packet.get('skill_id')) != source:
            raise ValueError('Received adaptive attack has no reviewed wish source')
        kinds = {'physical', 'magical'}
    if (not kinds <= {'physical', 'magical'} or fingerprint(source) != packet.get('source_hash')
            or packet.get('matchup') != rules.type_multiplier(packet.get('effective_type'), packet.get('target_form_id'))):
        raise ValueError('Received-attack source kind or resistance table changed')
    ignored, resolved_kinds = set(), set()
    for event in packet['events']:
        params = event.get('resolved_params', event.get('params', {}))
        before, after, loss = event.get('before'), event.get('after'), event.get('damage')
        if (event.get('op') not in ('damage', 'damage.hit') or event.get('target') != 'opponent'
                or params.get('kind') not in kinds or params.get('type') != packet['effective_type']
                or any(type(v) is not int for v in (before, after, loss)) or before <= 0 or after < 0
                or loss != before - after or loss < 0):
            raise ValueError('Received-attack growth requires actual completed direct damage events')
        ignore = params.get('ignore_type_resistance', False)
        if type(ignore) is not bool:
            raise ValueError('Received-attack ignore-resistance flag must be explicit boolean')
        ignored.add(ignore)
        resolved_kinds.add(params['kind'])
    if len(ignored) != 1 or len(resolved_kinds) != 1:
        raise ValueError('Mixed ignore-resistance flags need an explicit per-attack aggregation policy')
    ratio = packet['matchup']['multiplier']
    return 0 < Fraction(ratio['numerator'], ratio['denominator']) < 1 and not ignored.pop()


def _validate_previous(previous, turn, actor_member_id):
    from lab.action_outcome_runtime import committed_history
    if (not isinstance(previous, dict) or previous.get('turn') != turn - 1
            or previous.get('hash') != fingerprint({k:v for k,v in previous.items() if k != 'hash'})):
        raise ValueError('Previous-turn history snapshot changed')
    rows = committed_history({'member_id': actor_member_id, 'committed_skill_history': previous.get('rows')})
    if any(r['turn'] != turn - 1 or r['kind'] in ('physical', 'magical') or not _observed_source_matches(r) for r in rows):
        raise ValueError('Previous-turn non-attack condition contradicts committed history')


def _totals(events, skill_id):
    config = _data()
    add, factor, armed, cost_add, hits_add, position_armed, seen_types, tokens, previous_turn = 0, 1, False, 0, 0, False, set(), set(), 0
    position_turns = set()
    for event in events:
        if (not isinstance(event, dict) or event.get('skill_id') != skill_id
                or type(event.get('turn')) is not int or event['turn'] < max(1, previous_turn)
                or not isinstance(event.get('token'), str) or not event['token'] or event['token'] in tokens
                or event.get('source_hash') != config['skills'][str(skill_id)]['record_hash']):
            raise ValueError('Invalid source-bound skill history event')
        tokens.add(event['token']); previous_turn = event['turn']
        phase = event.get('phase')
        if phase not in ('after.use', 'member.enter', 'round.end', 'member.leave', 'direct.defeat', 'carried.action', 'carried.direct.defeat', 'received.attack', 'after.use.no_previous_attack', 'after.use.choice', 'slot.moved'):
            raise ValueError('Unknown skill history phase')
        components = config['skills'][str(skill_id)]['components']
        if phase in ('direct.defeat', 'carried.direct.defeat'):
            proof = event.get('proof')
            validate_direct_defeat(proof)
            if ((phase == 'direct.defeat' and proof['skill_id'] != skill_id) or proof['attacker']['member_id'] != event.get('actor_member_id')
                    or proof['action_token'] != event.get('action_token') or proof['turn'] != event['turn']):
                raise ValueError('Skill history kill proof belongs to a different committed source')
        if phase == 'carried.action':
            observed = event.get('observation')
            _validate_observation(observed)
            if observed['turn'] != event['turn'] or observed['actor_member_id'] != event['actor_member_id']:
                raise ValueError('Carried skill event and observation identity differ')
        if phase == 'received.attack':
            packet = event.get('packet')
            resisted = _validate_received(packet)
            if packet['turn'] != event['turn'] or packet.get('target_member_id') != event['actor_member_id']:
                raise ValueError('Received-attack holder and packet target differ')
        if phase == 'after.use.no_previous_attack':
            _validate_previous(event.get('previous_turn'), event['turn'], event['actor_member_id'])
        if phase == 'member.leave':
            armed, position_armed = False, False
        if phase == 'after.use.choice' and (type(event.get('choice_option')) is not int or event['choice_option'] not in (0,1)):
            raise ValueError('Choice growth requires the committed explicit branch')
        if phase == 'slot.moved':
            movement = event.get('movement')
            if (not position_armed or not isinstance(movement,dict)
                    or movement.get('hash') != fingerprint({k:v for k,v in movement.items() if k != 'hash'})
                    or type(movement.get('from_slot')) is not int or type(movement.get('to_slot')) is not int
                    or not 0 <= movement['from_slot'] < 4 or not 0 <= movement['to_slot'] < 4
                    or movement['from_slot'] == movement['to_slot']
                    or sorted(movement.get('permutation',[])) != [0,1,2,3]
                    or movement['permutation'][movement['to_slot']] != movement['from_slot']):
                raise ValueError('Position growth requires an installed listener and actual slot permutation')
            if event['turn'] in position_turns:
                raise ValueError('Position growth can trigger at most once per original slot and turn')
            position_turns.add(event['turn'])
        for component in components:
            when = {'after.use': 'after.use', 'member.enter': 'member.enter',
                    'round.end': 'round.end.armed', 'direct.defeat': 'this_skill.direct_defeat',
                    'carried.direct.defeat': 'carried.direct_defeat', 'received.attack': 'carried.received_attack',
                    'after.use.no_previous_attack': 'after.use.no_previous_attack', 'after.use.choice':'after.use.choice',
                    'slot.moved':'slot.moved.armed'}.get(phase)
            if not (_selected_observation(component, observed) if phase == 'carried.action' else component['when'] == when):
                continue
            if phase == 'after.use.choice' and component.get('option') != event['choice_option']:
                continue
            if component['when'] == 'carried.distinct_other_type.use':
                actual_type = observed['committed_skill']['effective_type']
                if actual_type in seen_types:
                    continue
                seen_types.add(actual_type)
            if phase == 'received.attack' and component.get('require_resisted') and not resisted:
                continue
            if phase == 'round.end' and not armed:
                raise ValueError('Round growth requires its prior use-installed active listener')
            if component['op'] == 'power.add':
                add += component['amount']
            elif component['op'] == 'power.multiply':
                factor *= component['factor']
            elif component['op'] == 'round_listener.arm':
                armed = True
            elif component['op'] == 'power.reset':
                add, factor = 0, 1
            elif component['op'] == 'cost.add':
                cost_add += component['amount']
            elif component['op'] == 'hits.add':
                hits_add += component['amount']
            elif component['op'] == 'position_listener.arm':
                position_armed = True
    return add, factor, armed, cost_add, hits_add, position_armed


def validate_member(member):
    from lab.dynamic_skills import carried_slot_owner, carried_slot_order
    rows = member.get('skill_history', {})
    if not isinstance(rows, dict):
        raise ValueError('Skill history must be a slot mapping')
    for key, row in rows.items():
        if (key not in ('0', '1', '2', '3') or not isinstance(row, dict) or row.get('policy') != POLICY
                or row.get('config_sha256') != CONFIG_SHA256 or row.get('member_id') != member['member_id']
                or row.get('slot') != int(key) or row.get('original_owner') != carried_slot_owner(member)
                or row.get('original_slot') != carried_slot_order(member)[int(key)]
                or row.get('record_hash') != fingerprint({k: v for k, v in row.items() if k != 'record_hash'})
                or not isinstance(row.get('events'), list)):
            raise ValueError('Skill history live slot/owner/source binding changed')
        seen = set()
        for event in row['events']:
            if not isinstance(event, dict) or str(event.get('skill_id')) not in _data()['skills'] or event.get('token') in seen:
                raise ValueError('Unknown or duplicate skill history source event')
            seen.add(event.get('token'))
        for skill_id in {event['skill_id'] for event in row['events']}:
            _totals([e for e in row['events'] if e['skill_id'] == skill_id], skill_id)


def has_armed_listener(member):
    validate_member(member)
    return any(_totals([e for e in row['events'] if e['skill_id'] == int(mid)], int(mid))[2]
        for row in member.get('skill_history', {}).values() for mid in _data()['skills'])


def _check_observer_origin(member, slot):
    if any(str(slot) in member.get(key, {}) for key in ('dynamic_skill_origins', 'transformation_skill_origins')):
        raise ValueError('Carried growth of generated/borrowed skill has no proven acquisition baseline; original bundle exchange remains supported')


def bind_action(catalog, state, side, action):
    from lab.dynamic_skills import carried_slot_owner, carried_slot_order
    prepared = _prepared(catalog)
    member = _active(state, side)
    for slot, mid in enumerate(member['skill_slots']):
        spec = _data()['skills'].get(str(mid))
        if spec and any(c['when'].startswith('carried.') for c in spec['components']):
            _check_observer_origin(member, slot)
    if 'skill_history_components' not in action.get('program', {}):
        return None
    expected = programs(prepared).get(action['skill_id'])
    if expected is None or fingerprint(action['program']) != fingerprint(expected):
        raise ValueError('Skill history program differs from whole-source compilation')
    slot = action['slot']
    validate_member(member)
    if member['member_id'] != action['actor_member_id'] or member['skill_slots'][slot] != action['skill_id']:
        raise ValueError('Bind skill history before any action changes the committed source slots')
    binding = {'policy': POLICY, 'config_sha256': CONFIG_SHA256, 'turn': state['turn'], 'side': side,
        'actor_member_id': member['member_id'], 'original_owner': carried_slot_owner(member),
        'original_slot': carried_slot_order(member)[slot], 'skill_id': action['skill_id'],
        'source_hash': action['program']['source_hash']}
    binding['binding_hash'] = fingerprint(binding)
    return binding


def _holder(state, binding):
    from lab.dynamic_skills import carried_slot_owner, carried_slot_order
    if (not isinstance(binding, dict) or binding.get('policy') != POLICY
            or binding.get('config_sha256') != CONFIG_SHA256
            or binding.get('binding_hash') != fingerprint({k: v for k, v in binding.items() if k != 'binding_hash'})
            or _data()['skills'].get(str(binding.get('skill_id')), {}).get('record_hash') != binding.get('source_hash')):
        raise ValueError('Skill history action binding changed')
    matches = [m for m in _members(state) if carried_slot_owner(m) == binding['original_owner']]
    if len(matches) != 1:
        raise ValueError('Skill history original bundle holder is not uniquely available')
    member = matches[0]
    validate_member(member)
    return member, carried_slot_order(member).index(binding['original_slot'])


def power_terms(state, binding):
    if binding is None:
        return None
    member, slot = _holder(state, binding)
    row = _row(member, slot)
    events = [e for e in row['events'] if e['skill_id'] == binding['skill_id']] if row else []
    add, factor, _, cost_add, hits_add, _ = _totals(events, binding['skill_id'])
    terms = {'policy': POLICY, 'config_sha256': CONFIG_SHA256, 'skill_id': binding['skill_id'],
             'binding_hash': binding['binding_hash'], 'events': deepcopy(events), 'add': add, 'factor': factor, 'cost_add': cost_add, 'hits_add': hits_add}
    terms['terms_hash'] = fingerprint(terms)
    return terms


def modify_power(value, terms):
    if terms is None:
        return value
    if (not isinstance(terms, dict) or terms.get('policy') != POLICY or terms.get('config_sha256') != CONFIG_SHA256
            or terms.get('terms_hash') != fingerprint({k: v for k, v in terms.items() if k != 'terms_hash'})
            or str(terms.get('skill_id')) not in _data()['skills']):
        raise ValueError('Power history terms changed')
    add, factor, _, cost_add, hits_add, _ = _totals(terms['events'], terms['skill_id'])
    if (type(terms.get('add')) is not int or type(terms.get('factor')) is not int or type(terms.get('cost_add')) is not int
            or type(terms.get('hits_add')) is not int
            or (add, factor, cost_add, hits_add) != (terms['add'], terms['factor'], terms['cost_add'], terms['hits_add'])):
        raise ValueError('Power history totals differ from source event replay')
    return (value + add) * factor


def cost(catalog, state, side, skill_id, value, slot=None):
    """Intrinsic source cost, before ordinary cost buffs; duplicate slots must agree."""
    prepared = _prepared(catalog)
    spec = _data()['skills'].get(str(skill_id))
    if not spec or not any(c['op'] == 'cost.add' for c in spec['components']):
        return value
    member = _active(state, side)
    validate_member(member)
    candidates = [i for i, mid in enumerate(member['skill_slots']) if mid == skill_id and (slot is None or i == slot)]
    if not candidates:
        raise ValueError('Intrinsic history cost requires its actual carried source slot')
    values = set()
    for index in candidates:
        _check_observer_origin(member, index)
        row = _row(member, index)
        events = [e for e in row['events'] if e['skill_id'] == skill_id] if row else []
        values.add(max(0, value + _totals(events, skill_id)[3]))
    if len(values) != 1:
        raise ValueError('Duplicate cost-history skill slots differ; explicit slot is required')
    return values.pop()


def hits(member, base, skill_id):
    """Permanent intrinsic hits before shared flat/percentage/fixed-hit rules."""
    spec = _data()['skills'].get(str(skill_id))
    if not spec or not any(c['op'] == 'hits.add' for c in spec['components']):
        return base
    validate_member(member)
    values = set()
    for slot, mid in enumerate(member['skill_slots']):
        if mid != skill_id:
            continue
        _check_observer_origin(member, slot)
        row = _row(member, slot)
        events = [e for e in row['events'] if e['skill_id'] == skill_id] if row else []
        values.add(base + _totals(events, skill_id)[4])
    if len(values) != 1:
        raise ValueError('Intrinsic hit history needs one unambiguous carried source history')
    return values.pop()


def _append(member, slot, skill_id, phase, turn, token, actor_member_id, **extra):
    row = _row(member, slot, create=True)
    event = {'skill_id': skill_id, 'source_hash': _data()['skills'][str(skill_id)]['record_hash'],
        'phase': phase, 'turn': turn, 'token': token, 'actor_member_id': actor_member_id, **deepcopy(extra)}
    prior = next((e for e in row['events'] if e['token'] == token), None)
    if prior:
        if prior != event:
            raise ValueError('Skill history token reused for a different source event')
        return None
    row['events'].append(event)
    row['record_hash'] = fingerprint({k: v for k, v in row.items() if k != 'record_hash'})
    validate_member(member)
    return {'op': 'skill.history', 'holder_member_id': member['member_id'], 'slot': slot,
            'history_event': deepcopy(event), 'policy': POLICY, 'training_eligible': False}


def _primitive(prepared, state, side, component, skill_id, context):
    actor, other = _active(state, side), 'b' if side == 'a' else 'a'
    params = {'target': 'self'}
    if component['op'] == 'energy.restore':
        params['amount'] = component['amount']
    else:
        params.update(attributes=component['attributes'],
                      percent={'numerator': component['percent'][0], 'denominator': component['percent'][1]})
    program = {'category': 'skill', 'status': 'compiled', 'blockers': [], 'game_id': skill_id,
        'static_fields': {'kind': _data()['skills'][str(skill_id)]['record']['kind']},
        'snapshot_id': prepared.snapshot_id, 'source_hash': _data()['skills'][str(skill_id)]['record_hash'],
        'operations': [{'op': component['op'], 'params': params}]}
    from lab import mark_runtime as marks
    relative = marks.attach_relative_marks(state, side)
    for target in relative.values():
        target['types'] = deepcopy(prepared._rules.form(target['form_id'])['types'])
    result = execute_effects(program, relative, {'mode': 'isolated_skill_experiment',
        'turn': state['turn'],
        'snapshot_id': prepared.snapshot_id, 'source_hash': program['source_hash'], 'excluded_hooks': sorted(HOOKS),
        'unresolved_dependencies': [], 'operation_order': 'source_text_order_experiment',
        'energy_policy': 'clamp_to_declared_max', 'stat_policy': 'record_signed_percentage_terms', **marks.research_context()})
    if result['status'] != 'applied':
        raise ValueError('Kill reward primitive blocked: ' + '; '.join(result['blockers']))
    updated = result['state']['self']
    for field in ('energy', 'stat_modifiers', 'stat_modifier_sources'):
        if field in updated:
            actor[field] = deepcopy(updated[field])
    return [{**e, 'actor_side': side, 'actor_member_id': actor['member_id'], 'target_side': side,
             'target_member_id': actor['member_id'], 'source_skill_id': skill_id,
             'source_hash': program['source_hash'], 'skill_history_policy': POLICY} for e in result['events']]


def after_skill(catalog, state, side, action, binding, *, action_token, context):
    if binding is None:
        return []
    prepared = _prepared(catalog); _context(context)
    if binding['turn'] != state['turn'] or binding['skill_id'] != action['skill_id'] or binding['actor_member_id'] != action['actor_member_id']:
        raise ValueError('Skill history binding belongs to another committed action')
    current = deepcopy(state)
    holder, slot = _holder(current, binding)
    actor = _active(current, side)
    if actor['member_id'] != binding['actor_member_id']:
        raise ValueError('Process source-owned skill history before caster departure')
    mid = binding['skill_id']
    event = _append(holder, slot, mid, 'after.use', current['turn'], action_token + ':history.use', actor['member_id'])
    if event is None:
        return []
    events = [event]
    if any(c['when'] == 'after.use.choice' for c in _data()['skills'][str(mid)]['components']):
        option = context.get('choice_option')
        extra = _append(holder,slot,mid,'after.use.choice',current['turn'],action_token+':history.choice',actor['member_id'],choice_option=option)
        if extra:
            events.append(extra)
    if any(c['when'] == 'after.use.no_previous_attack' for c in _data()['skills'][str(mid)]['components']):
        from lab.action_outcome_runtime import committed_history
        committed = committed_history(actor)
        actual = [r for r in committed if r['token'] == action_token]
        if len(actual) != 1 or current.get('committed_action_outcomes', {}).get(action_token) != actual[0]['outcome_signature']:
            raise ValueError('Previous-turn growth requires the current committed use proof')
        previous = [r for r in committed if r['turn'] == current['turn'] - 1]
        if not any(r['kind'] in ('physical', 'magical') for r in previous):
            proof = {'turn': current['turn'] - 1, 'rows': deepcopy(previous)}
            proof['hash'] = fingerprint(proof)
            extra = _append(holder, slot, mid, 'after.use.no_previous_attack', current['turn'],
                action_token + ':history.previous.turn', actor['member_id'], previous_turn=proof)
            if extra:
                events.append(extra)
    proofs = [proof for rows in current.get('knockout_provenance', {}).values() for proof in rows.values()
        if proof.get('action_token') == action_token and proof.get('skill_id') == mid
        and proof.get('attacker', {}).get('member_id') == actor['member_id']]
    for index, proof in enumerate(proofs):
        validate_direct_defeat(proof)
        components = [c for c in _data()['skills'][str(mid)]['components'] if c['when'] == 'this_skill.direct_defeat']
        if not components:
            continue
        extra = _append(holder, slot, mid, 'direct.defeat', current['turn'],
            action_token + ':history.kill:' + str(index), actor['member_id'], proof=proof, action_token=action_token)
        if extra:
            events.append(extra)
            for component in components:
                if component['op'] in ('energy.restore', 'stat.modify') and actor['hp'] > 0:
                    events.extend(_primitive(prepared, current, side, component, mid, context))
    state.clear(); state.update(current)
    return events


def observe_action(catalog, state, side, action, *, action_token, context):
    """Observe one committed top-level action or a named ordered Swift subaction.

    Call directly after committed outcomes, before slot/leave hooks. Switch may
    already have changed the active member; its original actor owns this event.
    """
    _prepared(catalog); _context(context)
    if (action.get('kind') not in ('skill', 'switch', 'recharge') or type(context.get('action_is_later')) is not bool
            or not isinstance(action_token, str) or not action_token):
        raise ValueError('Carried history requires a real committed action and explicit order flag')
    current = deepcopy(state)
    actor = next((m for m in current['teams'][side]['members'] if m['member_id'] == action.get('actor_member_id')), None)
    if actor is None:
        raise ValueError('Carried history committed actor is no longer in its owned roster')
    observed_kind = ('charge_setup' if action.get('execution_phase') == 'charge_setup_not_attack_release' else action['kind'])
    observation = {'kind': observed_kind, 'turn': current['turn'], 'actor_member_id': actor['member_id'],
        'token': action_token, 'action_is_later': context['action_is_later'],
        'order_scope': context.get('history_order_scope', 'top_level_action'), 'committed_skill': None}
    rows = [(slot, mid, _data()['skills'].get(str(mid))) for slot, mid in enumerate(actor['skill_slots'])]
    observers = [(slot, mid, spec) for slot, mid, spec in rows
        if spec and any(c['when'].startswith('carried.') for c in spec['components'])]
    if observed_kind == 'skill' and observers:
        from lab.action_outcome_runtime import committed_history
        committed = [r for r in committed_history(actor) if r['token'] == action_token]
        if len(committed) != 1 or current.get('committed_action_outcomes', {}).get(action_token) != committed[0]['outcome_signature']:
            raise ValueError('Carried growth requires the same already committed skill outcome token')
        observation['committed_skill'] = deepcopy(committed[0])
        if committed[0]['skill_id'] != action['skill_id']:
            raise ValueError('Carried growth action and outcome skill differ')
    observation['observation_hash'] = fingerprint(observation)
    # Receipt is independent of the currently carried bundle: replay after an
    # exchange cannot retroactively grow a newly acquired skill.
    receipt = fingerprint({'observation': {k: observation[k] for k in
        ('kind', 'turn', 'actor_member_id', 'token', 'action_is_later', 'order_scope')},
        'action': {k: action.get(k) for k in ('kind', 'actor_member_id', 'skill_id', 'slot', 'target_slot', 'execution_phase')}})
    ledger = current.setdefault('skill_history_observed_actions', {})
    if not isinstance(ledger, dict):
        raise ValueError('Malformed carried history observation receipts')
    if action_token in ledger:
        if ledger[action_token] != receipt:
            raise ValueError('Carried history token reused for a different committed action')
        return []
    events = []
    for slot, mid, spec in observers:
        _check_observer_origin(actor, slot)
        validate_member(actor)
        if any(_selected_observation(c, observation) for c in spec['components']):
            event = _append(actor, slot, mid, 'carried.action', current['turn'],
                action_token + ':history.observe:' + str(slot), actor['member_id'], observation=observation)
            if event:
                events.append(event)
        if any(c['when'] == 'carried.direct_defeat' for c in spec['components']) and observed_kind == 'skill':
            proofs = [p for rows in current.get('knockout_provenance', {}).values() for p in rows.values()
                if p.get('action_token') == action_token and p.get('attacker', {}).get('member_id') == actor['member_id']]
            for index, proof in enumerate(proofs):
                validate_direct_defeat(proof)
                event = _append(actor, slot, mid, 'carried.direct.defeat', current['turn'],
                    action_token + ':history.carried.kill:' + str(slot) + ':' + str(index), actor['member_id'],
                    proof=proof, action_token=action_token)
                if event:
                    events.append(event)
    ledger[action_token] = receipt
    state.clear(); state.update(current)
    return events


def observe_received_attack(catalog, state, target_side, action, damage_events, *, action_token, context):
    """One actual attack packet, before target replacement, with exact source chart."""
    prepared = _prepared(catalog); _context(context)
    if action.get('kind') != 'skill' or action.get('execution_phase') == 'charge_setup_not_attack_release':
        return []
    record = prepared._rules.skill(action['skill_id'])
    if record['kind'] not in ('physical', 'magical'):
        from lab.core_magic_runtime import reviewed_wish_skill
        if record['kind'] != 'higher' or reviewed_wish_skill(action['skill_id']) != record:
            return []
    current = deepcopy(state)
    target = _active(current, target_side)
    observed = [(slot, mid, _data()['skills'].get(str(mid))) for slot, mid in enumerate(target['skill_slots'])]
    observers = [(slot, mid, spec) for slot, mid, spec in observed
        if spec and any(c['when'] == 'carried.received_attack' for c in spec['components'])]
    if not observers:
        return []
    other = 'b' if target_side == 'a' else 'a'
    attacker = next((m for m in current['teams'][other]['members'] if m['member_id'] == action.get('actor_member_id')), None)
    if attacker is None or not isinstance(action_token, str) or not action_token:
        raise ValueError('Received-attack growth requires the actual committed attacking member/token')
    from lab.action_outcome_runtime import committed_history
    rows = [r for r in committed_history(attacker) if r['token'] == action_token]
    if (len(rows) != 1 or current.get('committed_action_outcomes', {}).get(action_token) != rows[0]['outcome_signature']
            or rows[0]['skill_id'] != action['skill_id']):
        raise ValueError('Received-attack history requires the same committed outcome proof')
    direct = [deepcopy(e) for e in damage_events if e.get('op') in ('damage', 'damage.hit')
              and e.get('target') == 'opponent' and e.get('before', 0) > 0]
    if not direct:
        return []
    types = {e.get('resolved_params', e.get('params', {})).get('type') for e in direct}
    if len(types) != 1:
        raise ValueError('Mixed-type direct attack packet needs explicit resistance aggregation policy')
    attack_type = types.pop()
    packet = {'turn': current['turn'], 'token': action_token, 'skill_id': action['skill_id'],
        'source_hash': fingerprint(record), 'attacker_member_id': attacker['member_id'],
        'target_member_id': target['member_id'], 'target_form_id': target['form_id'],
        'events': direct, 'effective_type': attack_type,
        'matchup': prepared._rules.type_multiplier(attack_type, target['form_id'])}
    packet['packet_hash'] = fingerprint(packet)
    resisted = _validate_received(packet)
    receipt_key = action_token + ':' + target['member_id']
    receipts = current.setdefault('skill_history_received_attacks', {})
    if not isinstance(receipts, dict):
        raise ValueError('Malformed received-attack history receipts')
    if receipt_key in receipts:
        if receipts[receipt_key] != packet['packet_hash']:
            raise ValueError('Received-attack token reused for a different actual packet')
        return []
    events = []
    for slot, mid, spec in observers:
        _check_observer_origin(target, slot)
        if any(c['when'] == 'carried.received_attack' and (not c.get('require_resisted') or resisted) for c in spec['components']):
            event = _append(target, slot, mid, 'received.attack', current['turn'],
                action_token + ':history.received:' + str(slot), target['member_id'], packet=packet)
            if event:
                events.append(event)
    receipts[receipt_key] = packet['packet_hash']
    state.clear(); state.update(current)
    return events


def on_entry(catalog, state, side, *, event_token, initial=False):
    from lab.dynamic_skills import carried_slot_owner, carried_slot_order
    _prepared(catalog)
    current, events = deepcopy(state), []
    actor = _active(current, side)
    minimum = 0 if initial else 1
    if type(actor.get('entered_turn')) is not int or not minimum <= actor['entered_turn'] <= state['turn']:
        raise ValueError('Skill entry history requires an owned entry turn')
    if actor['hp'] > 0:
        for slot, mid in enumerate(actor['skill_slots']):
            row = _data()['skills'].get(str(mid))
            if row and any(c['when'] == 'member.enter' for c in row['components']):
                event = _append(actor, slot, mid, 'member.enter', current['turn'],
                    event_token + ':history.entry:' + carried_slot_owner(actor) + ':' + str(carried_slot_order(actor)[slot]), actor['member_id'])
                if event:
                    events.append(event)
    state.clear(); state.update(current)
    return events


def initialize(catalog, state):
    if state.get('skill_history_initial_entry_done') is True:
        return []
    if state.get('skill_history_initial_entry_done') not in (None, False):
        raise ValueError('Invalid initial skill-history entry flag')
    current, events = deepcopy(state), []
    for side in ('a', 'b'):
        actor = _active(current, side)
        events.extend(on_entry(catalog, current, side, event_token='initial:' + side + ':' + actor['member_id'], initial=True))
    current['skill_history_initial_entry_done'] = True
    state.clear(); state.update(current)
    return events


def round_end(catalog, state):
    _prepared(catalog)
    current, events = deepcopy(state), []
    for side in ('a', 'b'):
        actor = _active(current, side)
        validate_member(actor)
        if actor['hp'] <= 0:
            continue
        for key, row in list(actor.get('skill_history', {}).items()):
            for mid in {e['skill_id'] for e in row['events']}:
                if _totals([e for e in row['events'] if e['skill_id'] == mid], mid)[2]:
                    event = _append(actor, int(key), mid, 'round.end', current['turn'],
                        f"round.end:{current['turn']}:{row['original_owner']}:{row['original_slot']}:{mid}", actor['member_id'])
                    if event:
                        events.append(event)
    state.clear(); state.update(current)
    return events


def on_departure(catalog, state, side, member_id, *, event_token):
    _prepared(catalog)
    current, events = deepcopy(state), []
    actor = next(m for m in current['teams'][side]['members'] if m['member_id'] == member_id)
    validate_member(actor)
    for key, row in list(actor.get('skill_history', {}).items()):
        for mid in {e['skill_id'] for e in row['events']}:
            totals = _totals([e for e in row['events'] if e['skill_id'] == mid], mid)
            if totals[2] or totals[5]:
                event = _append(actor, int(key), mid, 'member.leave', current['turn'],
                                event_token + ':history.leave:' + key + ':' + str(mid), member_id)
                if event:
                    events.append(event)
    state.clear(); state.update(current)
    return events


def on_slot_remap(member, permutation, *, turn=None, event_token=None):
    """Observe actual movement after the remapper rebinds original identities."""
    validate_member(member)
    events = []
    for key,row in list(member.get('skill_history',{}).items()):
        new_slot = int(key)
        old_slot = permutation[new_slot]
        if new_slot == old_slot:
            continue
        for mid in {e['skill_id'] for e in row['events']}:
            rows = [e for e in row['events'] if e['skill_id'] == mid]
            if not _totals(rows,mid)[5]:
                continue
            if type(turn) is not int or turn < 1:
                raise ValueError('Installed position history requires the actual remap turn')
            if any(e['phase']=='slot.moved' and e['turn']==turn for e in rows):
                continue
            movement = {'from_slot':old_slot,'to_slot':new_slot,'permutation':list(permutation)}
            movement['hash'] = fingerprint(movement)
            token = event_token or f"position:{turn}:{row['original_owner']}:{row['original_slot']}"
            event = _append(member,new_slot,mid,'slot.moved',turn,token+':history.position',member['member_id'],movement=movement)
            if event:
                events.append(event)
    return events


def conditional_swift(catalog,state,member,skill_id):
    spec = _data()['skills'].get(str(skill_id),{}).get('conditional_swift')
    if spec is None:
        return None
    _prepared(catalog)
    from lab.action_outcome_runtime import committed_history
    matches = []
    for actor in _members(state):
        for row in committed_history(actor):
            if row['turn']==state['turn']-1 and row['effective_type']==spec['previous_turn_type']:
                if not _observed_source_matches(row):
                    raise ValueError('Conditional Swift battle history source changed')
                matches.append(deepcopy(row))
    result = {'policy':POLICY,'config_sha256':CONFIG_SHA256,'skill_id':skill_id,
        'source_hash':_data()['skills'][str(skill_id)]['record_hash'],'turn':state['turn'],
        'member_id':member['member_id'],'condition':deepcopy(spec),'matches':matches,'swift':bool(matches)}
    result['proof_hash'] = fingerprint(result)
    return result


def conditional_swift_matches(program,candidate):
    proof = candidate.get('conditional_swift')
    return (isinstance(proof,dict) and proof.get('proof_hash')==fingerprint({k:v for k,v in proof.items() if k!='proof_hash'})
        and proof.get('policy')==POLICY and proof.get('config_sha256')==CONFIG_SHA256
        and proof.get('skill_id')==program.get('game_id') and proof.get('source_hash')==program.get('source_hash')
        and proof.get('condition')==program.get('conditional_swift_components') and proof.get('swift') is True)
