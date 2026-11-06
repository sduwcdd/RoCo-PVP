"""Source-bound adjacent power expressions over a pure current-power query."""
from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
import json
from pathlib import Path
import hashlib

from lab.prepared_rules import prepare_rules
from lab.ruleset import canonical_hash
from lab.power_query import quote_damage_power

CONFIG = Path(__file__).resolve().parents[1] / 'data/rules/reviewed-adjacent-power-1.json'
CONFIG_HASH = 'bb16792164cf56dfdbad0d6fdd184b508bd0715e0784cf78b30e3bce66ee5ad4'
POLICY = 'interior_neighbor_current_power_before_payment_floor_exact_text_fraction_abs_difference_experiment_v1'


@lru_cache(maxsize=2)
def _data(stamp):
    data = json.loads(CONFIG.read_text(encoding='utf8'))
    if canonical_hash(data) != CONFIG_HASH:
        raise ValueError('Adjacent power source configuration changed')
    return data


@lru_cache(maxsize=2)
def _source_catalog(config_stamp, catalog_stamp):
    data = _data(config_stamp)
    path = CONFIG.parents[2] / data['catalog_path']
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != data['catalog_file_sha256']:
        raise ValueError('Adjacent power catalog source file changed')
    return prepare_rules(json.loads(raw))


def programs(catalog):
    prepared, result = prepare_rules(catalog), {}
    data = _data(CONFIG.stat().st_mtime_ns)
    if prepared.snapshot_id != data['snapshot_id'] or prepared.catalog_content_hash != data['catalog_content_hash']:
        raise ValueError('Adjacent power snapshot differs')
    for key, row in data['skills'].items():
        record = prepared._rules.skill(int(key))
        if record != row['record'] or canonical_hash(record) != row['record_hash']:
            raise ValueError('Adjacent power whole source differs')
        program = deepcopy(prepared._rules.program(int(key)))
        program.pop('native_rule', None)
        program.update(status='compiled', blockers=[], operations=[{'op':'damage','params':{
            'target':'opponent','kind':record['kind'],'power':record['power'],'type':record['type']}}],
            adjacent_power_components=deepcopy(row['component']), adjacent_power_policy=POLICY,
            adjacent_power_config_hash=CONFIG_HASH, adjacent_power_catalog_hash=prepared.catalog_content_hash,
            requires_carried_cost_snapshot=True,
            executable=False, real_game_verified=False)
        result[int(key)] = program
    return result


def _intrinsic(spec, left, right):
    # Text specifies exact thirds/quarters; raw current table stores33/25.
    # Absolute difference and floor timing are explicitly named experiments.
    left, right = Fraction(str(left)), Fraction(str(right))
    value = ((left + right) if spec['operator'] == 'sum' else abs(left - right)) / spec['divisor']
    value += spec['base']
    result = value.numerator // value.denominator
    if result <= 0:
        raise ValueError('Zero adjacent attack power lies outside the current positive-power damage candidate domain')
    return result


def _native_operations(program, actors, context):
    from lab.skill_execution import _native_rule
    from lab.rule_expressions import evaluate_condition, evaluate_expression
    rule = _native_rule(program)
    attack_components = [c for c in rule['components'] if c['effect'] in ('damage','damage.sequence')]
    if len(attack_components) > 1:
        raise ValueError('Multi-component neighbor attacks need a staged pure source-power adapter')
    def reads_energy(value):
        if isinstance(value, dict):
            if value.get('read') == {'target':'self','field':'energy'}:
                return True
            return any(reads_energy(v) for v in value.values())
        return isinstance(value,list) and any(reads_energy(v) for v in value)
    if context.get('resolved_energy_cost') and any(reads_energy(c) for c in attack_components):
        raise ValueError('Neighbor native power reading post-payment energy needs its pure payment-stage parameter adapter')
    event = {'name':'skill.use','payload':{'origin':context.get('entry_origin','manual'), 'source_hash':program['source_hash']}}
    operations = []
    prefix_effect = False
    for component in rule['components']:
        if operations:
            break
        if 'when' in component and not evaluate_condition(component['when'], actors, event):
            continue
        if component['effect'] not in ('damage', 'damage.sequence'):
            prefix_effect = True
            continue
        if prefix_effect:
            raise ValueError('Adjacent neighbor power needs a pure adapter for effects preceding/between its attacks')
        def resolve(value):
            if isinstance(value, dict) and set(value) == {'expr'}:
                result = evaluate_expression(value['expr'], actors, event)
                if result.denominator != 1:
                    raise ValueError('Neighbor source expression has no exact integral power')
                return result.numerator
            if isinstance(value, dict):
                return {k:resolve(v) for k,v in value.items()}
            if isinstance(value, list):
                return [resolve(v) for v in value]
            return deepcopy(value)
        operations.append({'op':component['effect'], 'params':{'target':component['target'], **resolve(component['params'])}})
    return operations


def quote_carried_powers(catalog, state, context):
    """Four detached quotations; a blocked unused slot does not poison neighbors.

    Uses current source parameters plus the exact common power stage. No damage
    resolver, panel calculation, payment, random draw, or battle hook executes.
    """
    from lab.runtime_programs import reviewed_programs
    from lab import mechanism_runtime, action_field_runtime, derived_power_runtime, skill_history_runtime, weather_runtime
    prepared = prepare_rules(catalog)
    actors = {k:deepcopy(state[k]) for k in ('self','opponent')}
    actor = actors['self']
    costs = context.get('carried_effective_skill_costs')
    def valid_cost(value):
        return ((type(value) is int and value >= 0) or
            (isinstance(value,dict) and set(value) == {'blocked'} and isinstance(value['blocked'],str) and bool(value['blocked'])))
    if (not isinstance(costs, list) or len(costs) != 4 or any(mid and not valid_cost(costs[i])
            for i,mid in enumerate(actor['skill_slots']))):
        raise ValueError('Adjacent power query requires four source cost quotes or explicit blocked reasons')
    providers = reviewed_programs(prepared)
    adjacent = programs(prepared)
    side = context.get('actor_side', 'a')
    other = 'b' if side == 'a' else 'a'
    full = {'snapshot_id':prepared.snapshot_id, 'turn':context['turn'], 'teams':{
        side:{'active_slot':0,'members':[deepcopy(actor)]}, other:{'active_slot':0,'members':[deepcopy(actors['opponent'])]}}}
    rows, pending = {}, []
    def quote(slot):
        if slot in pending:
            raise ValueError('Recursive adjacent source-power dependency: ' + str(pending + [slot]))
        if slot in rows:
            if rows[slot]['status'] != 'quoted':
                raise ValueError(rows[slot]['blocker'])
            return rows[slot]['power']
        mid = actor['skill_slots'][slot]
        if not mid:
            rows[slot] = {'status':'quoted','slot':slot,'skill_id':0,'power':0,'source':'explicit_empty_slot'}
            return 0
        if isinstance(costs[slot],dict):
            raise ValueError('Neighbor total-cost quote blocked for slot ' + str(slot) + ': ' + costs[slot]['blocked'])
        record = prepared._rules.skill(mid)
        program = providers.get(mid, prepared._rules.program(mid))
        if program.get('status') != 'compiled' or program.get('blockers'):
            raise ValueError('Neighbor skill has no complete source-parameter adapter: ' + str(mid))
        if 'choice_components' in program:
            raise ValueError('Unselected neighbor choice has no unique current power snapshot: ' + str(mid))
        if 'charge_components' in program:
            raise ValueError('Neighbor charge layer/response power needs its explicit pure release-parameter adapter: ' + str(mid))
        pending.append(slot)
        try:
            ctx = {**deepcopy(context), 'snapshot_id':prepared.snapshot_id, 'source_hash':program['source_hash'],
                'resolved_energy_cost':costs[slot], 'weather_skill_id':mid, 'selected_skill_slot':slot,
                'skill_kind':record['kind'], 'skill_type':weather_runtime.resolved_skill_type(context.get('weather'),mid,record['type'])}
            ctx.pop('health_payment', None)
            ctx.pop('skill_history_power', None)
            responses = program.get('response_kinds', program.get('response_categories', []))
            if responses and ctx.get('opponent_kind') not in ('physical','magical','status','defense','switch','recharge','charge'):
                raise ValueError('Neighbor response-power query requires the observed opponent action category')
            ctx['response_success'] = any(prepared._components()[1].counter_matches(r,ctx['opponent_kind']) for r in responses) if responses else False
            action = {'kind':'skill','slot':slot,'skill_id':mid,'actor_member_id':actor['member_id'],'program':program}
            binding = skill_history_runtime.bind_action(prepared, full, side, action)
            if binding is not None:
                ctx['skill_history_power'] = skill_history_runtime.power_terms(full,binding)
            if mid in adjacent:
                if slot not in (1,2):
                    raise ValueError('Adjacent edge/wrap selection is not source-confirmed')
                params = deepcopy(program['operations'][0]['params'])
                params['power'] = _intrinsic(program['adjacent_power_components'],quote(slot-1),quote(slot+1))
                operations = [{'op':'damage','params':params}]
            elif 'mechanism_components' in program:
                operations = mechanism_runtime._base(program,deepcopy(actors),ctx)['operations']
            elif 'action_field_components' in program:
                operations = action_field_runtime.resolve(program,ctx,deepcopy(actors))['operations']
            elif 'derived_power_components' in program:
                operations = derived_power_runtime.resolve(program,ctx)['operations']
            elif 'native_rule' in program:
                operations = _native_operations(program,deepcopy(actors),ctx)
            else:
                operations = program['operations']
            attacks = [op['params'] for op in operations if op['op'] in ('damage','damage.sequence')]
            if not attacks:
                if record['kind'] not in ('status','defense'):
                    raise ValueError('Neighbor attack has no resolved attack source params')
                row = {'status':'quoted','slot':slot,'skill_id':mid,'source_hash':program['source_hash'],
                    'power':0,'source':'complete_nonattack_program_has_no_attack_power'}
            else:
                signatures = {(p['kind'],p['type'],p['power']) for p in attacks}
                if len(signatures) != 1:
                    raise ValueError('Neighbor has distinct attack source powers; a unique card-power adapter is required')
                actual = quote_damage_power(prepared,attacks[0],actors,ctx)
                row = {'status':'quoted','slot':slot,'skill_id':mid,'source_hash':program['source_hash'],
                    'power':actual['power'],'source_params':deepcopy(attacks[0]), 'power_stage':actual['stage'],
                    'history_terms_hash':ctx.get('skill_history_power',{}).get('terms_hash')}
            rows[slot] = row
            return row['power']
        finally:
            pending.pop()
    for slot in range(4):
        try:
            quote(slot)
        except (ValueError,KeyError,TypeError) as exc:
            rows[slot] = {'status':'blocked','slot':slot,'skill_id':actor['skill_slots'][slot],'blocker':str(exc)}
    result = {'policy':POLICY,'snapshot_id':prepared.snapshot_id,'turn':context['turn'],
        'actor_member_id':actor['member_id'],'skill_slots':deepcopy(actor['skill_slots']),
        'carried_effective_skill_costs':deepcopy(costs),'slots':[rows[i] for i in range(4)],
        'state_hash':canonical_hash(actors)}
    result['quote_hash'] = canonical_hash(result)
    return result


def resolve(program, state, context):
    """Resolve one selected source expression for common preflight/execution."""
    data = _data(CONFIG.stat().st_mtime_ns)
    path = CONFIG.parents[2] / data['catalog_path']
    catalog = _source_catalog(CONFIG.stat().st_mtime_ns,path.stat().st_mtime_ns)
    expected = programs(catalog).get(program.get('game_id'))
    if expected is None or program != expected:
        raise ValueError('Adjacent power program differs from reviewed whole source')
    if context.get('adjacent_power_policy') != POLICY:
        raise ValueError('Explicit adjacent power interpretation/rounding policy required')
    candidates = [i for i,mid in enumerate(state['self']['skill_slots']) if mid == program['game_id']]
    slot = context.get('selected_skill_slot', candidates[0] if len(candidates)==1 else None)
    if type(slot) is not int or slot not in (1,2) or slot not in candidates:
        raise ValueError('Adjacent expression requires its explicit interior source slot; edge/wrap remains unresolved')
    snapshot = quote_carried_powers(catalog,state,context)
    left, right = snapshot['slots'][slot-1], snapshot['slots'][slot+1]
    if any(row['status'] != 'quoted' for row in (left,right)):
        raise ValueError('Adjacent current-power snapshot blocked: ' + '; '.join(row.get('blocker','') for row in (left,right) if row['status']!='quoted'))
    result = deepcopy(program)
    result['operations'][0]['params']['power'] = _intrinsic(program['adjacent_power_components'],left['power'],right['power'])
    result['adjacent_power_quote'] = snapshot
    return result
