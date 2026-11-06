"""Reviewed component configurations over the common skill executor.

No prose is parsed at runtime. Cost durations and drain timing are explicitly
versioned experiments; raw installation records and BWIKI hashes stay attached.
"""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

from lab.ruleset import canonical_hash
from lab.skill_execution import execute_skill, preflight_skill

CONFIG = Path(__file__).resolve().parents[1] / 'data/rules/reviewed-mechanism-components-1.json'
POLICY = 'composable-cost-drain-root-v1'
OPS = {'mark.clear_reward','cost.debuff_layers', 'status.trigger', 'damage.ignore_type_resistance', 'damage.power.team_exhausted', 'cost.team_exhausted', 'damage.hits.team_skill_count', 'power.percent', 'next.priority', 'attack.poison', 'damage.power.status_count', 'cost.status_count', 'damage.power.missing_hp', 'damage.power.energy_percent', 'cost.missing_hp', 'cost.opponent_hp_below_half', 'hp.consume_all', 'skill.cost', 'cost.current', 'hp.drain', 'restriction.root', 'damage.power', 'damage.hits',
       'energy.transfer', 'energy.reduce', 'energy.restore', 'hp.restore', 'hp.exchange_ratio',
       'speed.flat', 'power.flat', 'next.cost', 'next.power', 'hits.flat', 'hits.percent', 'stat.modify', 'priority', 'damage.power.add', 'damage.multiply', 'damage.target', 'status.add', 'status.multiply', 'modifier.dispel', 'modifier.exchange', 'modifier.invert_stats', 'modifier.double', 'modifier.poison', 'modifier.dispel_limited'}
CONDITIONS = {None, 'opponent.not_defended', 'opponent.switched_this_turn', 'response.success', 'response.failure', 'self.hp_below_half', 'self.hp_above_half', 'self.hp_above_eighty', 'self.has_debuff', 'self.no_debuff', 'opponent.poisoned', 'opponent.frozen', 'entry.first_action', 'action.first_attack', 'action.later_attack', 'opponent.defeated_by_skill'}
COMMON_EFFECTS = {'energy.transfer', 'energy.reduce', 'energy.restore', 'hp.restore'}
NEXT_POLICY = 'sum_pending_apply_whole_next_successful_paid_skill_or_attack_consume_after_execution_v1'
HIT_POLICY = 'source_sequence_only_add_flat_then_sum_percent_floor_min_one_persistent_experiment_v1'
CONDITION_POLICY = 'read_source_predicates_before_payment_damage_and_resolve_sequence_experiment_v1'


@lru_cache(maxsize=2)
def _configuration(stamp):
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    if config.get('schema') != 'reviewed-mechanism-components-1' or config.get('policy') != POLICY:
        raise ValueError('Unknown reviewed mechanism configuration')
    return config


def _operations(record, row):
    operations = []
    if record['kind'] in ('physical', 'magical'):
        hits = row.get('base_hits')
        if hits is not None and (type(hits) is not int or hits < 1):
            raise ValueError('Reviewed hit count must be a positive integer')
        operations.append({'op': 'damage.sequence' if hits is not None else 'damage',
            'params': {'target': 'opponent', 'kind': record['kind'], 'power': record['power'],
                       'type': record['type'], **({'hits': hits} if hits is not None else {})}})
    return operations


def programs(prepared):
    config = _configuration(CONFIG.stat().st_mtime_ns)
    out = {}
    for row in config['skills']:
        mid = row['skill_id']
        record = prepared._rules.skill(mid)
        if canonical_hash(record) != row['record_hash']:
            raise ValueError(f'Mechanism source changed for {mid}; configuration needs review')
        if row.get('raw', record) != record:
            raise ValueError('Mechanism whole source differs from its retained raw record')
        for component in row['components']:
            if component.get('op') not in OPS or component.get('when') not in CONDITIONS:
                raise ValueError(f'Unsupported reviewed component: {mid}')
            if component.get('target') not in {'self', 'opponent'}:
                raise ValueError('Invalid component target')
            if component.get('event') not in {'turn.end', 'after.use', 'after.damage', 'before.damage', 'after.hit'}:
                raise ValueError('Invalid component event')
            for field in ('amount', 'rounds', 'percent', 'factor', 'repeat_hits'):
                if field in component and type(component[field]) is not int:
                    raise ValueError('Component numbers must be integers')
            if component['op'] in COMMON_EFFECTS | {'damage.hits'}:
                field = 'percent' if component['op'] == 'hp.restore' else 'amount'
                if type(component.get(field)) is not int or component[field] < 1:
                    raise ValueError('Common mechanism effect requires a positive source value')
            if component['op'] == 'damage.hits' and (row.get('base_hits') is None
                    or component['event'] != 'before.damage' or component['target'] != 'opponent'):
                raise ValueError('Conditional hit count requires its explicit base sequence')
        if any(c['op'].startswith('hits.') or 'repeat_hits' in c for c in row['components']):
            terms = [t for t in prepared._rules._catalog['glossary'] if t.get('key') == 3005]
            if terms != [row.get('hit_term')] or row.get('hit_policy') != HIT_POLICY:
                raise ValueError('Hit count term or research policy changed')
        if any(c['op'] in {'modifier.dispel', 'modifier.exchange', 'modifier.invert_stats', 'modifier.double', 'modifier.poison', 'modifier.dispel_limited'} for c in row['components']):
            from lab.modifier_ledger import POLICY as LEDGER_POLICY
            terms = [t for t in prepared._rules._catalog['glossary'] if t.get('key') in (1012, 1013)]
            if terms != row.get('modifier_terms') or row.get('modifier_policy') != LEDGER_POLICY:
                raise ValueError('Buff/debuff source terms or classifier policy changed')
        if row.get('status_count_terms') is not None:
            if row['status_count_terms'] != [t for t in prepared._rules._catalog['glossary'] if t.get('key') in (1004,1036)]:
                raise ValueError('Status count terminology changed')
        program = deepcopy(prepared._rules.program(mid))
        program.pop('native_rule', None)
        operations = _operations(record, row)
        if row.get('base_hits') is not None or any('repeat_hits' in c for c in row['components']):
            program['dependency_ids'] = sorted(set(program.get('dependency_ids', [])) | {3005})
        program.update(status='compiled', blockers=[], operations=operations,
            mechanism_components=deepcopy(row['components']), response_kinds=row['responses'],
            mechanism_evidence=deepcopy(row), mechanism_config_hash=canonical_hash(config),
            mechanism_policy=POLICY, mechanism_record=deepcopy(record),
            mechanism_condition_policy=CONDITION_POLICY)
        if any('percent_per_zero_cost' in component for component in row['components']):
            program['requires_carried_cost_snapshot']=True
        if row.get('intrinsic_swift'):
            from lab.skill_programs import SWIFT_TERM
            terms = [term for term in prepared._rules._catalog.get('glossary', []) if term.get('key') == 1005]
            if terms != [SWIFT_TERM]:
                raise ValueError('Reviewed Swift term changed')
            program.update(intrinsic_swift=True, entry_trigger={'kind': 'voluntary_switch', 'term_id': 1005},
                           swift_term=deepcopy(terms[0]))
            program['dependency_ids'] = sorted(set(program.get('dependency_ids', [])) | {1005})
        out[mid] = program
    return out


def validate_member(member):
    _flat(member, 'speed.flat')
    for item in member.get('skill_modifiers', []):
        if (not isinstance(item, dict) or item.get('policy') != POLICY
                or type(item.get('skill_id')) is not int or type(item.get('amount')) is not int
                or type(item.get('applied_turn')) is not int
                or (item.get('expires_after') is not None and type(item['expires_after']) is not int)):
            raise ValueError('Invalid persistent skill modifier')
    root = member.get('root_restriction')
    if root is not None and (not isinstance(root, dict) or root.get('policy') != POLICY
                            or type(root.get('expires_after')) is not int):
        raise ValueError('Invalid timed root restriction')


def cost(member, skill_id, base, turn, opponent=None, skill_kind=None):
    validate_member(member)
    if any(m.get('attack_only') for m in member.get('skill_modifiers',[])) and skill_kind not in {'physical','magical','status','defense'}:
        raise ValueError('Attack-only cost modifiers require current resolved skill kind')
    excluded={}
    if any(m.get('exclude_application_turn') for m in member.get('skill_modifiers',[])):
        from lab.action_outcome_runtime import committed_history
        for row in committed_history(member):excluded.setdefault(row['turn'],set()).add(row['skill_id'])
    change = sum(m['amount'] for m in member.get('skill_modifiers', [])
                 if m['skill_id'] in (0, skill_id) and (not m.get('exclude_application_turn') or (turn!=m['applied_turn'] and skill_id not in excluded.get(m['applied_turn'],set()))) and (not m.get('attack_only') or skill_kind in ('physical','magical')) and (m['expires_after'] is None or turn <= m['expires_after']))
    row = next((r for r in _configuration(CONFIG.stat().st_mtime_ns)['skills'] if r['skill_id'] == skill_id), None)
    for component in row['components'] if row else []:
        if component['op'] == 'cost.debuff_layers':
            from lab.modifier_ledger import _split,layer_count
            _,bundle=_split(member,{'debuff'})
            change+=layer_count(bundle)*component['amount']
        elif component['op'] == 'cost.team_exhausted':
            change += sum(r['hp']==0 for r in _team(member,'opponent')) * component['amount']
        elif component['op'] == 'cost.status_count':
            if opponent is None:
                raise ValueError('Status-count cost requires the current opposing member')
            change += _status_count(opponent,component['status']) * component['amount']
        elif component['op'] == 'cost.missing_hp':
            change += _missing_hp_steps(member, component['step_basis_points']) * component['amount']
        elif component['op'] == 'cost.opponent_hp_below_half':
            if opponent is None:
                raise ValueError('Conditional cost requires the current opposing member')
            if opponent['hp'] * 2 < opponent['max_hp']:
                change += component['amount']
        elif component['op'] == 'cost.current':
            if type(member.get('mark_entry_actions')) is not int:
                raise ValueError('First-action cost requires owned entry action count')
            if member['mark_entry_actions'] == 0:
                change += component['amount']
    from lab.trait_runtime import cost_delta
    return max(0, base + cost_delta(member,change + _flat(member, 'next.cost')))


def modify_speed(member, value):
    return max(1, value + _flat(member, 'speed.flat'))


def modify_power(member, value, skill=None):
    from lab.attack_grant_runtime import power_factor
    base = max(0, value + _flat(member, 'power.flat') + _flat(member, 'next.power'))
    percent = [e for e in member.get('mechanism_flat_modifiers',[]) if e['op']=='power.percent']
    if percent and not isinstance(skill,dict):
        raise ValueError('Typed power modifiers require current resolved skill type')
    amount = sum(e['amount'] for e in percent if e.get('skill_type') == skill.get('type')) if percent else 0
    from fractions import Fraction
    return base * Fraction(100+amount,100) * power_factor(member)


def _flat(member, op):
    entries = member.get('mechanism_flat_modifiers', [])
    for item in entries:
        if (not isinstance(item, dict) or item.get('policy') != POLICY
                or item.get('op') not in {'speed.flat', 'power.flat', 'power.percent', 'next.priority', 'attack.poison', 'next.cost', 'next.power', 'hits.flat', 'hits.percent'} or type(item.get('amount')) is not int
                or ('skill_id' in item and type(item['skill_id']) is not int)):
            raise ValueError('Invalid flat mechanism modifier')
        if item['op'].startswith('next.') and item.get('next_policy') != NEXT_POLICY:
            raise ValueError('Explicit one-use modifier policy required')
        if item['op'].startswith('hits.') and item.get('hit_policy') != HIT_POLICY:
            raise ValueError('Explicit hit-count modifier policy required')
    return sum(item['amount'] for item in entries if item['op'] == op)


def modify_hits(member, base, skill_id=None, context=None):
    if type(base) is not int or base < 1:
        raise ValueError('Source sequence requires positive integer hits')
    from lab.skill_history_runtime import hits as historical_hits
    base = historical_hits(member,base,skill_id)
    _flat(member, 'hits.flat')
    records = [m for m in member.get('mechanism_flat_modifiers', []) if m.get('skill_id') in (None,skill_id)]
    flat = sum(m['amount'] for m in records if m['op'] == 'hits.flat')
    from lab.trait_runtime import hit_bonus
    flat += hit_bonus(member,(context or {}).get('trait_hit_opponent'))
    percent = sum(m['amount'] for m in records if m['op'] == 'hits.percent')
    value = max(1, (base + flat) * (100 + percent) // 100)
    if context is not None and 'fixed_hit_count' in context:
        from lab.trait_runtime import validate_fixed_hits
        fixed = validate_fixed_hits(context)
        if fixed is not None:
            value = fixed
    return value


def modify_priority(program, value):
    return value + sum(c['amount'] for c in program.get('mechanism_components', []) if c['op'] == 'priority')


def _team(member, side):
    roster=member.get('trait_team_roster',{}).get(side)
    if not isinstance(roster,list) or not roster or any(type(r.get('hp')) is not int or r['hp']<0 for r in roster):
        raise ValueError('Team query requires owned HP roster')
    if len({r['member_id'] for r in roster})!=len(roster):
        raise ValueError('Team roster member identities must be unique')
    return roster


def _status_count(member, status):
    if status not in {'freeze','poison_effect'}:
        raise ValueError('Unknown reviewed status count')
    count = member.get('statuses',{}).get('poison' if status == 'poison_effect' else status,0)
    if type(count) is not int or count < 0:
        raise ValueError('Status count must be nonnegative integer')
    if status == 'poison_effect':
        from lab.mark_runtime import layer_count
        count += layer_count(member,1014)
    return count


def _missing_hp_steps(member, step):
    if type(step) is not int or step <= 0 or type(member.get('max_hp')) is not int or member['max_hp'] <= 0:
        raise ValueError('Missing-HP tiers require positive integer step and maximum HP')
    return (member['max_hp'] - member['hp']) * 10000 // (member['max_hp'] * step)


def _selected(component, state, context):
    condition = component.get('when')
    if condition == 'opponent.not_defended':
        if type(context.get('opponent_defended_this_attack')) is not bool:raise ValueError('Mark clear requires actual opposing defense response classification')
        return not context['opponent_defended_this_attack']
    if condition == 'opponent.switched_this_turn':
        return context.get('opponent_switched_this_turn') is True
    if condition == 'opponent.defeated_by_skill':
        return context.get('_committed_opponent_defeat') is True
    if condition in {'action.first_attack','action.later_attack'}:
        if condition == 'action.later_attack':
            return context.get('action_is_later') is True and context.get('opponent_kind') != 'unobserved_entry_opponent_action'
        if type(context.get('mark_first_attack')) is not bool:
            raise ValueError('Attack order condition requires explicit committed-order flag')
        if context.get('opponent_kind') == 'unobserved_entry_opponent_action':
            return False
        return context['mark_first_attack'] if condition == 'action.first_attack' else not context['mark_first_attack']
    if condition == 'entry.first_action':
        if type(context.get('mark_first_action')) is not bool:
            raise ValueError('Burst requires explicit owned entry first-action state')
        return context['mark_first_action']
    if condition == 'response.failure':
        if type(context.get('response_success')) is not bool:
            raise ValueError('Response replacement requires an explicit success boolean')
        return not context['response_success']
    if condition == 'response.success':
        return context.get('response_success') is True
    if condition == 'self.hp_above_eighty':
        return state['self']['hp'] * 5 > state['self']['max_hp'] * 4
    if condition in {'self.has_debuff','self.no_debuff'}:
        from lab.modifier_ledger import _split
        _, selected = _split(state['self'], {'debuff'})
        matched = any(bool(value) for value in selected.values())
        return matched if condition == 'self.has_debuff' else not matched
    if condition == 'self.hp_above_half':
        return state['self']['hp'] * 2 > state['self']['max_hp']
    if condition == 'self.hp_below_half':
        return state['self']['hp'] * 2 < state['self']['max_hp']
    if condition == 'opponent.frozen':
        return state['opponent']['statuses'].get('freeze', 0) > 0
    if condition == 'opponent.poisoned':
        return state['opponent']['statuses'].get('poison', 0) > 0
    return True


def _base(program, state, context):
    base = deepcopy(program)
    for component in program['mechanism_components']:
        if not _selected(component, state, context):
            continue
        if component['op'] == 'mark.clear_reward':
            base['operations'].append({'op':'mark.clear_reward','params':{k:deepcopy(v) for k,v in component.items() if k not in ('op','when','event')}})
        elif component['op'] == 'damage.ignore_type_resistance':
            for operation in base['operations']:
                if operation['op'].startswith('damage'):
                    operation['params']['ignore_type_resistance']=True
                    operation['params']['resistance_policy']='replace_positive_type_resistance_only_keep_immunity_and_traits_v1'
        elif component['op'] == 'damage.power.team_exhausted':
            count=sum(r['hp']==0 for r in _team(state['self'],'opponent'))
            for operation in base['operations']:
                if operation['op'].startswith('damage'):
                    operation['params']['power'] += count * component['amount']
        elif component['op'] == 'damage.hits.team_skill_count':
            roster=_team(state['self'],'self')
            if any(not isinstance(r.get('skill_slots'),list) or len(r['skill_slots'])!=4 for r in roster):
                raise ValueError('Team hit count requires four owned skill slots per member')
            count=sum(r['skill_slots'].count(component['skill_id']) for r in roster)
            for operation in base['operations']:
                if operation['op']=='damage.sequence':operation['params']['hits']=max(1,count)
        elif component['op'] == 'damage.power.status_count':
            count = _status_count(state[component['target']],component['status'])
            for operation in base['operations']:
                if operation['op'].startswith('damage'):
                    operation['params']['power'] += count * component['amount']
        elif component['op'] in {'damage.power.missing_hp', 'damage.power.energy_percent'}:
            actor = state[component['target']]
            for operation in base['operations']:
                if operation['op'].startswith('damage'):
                    power = operation['params']['power']
                    if component['op'] == 'damage.power.missing_hp':
                        power += _missing_hp_steps(actor,component['step_basis_points']) * component['amount']
                    else:
                        power = power * max(0,100 + actor['energy'] * component['amount']) // 100
                    operation['params']['power'] = max(0,power)
        elif component['op'] == 'damage.power':
            for op in base['operations']:
                if op['op'].startswith('damage'):
                    value = op['params']['power'] * component['factor']
                    denominator = component.get('denominator',1)
                    if value % denominator:
                        raise ValueError('Fractional power multiplier requires an explicit rounding policy')
                    op['params']['power'] = value // denominator
        elif component['op'] == 'damage.target':
            for op in base['operations']:
                if op['op'].startswith('damage'):
                    op['params']['target'] = component['target']
        elif component['op'] == 'damage.multiply':
            for op in base['operations']:
                if op['op'].startswith('damage'):
                    op['params']['damage_multiplier'] = {'numerator': component['factor'], 'denominator': 1}
        elif component['op'] == 'damage.power.add':
            for op in base['operations']:
                if op['op'].startswith('damage'):
                    op['params']['power'] += component['amount']
        elif component['op'] == 'modifier.dispel_limited':
            base['operations'].append({'op':'modifier.dispel_limited','params':{'target':component['target'],
                'mode':component['mode'],'count':component['count']}})
        elif component['op'] == 'modifier.poison':
            from lab.modifier_ledger import _split, layer_count
            _, bundle = _split(state[component['target']], {'buff'})
            count = layer_count(bundle)
            base['operations'].append({'op':'modifier.dispel','params':{'target':component['target'],'selection':'buff'}})
            if count:
                base['operations'].append({'op':'status.add','params':{'target':component['target'],'status':'poison','stacks':count}})
        elif component['op'] in {'modifier.dispel', 'modifier.exchange', 'modifier.invert_stats', 'modifier.double'}:
            base['operations'].append({'op': component['op'], 'params': {'target': component['target'],
                'selection': component['selection']}})
        elif component['op'] == 'status.trigger':
            base['operations'].append({'op':'status.trigger','params':{'target':component['target'],
                'status':component['status'],'policy':'immediate_existing_status_damage_no_decay_experiment_v1'}})
        elif component['op'] == 'status.multiply':
            base['operations'].append({'op':'status.multiply','params':{'target':component['target'],'status':component['status'],'factor':component['factor']}})
        elif component['op'] == 'hp.exchange_ratio':
            base['operations'].append({'op': 'hp.exchange_ratio', 'params': {
                'target': 'self', 'policy': component['policy']}})
        elif component['op'] == 'status.add' and component['event'] == 'after.hit':
            effect = {'op':'status.add','params':{'target':component['target'],'status':component['status'],'stacks':component['stacks']}}
            sequences = [operation for operation in base['operations'] if operation['op'] == 'damage.sequence']
            if not sequences:
                raise ValueError('Per-hit status requires its source multi-hit sequence')
            for operation in sequences:
                operation['params'].setdefault('hit_effects',[]).append(effect)
        elif component['op'] in {'stat.modify', 'status.add'} or (component['op'] in {'skill.cost', 'speed.flat'} and 'repeat_hits' in component):
            if component['op'] == 'stat.modify':
                percent=component['percent']
                if 'percent_per_zero_cost' in component:
                    costs=context.get('carried_effective_skill_costs')
                    if not isinstance(costs,list) or len(costs)!=4 or any(v is not None and (type(v) is not int or v<0) for v in costs):
                        raise ValueError('Zero-cost stat query requires four resolved carried costs')
                    percent += costs.count(0)*component['percent_per_zero_cost']
                params = {'target': component['target'], 'attributes': component['attributes'],
                          'percent': {'numerator': percent, 'denominator': 100}}
            elif component['op'] == 'status.add':
                params = {'target': component['target'], 'status': component['status'], 'stacks': component['stacks']}
            else:
                params = {'target': component['target'], 'component': deepcopy(component)}
            count = modify_hits(state['self'], component['repeat_hits'], program['game_id'], {**context,'trait_hit_opponent':state['opponent']}) if 'repeat_hits' in component else 1
            for index in range(count):
                repeated = deepcopy(params)
                if 'repeat_hits' in component:
                    repeated.update(base_hit_count=component['repeat_hits'], effective_hit_count=count,
                                    hit_index=index, hit_modifier_policy=HIT_POLICY)
                if context.get('fixed_hit_count') is not None and 'repeat_hits' in component:
                    repeated.update(fixed_hit_policy=context['fixed_hit_policy'],fixed_hit_sources=deepcopy(context['fixed_hit_sources']))
                base['operations'].append({'op': 'modifier.flat' if component['op'] == 'speed.flat' else component['op'], 'params': repeated})
        elif component['op'] == 'damage.hits':
            for op in base['operations']:
                if op['op'] == 'damage.sequence':
                    op['params']['hits'] = component['amount']
        elif component['op'] in COMMON_EFFECTS:
            params = {'target': component['target']}
            params.update({'percent': {'numerator': component['percent'], 'denominator': 100}}
                if component['op'] == 'hp.restore' else {'amount': component['amount']})
            count = modify_hits(state['self'], component['repeat_hits'], program['game_id'], {**context,'trait_hit_opponent':state['opponent']}) if 'repeat_hits' in component else 1
            for index in range(count):
                repeated = deepcopy(params)
                if 'repeat_hits' in component:
                    repeated.update(base_hit_count=component['repeat_hits'],effective_hit_count=count,hit_index=index,hit_modifier_policy=HIT_POLICY)
                if context.get('fixed_hit_count') is not None and 'repeat_hits' in component:
                    repeated.update(fixed_hit_policy=context['fixed_hit_policy'],fixed_hit_sources=deepcopy(context['fixed_hit_sources']))
                base['operations'].append({'op': component['op'], 'params': repeated})
    return base


def preflight(program, state, context, damage_resolver=None):
    if '_committed_opponent_defeat' in context:
        raise ValueError('Committed defeat predicate is server-owned')
    if program.get('mechanism_policy') != POLICY or type(context.get('turn')) is not int:
        raise ValueError('Explicit reviewed mechanism policy and turn required')
    evidence = program.get('mechanism_evidence', {})
    config = _configuration(CONFIG.stat().st_mtime_ns)
    trusted = next((row for row in config['skills'] if row['skill_id'] == program.get('game_id')), None)
    record = program.get('mechanism_record', {})
    if (program.get('mechanism_components') != evidence.get('components')
            or program.get('game_id') != evidence.get('skill_id')
            or program.get('source_hash') != evidence.get('record_hash')
            or evidence != trusted or program.get('mechanism_config_hash') != canonical_hash(config)
            or canonical_hash(record) != evidence.get('record_hash')
            or program.get('operations') != _operations(record, evidence)
            or program.get('response_kinds') != evidence.get('responses')
            or program.get('mechanism_condition_policy') != CONDITION_POLICY):
        raise ValueError('Reviewed component identity or source differs from configuration')
    for actor in state.values():
        validate_member(actor)
    for component in program['mechanism_components']:
        if component['op'] in {'power.percent','next.priority','attack.poison'} and _selected(component,state,context):
            grant_modifier(deepcopy(state[component['target']]),component,program,context)
    common_context = {**context, 'component_sequence_payment': 'reviewed_component_sequence_v1'}
    preflight_skill(_base(program, state, context), state, common_context, damage_resolver)


def _change_cost(actor, component, program, context):
    mid = (context.get('opponent_declared_skill') if component.get('skill_selector') == 'opponent.declared_skill'
           else program['game_id'])
    if component.get('skill_selector') == 'all':
        mid = 0
    if mid is None:
        return {'op': 'modifier.skipped', 'reason': 'opponent_did_not_declare_a_skill'}
    turn = context['turn']
    from lab.modifier_ledger import enhance_amount
    amount = enhance_amount(actor,program['game_id'],program['source_hash'],'skill.cost',component['amount'])
    if amount.denominator != 1:
        raise ValueError('Layer-adjusted cost must remain integral')
    item = {'skill_id': mid, 'amount': amount.numerator, 'applied_turn': turn,
        'expires_after': turn + component['rounds'] - 1 if 'rounds' in component else None,
        'source_skill_id': program['game_id'], 'source_hash': program['source_hash'], 'policy': POLICY}
    if component.get('attack_only'):item['attack_only']=True
    if component.get('exclude_application_turn'):
        from lab.action_outcome_runtime import committed_history
        committed_history(actor)
        item['exclude_application_turn']=True
    actor.setdefault('skill_modifiers', []).append(item)
    return {'op': 'skill.cost.modify', 'target': component['target'], **deepcopy(item)}


def execute(program, state, context, damage_resolver=None):
    preflight(program, state, context, damage_resolver)
    selected = [c for c in program['mechanism_components'] if _selected(c, state, context)]
    common_context = {**context, 'component_sequence_payment': 'reviewed_component_sequence_v1'}
    result = execute_skill(_base(program, state, context), state, common_context, damage_resolver=damage_resolver)
    if result['status'] != 'applied':
        return result
    current, events = result['state'], result['events']
    defeated = state['opponent']['hp'] > 0 and current['opponent']['hp'] == 0 and any(
        e.get('op') == 'damage' and e.get('target') == 'opponent' and e.get('damage',0) > 0 for e in events)
    post = [c for c in program['mechanism_components'] if c.get('when') == 'opponent.defeated_by_skill' and defeated]
    selected.extend(post)
    post_common = [c for c in post if c['op'] in COMMON_EFFECTS | {'stat.modify'}]
    if post_common and current['self']['hp'] > 0:
        after = {**deepcopy(program),'operations':[],'mechanism_components':post_common}
        post_context = {**common_context,'_committed_opponent_defeat':True,
                        'resolved_energy_cost':0,'component_sequence_paid_cost':context.get('resolved_energy_cost',0)}
        follow = execute_skill(_base(after,current,post_context),current,post_context,damage_resolver=damage_resolver)
        if follow['status'] != 'applied':
            return {**follow,'state':deepcopy(state),'events':[]}
        result['state'] = current = follow['state']
        events.extend(e for e in follow['events'] if e['op'] != 'energy.pay')
    loss = sum(e.get('damage', e.get('amount', 0)) for e in events
               if e.get('op') in ('damage', 'damage.hit') and e.get('target') == 'opponent')
    # The common executor records before/after HP per hit. Use these observed
    # losses, never nominal overkill, for the drain base.
    for component in selected:
        op, actor = component['op'], current[component['target']]
        if op == 'hp.consume_all':
            before = actor['hp']
            actor['hp'] = 0
            events.append({'op':'hp.consume_all','target':component['target'],'before':before,'after':0,
                'amount':before,'source_skill_id':program['game_id'],'source_hash':program['source_hash'],
                'policy':'after_successful_attack_effect_even_if_opponent_exhausted_not_payment_v1'})
        elif op == 'hp.drain' and actor['hp'] > 0:
            if component['target'] == 'self':
                from lab.trait_attack_hooks import defer_drain
                deferred = defer_drain(program, component, context, actor)
                if deferred is not None:
                    events.append(deferred)
                    continue
            before = actor['hp']
            actor['hp'] = min(actor['max_hp'], before + loss * component['percent'] // 100)
            events.append({'op': 'hp.drain', 'target': component['target'], 'damage_basis': loss,
                           'amount': actor['hp'] - before, 'policy': POLICY})
        elif op in {'speed.flat', 'power.flat', 'power.percent', 'next.priority', 'attack.poison', 'next.cost', 'next.power', 'hits.flat', 'hits.percent'} and 'repeat_hits' not in component:
            events.append(grant_modifier(actor,component,program,context))
        elif op == 'skill.cost' and 'repeat_hits' not in component:
            if component['event'] == 'turn.end':
                actor.setdefault('pending_modifiers', []).append({'component': deepcopy(component),
                    'program': {'game_id': program['game_id'], 'source_hash': program['source_hash']},
                    'context': {'turn': context['turn']}, 'policy': POLICY})
            else:
                events.append(_change_cost(actor, component, program, context))
        elif op == 'restriction.root' and actor['hp'] > 0:
            expiry = context['turn'] + component['rounds'] - 1
            old = actor.get('root_restriction', {})
            actor['root_restriction'] = {'expires_after': max(expiry, old.get('expires_after', expiry)),
                'policy': POLICY, 'source_skill_id': program['game_id'], 'source_hash': program['source_hash']}
            actor['rooted'] = True
            events.append({'op': 'restriction.root', 'target': component['target'], **actor['root_restriction']})
    return result


def end_turn(state):
    events, turn = [], state['turn']
    for side, team in state['teams'].items():
        for actor in team['members']:
            validate_member(actor)
            for pending in actor.pop('pending_modifiers', []):
                if pending.get('policy') != POLICY or pending['context']['turn'] != turn:
                    raise ValueError('Stale or unknown pending modifier')
                event = _change_cost(actor, pending['component'], pending['program'], pending['context'])
                events.append({**event, 'target_side': side, 'target_member_id': actor['member_id']})
            actor['skill_modifiers'] = [m for m in actor.get('skill_modifiers', [])
                                       if m['expires_after'] is None or m['expires_after'] > turn]
            restriction = actor.get('root_restriction')
            if restriction and restriction['expires_after'] <= turn:
                actor.pop('root_restriction')
                actor['rooted'] = False
                events.append({'op': 'restriction.expire', 'target_side': side,
                               'target_member_id': actor['member_id'], 'restriction': 'root', 'policy': POLICY})
    return events


def after_skill_hits(prepared, state, side, skill_id, *, token):
    """Commit a source-bound wing-skill trait increment once after skill success."""
    from lab import trait_runtime
    if state.get('trait_policy') != trait_runtime.POLICY:
        return []
    team = state['teams'][side]
    member = team['members'][team['active_slot']]
    form = prepared._rules.form(member['form_id'])
    tid = form.get('trait_id')
    row = next((r for r in _configuration(CONFIG.stat().st_mtime_ns).get('trait_hits', [])
                if r['trait_id'] == tid), None)
    if row is None:
        return []
    if (member.get('trait_id') != tid or member.get('trait_policy') != trait_runtime.POLICY
            or state.get('snapshot_id') != prepared.snapshot_id
            or canonical_hash(prepared._rules._catalog['traits'][str(tid)]) != row['record_hash']
            or row['raw'] != prepared._rules._catalog['traits'][str(tid)]
            or row.get('hit_policy') != HIT_POLICY):
        raise ValueError('Hit trait source or member binding changed')
    if prepared._rules.skill(skill_id)['type'] != row['skill_type'] or member['hp'] <= 0:
        return []
    if not isinstance(token, str) or not token:
        raise ValueError('Hit trait needs a unique successful action token')
    item = {**row['component'], 'policy': POLICY, 'hit_policy': HIT_POLICY,
        'source_trait_id': tid, 'source_hash': row['record_hash'], 'token': token,
        'trigger_skill_id': skill_id}
    _flat(member, 'hits.flat')
    ledger = member.setdefault('mechanism_flat_modifiers', [])
    previous = [r for r in ledger if r.get('source_trait_id') == tid and r.get('token') == token]
    if previous:
        if previous != [item]:
            raise ValueError('Hit trait token reused for a different action')
        return []
    ledger.append(item)
    return [{**deepcopy(item), 'op': 'trait.hits.modify', 'target': 'self', 'target_side': side,
        'target_member_id': member['member_id']}]


def grant_modifier(member, component, program, context):
    from lab.modifier_ledger import enhance_amount, enhance_buff_amount
    op = component['op']
    amount = (enhance_buff_amount(member,component['buff_id'],op,component['amount']) if 'buff_id' in component
        else enhance_amount(member,program['game_id'],program['source_hash'],op,component['amount']))
    if amount.denominator != 1:raise ValueError('Modifier layer amount must be integral')
    item = {'op':op,'amount':amount.numerator,'policy':POLICY,
        'source_skill_id':program['game_id'],'source_hash':program['source_hash']}
    if 'buff_id' in component:item['buff_id']=component['buff_id']
    if component.get('skill_selector') == 'self':item['skill_id']=program['game_id']
    if 'skill_type' in component:item['skill_type']=component['skill_type']
    if op == 'attack.poison':
        slots = context.get('carried_attack_skill_ids')
        if not isinstance(slots,list) or any(type(k) is not int for k in slots):
            raise ValueError('Attached poison requires resolved carried attack skill IDs')
        item['skill_ids']=sorted(set(slots))
    if op.startswith('next.'):item['next_policy']=NEXT_POLICY
    if op.startswith('hits.'):item['hit_policy']=HIT_POLICY
    member.setdefault('mechanism_flat_modifiers',[])
    if op == 'next.priority':
        member['mechanism_flat_modifiers']=[e for e in member['mechanism_flat_modifiers'] if e['op']!=op]
    member['mechanism_flat_modifiers'].append(item)
    return {**deepcopy(item),'target':component['target']}


def priority_bonus(member):
    return _flat(member,'next.priority')


def consume_priority(member):
    priority_bonus(member)
    consumed=[e for e in member.get('mechanism_flat_modifiers',[]) if e['op']=='next.priority']
    member['mechanism_flat_modifiers']=[e for e in member.get('mechanism_flat_modifiers',[]) if e not in consumed]
    return [{'op':'modifier.priority.consume','target':'self','modifier':deepcopy(e)} for e in consumed]


def after_skill(state, program, context, events):
    entries=[e for e in state['self'].get('mechanism_flat_modifiers',[]) if e['op']=='attack.poison'
             and program['game_id'] in e['skill_ids']]
    if (not entries or not any(e.get('op')=='damage' and e.get('target')=='opponent' for e in events)
            or any(state[s]['hp']<=0 for s in ('self','opponent'))):return state,[]
    from lab.modifier_ledger import flat_info
    for e in entries:flat_info(e,'mechanism_flat_modifiers')
    from lab.effect_runtime import execute_effects
    primitive={**deepcopy(program),'game_id':entries[0]['source_skill_id'],'source_hash':entries[0]['source_hash'],
        'operations':[{'op':'status.add','params':{'target':'opponent','status':'poison','stacks':sum(e['amount'] for e in entries)}}]}
    nested={**context,'source_hash':primitive['source_hash'],'resolved_energy_cost':0,
        'component_sequence_paid_cost':context.get('resolved_energy_cost',0)}
    result=execute_effects(primitive,state,nested)
    if result['status']!='applied':raise ValueError('Attached poison failed: '+'; '.join(result['blockers']))
    return result['state'],[{**e,'attachment_sources':deepcopy(entries),
        'attachment_policy':'carried_attack_ids_at_grant_once_after_whole_successful_attack_v1'}
        for e in result['events'] if e['op']!='energy.pay']


def consume_next(member, *, attacked):
    """Common executor calls after successful paid execution, before new grants."""
    _flat(member, 'next.cost')
    consumed = [m for m in member.get('mechanism_flat_modifiers', [])
                if m['op'] == 'next.cost' or attacked and m['op'] == 'next.power']
    if consumed:
        member['mechanism_flat_modifiers'] = [m for m in member['mechanism_flat_modifiers'] if m not in consumed]
    return [{'op': 'modifier.consume', 'target': 'self', 'modifier': deepcopy(item),
             'policy': NEXT_POLICY} for item in consumed]


def consume_skill_tokens(member, *, attacked, turn):
    events = consume_next(member, attacked=attacked)
    from lab.trait_runtime import consume_energy_attack_stats
    events.extend(consume_energy_attack_stats(member,attacked))
    from lab.attack_grant_runtime import consume_power
    events.extend(consume_power(member, attacked=attacked))
    if any(e.get('kind') == 'charge_skip' for e in member.get('timed_effects', [])):
        from lab.duration_runtime import consume_charge_bypass
        result = consume_charge_bypass(member, turn)
        member.clear(); member.update(result['member'])
        events.extend(result['events'])
    return events
