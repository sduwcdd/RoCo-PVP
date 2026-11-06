"""Transactional execution of *isolated*, explicitly parameterized skill effects.

This is an engine component, not a battle simulator. It does not derive damage,
rounding, final energy cost, stat stacking, turn order, or trigger behavior. All
applications are uncalibrated experiments and can never qualify training data.
Unsupported operations/dependencies reject the entire transaction, including any
explicit energy payment. Inputs and resolver arguments are isolated by copying.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import hashlib
import json

from lab import status_lifecycle as lifecycle


HOOKS = frozenset({"traits", "field", "marks", "bloodlines", "event_triggers"})
STATS = frozenset({"patk", "matk", "pdef", "mdef", "spd"})
IMMUNITIES = {"poison": "毒系", "burn": "火系", "freeze": "冰系", "leech": "草系"}
TYPES = frozenset({"光系", "冰系", "地系", "幻系", "幽系", "恶系", "普通系", "机械系", "武系", "毒系",
                   "水系", "火系", "电系", "翼系", "草系", "萌系", "虫系", "龙系"})
REVIEWED_TERMS_SHA256 = 'a7a4ad3bc1e30e154cdbc52b9e350ec75cbca04bb39e1b9e7012fa4a220ca822'
OPS = frozenset({"skill.noop", "mark.clear_reward", "modifier.grant", "status.trigger", "damage", "damage.sequence", "damage.conditional", "energy.restore", "energy.reduce", "energy.transfer", "hp.restore", "hp.exchange_ratio", "hp.copy_ratio", "modifier.dispel", "modifier.exchange", "modifier.invert_stats", "modifier.double", "modifier.flat", "modifier.dispel_limited", "skill.cost", "stat.modify", "status.add", "status.multiply"})


def _hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _stat_term(member, percent, context):
    """A ten-percent layer is explicit research policy, never inferred silently."""
    from lab import mark_runtime as marks
    value = Fraction(percent["numerator"], percent["denominator"])
    if value <= 0 or not marks.layer_count(member, 3012):
        return deepcopy(percent)
    if context.get("mark_policies") != marks.research_context()["mark_policies"]:
        raise ValueError("Sprout buff layers require explicit mark research policies")
    layers = value * 10
    if layers.denominator != 1:
        raise ValueError("Sprout cannot infer layers from a non-ten-percent stat increment")
    value = Fraction(marks.extra_buff_layers(member, layers.numerator), 10)
    return {"numerator": value.numerator, "denominator": value.denominator}


def _ratio(value, label):
    if not isinstance(value, dict) or set(value) != {"numerator", "denominator"}:
        raise ValueError(f"{label} must retain an explicit rational term")
    if type(value["numerator"]) is not int:
        raise ValueError(f"{label} numerator must be an integer")
    _integer(value["denominator"], label + " denominator", 1)


def _energy_cap(member, value):
    from lab.trait_runtime import energy_allows_overflow
    return value if energy_allows_overflow(member) else min(member['max_energy'],value)


def _energy_recovery(member, requested, context):
    if not member.get('timed_effects'):
        return requested
    from lab.duration_runtime import recovery_amount
    return recovery_amount(member, requested, context.get('turn'))['amount']


def _freeze_events(state):
    events = []
    for relative in ("self", "opponent"):
        for event in lifecycle.check_freeze(state[relative], relative):
            event.pop("target_side", None)  # The outer battle maps relative targets.
            events.append({**event, "target": relative})
    return events


def _state(state):
    if not isinstance(state, dict):
        raise ValueError("state must be an object")
    _hash(state)  # Reject non-JSON state and non-finite numbers, rather than coerce.
    for side in ("self", "opponent"):
        actor = state.get(side)
        if not isinstance(actor, dict):
            raise ValueError(f"missing {side} actor")
        for key in ("hp", "max_hp", "energy", "max_energy"):
            _integer(actor.get(key), f"{side}.{key}", 1 if key == "max_hp" else 0)
        from lab.trait_runtime import energy_allows_overflow
        if actor["hp"] > actor["max_hp"] or (actor["energy"] > actor["max_energy"] and not energy_allows_overflow(actor)):
            raise ValueError(f"{side} resource exceeds its explicitly supplied maximum")
        types = actor.get("types")
        if (not isinstance(types, list) or not 1 <= len(types) <= 2
                or any(not isinstance(x, str) or x not in TYPES for x in types)
                or len(set(types)) != len(types)):
            raise ValueError(f"{side}.types must contain 1–2 distinct BWIKI types; unknown or empty types cannot bypass immunity")
        if not isinstance(actor.get("statuses"), dict) or set(actor["statuses"]) - IMMUNITIES.keys():
            raise ValueError(f"{side}.statuses contains unsupported status state")
        for key, value in actor["statuses"].items():
            _integer(value, f"{side}.statuses.{key}")
        lifecycle.validate_lifecycles(actor)
        if not isinstance(actor.get("stat_modifiers"), dict) or set(actor["stat_modifiers"]) - STATS:
            raise ValueError(f"{side}.stat_modifiers contains unsupported attributes")
        for key, terms in actor["stat_modifiers"].items():
            if not isinstance(terms, list):
                raise ValueError(f"{side}.{key} modifiers must retain separate terms")
            for term in terms:
                _ratio(term, f"{side}.{key}")


def _preflight_header(program, state, context):
    if not isinstance(program, dict) or program.get("category") != "skill" or program.get("status") != "compiled":
        raise ValueError("skill description is not fully compiled")
    if program.get("blockers"):
        raise ValueError("program still contains compilation blockers")
    if not isinstance(context, dict) or context.get("mode") != "isolated_skill_experiment":
        raise ValueError("only an explicitly isolated skill experiment is supported")
    _hash(context)
    if not program.get("snapshot_id") or context.get("snapshot_id") != program["snapshot_id"]:
        raise ValueError("runtime and program snapshots must match")
    if context.get("source_hash") != program.get("source_hash") or not program.get("source_hash"):
        raise ValueError("runtime must explicitly bind the compiled source hash")
    if (1005 in program.get("dependency_ids", []) or "intrinsic_swift" in program
            or "entry_trigger" in program or "swift_term" in program):
        # Swift is a trigger attached to the skill, not a second damage op.
        # Manual use still executes once; the switch component alone chooses
        # and schedules entry use. Neither path may erase its source dependency.
        trigger = {"kind": "voluntary_switch", "term_id": 1005}
        term = program.get("swift_term")
        if (program.get("intrinsic_swift") is not True
                or program.get("entry_trigger") != trigger
                or 1005 not in program.get("dependency_ids", [])
                or program.get("term_source", {}).get("content_sha256") != REVIEWED_TERMS_SHA256
                or not isinstance(term, dict) or term.get("key") != 1005
                or term.get("definition") != "通过主动更换精灵的方式入场时，使用第一个能量满足要求，并带有迅捷的技能。"):
            raise ValueError("Swift metadata requires its reviewed source term and explicit entry trigger")
    if context.get("operation_order") != "source_text_order_experiment":
        raise ValueError("description order is not verified battle timing; acknowledge experiment order explicitly")
    if context.get("unresolved_dependencies") != []:
        raise ValueError("unresolved dependency list must be explicit and empty for this isolated experiment")
    excluded = context.get("excluded_hooks")
    if not isinstance(excluded, list) or len(excluded) != len(HOOKS) or set(excluded) != HOOKS:
        raise ValueError("trait, field, mark, bloodline and event hooks must be explicitly excluded; full battle execution is unavailable")
    _state(state)
    if state["self"]["hp"] == 0:
        raise ValueError("an exhausted actor cannot execute a skill fragment")
    if "resolved_energy_cost" in context:
        cost = _integer(context["resolved_energy_cost"], "resolved_energy_cost")
        if cost > state["self"]["energy"]:
            raise ValueError("insufficient energy for caller-resolved cost")


def _preflight(program, state, context, damage_resolver):
    _preflight_header(program, state, context)
    lifecycle_enabled = lifecycle.enabled(context)
    operations = program.get("operations")
    component_sequence = (context.get("component_sequence_payment") == "reviewed_component_sequence_v1"
                          and bool(program.get("mechanism_components") or program.get("forced_switch_components") or program.get("team_target_components") or program.get("random_devotion_components") or program.get("choice_components") or program.get("duration_components") or program.get("slot_components") or program.get("attack_grant_components") or program.get("action_field_components") or program.get("cute_components")))
    if not isinstance(operations, list) or (not operations and not component_sequence):
        raise ValueError("a compiled program must have operations")
    for operation in operations:
        if not isinstance(operation, dict) or operation.get("op") not in OPS:
            raise ValueError("unsupported operation; transaction rejected without partial execution")
        op, params = operation["op"], operation.get("params")
        if not isinstance(params, dict) or params.get("target") not in ("self", "opponent"):
            raise ValueError("operation target must be explicit")
        if state[params["target"]]["hp"] == 0:
            raise ValueError("an exhausted target requires unresolved revival/faint rules")
        if op == "skill.noop":
            from lab.dynamic_skills import POOL_POLICY
            from lab.action_mechanics import GENERATORS
            if (program.get('game_id') not in GENERATORS or program.get('generator_components', {}).get('policy') != POOL_POLICY
                    or program['generator_components'].get('source_hash') != program.get('source_hash')):
                raise ValueError('No-op requires the reviewed generated-skill source')
            if context.get('resolved_energy_cost') != 0:
                raise ValueError('A selected generator must consume zero energy')
        elif op == "energy.restore":
            _integer(params.get("amount"), "energy restore amount", 1)
            if context.get("energy_policy") != "clamp_to_declared_max":
                raise ValueError("energy cap policy must be explicit; no game cap is inferred")
        elif op == "energy.transfer":
            _integer(params.get("amount"), "energy transfer amount", 1)
            if params["target"] != "opponent":
                raise ValueError("Energy transfer steals from opponent into self")
            if (context.get("energy_policy") != "clamp_to_declared_max"
                    or context.get("energy_reduction_policy") != "clamp_to_zero_experiment"):
                raise ValueError("Energy transfer requires explicit cap and floor policies")
        elif op == "energy.reduce":
            _integer(params.get("amount"), "energy reduction amount", 1)
            if context.get("energy_reduction_policy") != "clamp_to_zero_experiment":
                raise ValueError("energy reduction floor must be an explicit experiment; no game floor is inferred")
        elif op in ("hp.exchange_ratio", "hp.copy_ratio"):
            if (params.get('target') != 'self'
                    or params.get('policy') != 'simultaneous_max_hp_ratio_floor_min_one_living_experiment_v1'
                    or any(state[side]['hp'] <= 0 for side in ('self', 'opponent'))):
                raise ValueError('HP ratio exchange requires two living members and explicit simultaneous rounding policy')
        elif op == "hp.restore":
            _ratio(params.get("percent"), "HP restoration percentage")
            if params["percent"]["numerator"] <= 0:
                raise ValueError("HP restoration percentage must be positive")
            policy = context.get("hp_policy")
            if (not isinstance(policy, dict)
                    or policy.get("percentage_basis") not in ("declared_max_hp", "current_hp")
                    or policy.get("rounding") not in ("exact", "floor", "ceil", "half_up")
                    or policy.get("cap") != "clamp_to_declared_max"):
                raise ValueError("HP percentage basis, rounding and cap must be explicitly supplied; no game defaults are inferred")
        elif op == 'modifier.dispel_limited':
            from lab.modifier_ledger import limited_dispel
            limited_dispel(deepcopy(state),params['target'],mode=params['mode'],count=params['count'],
                source_skill_id=program['game_id'],source_hash=program['source_hash'],turn=context.get('turn'))
        elif op in ('modifier.invert_stats', 'modifier.double'):
            from lab.modifier_ledger import transform
            transform(deepcopy(state),params['target'],params['selection'],op.split('.')[1], source_skill_id=program['game_id'],source_hash=program['source_hash'])
        elif op in ('modifier.dispel', 'modifier.exchange'):
            from lab.modifier_ledger import apply
            apply(deepcopy(state), op, params['target'], params.get('selection'))
        elif op == 'mark.clear_reward':
            from lab import mark_runtime as marks
            marks._policy(context)
            for target in params['targets']:
                for mark in marks._slots(state[target]).values():
                    if mark and marks._data()['marks'][str(mark['id'])]['buff_raw']['id'] not in params['eligible_buff_ids']:
                        raise ValueError('Owned mark is outside the source dispel pool')
        elif op == 'modifier.grant':
            from lab.mechanism_runtime import grant_modifier,_change_cost
            component=params['component']
            if component['op'] not in {'hits.flat','skill.cost'}:raise ValueError('Unsupported generic modifier grant')
            if params.get('when_response') and type(context.get('response_success')) is not bool:raise ValueError('Response grant requires explicit classification')
            if not params.get('when_response') or context['response_success']:
                ( _change_cost if component['op']=='skill.cost' else grant_modifier)(deepcopy(state[params['target']]),component,program,context)
        elif op in ("skill.cost", "modifier.flat"):
            from lab.mechanism_runtime import POLICY
            if (program.get('mechanism_policy') != POLICY or type(context.get('turn')) is not int
                    or params.get('component') not in program.get('mechanism_components', [])):
                raise ValueError('Per-hit cost effect requires source-bound reviewed component')
        elif op == "stat.modify":
            attributes = params.get("attributes")
            if not isinstance(attributes, list) or not attributes or set(attributes) - STATS or len(set(attributes)) != len(attributes):
                raise ValueError("stat attributes must be known and distinct")
            _ratio(params.get("percent"), "stat percentage")
            _stat_term(state[params["target"]], params["percent"], context)
            if context.get("stat_policy") != "record_signed_percentage_terms":
                raise ValueError("stat terms may be recorded only; an effective-stat formula is not available")
        elif op == 'status.trigger':
            if params.get('status') not in {'poison','burn'} or params.get('policy')!='immediate_existing_status_damage_no_decay_experiment_v1':
                raise ValueError('Immediate status trigger requires explicit status and no-decay research policy')
            if not callable(damage_resolver):raise ValueError('Immediate status trigger requires a damage resolver')
            if state[params['target']]['statuses'].get(params['status'],0) and IMMUNITIES[params['status']] in state[params['target']]['types']:
                raise ValueError('Existing immune status cannot be triggered without a removal policy')
        elif op == 'status.multiply':
            if params.get('status') not in IMMUNITIES or type(params.get('factor')) is not int or params['factor'] < 1:
                raise ValueError('Invalid explicit status count multiplier')
            if params['status'] in ('freeze','leech') and not lifecycle_enabled:
                raise ValueError('Status multiplication requires lifecycle threshold handling')
        elif op == "status.add":
            status = params.get("status")
            if status not in IMMUNITIES:
                raise ValueError("unsupported status")
            if status == "freeze" and not lifecycle_enabled:
                raise ValueError("freeze requires an immediate exhaustion-threshold resolver; assigning stacks alone is incomplete")
            if status == "leech" and not lifecycle_enabled:
                raise ValueError("leech requires source binding and a verified transfer direction; integer stacks alone lose essential state")
            _integer(params.get("stacks"), "status stacks", 1)
            policy = context.get("status_policies", {}).get(status)
            if not isinstance(policy, dict) or policy.get("stacking") != "add_to_declared_count" or "cap" not in policy:
                raise ValueError("status stacking and cap must be explicitly supplied")
            if policy["cap"] is not None:
                _integer(policy["cap"], "status cap")
            if policy.get("immunity_type") != IMMUNITIES[status]:
                raise ValueError("status immunity contradicts the BWIKI term")
            if lifecycle_enabled and status in ("freeze", "leech"):
                expected = lifecycle.research_context()["status_policies"][status]
                if policy != expected:
                    raise ValueError("Freeze/leech require the source-bound cap and immunity policy")
                if status == "leech":
                    if (context.get("leech_policy") != lifecycle.LEECH_POLICY
                            or context.get("actor_side") not in ("a", "b")
                            or not isinstance(state["self"].get("member_id"), str)
                            or not state["self"]["member_id"]
                            or context.get("actor_member_id") != state["self"]["member_id"]
                            or params["target"] != "opponent"):
                        raise ValueError("Leech requires the actual opposing caster member identity and named HP policy")
            if program.get("term_source", {}).get("content_sha256") != REVIEWED_TERMS_SHA256:
                raise ValueError("status operation requires the reviewed BWIKI Terms revision; changed terms need a new review")
            if state[params["target"]]["hp"] == 0:
                raise ValueError("status application to an exhausted target is outside this fragment contract")
        elif op in ("damage", "damage.sequence", "damage.conditional"):
            if not callable(damage_resolver):
                raise ValueError("damage formula/rounding unresolved: provide an explicit experimental resolver")
            if context.get("damage_policy") != "resolver_returns_actual_integer_hp_loss":
                raise ValueError("damage resolver must return actual integer HP loss, including overkill/rounding decisions")
            if params.get("kind") not in ("physical", "magical") or not isinstance(params.get("type"), str):
                raise ValueError("invalid damage kind or type")
            _integer(params.get("power"), "damage power", 1)
            if state[params["target"]]["hp"] == 0:
                raise ValueError("damage target is exhausted")
            if op == "damage.sequence":
                _integer(params.get("hits"), "fixed hit count", 1)
                from lab.mechanism_runtime import modify_hits
                modify_hits(state["self"], params["hits"],program.get('game_id'),{**context,'trait_hit_opponent':state['opponent']})
                if program.get("term_source", {}).get("content_sha256") != REVIEWED_TERMS_SHA256:
                    raise ValueError("damage sequence requires the reviewed BWIKI Terms revision")
                if 3005 not in program.get("dependency_ids", []):
                    raise ValueError("damage sequence must retain its hit-count term dependency")
                if 'hit_effects' in params:
                    children = params['hit_effects']
                    if not isinstance(children,list) or any(e.get('op') != 'status.add' for e in children):
                        raise ValueError('Per-hit follow-ups only support explicit source status components')
                    _preflight({**deepcopy(program),'operations':deepcopy(children)},state,context,damage_resolver)
                policy = context.get("multi_hit_policy")
                if (not isinstance(policy, dict) or set(policy) != {"power_basis", "timing"}
                        or policy.get("power_basis") not in ("source_power_per_hit", "source_power_total")
                        or policy.get("timing") != "sequential_experiment"):
                    raise ValueError("multi-hit power basis and sequential experiment timing must be explicitly supplied")
            elif op == "damage.conditional":
                condition, modifier = params.get("condition"), params.get("modifier")
                if (not isinstance(condition, dict)
                        or set(condition) != {"target", "attribute", "comparison", "value", "source_timing"}
                        or condition.get("target") not in ("self", "opponent")
                        or condition.get("attribute") != "energy"
                        or condition.get("comparison") not in ("eq", "lte")
                        or condition.get("source_timing") not in ("after_use", "unspecified")):
                    raise ValueError("conditional damage requires a supported explicit energy predicate")
                _integer(condition.get("value"), "energy condition value")
                if (not isinstance(modifier, dict) or set(modifier) != {"kind", "amount"}
                        or modifier.get("kind") not in ("power_add", "damage_multiply")):
                    raise ValueError("conditional damage requires a supported power or damage modifier")
                _integer(modifier.get("amount"), "conditional modifier amount", 1)
                policy = context.get("conditional_policy")
                if policy != {"timing": "after_payment_before_damage_experiment"}:
                    raise ValueError("conditional read timing must be explicitly acknowledged as an experiment")
                if "resolved_energy_cost" not in context:
                    raise ValueError("conditional damage requires an explicit resolved_energy_cost, including zero")


def execute_effects(program, state, context, *, damage_resolver=None):
    """Apply a whole isolated program or return the original state with blockers.

    Actors use ``self``/``opponent`` keys. HP/energy and declared maxima are exact
    integers. Stat modifiers are lists of rational percentage terms, not derived
    panels. Extra state, including four ordered skill slots, is copied intact.
    Costs are not inferred from base skill energy. Optional caller-resolved cost
    is paid only after every operation/dependency is preflighted.

    A damage resolver receives copies of (params, current_state, context), and
    returns an integer actual HP loss, bounded by remaining target HP. Its output
    is labeled caller-supplied, unvalidated; no default formula is provided.
    For damage.sequence it is called separately for each source-declared hit,
    with hit_index (zero-based), hit_count and the declared power_basis added to
    params. Source power is never divided or multiplied by this runtime.
    Conditional predicates read current energy after explicit payment, only
    under the declared timing experiment. The resolver receives adjusted power
    or an explicit damage multiplier and must return the FINAL actual HP loss;
    the multiplier is never applied a second time by this runtime.
    """
    original = deepcopy(state)
    result = {"status": "blocked", "scope": "isolated_skill_fragment", "state": original,
              "events": [], "blockers": [], "snapshot_id": program.get("snapshot_id") if isinstance(program, dict) else None,
              "program_hash": None, "source_hash": program.get("source_hash") if isinstance(program, dict) else None,
              "implementation_unvalidated": True, "training_eligible": False,
              "calibrated": False, "full_turn_executed": False}
    try:
        result["program_hash"] = _hash(program)
        _preflight(program, state, context, damage_resolver)
        current, events = deepcopy(state), []
        if "resolved_energy_cost" in context:
            cost = context["resolved_energy_cost"]
            current["self"]["energy"] -= cost
            events.append({"op": "energy.pay", "target": "self", "amount": cost, "source": "caller_resolved_cost"})
        for operation_index, operation in enumerate(program["operations"]):
            if operation_index and any(current[side]["hp"] == 0 for side in ("self", "opponent")):
                if context.get("faint_policy") == "stop_remaining_skill_on_exhaustion_experiment":
                    events.append({"op": "research.skill_stopped", "operation_index": operation_index,
                                   "reason": "exhaustion", "policy": context["faint_policy"]})
                    break
                raise ValueError("Exhaustion before a follow-up effect requires unresolved faint/trigger timing; whole skill rolled back")
            op, params = operation["op"], operation["params"]
            actor = current[params["target"]]
            event = {"op": op, "target": params["target"], "params": deepcopy(params)}
            follow_events = []
            if op == "energy.restore":
                before = actor["energy"]
                actor["energy"] = _energy_cap(actor, before + _energy_recovery(actor, params["amount"], context))
                event.update(before=before, after=actor["energy"], policy="caller_declared_cap")
                from lab.trait_runtime import after_energy_gain
                follow_events.extend({**e,'target':params['target']} for e in after_energy_gain(actor,actor['energy']-before,context))
            elif op == "energy.transfer":
                before = actor["energy"]
                receiver = current["self"]
                received_before = receiver["energy"]
                removed = min(before, params["amount"])
                actor["energy"] -= removed
                receiver["energy"] = _energy_cap(receiver, received_before + _energy_recovery(receiver, removed, context))
                event.update(before=before, after=actor["energy"], actual_amount=removed,
                             received=receiver["energy"] - received_before,
                             receiver_before=received_before, receiver_after=receiver["energy"],
                             policy="remove_actual_then_restore_with_cap_experiment")
                from lab.trait_runtime import after_energy_gain
                follow_events.extend({**e,'target':'self'} for e in after_energy_gain(receiver,receiver['energy']-received_before,context))
            elif op == "energy.reduce":
                before = actor["energy"]
                actor["energy"] = max(0, before - params["amount"])
                event.update(before=before, after=actor["energy"],
                             requested_amount=params["amount"], actual_amount=before - actor["energy"],
                             policy="clamp_to_zero_experiment")
            elif op in ("hp.exchange_ratio", "hp.copy_ratio"):
                basis = {side: {'hp': current[side]['hp'], 'max_hp': current[side]['max_hp']}
                         for side in ('self', 'opponent')}
                updates = {side: max(1, basis[side]['max_hp'] * basis[other]['hp'] // basis[other]['max_hp'])
                           for side, other in ((('self', 'opponent'),) if op == 'hp.copy_ratio' else (('self', 'opponent'), ('opponent', 'self')))}
                for side, value in updates.items():
                    current[side]['hp'] = value
                event.update(basis=basis, after=updates, policy=params['policy'])
            elif op == "hp.restore":
                policy = context["hp_policy"]
                before = actor["hp"]
                basis = actor["max_hp"] if policy["percentage_basis"] == "declared_max_hp" else before
                amount = basis * Fraction(params["percent"]["numerator"], params["percent"]["denominator"])
                numerator, denominator = amount.numerator, amount.denominator
                if policy["rounding"] == "exact":
                    if denominator != 1:
                        raise ValueError("Non-integral HP restoration requires an explicit experimental rounding rule")
                    requested = numerator
                elif policy["rounding"] == "floor":
                    requested = numerator // denominator
                elif policy["rounding"] == "ceil":
                    requested = (numerator + denominator - 1) // denominator
                else:
                    requested = (2 * numerator + denominator) // (2 * denominator)
                actor["hp"] = min(actor["max_hp"], before + requested)
                restored = actor["hp"] - before
                from lab.trait_runtime import after_hp_restore
                follow_events.extend(after_hp_restore(current, params["target"], requested, restored, context))
                actor = current[params["target"]]
                event.update(before=before, after=actor["hp"], basis_value=basis,
                             requested_unrounded={"numerator": numerator, "denominator": denominator},
                             requested=requested, restored=restored, overflow=requested-restored,
                             policy=deepcopy(policy), source="caller_supplied_unvalidated_hp_policy")
            elif op == 'modifier.dispel_limited':
                from lab.modifier_ledger import limited_dispel
                event.update(limited_dispel(current,params['target'],mode=params['mode'],count=params['count'],
                    source_skill_id=program['game_id'],source_hash=program['source_hash'],turn=context.get('turn')))
            elif op in ('modifier.invert_stats', 'modifier.double'):
                from lab.modifier_ledger import transform
                event.update(transform(current,params['target'],params['selection'],op.split('.')[1], source_skill_id=program['game_id'],source_hash=program['source_hash']))
            elif op in ('modifier.dispel', 'modifier.exchange'):
                from lab.modifier_ledger import apply
                event.update(apply(current, op, params['target'], params['selection']))
            elif op == 'modifier.flat':
                from lab.mechanism_runtime import POLICY
                item = {'op':params['component']['op'],'amount':params['component']['amount'],
                    'source_skill_id':program['game_id'],'source_hash':program['source_hash'],'policy':POLICY}
                actor.setdefault('mechanism_flat_modifiers',[]).append(item)
                event.update(item)
            elif op == "skill.cost":
                from lab.mechanism_runtime import _change_cost
                event.update(_change_cost(actor, params['component'], program, context))
            elif op == "stat.modify":
                term = _stat_term(actor, params["percent"], context)
                for attribute in params["attributes"]:
                    applied = deepcopy(term)
                    buff_id=params.get('buff_ids',{}).get(attribute)
                    if buff_id is not None:
                        from lab.modifier_ledger import enhance_buff_amount
                        value=enhance_buff_amount(actor,buff_id,attribute,Fraction(term['numerator'],term['denominator']))
                        applied={'numerator':value.numerator,'denominator':value.denominator}
                    elif program.get('modifier_source_kind','skill') == 'skill' and program.get('static_fields',{}).get('kind'):
                        from lab.modifier_ledger import enhance_amount
                        value = enhance_amount(actor,program['game_id'],program['source_hash'],attribute,
                                               Fraction(term['numerator'],term['denominator']))
                        if value != Fraction(term['numerator'],term['denominator']):
                            applied = {'numerator':value.numerator,'denominator':value.denominator}
                            event.setdefault('trait_applied_terms',{})[attribute] = deepcopy(applied)
                    actor["stat_modifiers"].setdefault(attribute, []).append(applied)
                    from lab.modifier_ledger import register_stat
                    register_stat(actor, attribute, source_kind=program.get('modifier_source_kind',
                        'skill' if program.get('static_fields', {}).get('kind') in ('physical','magical','status','defense') else 'other'),
                        source_id=program.get('game_id'), source_hash=program['source_hash'],buff_id=buff_id)
                if term != params["percent"]:
                    event.update(original_percent=deepcopy(params["percent"]), applied_percent=term,
                                 layer_policy="ten_percent_stat_layers_with_sprout_experiment")
                event["effective_panel_recomputed"] = False
            elif op == 'mark.clear_reward':
                from lab import mark_runtime as marks
                removed={target:deepcopy(marks._slots(current[target])) for target in params['targets']}
                total=sum(marks.layer_count(current[target]) for target in params['targets'])
                for target in params['targets']:current[target]['field_marks']=deepcopy(marks.EMPTY)
                event.update(removed=removed,removed_layers=total,source_skill_id=program['game_id'],source_hash=program['source_hash'])
                if total and params.get('reward'):
                    reward=params['reward']
                    primitive={**deepcopy(program),'operations':[{'op':'stat.modify','params':{'target':'self',
                        'attributes':[reward['attribute']],'percent':{'numerator':total*reward['percent_per_layer'],'denominator':100}}}]}
                    nested=execute_effects(primitive,current,{**context,'resolved_energy_cost':0,'component_sequence_paid_cost':context.get('resolved_energy_cost',0)})
                    if nested['status']!='applied':raise ValueError('Mark reward failed: '+'; '.join(nested['blockers']))
                    current=nested['state'];actor=current[params['target']]
                    follow_events.extend(e for e in nested['events'] if e['op']!='energy.pay')
            elif op == 'modifier.grant':
                from lab.mechanism_runtime import grant_modifier,_change_cost
                component=params['component']
                if not params.get('when_response') or context['response_success']:
                    event.update((_change_cost if component['op']=='skill.cost' else grant_modifier)(actor,component,program,context))
                else:event.update(skipped=True,reason='response_not_matched')
            elif op == 'status.trigger':
                from lab.status_runtime import STATUS_RULES
                status=params['status'];before=actor['hp'];stacks=actor['statuses'].get(status,0)
                spec=STATUS_RULES[status]
                descriptor={**deepcopy(params),'op':'status.trigger','stacks':stacks,
                    'rate':deepcopy(spec['rate']),'damage_type':spec['damage_type']}
                loss=damage_resolver(deepcopy(descriptor),deepcopy(current),deepcopy(context)) if stacks else 0
                _integer(loss,'actual immediate status HP loss')
                if loss>before:raise ValueError('Immediate status damage exceeds remaining HP')
                actor['hp']-=loss
                event.update(descriptor,hp_before=before,hp_after=actor['hp'],actual_hp_loss=loss,
                    stacks_before=stacks,stacks_after=stacks)
                from lab.trait_runtime import after_periodic_loss_relative
                follow_events.extend(after_periodic_loss_relative(current,params['target'],status,loss,context))
            elif op == 'status.multiply':
                status = params['status']
                before = actor['statuses'].get(status,0)
                cap = context['status_policies'][status]['cap']
                after = before * params['factor']
                if cap is not None:after=min(cap,after)
                actor['statuses'][status]=after
                if status in actor.get('status_modifier_sources',{}):
                    actor['status_modifier_sources'][status]['count']=after
                event.update(before=before,after=after,policy='multiply_existing_layers_preserve_source_and_lifetime')
            elif op == "status.add":
                status = params["status"]
                policy = context["status_policies"][status]
                before = actor["statuses"].get(status, 0)
                from lab.trait_switch_components import status_immune
                immune = IMMUNITIES[status] in actor["types"] or status_immune(actor, status)
                from lab.trait_runtime import status_extra_layers
                requested = status_extra_layers(current["self"],status,params["stacks"])
                after = before if immune else before + requested
                if not immune and policy["cap"] is not None:
                    if before > policy["cap"]:
                        raise ValueError("existing status count exceeds the caller-declared cap")
                    after = min(after, policy["cap"])
                if lifecycle.enabled(context) and status in ("freeze", "leech") and not immune:
                    lifecycle.apply_layers(actor, status, requested, cap=policy["cap"],
                        departure="clear" if status == "leech" else "retain", source=program["term_source"])
                    if status == "leech":
                        actor.setdefault("status_sources", {})["leech"] = {
                            "side": context["actor_side"], "member_id": current["self"]["member_id"],
                            "policy": lifecycle.LEECH_POLICY, "refresh_policy": lifecycle.SOURCE_REFRESH_POLICY,
                            "source_hash": program["source_hash"]}
                else:
                    actor["statuses"][status] = after
                from lab.modifier_ledger import register_status
                register_status(actor, status, source_kind=program.get('modifier_source_kind',
                    'skill' if program.get('static_fields', {}).get('kind') in ('physical','magical','status','defense') else 'other'),
                    source_id=program.get('game_id'), source_hash=program['source_hash'], before=before)
                event.update(before=before, after=after, immune=immune,requested_stacks=requested, term_source=deepcopy(program["term_source"]),
                             end_of_turn_resolved=False, status_consequences_resolved=False,
                             excluded_consequences="Isolated stack assignment only; damage, decay and freeze-exhaustion triggers are not executed.",
                             stacking_policy="caller_declared")
                from lab.trait_runtime import after_status_gain
                follow_events.extend(after_status_gain(current,params["target"],status,after-before,context))
                if lifecycle.enabled(context) and status in ("freeze", "leech"):
                    event.update(status_consequences_resolved=status == "freeze", lifecycle_policy=lifecycle.POLICY,
                                 excluded_consequences="End-of-turn leech uses the separately scheduled named research policy.")
                    if status == "leech" and not immune:
                        event["source_binding"] = deepcopy(actor["status_sources"]["leech"])
                        event["transfer_source"] = lifecycle.leech_source()
            elif op == "damage.sequence":
                from lab.mechanism_runtime import modify_hits, HIT_POLICY
                source_hits = params["hits"]
                params = deepcopy(params)
                params["hits"] = modify_hits(current["self"], source_hits,program.get('game_id'),{**context,'trait_hit_opponent':current['opponent']})
                if any(item['op'].startswith('hits.') for item in current['self'].get('mechanism_flat_modifiers', [])):
                    events.append({'op': 'damage.sequence.hits', 'target': 'self',
                        'source_hits': source_hits, 'effective_hits': params['hits'], 'policy': HIT_POLICY})
                policy = context["multi_hit_policy"]
                for hit_index in range(params["hits"]):
                    if hit_index and any(current[side]["hp"] == 0 for side in ("self", "opponent")):
                        if context.get("faint_policy") == "stop_remaining_skill_on_exhaustion_experiment":
                            events.append({"op": "research.hits_stopped", "operation_index": operation_index,
                                           "hit_index": hit_index, "reason": "exhaustion",
                                           "policy": context["faint_policy"]})
                            break
                        raise ValueError("Exhaustion before another hit requires unresolved faint/trigger timing; whole skill rolled back")
                    hit_params = deepcopy(params)
                    hit_params.update(hit_index=hit_index, hit_count=params["hits"],
                        base_hit_count=source_hits, effective_hit_count=params["hits"],
                        hit_modifier_policy=HIT_POLICY, power_basis=policy["power_basis"])
                    if context.get('fixed_hit_count') is not None:
                        hit_params.update(fixed_hit_policy=context['fixed_hit_policy'],fixed_hit_sources=deepcopy(context['fixed_hit_sources']))
                    from lab.defense_runtime import resolve_received_damage, after_received_damage
                    damage, mitigation = resolve_received_damage(damage_resolver,hit_params,current,context)
                    _integer(damage, "resolved actual damage")
                    if damage > actor["hp"]:
                        raise ValueError("resolver damage exceeds remaining HP; overkill policy is not inferred")
                    before = actor["hp"]
                    actor["hp"] -= damage
                    after_damage = actor["hp"]
                    received_events=after_received_damage(actor,damage,mitigation,context.get("turn"))
                    events.append({"op": "damage", "source_op": "damage.sequence", "target": params["target"],
                                   "params": hit_params, "before": before, "after": after_damage, "damage": damage,
                                   "sequence_operation_index": operation_index, "hit_index": hit_index,
                                   "hit_count": params["hits"], "base_hit_count": source_hits,
                                   "effective_hit_count": params["hits"], "hit_modifier_policy": HIT_POLICY,
                                   "power_basis": policy["power_basis"],
                                   "source": "caller_supplied_unvalidated_resolver"})
                    events.extend({**e,"target":params["target"]} for e in received_events)
                    from lab.defense_runtime import after_attack_retaliation
                    events.extend(after_attack_retaliation(damage_resolver, hit_params, current, context, damage,
                        token=f"{context.get('turn')}:{context.get('actor_member_id')}:{actor.get('member_id')}:retaliation:{actor.get('direct_damage_packet_counter')}"))
                    if lifecycle.enabled(context):
                        events.extend(_freeze_events(current))
                    if params.get('hit_effects') and not (context.get('faint_policy') == 'stop_remaining_skill_on_exhaustion_experiment'
                            and any(current[name]['hp'] == 0 for name in ('self','opponent'))):
                        nested_context = {**deepcopy(context),'resolved_energy_cost':0,
                                          'component_sequence_paid_cost':context.get('resolved_energy_cost',0)}
                        nested = execute_effects({**deepcopy(program),'operations':deepcopy(params['hit_effects'])},
                            current,nested_context,damage_resolver=damage_resolver)
                        if nested['status'] != 'applied':
                            raise ValueError('Per-hit follow-up failed: '+ '; '.join(nested['blockers']))
                        current = nested['state']
                        actor = current[params['target']]
                        events.extend({**e,'sequence_hit_index':hit_index} for e in nested['events'] if e['op'] != 'energy.pay')
                continue  # Individual hit events replace an aggregate sequence event.
            elif op == "damage.conditional":
                condition, modifier = params["condition"], params["modifier"]
                observed = current[condition["target"]]["energy"]
                matched = (observed == condition["value"] if condition["comparison"] == "eq"
                           else observed <= condition["value"])
                power = params["power"] + (modifier["amount"] if matched and modifier["kind"] == "power_add" else 0)
                multiplier = {"numerator": modifier["amount"] if matched and modifier["kind"] == "damage_multiply" else 1,
                              "denominator": 1}
                resolved = deepcopy(params)
                resolved.update(base_power=params["power"], power=power, condition_observed=observed,
                                condition_matched=matched, damage_multiplier=deepcopy(multiplier))
                from lab.defense_runtime import resolve_received_damage, after_received_damage
                damage, mitigation = resolve_received_damage(damage_resolver,resolved,current,context)
                _integer(damage, "resolved actual conditional damage")
                if damage > actor["hp"]:
                    raise ValueError("resolver damage exceeds remaining HP; overkill policy is not inferred")
                before = actor["hp"]
                actor["hp"] -= damage
                after_damage = actor["hp"]
                follow_events.extend({**e,"target":params["target"]} for e in after_received_damage(actor,damage,mitigation,context.get("turn")))
                from lab.defense_runtime import after_attack_retaliation
                follow_events.extend(after_attack_retaliation(damage_resolver, resolved, current, context, damage,
                    token=f"{context.get('turn')}:{context.get('actor_member_id')}:{actor.get('member_id')}:retaliation:{actor.get('direct_damage_packet_counter')}"))
                event.update(op="damage", source_op="damage.conditional", before=before, after=after_damage,
                             damage=damage, base_power=params["power"], resolved_power=power,
                             condition=deepcopy(condition), condition_observed=observed, condition_matched=matched,
                             damage_multiplier=deepcopy(multiplier), resolved_params=resolved,
                             conditional_policy=deepcopy(context["conditional_policy"]),
                             source="caller_supplied_unvalidated_resolver")
            elif op == "damage":
                from lab.defense_runtime import resolve_received_damage, after_received_damage
                damage, mitigation = resolve_received_damage(damage_resolver,params,current,context)
                _integer(damage, "resolved actual damage")
                if damage > actor["hp"]:
                    raise ValueError("resolver damage exceeds remaining HP; overkill policy is not inferred")
                before = actor["hp"]
                actor["hp"] -= damage
                after_damage = actor["hp"]
                follow_events.extend({**e,"target":params["target"]} for e in after_received_damage(actor,damage,mitigation,context.get("turn")))
                from lab.defense_runtime import after_attack_retaliation
                follow_events.extend(after_attack_retaliation(damage_resolver, params, current, context, damage,
                    token=f"{context.get('turn')}:{context.get('actor_member_id')}:{actor.get('member_id')}:retaliation:{actor.get('direct_damage_packet_counter')}"))
                event.update(before=before, after=after_damage, damage=damage, source="caller_supplied_unvalidated_resolver")
            events.append(event)
            events.extend(follow_events)
            if lifecycle.enabled(context):
                events.extend(_freeze_events(current))
        if ('resolved_energy_cost' in context and 'component_sequence_paid_cost' not in context
                and program.get('modifier_source_kind', 'skill') == 'skill'
                and type(program.get('game_id')) is int
                and program.get('static_fields', {}).get('kind') in ('physical', 'magical', 'status', 'defense')):
            from lab.mechanism_runtime import consume_skill_tokens, after_skill
            current, attached = after_skill(current,program,context,events)
            events.extend(attached)
            events.extend(consume_skill_tokens(current['self'], attacked=any(e.get('op') == 'damage' for e in events), turn=context.get('turn')))
        for event in events:
            event.update(snapshot_id=result["snapshot_id"], program_hash=result["program_hash"],
                         implementation_unvalidated=True, training_eligible=False)
        result.update(status="applied", state=current, events=events,
                      assumptions=deepcopy(context), energy_cost_applied="resolved_energy_cost" in context)
    except Exception as exc:
        # Resolver callbacks form an explicit extension boundary. Any ordinary
        # exception rolls back the copy, rather than exposing a partial commit.
        result["blockers"] = [str(exc)]
    return result
