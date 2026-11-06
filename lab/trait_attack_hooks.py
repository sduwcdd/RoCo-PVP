"""Source-bound trait lifesteal over committed actual damage and common healing.

The HP predicate is sampled after payment and before the whole attack. Hits are
summed and rounded once, matching the existing mechanism drain experiment.
Skill and trait percentages add under the user's 2026-10-30 rule and heal once.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from lab.effect_runtime import execute_effects, HOOKS
from lab.game_runtime_defaults import ROOT
from lab.phase_config import fingerprint
from lab import trait_runtime as traits

CONFIG = ROOT / 'data/rules/reviewed-trait-attack-hooks-1.json'
CONFIG_SHA256 = '75869b5477e8a2f6a355b160efbafd096d4823ba858163d8944422949138b1a8'
POLICY = 'trait_lifesteal_actual_damage_sum_floor_once_action_hp_snapshot_v2'
POLICIES = {'timing': 'after_payment_before_skill_hp_snapshot_then_after_whole_skill',
    'damage_basis': 'sum_committed_opponent_direct_attack_hp_loss',
    'rounding': 'floor_once_on_total_actual_damage', 'cap': 'clamp_to_declared_max',
    'stacking': 'user_confirmed_add_percentages_single_restore_20261030', 'entry': 'explicit_owned_entry_aura',
    'exhaustion': 'never_revive_from_lifesteal'}


@lru_cache(maxsize=2)
def _configuration(stamp):
    raw = CONFIG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONFIG_SHA256:
        raise ValueError('Trait attack configuration changed; review required')
    return json.loads(raw)


@lru_cache(maxsize=16)
def _source_hash(path, size, stamp):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@traits.cached_source_query
def _data():
    data = _configuration(CONFIG.stat().st_mtime_ns)
    for relative, expected in data['sources'].items():
        path = (ROOT / relative).resolve()
        stat = path.stat()
        if not path.is_relative_to(ROOT) or _source_hash(str(path), stat.st_size, stat.st_mtime_ns) != expected:
            raise ValueError('Trait attack extracted source changed')
    return data


def research_context():
    return {'trait_attack_policy': POLICY, 'trait_attack_policies': deepcopy(POLICIES)}


def _context(context):
    if (context.get('trait_attack_policy') != POLICY
            or context.get('trait_attack_policies') != POLICIES):
        raise ValueError('Explicit trait-attack timing and stacking policies required')


def _active(state, side):
    team = state['teams'][side]
    return team['members'][team['active_slot']]


def _source(prepared, member):
    if member.get('trait_policy') != traits.POLICY:
        return None
    data = _data()
    form = data['forms'].get(str(member['form_id']))
    if form is None:
        return None
    if (prepared.snapshot_id != data['snapshot_id']
            or fingerprint(prepared._rules.form(member['form_id'])) != form['record_hash']
            or member.get('trait_id') != form['trait_id']):
        raise ValueError('Trait attack form/source binding changed')
    tid = str(form['trait_id'])
    row = data['traits'].get(tid) or data['blocked_traits'].get(tid)
    if fingerprint(prepared._rules._catalog['traits'][tid]) != row['record_hash']:
        raise ValueError('Trait attack description source changed')
    if tid in data['blocked_traits']:
        raise ValueError(data['blocked_traits'][tid]['reason'])
    return row


def _aura(row, member):
    return {'policy': POLICY, 'config_sha256': CONFIG_SHA256, 'trait_id': row['trait_id'],
        'source_hash': row['record_hash'], 'member_id': member['member_id'],
        'entry_turn': member['entered_turn'], 'percent': row['percent']}


def on_entry(prepared, state, side, *, initial=False):
    """Call at initial/actual entry, before Swift. A reserve has no entry grant."""
    member = _active(state, side)
    row = _source(prepared, member)
    if row is None or row['when'] != 'entered' or member['hp'] <= 0:
        return []
    minimum = 0 if initial else 1
    if type(member.get('entered_turn')) is not int or not minimum <= member['entered_turn'] <= state['turn']:
        raise ValueError('Trait lifesteal entry needs the owned entered_turn')
    aura = _aura(row, member)
    current = member.get('trait_attack_aura')
    if current == aura:
        return []
    if current is not None:
        if (not isinstance(current, dict) or set(current) != set(aura)
                or any(current.get(key) != aura[key] for key in aura if key != 'entry_turn')
                or type(current.get('entry_turn')) is not int
                or not 0 <= current['entry_turn'] <= member['entered_turn']):
            raise ValueError('Unknown or modified trait attack entry aura')
    member['trait_attack_aura'] = aura
    return [{'op': 'trait.lifesteal.entry', 'actor_side': side,
             'actor_member_id': member['member_id'], **deepcopy(aura)}]


def initialize(prepared, state):
    if state.get('trait_policy') != traits.POLICY:
        return []
    current, events = deepcopy(state), []
    for side in ('a', 'b'):
        member = _active(current, side)
        # Leave unsupported unrelated traits to the owning capability gate.
        row = _data()['traits'].get(str(member.get('trait_id')))
        if row and row['when'] == 'entered':
            events.extend(on_entry(prepared, current, side, initial=True))
    state.clear(); state.update(current)
    return events


def _overlap(program, member, events=()):
    if member.get('team_devotion', {}).get('lifesteal', 0):
        raise ValueError('Devotion and trait lifesteal overlap; stacking rule is unverified')
    if any(e.get('target') == 'self' and (e.get('op') in ('hp.drain', 'devotion.lifesteal')
           or e.get('trait_attack_policy') == POLICY) for e in events):
        raise ValueError('Another lifesteal already processed this attack; duplicate healing blocked')


def _attack_source(prepared, member):
    trait = _source(prepared, member)
    from lab.attack_grant_runtime import lifesteal_source
    skill = lifesteal_source(member) if member.get('skill_attack_grants') else None
    if trait is not None and skill is not None:
        refs = [{k: deepcopy(v) for k, v in source.items() if k != 'evidence'} for source in (trait, skill)]
        return {'trait_id': trait['trait_id'], 'source_kind': 'combined', 'record_hash': fingerprint(refs),
                'when': 'combined', 'percent': trait['percent'] + skill['percent'], 'sources': refs}
    return skill or trait


def stacking_rule():
    rule = _data()['stacking_rule']
    if (rule.get('combine') != 'sum_active_percentages' or rule.get('restore') != 'single'
            or rule.get('source') != 'user_instruction_20261030'):
        raise ValueError('User-confirmed lifesteal composition rule changed')
    return deepcopy(rule)


def _percent(row, hp, maximum):
    return sum(_percent(source, hp, maximum) for source in row['sources']) if row.get('sources') else (
        row['percent'] if row['when'] in ('entered', 'skill_grant') or hp * 2 < maximum else 0)


def defer_drain(program, component, context, member):
    """An owned attack binding transfers direct skill healing to the one common hook."""
    binding = context.get('combined_lifesteal_binding')
    if binding is None:
        return None
    _context(context)
    stacking_rule()
    if (binding.get('policy') != POLICY or binding.get('config_sha256') != CONFIG_SHA256
            or binding.get('binding_hash') != fingerprint({k:v for k,v in binding.items() if k != 'binding_hash'})
            or binding.get('member_id') != member.get('member_id')
            or binding.get('skill_id') != program.get('game_id') or binding.get('skill_source_hash') != program.get('source_hash')
            or binding.get('turn') != context.get('turn')):
        raise ValueError('Combined lifesteal requires the matching owned attack binding')
    index = next(i for i,c in enumerate(program['mechanism_components']) if c is component)
    return {'op': 'hp.drain.deferred', 'target': 'self', 'percent': component['percent'],
            'component_index': index, 'source_skill_id': program['game_id'], 'source_hash': program['source_hash'],
            'binding_hash': binding['binding_hash'], 'stacking_rule': stacking_rule()}


def prepare_attack(prepared, member, program, context, *, token):
    """Preflight on the owned pre-action member; account for quoted HP payment.

    Supply the relative member with team_devotion if present. Save the returned
    detached binding; after_skill consumes the same binding after commit.
    """
    row = _attack_source(prepared, member)
    if row is None or program.get('static_fields', {}).get('kind', context.get('skill_kind')) not in ('physical', 'magical'):
        return None
    _context(context)
    if type(context.get('turn')) is not int or not isinstance(token, str) or not token:
        raise ValueError('Trait attack needs an explicit turn and unique action token')
    for source in row.get('sources', [row]):
        if source['when'] == 'entered' and member.get('trait_attack_aura') != _aura(source, member):
            raise ValueError('Entry lifesteal was not granted for this owned entry')
    hp_after_payment = member['hp']
    if 'health_payment' in context:
        from lab import payment_runtime as payment
        supplied = context['health_payment']
        expected = payment.quote(prepared, member, program['game_id'], supplied.get('total_cost'))
        if fingerprint(supplied) != fingerprint(expected):
            raise ValueError('Lifesteal HP predicate requires the unmodified health-payment quote')
        hp_after_payment -= expected['paid_hp']
    percent = _percent(row, hp_after_payment, member['max_hp'])
    if percent:
        _overlap(program, member)
    binding = {'policy': POLICY, 'config_sha256': CONFIG_SHA256,
        'trait_id': row['trait_id'], 'source_hash': row['record_hash'],
        'member_id': member['member_id'], 'form_id': member['form_id'],
        'skill_id': program['game_id'], 'skill_source_hash': program['source_hash'],
        'turn': context['turn'], 'token': token, 'hp_after_payment': hp_after_payment,
        'max_hp': member['max_hp'], 'percent': percent,
        'source_kind': row.get('source_kind', 'trait'),
        'sources': deepcopy(row.get('sources')),
        'skill_lifesteal_grant': deepcopy(row.get('skill_lifesteal_grant'))}
    binding['binding_hash'] = fingerprint(binding)
    return binding


def after_skill(prepared, state, side, program, damage_events, binding, *, context):
    """Commit the trait heal once; callbacks/partial or nominal damage are unused."""
    if binding is None:
        return []
    _context(context)
    member = _active(state, side)
    row = _attack_source(prepared, member)
    if (row is None or binding.get('policy') != POLICY or binding.get('config_sha256') != CONFIG_SHA256
            or binding.get('binding_hash') != fingerprint({k: v for k, v in binding.items() if k != 'binding_hash'})
            or binding.get('member_id') != member['member_id'] or binding.get('form_id') != member['form_id']
            or binding.get('source_hash') != row['record_hash'] or binding.get('trait_id') != row['trait_id']
            or binding.get('source_kind') != row.get('source_kind', 'trait')
            or binding.get('skill_lifesteal_grant') != row.get('skill_lifesteal_grant')
            or binding.get('sources') != row.get('sources')
            or binding.get('skill_id') != program['game_id'] or binding.get('skill_source_hash') != program['source_hash']
            or binding.get('turn') != state['turn'] or binding.get('max_hp') != member['max_hp']
            or type(binding.get('hp_after_payment')) is not int or not 0 < binding['hp_after_payment'] <= member['max_hp']):
        raise ValueError('Trait lifesteal attack binding changed')
    percent = _percent(row, binding['hp_after_payment'], member['max_hp'])
    if type(binding.get('percent')) is not int or binding['percent'] != percent:
        raise ValueError('Trait lifesteal rate differs from its source and HP predicate')
    deferred, component_ids = [], set()
    for event in damage_events:
        if event.get('op') != 'hp.drain.deferred':
            continue
        index = event.get('component_index')
        components = program.get('mechanism_components', [])
        if type(index) is not int or not 0 <= index < len(components) or index in component_ids:
            raise ValueError('Duplicate or invalid deferred lifesteal component')
        component = components[index]
        if (component.get('op') != 'hp.drain' or component.get('target') != 'self'
                or event.get('percent') != component.get('percent') or type(event.get('percent')) is not int
                or event['percent'] < 0 or event.get('source_skill_id') != program['game_id']
                or event.get('source_hash') != program['source_hash'] or event.get('binding_hash') != binding['binding_hash']
                or event.get('stacking_rule') != stacking_rule()):
            raise ValueError('Deferred lifesteal source differs from committed attack')
        component_ids.add(index)
        deferred.append(deepcopy(event))
    percent += sum(event['percent'] for event in deferred)
    ledger = member.get('trait_attack_events', [])
    if (not isinstance(ledger, list) or any(not isinstance(e, dict) or set(e) != {'token', 'binding_hash'}
            or not isinstance(e['token'], str) or not isinstance(e['binding_hash'], str) for e in ledger)
            or len({e['token'] for e in ledger}) != len(ledger)):
        raise ValueError('Malformed trait lifesteal event ledger')
    prior = next((e for e in ledger if e['token'] == binding['token']), None)
    if prior:
        if prior['binding_hash'] != binding['binding_hash']:
            raise ValueError('Trait lifesteal token reused for a different attack')
        return []
    current, events = deepcopy(state), []
    actor = _active(current, side)
    if percent and actor['hp'] > 0:
        _overlap(program, member, damage_events)
        losses, seen = [], set()
        for event in damage_events:
            if event.get('op') not in ('damage', 'damage.hit') or event.get('target') != 'opponent':
                continue
            params = event.get('resolved_params', event.get('params', {}))
            if params.get('kind') not in ('physical', 'magical'):
                continue
            damage, before, after = (event.get(key) for key in ('damage', 'before', 'after'))
            if (any(type(v) is not int for v in (damage, before, after))
                    or not 0 <= after <= before or damage != before - after):
                raise ValueError('Lifesteal requires committed integer actual HP-loss events')
            identity = fingerprint(event)
            if damage and identity in seen:
                raise ValueError('Duplicate actual damage event would repeat lifesteal')
            seen.add(identity)
            losses.append(damage)
        damage = sum(losses)
        if damage:
            # Reuse common HP restoration for exact arithmetic, floor and cap.
            # This equals the existing mechanism drain total-loss experiment.
            heal_program = {'game_id': row.get('source_buff_id') or row['trait_id'], 'category': 'skill', 'status': 'compiled', 'blockers': [],
                'snapshot_id': prepared.snapshot_id, 'source_hash': row['record_hash'],
                'operations': [{'op': 'hp.restore', 'params': {'target': 'self',
                    'percent': {'numerator': damage * percent, 'denominator': 100 * actor['max_hp']}}}]}
            other = 'b' if side == 'a' else 'a'
            relative = {'self': deepcopy(actor), 'opponent': deepcopy(_active(current, other))}
            for key in relative:
                relative[key]['types'] = deepcopy(prepared._rules.form(relative[key]['form_id'])['types'])
            heal_context = {'mode': 'isolated_skill_experiment', 'snapshot_id': prepared.snapshot_id,
                'source_hash': row['record_hash'], 'excluded_hooks': sorted(HOOKS), 'unresolved_dependencies': [],
                'operation_order': 'source_text_order_experiment',
                'hp_policy': {'percentage_basis': 'declared_max_hp', 'rounding': 'floor', 'cap': 'clamp_to_declared_max'}}
            result = execute_effects(heal_program, relative, heal_context)
            if result['status'] != 'applied':
                raise ValueError('Trait lifesteal common restoration blocked: ' + '; '.join(result['blockers']))
            for key,sid in (('self',side),('opponent',other)):
                target=_active(current,sid);updated=result['state'][key]
                if 'types' not in target:updated.pop('types',None)
                target.clear();target.update(updated)
            events.extend({**e, 'trait_id': row['trait_id'], 'trait_source_hash': row['record_hash'],
                'lifesteal_source_kind': row.get('source_kind', 'trait'),
                'skill_lifesteal_grant': deepcopy(row.get('skill_lifesteal_grant')),
                'actor_side': side, 'actor_member_id': actor['member_id'], 'damage_basis': damage,
                'hit_losses': losses, 'lifesteal_percent': percent, 'hp_predicate_snapshot': binding['hp_after_payment'],
                'lifesteal_sources': deepcopy(row.get('sources', [row])), 'deferred_skill_lifesteal': deepcopy(deferred),
                'stacking_rule': stacking_rule(),
                'trait_attack_policy': POLICY, 'trait_attack_policies': deepcopy(POLICIES),
                'trait_attack_config_hash': CONFIG_SHA256,
                'attack_token': binding['token']} for e in result['events'])
    actor['trait_attack_events'] = [*deepcopy(ledger), {'token': binding['token'], 'binding_hash': binding['binding_hash']}]
    state.clear(); state.update(current)
    return events
