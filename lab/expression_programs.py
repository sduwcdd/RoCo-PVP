"""Reviewed source configurations using the existing bounded expression engine."""
from copy import deepcopy
import json
from pathlib import Path
from lab.prepared_rules import prepare_rules
from lab.rule_config import execution_program
from lab.ruleset import canonical_hash

CONFIG = Path(__file__).resolve().parents[1] / 'data/rules/reviewed-expression-components-1.json'
CONFIG_HASH = 'e24a7e8b2d5cdabb2a41d779cd2c9de319db90253d7f063b484a109ec1e6814d'


def programs(catalog):
    prepared = prepare_rules(catalog)
    data = json.loads(CONFIG.read_text(encoding='utf8'))
    if canonical_hash(data) != CONFIG_HASH or prepared.snapshot_id != data['snapshot_id']:
        raise ValueError('Expression configuration or snapshot changed')
    result = {}
    for key, row in data['skills'].items():
        record = prepared._rules.skill(int(key))
        if record != row['record'] or canonical_hash(record) != row['record_hash']:
            raise ValueError('Expression skill source changed')
        result[int(key)] = execution_program(deepcopy(row['rule']))
    return result
