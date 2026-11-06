"""Composable HP-for-missing-energy payment under explicit nonlethal policy.

This module only admits a payment component. It never turns an otherwise
unsupported skill/trait into a fully executable rule.
"""
from copy import deepcopy
from functools import lru_cache
from fractions import Fraction
import hashlib
import json
from pathlib import Path

from lab.game_runtime_defaults import ROOT
from lab.phase_config import fingerprint
from lab.trait_runtime import cached_source_query

CONFIG = ROOT / 'data/rules/reviewed-health-payment-1.json'
CONFIG_SHA256 = 'ac07b2b2acee7e1f66a5caab622f9e9cb608ed048e1c65b7574ecea402bfd67a'
POLICY = 'missing_energy_five_percent_max_hp_floor_total_nonlethal_v1'


@lru_cache(maxsize=2)
def _configuration(stamp):
    raw = CONFIG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONFIG_SHA256:
        raise ValueError('Health payment configuration changed; source review required')
    return json.loads(raw)


@lru_cache(maxsize=16)
def _source_hash(path, size, stamp):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@cached_source_query
def _data():
    config = _configuration(CONFIG.stat().st_mtime_ns)
    for relative, expected in config['source_files'].items():
        path = (ROOT / relative).resolve()
        stat = path.stat()
        if not path.is_relative_to(ROOT) or _source_hash(str(path), stat.st_size, stat.st_mtime_ns) != expected:
            raise ValueError('Health payment extracted source changed: ' + relative)
    return config


def _integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(label + ' must be an integer >= ' + str(minimum))
    return value


def _member_basis(member):
    for name in ('hp', 'max_hp', 'energy', 'max_energy'):
        _integer(member.get(name), name, 1 if name == 'max_hp' else 0)
    from lab.trait_runtime import energy_allows_overflow
    if (member['hp'] <= 0 or member['hp'] > member['max_hp']
            or (member['energy'] > member['max_energy'] and not energy_allows_overflow(member))):
        raise ValueError('Health payment requires valid living resource bounds')
    return {key: deepcopy(member.get(key)) for key in ('member_id', 'form_id', 'trait_id',
        'trait_policy', 'trait_source_hash', 'trait_config_hash', 'hp', 'max_hp', 'energy', 'max_energy')}


def _quote(member, skill_id, total_cost, config):
    _integer(skill_id, 'skill_id', 1)
    _integer(total_cost, 'total_cost')
    basis = _member_basis(member)
    paid_energy = min(total_cost, member['energy'])
    missing = total_cost - paid_energy
    selected = []
    if missing:
        from lab import trait_runtime as traits
        form = config['forms'].get(str(member.get('form_id')))
        trait_id = form['trait_id'] if form and member.get('trait_policy') == traits.POLICY else None
        if trait_id is not None and member.get('trait_id') != trait_id:
            raise ValueError('Health payment trait differs from the source form')
        selected = [row for row in config['components']
                    if (row['kind'] == 'trait' and row['source_id'] == trait_id)
                    or (row['kind'] == 'skill' and row['source_id'] == skill_id)]
        if not selected:
            raise ValueError('Insufficient energy; no reviewed health-payment component applies')
    ratios = {tuple(row['component']['hp_ratio']) for row in selected}
    if len(ratios) > 1:
        raise ValueError('Different health-conversion components require an unresolved selection rule')
    # Shared alternatives grant the same conversion; never add their rates.
    ratio = Fraction(*next(iter(ratios))) if ratios else Fraction(0)
    exact = member['max_hp'] * missing * ratio
    paid_hp = exact.numerator // exact.denominator
    if missing and paid_hp == 0:
        raise ValueError('Rounded zero health cost: minimum-one/free conversion is not source-verified')
    if paid_hp >= member['hp']:
        raise ValueError('Lethal or unaffordable health payment: legality is not source-verified')
    return {'policy': POLICY, 'config_sha256': CONFIG_SHA256, 'skill_id': skill_id,
        'member_basis': basis, 'member_basis_hash': fingerprint(basis),
        'total_cost': total_cost, 'missing_energy': missing, 'paid_energy': paid_energy,
        'paid_hp': paid_hp, 'unrounded_hp': {'numerator': exact.numerator, 'denominator': exact.denominator},
        'rounding': 'floor_once_after_total_missing_energy', 'hp_basis': 'max_hp',
        'sources': [{'source_id': row['source_id'], 'kind': row['kind'], 'source_hash': row['record_hash']}
                    for row in selected], 'training_eligible': False, 'real_game_verified': False}


def quote(prepared, member, skill_id, total_cost):
    """Server-owned quote, after normal cost modifiers, without changing energy.

    Pass paid_energy to the joint planner and normal executor. Preserve this
    entire detached quote in fragment_context.health_payment. Keep the original
    selected total cost. Immediately before execution, recheck current resources
    against that price; later modifiers do not reprice the queued ordinary cast.
    """
    config = _data()
    if prepared.snapshot_id != config['snapshot_id']:
        raise ValueError('Health payment catalog snapshot differs')
    prepared._rules.skill(skill_id)
    result = _quote(member, skill_id, total_cost, config)
    for source in result['sources']:
        record = (prepared._rules.skill(source['source_id']) if source['kind'] == 'skill'
                  else prepared._rules._catalog['traits'][str(source['source_id'])])
        if fingerprint(record) != source['source_hash']:
            raise ValueError('Health payment skill/trait record changed')
        if source['kind'] == 'trait':
            form = prepared._rules.form(member['form_id'])
            if fingerprint(form) != config['forms'][str(member['form_id'])]['record_hash']:
                raise ValueError('Health payment form binding changed')
    return result


def _paid_state(program, state, context):
    payment = context.get('health_payment')
    if payment is None:
        return deepcopy(state), None
    if not isinstance(payment, dict):
        raise ValueError('health_payment must be a server-owned complete quote')
    expected = _quote(state['self'], program['game_id'], payment.get('total_cost'), _data())
    if fingerprint(payment) != fingerprint(expected):
        raise ValueError('Health payment quote source, resource state or amounts changed')
    if (type(context.get('resolved_energy_cost')) is not int
            or context['resolved_energy_cost'] != payment['paid_energy']):
        raise ValueError('Executor energy cost must equal the quoted paid_energy')
    current = deepcopy(state)
    current['self']['hp'] -= payment['paid_hp']
    return current, payment


def preflight(program, state, context, *, preflight_base, damage_resolver=None):
    current, _ = _paid_state(program, state, context)
    return preflight_base(program, current, context, damage_resolver=damage_resolver)


def execute(program, state, context, *, execute_base, damage_resolver=None):
    """Deduct HP on a copy, let the existing component pay quoted energy once."""
    current, payment = _paid_state(program, state, context)
    result = execute_base(program, current, context, damage_resolver=damage_resolver)
    if result['status'] != 'applied':
        result = deepcopy(result)
        result.update(state=deepcopy(state), events=[])
        return result
    if payment is not None and payment['paid_hp']:
        result['events'].insert(0, {'op': 'hp.pay', 'target': 'self', 'amount': payment['paid_hp'],
            'before': state['self']['hp'], 'after': state['self']['hp'] - payment['paid_hp'],
            'payment': deepcopy(payment), 'policy': POLICY, 'training_eligible': False})
    return result


def programs(catalog):
    """Admit complete reviewed skill descriptions, with payment kept orthogonal."""
    from lab.prepared_rules import prepare_rules
    from lab.defense_runtime import defense_programs
    prepared=prepare_rules(catalog);config=_data();result={}
    if prepared.snapshot_id!=config['snapshot_id']:
        raise ValueError('Payment skill snapshot differs')
    defenses=defense_programs(prepared)
    for row in config['components']:
        if row['kind']!='skill':continue
        mid=row['source_id'];record=prepared._rules.skill(mid)
        if record!=row['evidence']['catalog_raw'] or fingerprint(record)!=row['record_hash']:
            raise ValueError('Payment skill complete source differs')
        if record['kind']=='defense':
            if mid not in defenses:continue
            program=defenses[mid]
        else:
            program=deepcopy(prepared._rules.program(mid));program.pop('native_rule',None)
            program.update(status='compiled',blockers=[],operations=[{'op':'damage','params':{
                'target':'opponent','kind':record['kind'],'type':record['type'],'power':record['power']}}])
        program.update(payment_component=deepcopy(row['component']),payment_config_sha256=CONFIG_SHA256,
            executable=False,real_game_verified=False,training_eligible=False)
        result[mid]=program
    return result
