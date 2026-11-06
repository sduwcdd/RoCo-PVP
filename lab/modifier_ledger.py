"""Source classification for Terms 1012/1013; unknown legacy terms fail closed."""
from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_CONFIG = ROOT / 'data/rules/reviewed-modifier-source-units-1.json'
SOURCE_HASH = 'a70bd22218c3557b1e63d931b80db041a4094fc17a660377787dc2870fdec458'

@lru_cache(maxsize=2)
def _sources(stamp):
    raw = SOURCE_CONFIG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_HASH:
        raise ValueError('Modifier source-unit configuration changed')
    config = json.loads(raw)
    for relative, expected in config['source_files'].items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Modifier source-unit extracted evidence changed')
    return config


def source_info(source_id, source_hash, field, amount):
    rows = _sources(SOURCE_CONFIG.stat().st_mtime_ns)['skills']
    row = rows.get(str(source_id))
    if not row or row['source_hash'] != source_hash:
        return {'category':'unknown','layers':None}
    matches = []
    for buff in row['buffs']:
        unit = buff['units'].get(field)
        if unit and amount and Fraction(*unit) * amount > 0:
            layers = Fraction(amount) / Fraction(*unit)
            if layers.denominator == 1:
                matches.append((buff['type'], tuple(unit), layers.numerator, buff['buff_id']))
    identities = {m[:3] for m in matches}
    if len(identities) != 1:
        return {'category': 'unknown', 'layers': None}
    kind, unit, count = next(iter(identities))
    return {'category': {1:'buff',2:'debuff',3:'other',4:'mark'}[kind], 'layers':count,
        'unit':list(unit), 'buff_ids':[m[3] for m in matches],
        'max_layers':min(b['raw']['add_max'] for b in row['buffs'] if b['buff_id'] in [m[3] for m in matches]),
        'source_config_hash':SOURCE_HASH}


POLICY = 'skill_modifier_source_sidecar_terms_1012_1013_v1'
EXCLUDED = {'trait', 'mark', 'other'}

def _verify_trait_buff(source_id, source_hash, buff_id):
    # Transfer changes the holder, never the original trait source identity.
    from lab.trait_runtime import _rows
    row = _rows().get(source_id)
    if (row is None or row['record_hash'] != source_hash
            or str(buff_id) not in row.get('installation_evidence', {}).get('buffs', {})):
        raise ValueError('Trait-derived BUFF source binding changed')


def register_stat(member, attribute, *, source_kind, source_id, source_hash, buff_id=None):
    """Call immediately after appending one pure rational stat term."""
    if source_kind not in EXCLUDED | {'skill'}:
        raise ValueError('Unknown modifier source category')
    if source_kind == 'trait' and buff_id is not None:
        _verify_trait_buff(source_id,source_hash,buff_id)
    terms = member['stat_modifiers'][attribute]
    index = len(terms) - 1
    member.setdefault('stat_modifier_sources', {}).setdefault(attribute, []).append({
        'index': index, 'term': deepcopy(terms[index]), 'source_kind': source_kind,
        'source_id': source_id, 'source_hash': source_hash, 'policy': POLICY,
        **({'buff_id':buff_id} if buff_id is not None else {}),
        'classification': buff_info(buff_id,attribute,Fraction(terms[index]['numerator'],terms[index]['denominator'])) if buff_id is not None else source_info(source_id, source_hash, attribute, Fraction(terms[index]['numerator'],terms[index]['denominator'])) if source_kind == 'skill' else {'category':source_kind,'layers':None}})

def register_status(member, status, *, source_kind, source_id, source_hash, before):
    if member['statuses'].get(status, 0) == before:
        return
    records = member.setdefault('status_modifier_sources', {})
    old = records.get(status)
    provenance = deepcopy(old.get('origins',[])) if old else []
    provenance.append({'source_kind':source_kind,'source_id':source_id,'source_hash':source_hash,
        'added_layers':member['statuses'].get(status,0)-before})
    records[status] = {'source_kind':source_kind,'source_id':source_id,'source_hash':source_hash,
        'origins':provenance,'effect_source':status_info(status),
        'policy': POLICY, 'count': member['statuses'].get(status, 0)}

def _polarity(amount, cost=False):
    return 'buff' if (amount < 0 if cost else amount > 0) else 'debuff' if amount else None

def _split(member, selection):
    """Return retained/selected bundles without mutating input."""
    kept, moved = deepcopy(member), {'stat_modifiers': {}, 'stat_modifier_sources': {},
        'mechanism_flat_modifiers': [], 'skill_modifiers': [], 'statuses': {},
        'status_modifier_sources': {}, 'status_lifecycles': {}, 'status_sources': {}, 'timed_effects': [], 'skill_attack_grants': [], 'dark_surge_modifiers': []}
    for stat, terms in member.get('stat_modifiers', {}).items():
        records = {r['index']: r for r in member.get('stat_modifier_sources', {}).get(stat, [])}
        kept['stat_modifiers'][stat] = []
        kept.setdefault('stat_modifier_sources', {})[stat] = []
        for index, term in enumerate(terms):
            record = records.get(index)
            wanted = _polarity(term['numerator']) in selection
            if wanted and (record is None or record.get('policy') != POLICY or record.get('term') != term):
                raise ValueError('Legacy stat modifier lacks verified source classification')
            if record and (record['source_kind'] == 'skill' or 'buff_id' in record):
                _verify_stat_record(stat, record)
            category = record.get('classification', {}).get('category') if record else 'unknown'
            if wanted and (record['source_kind'] == 'skill' or 'buff_id' in record) and category == 'unknown':
                raise ValueError('Stat source BUFF type or layer unit unresolved')
            target = moved if wanted and (record['source_kind'] == 'skill' or 'buff_id' in record) and category in {'buff','debuff'} else kept
            dest = target.setdefault('stat_modifiers', {}).setdefault(stat, [])
            dest.append(deepcopy(term))
            if record:
                target.setdefault('stat_modifier_sources', {}).setdefault(stat, []).append({**deepcopy(record), 'index':len(dest)-1})
    for field in ('mechanism_flat_modifiers', 'skill_modifiers'):
        kept[field] = []
        for record in member.get(field, []):
            kind = record.get('source_kind', 'trait' if 'source_trait_id' in record else 'skill' if 'source_skill_id' in record else 'unknown')
            wanted = _polarity(record['amount'], field == 'skill_modifiers' or record.get('op') == 'next.cost') in selection
            if wanted and kind == 'unknown':
                raise ValueError('Modifier ledger source classification unavailable')
            classification = flat_info(record,field) if kind == 'skill' or 'buff_id' in record else {'category':kind}
            if wanted and classification['category'] == 'unknown':
                raise ValueError('Modifier source BUFF type or layer unit unresolved')
            (moved if wanted and (kind == 'skill' or 'buff_id' in record) and classification['category'] in {'buff','debuff'} else kept)[field].append(deepcopy(record))
    if member.get('dark_surge_modifiers'):
        from lab.dark_surge_runtime import validate_member
        kept['dark_surge_modifiers'] = []
        for record in validate_member(member):
            info = buff_info(record['buff_id'],'speed.flat',record['amount'])
            if info['layers'] != record['layers']:
                raise ValueError('Dark surge count differs from concrete BUFF layers')
            (moved if info['category'] in selection else kept)['dark_surge_modifiers'].append(deepcopy(record))
    if member.get('skill_attack_grants'):
        from lab.attack_grant_runtime import validate_member
        kept['skill_attack_grants'] = []
        for record in validate_member(member):
            (moved if record['kind'] == 'lifesteal' and 'buff' in selection else kept)['skill_attack_grants'].append(deepcopy(record))
    if member.get('timed_effects'):
        from lab.duration_runtime import validate_member, rules
        config = rules()
        buff_rows = {}
        for source in config['sources']:
            if source['path'].endswith('/BUFF_CONF.json'):
                buff_rows.update(source['rows'])
        kept['timed_effects'] = []
        for record in validate_member(member):
            raw = buff_rows.get(str(record['buff_id']))
            if raw is None:
                raise ValueError('Timed modifier source BUFF category unavailable')
            category = {1:'buff',2:'debuff',3:'other',4:'mark'}.get(raw['type'])
            (moved if category in selection else kept)['timed_effects'].append(deepcopy(record))
    if 'debuff' in selection:
        for status, count in member.get('statuses', {}).items():
            if not count:continue
            record = member.get('status_modifier_sources', {}).get(status)
            expected=status_info(status)
            if record and (record.get('policy') != POLICY or record.get('effect_source') != expected):
                raise ValueError('Status source classification changed')
            if not record:
                kept.setdefault('status_modifier_sources',{})[status]={'policy':POLICY,'count':count,
                    'source_kind':'declared_state','effect_source':expected,'origins':[]}
            moved['statuses'][status] = count
            kept['statuses'][status] = 0
            for field in ('status_modifier_sources','status_lifecycles','status_sources'):
                if status in kept.get(field, {}):
                    moved[field][status] = kept[field].pop(status)
    return kept, moved

def _merge(member, bundle):
    for stat, terms in bundle['stat_modifiers'].items():
        offset = len(member['stat_modifiers'].setdefault(stat, []))
        member['stat_modifiers'][stat].extend(deepcopy(terms))
        member.setdefault('stat_modifier_sources', {}).setdefault(stat, []).extend(
            {**deepcopy(r),'index':r['index']+offset} for r in bundle['stat_modifier_sources'][stat])
    for field in ('mechanism_flat_modifiers','skill_modifiers'):
        member.setdefault(field, []).extend(deepcopy(bundle[field]))
    member.setdefault('dark_surge_modifiers',[]).extend(deepcopy(bundle.get('dark_surge_modifiers',[])))
    for grant in bundle.get('skill_attack_grants', []):
        owned = member.setdefault('skill_attack_grants', [])
        if any(e['kind'] == grant['kind'] for e in owned):
            raise ValueError('Exchanged skill grant overlaps protected owned grant')
        owned.append(deepcopy(grant))
    for timed in bundle.get('timed_effects', []):
        owned = member.setdefault('timed_effects', [])
        if any((e['buff_id'],e['kind']) == (timed['buff_id'],timed['kind']) for e in owned):
            raise ValueError('Exchanged timed buff overlaps protected owned record')
        owned.append(deepcopy(timed))
    for status, count in bundle['statuses'].items():
        if member['statuses'].get(status, 0):
            raise ValueError('Exchanged status overlaps a protected status; merging is unresolved')
        member['statuses'][status] = count
        for field in ('status_modifier_sources','status_lifecycles','status_sources'):
            if status in bundle[field]:member.setdefault(field,{})[status] = deepcopy(bundle[field][status])

def apply(state, op, target, selection):
    selected = {'buff','debuff'} if selection == 'both' else {selection}
    if not selected <= {'buff','debuff'}:raise ValueError('Unknown dispel category')
    if op == 'modifier.exchange':
        a, left = _split(state['self'], selected)
        b, right = _split(state['opponent'], selected)
        _merge(a,right);_merge(b,left)
        state.update(self=a,opponent=b)
        return {'op':op,'target':'self','selection':selection,'transferred':{'self':left,'opponent':right},'policy':POLICY}
    kept, removed = _split(state[target], selected)
    state[target] = kept
    return {'op':op,'target':target,'selection':selection,'removed':removed,'policy':POLICY}


def layer_count(bundle):
    total = 0
    for stat, records in bundle['stat_modifier_sources'].items():
        for record in records:
            info = record.get('classification', {})
            if type(info.get('layers')) is not int:
                raise ValueError('Exact stat layer count unavailable')
            total += info['layers']
    for field in ('mechanism_flat_modifiers','skill_modifiers'):
        for record in bundle[field]:
            info = flat_info(record,field)
            if type(info.get('layers')) is not int:
                raise ValueError('Exact modifier layer count unavailable')
            total += info['layers']
    if bundle.get('timed_effects'):
        raise ValueError('Exact timed modifier layer count requires source count binding')
    total += sum(e['layers'] for e in bundle.get('dark_surge_modifiers', []))
    total += sum(e['layers'] for e in bundle.get('skill_attack_grants', []) if e['kind'] == 'lifesteal')
    total += sum(bundle['statuses'].values())
    return total


def transform(state, target, selection, operation, *, source_skill_id=None, source_hash=None):
    original_member = deepcopy(state[target])
    view = deepcopy(original_member)
    if operation == 'invert_stats':
        view['mechanism_flat_modifiers'] = [m for m in view.get('mechanism_flat_modifiers',[]) if m['op'] == 'speed.flat']
        for field in ('skill_modifiers','timed_effects','skill_attack_grants','dark_surge_modifiers'):
            view[field] = []
        for field in ('statuses','status_lifecycles','status_sources','status_modifier_sources'):
            view[field] = {}
    kept, bundle = _split(view, {selection})
    if operation == 'double' and bundle.get('timed_effects'):
        raise ValueError('Timed modifier layers cannot be doubled without source count binding')
    for stat, terms in bundle['stat_modifiers'].items():
        for index, term in enumerate(terms):
            record = bundle['stat_modifier_sources'][stat][index]
            info = record['classification']
            if type(info.get('layers')) is not int:
                raise ValueError('Exact stat layer count unavailable')
            factor = -1 if operation == 'invert_stats' else 2
            original = deepcopy(term)
            term['numerator'] *= factor
            record.setdefault('transformations', []).append({'operation':operation,'before':original,'after':deepcopy(term)})
            record['term'] = deepcopy(term)
            if operation == 'invert_stats':
                info['category'] = 'debuff'
                info['unit'][0] *= -1
            else:info['layers'] *= 2
    if operation == 'invert_stats':
        for record in bundle['mechanism_flat_modifiers']:
            before = record['amount']
            record['amount'] = -before
            record.setdefault('flat_transformations',[]).append({'operation':'invert_stats','before':before,'after':-before})
    if operation == 'double':
        for record in bundle.get('dark_surge_modifiers', []):
            record['layers'] = min(99,record['layers']*2)
            record['amount'] = -10 * record['layers']
        from lab.attack_grant_runtime import transform_lifesteal
        bundle['skill_attack_grants'] = [transform_lifesteal(e,min(99,e['layers']*2),source_skill_id,source_hash)
            for e in bundle.get('skill_attack_grants', [])]
        for field in ('mechanism_flat_modifiers','skill_modifiers'):
            for record in bundle[field]:
                info = flat_info(record,field)
                if type(info.get('layers')) is not int:
                    raise ValueError('Exact modifier layer count unavailable')
                before = record['amount']
                record['amount'] *= 2
                record.setdefault('flat_transformations',[]).append({'operation':'double','before':before,'after':record['amount']})
        for status in bundle['statuses']:
            cap = bundle['status_lifecycles'].get(status,{}).get('cap')
            bundle['statuses'][status] *= 2
            if cap is not None:bundle['statuses'][status] = min(cap,bundle['statuses'][status])
            if status in bundle['status_modifier_sources']:
                bundle['status_modifier_sources'][status]['count'] = bundle['statuses'][status]
    _merge(kept,bundle)
    if operation == 'invert_stats':
        original_member['stat_modifiers'] = kept['stat_modifiers']
        original_member['stat_modifier_sources'] = kept['stat_modifier_sources']
        original_member['mechanism_flat_modifiers'] = [m for m in original_member.get('mechanism_flat_modifiers',[]) if m['op'] != 'speed.flat'] + kept['mechanism_flat_modifiers']
        kept = original_member
    state[target] = kept
    return {'op':'modifier.'+operation,'target':target,'selection':selection,'policy':POLICY,
        'layer_policy':'source_unit_layer_count_linear_double_existing_status_caps_experiment'}


def _verify_stat_record(stat, record):
    if record.get('source_kind') == 'trait' and 'buff_id' in record:
        _verify_trait_buff(record['source_id'],record['source_hash'],record['buff_id'])
    history = record.get('transformations', [])
    origin = history[0]['before'] if history else record['term']
    info = (buff_info(record['buff_id'],stat,Fraction(origin['numerator'],origin['denominator'])) if 'buff_id' in record
        else source_info(record['source_id'],record['source_hash'],stat,Fraction(origin['numerator'],origin['denominator'])))
    term = deepcopy(origin)
    for change in history:
        if change.get('before') != term or change.get('operation') not in {'invert_stats','double','remove_layers'}:
            raise ValueError('Stat transformation provenance changed')
        expected = deepcopy(term)
        if change['operation'] == 'remove_layers':
            _limited_source(change['source_skill_id'],change['source_hash'])
            n=change['removed_layers']
            if type(n) is not int or not 0 < n <= info['layers']:raise ValueError('Invalid removed layer count')
            value=Fraction(*info['unit'])*(info['layers']-n)
            expected={'numerator':value.numerator,'denominator':value.denominator}
        else:
            expected['numerator'] *= -1 if change['operation'] == 'invert_stats' else 2
        if change['after'] != expected:
            raise ValueError('Stat transformation magnitude changed')
        term = expected
        if change['operation'] == 'invert_stats':
            info['category']='debuff';info['unit'][0]*=-1
        elif change['operation'] == 'remove_layers':info['layers']-=change['removed_layers']
        else:info['layers']*=2
    if term != record['term'] or info != record.get('classification'):
        raise ValueError('Stat source classification or transformation binding changed')


def buff_info(buff_id, field, amount):
    matches = [buff for row in _sources(SOURCE_CONFIG.stat().st_mtime_ns)['skills'].values()
               for buff in row['buffs'] if buff['buff_id'] == buff_id]
    if not matches or any(buff != matches[0] for buff in matches):
        raise ValueError('Concrete modifier BUFF source unavailable or conflicting')
    buff = matches[0]
    unit = buff['units'].get(field)
    layers = Fraction(amount) / Fraction(*unit) if unit else Fraction(0)
    if not unit or layers.denominator != 1 or layers < 0:
        raise ValueError('Concrete BUFF layers do not match the source unit')
    return {'category':{1:'buff',2:'debuff',3:'other',4:'mark'}[buff['type']], 'layers':layers.numerator,
        'unit':unit,'buff_ids':[buff_id],'max_layers':buff['raw']['add_max'],'source_config_hash':SOURCE_HASH}


def enhance_amount(member, source_skill_id, source_hash, field, amount):
    if not amount:return Fraction(0)
    from lab.trait_runtime import buff_extra_layers
    info = source_info(source_skill_id,source_hash,field,amount)
    if info['category'] == 'unknown':
        buff_extra_layers(member,'unknown',1)
        return amount
    requested = info['layers']
    layers = buff_extra_layers(member,info['category'],requested)
    if layers == requested:return amount
    return Fraction(*info['unit']) * min(info['max_layers'],layers)


def flat_info(record, field):
    if 'source_trait_id' in record and 'buff_id' in record:
        _verify_trait_buff(record['source_trait_id'],record['source_hash'],record['buff_id'])
    history = record.get('flat_transformations',[])
    origin = history[0]['before'] if history else record['amount']
    name = 'skill.cost' if field == 'skill_modifiers' else record['op']
    info = (buff_info(record['buff_id'],name,origin) if 'buff_id' in record
        else source_info(record['source_skill_id'],record['source_hash'],name,origin))
    value = origin
    for change in history:
        if change.get('before') != value or change.get('operation') not in {'invert_stats','double','remove_layers'}:
            raise ValueError('Flat modifier transformation source changed')
        if change['operation'] == 'invert_stats' and record['op'] != 'speed.flat':
            raise ValueError('Only speed flat is an attribute inversion target')
        if change['operation'] == 'remove_layers':
            _limited_source(change['source_skill_id'],change['source_hash'])
            n=change['removed_layers']
            if type(n) is not int or not 0 < n <= info['layers']:raise ValueError('Invalid removed layer count')
            value=Fraction(*info['unit'])*(info['layers']-n)
        else:value *= -1 if change['operation'] == 'invert_stats' else 2
        if change.get('after') != value or info['category'] == 'unknown':
            raise ValueError('Flat modifier transformation amount changed')
        if change['operation'] == 'invert_stats':
            info['category']='debuff';info['unit'][0]*=-1
        elif change['operation'] == 'remove_layers':info['layers']-=change['removed_layers']
        else:info['layers']*=2
    if value != record['amount']:
        raise ValueError('Flat modifier amount differs from source transformation')
    return info


LIMITED_POLICY = 'complete_source_buff_groups_hash_rank_then_fifo_layers_experiment_v1'

def _limited_source(source_skill_id, source_hash):
    row = _sources(SOURCE_CONFIG.stat().st_mtime_ns)['skills'].get(str(source_skill_id))
    if source_skill_id not in (7021070,7150260,7120270) or row is None or row['source_hash'] != source_hash:
        raise ValueError('Limited modifier removal source changed')

def limited_dispel(state, target, *, mode, count, source_skill_id, source_hash, turn):
    from lab.ruleset import canonical_hash
    _limited_source(source_skill_id,source_hash)
    if mode not in ('kinds','layers') or type(count) is not int or count < 1 or type(turn) is not int:
        raise ValueError('Explicit limited modifier selection required')
    kept,bundle = _split(state[target], {'buff'})
    if bundle.get('timed_effects'):
        raise ValueError('Timed buff unit count is not bound for limited removal')
    candidates=[]
    for stat,terms in bundle['stat_modifiers'].items():
        for term,record in zip(terms,bundle['stat_modifier_sources'][stat]):
            candidates.append({'field':stat,'term':term,'record':record,'info':record['classification']})
    for field in ('mechanism_flat_modifiers','skill_modifiers'):
        for record in bundle[field]:
            candidates.append({'field':field,'record':record,'info':flat_info(record,field)})
    for record in bundle.get('skill_attack_grants',[]):
        candidates.append({'field':'lifesteal','record':record,
            'info':{'layers':record['layers'],'buff_ids':[record['buff_id']]}})
    groups={}
    for entry in candidates:
        info=entry['info']
        if type(info.get('layers')) is not int or not info.get('buff_ids'):
            raise ValueError('Complete candidate pool needs exact source layer counts')
        key=','.join(map(str,sorted(info['buff_ids'])))
        groups.setdefault(key,[]).append(entry)
    seed=canonical_hash({'source_skill_id':source_skill_id,'turn':turn,'member':state[target]})
    ordered=sorted(groups,key=lambda key:canonical_hash([seed,key]))
    pool=[{'buff_ids':key,'layers':sum(e['info']['layers'] for e in groups[key])} for key in ordered]
    remaining=count
    selected=[]
    for key in ordered:
        if remaining <= 0:break
        available=sum(e['info']['layers'] for e in groups[key])
        take=available if mode=='kinds' else min(available,remaining)
        selected.append({'buff_ids':key,'layers':take})
        budget=take
        for entry in groups[key]:
            n=min(entry['info']['layers'],budget);budget-=n
            if not n:continue
            record,field=entry['record'],entry['field']
            if field=='lifesteal':
                if n==record['layers']:
                    bundle['skill_attack_grants'].remove(record)
                else:
                    from lab.attack_grant_runtime import reduce_lifesteal
                    replacement=reduce_lifesteal(record,n,source_skill_id,source_hash)
                    record.clear();record.update(replacement)
            elif field in ('mechanism_flat_modifiers','skill_modifiers'):
                before=record['amount'];value=Fraction(*entry['info']['unit'])*(entry['info']['layers']-n)
                if value.denominator!=1:raise ValueError('Flat removal produced fractional amount')
                record['amount']=value.numerator
                record.setdefault('flat_transformations',[]).append({'operation':'remove_layers','before':before,
                    'after':record['amount'],'removed_layers':n,'source_skill_id':source_skill_id,'source_hash':source_hash})
            else:
                before=deepcopy(entry['term']);value=Fraction(*entry['info']['unit'])*(entry['info']['layers']-n)
                entry['term'].update(numerator=value.numerator,denominator=value.denominator)
                record.setdefault('transformations',[]).append({'operation':'remove_layers','before':before,
                    'after':deepcopy(entry['term']),'removed_layers':n,'source_skill_id':source_skill_id,'source_hash':source_hash})
                record['term']=deepcopy(entry['term']);record['classification']['layers']-=n
        remaining-=1 if mode=='kinds' else take
    for stat in bundle['stat_modifiers']:
        pairs=[(t,r) for t,r in zip(bundle['stat_modifiers'][stat],bundle['stat_modifier_sources'][stat]) if t['numerator']]
        bundle['stat_modifiers'][stat]=[t for t,r in pairs]
        bundle['stat_modifier_sources'][stat]=[{**r,'index':i} for i,(t,r) in enumerate(pairs)]
    for field in ('mechanism_flat_modifiers','skill_modifiers'):
        bundle[field]=[r for r in bundle[field] if r['amount']]
    _merge(kept,bundle);state[target]=kept
    return {'op':'modifier.dispel_limited','target':target,'mode':mode,'requested':count,
        'candidate_pool':pool,'selected':selected,'selection_seed':seed,'policy':LIMITED_POLICY}


def enhance_buff_amount(member, buff_id, field, amount):
    from lab.trait_runtime import buff_extra_layers
    info=buff_info(buff_id,field,amount)
    layers=buff_extra_layers(member,info['category'],info['layers'])
    if layers==info['layers']:return amount
    return Fraction(*info['unit'])*min(info['max_layers'],layers)


INHERIT_POLICY = 'source_bound_detached_buff_transfer_before_departure_cleanup_then_before_entry_actions_v1'

def prepare_inheritance(member, *, source_skill_id, source_hash, token):
    from lab.ruleset import canonical_hash
    row=_sources(SOURCE_CONFIG.stat().st_mtime_ns)['skills'].get(str(source_skill_id))
    if source_skill_id!=7160270 or row is None or row['source_hash']!=source_hash or not isinstance(token,str) or not token:
        raise ValueError('Buff inheritance needs the reviewed whole source and owned action token')
    if member['hp']<=0:raise ValueError('Exhausted member cannot prepare voluntary buff inheritance')
    departing,bundle=_split(member,{'buff'})
    grant={'policy':INHERIT_POLICY,'source_skill_id':source_skill_id,'source_hash':source_hash,
        'source_member_id':member['member_id'],'token':token,'bundle':bundle,'bundle_hash':canonical_hash(bundle)}
    return {'departing_member':departing,'grant':grant,'events':[{'op':'modifier.inheritance.prepare',
        'source_member_id':member['member_id'],'bundle_hash':grant['bundle_hash'],'token':token,'policy':INHERIT_POLICY}]}

def apply_inheritance(member, grant):
    from lab.ruleset import canonical_hash
    row=_sources(SOURCE_CONFIG.stat().st_mtime_ns)['skills'].get(str(grant.get('source_skill_id')))
    if (grant.get('policy')!=INHERIT_POLICY or grant.get('source_skill_id')!=7160270 or row is None
            or grant.get('source_hash')!=row['source_hash'] or grant.get('bundle_hash')!=canonical_hash(grant.get('bundle'))
            or member['member_id']==grant.get('source_member_id') or member['hp']<=0):
        raise ValueError('Buff inheritance source, bundle or recipient changed')
    receipt={'token':grant['token'],'source_member_id':grant['source_member_id'],'bundle_hash':grant['bundle_hash']}
    current=deepcopy(member)
    previous=[r for r in current.get('buff_inheritance_receipts',[]) if r['token']==receipt['token']]
    if previous:
        if previous!=[receipt]:raise ValueError('Inheritance token reused for another source bundle')
        return []
    probe=deepcopy(member)
    probe.update(deepcopy(grant['bundle']))
    _,classified=_split(probe,{'buff'})
    if canonical_hash(classified)!=grant['bundle_hash']:
        raise ValueError('Inheritance bundle contains protected or non-buff records')
    _merge(current,deepcopy(grant['bundle']))
    _split(current,{'buff'})
    current.setdefault('buff_inheritance_receipts',[]).append(receipt)
    member.clear();member.update(current)
    return [{'op':'modifier.inheritance.receive','target':'self','target_member_id':member['member_id'],
        'source_member_id':grant['source_member_id'],'bundle_hash':grant['bundle_hash'],
        'token':grant['token'],'policy':INHERIT_POLICY}]


@lru_cache(maxsize=4)
def status_info(status):
    from lab.ruleset import canonical_hash
    config=_sources(SOURCE_CONFIG.stat().st_mtime_ns)
    path=next(ROOT/p for p in config['source_files'] if p.endswith('/BUFF_CONF.json'))
    mapping={'poison':20070010,'burn':20070020,'freeze':20580010,'leech':20050010}
    if status not in mapping:raise ValueError('Unknown canonical status BUFF')
    raw=json.loads(path.read_text(encoding='utf-8'))[str(mapping[status])]
    if raw['type']!=2:raise ValueError('Canonical status is no longer a debuff')
    return {'buff_id':mapping[status],'category':'debuff','unit':1,'record_hash':canonical_hash(raw)}


def depart_modifiers(member):
    """Clear only concrete source BUFFs with installed rest=1; inherit before this."""
    data=_sources(SOURCE_CONFIG.stat().st_mtime_ns)
    raw={b['buff_id']:b['raw'] for row in data['skills'].values() for b in row['buffs']}
    def clears(info):
        ids=info.get('buff_ids',[])
        return bool(ids) and all(raw[i].get('is_clean_when_rest')==1 for i in ids)
    removed=[]
    for stat,terms in member.get('stat_modifiers',{}).items():
        records={r['index']:r for r in member.get('stat_modifier_sources',{}).get(stat,[])}
        kept_terms=[];kept_records=[]
        for i,term in enumerate(terms):
            record=records.get(i)
            if record and (record['source_kind']=='skill' or 'buff_id' in record):
                _verify_stat_record(stat,record)
                if clears(record['classification']):
                    removed.append({'field':stat,'record':deepcopy(record)});continue
            kept_terms.append(term)
            if record:kept_records.append({**record,'index':len(kept_terms)-1})
        member['stat_modifiers'][stat]=kept_terms
        if stat in member.get('stat_modifier_sources',{}):member['stat_modifier_sources'][stat]=kept_records
    for field in ('mechanism_flat_modifiers','skill_modifiers'):
        kept=[]
        for record in member.get(field,[]):
            known='source_skill_id' in record or 'buff_id' in record
            if known and clears(flat_info(record,field)):
                removed.append({'field':field,'record':deepcopy(record)})
            else:kept.append(record)
        if field in member:member[field]=kept
    return [{'op':'modifier.departure.clear','removed':removed,
             'policy':'source_buff_rest_one_only_after_inheritance_preserve_unknown_v1'}] if removed else []


def buff_kind_ids(member):
    """Actual source BUFF IDs, never stat-field names or possible-ID unions."""
    _,bundle=_split(member,{'buff'})
    kinds=set()
    def add(info):
        ids=info.get('buff_ids',[])
        if len(ids)!=1:raise ValueError('Distinct buff kind needs one unambiguous actual BUFF ID')
        kinds.add(ids[0])
    for rows in bundle.get('stat_modifier_sources',{}).values():
        for record in rows:add(record['classification'])
    for field in ('mechanism_flat_modifiers','skill_modifiers'):
        for record in bundle.get(field,[]):add(flat_info(record,field))
    for field in ('skill_attack_grants','timed_effects','dark_surge_modifiers'):
        for record in bundle.get(field,[]):add({'buff_ids':[record['buff_id']]})
    return sorted(kinds)


def buff_layer_count(member, eligible_buff_ids=None):
    _,bundle=_split(member,{'buff'})
    if eligible_buff_ids is None:return layer_count(bundle)
    eligible=set(eligible_buff_ids)
    if any(type(i) is not int for i in eligible):raise ValueError('Eligible BUFF IDs must be integers')
    infos=[r['classification'] for rows in bundle.get('stat_modifier_sources',{}).values() for r in rows]
    infos += [flat_info(r,field) for field in ('mechanism_flat_modifiers','skill_modifiers') for r in bundle.get(field,[])]
    infos += [{'buff_ids':[r['buff_id']],'layers':r['layers']} for r in bundle.get('skill_attack_grants',[])]
    infos += [{'buff_ids':[r['buff_id']],'layers':r['layers']} for r in bundle.get('dark_surge_modifiers',[])]
    infos += [{'buff_ids':[r['buff_id']],'layers':None} for r in bundle.get('timed_effects',[])]
    total=0
    for info in infos:
        ids=set(info.get('buff_ids',[]))
        if not ids:raise ValueError('Layer query requires actual BUFF source IDs')
        if not ids & eligible:continue
        if ids-eligible or type(info.get('layers')) is not int:raise ValueError('Filtered BUFF layer identity or unit is unresolved')
        total+=info['layers']
    return total
