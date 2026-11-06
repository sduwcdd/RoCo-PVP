"""Source-bound trait components sharing the bounded event/effect executors."""
from copy import deepcopy
from fractions import Fraction
from functools import lru_cache, wraps
from contextlib import contextmanager
from contextvars import ContextVar
import json
import hashlib
from pathlib import Path

from lab.event_scheduler import dispatch_events
from lab.effect_runtime import execute_effects, _state
from lab.ruleset import canonical_hash

POLICY = 'source_bound_trait_events_research_v1'
CONFIG = Path(__file__).resolve().parents[1] / 'data/rules/reviewed-trait-events-1.json'
CONFIG_HASH = '366a0b451fec26783e982423d2784551b2313b163aa9ae4cd69ccc0aa54b3daa'
ROOT = CONFIG.parents[2]
CONFIRMED_CONFIG = ROOT / 'data/rules/reviewed-user-traits-20261030.json'
CONFIRMED_CONFIG_HASH = 'f8be1dcd03a268d53c0a40ad31039707221a930852278788d2980e16921211e0'
EVENTS = {'damage.super_effective', 'member.enter', 'member.leave', 'opponent.leave', 'skill.after', 'action.after', 'charge.start', 'turn.end', 'attack.received', 'attack.skill_received', 'member.faint', 'opponent.defeated'}
CONDITIONS = {'energy_eq', 'skill_type', 'skill_kind', 'base_cost_eq', 'response_success',
              'skill_type_not', 'base_cost_gt', 'base_cost_lte', 'skill_id', 'not_same_type', 'attack_type_carried', 'attacker_stab', 'attacker_energy_eq', 'skill_kind_in', 'entry_first_action','first_attack','first_action','energy_spent_eq'}

_QUERY = ContextVar('trait_read_query', default=None)


@contextmanager
def query_scope():
    """Verify immutable sources once per operation; never cache battle state."""
    if _QUERY.get() is not None:
        yield
        return
    data = _data()
    token = _QUERY.set((data, _combined_rows(data), {}))
    try:
        yield
    finally:
        _QUERY.reset(token)


def cached_source_query(load):
    """Reuse verified immutable source data only inside this operation's scope."""
    @wraps(load)
    def query():
        scope = _QUERY.get()
        if scope is None:
            return load()
        cache = scope[2]
        if load not in cache:
            cache[load] = load()
        return cache[load]
    return query


@lru_cache(maxsize=2)
def _load(stamp):
    data = json.loads(CONFIG.read_text(encoding='utf-8'))
    if data.get('schema') != 'trait-events-1' or data.get('policy') != POLICY or canonical_hash(data) != CONFIG_HASH:
        raise ValueError('Trait component configuration changed; source review required')
    return data


@lru_cache(maxsize=16)
def _source_hash(path, size, stamp):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _data():
    if _QUERY.get() is not None:
        return _QUERY.get()[0]
    data = _load(CONFIG.stat().st_mtime_ns)
    for source in data['sources'].values():
        path = (ROOT / source['path']).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError('Trait evidence path leaves the project')
        stat = path.stat()
        if _source_hash(str(path), stat.st_size, stat.st_mtime_ns) != source['sha256']:
            raise ValueError('Trait extracted source changed; review required')
    return data


def _rows():
    if _QUERY.get() is not None:
        return _QUERY.get()[1]
    return _combined_rows(_data())


@lru_cache(maxsize=2)
def _confirmed_configuration(stamp):
    raw = CONFIRMED_CONFIG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONFIRMED_CONFIG_HASH:
        raise ValueError('User-confirmed trait configuration changed')
    return json.loads(raw)


def _confirmed_rows():
    data = _confirmed_configuration(CONFIRMED_CONFIG.stat().st_mtime_ns)
    return {row['trait_id']:row for row in data['skills']}


def _combined_rows(data):
    rows = {row['trait_id']:row for row in data['skills']}
    for tid, row in _confirmed_rows().items():
        if tid in rows:
            raise ValueError('User-confirmed trait duplicates an existing whole trait')
        _validate_runtime_delegate(row)
        rows[tid] = {**row,'raw':row['record'],'event':'confirmed.runtime'}
    try:
        from lab.trait_switch_components import trait_rows
    except ModuleNotFoundError as exc:
        if exc.name!='lab.trait_switch_components':raise
    else:
        for tid,row in trait_rows().items():
            if tid in rows:raise ValueError('Trait switch delegate duplicates whole trait source')
            rows[tid]=row
    return rows


def policies():
    return deepcopy(_data()['policies'])


def _enabled(state):
    if 'trait_policy' not in state:
        return False
    if state['trait_policy'] != POLICY:
        raise ValueError('Unknown trait research policy')
    return True


def _validate_modifiers(member):
    values = member.get('trait_modifiers', {})
    records = member.get('trait_modifier_sources', [])
    if (not isinstance(values, dict) or set(values) - {'cost', 'power'}
            or any(type(v) is not int for v in values.values()) or not isinstance(records, list)):
        raise ValueError('Malformed trait modifiers')
    totals, seen = {}, set()
    for record in records:
        row = _rows().get(record.get('trait_id')) if isinstance(record, dict) else None
        field = record.get('field') if isinstance(record, dict) else None
        if (not row or field not in ('cost', 'power') or record.get('policy') != POLICY
                or (record.get('trait_id') != member.get('trait_id') and not any(h.get('trait_id')==record.get('trait_id') and h.get('trait_source_hash')==record.get('source_hash') for h in member.get('evolution_trait_history',[])))
                or record.get('source_hash') != row['record_hash']
                or record.get('member_id') != member.get('member_id')
                or type(record.get('amount')) is not int
                or type(record.get('turn')) is not int or record['turn'] < 1
                or not isinstance(record.get('token'), str) or len(record['token']) != 64
                or not any(c.get('op') == ('skill.cost_all' if field == 'cost' else 'skill.power_all')
                           and (max(-c['max_magnitude'],min(c['max_magnitude'],totals.get(field,0)+c['amount']))-totals.get(field,0)
                                if 'max_magnitude' in c else c.get('amount')) == record['amount'] for c in row['components'])):
            raise ValueError('Trait modifier source differs from reviewed component')
        identity = (record['turn'], record['token'], field)
        if identity in seen:
            raise ValueError('Duplicate trait modifier source event')
        seen.add(identity)
        totals[field] = totals.get(field, 0) + record['amount']
    if values != totals:
        raise ValueError('Trait modifier totals require their matching source ledger')


def component_support(prepared, trait_id):
    """Report independently executable components without claiming whole-trait support."""
    from lab import payment_runtime, trait_attack_hooks, mechanism_runtime, victory_rules
    scope = _QUERY.get()
    cache = scope[2] if scope is not None else {}
    key = (prepared.catalog_content_hash, trait_id)
    if key in cache:
        return list(cache[key])
    if 'component_sources' not in cache:
        cache['component_sources'] = (payment_runtime._data(), trait_attack_hooks._data(),
            mechanism_runtime._configuration(mechanism_runtime.CONFIG.stat().st_mtime_ns),
            victory_rules._loss_data())
    payment, attack, mechanism, loss = cache['component_sources']
    found = []
    for row in payment['components']:
        if row['kind'] == 'trait' and row['source_id'] == trait_id:
            found.append(('生命代付能量', row['record_hash']))
    row = attack['traits'].get(str(trait_id))
    if row:
        found.append(('吸血', row['record_hash']))
    for row in mechanism.get('trait_hits', []):
        if row['trait_id'] == trait_id:
            found.append(('连击增益', row['record_hash']))
    row = loss['traits'].get(str(trait_id))
    if row:
        found.append(('倒下魔力损耗', row['record_hash']))
    expected = canonical_hash(prepared._rules._catalog['traits'].get(str(trait_id)))
    if any(source != expected for _, source in found):
        raise ValueError('Trait component description source changed')
    support = tuple(name for name, _ in found)
    cache[key] = support
    return list(support)


def bind(prepared, state):
    if not _enabled(state):
        return
    current = deepcopy(state)
    _bind_owned(prepared, current)
    state.clear(); state.update(current)


def _bind_owned(prepared, current):
    """Validate/install on an already isolated state; callers own the commit."""
    data = _data()
    if current.get('snapshot_id') != prepared.snapshot_id:
        raise ValueError('Trait battle snapshot differs from its source')
    if current.get('trait_config_hash', CONFIG_HASH) != CONFIG_HASH or current.get('trait_policies', policies()) != policies():
        raise ValueError('Trait source/policies changed; start or replay the battle')
    if type(current.get('turn')) is not int or current['turn'] < 1 or set(current['teams']) != {'a', 'b'}:
        raise ValueError('Trait battle requires two sides and a positive integer turn')
    seen = set()
    for team in current['teams'].values():
        if (not isinstance(team.get('members'), list) or not team['members']
                or type(team.get('active_slot')) is not int or not 0 <= team['active_slot'] < len(team['members'])):
            raise ValueError('Malformed trait team roster/active slot')
        for member in team['members']:
            mid = member.get('member_id')
            if not isinstance(mid, str) or not mid or mid in seen:
                raise ValueError('Trait members need unique nonempty IDs')
            seen.add(mid)
            form = prepared._rules.form(member['form_id'])
            tid = form.get('trait_id')
            row = _rows().get(tid)
            if tid==200318 and 'gene_editing_base_cost' not in member and current['turn']==1:
                member['gene_editing_base_cost']={'first_turn_original':True,'from_turn':0,
                    'source_hash':row['record_hash'],'config_sha256':CONFIRMED_CONFIG_HASH}
            if tid==200318 and member.get('gene_editing_base_cost',{}).get('first_turn_original') and current['turn']!=1:
                raise ValueError('Gene editing previous-round actual payment snapshot is missing')
            if row and any(c['op']=='initial.energy_zero' for c in row['components']) and not member.get('confirmed_initial_energy_set'):
                if current['turn'] != 1 or current.get('actual_skill_payments'):
                    raise ValueError('Initial-zero-energy trait needs fresh battle initialization or explicit saved marker')
                member['energy']=0
                member['confirmed_initial_energy_set']=True
            if row and any(c['op']=='stat.calendar' for c in row['components']):
                date_value,weekday=validate_calendar(current.get('trait_calendar'))
                binding={'date':date_value,'weekday':weekday,'policy':policies()['calendar'],'source_hash':row['record_hash']}
                if member.get('trait_calendar_binding',binding)!=binding:
                    raise ValueError('Trait calendar binding changed within the owned battle state')
                member['trait_calendar_binding']=binding
            from lab.action_traits import evidence as action_trait_evidence
            action_evidence = action_trait_evidence(prepared, current, member)
            from lab.forced_trait_runtime import evidence as forced_trait_evidence
            forced_evidence = forced_trait_evidence(prepared, current, member)
            evidence = row or data['weather_trait_sources'].get(str(tid))
            if evidence is None and forced_evidence:
                evidence = {'record_hash': forced_evidence['source_hash']}
            if evidence is None and action_evidence:
                evidence = {'record_hash': action_evidence['source_hash']}
            if evidence and canonical_hash(prepared._rules._catalog['traits'][str(tid)]) != evidence['record_hash']:
                raise ValueError('Trait source changed: ' + str(tid))
            if member.get('trait_id', tid) != tid or member.get('trait_policy', POLICY) != POLICY:
                raise ValueError('Member trait identity/policy differs from its source form')
            source_hash = evidence['record_hash'] if evidence else None
            if (member.get('trait_source_hash', source_hash) != source_hash
                    or member.get('trait_config_hash', CONFIG_HASH) != CONFIG_HASH):
                raise ValueError('Member trait source binding changed')
            if any(key in member for key in ('field_marks','team_devotion','trait_team_roster','trait_team_fainted_counts','trait_carried_costs')):
                raise ValueError('Temporary team mark fields must not persist on a trait member')
            member['trait_id'] = tid
            member['trait_component_support'] = component_support(prepared, tid)
            member['trait_policy'] = POLICY
            member['trait_supported'] = row is not None or action_evidence is not None or forced_evidence is not None
            member['trait_weather_supported'] = row is None and action_evidence is None and forced_evidence is None and evidence is not None
            member['trait_support_scope'] = 'reviewed_events' if row else 'reviewed_action_rules' if action_evidence else 'reviewed_departure_rules' if forced_evidence else 'weather_module_subset' if evidence else 'unsupported'
            member['trait_source_hash'] = source_hash
            member['requires_departure_choice'] = bool(forced_evidence and forced_evidence['components']['cause'] == 'detach')
            member['trait_config_hash'] = CONFIG_HASH
            validate_energy_attack_stats(member)
            validate_paid_energy(member)
            member['trait_current_skill_types'] = [prepared._rules.skill(mid)['type'] if mid else None for mid in member['skill_slots']]
            priority_bonus(member)
            if 'trait_skill_cooldowns' in member:
                from lab.duration_runtime import trait_cooldowns
                trait_cooldowns(member)
            once = member.get('trait_once_events', {})
            if not isinstance(once, dict) or any(str(tid) != key or not row or not row.get('once_per_battle')
                    or value != row['record_hash'] for key,value in once.items()):
                raise ValueError('Once-per-battle trait history source changed')
            member['allowed_skill_slots'] = deepcopy(action_evidence['components'].get('allowed_slots', [0, 1, 2, 3])) if action_evidence else [0, 1, 2, 3]
            if row and any(c['op'].endswith('.initial_carried') for c in row['components']):
                initial = member.setdefault('trait_initial_skill_ids', deepcopy(member['skill_slots']))
                if not isinstance(initial, list) or len(initial) != 4 or any(type(mid) is not int or mid < 0 for mid in initial):
                    raise ValueError('Initial carried trait requires four source skill slots')
                types = [prepared._rules.skill(mid)['type'] if mid else None for mid in initial]
                if member.get('trait_initial_skill_types', types) != types:
                    raise ValueError('Initial carried trait types differ from source skill IDs')
                member['trait_initial_skill_types'] = types
            if 'types' in member and member['types'] != form['types']:
                raise ValueError('Trait member types conflict with its source form')
            if member.get('trait_form_types',form['types']) != form['types']:
                raise ValueError('Trait-owned form types differ from source')
            member['trait_form_types']=deepcopy(form['types'])
            typed = {**member, 'types': deepcopy(form['types'])}
            _state({'self': typed, 'opponent': typed})
            _validate_modifiers(member)
            event_stat_layers(member)
            _overheal_progress(member)
            if any(record['turn'] > current['turn'] for record in member.get('trait_modifier_sources', [])):
                raise ValueError('Trait modifier source occurs after the current turn')
    current.update(trait_config_hash=CONFIG_HASH, trait_policies=policies())


def _active(state, side):
    team = state['teams'][side]
    return team['members'][team['active_slot']]


def _match(row, member, payload):
    cond = row['when']
    if not isinstance(cond, dict) or set(cond) - CONDITIONS:
        raise ValueError('Unknown trait condition; complete source review required')
    if any(key in cond for key in ('base_cost_eq', 'base_cost_gt', 'base_cost_lte')) and payload.get('energy') is not None:
        if type(payload['energy']) is not int or payload['energy'] < 0:
            raise ValueError('Trait base-cost predicate needs a nonnegative integer source cost')
    checks = {'energy_eq': member['energy'], 'skill_type': payload.get('type'),
              'skill_kind': payload.get('kind'), 'base_cost_eq': payload.get('energy'),
              'response_success': payload.get('response_success'), 'skill_id': payload.get('id', payload.get('game_id'))}
    checks.update({key: payload.get(key) for key in ('attack_type_carried', 'attacker_stab', 'attacker_energy_eq')})
    for key, value in cond.items():
        if key == 'energy_spent_eq':
            ledger=validate_paid_energy(member)
            if (ledger['total'] if ledger else 0) != value:return False
        if key in ('first_attack','first_action'):
            if type(payload.get(key)) is not bool:
                raise ValueError('Order-dependent trait requires an explicit resolved order Boolean')
            if payload[key] != value: return False
        if key == 'skill_kind_in' and payload.get('kind') not in value:
            return False
        if key == 'entry_first_action':
            if 'entry_first_action' in payload:
                if type(payload['entry_first_action']) is not bool:
                    raise ValueError('Entry action predicate must be Boolean')
                if payload['entry_first_action'] != value: return False
                continue
            count = member.get('mark_entry_actions')
            if type(count) is not int or count < 0:
                raise ValueError('Burst trait requires owned entry action count')
            if (count == 0) != value:
                return False
        if key in checks and checks[key] != value:
            return False
        if key == 'skill_type_not' and (not isinstance(payload.get('type'), str) or payload['type'] == value):
            return False
        if key == 'base_cost_gt' and (payload.get('energy') is None or payload['energy'] <= value):
            return False
        if key == 'base_cost_lte' and (payload.get('energy') is None or payload['energy'] > value):
            return False
        if key == 'not_same_type':
            if value is not True or not member.get('types') or not isinstance(payload.get('type'), str):
                raise ValueError('Non-STAB trait needs explicit source types and skill type')
            if payload['type'] in member['types']:
                return False
    return True


def _passive(member, event, payload):
    if not _enabled(member) or member['hp'] <= 0:
        return []
    row = _rows().get(member.get('trait_id'))
    if row and (member.get('trait_config_hash') != CONFIG_HASH or member.get('trait_source_hash') != row['record_hash']):
        raise ValueError('Passive trait source binding changed')
    return row['components'] if row and row['event'] == event and _match(row, member, payload) else []


def energy_allows_overflow(member):
    """Validate stored overflow even after exhaustion; never change max_energy."""
    if not _enabled(member):
        return False
    row = _rows().get(member.get('trait_id'))
    if row and (member.get('trait_config_hash') != CONFIG_HASH or member.get('trait_source_hash') != row['record_hash']):
        raise ValueError('Energy-cap trait source changed')
    return bool(row and row['event'] == 'energy.cap' and row['components'] == [{'op':'energy.uncapped'}])


def buff_extra_layers(member, source_category, requested_layers):
    if type(requested_layers) is not int or requested_layers < 0:
        raise ValueError('Buff layers require an integer nonnegative count')
    components = _passive(member, 'buff.layers', {})
    if not components or not requested_layers:
        return requested_layers
    if source_category == 'unknown':
        raise ValueError('Extra-buff-layer trait requires decoded source BUFF type')
    if source_category not in ('buff','debuff','other','mark','trait'):
        raise ValueError('Unknown modifier source category')
    return requested_layers + (sum(c['amount'] for c in components) if source_category == 'buff' else 0)


def fixed_hits(state):
    sources = []
    if _enabled(state):
        for side in ('a','b'):
            member = _active(state, side)
            for component in _passive(member, 'hits.query', {}):
                sources.append({'trait_id':member['trait_id'],'source_hash':member['trait_source_hash'],
                    'member_id':member['member_id'],'side':side,'count':component['count']})
    counts = {source['count'] for source in sources}
    if len(counts) > 1:
        raise ValueError('Conflicting source fixed-hit auras; precedence is unverified')
    return {'count':next(iter(counts),None), 'sources':sources, 'policy':policies()['fixed_hits']}


def validate_fixed_hits(context):
    count, sources = context.get('fixed_hit_count'), context.get('fixed_hit_sources', [])
    if count is None and not sources:
        return None
    if (type(count) is not int or count < 1 or not isinstance(sources,list) or not sources
            or context.get('fixed_hit_policy') != policies()['fixed_hits']):
        raise ValueError('Fixed-hit override requires explicit source evidence')
    seen = set()
    for source in sources:
        row = _rows().get(source.get('trait_id')) if isinstance(source,dict) else None
        if (row is None or row['event'] != 'hits.query' or source.get('source_hash') != row['record_hash']
                or source.get('count') != count or row['components'] != [{'op':'hits.fixed','count':count}]
                or source.get('side') not in ('a','b') or not isinstance(source.get('member_id'),str)
                or not source['member_id'] or source['side'] in seen):
            raise ValueError('Fixed-hit source/count differs from reviewed aura')
        seen.add(source['side'])
    return count


def priority_bonus(member):
    entry = member.get('trait_next_priority')
    if entry is None:
        return 0
    row = _rows().get(entry.get('trait_id')) if isinstance(entry,dict) else None
    if (not _enabled(member) or row is None or member.get('trait_source_hash') != row['record_hash']
            or member.get('trait_config_hash') != CONFIG_HASH
            or row['components'] != [{'op':'next.priority','target':'self','amount':1}]
            or entry != {'trait_id':member.get('trait_id'),'source_hash':row['record_hash'],
                         'member_id':member['member_id'],'amount':1,'policy':policies()['next_priority']}):
        raise ValueError('Pending trait priority source changed')
    return entry['amount']


def consume_priority(member):
    if not priority_bonus(member):
        return []
    return [{'op':'trait.priority.consume','target_member_id':member['member_id'],
             'source':member.pop('trait_next_priority')}]


def after_opponent_skill(prepared, state, actor_side, skill_id, *, token):
    if not _enabled(state):
        return []
    owner_side = 'b' if actor_side == 'a' else 'a'
    if actor_side not in ('a','b'):
        raise ValueError('Invalid acting side for opponent skill trigger')
    owner = _active(state, owner_side)
    components = _passive(owner, 'opponent.skill.after', {})
    if not components:
        return []
    prepared._rules.skill(skill_id)
    from lab.duration_runtime import install_trait_cooldown
    event = install_trait_cooldown(_active(state,actor_side),owner['trait_id'],owner['trait_source_hash'],
        skill_id,state['turn'],token=token)
    return [{**event,'target_side':actor_side,'source_member_id':owner['member_id']}] if event else []


def after_outcome(prepared, state, side, action, events, *, token, context=None):
    """Use the already committed direct-defeat proof, before replacement."""
    if not _enabled(state): return []
    from lab.action_outcome_runtime import validate_direct_defeat
    payment_events=[]
    actor=_active(state,side)
    if action.get('kind')=='skill':
        payments=[e['amount'] for e in events if e.get('op')=='energy.pay' and e.get('target')=='self']
        if any(type(v) is not int or v<0 for v in payments):raise ValueError('Committed payment trace is not actual integer energy')
        payment_events=record_paid_energy(actor,sum(payments),state['turn'],token)
    other = 'b' if side == 'a' else 'a'
    target = _active(state,other)
    if action.get('kind')=='skill':
        payment_events.extend(record_actual_payment(prepared,state,side,{**action,'response_success':(context or {}).get('response_success',action.get('response_success'))},sum(payments),token=token))
    payment_events.extend(after_super_effective_damage(prepared,state,side,events,token=token,context=context))
    proof = state.get('knockout_provenance',{}).get(other,{}).get(target['member_id'])
    if not proof or proof.get('action_token') != token: return payment_events
    validate_direct_defeat(proof)
    if (proof['attacker_side'] != side or proof['attacker']['member_id'] != action['actor_member_id']
            or proof['skill_id'] != action['skill_id'] or target['hp'] != 0):
        raise ValueError('Trait defeat trigger differs from committed proof')
    return payment_events + run_event(prepared,state,'opponent.defeated',side=side,
        member_id=action['actor_member_id'],token=proof['proof_hash'],context=context)


def validate_paid_energy(member):
    ledger=member.get('trait_paid_energy')
    if ledger is None:return None
    row=_rows().get(member.get('trait_id'))
    if (not isinstance(ledger,dict) or row is None or 'energy_tracking' not in row or not _enabled(member)
            or member.get('trait_source_hash')!=row['record_hash'] or member.get('trait_config_hash')!=CONFIG_HASH):
        raise ValueError('Paid energy tracker source changed')
    payments=ledger.get('payments')
    if (not isinstance(payments,list) or any(not isinstance(p,dict) or set(p)!={'amount','turn','token'}
            or type(p['amount']) is not int or p['amount']<=0 or type(p['turn']) is not int or p['turn']<1
            or not isinstance(p['token'],str) or not p['token'] for p in payments)
            or len({p['token'] for p in payments})!=len(payments)):
        raise ValueError('Malformed committed energy payment history')
    expected={'source_trait_id':row['trait_id'],'source_hash':row['record_hash'],'buff_id':row['energy_tracking']['buff_id'],
        'total':min(row['energy_tracking']['cap'],sum(p['amount'] for p in payments)),
        'payments':payments,'policy':policies()['energy_spent']}
    if ledger!=expected:raise ValueError('Paid energy total differs from actual payment history')
    return ledger


def record_paid_energy(member, amount, turn, token):
    row=_rows().get(member.get('trait_id'))
    if not _enabled(member) or row is None or 'energy_tracking' not in row:return []
    if member.get('trait_source_hash')!=row['record_hash'] or member.get('trait_config_hash')!=CONFIG_HASH:
        raise ValueError('Payment tracker owner source changed')
    ledger=validate_paid_energy(member)
    if type(amount) is not int or amount<0 or type(turn) is not int or turn<1 or not isinstance(token,str) or not token:
        raise ValueError('Energy tracking requires actual positive payment provenance')
    if not amount:return []
    payments=deepcopy(ledger['payments']) if ledger else []
    record={'amount':amount,'turn':turn,'token':token}
    old=next((p for p in payments if p['token']==token),None)
    if old:
        if old!=record:raise ValueError('Payment token reused for different energy loss')
        return []
    payments.append(record)
    member['trait_paid_energy']={'source_trait_id':row['trait_id'],'source_hash':row['record_hash'],
        'buff_id':row['energy_tracking']['buff_id'],'total':min(row['energy_tracking']['cap'],sum(p['amount'] for p in payments)),
        'payments':payments,'policy':policies()['energy_spent']}
    validate_paid_energy(member)
    return [{'op':'trait.energy_spent.record','payment':record,'total':member['trait_paid_energy']['total']}]


def after_faint(prepared, state, side, member_id, *, occurrence):
    """Call from the real living-to-zero occurrence observer, before replacement."""
    if not _enabled(state): return []
    if type(occurrence) is not int or occurrence < 1:
        raise ValueError('Faint trait requires an owned positive knockout occurrence')
    owner = next((m for m in state['teams'][side]['members'] if m['member_id']==member_id),None)
    if owner is None or owner['hp'] != 0:
        raise ValueError('Faint trait owner must be the exhausted member')
    ledger = owner.setdefault('trait_faint_occurrences', {})
    key = str(occurrence)
    if key in ledger:
        if ledger[key] != owner.get('trait_source_hash'): raise ValueError('Faint occurrence source changed')
        return []
    events = run_event(prepared,state,'member.faint',side=side,member_id=member_id,token=f'faint:{member_id}:{occurrence}')
    owner = next(m for m in state['teams'][side]['members'] if m['member_id']==member_id)
    owner.setdefault('trait_faint_occurrences', {})[key] = owner.get('trait_source_hash')
    return events


def modify_cost(member, opponent, skill, value):
    if not _enabled(member):
        return value
    _validate_modifiers(member)
    if type(value) is not int or value < 0:
        raise ValueError('Trait cost input must be a nonnegative integer')
    delta = member.get('trait_modifiers', {}).get('cost', 0) if member['hp'] > 0 else 0
    snapshot = _entry_history_snapshot(member, field='cost_delta')
    if snapshot:
        delta += snapshot.get('cost_delta',0)
    for component in _passive(member, 'cost.query', skill) + _passive(opponent, 'opponent.cost.query', skill):
        factor = _initial_count(member, component['carried_type']) if component['op'] == 'cost.initial_carried' else 1
        delta += component['amount'] * factor
    return max(0, value + cost_delta(member,delta))


def cost_delta(member, amount):
    """Transform each provider's signed change before its existing zero clamp."""
    if type(amount) is not int:
        raise ValueError('Cost effect delta must be an integer')
    for component in _passive(member,'cost.delta',{}):
        amount *= component['factor']
    return amount


def status_extra_layers(source_member, status, requested):
    if type(requested) is not int or requested < 0:
        raise ValueError('Status application requires integer nonnegative layers')
    return requested + (sum(c['amount'] for c in _passive(source_member,'status.layers',{})
        if c['status'] == status) if requested else 0)


def _existing_buff_layers(member, buff_id, field):
    from lab.modifier_ledger import flat_info, _verify_stat_record
    count = 0
    if field in ('patk','matk','pdef','mdef'):
        for record in member.get('stat_modifier_sources',{}).get(field,[]):
            if record.get('source_kind') == 'skill' or 'buff_id' in record:
                _verify_stat_record(field,record)
                info = record['classification']
                if buff_id in info.get('buff_ids',[]): count += info['layers']
    else:
        key = 'skill_modifiers' if field == 'skill.cost' else 'mechanism_flat_modifiers'
        for record in member.get(key,[]):
            if key == 'mechanism_flat_modifiers' and record['op'] != field: continue
            if 'buff_id' in record or 'source_skill_id' in record:
                info = flat_info(record,key)
                if buff_id in info.get('buff_ids',[]): count += info['layers']
    return count


def after_status_gain(state, target, status, actual_gain, context):
    """Mutate owned relative state once after positive opponent stack gain."""
    if type(actual_gain) is not int or actual_gain < 0:
        raise ValueError('Status trait needs actual nonnegative layer gain')
    if target != 'opponent' or not actual_gain:
        return []
    owner, recipient = state['self'], state['opponent']
    components = _passive(owner,'status.inflicted',{})
    if not components and _enabled(owner) and owner['hp'] > 0:
        # _passive validates source binding even for the entry+status composite.
        components = _rows().get(owner.get('trait_id'),{}).get('status_gain_components',[])
    components = [c for c in components if c['status'] == status]
    if not components or recipient['hp'] <= 0: return []
    turn = context.get('turn')
    if type(turn) is not int or turn < 1:
        raise ValueError('Status-derived modifiers require an explicit turn')
    from lab.mechanism_runtime import POLICY as mechanism_policy
    from lab.modifier_ledger import register_stat
    emitted=[]
    for component in components:
        field = 'skill.cost' if component['op'] == 'status.cost' else 'speed.flat' if component['op'] == 'status.speed' else component['attribute']
        unit = component.get('unit',1)
        requested = component.get('amount',component.get('percent'))//unit
        layers = min(requested,max(0,component['max_layers']-_existing_buff_layers(recipient,component['buff_id'],field)))
        if not layers: continue
        amount = layers*unit
        source = {'source_trait_id':owner['trait_id'],'source_hash':owner['trait_source_hash'],
            'buff_id':component['buff_id'],'policy':mechanism_policy,'amount':amount}
        if field == 'skill.cost':
            recipient.setdefault('skill_modifiers',[]).append({**source,'skill_id':0,'applied_turn':turn,'expires_after':None})
        elif field == 'speed.flat':
            recipient.setdefault('mechanism_flat_modifiers',[]).append({**source,'op':'speed.flat'})
        else:
            recipient.setdefault('stat_modifiers',{}).setdefault(field,[]).append({'numerator':amount,'denominator':100})
            register_stat(recipient,field,source_kind='trait',source_id=owner['trait_id'],source_hash=owner['trait_source_hash'],buff_id=component['buff_id'])
        emitted.append({'op':'trait.status_derived','target':'opponent','status':status,'actual_gain':actual_gain,
            'field':field,'amount':amount,'layers':layers,'source':source,'policy':policies()['status_inflicted']})
    return emitted


def modify_power(member, skill, value, *, opponent=None, first_attack=None):
    if not _enabled(member):
        return value
    _validate_modifiers(member)
    if member['hp'] <= 0:
        return value
    value += member.get('trait_modifiers', {}).get('power', 0)
    payload = {**skill, 'first_attack':first_attack} if first_attack is not None else skill
    snapshot = _entry_history_snapshot(member, field='power_add')
    if snapshot:
        value += snapshot.get('power_add',0)
    confirmed=_confirmed_member(member)
    if confirmed and confirmed['trait_id']==200192:
        if not isinstance(opponent,dict):raise ValueError('Foreign-bloodline power needs an exact opponent')
        if bloodline_relation(opponent)['foreign_type']:value*=2
    for component in _passive(member, 'power.query', payload):
        if component['op'] == 'power.add':
            value += component['amount']
        elif component['op'] == 'power.opponent_buff_layers':
            value *= 1+Fraction(component['percent_per']*_opponent_buff_layers(opponent),100)
        elif component['op'] == 'power.opponent_types':
            types = opponent.get('trait_current_skill_types') if isinstance(opponent,dict) else None
            if not isinstance(types,list) or len(types) != 4:
                raise ValueError('Power query requires current source-resolved opposing carried types')
            value += len(set(t for t in types if t is not None)) * component['amount']
        elif component['op'] == 'power.opponent_total_cost':
            value *= 1 + Fraction(component['percent_per']*min(component['cap'],_carried_cost_total(opponent)),100)
        elif component['op'] == 'power.initial_carried':
            value *= 1 + Fraction(component['percent_per'] * _initial_count(member, component['carried_type']), 100)
        elif component['op'] == 'power.opponent_marks':
            if not isinstance(opponent, dict) or 'field_marks' not in opponent:
                raise ValueError('Mark-dependent trait power requires owned opposing team marks')
            from lab.mark_runtime import layer_count
            value *= 1 + Fraction(component['percent_per'] * layer_count(opponent, component['mark_id']), 100)
        else:
            value *= Fraction(component['percent'], 100)
    return value


def _initial_count(member, skill_type):
    types = member.get('trait_initial_skill_types')
    if not isinstance(types, list) or len(types) != 4:
        raise ValueError('Trait needs the source-bound initial carried skill snapshot')
    return types.count(skill_type)


def requires_cost_snapshot(member):
    if not _enabled(member) or member.get('hp',0)<=0:return False
    _passive(member,'cost.snapshot',{})
    return any(c['op'] in ('stat.own_total_cost','power.opponent_total_cost')
        for c in _rows().get(member.get('trait_id'),{}).get('components',[]))


def _carried_cost_total(member):
    costs=member.get('trait_carried_costs') if isinstance(member,dict) else None
    slots=member.get('skill_slots') if isinstance(member,dict) else None
    if (not isinstance(costs,list) or len(costs)!=4 or not isinstance(slots,list) or len(slots)!=4
            or any((value is not None if slots[i]==0 else type(value) is not int or value<0) for i,value in enumerate(costs))):
        raise ValueError('Trait total-cost query requires source-aligned current four-slot execution costs')
    return sum(value for value in costs if value is not None)


def party_fainted_count(member, scopes=('self',)):
    """Use synchronized public totals when individual hidden members are absent."""
    counts = member.get('trait_team_fainted_counts')
    if counts is not None:
        if not isinstance(counts, dict) or any(type(counts.get(s)) is not int or not 0 <= counts[s] <= 6 for s in scopes):
            raise ValueError('Party fainted query requires valid synchronized counts')
        return sum(counts[s] for s in scopes)
    roster = member.get('trait_team_roster')
    if not isinstance(roster, dict) or any(not isinstance(roster.get(s), list) for s in scopes):
        raise ValueError('Party fainted query requires owned team rosters or synchronized counts')
    members = [m for s in scopes for m in roster[s]]
    if any(not isinstance(m, dict) or type(m.get('hp')) is not int or m['hp'] < 0 for m in members):
        raise ValueError('Party fainted query contains unknown HP')
    return sum(m['hp'] == 0 for m in members)


def stat_terms(member, attribute, turn, *, opponent=None):
    """Pure additive percentage terms, never permanently append dynamic buffs."""
    terms = []
    snapshot = _entry_history_snapshot(member, field=attribute)
    if snapshot and attribute in snapshot.get('stats',{}):
        terms.append({'numerator':snapshot['stats'][attribute],'denominator':100})
    components = _passive(member, 'stats.query', {})
    if not components and _enabled(member) and member['hp'] > 0:
        components = _rows().get(member.get('trait_id'),{}).get('stat_query_components',[])
    for component in components:
        if attribute not in component['attributes']:
            continue
        if component['op'] == 'stat.energy':
            energy = member.get('energy')
            if type(energy) is not int or energy < 0:
                raise ValueError('Dynamic energy defense needs an integer energy count')
            amount = min(component['cap'], energy) * component['percent_per']
        elif component['op'] == 'stat.calendar':
            binding=member.get('trait_calendar_binding')
            if not isinstance(binding,dict) or binding.get('source_hash')!=member['trait_source_hash']:
                raise ValueError('Calendar trait requires its source-bound explicit game date')
            _,weekday=validate_calendar({'date':binding.get('date'),'policy':binding.get('policy')})
            if binding.get('weekday')!=weekday:raise ValueError('Calendar weekday differs from explicit date')
            attrs=component['weekend_attributes'] if weekday>=5 else component['weekday_attributes']
            amount=component['percent'] if attribute in attrs else 0
        elif component['op'] == 'stat.own_total_cost':
            amount=component['percent'] if _carried_cost_total(member)<component['less_than'] else 0
        elif component['op'] == 'stat.entry_turn':
            if type(turn) is not int or type(member.get('entered_turn')) is not int:
                raise ValueError('Entry stat query needs owned absolute turns')
            amount = component['percent'] if turn == max(1, member['entered_turn']) else 0
        elif component['op'] == 'stat.opponent_marks':
            if not isinstance(opponent,dict) or 'field_marks' not in opponent:
                raise ValueError('Dynamic stat query requires opposing team marks')
            from lab.mark_runtime import layer_count
            amount = min(component['cap'],layer_count(opponent,component['mark_id'])) * component['percent_per']
        elif component['op'] == 'stat.field_buff_kinds':
            from lab.modifier_ledger import buff_kind_ids
            if not isinstance(opponent,dict):
                raise ValueError('Field buff-kind query requires the owned opposing member')
            identities=set(buff_kind_ids(member)) | set(buff_kind_ids(opponent))
            amount=min(component['cap'],len(identities))*component['percent_per']
        elif component['op'] == 'stat.field_mark_kinds':
            from lab.mark_runtime import validate_marks
            identities=set()
            for owner in (member,opponent):
                if not isinstance(owner,dict) or 'field_marks' not in owner:
                    raise ValueError('Field mark-kind query requires both owned team mark slots')
                validate_marks(owner['field_marks'])
                identities.update(mark['id'] for mark in owner['field_marks'].values() if mark is not None)
            amount=min(component['cap'],len(identities))*component['percent_per']
        elif component['op'] == 'stat.overheal':
            amount=min(99,_overheal_progress(member)[1])*component['percent_per']
        elif component['op'] == 'stat.event_layers':
            amount=event_stat_layers(member)*component['percent_per']
        elif component['op'] == 'stat.entry_party':
            snapshot = member.get('trait_entry_party')
            if snapshot is None: continue
            if (not isinstance(snapshot,dict) or snapshot.get('source_hash') != member['trait_source_hash']
                    or type(snapshot.get('count')) is not int or not 0 <= snapshot['count'] <= component['cap']
                    or snapshot.get('policy')!=policies()['party_counts'] or type(snapshot.get('turn')) is not int
                    or not 1 <= snapshot['turn'] <= turn):
                raise ValueError('Entry party stat query requires its sourced entry snapshot')
            amount = snapshot['count']*component['percent_per']
        elif component['op'] == 'stat.entry_magic':
            snapshot = member.get('trait_entry_magic')
            if snapshot is None: continue
            if (not isinstance(snapshot,dict) or snapshot.get('source_hash') != member['trait_source_hash']
                    or type(snapshot.get('triggered')) is not bool or type(snapshot.get('observed_magic')) is not int
                    or snapshot['observed_magic']<0 or snapshot['triggered'] != (snapshot['observed_magic']==1)
                    or snapshot.get('policy')!=policies()['entry_magic'] or type(snapshot.get('turn')) is not int
                    or not 1 <= snapshot['turn'] <= turn):
                raise ValueError('Entry magic query requires its source-bound condition snapshot')
            amount = component['percent'] if snapshot['triggered'] else 0
        elif component['op'] == 'stat.energy_pending':
            entry=validate_energy_attack_stats(member)
            amount=entry['layers']*component['percent_per'] if entry else 0
        elif component['op'] == 'stat.party_fainted':
            scopes = ('self','opponent') if component['scope']=='both' else ('self',)
            amount = min(component['cap'], party_fainted_count(member, scopes)) * component['percent_per']
        elif component['op'] == 'stat.party_type_exists':
            roster = member.get('trait_team_roster')
            if not isinstance(roster,dict) or set(roster) != {'self','opponent'}:
                raise ValueError('Party stat query requires temporary owned team rosters')
            for members in roster.values():
                if not isinstance(members,list) or any(not isinstance(m,dict) or type(m.get('hp')) is not int
                        or m['hp'] < 0 or not isinstance(m.get('types'),list) or not m.get('member_id') for m in members):
                    raise ValueError('Invalid temporary party stat roster')
            amount = component['percent'] if any(component['type'] in m['types'] for m in roster['self']) else 0
        else:
            raise ValueError('Unknown dynamic trait stat query')
        if amount:
            terms.append({'numerator':amount, 'denominator':100})
    return terms


def hit_bonus(member, opponent=None):
    bonus = 0
    for component in _passive(member,'hits.dynamic',{}):
        if component['op'] == 'hits.hp_missing':
            hp, maximum = member.get('hp'), member.get('max_hp')
            if type(hp) is not int or type(maximum) is not int or not 0 <= hp <= maximum or maximum <= 0:
                raise ValueError('HP hit threshold requires valid integer current/max HP')
            bonus += min(component['max_bonus'],((maximum-hp)*100//(maximum*component['threshold_percent']))*component['amount'])
        elif component['op'] == 'hits.opponent_status':
            if not isinstance(opponent,dict) or not isinstance(opponent.get('statuses'),dict):
                raise ValueError('Poison-dependent hits require current opposing statuses')
            count = opponent['statuses'].get(component['status'],0)
            if type(count) is not int or count < 0:
                raise ValueError('Poison layers must be nonnegative integers')
            bonus += min(component['cap'],count)*component['amount']
    return bonus


def after_energy_gain(member, actual_gain, context):
    """Actual gain after suppression/cap, floor one heal and never revive."""
    if type(actual_gain) is not int or actual_gain < 0:
        raise ValueError('Trait recovery requires a nonnegative integer actual gain')
    components = _passive(member, 'energy.gain', {})
    if not actual_gain or not components:
        return []
    if type(context.get('turn')) is not int or context['turn'] < 1:
        raise ValueError('Trait recovery requires an explicit turn')
    if any(c['op']=='stat.energy_pending' for c in components):
        entry=validate_energy_attack_stats(member)
        gains=deepcopy(entry['gains']) if entry else []
        gains.append({'actual_gain':actual_gain,'turn':context['turn']})
        before=entry['layers'] if entry else 0
        member['trait_energy_attack_layers']={'trait_id':member['trait_id'],'source_hash':member['trait_source_hash'],
            'buff_id':components[0]['buff_id'],'layers':min(components[0]['cap'],before+actual_gain),
            'gains':gains,'policy':policies()['energy_attack_stats']}
        return [{'op':'trait.energy_attack_stats','before':before,'after':member['trait_energy_attack_layers']['layers'],
            'actual_energy_gain':actual_gain,'source_trait_id':member['trait_id'],'source_hash':member['trait_source_hash'],
            'policy':policies()['energy_attack_stats']}]
    before = member['hp']
    amount = member['max_hp'] * sum(c['percent_per'] for c in components) * actual_gain // 100
    member['hp'] = min(member['max_hp'], before + amount)
    return [{'op':'trait.energy_gain_heal','before':before,'after':member['hp'],
        'amount':member['hp']-before,'actual_energy_gain':actual_gain,'trait_id':member['trait_id'],
        'source_hash':member['trait_source_hash'],'policy':policies()['actual_energy_gain']}]


def validate_energy_attack_stats(member):
    entry=member.get('trait_energy_attack_layers')
    if entry is None: return None
    row=_rows().get(member.get('trait_id'))
    if (not isinstance(entry,dict) or row is None or row['event']!='energy.gain'
            or row['components'][0]['op']!='stat.energy_pending' or not _enabled(member)
            or member.get('trait_source_hash')!=row['record_hash'] or member.get('trait_config_hash')!=CONFIG_HASH):
        raise ValueError('Pending energy stat source differs from its owner')
    gains=entry.get('gains')
    if not isinstance(gains,list) or not gains or any(not isinstance(g,dict) or set(g)!={'actual_gain','turn'}
            or type(g['actual_gain']) is not int or g['actual_gain']<=0 or type(g['turn']) is not int or g['turn']<1 for g in gains):
        raise ValueError('Pending energy stats require actual-gain provenance')
    component=row['components'][0]
    expected={'trait_id':row['trait_id'],'source_hash':row['record_hash'],'buff_id':component['buff_id'],
        'layers':min(component['cap'],sum(g['actual_gain'] for g in gains)),'gains':gains,'policy':policies()['energy_attack_stats']}
    if entry!=expected: raise ValueError('Pending energy stat layers were changed')
    return entry


def consume_energy_attack_stats(member, attacked):
    if type(attacked) is not bool: raise ValueError('Energy stat consumption requires explicit attack classification')
    entry=validate_energy_attack_stats(member)
    if not entry or not attacked:return []
    member.pop('trait_energy_attack_layers')
    return [{'op':'trait.energy_attack_stats.consume','source':deepcopy(entry)}]


def after_periodic_loss(state, damaged_side, status, actual_loss, context=None):
    if damaged_side not in ('a','b') or type(actual_loss) is not int or actual_loss < 0:
        raise ValueError('Periodic trait needs an owned target side and actual integer HP loss')
    if not _enabled(state) or not actual_loss: return []
    owner_side = 'b' if damaged_side=='a' else 'a'
    relative={'self':_active(state,owner_side),'opponent':_active(state,damaged_side)}
    events=after_periodic_loss_relative(relative,'opponent',status,actual_loss,context)
    return [{**{k:v for k,v in event.items() if k not in ('target','damaged_target')},
        'target_side':owner_side if event.get('target')=='self' else damaged_side,'damaged_side':damaged_side} for event in events]


def after_periodic_loss_relative(state, damaged_key, status, actual_loss, context=None):
    if damaged_key not in ('self','opponent') or type(actual_loss) is not int or actual_loss < 0:
        raise ValueError('Periodic trait needs a relative target and actual integer HP loss')
    if not actual_loss: return []
    owner_key = 'opponent' if damaged_key=='self' else 'self'
    owner = state[owner_key]
    components = [c for c in _passive(owner,'opponent.periodic_loss',{}) if status in c['statuses']]
    if not components: return []
    before=owner['hp']
    owner['hp']=min(owner['max_hp'],before+actual_loss)
    return [{'op':'trait.periodic_loss_heal','target':owner_key,'target_member_id':owner['member_id'],
        'damaged_target':damaged_key,'status':status,'actual_enemy_hp_loss':actual_loss,'before':before,
        'after':owner['hp'],'amount':owner['hp']-before,'source_trait_id':owner['trait_id'],
        'source_hash':owner['trait_source_hash'],'policy':policies()['periodic_loss_heal']}] + after_hp_restore(
            state,owner_key,actual_loss,owner['hp']-before,context or {})


def damage_multiplier(defender, attacker, skill, *, carried_types, attacker_types):
    """Attack damage only; periodic damage does not pass through this query."""
    payload = {**skill, 'attack_type_carried': skill['type'] in carried_types,
               'attacker_stab': skill['type'] in attacker_types,
               'attacker_energy_eq': attacker['energy']}
    multiplier = Fraction(1)
    for component in _passive(defender, 'damage.query', payload):
        multiplier *= Fraction(component['percent'], 100)
    return multiplier


def run_event(prepared, state, event_name, *, side=None, member_id=None, payload=None, token=None, context=None):
    """Commit this event only after every bounded subscriber succeeds."""
    if not _enabled(state):
        return []
    current = deepcopy(state)
    events = _confirmed_event(prepared,current,event_name,side=side,member_id=member_id,token=token)
    events.extend(_run_event(prepared, current, event_name, side=side, member_id=member_id, payload=payload, token=token, context=context))
    try:
        from lab.trait_switch_components import on_event as switch_trait_event
    except ModuleNotFoundError as exc:
        if exc.name!='lab.trait_switch_components':raise
    else:
        events.extend(switch_trait_event(prepared,current,event_name,side=side,member_id=member_id,token=token,context=context))
    if event_name=='member.leave':
        if side not in ('a','b'):raise ValueError('Departure forwarding needs the actual leaving side')
        events.extend(_run_event(prepared,current,'opponent.leave',side='b' if side=='a' else 'a',
            payload=payload,token=token,context=context))
    state.clear(); state.update(current)
    return events


def after_received_attack(prepared, state, defender_side, damage_events, *, context, token):
    """Per positive committed direct-damage event; never count poison or mark damage."""
    if not _enabled(state):
        return []
    if defender_side not in ('a', 'b') or not isinstance(token, str) or not token:
        raise ValueError('Received-attack traits need a target side and unique attack token')
    current, events, seen = deepcopy(state), [], set()
    for index, event in enumerate(damage_events):
        params = event.get('resolved_params', event.get('params', {}))
        if event.get('op') not in ('damage', 'damage.hit') or event.get('target') != 'opponent' or params.get('kind') not in ('physical', 'magical'):
            continue
        amount, before, after = event.get('damage'), event.get('before'), event.get('after')
        if any(type(value) is not int for value in (amount, before, after)) or amount != before - after or amount < 0:
            raise ValueError('Received-attack trait requires actual integer HP-loss evidence')
        if amount == 0:
            continue
        identity = canonical_hash(event)
        if identity in seen:
            raise ValueError('Duplicate damage event would repeat a received-attack trait')
        seen.add(identity)
        events.extend(run_event(prepared, current, 'attack.received', side=defender_side,
            payload={'damage':amount,'source_damage_event':deepcopy(event)},
            context=context, token=f'{token}:hit:{index}'))
    if seen:
        events.extend(run_event(prepared,current,'attack.skill_received',side=defender_side,
            payload={'positive_damage_hits':len(seen)},context=context,token=f'{token}:whole-skill'))
    state.clear(); state.update(current)
    return events


def _run_event(prepared, state, event_name, *, side=None, member_id=None, payload=None, token=None, context=None):
    if event_name not in EVENTS or side not in (None, 'a', 'b'):
        raise ValueError('Unknown trait event or side')
    if member_id is not None and (not isinstance(member_id, str) or not member_id):
        raise ValueError('Trait member ID must be a nonempty string')
    if payload is not None and not isinstance(payload, dict):
        raise ValueError('Trait payload must be an object')
    if token is not None and (not isinstance(token, str) or not token):
        raise ValueError('Trait idempotency token must be nonempty text')
    _bind_owned(prepared, state)
    payload = deepcopy(payload or {})
    if 'response_success' in payload and type(payload['response_success']) is not bool:
        raise ValueError('Trait response_success must be an explicit Boolean')
    token = token or f"{state['turn']}:{event_name}:{side}:{member_id}"
    token = canonical_hash({'event': event_name, 'side': side, 'member_id': member_id, 'token': token})
    ledger = state.setdefault('trait_events', {'turn': state['turn'], 'tokens': []})
    if (not isinstance(ledger, dict) or type(ledger.get('turn')) is not int or ledger['turn'] > state['turn']
            or not isinstance(ledger.get('tokens'), list)
            or any(not isinstance(t, str) or not t for t in ledger['tokens'])
            or len(ledger['tokens']) != len(set(ledger['tokens']))):
        raise ValueError('Malformed trait event ledger')
    if ledger.get('turn') != state['turn']:
        ledger.update(turn=state['turn'], tokens=[])
    if token in ledger['tokens']:
        return []
    subscriptions, handlers = [], {}
    selected = []
    matched_member = member_id is None
    for owner_side in ('a', 'b'):
        team = state['teams'][owner_side]
        if side is not None and side != owner_side:
            continue
        member = (next((m for m in team['members'] if m['member_id'] == member_id), None)
                  if member_id else team['members'][team['active_slot']])
        matched_member = matched_member or member is not None
        if member and (member['hp'] > 0 or event_name == 'member.faint' and member['hp'] == 0):
            row = _rows().get(member.get('trait_id'))
            if row and row.get('once_per_battle') and str(row['trait_id']) in member.get('trait_once_events', {}):
                if member['trait_once_events'][str(row['trait_id'])] != row['record_hash']:
                    raise ValueError('Once-per-battle trait source changed')
                continue
            if row and row['event'] == event_name and _match(row, member, payload):
                selected.append((owner_side, member['member_id'], row))
    if not matched_member:
        raise ValueError('Trait event member not found on the selected side')
    for order, (owner_side, owner_id, row) in enumerate(selected):
        source = {'rule_id': 'trait:' + str(row['trait_id']), 'component_id': event_name,
                  'snapshot_id': prepared.snapshot_id}
        key = owner_id + ':' + str(row['trait_id'])
        subscriptions.append({'id': key, 'event': event_name, 'handler': key, 'order': order,
                              'max_executions': 1, 'source': source})
        def apply(current, event, owner_side=owner_side, owner_id=owner_id, row=row):
            actor = next(m for m in current['teams'][owner_side]['members'] if m['member_id'] == owner_id)
            other = 'b' if owner_side == 'a' else 'a'
            events = []
            for component in row['components']:
                if not _match({'when': component.get('when', {})}, actor, payload):
                    continue
                op = component['op']
                if op == 'duration.install':
                    from lab.duration_runtime import install_trait_duration
                    target_side=owner_side if component['target']=='self' else other
                    events.extend({**e,'target_side':target_side} for e in install_trait_duration(
                        _active(current,target_side),row['trait_id'],row['record_hash'],current['turn']))
                    continue
                if op == 'energy.refill':
                    amount=max(0,actor['max_energy']-actor['energy'])
                    if not amount:continue
                    component={'op':'energy.restore','target':'self','amount':amount}
                    op=component['op']
                if op == 'hits.action_grant':
                    if _active(current,owner_side)['member_id'] != owner_id:
                        events.append({'op':op,'retained':False,'reason':'source_clears_on_departure','member_id':owner_id})
                        continue
                    from lab.mechanism_runtime import POLICY as mechanism_policy, HIT_POLICY
                    ledger = actor.setdefault('mechanism_flat_modifiers',[])
                    existing = sum(m['amount'] for m in ledger if m.get('source_trait_id')==row['trait_id'] and m.get('op')=='hits.flat')
                    amount = min(component['amount'],max(0,component['max_layers']-existing))
                    if amount:
                        item={'op':'hits.flat','amount':amount,'policy':mechanism_policy,'hit_policy':HIT_POLICY,
                            'source_trait_id':row['trait_id'],'source_hash':row['record_hash'],'source_buff_id':component['buff_id']}
                        ledger.append(item);events.append({**deepcopy(item),'target':'self'})
                    continue
                if op == 'cost.opponent_all':
                    recipient=_active(current,other)
                    if recipient['hp'] <= 0: continue
                    existing=_existing_buff_layers(recipient,component['buff_id'],'skill.cost')
                    amount=min(component['amount'],max(0,component['max_layers']-existing))
                    if amount:
                        from lab.mechanism_runtime import POLICY as mechanism_policy
                        item={'skill_id':0,'amount':amount,'applied_turn':current['turn'],'expires_after':None,
                            'source_trait_id':row['trait_id'],'source_hash':row['record_hash'],
                            'buff_id':component['buff_id'],'policy':mechanism_policy}
                        recipient.setdefault('skill_modifiers',[]).append(item)
                        events.append({'op':op,'target':'opponent',**deepcopy(item)})
                    continue
                if op == 'magic.entry_condition':
                    from lab.victory_rules import validate_victory
                    if not isinstance(current.get('victory'),dict):
                        raise ValueError('Entry magic trait requires the source-bound victory ledger')
                    validate_victory(current)
                    magic_side = owner_side if component['magic_side']=='self' else other
                    value = current['victory']['magic'][magic_side]
                    actor['trait_entry_magic'] = {'triggered':value==component['equals'],'observed_magic':value,
                        'source_hash':row['record_hash'],'turn':current['turn'],'policy':policies()['entry_magic']}
                    events.append({'op':op,**deepcopy(actor['trait_entry_magic'])})
                    continue
                if op == 'party.entry_count':
                    count = sum(component['type'] in prepared._rules.form(m['form_id'])['types']
                        for m in current['teams'][owner_side]['members'] if m['member_id'] != owner_id)
                    actor['trait_entry_party'] = {'count':min(component['cap'],count),'source_hash':row['record_hash'],
                        'turn':current['turn'],'policy':policies()['party_counts']}
                    events.append({'op':op,**deepcopy(actor['trait_entry_party'])})
                    continue
                if op in ('status.initial_carried','status.opponent_marks'):
                    if op == 'status.initial_carried':
                        count = _initial_count(actor,component['carried_type'])
                    else:
                        from lab.mark_runtime import layer_count
                        count = layer_count({'field_marks':current['teams'][other]['marks']},component['mark_id'])
                    if count == 0: continue
                    component = {'op':'status.add','target':component['target'],'status':component['status'],
                                 'stacks':component['stacks_per']*count}
                    op = component['op']
                if op == 'stat.event_layers':
                    before=event_stat_layers(actor)
                    after=min(component['max_layers'],before+component['layers'])
                    actor['trait_event_stat_layers']={'source_trait_id':row['trait_id'],'source_hash':row['record_hash'],
                        'layers':after,'buff_id':component['buff_id'],'policy':policies()['event_stat_layers']}
                    events.append({'op':op,'before':before,'after':after,'buff_id':component['buff_id']})
                    continue
                if op == 'stat.permanent_layers':
                    history = actor.setdefault('trait_permanent_layers', {})
                    key = str(row['trait_id'])
                    old = history.get(key, {'layers':0,'source_hash':row['record_hash']})
                    if (not isinstance(old,dict) or old.get('source_hash') != row['record_hash']
                            or type(old.get('layers')) is not int or not 0 <= old['layers'] <= component['max_layers']):
                        raise ValueError('Permanent trait stat layer source changed')
                    layers = min(component['max_layers'],old['layers']+component['layers'])
                    from lab.modifier_ledger import register_stat
                    for attribute in component['attributes']:
                        if layers == old['layers']: continue
                        actor.setdefault('stat_modifiers',{}).setdefault(attribute,[]).append(
                            {'numerator':(layers-old['layers'])*component['percent_per'],'denominator':100})
                        register_stat(actor,attribute,source_kind='trait',source_id=row['trait_id'],
                            source_hash=row['record_hash'])
                    history[key] = {'layers':layers,'source_hash':row['record_hash']}
                    events.append({'op':'trait.permanent_layers','before':old['layers'],'after':layers,'source_trait_id':row['trait_id']})
                    continue
                if op == 'next.priority':
                    priority_bonus(actor)
                    actor['trait_next_priority'] = {'trait_id':row['trait_id'],'source_hash':row['record_hash'],
                        'member_id':owner_id,'amount':component['amount'],'policy':policies()['next_priority']}
                    events.append({'op':'trait.priority.grant',**deepcopy(actor['trait_next_priority'])})
                    continue
                if op == 'hp.lose_current_percent':
                    before = actor['hp']
                    actor['hp'] -= before * component['percent'] // 100
                    events.append({'op':'trait.hp.lose_current_percent','before':before,'after':actor['hp'],
                        'amount':before-actor['hp'],'policy':policies()['first_entry_hp']})
                    continue
                if op == 'devotion.random':
                    from lab import random_devotion_runtime as devotion
                    trait_context = dict(context or {})
                    cursor = current.get('random_devotion_rng')
                    if (isinstance(cursor, dict) and type(cursor.get('seed')) is int
                            and 'random_devotion_policies' in trait_context):
                        # The battle state owns the stream seed; a trait fragment
                        # never resets it back to the platform default.
                        trait_context['random_devotion_seed'] = cursor['seed']
                    fragment = devotion.apply(current, owner_side, row['trait_id'], context=trait_context)
                    if fragment['status'] != 'applied':
                        raise ValueError('; '.join(fragment['blockers']))
                    current.clear(); current.update(fragment['state'])
                    events.extend(fragment['events'])
                    continue
                if op == 'attack.grant':
                    from lab.attack_grant_runtime import install_trait_power
                    events.append(install_trait_power(actor, row['trait_id'], row['record_hash']))
                    continue
                if op == 'next.cost':
                    from lab import mechanism_runtime as mechanisms
                    mechanisms.validate_member(actor)
                    ledger = actor.setdefault('mechanism_flat_modifiers', [])
                    ledger[:] = [r for r in ledger if not (r.get('source_trait_id') == row['trait_id'] and r.get('op') == op)]
                    item = {'op':op,'amount':component['amount'],'policy':mechanisms.POLICY,
                        'next_policy':mechanisms.NEXT_POLICY,'source_trait_id':row['trait_id'],
                        'source_hash':row['record_hash'],'token':token}
                    ledger.append(item)
                    events.append({**deepcopy(item),'target':'self'})
                    continue
                if op == 'status.to_mark':
                    from lab import mark_runtime as marks, status_lifecycle as lifecycle
                    target_side=owner_side if component['target']=='self' else other
                    target=_active(current,target_side)
                    if target['hp']<=0:continue
                    before=target.get('statuses',{}).get(component['status'],0)
                    if type(before) is not int or before<0:
                        raise ValueError('Status conversion requires a nonnegative integer layer count')
                    pairs=min(component['cap'],before//component['layers_per'])
                    if not pairs:continue
                    after=before-pairs*component['layers_per']
                    value,extra=marks.change_marks(current['teams'][target_side]['marks'],component['mark_id'],
                        pairs*component['mark_layers_per'],context=marks.research_context(),
                        source={'trait_id':row['trait_id'],'source_hash':row['record_hash']})
                    if after:target['statuses'][component['status']]=after
                    else:lifecycle.clear_status(target,component['status'],reason='trait_status_to_mark')
                    if component['status'] in target.get('status_modifier_sources',{}):
                        target['status_modifier_sources'][component['status']]['count']=after
                    current['teams'][target_side]['marks']=value
                    events.append({'op':op,'status':component['status'],'before':before,'after':after,
                        'consumed':before-after,'requested_mark_layers':pairs*component['mark_layers_per'],
                        'target_side':target_side,'policy':policies()['status_to_mark']})
                    events.extend({**e,'target_side':target_side} for e in extra)
                    continue
                if op == 'mark.add':
                    from lab import mark_runtime as marks
                    target_side = owner_side if component['target'] == 'self' else other
                    value, extra = marks.change_marks(current['teams'][target_side]['marks'],
                        component['mark_id'],component['stacks'],context=marks.research_context(),
                        source={'trait_id':row['trait_id'],'source_hash':row['record_hash']})
                    current['teams'][target_side]['marks'] = value
                    events.extend({**e,'target_side':target_side} for e in extra)
                    continue
                if op in ('skill.cost_all', 'skill.power_all'):
                    field = 'cost' if op == 'skill.cost_all' else 'power'
                    values = actor.setdefault('trait_modifiers', {})
                    before=values.get(field,0)
                    amount=component['amount']
                    if 'max_magnitude' in component:
                        amount=max(-component['max_magnitude'],min(component['max_magnitude'],before+amount))-before
                    if amount==0:continue
                    values[field] = before + amount
                    actor.setdefault('trait_modifier_sources', []).append({'policy': POLICY,
                        'trait_id': row['trait_id'], 'source_hash': row['record_hash'], 'member_id': owner_id,
                        'field': field, 'amount': amount, 'turn': current['turn'], 'token': token})
                    events.append({'op': 'trait.modifier', 'field': field, 'amount': amount})
                    continue
                targets = ([(s, m) for s in ('a', 'b') for m in current['teams'][s]['members']]
                    if component['target'] == 'all_members' else
                    [(owner_side, actor)] if component['target'] == 'self' else [(other, _active(current, other))])
                for target_side, target in targets:
                    if target['hp'] <= 0:
                        continue
                    params = {k: deepcopy(v) for k,v in component.items() if k not in ('op','target','when')}
                    # Treat each selected recipient as self so the same shared
                    # effect validates/clamps active and reserve resources.
                    relative_target = 'opponent' if target_side != owner_side else 'self'
                    if actor['hp'] == 0:
                        relative_target = 'self'
                    program = {'category': 'skill', 'status': 'compiled', 'game_id': row['trait_id'],
                        'snapshot_id': prepared.snapshot_id, 'source_hash': row['record_hash'], 'blockers': [],
                        'dependency_ids': [], 'term_source': deepcopy(prepared._rules._catalog['provenance']['Terms']),
                        'modifier_source_kind': 'trait',
                        'operations': [{'op': op, 'params': {'target': relative_target, **params}}]}
                    from lab.research_phases import _fragment, _devotion_seed
                    effect_context = _fragment(program, _devotion_seed(current))
                    effect_context.update(resolved_energy_cost=0, actor_side=owner_side, turn=current['turn'],
                                   actor_member_id=actor['member_id'], faint_policy='stop_remaining_skill_on_exhaustion_experiment')
                    from lab import mark_runtime as marks
                    effect_context.update(marks.research_context())
                    opposing_side = 'b' if target_side == 'a' else 'a'
                    relative = ({'self': deepcopy(actor), 'opponent': deepcopy(target)} if relative_target == 'opponent'
                        else {'self': deepcopy(target), 'opponent': deepcopy(_active(current, opposing_side))})
                    relative_sides = (('self', owner_side), ('opponent', target_side)) if relative_target == 'opponent' else (('self', target_side), ('opponent', opposing_side))
                    for key, absolute in relative_sides:
                        relative[key]['types'] = deepcopy(prepared._rules.form(relative[key]['form_id'])['types'])
                        slots = current['teams'][absolute].get('marks', deepcopy(marks.EMPTY))
                        marks.validate_marks(slots)
                        relative[key]['field_marks'] = deepcopy(slots)
                    result = execute_effects(program, relative, effect_context)
                    if result['status'] != 'applied':
                        raise ValueError('Trait effect blocked: ' + '; '.join(result['blockers']))
                    if op == 'energy.transfer':
                        actor['energy'] = result['state']['self']['energy']
                    updated = result['state'][relative_target]
                    updated.pop('field_marks', None)
                    updated.pop('team_devotion', None)
                    if 'types' not in target:
                        updated.pop('types', None)
                    target.clear(); target.update(updated)
                    events.extend({**e, 'target_side': target_side, 'target_member_id': target['member_id']}
                                  for e in result['events'] if e['op'] != 'energy.pay')
            if row.get('once_per_battle'):
                actor.setdefault('trait_once_events', {})[str(row['trait_id'])] = row['record_hash']
            return {'state': current, 'events': [], 'result': [
                {**e, 'trait_id': row['trait_id'], 'trait_name': row['name'], 'actor_side': owner_side,
                 'actor_member_id': owner_id, 'source_hash': row['record_hash'], 'trigger': event_name,
                 'trait_policy': POLICY, 'trait_config_hash': CONFIG_HASH,
                 'trait_policies': policies(), 'uncertainties': deepcopy(_data()['uncertainties'])} for e in events]}
        handlers[key] = apply
    source = {'rule_id':'trait.phase', 'component_id':event_name, 'snapshot_id':prepared.snapshot_id}
    result = dispatch_events(state, [{'name':event_name,'payload':payload,'source':source}],
        subscriptions, handlers, policy={'mode':'explicit_fifo_experiment','max_events':64,'max_depth':8,'max_handler_calls':64})
    if result['status'] != 'applied':
        raise ValueError('Trait event blocked: ' + '; '.join(result['blockers']))
    result['state']['trait_events']['tokens'].append(token)
    state.clear(); state.update(result['state'])
    return [event for results in result['results'].values() for group in results for event in group]


def require_faint_observer(state):
    if (_enabled(state) and not isinstance(state.get('victory'),dict)
            and any(member.get('trait_id') in (200235,200230) for team in state['teams'].values() for member in team['members'])):
        raise ValueError('Faint trait requires the owned victory knockout occurrence observer')


def depart(member):
    current = deepcopy(member)
    if _rows().get(member.get('trait_id'),{}).get('overheal_component',{}).get('clear_on_departure'):
        current.pop('trait_overheal',None)
    if any(c['op']=='stat.event_layers' and c.get('clear_on_departure') for c in _rows().get(member.get('trait_id'),{}).get('components',[])):
        current.pop('trait_event_stat_layers',None)
    fields={'cost' if c['op']=='skill.cost_all' else 'power' for c in _rows().get(member.get('trait_id'),{}).get('components',[])
        if c['op'] in ('skill.cost_all','skill.power_all') and c.get('clear_on_departure')}
    if fields:
        _validate_modifiers(current)
        current['trait_modifier_sources']=[r for r in current.get('trait_modifier_sources',[]) if r['field'] not in fields]
        current['trait_modifiers']={k:v for k,v in current.get('trait_modifiers',{}).items() if k not in fields}
    current.pop('confirmed_entry_history',None)
    current.pop('sentry_prediction',None)
    current.pop('trait_entry_party',None)
    current.pop('trait_entry_magic',None)
    if 'mechanism_flat_modifiers' in current:
        current['mechanism_flat_modifiers']=[m for m in current['mechanism_flat_modifiers'] if m.get('source_trait_id') != 200125]
    return current


def initialize(prepared, state):
    if not _enabled(state):
        return []
    if 'trait_initial_entry_done' in state and type(state['trait_initial_entry_done']) is not bool:
        raise ValueError('Malformed initial trait-entry flag')
    if state.get('trait_initial_entry_done'):
        bind(prepared, state)
        require_faint_observer(state)
        return []
    current, events = deepcopy(state), []
    bind(prepared,current)
    require_faint_observer(current)
    for side in ('a','b'):
        events.extend(run_event(prepared, current, 'member.enter', side=side, token='initial:' + side))
    current['trait_initial_entry_done'] = True
    state.clear(); state.update(current)
    return events


def status_decay_remaining(state, status, before, remaining):
    """Replace a scheduled rounded decay using living source-bound field auras."""
    if any(type(v) is not int for v in (before,remaining)) or not 0<=remaining<=before:
        raise ValueError('Status decay query requires integer before/remaining layers')
    sources=[]; caps=set(); conversions=[]
    for side in ('a','b'):
        member=_active(state,side)
        for component in _passive(member,'status.decay.query',{}):
            if component['op']=='status.decay_convert' and component['status']==status:
                conversions.append({'side':side,'member_id':member['member_id'],'trait_id':member['trait_id'],
                    'source_hash':member['trait_source_hash'],'to_status':component['to_status'],'cap':component['cap']})
            if component['op']=='status.decay_growth' and component['status']==status:
                caps.add(component['cap'])
                sources.append({'side':side,'member_id':member['member_id'],'trait_id':member['trait_id'],
                    'source_hash':member['trait_source_hash']})
    if conversions:
        if sources or len(conversions)!=1:
            raise ValueError('Overlapping decay replacements need an explicit source-order contract')
        return remaining,[{'op':'trait.status_decay_convert','source':conversions[0],'stacks':before-remaining,
            'policy':policies()['burn_decay_conversion']}]
    if not sources:return remaining,[]
    if len(caps)!=1 or before>next(iter(caps)):
        raise ValueError('Conflicting or exceeded status decay growth source caps')
    after=min(next(iter(caps)),before+(before-remaining))
    return after,[{'op':'trait.status_decay_growth','status':status,'before':before,'scheduled_remaining':remaining,
        'after':after,'actual_gain':after-before,'sources':sources,'policy':policies()['burn_decay_growth']}]


def apply_decay_conversion(prepared,state,target_side,replacements):
    """Apply the sourced conversion through common immunity/cap/status-gain hooks."""
    result_events=[]
    for event in replacements:
        if event['op']!='trait.status_decay_convert' or not event['stacks']:continue
        source=event['source']; owner_side=source['side']; other='b' if owner_side=='a' else 'a'
        target='self' if target_side==owner_side else 'opponent'
        relative={'self':deepcopy(_active(state,owner_side)),'opponent':deepcopy(_active(state,other))}
        if relative[target]['hp']<=0:continue
        for key in ('self','opponent'):
            relative[key]['types']=deepcopy(prepared._rules.form(relative[key]['form_id'])['types'])
        program={'category':'skill','status':'compiled','game_id':source['trait_id'],'snapshot_id':prepared.snapshot_id,
            'source_hash':source['source_hash'],'blockers':[],'dependency_ids':[],
            'term_source':deepcopy(prepared._rules._catalog['provenance']['Terms']),'modifier_source_kind':'trait',
            'operations':[{'op':'status.add','params':{'target':target,'status':source['to_status'],'stacks':event['stacks']}}]}
        from lab.research_phases import _fragment, _devotion_seed
        context=_fragment(program, _devotion_seed(state))
        context.update(resolved_energy_cost=0,component_sequence_paid_cost=0,actor_side=owner_side,
            actor_member_id=source['member_id'],turn=state['turn'])
        context['status_policies'][source['to_status']]['cap']=source['cap']
        result=execute_effects(program,relative,context)
        if result['status']!='applied':raise ValueError('Decay conversion blocked: '+'; '.join(result['blockers']))
        for key,side in (('self',owner_side),('opponent',other)):
            member=_active(state,side); updated=result['state'][key]
            if 'types' not in member:updated.pop('types',None)
            member.clear();member.update(updated)
        result_events.extend({**e,'target_side':target_side,'source_trait_id':source['trait_id'],
            'decay_policy':event['policy']} for e in result['events'] if e['op']!='energy.pay')
    return result_events


def event_stat_layers(member):
    entry=member.get('trait_event_stat_layers')
    if entry is None:return 0
    row=_rows().get(member.get('trait_id'),{})
    component=next((c for c in row.get('components',[]) if c['op']=='stat.event_layers'),None)
    if (component is None or not isinstance(entry,dict) or entry.get('source_trait_id')!=row['trait_id']
            or entry.get('source_hash')!=row['record_hash'] or entry.get('buff_id')!=component['buff_id']
            or entry.get('policy')!=policies()['event_stat_layers'] or type(entry.get('layers')) is not int
            or not 0<=entry['layers']<=component['max_layers']):
        raise ValueError('Trait event stat layers do not match their source')
    return entry['layers']


def after_super_effective_damage(prepared,state,side,damage_events,*,token,context=None):
    actor=_active(state,side)
    if _rows().get(actor.get('trait_id'),{}).get('event')!='damage.super_effective':return []
    target=_active(state,'b' if side=='a' else 'a');emitted=[];seen=set()
    for index,event in enumerate(damage_events):
        params=event.get('resolved_params',event.get('params',{}))
        if event.get('op') not in ('damage','damage.hit') or event.get('target')!='opponent' or params.get('kind') not in ('physical','magical'):continue
        amount,before,after=event.get('damage'),event.get('before'),event.get('after')
        if any(type(v) is not int for v in (amount,before,after)) or amount!=before-after or amount<0:
            raise ValueError('Super-effective trigger requires actual direct HP-loss proof')
        if not amount:continue
        identity=canonical_hash(event)
        if identity in seen:raise ValueError('Duplicate direct hit in super-effective trigger')
        seen.add(identity)
        matchup=prepared._rules.type_multiplier(params.get('type'),target['form_id'])
        ratio=matchup['multiplier']
        if ratio['numerator']>ratio['denominator']:
            emitted.extend(run_event(prepared,state,'damage.super_effective',side=side,
                payload={'type_matchup':matchup,'source_damage_event':deepcopy(event)},
                token=f'{token}:super-effective:{index}',context=context))
    return emitted


def _opponent_buff_layers(opponent,eligible=None):
    if not isinstance(opponent,dict):raise ValueError('Opponent buff-layer query requires its owned current member')
    from lab.modifier_ledger import buff_layer_count
    return buff_layer_count(opponent,eligible_buff_ids=eligible)


def speed_bonus(member,*,opponent=None):
    confirmed_bonus = _confirmed_speed_bonus(member)
    if not any(c['op']=='power.opponent_buff_layers' for c in _rows().get(member.get('trait_id'),{}).get('components',[])):
        return confirmed_bonus
    return confirmed_bonus + sum(component['speed_per']*min(component['speed_cap'],
        _opponent_buff_layers(opponent,component['speed_buff_ids']))
        for component in _passive(member,'power.query',{}) if component['op']=='power.opponent_buff_layers')


def _overheal_progress(member):
    entry=member.get('trait_overheal')
    if entry is None:return Fraction(0),0
    row=_rows().get(member.get('trait_id'),{}); component=row.get('overheal_component')
    if (component is None or not isinstance(entry,dict) or entry.get('source_hash')!=row['record_hash']
            or entry.get('source_trait_id')!=row['trait_id'] or entry.get('policy')!=policies()['overheal']):
        raise ValueError('Overheal ledger source mismatch')
    total=Fraction(0)
    for grant in entry.get('grants',[]):
        if (not isinstance(grant,dict) or type(grant.get('overflow')) is not int or grant['overflow']<=0
                or type(grant.get('max_hp')) is not int or grant['max_hp']<=0):
            raise ValueError('Overheal requires actual integer overflow and max HP evidence')
        total+=Fraction(grant['overflow']*100,grant['max_hp']*component['threshold_percent'])
    if entry.get('thresholds')!=total.numerator//total.denominator:
        raise ValueError('Overheal threshold ledger differs from actual grants')
    return total,entry['thresholds']


def after_hp_restore(state,target,requested,restored,context):
    if target not in ('self','opponent') or any(type(v) is not int for v in (requested,restored)) or not 0<=restored<=requested:
        raise ValueError('Overheal hook requires actual requested and restored integer HP')
    member=state[target];row=_rows().get(member.get('trait_id'),{});component=row.get('overheal_component')
    if not _enabled(member) or member['hp']<=0 or not component or requested==restored:return []
    total,before=_overheal_progress(member);overflow=requested-restored
    total+=Fraction(overflow*100,member['max_hp']*component['threshold_percent'])
    thresholds=total.numerator//total.denominator;granted=thresholds-before
    grants=deepcopy(member.get('trait_overheal',{}).get('grants',[]))+[{'overflow':overflow,'max_hp':member['max_hp']}]
    member['trait_overheal']={'source_trait_id':row['trait_id'],'source_hash':row['record_hash'],
        'thresholds':thresholds,'grants':grants,'policy':policies()['overheal']}
    events=[{'op':'trait.overheal','target':target,'overflow':overflow,'crossed_thresholds':granted,
        'thresholds':thresholds,'source_trait_id':row['trait_id'],'source_hash':row['record_hash'],'policy':policies()['overheal']}]
    if component['op']=='stat.layers' or not granted:return events
    opposite='opponent' if target=='self' else 'self'
    if state[opposite]['hp']<=0:return events
    relative={'self':deepcopy(member),'opponent':deepcopy(state[opposite])}
    for owner in relative.values():
        if 'types' not in owner:owner['types']=deepcopy(owner.get('trait_form_types'))
    program={'category':'skill','status':'compiled','game_id':row['trait_id'],'snapshot_id':_data()['snapshot_id'],
        'source_hash':row['record_hash'],'blockers':[],'dependency_ids':[],'modifier_source_kind':'trait',
        'term_source':deepcopy(_data()['term_source']),
        'operations':[{'op':'status.add','params':{'target':'opponent','status':'poison','stacks':granted}}]}
    from lab.research_phases import _fragment
    nested=_fragment(program, context.get('random_devotion_seed', 0));nested.update(resolved_energy_cost=0,component_sequence_paid_cost=0,turn=context.get('turn'))
    nested['status_policies']['poison']['cap']=component['cap']
    result=execute_effects(program,relative,nested)
    if result['status']!='applied':raise ValueError('Overheal poison blocked: '+'; '.join(result['blockers']))
    for key,original in (('self',target),('opponent',opposite)):
        updated=result['state'][key]
        if 'types' not in state[original]:updated.pop('types',None)
        state[original].clear();state[original].update(updated)
    events.extend({**e,'target':opposite if e.get('target')=='opponent' else target,
        'overheal_source_trait_id':row['trait_id']} for e in result['events'] if e['op']!='energy.pay')
    return events


def after_hp_restore_full(state,recipient_side,requested,restored,context=None,member_id=None):
    if recipient_side not in ('a','b'):raise ValueError('HP restore needs an actual side')
    recipient=_active(state,recipient_side)
    if member_id is not None and recipient['member_id']!=member_id:return []
    opposite='b' if recipient_side=='a' else 'a'
    relative={'self':recipient,'opponent':_active(state,opposite)}
    return [{**e,'target_side':recipient_side if e.get('target')=='self' else opposite}
        for e in after_hp_restore(relative,'self',requested,restored,{'turn':state['turn'],**(context or {})})]


def validate_calendar(value):
    from datetime import date
    if (not isinstance(value,dict) or set(value)!={'date','policy'}
            or value.get('policy')!=policies()['calendar'] or not isinstance(value.get('date'),str)):
        raise ValueError('Trait 200269 requires explicit trait_calendar date YYYY-MM-DD and policy caller_supplied_game_calendar_date_experiment; host clock is not used')
    try:parsed=date.fromisoformat(value['date'])
    except ValueError as exc:raise ValueError('trait_calendar.date must be a valid YYYY-MM-DD game date') from exc
    if parsed.isoformat()!=value['date']:raise ValueError('trait_calendar.date must use canonical YYYY-MM-DD')
    return value['date'],parsed.weekday()



def _confirmed_member(member):
    row = _confirmed_rows().get(member.get('trait_id'))
    if row is None or not _enabled(member):
        return None
    if (member.get('trait_source_hash') != row['record_hash']
            or member.get('trait_config_hash') != CONFIG_HASH):
        raise ValueError('User-confirmed trait member source binding changed')
    return row


def before_hp_loss_relative(relative, target, damage, context, token):
    """One shared pre-loss gate for each direct hit or indirect HP-loss packet."""
    if target not in ('self','opponent') or type(damage) is not int or damage<0 or not isinstance(token,str) or not token:
        raise ValueError('Fatal protection requires an exact nonnegative packet and unique token')
    actor = relative[target]
    row = _confirmed_member(actor)
    result = {'damage':damage,'events':[]}
    if row is None or row['trait_id'] not in (200151,200195) or actor['hp']<=0:
        return result
    records = actor.setdefault('fatal_protection_events',[])
    if not isinstance(records,list) or any(not isinstance(r,dict) or r.get('source_hash')!=row['record_hash']
            or r.get('trait_id')!=row['trait_id'] or not isinstance(r.get('token'),str) for r in records):
        raise ValueError('Fatal protection source ledger changed')
    old = next((r for r in records if r['token']==token),None)
    if old:
        if old['requested_damage']!=damage:raise ValueError('Fatal packet token reused with different damage')
        raise ValueError('Fatal packet was already resolved; duplicate HP application rejected')
    limit = row['components'][0]['limit']
    if damage<actor['hp'] or len(records)>=limit:
        return result
    amount = max(0,actor['hp']-1) if row['trait_id']==200151 else 0
    record = {'trait_id':row['trait_id'],'source_hash':row['record_hash'],'token':token,
              'requested_damage':damage,'applied_damage':amount,'occurrence':len(records)+1,
              'source':'user_confirmation_20261030','config_sha256':CONFIRMED_CONFIG_HASH}
    if row['trait_id']==200151:
        other = relative['opponent' if target=='self' else 'self']
        if other['hp']>0:
            from lab.effect_runtime import IMMUNITIES
            if not isinstance(other.get('types'),list):
                raise ValueError('Phoenix burn requires explicit current opponent types')
            before = other.setdefault('statuses',{}).get('burn',0)
            if type(before) is not int or before<0:raise ValueError('Malformed burn count')
            cap = context.get('status_policies',{}).get('burn',{}).get('cap')
            if cap is not None and (type(cap) is not int or cap<1):raise ValueError('Malformed burn cap')
            after = before if IMMUNITIES['burn'] in other['types'] else before+15
            if cap is not None:after=min(cap,after)
            other['statuses']['burn']=after
            from lab.modifier_ledger import register_status
            register_status(other,'burn',source_kind='trait',source_id=row['trait_id'],source_hash=row['record_hash'],before=before)
            result['events'].append({'op':'trait.fatal_burn','target':'opponent' if target=='self' else 'self',
                'before':before,'after':after,'source_hash':row['record_hash']})
    else:
        from lab.cute_runtime import gain_cute
        gained = gain_cute(actor,1,source={'trait_id':row['trait_id'],'source_hash':row['record_hash']},context=context)
        result['events'].extend(gained['events'])
    records.append(record)
    result['damage']=amount
    result['events'].append({'op':'trait.fatal_protection','target':target,**deepcopy(record)})
    return result


def before_hp_loss(prepared,state,side,member_id,damage,*,token,context=None):
    """World-state wrapper; use within the caller's existing owned transaction."""
    _bind_owned(prepared,state)
    if side not in ('a','b'):raise ValueError('Fatal protection side is invalid')
    actor = next((m for m in state['teams'][side]['members'] if m['member_id']==member_id),None)
    if actor is None:raise ValueError('Fatal protection member not found')
    other = _active(state,'b' if side=='a' else 'a')
    relative = {'self':actor,'opponent':other}
    original = {k:'types' in v for k,v in relative.items()}
    for v in relative.values():v['types']=deepcopy(prepared._rules.form(v['form_id'])['types'])
    try:return before_hp_loss_relative(relative,'self',damage,context or {},token)
    finally:
        for k,v in relative.items():
            if not original[k]:v.pop('types',None)


def record_actual_payment(prepared,state,side,action,amount,*,token):
    """Persist real cost including zero; replay/idempotency never uses displayed cost."""
    if type(amount) is not int or amount<0 or not isinstance(token,str) or not token:
        raise ValueError('Actual payment requires nonnegative integer amount and token')
    skill = prepared._rules.skill(action['skill_id'])
    from lab.weather_runtime import resolved_skill_type
    row = {'turn':state['turn'],'side':side,'member_id':action['actor_member_id'],
           'skill_id':action['skill_id'],'kind':skill['kind'],
           'type':resolved_skill_type(state.get('weather'),action['skill_id'],skill['type']),
           'amount':amount,'token':token,'source_hash':canonical_hash(skill),
           'response_success':action.get('response_success')}
    row['record_hash']=canonical_hash(row)
    history = state.setdefault('actual_skill_payments',[])
    if not isinstance(history,list):raise ValueError('Actual payment history malformed')
    old = next((r for r in history if r['token']==token),None)
    if old:
        if old!=row:raise ValueError('Payment token reused with different committed skill')
        return []
    history.append(row)
    return [{'op':'trait.actual_payment.record',**deepcopy(row)}]


def _payment_rows(state,turn,side):
    rows = []
    for row in state.get('actual_skill_payments',[]):
        if row.get('record_hash')!=canonical_hash({k:v for k,v in row.items() if k!='record_hash'}):
            raise ValueError('Actual payment history was changed')
        if row['turn']==turn and row['side']==side:rows.append(row)
    return rows


def _single_cast_payment(state,turn,side):
    """Fold equal repeated payments for queries, never remove committed cast records."""
    rows=_payment_rows(state,turn,side)
    if not rows:return None
    amounts={r['amount'] for r in rows}
    if len(amounts)!=1:
        raise ValueError('Different per-cast actual payments on one side in the same round need an explicit comparison rule; no last/max/sum inferred')
    return {'amount':next(iter(amounts)),
            'types':{r['type'] for r in rows},'kinds':{r['kind'] for r in rows},
            'cast_count':len(rows),'tokens':[r['token'] for r in rows]}


def base_skill_cost(member,value):
    """Call before cost modifiers; gene editing overrides the skill's base only."""
    row = _confirmed_member(member)
    if row is None or row['trait_id']!=200318:return value
    entry = member.get('gene_editing_base_cost')
    if entry is None:
        raise ValueError('Gene editing requires the previous-round actual payment snapshot')
    if entry.get('first_turn_original') is True:
        if entry.get('from_turn')!=0 or entry.get('source_hash')!=row['record_hash'] or entry.get('config_sha256')!=CONFIRMED_CONFIG_HASH:
            raise ValueError('Gene first-turn source binding changed')
        return value
    if (entry.get('source_hash')!=row['record_hash'] or type(entry.get('value')) is not int or entry['value']<0
            or entry.get('config_sha256')!=CONFIRMED_CONFIG_HASH):
        raise ValueError('Gene editing payment source binding changed')
    return entry['value']


def _confirmed_event(prepared,state,event_name,*,side=None,member_id=None,token=None):
    supported=_confirmed_rows()
    if not any((member['trait_id'] if 'trait_id' in member else prepared._rules.form(member['form_id']).get('trait_id')) in supported
               for team in state['teams'].values() for member in team['members']):
        return []
    _bind_owned(prepared,state)
    events=[]
    identity = canonical_hash({'turn':state['turn'],'event':event_name,'side':side,'member_id':member_id,'token':token})
    seen = state.setdefault('confirmed_trait_events',[])
    if not isinstance(seen,list) or len(seen)!=len(set(seen)):raise ValueError('Confirmed trait token ledger malformed')
    if identity in seen:return []
    if event_name=='member.enter':
        events.extend(_snapshot_entry_history(state,side,member_id))
    if event_name=='member.faint':
        member=next((m for m in state['teams'][side]['members'] if m['member_id']==member_id),None)
        row=_confirmed_member(member) if member else None
        if row and row['trait_id']==200230 and member['hp']==0:
            member['revival_pending']={'fainted_turn':state['turn'],'revive_at_turn':state['turn']+4,
                'source_hash':row['record_hash'],'config_sha256':CONFIRMED_CONFIG_HASH}
            events.append({'op':'trait.revival.schedule','member_id':member_id,**deepcopy(member['revival_pending'])})
    if event_name=='turn.end':
        for owner_side in ('a','b'):
            team=state['teams'][owner_side]
            for member in team['members']:
                row=_confirmed_member(member)
                pending=member.get('revival_pending')
                if pending is not None:
                    if (not row or row['trait_id']!=200230 or pending.get('source_hash')!=row['record_hash']
                            or pending.get('config_sha256')!=CONFIRMED_CONFIG_HASH):
                        raise ValueError('Pending revival source changed')
                    if member['hp']==0 and state['turn']>=pending['revive_at_turn'] and any(m['hp']>0 for m in team['members']):
                        if member['max_energy']<10:raise ValueError('Revival requires support for confirmed ten energy')
                        member['hp']=member['max_hp'];member['energy']=10;member.pop('revival_pending')
                        events.append({'op':'trait.revive','side':owner_side,'member_id':member['member_id'],
                            'hp':member['hp'],'energy':10,'source_hash':row['record_hash'],'source':'user_confirmation_20261030'})
                if row and row['trait_id']==200318:
                    unit_costs=[_single_cast_payment(state,state['turn'],who) for who in ('a','b')]
                    total=sum(record['amount'] for record in unit_costs if record is not None)
                    member['gene_editing_base_cost']={'value':total,'from_turn':state['turn'],
                        'source_hash':row['record_hash'],'config_sha256':CONFIRMED_CONFIG_HASH}
            actor=_active(state,owner_side);row=_confirmed_member(actor)
            if not row or actor['hp']<=0 or row['trait_id'] not in (200104,200275):continue
            own=_single_cast_payment(state,state['turn'],owner_side)
            other_side='b' if owner_side=='a' else 'a'
            other=_single_cast_payment(state,state['turn'],other_side)
            if not own:continue
            if row['trait_id']==200104:
                target=_active(state,other_side);before=target['energy']
                target['energy']=max(0,before-max(0,own['amount']-(other['amount'] if other else 0)))
                events.append({'op':'trait.paid_difference','side':owner_side,'target_side':other_side,
                    'before':before,'after':target['energy'],'source_hash':row['record_hash'],
                    'own_per_cast_payment':own['amount'],'opponent_per_cast_payment':other['amount'] if other else 0})
            else:
                if not other:continue
                if any(len(record[field])!=1 for record in (own,other) for field in ('types','kinds')):
                    raise ValueError('Multiple distinct skill types or kinds in one round need an explicit harmony comparison rule')
                count=int(own['types']==other['types'])+int(own['kinds']==other['kinds'])+int(own['amount']==other['amount'])
                if count:
                    from lab.modifier_ledger import register_stat
                    for attribute in ('patk','pdef'):
                        actor.setdefault('stat_modifiers',{}).setdefault(attribute,[]).append({'numerator':10*count,'denominator':100})
                        register_stat(actor,attribute,source_kind='trait',source_id=row['trait_id'],source_hash=row['record_hash'])
                    events.append({'op':'trait.paid_matching_stats','member_id':actor['member_id'],'matches':count,
                        'percent':10*count,'source_hash':row['record_hash'],
                        'own_per_cast_payment':own['amount'],'opponent_per_cast_payment':other['amount']})
    seen.append(identity)
    return events


def rebind_evolved_member(prepared,state,side,member_id,*,source_form_id,evolution_evidence):
    """Rebind identity only; all HP/resource/slot/status and modifier values survive."""
    from lab.core_magic_runtime import CONFIRMED_POLICY, CONFIRMED_SHA256, load_confirmed_core_magic_rules, _boss_target
    member=next((m for m in state['teams'][side]['members'] if m['member_id']==member_id),None)
    if (member is None or evolution_evidence.get('item_id')!=104007
            or evolution_evidence.get('policy')!=CONFIRMED_POLICY
            or evolution_evidence.get('rules_sha256')!=CONFIRMED_SHA256
            or evolution_evidence.get('source_form_id')!=source_form_id
            or evolution_evidence.get('target_form_id')!=member['form_id']
            or evolution_evidence.get('member_id')!=member_id):
        raise ValueError('Evolution trait rebind requires the current confirmed core-magic proof')
    rules=load_confirmed_core_magic_rules()
    if evolution_evidence.get('petbase_sha256')!=rules['sources'][0]['sha256']:
        raise ValueError('Evolution trait rebind native form source changed')
    source_member={**member,'form_id':source_form_id}
    if _boss_target(prepared,source_member)['id']!=member['form_id']:
        raise ValueError('Evolution trait rebind target differs from native form mapping')
    from lab.action_traits import ROWS as ACTION_ROWS
    from lab.forced_trait_runtime import _config as forced_config
    tid=prepared._rules.form(member['form_id']).get('trait_id')
    if tid not in _rows() and tid not in ACTION_ROWS and str(tid) not in forced_config()['traits']:
        raise ValueError('Evolved form trait is not fully supported: '+str(tid))
    archive = {k:deepcopy(member[k]) for k in ('trait_id','trait_source_hash','trait_config_hash','trait_once_events','fatal_protection_events','trait_faint_occurrences') if k in member}
    archive.update(source_form_id=source_form_id,target_form_id=member['form_id'],proof=deepcopy(evolution_evidence))
    member.setdefault('evolution_trait_history',[]).append(archive)
    for key in ('trait_id','trait_source_hash','trait_config_hash','trait_supported','trait_weather_supported','trait_support_scope','trait_component_support'):
        member.pop(key,None)
    if tid!=archive.get('trait_id'):
        for key in ('trait_once_events','fatal_protection_events','trait_faint_occurrences','trait_paid_energy'):
            if key in member:
                archive[key]=deepcopy(member.pop(key))
    if any(c['op']=='initial.energy_zero' for c in _rows().get(tid,{}).get('components',[])):
        member['confirmed_initial_energy_set']=True  # Evolution preserves current energy, not battle-initial energy.
    _bind_owned(prepared,state)
    return [{'op':'trait.evolution_rebind','member_id':member_id,'old_trait_id':archive.get('trait_id'),
        'new_trait_id':tid,'source':'user_confirmation_20261030'}]



_ENTRY_HISTORY_QUERY_OPS = {
    'cost_delta': {'entry.history_cost', 'entry.party_cute_cost'},
    'power_add': {'entry.history_power'},
    'patk': {'entry.history_stats', 'entry.history_distinct_stats'},
    'matk': {'entry.history_stats', 'entry.history_distinct_stats'},
    'pdef': {'entry.history_stats'}, 'mdef': {'entry.history_stats'},
    'hp': set(), 'spd': set(),
    'speed_bonus': {'entry.history_stats'},
}


def _entry_history_snapshot(member, *, field=None):
    if field is not None and field not in _ENTRY_HISTORY_QUERY_OPS:
        raise ValueError('Unknown entry-history query field')
    snapshot=member.get('confirmed_entry_history')
    if snapshot is None:
        row=_confirmed_member(member)
        # Missing history blocks only effects which actually depend on that history.
        if row and member.get('hp',0)>0 and any(
                c['op'] in _ENTRY_HISTORY_QUERY_OPS[field] if field is not None else
                c['op'].startswith('entry.history_') or c['op']=='entry.party_cute_cost'
                for c in row['components']):
            raise ValueError('Entry-history trait needs an initialized source-bound entry snapshot')
        return None
    row=_confirmed_member(member)
    if (not row or snapshot.get('source_hash')!=row['record_hash']
            or snapshot.get('record_hash')!=canonical_hash({k:v for k,v in snapshot.items() if k!='record_hash'})):
        raise ValueError('Entry-history trait snapshot changed')
    return snapshot


def preview_entry_history(state, side, target_slot):
    """Detached incoming view; snapshot effects are committed only by member.enter."""
    current = deepcopy(state)
    current['teams'][side]['active_slot'] = target_slot
    actor = _active(current, side)
    actor['mark_entry_actions'] = 0
    if 'trait_policy' in current:
        if current['trait_policy'] != POLICY:
            raise ValueError('Unknown trait research policy')
        _snapshot_entry_history(current, side, actor['member_id'])
    return current


def _snapshot_entry_history(state,side,member_id):
    team=state['teams'][side]
    actor=next((m for m in team['members'] if m['member_id']==member_id),None) if member_id else _active(state,side)
    if actor is None:raise ValueError('Entry-history member was not found')
    row=_confirmed_member(actor)
    if row is None:return []
    components=[c for c in row['components'] if c['op'].startswith('entry.history_') or c['op']=='entry.party_cute_cost']
    if not components:return []
    rows=[record for turn in range(1,state['turn']+1) for record in _payment_rows(state,turn,side)]
    value={'source_hash':row['record_hash'],'entry_turn':state['turn'],
           'member_id':actor['member_id'],'observed_tokens':[r['token'] for r in rows],
           'cost_delta':0,'power_add':0,'speed_bonus':0,'stats':{}}
    events=[]
    for component in components:
        matched=[r for r in rows if 'type' not in component or r['type']==component['type']]
        if component.get('response_success'):
            if any(type(r.get('response_success')) is not bool for r in matched):
                raise ValueError('Entry response history is incomplete; cannot assume no prior responses')
            matched=[r for r in matched if r['response_success']]
        count=len({r['type'] for r in matched}) if component['op']=='entry.history_distinct_stats' else len(matched)
        count=min(component.get('cap',count),count)
        op=component['op']
        if op=='entry.party_cute_cost':
            count=0
            from lab.cute_runtime import validate as cute_layers
            for other in team['members']:
                if other['member_id']==actor['member_id']:continue
                if 'cute_layers' not in other and (state['turn']!=1 or state.get('actual_skill_payments')):
                    raise ValueError('Guardian needs explicit cute layers of every teammate')
                layers=cute_layers(other)
                if other['hp']>0:count+=layers
            value['cost_delta']+=count*component['amount_per']
        elif op=='entry.history_cost':value['cost_delta']+=count*component['amount_per']
        elif op=='entry.history_power':value['power_add']+=count*component['amount_per']
        elif op=='entry.history_stats':
            value['stats']={a:count*component['percent_per'] for a in ('patk','matk','pdef','mdef')}
            value['speed_bonus']+=count*component['speed_per']
        elif op=='entry.history_distinct_stats':
            value['stats']={a:count*component['percent_per'] for a in ('patk','matk')}
        elif op=='entry.history_energy':
            old=actor.get('entry_history_energy_credited',0)
            if type(old) is not int or old<0 or count<old:
                raise ValueError('Entry energy history moved backwards')
            before=actor['energy'];actor['energy']=min(actor['max_energy'],before+(count-old)*component['amount_per'])
            actor['entry_history_energy_credited']=count
            events.append({'op':'trait.entry_history_energy','before':before,'after':actor['energy'],
                'new_occurrences':count-old,'source_hash':row['record_hash']})
    value['record_hash']=canonical_hash(value)
    actor['confirmed_entry_history']=value
    events.append({'op':'trait.entry_history_snapshot',**deepcopy(value),
        'history_scope':'all_committed_own_team_skills_before_this_entry_including_self_swift_borrowed',
        'source':'user_confirmation_20261030'})
    return events


def prepare_sentry(prepared,state,side,*,predicted_single_hit,token):
    """The engine supplies shared-HUD single-hit prediction, never private policy data."""
    _bind_owned(prepared,state)
    actor=_active(state,side);row=_confirmed_member(actor)
    if row is None or row['trait_id']!=200262:return []
    if type(predicted_single_hit) is not int or predicted_single_hit<0 or not isinstance(token,str) or not token:
        raise ValueError('Sentry requires the current shared-HUD noncrit nonresponse single-hit integer')
    entry={'source_hash':row['record_hash'],'turn':state['turn'],'predicted_single_hit':predicted_single_hit,
        'triggered':actor['hp']>0 and predicted_single_hit>=actor['hp'],'token':token,
        'scope':'pvp_no_crit_no_response_single_hit_no_marks','config_sha256':CONFIRMED_CONFIG_HASH}
    entry['record_hash']=canonical_hash(entry)
    actor['sentry_prediction']=entry
    return [{'op':'trait.sentry_prediction','member_id':actor['member_id'],**deepcopy(entry)}]


def _confirmed_speed_bonus(member):
    snapshot=_entry_history_snapshot(member, field='speed_bonus')
    bonus=snapshot.get('speed_bonus',0) if snapshot else 0
    entry=member.get('sentry_prediction')
    if entry is not None:
        row=_confirmed_member(member)
        if (not row or row['trait_id']!=200262 or entry.get('source_hash')!=row['record_hash']
                or entry.get('config_sha256')!=CONFIRMED_CONFIG_HASH
                or entry.get('record_hash')!=canonical_hash({k:v for k,v in entry.items() if k!='record_hash'})):
            raise ValueError('Sentry prediction source binding changed')
        if entry['triggered']:bonus+=50
    return bonus



def _validate_runtime_delegate(row):
    delegate=row.get('runtime_delegate')
    if delegate is None:return
    if delegate=='payment_runtime':
        from lab.payment_runtime import _data
        candidates=[r for r in _data()['components'] if r['kind']=='trait' and r['source_id']==row['trait_id']]
        if len(candidates)!=1 or candidates[0]['record_hash']!=row['record_hash']:
            raise ValueError('Whole health-payment trait delegate source changed')
    elif delegate=='victory_rules':
        from lab.victory_rules import _loss_data
        source=_loss_data().get('direct_defeat_extras',{}).get(str(row['trait_id']))
        if (not source or source['record_hash']!=row['record_hash']
                or source['roles']!=['attacker','target'] or source['amount']!=1):
            raise ValueError('Whole direct-defeat magic-loss trait delegate source changed')
    elif delegate=='cute_runtime':
        from lab.cute_runtime import _data
        source=_data()['unlimited_trait']
        if source['id']!=row['trait_id'] or source['record_hash']!=row['record_hash']:
            raise ValueError('Whole unlimited-cute trait delegate source changed')
    else:raise ValueError('Unknown complete trait runtime delegate')


def bloodline_relation(member):
    """Shared mixed-blood and foreign-elemental predicates; unknown IDs fail closed."""
    from lab.team_code import BLOODLINES
    sources=[member.get('bloodline_id'),member.get('bloodId'),member.get('original_configuration',{}).get('bloodline_id')]
    values={v for v in sources if v is not None}
    if len(values)!=1:
        raise ValueError('Bloodline is missing or conflicts between source fields')
    value=next(iter(values))
    if type(value) is not int or value not in BLOODLINES or value==0:
        raise ValueError('Unknown bloodline cannot be classified as mixed or native')
    if value==19:return {'bloodline_id':value,'foreign_type':False,'mixed':True}
    types=member.get('types')
    if not isinstance(types,list) or not types or any(not isinstance(t,str) for t in types):
        raise ValueError('Bloodline predicate requires exact current species types')
    foreign=BLOODLINES[value]+'系' not in types
    return {'bloodline_id':value,'foreign_type':foreign,'mixed':foreign}


def permits_member_skill_while_charging(prepared,actor,slot):
    """Jealousy validates carried selection; only the successful commit consumes charge."""
    row=_confirmed_member(actor)
    if row is None or row['trait_id']!=200174 or actor.get('charge') is None:return False
    if type(slot) is not int or not 0<=slot<4 or not actor['skill_slots'][slot]:
        raise ValueError('Jealousy requires an actual nonempty carried slot')
    charge=actor['charge']
    if not isinstance(charge,dict):raise ValueError('Jealousy pending charge is malformed')
    skill_id=actor['skill_slots'][slot]
    phases=prepared._components()[1]
    if phases.requires_charge(skill_id):
        if charge.get('skill_id')==skill_id and charge.get('slot')==slot:
            return False  # The original charge still follows its real release transition.
        return True  # One real prior charge may release a different charged skill.
    return True


def permits_carried_skill_while_charging(prepared,state,side,slot):
    return permits_member_skill_while_charging(prepared,_active(state,side),slot)
