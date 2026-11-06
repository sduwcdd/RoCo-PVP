"""Transactional, source-bound status experiments, not a full turn end.

The source gives a percentage and elemental damage type, but does not establish
the current-version HP basis, layer multiplier, cap, rounding or all modifiers.
Only a caller's explicit resolver may produce the final actual HP loss. Schedule
and burn-decay rounding are experimental inputs, never default game rules.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction

from lab.effect_runtime import HOOKS, REVIEWED_TERMS_SHA256, _state
from lab.prepared_rules import PreparedRules, prepare_rules
from lab.ruleset import canonical_hash
from lab.turn_plan import SIDES, _validate_state
from lab import status_lifecycle as lifecycle


STATUS_RULES = {
    "poison": {"term_id": 1001, "name": "中毒", "rate": {"numerator": 3, "denominator": 100},
               "damage_type": "毒系", "definition": "回合结束时，造成3%生命的毒系伤害。（毒系精灵免疫此效果）"},
    "burn": {"term_id": 1002, "name": "灼烧", "rate": {"numerator": 2, "denominator": 100},
             "damage_type": "火系", "definition": "回合结束时，造成2%生命的火系伤害，并衰减一半层数。（火系精灵免疫此效果）"},
}
UNRESOLVED = [
    "Damage basis, per-layer arithmetic, cap, rounding and final modifiers require an external uncalibrated resolver.",
    "The supplied status schedule and damage-then-decay order are experimental, not verified game timing.",
    "Existing status on an immune type and full replacement/associated trigger semantics remain unresolved.",
    "Only source-bound periodic-loss healing traits are processed here; bench effects, field, marks, bloodlines and other event hooks require their owning modules.",
    "No resource regeneration, turn advancement or winner calculation is performed.",
]


def _active(state, side):
    team = state["teams"][side]
    return team["members"][team["active_slot"]]


def _remaining_burn(stacks, rounding):
    value = Fraction(stacks, 2)
    if rounding == "exact":
        if value.denominator != 1:
            raise ValueError("Half of burn layers is fractional; exact decay cannot guess integer rounding")
        return value.numerator
    if rounding == "floor":
        return value.numerator // value.denominator
    return -(-value.numerator // value.denominator)


def execute_status_phase(catalog, state, context, *, damage_resolver=None):
    """Execute explicitly scheduled active poison/burn ticks atomically.

    State is the joint-action state; active members additionally require the
    effect runtime's max resources, statuses and stat_modifiers. Types are read
    from the exact BWIKI form; conflicting supplied types reject the transaction.

    Context requires mode=isolated_status_phase_experiment, snapshot_id,
    catalog_content_hash, all excluded_hooks, unresolved_dependencies=[],
    operation_order=damage_then_decay_experiment, schedule=[{side,status}, ...]
    covering every positive active poison/burn once, and status_policy containing
    immunity=reject_existing_immune_status and burn_decay_rounding=exact|floor|ceil.

    The resolver receives detached (descriptor, joint_state, context) copies and
    returns the final integer HP loss. Rates and layers remain separate metadata;
    this function does not multiply them, apply elemental factors or infer an HP
    basis. Burn decay happens after its damage under the explicit experiment
    order. Any missing dependency, callback failure or HP reaching zero restores
    the complete input state and discards all events. Turn stays unchanged.
    Optional faint_policy=research_status_exhaustion_skip_remaining_ticks_experiment
    allows research v2 to tick only living actives, commit status exhaustion and
    skip later ticks on that exhausted actor. Strict default behavior is unchanged.
    The optional status_lifecycle_policy bridge additionally permits source-bound
    leech ticks and shared freeze thresholds. Its named leech_policy declares HP
    basis, per-layer multiplication, floor, source-member healing and overkill;
    the installed source establishes 2% damage/transfer direction, not arithmetic.
    """
    result = {
        "status": "blocked", "scope": "isolated_status_phase_experiment",
        "state": deepcopy(state), "events": [], "blockers": [],
        "snapshot_id": catalog.snapshot_id if isinstance(catalog, PreparedRules)
        else catalog.get("snapshot_id") if isinstance(catalog, dict) else None,
        "state_hash": None, "context_hash": None, "catalog_hash": None,
        "input_state_mutated": False, "full_turn_executed": False,
        "end_of_turn_executed": False, "status_phase_executed": False,
        "battle_executable": False, "calibrated": False, "real_game_verified": False,
        "training_eligible": False, "implementation_unvalidated": True,
        "unresolved": deepcopy(UNRESOLVED),
    }
    try:
        result.update(state_hash=canonical_hash(state), context_hash=canonical_hash(context))
        context = deepcopy(context)
        lifecycle_enabled = lifecycle.enabled(context)
        if lifecycle_enabled:
            result["unresolved"].extend([
                "Leech max-HP basis, per-layer multiplier, floor, latest-source ownership and healing a benched caster are named research choices, not verified server semantics.",
                "Generic lifecycle fields are explicit declarations; arbitrary BUFF cover/group/trigger enums are not automatically executed.",
            ])
        allow_faint = context.get("faint_policy") == "research_status_exhaustion_skip_remaining_ticks_experiment"
        if "faint_policy" in context and not allow_faint:
            raise ValueError("Unknown status faint policy")
        prepared = prepare_rules(catalog)
        rules, phases, _ = prepared._components()
        result["catalog_hash"] = rules.catalog_content_hash
        if not isinstance(context, dict) or context.get("mode") != "isolated_status_phase_experiment":
            raise ValueError("An isolated status-phase experiment must be explicitly requested")
        if context.get("snapshot_id") != rules.snapshot_id or context.get("catalog_content_hash") != rules.catalog_content_hash:
            raise ValueError("Status experiment must bind both snapshot and catalog content hash")
        if context.get("operation_order") != "damage_then_decay_experiment":
            raise ValueError("Damage-then-decay is experimental and must be explicitly requested")
        excluded = context.get("excluded_hooks")
        if (not isinstance(excluded, list) or len(excluded) != len(HOOKS)
                or any(not isinstance(x, str) for x in excluded) or set(excluded) != HOOKS):
            raise ValueError("Every trait, field, mark, bloodline and event hook must be explicitly excluded")
        if context.get("unresolved_dependencies") != []:
            raise ValueError("Isolated dependency list must be explicit and empty")
        policy = context.get("status_policy")
        if (not isinstance(policy, dict) or set(policy) != {"immunity", "burn_decay_rounding"}
                or policy.get("immunity") != "reject_existing_immune_status"
                or policy.get("burn_decay_rounding") not in ("exact", "floor", "ceil")):
            raise ValueError("Explicit existing-immunity rejection and burn-decay rounding policies are required")

        sources = {}
        for status, spec in STATUS_RULES.items():
            term = rules.term(spec["term_id"])
            if (term.get("zh") != spec["name"] or term.get("definition") != spec["definition"]
                    or term["evidence"].get("content_sha256") != REVIEWED_TERMS_SHA256):
                raise ValueError("Status source differs from the reviewed BWIKI term; re-review is required")
            sources[status] = term

        current = deepcopy(state)
        _validate_state(rules, phases, current)
        active_types, relative = {}, {}
        for side, name in (("a", "self"), ("b", "opponent")):
            actor = _active(current, side)
            types = rules.form(actor["form_id"])["types"]
            if "types" in actor and actor["types"] != types:
                raise ValueError("Active actor types conflict with the exact BWIKI form; transformation rules are unresolved")
            active_types[side] = deepcopy(types)
            relative[name] = {**deepcopy(actor), "types": deepcopy(types)}
        _state(relative)

        expected = set()
        remaining_burn = {}
        initial_events = []
        for side in SIDES:
            actor = _active(current, side)
            if actor["hp"] == 0:
                if allow_faint:
                    continue
                raise ValueError("An exhausted active member requires unresolved replacement and trigger rules")
            if not lifecycle_enabled and any(actor["statuses"].get(s, 0) > 0 for s in ("freeze", "leech")):
                raise ValueError("Existing freeze or leech requires unresolved threshold/source-binding rules; cannot skip it")
            if lifecycle_enabled:
                initial_events.extend(lifecycle.check_freeze(actor, side))
                if actor["hp"] == 0:
                    if not allow_faint:
                        raise ValueError("Freeze exhaustion requires the explicit research faint policy")
                    continue
                if actor["statuses"].get("leech", 0):
                    if context.get("leech_policy") != lifecycle.LEECH_POLICY:
                        raise ValueError("Leech requires its explicit named HP-basis and transfer policy")
                    lifecycle.leech_source()
                    lifecycle.validate_leech_binding(actor, side, current)
                    if "草系" in active_types[side]:
                        raise ValueError("Existing leech on an immune grass type requires an explicit removal policy")
                    expected.add((side, "leech"))
            for status, spec in STATUS_RULES.items():
                stacks = actor["statuses"].get(status, 0)
                if stacks:
                    if spec["damage_type"] in active_types[side]:
                        raise ValueError("Existing status on an immune type has unresolved removal/tick/decay semantics")
                    expected.add((side, status))
                    if status == "burn":
                        remaining_burn[side] = _remaining_burn(stacks, policy["burn_decay_rounding"])

        schedule = context.get("schedule")
        if not isinstance(schedule, list):
            raise ValueError("Every active poison/burn tick needs an explicit experimental schedule")
        actual = []
        for item in schedule:
            if (not isinstance(item, dict) or set(item) != {"side", "status"}
                    or item.get("side") not in SIDES
                    or item.get("status") not in (set(STATUS_RULES) | ({"leech"} if lifecycle_enabled else set()))):
                raise ValueError("Schedule items must contain exactly a known side and poison/burn status")
            actual.append((item["side"], item["status"]))
        if len(actual) != len(set(actual)) or set(actual) != expected:
            raise ValueError("Schedule must cover all positive active poison/burn statuses exactly once")
        if any(status in STATUS_RULES for _, status in expected) and not callable(damage_resolver):
            raise ValueError("No calibrated/default status damage formula is available; supply an explicit experiment resolver")

        # All dependencies, decay fractions and both actors validate before any
        # callback. Nothing from callbacks is reused except a validated integer.
        events = initial_events
        for index, (side, status) in enumerate(actual):
            actor = _active(current, side)
            if actor["hp"] == 0 and allow_faint:
                events.append({"op": "research.status_skipped", "side": side, "status": status,
                               "reason": "exhausted_active", "policy": context["faint_policy"]})
                continue
            if status == "leech":
                event = lifecycle.tick_leech(current, side, policy=context.get("leech_policy"))
                if actor["hp"] == 0 and not allow_faint:
                    raise ValueError("Leech exhaustion requires the explicit research faint policy")
                event.update(snapshot_id=rules.snapshot_id, catalog_hash=rules.catalog_content_hash)
                events.append(event)
                events.extend(event.get("trait_protection_events", []))
                for affected_side in SIDES:
                    freeze_events = lifecycle.check_freeze(_active(current, affected_side), affected_side)
                    if freeze_events and not allow_faint:
                        raise ValueError("Status-triggered freeze exhaustion requires the explicit research faint policy")
                    events.extend(freeze_events)
                continue
            stacks, before = actor["statuses"][status], actor["hp"]
            spec = STATUS_RULES[status]
            descriptor = {"status": status, "stacks": stacks, "rate": deepcopy(spec["rate"]),
                          "damage_type": spec["damage_type"], "target_side": side,
                          "target_member_id": actor["member_id"], "target_types": deepcopy(active_types[side]),
                          "schedule_index": index, "source": deepcopy(sources[status]),
                          "rate_and_stacks_are_separate": True,
                          "operation_order": context["operation_order"]}
            loss = damage_resolver(deepcopy(descriptor), deepcopy(current), deepcopy(context))
            if type(loss) is not int or not 0 <= loss <= before:
                raise ValueError("Status resolver must return the final actual integer HP loss within remaining HP")
            from lab.defense_runtime import prevent_lethal
            protection = prevent_lethal(actor,loss,current["turn"])
            loss = protection["damage"]
            if protection["event"] is not None:
                events.append({**protection["event"],"target_side":side})
            from lab.trait_runtime import before_hp_loss
            trait_protection = before_hp_loss(prepared, current, side, actor["member_id"], loss,
                token=f"status:{current['turn']}:{side}:{status}:{index}", context=context)
            loss = trait_protection["damage"]
            events.extend(trait_protection["events"])
            if loss == before and not allow_faint:
                raise ValueError("Status exhaustion needs unresolved faint/replacement/trigger timing; whole phase rolled back")
            actor["hp"] -= loss
            event = {"op": "status.tick", **descriptor, "hp_before": before, "hp_after": actor["hp"],
                     "actual_hp_loss": loss, "stacks_before": stacks, "stacks_after": stacks,
                     "snapshot_id": rules.snapshot_id, "catalog_hash": rules.catalog_content_hash,
                     "real_game_verified": False, "calibrated": False}
            if status == "burn":
                half = Fraction(stacks, 2)
                from lab.trait_runtime import status_decay_remaining
                remaining, decay_events = status_decay_remaining(current,status,stacks,remaining_burn[side])
                actor["statuses"][status] = remaining
                if status in actor.get("status_modifier_sources", {}):
                    actor["status_modifier_sources"][status]["count"] = remaining
                event.update(stacks_after=remaining, trait_decay_replacements=decay_events,
                             decay_remaining_unrounded={"numerator": half.numerator, "denominator": half.denominator},
                             decay_rounding=policy["burn_decay_rounding"])
            events.append(event)
            if status == "burn":
                from lab.trait_runtime import apply_decay_conversion
                events.extend(apply_decay_conversion(prepared,current,side,decay_events))
            from lab.trait_runtime import after_periodic_loss
            events.extend(after_periodic_loss(current,side,status,loss,context))
            if lifecycle_enabled:
                freeze_events = lifecycle.check_freeze(actor, side)
                if freeze_events and not allow_faint:
                    raise ValueError("Status-triggered freeze exhaustion requires the explicit research faint policy")
                events.extend(freeze_events)
        if lifecycle_enabled:
            for side in SIDES:
                events.extend(lifecycle.advance_lifecycles(_active(current, side), side, decayed_statuses=("burn",)))
        result.update(status="applied", state=current, events=events,
                      schedule=deepcopy(schedule), final_state_hash=canonical_hash(current),
                      assumptions=deepcopy(context), status_phase_executed=True)
    except Exception as exc:
        result["blockers"] = [str(exc)]
    return result
