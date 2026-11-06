"""Shared resource staging and license helpers for desktop and mobile builds."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(args, cwd, log, env=None):
    with Path(log).open('a', encoding='utf8') as out:
        subprocess.run([str(a) for a in args], cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT, check=True)


def validate_inventory(inventory):
    """Validate discover() exclusions without pinning future resource additions."""
    if inventory['missing']:
        raise RuntimeError('Missing referenced resources; inspect inventory.json')
    ignored = {'artifacts/unpack_probe_20261025/parse_roco_tables.py',
               'data/external/user-teams-20261030/team-codes.txt',
               'data/reference/team-code-20261025/user-team-codes.txt',
               'data/reference/formula-followup-20261025/arena-source-recheck.json',
               'data/reference/mechanics-20261025/evidence.json',
               # Numeric sample provenance uses path/hash constants, never personal replay storage.
               'data/reference/world-panel-20261101.json'}
    provenance_only = {
        ('artifacts/world_dunshu_20261101/npc_evidence.json', 'data/replays/human-battles.sqlite3'),
        ('artifacts/world_dunshu_20261101/npc_evidence.json', 'artifacts/unpack_probe_20261025/extract_targeted.py'),
    }
    if any(row['path'] not in ignored and (row['source'], row['path']) not in provenance_only
           for row in inventory['forbidden']):
        raise RuntimeError('Unreviewed resource exclusions; inspect inventory.json')


def frozen_source(relative, raw):
    """Adapt file loading only in compiler input; preserve evidence adapter sources."""
    if relative not in ('lab/game_rule_candidates.py', 'lab/game_layer_references.py'):
        return raw
    text = raw.decode('utf8').replace('\r\n', '\n')
    name = 'verified_roco_table_probe' if relative.endswith('game_rule_candidates.py') else 'layer_reference_verified_probe'
    old = (f'    spec = importlib.util.spec_from_file_location("{name}", parser_path)\n'
           '    parser = importlib.util.module_from_spec(spec)\n    spec.loader.exec_module(parser)\n')
    if text.count(old) != 1:
        raise RuntimeError('Pinned parser loading adapter changed; review the frozen transformation')
    text = text.replace(old, '    import _release_parser as parser\n')
    if relative.endswith('game_rule_candidates.py'):
        old = 'def file_hash(path):\n    return hashlib.sha256(Path(path).read_bytes()).hexdigest()'
        if text.count(old) != 1:
            raise RuntimeError('Pinned source hashing adapter changed')
        text = text.replace(old, 'def file_hash(path):\n    from lab.release_runtime import frozen_source_hash\n'
            '    original = frozen_source_hash(path)\n    if original is not None:\n        return original\n'
            '    return hashlib.sha256(Path(path).read_bytes()).hexdigest()')
    return text.encode('utf8')


def copy_licenses(output, inventory):
    notices = output / 'licenses'
    notices.mkdir(exist_ok=True)
    for row in inventory['licenses']:
        original = ROOT / row['path']
        name = row['name'].replace('/', '_').replace('\\', '_')
        # Several upstream projects use the same basename for distinct notices.
        tag = hashlib.sha256(row['path'].encode('utf8')).hexdigest()[:8]
        shutil.copy2(original, notices / (name + '-' + tag + '-' + original.name))
    from importlib.metadata import distribution
    for name in ('PyInstaller', 'cryptography', 'cffi'):
        d = distribution(name)
        for item in d.files or []:
            if 'licenses/' in str(item).replace('\\', '/'):
                p = Path(d.locate_file(item))
                tag = hashlib.sha256(str(item).encode('utf8')).hexdigest()[:8]
                shutil.copy2(p, notices / (name + '-' + tag + '-' + p.name))
    python_license = Path(sys.base_prefix) / 'LICENSE_PYTHON.txt'
    if python_license.is_file():
        shutil.copy2(python_license, notices / 'PYTHON-LICENSE.txt')
