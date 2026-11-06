"""Common skill dispatch for manual actions and selected entry skills.

Scheduling and conditional evaluation are explicit component experiments, not
assertions about game timing. State transactions cannot undo external callbacks.
"""
from copy import deepcopy

from lab.effect_runtime import execute_effects, _preflight_header, _preflight
from lab.event_scheduler import dispatch_events
from lab.rule_expressions import evaluate_condition, evaluate_expression


def _dispatch(program, state, context, handler):
    source = {"rule_id": f"skill:{program.get('game_id')}", "component_id": "skill.use",
              "snapshot_id": program.get("snapshot_id")}
    result = dispatch_events(state, [{"name": "skill.use", "payload": {
        "origin": context.get("entry_origin", "manual"),
        "source_hash": program.get("source_hash")}, "source": source}],
        [{"id": "skill.execute", "event": "skill.use", "handler": "skill.execute",
          "order": None, "max_executions": 1, "source": source}],
        {"skill.execute": handler}, policy={"mode": "explicit_fifo_experiment", "max_events": 1,
            "max_depth": 1, "max_handler_calls": 1})
    if result["status"] == "applied":
        fragment = result["results"]["skill.execute"][0]
    else:
        fragment = {"status": "blocked", "state": deepcopy(state), "events": [],
                    "blockers": result["blockers"], "training_eligible": False,
                    "full_turn_executed": False, "calibrated": False}
    fragment["dispatch_trace"] = result["trace"]
    fragment["dispatch_trace_is_diagnostic"] = True
    return fragment


def execute_skill(program, state, context, *, damage_resolver=None):
    """One shared entry point; no ID/name or Swift-specific effect branches."""
    program, context = deepcopy(program), deepcopy(context)
    if isinstance(state, dict) and type(state.get("self", {}).get("energy")) is int:
        context["energy_before_cast"] = state["self"]["energy"]
    if isinstance(program, dict) and "native_rule" in program:
        try:
            return execute_rule(_native_rule(program), state, context, damage_resolver=damage_resolver)
        except ValueError as exc:
            return {"status": "blocked", "state": deepcopy(state), "events": [], "blockers": [str(exc)],
                    "training_eligible": False, "full_turn_executed": False, "calibrated": False}
    def handler(current, event):
        result = execute_effects(program, current, context, damage_resolver=damage_resolver)
        if result["status"] != "applied":
            raise ValueError("Skill effects blocked: " + "; ".join(result["blockers"]))
        return {"state": result["state"], "events": [], "result": result}
    if not isinstance(program, dict) or not isinstance(context, dict):
        return {"status": "blocked", "state": deepcopy(state), "events": [],
                "blockers": ["Skill program and context must be objects"], "training_eligible": False}
    return _dispatch(program, state, deepcopy(context), handler)


def _native_rule(program):
    """Never attribute an inner execution to a conflicting outer identity."""
    from lab.rule_config import validate_rule
    rule = program["native_rule"]
    errors = validate_rule(rule)
    if errors:
        raise ValueError("; ".join(errors))
    expected = {**rule["program"], "operations": [], "native_rule": rule}
    if program != expected:
        raise ValueError("Native program envelope conflicts with its rule identity or source; execution rejected")
    return rule


def preflight_skill(program, state, context, damage_resolver=None):
    """Validate both representations without losing dynamic conditions."""
    if "native_rule" not in program:
        return _preflight(program, state, context, damage_resolver)
    rule = _native_rule(program)
    if context.get("component_evaluation_policy") != "after_payment_before_each_component_experiment" or "resolved_energy_cost" not in context:
        raise ValueError("Native components require explicit timing and resolved_energy_cost")
    _preflight_header(rule["program"], state, context)


def execute_rule(rule, state, context, *, damage_resolver=None):
    """Execute validated component data, including bounded predicates/expressions.

    The caller must bind a trusted configuration to source before invoking this
    low-level experiment interface. A syntactically valid edited config is NOT a
    verified game rule. Existing source configurations use the parity fast path.
    """
    from lab.rule_config import validate_rule, rule_to_program, requires_native_execution
    try:
        errors = validate_rule(rule)
        if errors:
            raise ValueError("; ".join(errors))
        rule, context = deepcopy(rule), deepcopy(context)
        program = rule["program"]
        dynamic = requires_native_execution(rule)
        if not dynamic:
            return execute_skill(rule_to_program(rule), state, context, damage_resolver=damage_resolver)
        if context.get("component_evaluation_policy") != "after_payment_before_each_component_experiment":
            raise ValueError("Conditional components require explicit after-payment per-component experiment timing")
        if "resolved_energy_cost" not in context:
            raise ValueError("Conditional components require explicit resolved_energy_cost, including zero")

        def handler(current, event):
            _preflight_header(program, current, context)
            cost = context.get("resolved_energy_cost", 0)
            current["self"]["energy"] -= cost
            events = ([{"op": "energy.pay", "target": "self", "amount": cost, "source": "caller_resolved_cost"}]
                      if "resolved_energy_cost" in context else [])
            observations = []
            fragment_context = deepcopy(context)
            # The sequence paid once above. Each component has explicit zero
            # additional cost, while preserving the sequence payment evidence.
            # Conditional damage still sees a declared cost and current energy.
            fragment_context["resolved_energy_cost"] = 0
            fragment_context["component_sequence_paid_cost"] = cost
            for component in rule["components"]:
                if any(current[side]["hp"] == 0 for side in ("self", "opponent")):
                    if context.get("faint_policy") == "stop_remaining_skill_on_exhaustion_experiment":
                        events.append({"op": "research.skill_stopped", "component_id": component["id"],
                                       "reason": "exhaustion", "policy": context["faint_policy"]})
                        break
                    raise ValueError("Exhaustion before component needs unresolved faint/trigger timing")
                selected = "when" not in component or evaluate_condition(component["when"], current, event)
                observation = {"component_id": component["id"], "selected": selected,
                               "evidence": deepcopy(component["evidence"]),
                               "uncertainties": deepcopy(component["uncertainties"])}
                observations.append(observation)
                if not selected:
                    continue
                def resolve(value, path='params'):
                    if isinstance(value, dict) and set(value) == {'expr'}:
                        numeric = evaluate_expression(value['expr'], current, event)
                        if numeric.denominator != 1:
                            raise ValueError(f"Component {component['id']} {path} needs explicit rounding; fractional value rejected")
                        return numeric.numerator
                    if isinstance(value, dict):
                        return {key:resolve(item,path+'.'+key) for key,item in value.items()}
                    if isinstance(value,list):
                        return [resolve(item,f'{path}[{index}]') for index,item in enumerate(value)]
                    return deepcopy(value)
                params = resolve(component['params'])
                observation["resolved_params"] = deepcopy(params)
                one = {**deepcopy(program), "operations": [{"op": component["effect"],
                       "params": {"target": component["target"], **params}}]}
                result = execute_effects(one, current, fragment_context, damage_resolver=damage_resolver)
                if result["status"] != "applied":
                    raise ValueError(f"Component {component['id']} blocked: " + "; ".join(result["blockers"]))
                current = result["state"]
                events.extend(item for item in result["events"] if item["op"] != "energy.pay")
            from lab.mechanism_runtime import consume_skill_tokens, after_skill
            current, attached = after_skill(current,rule['program'],context,events)
            events.extend(attached)
            events.extend(consume_skill_tokens(current['self'], attacked=any(e.get('op') == 'damage' for e in events), turn=context.get('turn')))
            result = {"status": "applied", "state": current, "events": events, "blockers": [],
                      "component_observations": observations, "assumptions": deepcopy(context),
                      "training_eligible": False, "full_turn_executed": False, "calibrated": False}
            return {"state": current, "events": [], "result": result}
        return _dispatch(program, state, context, handler)
    except Exception as exc:
        return {"status": "blocked", "state": deepcopy(state), "events": [], "blockers": [str(exc)],
                "training_eligible": False, "full_turn_executed": False, "calibrated": False}
