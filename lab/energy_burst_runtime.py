"""Consume-all-energy attack using the user-confirmed shared HUD tier table."""
from copy import deepcopy

from lab import live_power
from lab.ruleset import canonical_hash

SKILL_ID = 7020550
POLICY = 'user_confirmed_existing_hud_energy_tiers_clamp_10_20261030'


def programs(prepared):
    row = live_power.specification(SKILL_ID)
    record = prepared._rules.skill(SKILL_ID)
    if not row or row.get('source_policy') != POLICY or row['record_hash'] != canonical_hash(record):
        raise ValueError('Energy burst source differs from its confirmed HUD rule')
    program = deepcopy(prepared._rules.program(SKILL_ID))
    program.pop('native_rule', None)
    program.update(status='compiled', blockers=[], execution_blockers=[],
        energy_burst_components={'consume': 'all_current_energy', 'policy': POLICY,
                                 'source_config_hash': canonical_hash(row)},
        operations=[{'op': 'damage', 'params': {'target': 'opponent', 'kind': record['kind'],
            'type': record['type'], 'power': row['components'][0]['powers'][0]}}])
    return {SKILL_ID: program}


def resolve_program(program, state, context):
    if not program.get('energy_burst_components'):
        return program
    row = live_power.specification(SKILL_ID)
    expected = {'consume': 'all_current_energy', 'policy': POLICY, 'source_config_hash': canonical_hash(row)}
    if (program.get('game_id') != SKILL_ID or program.get('source_hash') != row['record_hash']
            or program['energy_burst_components'] != expected):
        raise ValueError('Consume-all energy program/source changed')
    energy = context.get('energy_before_cast')
    if type(energy) is not int or energy < 0:
        raise ValueError('Energy burst needs exact pre-payment energy, including zero')
    powers = row['components'][0]['powers']
    out = deepcopy(program)
    out['operations'][0]['params']['power'] = powers[min(energy, len(powers) - 1)]
    out['energy_burst_resolved_energy'] = energy
    return out
