"""Component admission is separate from compilation and live calibration."""
from lab.effect_runtime import OPS


def inspect_program(program):
    reasons = list(program.get('blockers', []))
    structured = program.get('status') == 'compiled'
    if not structured and not reasons:
        reasons.append('技能描述尚未完整结构化')
    if structured:
        effects = [(op.get('op'), op.get('params', {})) for op in program.get('operations', [])]
        effects += [(c.get('effect'), c.get('params', {}))
                    for c in program.get('native_rule', {}).get('components', [])]
        for op, params in effects:
            if op == 'choice.select' and 'choice_components' in program:
                continue
            if op == 'defense.plan' and ('defense_components' in program or 'transformation_components' in program):
                continue
            if op == 'pressure.plan' and 'pressure_components' in program:
                continue
            if op == 'response_cost.plan' and 'response_cost_components' in program:
                continue
            if op == 'adjacent_cost.plan' and 'adjacent_cost_components' in program:
                continue
            if op == 'adjacent_power.plan' and 'adjacent_power_components' in program:
                continue
            if op == 'slot_stat.plan' and 'slot_stat_components' in program:
                continue
            if op == 'power_rule.plan' and 'power_rule_components' in program:
                continue
            if op == 'team_rotation.plan' and 'team_rotation_components' in program:
                continue
            if op == 'swift_release.plan' and 'swift_release_components' in program:
                continue
            if op not in OPS:
                reasons.append('完整回合尚无此组件执行器：' + str(op))
            if op == 'status.add' and params.get('status') not in {'poison', 'burn', 'freeze', 'leech'}:
                reasons.append('未接通该状态的完整生命周期：' + str(params.get('status')))
    return {'description_structured': structured, 'components_executable': structured and not reasons,
            'full_battle_executable': False, 'calibrated': False,
            'supported': structured and not reasons, 'blockers': list(dict.fromkeys(reasons))}
