"""Whole-source binary skill choices; no default, random, or inferred selection."""
from copy import deepcopy
import json
from pathlib import Path

from lab.effect_runtime import execute_effects, _preflight_header, REVIEWED_TERMS_SHA256
from lab.phase_config import fingerprint, load_phase_config
from lab.prepared_rules import prepare_rules

CONFIG = Path(__file__).resolve().parents[1] / "data/rules/reviewed-choice-components-1.json"
CONFIG_HASH = '9217b693472ea114e69bf76517f83da658f027a756ef89887ab00812c2f44254'
POLICY = "explicit_source_order_binary_choice_before_payment_experiment_v1"
RECOIL_POLICY = 'declared_max_hp_floor_after_skill_nonlethal_only_boundary_block_v1'


def rules():
    data = json.loads(CONFIG.read_text(encoding="utf8"))
    if fingerprint(data) != CONFIG_HASH:
        raise ValueError("Reviewed choice configuration changed")
    return data


def choice_programs(catalog):
    prepared = prepare_rules(catalog)
    source, data = prepared._rules._catalog, rules()
    load_phase_config(source)
    if (source["snapshot_id"] != data["snapshot_id"] or
            next((r for r in source["glossary"] if r["key"] == 3019), None) != data["term"]):
        raise ValueError("Choice source or term differs")
    records = source["moves"]
    records = records if isinstance(records, dict) else {str(r["id"]): r for r in records}
    output = {}
    for mid, row in data["skills"].items():
        if fingerprint(records.get(mid)) != row["record_hash"]:
            raise ValueError("Choice whole skill source differs")
        for skill_type,ids in row.get('carried_type_ids',{}).items():
            if ids != sorted(int(k) for k,v in records.items() if v['type']==skill_type):
                raise ValueError('Choice carried-type selector source changed')
        program = deepcopy(prepared._rules.program(int(mid)))
        program.pop("native_rule", None)
        program.update(status="compiled", blockers=[], dependency_ids=row["record"]["desc_notes"],
            operations=[{"op": "choice.select", "params": {"options": deepcopy(row["options"])}}],
            choice_components=deepcopy(row["options"]), choice_policy=POLICY,
            choice_config_hash=CONFIG_HASH, response_kinds=deepcopy(row.get("responses", [])), executable=False, real_game_verified=False)
        if any(op['op']=='damage.sequence' for option in row['options'] for op in option):
            program['dependency_ids'] = sorted(set(program['dependency_ids']) | {3005})
        output[int(mid)] = program
    return output


def select(program, option, *, context, state=None, validate_only=False):
    """Validate and resolve an explicit 0=明/1=暗 branch before any payment."""
    data = rules()
    row = data["skills"].get(str(program.get("game_id")))
    if (row is None or program.get("source_hash") != row["record_hash"]
            or program.get("snapshot_id") != data["snapshot_id"]
            or program.get("term_source", {}).get("content_sha256") != REVIEWED_TERMS_SHA256
            or program.get("choice_policy") != POLICY or program.get("choice_config_hash") != CONFIG_HASH
            or program.get("choice_components") != row["options"]
            or program.get("operations") != [{"op": "choice.select", "params": {"options": row["options"]}}]):
        raise ValueError("Choice program/source differs from reviewed definition")
    if context.get("choice_policy") != POLICY or type(option) is not int or option not in (0, 1):
        raise ValueError("Choice requires explicit policy and option 0 (明) or 1 (暗)")
    if validate_only:
        return deepcopy(program)
    selected = deepcopy(program)
    selected['operations'] = []
    for operation in row['options'][option]:
        if 'when_slot' in operation:
            from lab.mark_runtime import _skill_slot
            if not isinstance(state,dict):raise ValueError('Slot choice requires owned actor state')
            if _skill_slot(state['self'],program['game_id'],context)!=operation['when_slot']:continue
        if 'when_response' in operation:
            if type(context.get('response_success')) is not bool:
                raise ValueError('Conditional choice requires explicit response classification')
            if context['response_success'] != operation['when_response']:
                continue
        if 'when' in operation:
            from lab.rule_expressions import evaluate_condition
            if not isinstance(state,dict):
                raise ValueError('Conditional choice requires the owned actor state')
            if not evaluate_condition(operation['when'],state):
                continue
        if 'when_carried_type' in operation:
            if not isinstance(state,dict):raise ValueError('Carried-type choice requires live slot state')
            condition=operation['when_carried_type'];slots=state[condition['target']]['skill_slots']
            matched=any(mid in row['carried_type_ids'][condition['type']] for mid in slots)
            if matched != condition['present']:continue
        resolved={k:deepcopy(v) for k,v in operation.items() if k not in ('when','when_response','when_slot','power_if_slot','power_factor_on_response','when_carried_type')}
        if 'power_factor_on_response' in operation:
            if type(context.get('response_success')) is not bool:
                raise ValueError('Choice power factor requires explicit response success')
            if context['response_success']:
                resolved['params']['choice_power_factor'] = operation['power_factor_on_response']
        if 'power_if_slot' in operation:
            from lab.mark_runtime import _skill_slot
            if not isinstance(state,dict):raise ValueError('Slot power requires owned actor state')
            bonus=operation['power_if_slot']
            if _skill_slot(state['self'],program['game_id'],context)==bonus['slot']:
                resolved['params']['power']+=bonus['amount']
        selected['operations'].append(resolved)
    return selected


def response_categories(program, option):
    row = rules()['skills'].get(str(program.get('game_id')))
    if row is None or program.get('source_hash') != row['record_hash']:
        raise ValueError('Choice response source differs')
    if 'option_responses' not in row:
        return deepcopy(row.get('responses', []))
    if type(option) is not int or option not in (0,1):
        raise ValueError('Choice response requires an explicit selected branch')
    return deepcopy(row['option_responses'][option])


def current_power_factor(skill_id, params, context):
    factor = params.get('choice_power_factor',1)
    if type(factor) is not int or factor < 1:
        raise ValueError('Choice power factor requires a positive source integer')
    if factor == 1:
        return 1
    row = rules()['skills'].get(str(skill_id))
    option = context.get('choice_option')
    if (row is None or type(option) is not int or option not in (0,1)
            or context.get('source_hash') != row['record_hash'] or context.get('response_success') is not True
            or not any(op.get('power_factor_on_response') == factor for op in row['options'][option])):
        raise ValueError('Choice current power factor differs from committed branch source')
    return factor


EXTRA_OPS={'speed.flat','power.flat','devotion.add','mark.remove_layers','transmission.extra','hp.recoil_percent','skill.replace_declared'}


def cost(program, option, value, *, actor=None):
    row=rules()['skills'].get(str(program.get('game_id')))
    if row is None or 'option_cost_deltas' not in row:return value
    if type(option) is not int or option not in (0,1):raise ValueError('Choice cost needs explicit branch')
    if program.get('source_hash')!=row['record_hash']:raise ValueError('Choice cost source changed')
    from lab.trait_runtime import cost_delta
    return max(0,value+cost_delta(actor or {},row['option_cost_deltas'][option]))


def _extras(program,state,context,operations):
    from lab import mechanism_runtime as mechanisms, mark_runtime as marks
    events=[]
    for operation in operations:
        op,params=operation['op'],operation['params'];member=state[params.get('target','self')]
        if op=='hp.recoil_percent':
            policy=RECOIL_POLICY
            if context.get('choice_recoil_policy')!=policy:
                raise ValueError('Explicit max-HP floor choice recoil policy required')
            before=member['hp'];amount=member['max_hp']*params['percent']//100
            if amount>=before:raise ValueError('Choice recoil may be lethal; source KO boundary remains unresolved')
            member['hp']-=amount
            events.append({'op':op,'target':params['target'],'before':before,'after':member['hp'],'amount':amount,
                'source_skill_id':program['game_id'],'source_hash':program['source_hash'],'policy':policy})
        elif op=='skill.replace_declared':
            slot=context.get('opponent_declared_slot');declared=context.get('opponent_declared_skill')
            if (context.get('opponent_kind')!='status' or type(slot) is not int or not 0<=slot<4
                    or context.get('opponent_declared_member_id')!=member['member_id']
                    or member['skill_slots'][slot]!=declared):
                raise ValueError('Choice slot replacement requires the exact live declared status member/slot')
            binding={'turn':context['turn'],'source_skill_id':program['game_id'],'source_hash':program['source_hash'],
                'config_hash':CONFIG_HASH,'actor_member_id':state['self']['member_id'],'option':context['choice_option'],
                'target_member_id':member['member_id'],'target_slot':slot,'target_skill_id':declared,
                'replacement_id':params['skill_id']}
            binding['hash']=fingerprint(binding)
            events.append({'op':'choice.deferred_slot_replacement','binding':binding})
        elif op in {'speed.flat','power.flat'}:
            events.append(mechanisms.grant_modifier(member,{'op':op,**params},program,context))
        elif op=='devotion.add':
            marks._policy(context)
            if params['enhancement'] not in marks.DEVOTIONS:raise ValueError('Unknown devotion enhancement')
            values=deepcopy(marks._devotion(member));key=params['enhancement'];values[key]=values.get(key,0)+params['amount']
            member['team_devotion']=values
            events.append({'op':op,'target':'self','enhancement':key,'after':values[key],
                'source_skill_id':program['game_id'],'source_hash':program['source_hash'],'policy':marks.POLICIES['devotion']})
        elif op=='mark.remove_layers':
            for target in params['targets']:
                for mark in list(marks._slots(state[target]).values()):
                    if mark is None:continue
                    raw_id=marks._data()['marks'][str(mark['id'])]['buff_raw']['id']
                    if raw_id not in params['eligible_buff_ids']:raise ValueError('Owned mark not in source removal pool')
                    changed,extra=marks.change_marks(state[target]['field_marks'],mark['id'],-min(mark['stacks'],params['amount']),
                        context=context,source={'skill_id':program['game_id'],'source_hash':program['source_hash']})
                    state[target]['field_marks']=changed
                    events.extend({**e,'target':target,'candidate_buff_ids':params['eligible_buff_ids'],
                        'selection_policy':'each_owned_matching_mark_loses_one_layer_experiment_v1'} for e in extra)
        elif op=='transmission.extra':
            from lab.dynamic_skills import remap_member_slots
            start=marks._skill_slot(member,program['game_id'],context)
            permutation=list(range(4));permutation.insert((start+params['amount'])%4,permutation.pop(start))
            before=list(member['skill_slots']);member['skill_slots']=[before[i] for i in permutation]
            events.extend(remap_member_slots(member,permutation,turn=context.get('turn')))
            events.append({'op':op,'target':'self','before':before,'after':list(member['skill_slots']),
                'source_skill_id':program['game_id'],'source_hash':program['source_hash'],
                'policy':'extra_self_transmission_after_successful_skill_base_round_start_unchanged_v1'})
    return events


def after_skill(catalog,state,side,action,events,*,context,event_token):
    deferred=[e['binding'] for e in events if e.get('op')=='choice.deferred_slot_replacement']
    if not deferred:return []
    prepared=prepare_rules(catalog);current=deepcopy(state);output=[]
    program=action['program'];row=rules()['skills'].get(str(action['skill_id']))
    if row is None or program.get('source_hash')!=row['record_hash']:
        raise ValueError('Deferred choice replacement source changed')
    ledger=current.setdefault('choice_slot_replacements',{})
    other='b' if side=='a' else 'a'
    for index,binding in enumerate(deferred):
        if (binding.get('hash')!=fingerprint({k:v for k,v in binding.items() if k!='hash'})
                or binding.get('config_hash')!=CONFIG_HASH or binding.get('turn')!=current['turn']
                or binding.get('actor_member_id')!=action['actor_member_id']
                or binding.get('source_skill_id')!=action['skill_id'] or binding.get('source_hash')!=program['source_hash']
                or type(binding.get('option')) is not int or binding['option'] not in (0,1)
                or not any(op['op']=='skill.replace_declared' and op['params']['skill_id']==binding['replacement_id']
                    for op in row['options'][binding['option']])):
            raise ValueError('Deferred choice target/source binding changed')
        token=event_token+':'+str(index)
        if token in ledger:
            if ledger[token]!=binding['hash']:raise ValueError('Choice replacement token reused')
            continue
        target=next((m for m in current['teams'][other]['members'] if m['member_id']==binding['target_member_id']),None)
        if (target is None or type(binding.get('target_slot')) is not int or not 0<=binding['target_slot']<4
                or target['skill_slots'][binding['target_slot']]!=binding['target_skill_id']
                or prepared._rules.skill(binding['target_skill_id'])['kind']!='status'):
            raise ValueError('Deferred choice status target changed; refusing to replace an unrelated slot')
        from lab.transformation_runtime import replace_battle_slot,_candidate_blocker
        code,blocker=_candidate_blocker(prepared,binding['replacement_id'])
        output.append(replace_battle_slot(current,other,target['member_id'],binding['target_slot'],binding['replacement_id'],
            source_skill_id=action['skill_id'],source_hash=program['source_hash'],kind='slot_replace',
            prior_dynamic_origin=target.get('dynamic_skill_origins',{}).get(str(binding['target_slot'])),
            prior_transformation_origin=target.get('transformation_skill_origins',{}).get(str(binding['target_slot'])),
            blocker=blocker,blocker_code=code))
        ledger[token]=binding['hash']
    state.clear();state.update(current)
    return output


def preflight(program, state, context, *, option, damage_resolver=None):
    from lab.effect_runtime import _preflight
    selected=select(program,option,context=context,state=state)
    extra=[op for op in selected['operations'] if op['op'] in EXTRA_OPS]
    _extras(program,deepcopy(state),context,extra)
    selected['operations']=[op for op in selected['operations'] if op['op'] not in EXTRA_OPS]
    return _preflight(selected,state,{**context,'component_sequence_payment':'reviewed_component_sequence_v1'},damage_resolver)


def execute_choice_skill(program, state, context, *, option, damage_resolver=None):
    result={'status':'blocked','state':deepcopy(state),'events':[],'blockers':[],
        'training_eligible':False,'real_game_verified':False,'calibrated':False}
    try:
        _preflight_header(program,state,context)
        preflight(program,state,context,option=option,damage_resolver=damage_resolver)
        selected=select(program,option,context=context,state=state)
        extra=[op for op in selected['operations'] if op['op'] in EXTRA_OPS]
        selected['operations']=[op for op in selected['operations'] if op['op'] not in EXTRA_OPS]
        applied=execute_effects(selected,state,{**context,'component_sequence_payment':'reviewed_component_sequence_v1'},damage_resolver=damage_resolver)
        if applied['status']!='applied':return applied
        stopped=(context.get('faint_policy')=='stop_remaining_skill_on_exhaustion_experiment'
            and any(applied['state'][side]['hp']==0 for side in ('self','opponent')))
        if not stopped:applied['events'].extend(_extras(program,applied['state'],context,extra))
        applied['events'].insert(0,{'op':'choice.select','option':option,'label':'明' if option==0 else '暗',
            'source_hash':program['source_hash'],'config_hash':CONFIG_HASH,'policy':POLICY})
        return applied
    except (ValueError,TypeError,KeyError) as exc:
        result['blockers']=[str(exc)]
    return result
