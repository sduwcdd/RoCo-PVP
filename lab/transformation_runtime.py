"""Whole-source transformation fragments and slot identities for research turns.

The selected action remains locked to its original program. Replacement changes
the battle slot for future selections, never a template or a committed action.
All timing/permanence choices are named experiments, not server calibration.
"""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

from lab.action_mechanics import build_action_mechanics, GENERATORS
from lab import defense_runtime as defense
from lab.dynamic_skills import _draw, _digest_record, initialize_dynamic_skills
from lab.prepared_rules import prepare_rules
from lab.ruleset import canonical_hash
from lab.skill_execution import execute_skill, preflight_skill


CONFIG = Path(__file__).resolve().parents[1] / 'data/rules/reviewed-transformation-components-1.json'
CONFIG_HASH = '37af903edac0e8f976e55e7c65fa31c3ee9d17410331c259491daf4e30af28cd'
POLICY = 'source_bound_transformations_experiment_v1'


@lru_cache(maxsize=2)
def _configuration(stamp):
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    if config.get('schema') != 'reviewed-transformation-components-1' or canonical_hash(config) != CONFIG_HASH:
        raise ValueError('Transformation configuration changed; source review required')
    return config


def policies():
    return deepcopy(_configuration(CONFIG.stat().st_mtime_ns)['policies'])


def _authoritative_dynamic_seed(state):
    if "dynamic_skills" in state:
        seed = state["dynamic_skills"].get("prng", {}).get("seed")
    else:
        seed = state.get("random_devotion_rng", {}).get("seed")
    if type(seed) is not int or seed < 0:
        raise ValueError("Transformation requires its existing or episode-authoritative random seed")
    return seed


def programs(catalog):
    """Only fully reviewed descriptions produce executable fragment overrides."""
    prepared = prepare_rules(catalog)
    source = prepared._rules._catalog
    config = _configuration(CONFIG.stat().st_mtime_ns)
    metadata = build_action_mechanics(source)
    if next((t for t in source.get('glossary', []) if t.get('key') == 3011), None) != config['term']:
        raise ValueError('Transformation term 3011 changed; review required')
    result = {}
    for key, row in config['skills'].items():
        record = source.get('moves', {}).get(key)
        if record is None:
            continue
        if canonical_hash(record) != row['record_hash']:
            raise ValueError(f'Transformation whole source changed for {key}; review required')
        spec = row['components']
        meta = metadata['transformations'].get(key)
        if spec['transformation'] and (not meta or meta['status'] != 'supported'):
            raise ValueError(f'Transformation metadata blocked for {key}')
        if spec['transformation'] == 'clever_change' and meta['pool_ids'] != row['pool']['ids']:
            raise ValueError(f'Transformation candidate pool changed for {key}; review required')
        program = deepcopy(prepared._rules.program(int(key)))
        program.pop('native_rule', None)
        if 'operations' in spec:
            operations=deepcopy(spec['operations'])
        elif spec['hits']:
            operations = [{'op': 'damage.sequence' if spec['hits'] > 1 else 'damage',
                'params': {'target': 'opponent', 'kind': record['kind'], 'power': record['power'],
                           'type': record['type'], **({'hits': spec['hits']} if spec['hits'] > 1 else {})}}]
        else:
            operations = [{'op': 'defense.plan', 'params': {'target': 'self',
                'reduction': {'numerator': spec['reduction_percent'], 'denominator': 100}, 'response': 'attack'}}]
        program.update(status='compiled', blockers=[], operations=operations,
            dependency_ids=sorted(set(record.get('desc_notes', []) + ([3005] if spec['hits'] > 1 else []))),
            transformation_components=deepcopy(spec), transformation_evidence=deepcopy(row),
            transformation_metadata=deepcopy(meta), transformation_config_hash=CONFIG_HASH,
            transformation_policy=POLICY, transformation_policies=deepcopy(config['policies']),
            response_kinds=['attack'] if spec['reduction_percent'] is not None else [],
            executable=False, real_game_verified=False)
        if 1005 in record.get('desc_notes', []):
            swift = next((t for t in source.get('glossary', []) if t.get('key') == 1005), None)
            if swift != config['swift_term']:
                raise ValueError('Transformation Swift term changed; review required')
            program.update(intrinsic_swift=True, swift_term=deepcopy(swift),
                entry_trigger={'kind': 'voluntary_switch', 'term_id': 1005})
        result[int(key)] = program
    return result


def _validate_program(program):
    row = _configuration(CONFIG.stat().st_mtime_ns)['skills'].get(str(program.get('game_id')))
    if (row is None or program.get('source_hash') != row['record_hash']
            or program.get('transformation_evidence') != row
            or program.get('transformation_components') != row['components']
            or program.get('transformation_metadata') != row['metadata']
            or program.get('transformation_policy') != POLICY
            or program.get('transformation_config_hash') != CONFIG_HASH
            or program.get('transformation_policies') != policies()):
        raise ValueError('Transformation program source/components differ from reviewed configuration')
    expected = row['components']
    if 'operations' in expected:
        ops=deepcopy(expected['operations'])
    elif expected['hits']:
        raw = row['raw']
        ops = [{'op': 'damage.sequence' if expected['hits'] > 1 else 'damage',
            'params': {'target': 'opponent', 'kind': raw['kind'], 'power': raw['power'], 'type': raw['type'],
                       **({'hits': expected['hits']} if expected['hits'] > 1 else {})}}]
    else:
        ops = [{'op': 'defense.plan', 'params': {'target': 'self',
            'reduction': {'numerator': expected['reduction_percent'], 'denominator': 100}, 'response': 'attack'}}]
    dependencies = sorted(set(row['raw'].get('desc_notes', []) + ([3005] if expected['hits'] > 1 else [])))
    if (program.get('operations') != ops or 'native_rule' in program
            or program.get('dependency_ids') != dependencies
            or program.get('response_kinds') != (['attack'] if expected['reduction_percent'] is not None else [])):
        raise ValueError('Transformation executable operations changed')
    if 1005 in dependencies and (program.get('intrinsic_swift') is not True
            or program.get('entry_trigger') != {'kind': 'voluntary_switch', 'term_id': 1005}
            or program.get('swift_term') != _configuration(CONFIG.stat().st_mtime_ns)['swift_term']):
        raise ValueError('Transformation Swift source metadata changed')
    return expected


def preflight(program, state, context, damage_resolver=None):
    spec = _validate_program(program)
    if context.get('transformation_policies') != policies():
        raise ValueError('Explicit transformation experiment policies required')
    if spec.get('random_stat_components'):
        from lab.user_skill_extensions import preflight_random
        preflight_random(program, state, context)
    elif spec['reduction_percent'] is not None:
        from lab.effect_runtime import _preflight_header
        _preflight_header(program, state, context)
        defense.check_cooldown(state['self'], context['turn'])
        if type(context.get('resolved_energy_cost')) is not int or context['resolved_energy_cost'] < 0:
            raise ValueError('Resolved nonnegative transformation defense cost required')
    else:
        preflight_skill(program, state, context, damage_resolver)


def execute(program, state, context, damage_resolver=None):
    """Damage delegates to the same executor; defense shares its guard/CD state."""
    result = {'status': 'blocked', 'state': deepcopy(state), 'events': [], 'blockers': [],
              'training_eligible': False, 'calibrated': False, 'full_turn_executed': False}
    try:
        preflight(program, state, context, damage_resolver)
        spec = program['transformation_components']
        if spec.get('random_stat_components'):
            from lab.user_skill_extensions import execute_random
            return execute_random(program, state, context)
        if spec['reduction_percent'] is None:
            return execute_skill(program, state, context, damage_resolver=damage_resolver)
        owned = deepcopy(state)
        actor = owned['self']
        cost = context['resolved_energy_cost']
        actor['energy'] -= cost
        ratio = {'numerator': spec['reduction_percent'], 'denominator': 100}
        actor['defense_runtime'] = {'policy': defense.POLICY, 'cooldown_through_turn': context['turn'] + 1,
            'guard_turn': context['turn'], 'reduction': ratio, 'skill_id': program['game_id'],
            'source_hash': program['source_hash'], 'snapshot_id': program['snapshot_id'],
            'phase_config_hash': CONFIG_HASH}
        result.update(status='applied', state=owned, response_success=context.get('response_success') is True,
            events=[{'op': 'energy.pay', 'target': 'self', 'amount': cost},
                {'op': 'defense.activate', 'target': 'self', 'reduction': ratio,
                 'turn': context['turn'], 'cooldown_through_turn': context['turn'] + 1,
                 'response_success': context.get('response_success') is True, 'policy': defense.POLICY}])
    except (ValueError, KeyError, TypeError) as exc:
        result['blockers'] = [str(exc)]
    return result


def validate_member(member):
    origins = member.get('transformation_skill_origins', {})
    if not isinstance(origins, dict):
        raise ValueError('Transformation origins must be a slot mapping')
    for key, row in origins.items():
        if (key not in ('0', '1', '2', '3') or not isinstance(row, dict)
                or row.get('policy') != POLICY or row.get('record_hash') != _digest_record(row)
                or row.get('member_id') != member.get('member_id') or row.get('slot') != int(key)
                or type(row.get('generated_skill_id')) is not int
                or row['generated_skill_id'] != member['skill_slots'][int(key)]
                or row.get('kind') not in ('clever_change', 'slot_replace')
                or row.get('energy_delta') != (-1 if row['kind'] == 'clever_change' else 0)
                or type(row.get('origin_skill_id')) is not int
                or row.get('source_config_hash') != CONFIG_HASH):
            raise ValueError('Invalid source-tracked transformation slot')
        if row['kind'] == 'clever_change' and row['generated_skill_id'] not in row.get('pool_ids', []):
            raise ValueError('Transformation draw not in recorded unfiltered candidate pool')
        if row['kind'] == 'clever_change':
            source = _configuration(CONFIG.stat().st_mtime_ns)['skills'].get(str(row['origin_skill_id']))
            if (not source or source['components']['transformation'] != 'clever_change'
                    or row.get('pool_ids') != source['pool']['ids']
                    or row.get('source_hash') != source['record_hash']):
                raise ValueError('Transformation origin/pool differs from reviewed whole source')


def _member(state, side, member_id):
    if side not in ('a', 'b'):
        raise ValueError('Transformation requires explicit a/b side')
    matches = [m for m in state['teams'][side]['members'] if m['member_id'] == member_id]
    if len(matches) != 1:
        raise ValueError('Transformation target must identify exactly one battle member')
    return matches[0]


def before_action(catalog, state, side, action, opponent_action, context):
    """Bind committed action identity, even if its actual slot has since changed.

    Call after planning and before execution; after_action consumes this token.
    An already committed program is never replaced by the current slot's program.
    """
    actor = _member(state, side, action['actor_member_id'])
    validate_member(actor)
    slot = action.get('slot')
    if action.get('kind') != 'skill' or action.get('execution_phase') == 'charge_setup_not_attack_release':
        return None
    if type(slot) is not int or not 0 <= slot < 4:
        raise ValueError('Transformation action must retain its committed slot')
    program = action['program']
    if action['skill_id'] != program.get('game_id'):
        raise ValueError('Committed action skill ID conflicts with its program')
    origin = actor.get('transformation_skill_origins', {}).get(str(slot))
    matching = actor['skill_slots'][slot] == action['skill_id']
    if matching and origin and origin.get('blocker'):
        raise ValueError(origin['blocker'])
    if action['skill_id'] in GENERATORS:
        raise ValueError('Copied generator cannot execute recursively; no reroll allowed')
    binding = {'policy': POLICY, 'side': side, 'member_id': actor['member_id'], 'slot': slot,
        'skill_id': action['skill_id'], 'turn': state['turn'], 'source_hash': program['source_hash'],
        'slot_skill_id_before_execution': actor['skill_slots'][slot],
        'origin': deepcopy(origin) if matching else None,
        'dynamic_origin': deepcopy(actor.get('dynamic_skill_origins', {}).get(str(slot))) if matching else None,
        'opponent_skill_id': opponent_action.get('skill_id') if opponent_action.get('kind') == 'skill' else None,
        'opponent_kind': (prepare_rules(catalog)._rules.skill(opponent_action['skill_id'])['kind']
            if opponent_action.get('kind') == 'skill' and opponent_action.get('execution_phase') != 'charge_setup_not_attack_release'
            else opponent_action.get('kind')),
        'slot_matches_committed_action': matching,
        'locked_action_policy': policies()['locked_action']}
    binding['record_hash'] = _digest_record(binding)
    return binding


def replace_battle_slot(state, side, member_id, slot, replacement_id, *, source_skill_id,
                        source_hash, kind='slot_replace', pool_ids=None, prior_dynamic_origin=None,
                        prior_transformation_origin=None, blocker=None, blocker_code=None):
    """Exact member+slot replacement; duplicate skill IDs never locate a slot."""
    if type(slot) is not int or not 0 <= slot < 4 or type(replacement_id) is not int or replacement_id <= 0:
        raise ValueError('Replacement requires a slot in 0..3 and a positive skill ID')
    if kind not in ('slot_replace', 'clever_change') or (kind == 'clever_change' and replacement_id not in (pool_ids or [])):
        raise ValueError('Invalid transformation kind or sampled candidate')
    actor = _member(state, side, member_id)
    initialize_dynamic_skills(state, seed=_authoritative_dynamic_seed(state))
    previous = actor['skill_slots'][slot]
    if replacement_id in GENERATORS:
        blocker_code = 'recursive_generator'
        blocker = 'Copied generator cannot execute recursively; no reroll allowed'
    row = {'policy': POLICY, 'kind': kind, 'member_id': member_id, 'slot': slot,
        'origin_skill_id': source_skill_id, 'generated_skill_id': replacement_id,
        'energy_delta': -1 if kind == 'clever_change' else 0, 'applied_turn': state['turn'],
        'source_hash': source_hash, 'source_config_hash': CONFIG_HASH,
        'pool_ids': list(pool_ids or []), 'prior_dynamic_origin': deepcopy(prior_dynamic_origin),
        'prior_transformation_origin': deepcopy(prior_transformation_origin),
        'blocker': blocker, 'blocker_code': blocker_code}
    row['record_hash'] = _digest_record(row)
    actor['skill_slots'][slot] = replacement_id
    actor.setdefault('dynamic_skill_origins', {}).pop(str(slot), None)
    actor.setdefault('transformation_skill_origins', {})[str(slot)] = row
    return {'op': 'transformation.slot_changed', 'side': side, 'member_id': member_id,
        'slot': slot, 'before_skill_id': previous, 'skill_id': replacement_id, 'kind': kind,
        'status': 'blocked' if blocker else 'changed',
        'energy_delta': row['energy_delta'], 'blocker': blocker, 'blocker_code': blocker_code,
        'policy': POLICY, 'record_hash': row['record_hash']}


def _candidate_blocker(catalog, skill_id):
    if skill_id in GENERATORS:
        return 'recursive_generator', 'Copied generator cannot execute recursively; no reroll allowed'
    prepared = prepare_rules(catalog)
    try:
        from lab.runtime_programs import reviewed_programs
        from lab import weather_runtime as weather
        available = {**reviewed_programs(prepared), **programs(prepared),
            **weather.weather_programs(prepared), **weather.weather_attack_programs(prepared)}
        program = available.get(skill_id, prepared._rules.program(skill_id))
    except (ValueError, KeyError) as exc:
        return 'missing_candidate_record', f'Sampled skill {skill_id} cannot resolve: {exc}; no reroll allowed'
    if program['status'] != 'compiled':
        return 'unsupported_candidate', f'Sampled skill {skill_id} is not executable: {program.get("blockers")}; no reroll allowed'
    return None, None


def after_action(catalog, state, side, action, opponent_action, context, result):
    """Mutate two-team slots only after an applied execution; return new events.

    An applied multi-hit attack may stop on KO and still counts as a use. Failed,
    skipped or charging setup actions never draw, replace or return a slot.
    """
    if result.get('status') != 'applied' or action.get('kind') != 'skill' or action.get('execution_phase') == 'charge_setup_not_attack_release':
        return []
    binding = context.get('_transformation_binding')
    if binding is None:
        raise ValueError('Transformation after-action requires a before-action identity binding')
    if (binding.get('record_hash') != _digest_record(binding) or binding.get('policy') != POLICY
            or binding.get('side') != side or binding.get('member_id') != action['actor_member_id']
            or binding.get('slot') != action['slot'] or binding.get('skill_id') != action['skill_id']
            or binding.get('turn') != state['turn'] or binding.get('source_hash') != action['program']['source_hash']):
        raise ValueError('Transformation action identity binding changed')
    current = deepcopy(state)
    actor = _member(current, side, action['actor_member_id'])
    validate_member(actor)
    if not binding['slot_matches_committed_action']:
        return [{'op': 'transformation.locked_action_retained', 'slot': action['slot'],
                 'skill_id': action['skill_id'], 'policy': policies()['locked_action']}]
    root = current.setdefault('transformation_runtime', {'policy': POLICY, 'applied_bindings': []})
    if root.get('policy') != POLICY or not isinstance(root.get('applied_bindings'), list):
        raise ValueError('Invalid transformation replay state')
    if binding['record_hash'] in root['applied_bindings']:
        return []
    slot = action['slot']
    # Another after-use hook may replace this slot; never overwrite its identity.
    if actor['skill_slots'][slot] != binding['slot_skill_id_before_execution']:
        return []
    events = []
    origin = binding['origin']
    if origin and origin['kind'] == 'clever_change':
        actor['skill_slots'][slot] = origin['origin_skill_id']
        actor['transformation_skill_origins'].pop(str(slot))
        if origin.get('prior_transformation_origin'):
            actor['transformation_skill_origins'][str(slot)] = deepcopy(origin['prior_transformation_origin'])
        if origin.get('prior_dynamic_origin'):
            actor.setdefault('dynamic_skill_origins', {})[str(slot)] = deepcopy(origin['prior_dynamic_origin'])
        events.append({'op': 'transformation.returned', 'member_id': actor['member_id'], 'slot': slot,
            'before_skill_id': action['skill_id'], 'skill_id': origin['origin_skill_id'], 'policy': POLICY})
    elif 'transformation_components' in action['program']:
        spec = _validate_program(action['program'])
        kind = spec['transformation']
        if kind == 'clever_change':
            initialize_dynamic_skills(current, seed=_authoritative_dynamic_seed(current))
            meta = action['program']['transformation_metadata']
            pool = meta['pool_ids']
            if not pool:
                raise ValueError('Reviewed clever candidate pool is empty')
            selected = pool[_draw(current['dynamic_skills']['prng'], len(pool))]
            code, blocker = _candidate_blocker(catalog, selected)
            events.append(replace_battle_slot(current, side, actor['member_id'], slot, selected,
                source_skill_id=action['skill_id'], source_hash=action['program']['source_hash'],
                kind='clever_change', pool_ids=pool, prior_dynamic_origin=binding['dynamic_origin'],
                prior_transformation_origin=binding['origin'],
                blocker=blocker, blocker_code=code))
        elif kind == 'slot_replace' and context.get('response_success') is True:
            selected = binding['opponent_skill_id']
            if type(selected) is not int or binding['opponent_kind'] not in ('physical', 'magical'):
                raise ValueError('Successful mirror response requires the committed opposing skill')
            initialize_dynamic_skills(current, seed=_authoritative_dynamic_seed(current))
            code, blocker = _candidate_blocker(catalog, selected)
            events.append(replace_battle_slot(current, side, actor['member_id'], slot, selected,
                source_skill_id=action['skill_id'], source_hash=action['program']['source_hash'],
                blocker=blocker, blocker_code=code))
    if not events:
        return []
    root['applied_bindings'].append(binding['record_hash'])
    state.clear()
    state.update(current)
    return events
