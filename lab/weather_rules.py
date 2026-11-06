"""Reviewed, source-bound weather configuration; no runtime prose parsing.

Historical numeric configuration and current text are both retained. Execution
order and rounding remain research policies, separate from extracted facts.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / 'artifacts/weather_rules_20261025/weather_rules.json'
REVIEWED_RULES_SHA256 = '47ba0ae91f612688791c0b2c31c27b68c64243e124eaebaf9a09e5b6d45bba47'
OPS = {'power_multiplier', 'energy_multiplier', 'add_status', 'energy_add',
       'extend_weather', 'skill_type_from_weather', 'priority_add', 'power_add',
       'drain', 'stat_multiplier', 'stat_add'}
PHASES = {'before_damage', 'before_cost', 'round_end', 'after_skill',
          'action_order', 'after_damage'}
WEATHER_IDS = {'rain': 3, 'sandstorm': 6, 'blizzard': 5, 'thunder': 14}
SETTERS = {'7050250': 'rain', '7080210': 'sandstorm',
           '7090370': 'blizzard', '7110440': 'thunder'}


class WeatherRulesError(ValueError):
    """Reviewed weather evidence/configuration is missing or changed."""


def validate_weather_rules(rules):
    if rules.get('schema_version') != 1 or rules.get('profile') != 'game_files_weather_research_v1':
        raise WeatherRulesError('Unsupported weather configuration schema/profile')
    if set(rules.get('weather', {})) != set(WEATHER_IDS):
        raise WeatherRulesError('Weather identifiers differ from reviewed set')
    for key, wid in WEATHER_IDS.items():
        row = rules['weather'][key]
        if row.get('weather_id') != wid or row.get('duration') != 8 or not row.get('source'):
            raise WeatherRulesError(f'Invalid weather identity/duration/source: {key}')
    if set(rules.get('setters', {})) != set(SETTERS):
        raise WeatherRulesError('Setter identifiers differ from reviewed set')
    for sid, weather in SETTERS.items():
        row = rules['setters'][sid]
        if row.get('weather') != weather or row.get('duration') != 8:
            raise WeatherRulesError(f'Invalid weather setter: {sid}')
    groups = [r['effects'] for r in rules['weather'].values()]
    for category in ('skill_modifiers', 'trait_modifiers'):
        for sid, effects in rules.get(category, {}).items():
            if not sid.isdigit() or not effects:
                raise WeatherRulesError(f'Invalid modifier identity: {sid}')
            groups.append(effects)
    for effects in groups:
        for effect in effects:
            op = effect.get('op')
            if op not in OPS or effect.get('phase') not in PHASES:
                raise WeatherRulesError(f'Unreviewed weather operation/phase: {op}')
            value = effect.get('value')
            if op == 'skill_type_from_weather':
                if value is not None:
                    raise WeatherRulesError('Weather type operation does not take numeric value')
            elif (isinstance(value, bool) or not isinstance(value, (int, float))
                  or not math.isfinite(value) or not -100 <= value <= 100):
                raise WeatherRulesError(f'Invalid weather operation value: {op}')
            if op in {'power_multiplier', 'energy_multiplier', 'stat_multiplier', 'drain'} and value < 0:
                raise WeatherRulesError(f'Negative weather ratio: {op}')
            if op == 'add_status' and (effect.get('status') not in {'freeze', 'conductive'}
                                       or value < 1 or int(value) != value):
                raise WeatherRulesError('Invalid weather status application')
            when = effect.get('when')
            if not isinstance(when, dict) or (when.get('weather') and when['weather'] not in WEATHER_IDS):
                raise WeatherRulesError('Invalid weather condition')
    if rules.get('formal_training_eligible') is not False or rules.get('server_semantics_verified') is not False:
        raise WeatherRulesError('Research weather profile cannot claim verified server semantics')
    return True


@lru_cache(maxsize=64)
def _hash_file(path, size, mtime_ns):
    # Metadata keys invalidate the cache when ordinary edits update an artifact.
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sha(path):
    stat = path.stat()
    return _hash_file(str(path), stat.st_size, stat.st_mtime_ns)


def _load_reviewed():
    if not RULES_PATH.is_file() or _sha(RULES_PATH) != REVIEWED_RULES_SHA256:
        raise WeatherRulesError('Weather rule file differs from the reviewed hash')
    rules = json.loads(RULES_PATH.read_text(encoding='utf-8'))
    validate_weather_rules(rules)
    return rules


def verify_weather_sources(rules=None):
    rules = _load_reviewed() if rules is None else rules
    errors = []
    for source in rules['sources']:
        path = (ROOT / source['path']).resolve()
        if not path.is_relative_to(ROOT.resolve()) or not path.is_file() or _sha(path) != source['sha256']:
            errors.append(source['path'])
    return errors


def get_weather_rules(catalog=None):
    result = _load_reviewed()
    errors = verify_weather_sources(result)
    if errors:
        raise WeatherRulesError('Weather source evidence changed: ' + ', '.join(errors))
    if catalog is not None:
        snapshot = catalog.get('snapshot_id') if isinstance(catalog, dict) else getattr(catalog, 'snapshot_id', None)
        if snapshot and snapshot != result['snapshot_id']:
            result['uncertainties'].append({'id': 'catalog_version_mismatch', 'expected': result['snapshot_id'], 'actual': snapshot})
    return deepcopy(result)
