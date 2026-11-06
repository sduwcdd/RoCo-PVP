"""Append eight whole-source reviewed compositions without changing old rows."""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lab.mechanism_runtime import CONFIG, CONDITION_POLICY
from lab.ruleset import canonical_hash
from lab.server import load_catalog


SPECS = {
    7170250: ('3f81fa98ce889ccd4ac0e146054b365b6071a2014dd9cfb93e99c734166ce485', None,
        [{'op': 'energy.transfer', 'target': 'opponent', 'amount': 3, 'event': 'after.use'}], []),
    7020460: ('4c56f3d09abe3608618c8c9fa148632fd5972e0878a7e9056fa9aba6f29733c6', 2,
        [{'op': 'damage.hits', 'target': 'opponent', 'amount': 4, 'event': 'before.damage', 'when': 'response.success'}], ['status']),
    7020470: ('51921380e5ca706d71943d5f0ee649500a3ba1007dace2ce80e8fbbbd7d27cdf', 1,
        [{'op': 'damage.hits', 'target': 'opponent', 'amount': 3, 'event': 'before.damage', 'when': 'response.success'}], ['status']),
    7140070: ('a4323f6b8de5cfbbe8743938022108fc1afe2e3eab75b898b3b1e4f72e90ced4', 2,
        [{'op': 'damage.hits', 'target': 'opponent', 'amount': 6, 'event': 'before.damage', 'when': 'response.success'}], ['status']),
    7120280: ('e823858376fdd9fc862bf93ccb7a4ef7746612dfb60b608c82103edb2771dacf', 1,
        [{'op': 'damage.hits', 'target': 'opponent', 'amount': 3, 'event': 'before.damage', 'when': 'opponent.poisoned'}], []),
    7180110: ('714cd427aaad2f02a25d6a87bd4e96ed4b521f7a04a8852006f23f76d7b200b1', 3,
        [{'op': 'damage.hits', 'target': 'opponent', 'amount': 5, 'event': 'before.damage', 'when': 'self.hp_below_half'}], []),
    7170100: ('3a780b8cb4087542b112bccf9f89dcbf48b7e6cf515936269c3964236aef5a5d', None,
        [{'op': 'energy.reduce', 'target': 'opponent', 'amount': 6, 'event': 'after.damage', 'when': 'response.success'}], ['status']),
    7030530: ('51b7d407953d382b7807402bbb383fc2f97069112415535654aa9b83b9793fe5', None,
        [{'op': 'hp.restore', 'target': 'self', 'percent': 50, 'event': 'after.damage', 'when': 'response.success'},
         {'op': 'energy.restore', 'target': 'self', 'amount': 5, 'event': 'after.damage', 'when': 'response.success'}], ['status']),
}


def main():
    catalog = load_catalog()[0]
    table_path = 'artifacts/unpack_probe_20261025/battle_analysis/tables/parsed/SKILL_CONF.json'
    installed = json.loads((ROOT / table_path).read_text(encoding='utf-8'))
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    old = deepcopy(config['skills'])
    existing = {row['skill_id']: row for row in old}
    added = []
    for mid, (expected, hits, components, responses) in SPECS.items():
        record = catalog['moves'][str(mid)]
        if canonical_hash(record) != expected:
            raise ValueError(f'Whole source changed for {mid}; new review required')
        game = installed[str(mid)]
        row = {'skill_id': mid, 'name': record['name']['zh'], 'description': record['desc']['zh'],
            'record_hash': expected, 'raw': deepcopy(record), 'components': components,
            'responses': responses,
            'source': {'snapshot_id': catalog['snapshot_id'], 'bwiki': record['source_url'],
                'bwiki_source': deepcopy(catalog['provenance']['Skills']),
                'game_table_path': table_path, 'game_record': deepcopy(game),
                'game_record_hash': canonical_hash(game)},
            'condition_policy': CONDITION_POLICY,
            'uncertainties': ['Historical installation and BWIKI records are retained separately; online overrides are unverified.',
                'Predicate timing, sequential hits, resource caps and rounding use named research policies.']}
        if hits is not None:
            row['base_hits'] = hits
        if mid in existing:
            if existing[mid] != row:
                raise ValueError(f'Existing mechanism row {mid} differs; refusing to replace it')
            continue
        config['skills'].append(row)
        added.append(mid)
    assert config['skills'][:len(old)] == old
    if added:
        CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'added': added, 'reviewed_mechanism_rows': len(config['skills']),
                      'config_hash': canonical_hash(config)}))


if __name__ == '__main__':
    main()
