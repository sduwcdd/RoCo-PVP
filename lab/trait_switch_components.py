"""Whole-source switch/slot traits composed with existing effects and switches."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from lab.prepared_rules import prepare_rules
from lab.ruleset import canonical_hash

CONFIG = Path(__file__).resolve().parents[1] / 'data/rules/reviewed-trait-switch-components-20261030.json'
CONFIG_SHA256 = '704203af7246615f4c78151e88c35a27499e85c8f4efd93e2c0e2fe784227d30'
POLICY = 'source_bound_switch_slot_components_current_first_own_wing_v2'


@lru_cache(maxsize=2)
def _configuration(stamp):
    raw = CONFIG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONFIG_SHA256:
        raise ValueError('Switch-trait component configuration changed')
    data = json.loads(raw)
    if data.get('policy') != POLICY:
        raise ValueError('Unknown switch-trait policy')
    for row in data['skills']:
        if canonical_hash(row['raw']) != row['record_hash']:
            raise ValueError('Switch-trait whole source differs')
    return data


def _data():
    return _configuration(CONFIG.stat().st_mtime_ns)


def trait_rows():
    rows = {r['trait_id']: deepcopy(r) for r in _data()['skills']}
    from lab.victory_rules import _loss_data
    loss = _loss_data().get('direct_defeat_extras', {}).get('200211')
    if (not loss or loss.get('record_hash') != rows[200211]['record_hash']
            or loss.get('roles') != ['target'] or loss.get('amount') != 1):
        rows.pop(200211)
    return rows


def _row(prepared, member):
    prepared = prepare_rules(prepared)
    tid = prepared._rules.form(member['form_id']).get('trait_id')
    row = next((r for r in _data()['skills'] if r['trait_id'] == tid), None)
    if row is None:
        return None
    if (member.get('trait_id', tid) != tid or prepared.snapshot_id != _data()['snapshot_id']
            or prepared._rules._catalog['traits'].get(str(tid)) != row['raw']):
        raise ValueError('Switch-trait member/source identity differs')
    return row


def _active(state, side):
    team = state['teams'][side]
    return team['members'][team['active_slot']]


def _receipt(state, token, payload):
    if not isinstance(token, str) or not token:
        raise ValueError('Switch-trait effect requires its committed event token')
    signature = canonical_hash(payload)
    rows = state.setdefault('trait_switch_receipts', {})
    if token in rows:
        if rows[token] != signature:
            raise ValueError('Switch-trait token reused with another source')
        return False
    rows[token] = signature
    return True


def _effects(prepared, state, owner, opponent, row, operations, token):
    """Execute source-backed components, including real immunity and restore hooks."""
    from lab.effect_runtime import execute_effects
    from lab.research_phases import _fragment, _devotion_seed
    program = {'category': 'skill', 'game_id': row['trait_id'], 'status': 'compiled',
        'snapshot_id': prepared.snapshot_id, 'source_hash': row['record_hash'],
        'blockers': [], 'dependency_ids': [], 'operations': deepcopy(operations),
        'term_source': deepcopy(prepared._rules.evidence('Terms')), 'modifier_source_kind': 'trait'}
    context = {**_fragment(program, _devotion_seed(state)), 'resolved_energy_cost': 0, 'turn': state['turn']}
    relative = {'self': deepcopy(owner), 'opponent': deepcopy(opponent)}
    original_types = {'self': 'types' in owner, 'opponent': 'types' in opponent}
    for actor in relative.values():
        actor.setdefault('types', deepcopy(prepared._rules.form(actor['form_id'])['types']))
    result = execute_effects(program, relative, context)
    if result['status'] != 'applied':
        raise ValueError('Switch-trait components blocked: ' + '; '.join(result['blockers']))
    for key in original_types:
        if not original_types[key]:
            result['state'][key].pop('types', None)
    owner.clear(); owner.update(result['state']['self'])
    opponent.clear(); opponent.update(result['state']['opponent'])
    return [{**e, 'source_trait_id': row['trait_id'], 'source_hash': row['record_hash'],
             'trait_switch_token': token, 'trait_switch_policy': POLICY}
            for e in result['events'] if e['op'] != 'energy.pay']


def _immune_grant(member, status, row, token):
    grant = {'status': status, 'source_trait_id': row['trait_id'], 'source_hash': row['record_hash'],
             'config_sha256': CONFIG_SHA256, 'token': token, 'departure': 'clear'}
    member.setdefault('successor_status_immunities', []).append(grant)
    return {'op': 'trait.successor.immunity', 'member_id': member['member_id'], **deepcopy(grant)}


def status_immune(member, status):
    found = False
    grants = member.get('successor_status_immunities', [])
    if not isinstance(grants, list) or any(not isinstance(grant, dict) for grant in grants):
        raise ValueError('Successor immunities must retain their source record list')
    for grant in grants:
        row = next((r for r in _data()['skills'] if r['trait_id'] == grant.get('source_trait_id')), None)
        allowed = 'leech' if grant.get('source_trait_id') == 200202 else 'freeze' if grant.get('source_trait_id') == 200253 else None
        if (row is None or allowed is None or grant.get('source_hash') != row['record_hash'] or grant.get('status') != allowed
                or grant.get('config_sha256') != CONFIG_SHA256 or grant.get('departure') != 'clear'):
            raise ValueError('Successor immunity source changed')
        found |= status == allowed
    return found


def clear_successor_effects(member):
    status_immune(member, 'freeze')
    removed = member.pop('successor_status_immunities', [])
    source = next(r for r in _data()['skills'] if r['trait_id'] == 200253)
    for attribute, terms in list(member.get('stat_modifiers', {}).items()):
        records = {r['index']: r for r in member.get('stat_modifier_sources', {}).get(attribute, [])}
        kept, ledger = [], []
        for index, term in enumerate(terms):
            record = records.get(index)
            if record and record.get('source_kind') == 'trait' and record.get('source_id') == 200253:
                if record.get('source_hash') != source['record_hash'] or record.get('term') != term:
                    raise ValueError('Successor defense modifier source changed')
                removed.append(deepcopy(record))
                continue
            kept.append(term)
            if record:
                ledger.append({**record, 'index': len(kept) - 1})
        member['stat_modifiers'][attribute] = kept
        if attribute in member.get('stat_modifier_sources', {}):
            member['stat_modifier_sources'][attribute] = ledger
    return [{'op': 'trait.successor.clear', 'member_id': member['member_id'], 'removed': removed}] if removed else []


def after_switch(prepared, state, side, outgoing_id, incoming_id, *, token):
    if 'trait_policy' not in state:
        return []
    prepared = prepare_rules(prepared)
    team = state['teams'][side]
    outgoing = next(m for m in team['members'] if m['member_id'] == outgoing_id)
    incoming = next(m for m in team['members'] if m['member_id'] == incoming_id)
    if incoming['hp'] <= 0 or _active(state, side) is not incoming:
        raise ValueError('Switch-trait transition requires the actual living successor')
    if not _receipt(state, token, {'side': side, 'from': outgoing_id, 'to': incoming_id, 'turn': state['turn']}):
        return []
    events = clear_successor_effects(outgoing)
    other_side = 'b' if side == 'a' else 'a'
    observer = _active(state, other_side)
    predecessor_row, observer_row = _row(prepared, outgoing), _row(prepared, observer)
    mirrors = [(m, r) for m, r in ((outgoing, predecessor_row), (observer, observer_row))
               if r and r['trait_id'] == 200142 and m['hp'] > 0 and m['member_id'] != incoming_id]
    if len(mirrors) > 1:
        raise ValueError('Simultaneous HP-percentage reflection order remains unresolved')
    for owner, row in mirrors:
        events += _effects(prepared, state, owner, incoming, row,
            [{'op': 'hp.exchange_ratio', 'params': {'target': 'self',
               'policy': 'simultaneous_max_hp_ratio_floor_min_one_living_experiment_v1'}}], token)
    if observer_row and observer_row['trait_id'] == 200156 and observer['hp'] > 0:
        events += _effects(prepared, state, observer, incoming, observer_row,
            [{'op': 'status.add', 'params': {'target': 'opponent', 'status': 'poison', 'stacks': 5}}], token)
    if predecessor_row and predecessor_row['trait_id'] == 200202:
        events += _effects(prepared, state, incoming, observer, predecessor_row,
            [{'op': 'hp.restore', 'params': {'target': 'self', 'percent': {'numerator': 20, 'denominator': 100}}}], token)
        events.append(_immune_grant(incoming, 'leech', predecessor_row, token))
    if predecessor_row and predecessor_row['trait_id'] == 200253:
        events += _effects(prepared, state, incoming, observer, predecessor_row,
            [{'op': 'stat.modify', 'params': {'target': 'self', 'attributes': ['pdef', 'mdef'],
                'percent': {'numerator': 20, 'denominator': 100}}}], token)
        events.append(_immune_grant(incoming, 'freeze', predecessor_row, token))
    return [{**e, 'switch_side': side, 'departing_member_id': outgoing_id, 'entering_member_id': incoming_id} for e in events]


def transmission_grants(member):
    """Grant the current first slot at this transmission phase, once per pass."""
    if member.get('trait_id') not in (200171, 200234):
        return {}
    row = next(r for r in _data()['skills'] if r['trait_id'] == member['trait_id'])
    if member.get('trait_source_hash') != row['record_hash']:
        raise ValueError('Transmission grant lost its trait source')
    slots = member.get('skill_slots')
    if not isinstance(slots, list) or len(slots) != 4:
        raise ValueError('Transmission grant requires four ordered current slots')
    if not slots[0]:
        return {}
    return {0: {'amount': 1, 'source_trait_id': row['trait_id'],
        'source_hash': row['record_hash'], 'config_sha256': CONFIG_SHA256}}


def swift_grants(prepared, state, member):
    prepared = prepare_rules(prepared)
    row = _row(prepared, member)
    if row is None or row['trait_id'] not in (200211, 200234):
        return {}
    granted = [0] if row['trait_id'] == 200234 else []
    if row['trait_id'] == 200211:
        teams = [team for team in state['teams'].values()
                 if any(m['member_id'] == member['member_id'] for m in team['members'])]
        if len(teams) != 1:
            raise ValueError('Wing shared-skill grant requires one actual owning team')
        others = [m for m in teams[0]['members']
                  if m['member_id'] != member['member_id'] and '翼系' in prepared._rules.form(m['form_id'])['types']]
        granted = [slot for slot, mid in enumerate(member['skill_slots']) if mid and any(mid in m['skill_slots'] for m in others)]
    return {slot: {'trait_id': row['trait_id'], 'source_hash': row['record_hash'], 'record': deepcopy(row['raw']),
            'swift_granted': True, 'slot_allowed': True, 'slot': slot,
            'skill_source_hash': canonical_hash(prepared._rules.skill(member['skill_slots'][slot])),
            'policy': POLICY, 'config_sha256': CONFIG_SHA256} for slot in granted if member['skill_slots'][slot]}


def after_action(prepared, state, side, action, *, token):
    if 'trait_policy' not in state:
        return []
    prepared = prepare_rules(prepared)
    member = _active(state, side)
    row = _row(prepared, member)
    if (row is None or row['trait_id'] != 200171 or action.get('kind') != 'skill'
            or action.get('execution_phase') == 'charge_setup_not_attack_release'):
        return []
    slot = action.get('slot')
    if type(slot) is not int or not 0 <= slot < 4:
        raise ValueError('Greedy algorithm requires the committed skill slot')
    if action.get('actor_member_id') != member['member_id']:
        raise ValueError('Greedy algorithm requires the actual committed skill actor')
    # action.slot records selection before the skill can move its own slots.
    if slot != 0:
        return []
    if not _receipt(state, token, {'trait_id': row['trait_id'], 'member_id': member['member_id'],
                                  'turn': state['turn'], 'skill_id': action['skill_id'], 'selected_slot': slot}):
        return []
    opponent = _active(state, 'b' if side == 'a' else 'a')
    if opponent['hp'] <= 0:
        return []
    return _effects(prepared, state, member, opponent, row,
        [{'op': 'status.add', 'params': {'target': 'opponent', 'status': 'burn', 'stacks': 6}}], token)


def on_event(prepared, state, event_name, side=None, member_id=None, token=None, context=None):
    if event_name != 'turn.end':
        return []
    prepared = prepare_rules(prepared)
    from lab import forced_switch_runtime as forced
    events = []
    for owner_side in (('a', 'b') if side is None else (side,)):
        active = _active(state, owner_side)
        if active['hp'] <= 0 or active['energy'] != 0:
            continue
        team = state['teams'][owner_side]
        candidates = [(slot, m) for slot, m in enumerate(team['members']) if slot != team['active_slot']
                      and m['hp'] > 0 and (_row(prepared, m) or {}).get('trait_id') == 200166]
        if len(candidates) > 1:
            raise ValueError('Multiple zero-energy replacement owners need a verified trigger order')
        if not candidates:
            continue
        slot, replacement = candidates[0]
        if not isinstance(token, str) or not token:
            raise ValueError('Zero-energy replacement needs the actual round-end event token')
        marker = token + ':star:' + owner_side
        if not _receipt(state, marker, {'turn': state['turn'], 'from': active['member_id'], 'to': replacement['member_id']}):
            continue
        result = forced.execute_forced_switch_fragment(prepared, state, owner_side, 'detach', target_slot=slot,
            context={**deepcopy(context or {}), 'snapshot_id': prepared.snapshot_id,
                     'forced_switch_policies': forced.policies(), 'event_token': marker})
        if result['status'] != 'applied':
            raise ValueError('Zero-energy ally replacement blocked: ' + '; '.join(result.get('blockers', [])))
        state.clear(); state.update(result['state'])
        events += result['events']
    return events


def retaliation_request(prepared, member):
    row = _row(prepare_rules(prepared), member)
    if row is None or row['trait_id'] != 200103:
        return None
    return retaliation_source(member)


def retaliation_source(member):
    if member.get('trait_id') != 200103 or 'trait_policy' not in member:
        return None
    from lab.trait_runtime import POLICY as TRAIT_POLICY
    row = next(r for r in _data()['skills'] if r['trait_id'] == 200103)
    if member['trait_policy'] != TRAIT_POLICY or member.get('trait_source_hash') != row['record_hash']:
        raise ValueError('Thorns retaliation requires its exact bound trait source')
    return {'source_trait_id': 200103, 'source_hash': row['record_hash'], 'config_sha256': CONFIG_SHA256,
            'policy': POLICY, 'power': 50, 'kind': 'physical', 'type': '无系别', 'effect_id': 1001013,
            'stab': 1, 'type_multiplier': 1, 'can_trigger_retaliation': False}
