"""Reviewed trait slot gates and entry Swift grants; timing is experimental."""
from copy import deepcopy

from lab.dynamic_skills import duplicate_slots_allowed
from lab.prepared_rules import prepare_rules
from lab.ruleset import canonical_hash
from lab.switch_rules import SKILLS_SHA256


POLICY = 'source_bound_trait_slot_gates_and_entry_swift_experiment_v1'
SWIFT_POLICY = 'source_intrinsic_and_reviewed_trait_grants_experiment'
BASE_COST_POLICY = 'trait_swift_checks_source_base_energy_before_cost_modifiers_experiment'
ROWS = {
    200208: {'record_hash': '248f35f838cc73d379209d291a037d8c1847509126b1686fed33157b42fbdeee',
             'allowed_slots': [0]},
    280017: {'record_hash': '108d9af58f496d6560b225bbdc4566c82a9b4638b8dd3808765bc22696e01685',
             'allowed_slots': [0, 2]},
    200129: {'record_hash': '6f17d55667f7f9de0d5046e2ff83b8af839889856d3232c5931a88a0e4912c69',
             'swift_base_cost_lt': 3},
    200173: {'record_hash': '04933828d862777ebbf0a6a6846166cf47a5f6b26a80ec74c8c5c27dc4e6c8b8',
             'swift_skill_type': '龙系'},
}


def source_evidence(rules, member):
    """Validate the same exact action-trait source for execution and HUD support."""
    from lab.trait_runtime import POLICY as TRAIT_POLICY, CONFIG_HASH
    source = rules._catalog
    form = rules.form(member['form_id'])
    tid = form.get('trait_id')
    if member.get('trait_id', tid) != tid:
        raise ValueError('Action trait differs from its exact source form')
    definition = ROWS.get(tid)
    if definition is None:
        return None
    raw = source.get('traits', {}).get(str(tid))
    provenance = source.get('provenance', {}).get('Skills', {})
    if (not raw or canonical_hash(raw) != definition['record_hash']
            or provenance.get('content_sha256') != SKILLS_SHA256):
        raise ValueError('Action trait whole source changed; review required')
    if (member.get('trait_source_hash', definition['record_hash']) != definition['record_hash']
            or member.get('trait_policy', TRAIT_POLICY) != TRAIT_POLICY
            or member.get('trait_config_hash', CONFIG_HASH) != CONFIG_HASH):
        raise ValueError('Action trait member source binding changed')
    return {'policy': POLICY, 'trait_id': tid, 'source_hash': definition['record_hash'],
            'raw': deepcopy(raw), 'source': deepcopy(provenance), 'member_id': member.get('member_id'),
            'form_id': member['form_id'], 'snapshot_id': rules.snapshot_id,
            'components': deepcopy(definition), 'base_cost_policy': BASE_COST_POLICY,
            'real_game_verified': False}


def evidence(prepared, state, member):
    if 'trait_policy' not in state:
        return None
    from lab.trait_runtime import POLICY as TRAIT_POLICY
    if state['trait_policy'] != TRAIT_POLICY:
        raise ValueError('Unknown trait research policy')
    prepared = prepare_rules(prepared)
    row = source_evidence(prepared._rules, member)
    if row and state.get('snapshot_id') != prepared.snapshot_id:
        raise ValueError('Action trait whole source changed; review required')
    return row


def check_evidence_slot(row, slot):
    if type(slot) is not int or not 0 <= slot < 4:
        raise ValueError('Action trait requires a skill slot in 0..3')
    allowed = row['components'].get('allowed_slots') if row else None
    if allowed is not None and slot not in allowed:
        raise ValueError(f"Trait {row['trait_id']} forbids current skill slot {slot + 1}")
    return row


def check_skill_slot(prepared, state, member, slot):
    """Gate the current numbered slot, including moved/generated/copied skills."""
    return check_evidence_slot(evidence(prepared, state, member), slot)


def swift_candidates(prepared, state, member, effective_costs, *, include_trait_grants=True):
    """Keep all four positions; grants use source cost/type, affordability final cost."""
    prepared = prepare_rules(prepared)
    slots = member.get('skill_slots')
    if (not isinstance(slots, list) or len(slots) != 4
            or not isinstance(effective_costs, list) or len(effective_costs) != 4):
        raise ValueError('Trait Swift requires four ordered skill slots and explicit costs')
    if not duplicate_slots_allowed(member):
        raise ValueError('Duplicate Swift slots require source-tracked generation or copying')
    row = evidence(prepared, state, member)
    components = row['components'] if row else {}
    from lab.trait_switch_components import swift_grants
    delegated = swift_grants(prepared, state, member) if include_trait_grants else {}
    result = []
    switches = prepared._components()[2]
    for slot, (sid, cost) in enumerate(zip(slots, effective_costs)):
        if type(sid) is not int or sid < 0 or cost is not None and (type(cost) is not int or cost < 0):
            raise ValueError('Trait Swift IDs and costs must be nonnegative integers')
        if sid == 0:
            if cost is not None:
                raise ValueError('Empty skill slots require null costs')
            result.append(None)
            continue
        metadata = switches.skill_swift_metadata(sid)
        from lab.skill_history_runtime import conditional_swift
        conditional = conditional_swift(prepared,state,member,sid)
        skill = prepared._rules.skill(sid)
        grant = include_trait_grants and (
            'swift_base_cost_lt' in components and skill['energy'] < components['swift_base_cost_lt']
            or 'swift_skill_type' in components and skill['type'] == components['swift_skill_type']
            or slot in delegated)
        allowed = slot in components.get('allowed_slots', [0, 1, 2, 3])
        candidate = {'skill_id': sid, 'effective_cost': cost, 'source_metadata': metadata,
                     'swift': (True if grant else conditional['swift'] if conditional else metadata['swift']) if allowed else False}
        if conditional is not None:
            candidate['conditional_swift'] = conditional
        if row:
            candidate['action_trait'] = {**deepcopy(row), 'swift_granted': bool(grant),
                'slot_allowed': allowed, 'slot': slot, 'skill_source_hash': canonical_hash(skill),
                'skill_raw': deepcopy(skill)}
        elif slot in delegated:
            candidate['action_trait'] = deepcopy(delegated[slot])
        result.append(candidate)
    return result


def entry_program_has_swift(program, candidate):
    intrinsic = (program.get('intrinsic_swift') is True
        and program.get('entry_trigger') == {'kind': 'voluntary_switch', 'term_id': 1005}
        and 1005 in program.get('dependency_ids', []))
    granted = candidate.get('action_trait', {}).get('swift_granted') is True
    from lab.skill_history_runtime import conditional_swift_matches
    conditional = conditional_swift_matches(program,candidate)
    return (program.get('status') == 'compiled' and program.get('game_id') == candidate['skill_id']
            and (intrinsic or granted or conditional))
