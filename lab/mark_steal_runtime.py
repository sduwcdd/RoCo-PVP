"""Source-bound one-mark transfer; ambiguous selection/replacement fails closed."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from lab.game_runtime_defaults import ROOT
from lab.phase_config import fingerprint
from lab.prepared_rules import prepare_rules
from lab import mark_runtime as marks, trait_runtime as traits

CONFIG = ROOT / 'data/rules/reviewed-mark-steal-1.json'
CONFIG_SHA256 = 'd2e8e97230a684d04eb0035d1d91ef067f52f537e0f22c638a112689a93861ef'
POLICY = 'unique_enemy_mark_same_kind_or_empty_recipient_one_layer_transfer_v1'


@lru_cache(maxsize=2)
def _configuration(stamp):
    raw = CONFIG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONFIG_SHA256:
        raise ValueError('Mark steal configuration changed; review required')
    return json.loads(raw)


@lru_cache(maxsize=16)
def _source_hash(path, size, stamp):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _data():
    data = _configuration(CONFIG.stat().st_mtime_ns)
    for relative, expected in data['sources'].items():
        path = (ROOT / relative).resolve(); stat = path.stat()
        if not path.is_relative_to(ROOT) or _source_hash(str(path), stat.st_size, stat.st_mtime_ns) != expected:
            raise ValueError('Mark steal extracted source changed')
    return data


def research_context():
    return {'mark_steal_policy': POLICY}


def _context(context):
    if context.get('mark_steal_policy') != POLICY or context.get('mark_policies') != marks.POLICIES:
        raise ValueError('Explicit conservative mark-transfer and mark ownership policies required')


def programs(catalog):
    prepared, data = prepare_rules(catalog), _data()
    record = prepared._rules.skill(data['skill']['record']['id'])
    if prepared.snapshot_id != data['snapshot_id'] or fingerprint(record) != data['skill']['record_hash']:
        raise ValueError('Mark steal whole source changed')
    mid = record['id']
    program = deepcopy(prepared._rules.program(mid))
    program.pop('native_rule', None)
    program.update(status='compiled', blockers=[], operations=[{'op': 'damage', 'params': {
        'target': 'opponent', 'kind': record['kind'], 'power': record['power'], 'type': record['type']}}],
        mark_steal_components={'op': 'mark.steal', 'amount': 1}, mark_steal_config_hash=CONFIG_SHA256,
        mark_steal_evidence=deepcopy(data['skill']), mark_steal_policy=POLICY, response_kinds=[],
        executable=False, training_eligible=False, real_game_verified=False)
    return {mid: program}


def _active(state, side):
    team = state['teams'][side]
    return team['members'][team['active_slot']]


def _relative(state, side):
    other = 'b' if side == 'a' else 'a'
    return {'self': {'field_marks': deepcopy(state['teams'][side]['marks'])},
            'opponent': {'field_marks': deepcopy(state['teams'][other]['marks'])}}


def _primitive(state, side, source, context):
    return marks.steal_one_mark(_relative(state, side), context=context, source=source,
                               eligible_buff_ids=_data()['eligibility_buff_ids'])


def preflight(catalog, state, side, program, *, context):
    prepared = prepare_rules(catalog); _context(context)
    expected = programs(prepared).get(program.get('game_id'))
    if expected is None or fingerprint(expected) != fingerprint(program):
        raise ValueError('Mark steal program differs from source-bound whole description')
    return _primitive(state, side, {'policy': POLICY, 'source_id': program['game_id'],
                                  'source_hash': program['source_hash']}, context)


def _apply(state, side, *, source_id, source_hash, event_token, context):
    if not isinstance(event_token, str) or not event_token:
        raise ValueError('Mark transfer needs a unique nonempty source-event token')
    ledger = state.get('mark_steal_events', {})
    if not isinstance(ledger, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in ledger.items()):
        raise ValueError('Malformed mark-steal event ledger')
    actor = _active(state, side)
    identity = fingerprint({'turn': state['turn'], 'side': side, 'member_id': actor['member_id'],
        'source_id': source_id, 'source_hash': source_hash, 'policy': POLICY})
    if event_token in ledger:
        if ledger[event_token] != identity:
            raise ValueError('Mark-steal event token reused for a different source')
        return []
    if (source_id == _data()['skill']['record']['id']
            and context.get('faint_policy') == 'stop_remaining_skill_on_exhaustion_experiment'
            and any(_active(state, target)['hp'] <= 0 for target in ('a', 'b'))):
        state['mark_steal_events'] = {**ledger, event_token: identity}
        return [{'op': 'mark.steal.skipped', 'reason': 'exhaustion', 'source_id': source_id,
                 'source_hash': source_hash, 'event_token': event_token, 'mark_steal_policy': POLICY}]
    source = {'policy': POLICY, 'source_id': source_id, 'source_hash': source_hash,
              'actor_side': side, 'actor_member_id': actor['member_id'], 'event_token': event_token}
    fragment = _primitive(state, side, source, context)
    other = 'b' if side == 'a' else 'a'
    for relative, absolute in [('self', side), ('opponent', other)]:
        state['teams'][absolute]['marks'] = fragment['state'][relative]['field_marks']
    state['mark_steal_events'] = {**ledger, event_token: identity}
    return [{**event, 'target_side': side if event['target'] == 'self' else other,
        'actor_side': side, 'actor_member_id': actor['member_id'], 'source_id': source_id,
        'source_hash': source_hash, 'mark_steal_policy': POLICY} for event in fragment['events']]


def after_skill(catalog, state, side, program, *, event_token, context):
    prepared = prepare_rules(catalog)
    _context(context)
    expected = programs(prepared).get(program.get('game_id'))
    if expected is None or fingerprint(expected) != fingerprint(program):
        raise ValueError('Mark steal program differs from source-bound compilation')
    current = deepcopy(state)
    events = _apply(current, side, source_id=program['game_id'], source_hash=program['source_hash'],
                    event_token=event_token, context=context)
    state.clear(); state.update(current)
    return events


def _eligible_trait(prepared, state, side):
    if state.get('trait_policy') != traits.POLICY:
        return False
    actor, data = _active(state, side), _data()
    form = data['forms'].get(str(actor['form_id']))
    if form is None or actor['hp'] <= 0:
        return False
    if (prepared.snapshot_id != data['snapshot_id'] or actor.get('trait_policy') != traits.POLICY
            or actor.get('trait_id') != data['trait']['record']['id']
            or fingerprint(prepared._rules.form(actor['form_id'])) != form['record_hash']
            or fingerprint(prepared._rules._catalog['traits'][str(actor['trait_id'])]) != data['trait']['record_hash']):
        raise ValueError('Mark-stealing trait differs from its form/source binding')
    return True


def round_end(catalog, state, *, context):
    prepared = prepare_rules(catalog); _context(context)
    owners = [side for side in ('a', 'b') if _eligible_trait(prepared, state, side)]
    if len(owners) == 2 and any(mark for team in state['teams'].values() for mark in team['marks'].values()):
        raise ValueError('Simultaneous mark-stealing traits have no source-resolved execution order')
    current, events = deepcopy(state), []
    data = _data()
    for side in owners:
        events.extend(_apply(current, side, source_id=data['trait']['record']['id'],
            source_hash=data['trait']['record_hash'], event_token=f"{state['turn']}:{side}:trait.mark.steal", context=context))
    state.clear(); state.update(current)
    return events
