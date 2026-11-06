"""Complete installed dark-surge pool; probabilities remain an explicit experiment."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from lab.ruleset import canonical_hash

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'data/rules/reviewed-dark-surge-1.json'
CONFIG_HASH = 'c99935a7d25f8456875708cd4e692b19a51b435d4f13faff09c97cf610d95822'
POLICY = 'complete_pool_uniform_with_replacement_sha256_counter_seed0_experiment_v1'


@lru_cache(maxsize=16)
def _hash(path, size, stamp):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rules():
    data = json.loads(CONFIG.read_text(encoding='utf8'))
    if canonical_hash(data) != CONFIG_HASH:
        raise ValueError('Dark-surge reviewed configuration changed')
    for source in data['sources']:
        path = (ROOT / source['path']).resolve()
        st = path.stat()
        if not path.is_relative_to(ROOT) or _hash(str(path), st.st_size, st.st_mtime_ns) != source['sha256']:
            raise ValueError('Dark-surge extracted source changed')
    return data


def research_context():
    return {'dark_surge_policy': POLICY, 'dark_surge_seed': 0}


def validate_member(member):
    rows = member.get('dark_surge_modifiers', [])
    if not isinstance(rows, list):
        raise ValueError('Dark-surge speed requires an explicit source ledger')
    for row in rows:
        if (not isinstance(row, dict) or row.get('buff_id') != 20010091 or row.get('stat') != 'spd'
                or row.get('source_id') != 1016027 or row.get('source_hash') != CONFIG_HASH
                or row.get('config_hash') != CONFIG_HASH or row.get('policy') != POLICY
                or type(row.get('layers')) is not int or not 1 <= row['layers'] <= 99
                or row.get('amount') != -10 * row['layers']):
            raise ValueError('Dark-surge flat-speed source/layers differ')
    return rows


def modify_speed(member, speed):
    return max(1, speed + sum(row['amount'] for row in validate_member(member)))


def apply(member, mark_layers, *, context):
    from lab.modifier_ledger import register_stat
    data = rules()
    if context.get('dark_surge_policy') != POLICY or context.get('dark_surge_seed') != 0:
        raise ValueError('Dark-surge requires an explicit uncalibrated random policy')
    if type(mark_layers) is not int or not 1 <= mark_layers <= 99:
        raise ValueError('Invalid dark-surge mark layers')
    validate_member(member)
    current = deepcopy(member)
    cursor = current.get('dark_surge_draw_index', 0)
    if type(cursor) is not int or cursor < 0 or not isinstance(current.get('member_id'), str):
        raise ValueError('Dark-surge cursor or stable owner missing')
    events = []
    for index in range(cursor, cursor + mark_layers * data['layers_per_mark']):
        attempt = 0
        while True:
            material = f"dark-surge-v1:0:{current['member_id']}:{index}:{attempt}"
            value = int.from_bytes(hashlib.sha256(material.encode()).digest()[:4], 'big')
            if value < 2**32 - (2**32 % len(data['pool'])):
                break
            attempt += 1
        row = data['pool'][value % len(data['pool'])]
        if row['flat']:
            rows = current.setdefault('dark_surge_modifiers', [])
            total = sum(item['layers'] for item in rows)
            if total < 99:
                rows.append({'buff_id':row['buff_id'], 'stat':'spd', 'layers':1, 'amount':-10,
                    'source_id':1016027, 'source_hash':CONFIG_HASH, 'policy':POLICY, 'config_hash':CONFIG_HASH})
        else:
            terms = current['stat_modifiers'].setdefault(row['stat'], [])
            # The source cap is applied to explicit same-BUFF layer records only.
            records = current.get('stat_modifier_sources', {}).get(row['stat'], [])
            layers = sum(-r['term']['numerator'] * 10 // r['term']['denominator']
                         for r in records if r.get('buff_id') == row['buff_id'])
            if layers < 99:
                terms.append({'numerator':-10, 'denominator':100})
                register_stat(current, row['stat'], source_kind='mark', source_id=1016027,
                    source_hash=CONFIG_HASH, buff_id=row['buff_id'])
        events.append({'op':'mark.dark_surge_draw', 'target_member_id':current['member_id'],
            'draw_index':index, 'pool_index':value % len(data['pool']), 'buff_id':row['buff_id'],
            'raw_uint32':value, 'attempt':attempt, 'policy':POLICY, 'config_hash':CONFIG_HASH})
    current['dark_surge_draw_index'] = cursor + mark_layers * data['layers_per_mark']
    member.clear(); member.update(current)
    return events
