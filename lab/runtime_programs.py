"""Cache reviewed immutable configurations, never battle state or random draws."""
from copy import deepcopy
from threading import Lock
from lab import forced_switch_programs, team_target_programs, random_devotion_runtime, choice_runtime, duration_runtime, action_outcome_runtime, derived_power_runtime, expression_programs, slot_runtime, attack_grant_runtime, skill_history_runtime, action_field_runtime, status_skill_runtime, mark_steal_runtime
from lab.charge_program_adapter import load_charge_program_overrides
from lab import mechanism_runtime, defense_runtime, transformation_runtime, mark_runtime
from lab import adjacent_power_runtime, payment_runtime, pressure_runtime, response_cost_runtime, adjacent_cost_runtime, adjacent_power_aura_runtime, slot_stat_runtime, power_rule_runtime, team_rotation_runtime, swift_release_runtime, power_rule_runtime

_CACHE = {}
_LOCK = Lock()


def reviewed_programs(prepared, selected_skill_ids=None):
    folder = mechanism_runtime.CONFIG.parent / prepared.snapshot_id
    files = sorted(mechanism_runtime.CONFIG.parent.glob('reviewed-*.json'))
    files += [folder / 'phase-config-1.json', folder / 'phase-config-1.manifest.json']
    stamp = tuple((str(path), path.stat().st_mtime_ns) for path in files)
    key = (prepared.catalog_content_hash, stamp)
    with _LOCK:
        if key not in _CACHE:
            programs = {**load_charge_program_overrides(prepared._rules._catalog), **mechanism_runtime.programs(prepared), **defense_runtime.defense_programs(prepared),
                        **transformation_runtime.programs(prepared), **mark_runtime.mark_programs(prepared), **forced_switch_programs.programs(prepared), **team_target_programs.programs(prepared), **random_devotion_runtime.programs(prepared), **choice_runtime.choice_programs(prepared), **duration_runtime.programs(prepared), **action_outcome_runtime.programs(prepared), **derived_power_runtime.programs(prepared), **expression_programs.programs(prepared), **slot_runtime.programs(prepared), **attack_grant_runtime.programs(prepared), **skill_history_runtime.programs(prepared), **action_field_runtime.programs(prepared), **status_skill_runtime.programs(prepared), **mark_steal_runtime.programs(prepared), **pressure_runtime.programs(prepared), **response_cost_runtime.programs(prepared), **adjacent_cost_runtime.programs(prepared), **adjacent_power_aura_runtime.programs(prepared), **slot_stat_runtime.programs(prepared), **power_rule_runtime.programs(prepared), **team_rotation_runtime.programs(prepared), **swift_release_runtime.programs(prepared)}
            programs.update(adjacent_power_runtime.programs(prepared))
            programs.update(payment_runtime.programs(prepared))
            from lab import cute_runtime
            programs.update(cute_runtime.programs(prepared))
            from lab import energy_burst_runtime
            programs.update(energy_burst_runtime.programs(prepared))
            from lab import user_skill_extensions
            programs.update(user_skill_extensions.programs(prepared))
            from lab.dynamic_skills import generator_programs
            programs.update(generator_programs(prepared))
            _CACHE.clear()
            _CACHE[key] = programs
        programs = _CACHE[key]
        if selected_skill_ids is not None:
            programs = {mid: programs[mid] for mid in sorted(set(selected_skill_ids)) if mid in programs}
        return deepcopy(programs)
