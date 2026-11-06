"""Build the updatable helper app without modifying the checkout.

Use .venv-release/Scripts/python.exe to package Python bytecode and plain resources.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.release_common import copy_licenses, digest, frozen_source, run, validate_inventory
from scripts.release_resources import discover

BUILDS = ROOT / 'artifacts/release_builds'
APP_FILES = ('desktop.js', 'desktop_services.js', 'desktop_preload.js', 'desktop_renderer.js',
             'desktop_updater.js', 'update_config.json', 'desktop.html', 'desktop.css',
             'main.js', 'preload.js', 'offline.html', 'dimo.ico')


def build_path(build_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', build_id or ''):
        raise ValueError('Invalid build ID')
    return BUILDS / build_id


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def manifest(folder):
    return {p.relative_to(folder).as_posix(): digest(p) for p in sorted(folder.rglob('*')) if p.is_file()}


def validate_backend_catalog(backend):
    """Require reused resources to contain the current verified BWIKI catalog."""
    from lab.catalog_store import runtime_catalog
    catalog, catalog_digest, catalog_path = runtime_catalog()
    try:
        with zipfile.ZipFile(Path(backend) / '_internal/resources.zip') as archive:
            pointer = json.loads(archive.read('data/bwiki/latest.json'))
            if not isinstance(pointer, dict):
                raise ValueError('Invalid packaged catalog pointer')
            relative = pointer.get('path') or pointer.get('snapshot_id') or pointer.get('directory')
            digest = hashlib.sha256(archive.read(catalog_path.relative_to(ROOT).as_posix())).hexdigest()
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise ValueError('Backend catalog is missing or invalid; rebuild with scripts/build_updatable.py') from exc
    if (relative != catalog['snapshot_id'] or pointer.get('catalog_sha256') != catalog_digest
            or digest != catalog_digest):
        raise ValueError('Backend catalog is stale; rebuild with scripts/build_updatable.py')


def build_backend(work, report):
    inventory = discover(ROOT)
    write_json(work / 'inventory.json', inventory)
    validate_inventory(inventory)
    source = work / 'plain-src'
    source.mkdir()
    modules, hashes = [], {}
    excluded = {'metamon_policy', 'metamon_features', 'metamon_reward', 'amago_bridge',
                'amago_training', 'legacy_amago_opponent'}
    for original in sorted((ROOT / 'lab').glob('*.py')):
        if original.stem.startswith('rl_') or original.stem in excluded:
            continue
        relative = original.relative_to(ROOT).as_posix()
        target = source / relative
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(b'' if original.stem == '__init__' else frozen_source(relative, original.read_bytes()))
        hashes[relative] = digest(original)
        if original.stem != '__init__':
            modules.append('lab.' + original.stem)
    for original in sorted((ROOT / 'vendor/rkpp').glob('*.py')):
        shutil.copy2(original, source / original.name)
        hashes[original.relative_to(ROOT).as_posix()] = digest(original)
        modules.append(original.stem)
    parser = 'artifacts/unpack_probe_20261025/parse_roco_tables.py'
    shutil.copy2(ROOT / parser, source / '_release_parser.py')
    hashes[parser] = digest(ROOT / parser)
    shutil.copy2(ROOT / 'scripts/release_bootstrap.py', source / '_release_bootstrap.py')
    hashes['scripts/release_bootstrap.py'] = digest(ROOT / 'scripts/release_bootstrap.py')
    hashes['scripts/plain_release_entry.py'] = digest(ROOT / 'scripts/plain_release_entry.py')
    modules.extend(('_release_parser', '_release_bootstrap', '_release_secrets'))
    source_hash = hashlib.sha256(b''.join(p.name.encode('utf8') + b'\0' + p.read_bytes()
        for p in sorted((ROOT / 'lab').glob('*.py')))).hexdigest()
    package = work / 'resources.zip'
    with zipfile.ZipFile(package, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in inventory['resources']:
            archive.write(ROOT / name, name)
    resource_hash = digest(package)
    (source / '_release_secrets.py').write_text(
        '# Compatibility module name; no encryption keys or access tokens.\n'
        'BUILD_ID=' + repr(report['build_id']) + '\nSOURCE_HASH=' + repr(source_hash) +
        '\nRESOURCE_HASH=' + repr(resource_hash) + '\nSOURCE_HASHES=' + repr(hashes) + '\n', encoding='utf8')
    report.update(source_hash=source_hash, resource_hash=resource_hash, source_hashes=hashes,
                  resource_files=len(inventory['resources']), packaging='python-bytecode-and-plain-zip',
                  packaging_transforms=['pinned parser import', 'original source hash manifest lookup', 'empty package initializer'],
                  packaged_source_hashes=manifest(source))
    write_json(work / 'build-report.json', report)
    args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--console',
            '--name', 'roco_backend', '--distpath', work / 'freeze', '--workpath', work / 'pyi', '--specpath', work,
            '--paths', source, '--paths', ROOT / '.venv-rkpp/Lib/site-packages',
            '--add-data', str(package) + ';.', '--icon', ROOT / 'overlay/dimo.ico']
    for name in modules:
        args.extend(['--hidden-import', name])
    for name in ('scapy', 'Crypto', 'google.protobuf', 'msgpack', 'cryptography'):
        args.extend(['--collect-submodules', name, '--collect-data', name, '--collect-binaries', name])
    for name in ('ffi.dll', 'libmpdec-4.dll', 'sqlite3.dll', 'libssl-3-x64.dll', 'libcrypto-3-x64.dll'):
        dll = Path(sys.base_prefix) / 'Library/bin' / name
        if dll.is_file():
            args.extend(['--add-binary', str(dll) + ';.'])
    for name in ('torch', 'numpy', 'pandas', 'matplotlib', 'amago', 'gymnasium', 'tests', 'tkinter'):
        args.extend(['--exclude-module', name])
    args.append(ROOT / 'scripts/plain_release_entry.py')
    run(args, source, work / 'freeze.log')
    toc = ast.literal_eval((work / 'pyi/roco_backend/Analysis-00.toc').read_text(encoding='utf8'))
    def rows(value):
        if isinstance(value, (tuple, list)):
            if len(value) == 3 and all(isinstance(v, str) for v in value):
                yield value
            else:
                for item in value:
                    yield from rows(item)
    included = {name: Path(path).resolve() for name, path, kind in rows(toc) if kind.startswith('PYMODULE')}
    for name in modules:
        expected = source / (name.replace('.', '/') + '.py')
        if included.get(name) != expected.resolve():
            raise RuntimeError('Frozen module did not use staged bytecode source: ' + name)
    backend = work / 'freeze/roco_backend'
    run([backend / 'roco_backend.exe', 'self-test'], work, work / 'self-test.log')
    report.update(status='backend_built', self_test_passed=True, bytecode_toc_verified=True,
                  backend_path=str(backend), backend_hashes=manifest(backend))
    write_json(work / 'build-report.json', report)
    return backend, inventory


def build(build_id, version, backend_only=False, reuse_backend=None):
    if os.name != 'nt':
        raise RuntimeError('Windows build host required')
    if not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', version):
        raise ValueError('Version must be a stable major.minor.patch version')
    work = build_path(build_id or time.strftime('%Y%m%d-%H%M%S-plain'))
    work.mkdir(parents=True, exist_ok=False)
    report = {'build_id': work.name, 'version': version, 'status': 'building', 'signed': False,
              'public_release_approved': False, 'packaging': 'python-bytecode-and-plain-zip'}
    write_json(work / 'build-report.json', report)
    if reuse_backend:
        previous = build_path(reuse_backend)
        previous_report = json.loads((previous / 'build-report.json').read_text(encoding='utf8'))
        backend = (build_path(previous_report.get('backend_build_id', reuse_backend)) / 'freeze/roco_backend').resolve()
        if (previous_report.get('packaging') != report['packaging'] or not previous_report.get('self_test_passed')
                or not previous_report.get('backend_hashes') or manifest(backend) != previous_report['backend_hashes']):
            raise RuntimeError('Reusable backend is incomplete, modified, or not a verified plain build')
        validate_backend_catalog(backend)
        for key in ('source_hash', 'resource_hash', 'source_hashes', 'resource_files', 'self_test_passed', 'backend_hashes'):
            report[key] = previous_report[key]
        report.update(backend_build_id=previous_report.get('backend_build_id', previous_report['build_id']),
                      backend_path=str(backend), reused_backend=reuse_backend)
        inventory = json.loads((previous / 'inventory.json').read_text(encoding='utf8'))
        write_json(work / 'inventory.json', inventory)
    else:
        backend, inventory = build_backend(work, report)
        report['backend_build_id'] = work.name
    if backend_only:
        report['status'] = 'backend_built'
        write_json(work / 'build-report.json', report)
        print(str(backend), flush=True)
        return work
    for name in APP_FILES:
        if not (ROOT / 'overlay' / name).is_file():
            raise RuntimeError('Required app file missing: ' + name)
    release = work / 'release-meta'
    release.mkdir()
    app = work / 'overlay'
    app.mkdir()
    for name in (*APP_FILES, 'package.json', 'package-lock.json'):
        shutil.copy2(ROOT / 'overlay' / name, app / name)
    report['app_source_hashes'] = {name: digest(app / name) for name in (*APP_FILES, 'package.json', 'package-lock.json')}
    (app / 'desktop.html').write_text((app / 'desktop.html').read_text(encoding='utf8').replace(
        '../web/assets/roco/pet-avatars/3004.png', 'dimo.png'), encoding='utf8')
    shutil.copy2(ROOT / 'web/assets/roco/pet-avatars/3004.png', app / 'dimo.png')
    npm = shutil.which('npm.cmd')
    if not npm:
        raise RuntimeError('npm.cmd is required to install locked desktop production dependencies')
    run([npm, 'ci', '--omit=dev', '--ignore-scripts', '--bin-links=false', '--no-audit', '--no-fund'],
        app, work / 'electron-dependencies.log')
    identity = {
        'release_id': report['backend_build_id'], 'source_hash': report['source_hash'],
        'resource_hash': report['resource_hash'], 'backend': 'python-bytecode',
        'resources': 'unencrypted-zip', 'rules': 'existing-unified-pvp-rules', 'signed': False}
    identity.update(app_build_id=work.name, installer_build_id=work.name, version=version)
    write_json(release / 'release.json', identity)
    copy_licenses(release, inventory)
    output = ROOT / 'dist' / ('RocoPVP-' + work.name + '-installer')
    if output.exists():
        raise FileExistsError(output)
    env = os.environ.copy()
    # Publishing is a separate explicit action. No build-time credential is needed.
    for name in ('GH_TOKEN', 'GITHUB_TOKEN', 'CSC_LINK', 'CSC_KEY_PASSWORD'):
        env.pop(name, None)
    env.update(ROCO_APP_DIR=str(app), ROCO_BACKEND_DIR=str(backend), ROCO_RELEASE_META_DIR=str(release), ROCO_INSTALLER_OUTPUT=str(output),
               ROCO_APP_VERSION=version, CSC_IDENTITY_AUTO_DISCOVERY='false')
    report['status'] = 'packaging'
    write_json(work / 'build-report.json', report)
    run(['node', ROOT / 'overlay/node_modules/electron-builder/cli.js', '--config', ROOT / 'scripts/electron-builder.cjs',
         '--win', 'nsis', '--x64', '--publish', 'never'], ROOT / 'overlay', work / 'installer.log', env=env)
    expected = [output / ('RocoPVP-Setup-' + version + '.exe'), output / 'latest.yml']
    if any(not path.is_file() for path in expected):
        raise RuntimeError('Installer or updater metadata is missing')
    unpacked = (output / 'win-unpacked').resolve()
    if unpacked.parent != output.resolve() or not unpacked.is_relative_to((ROOT / 'dist').resolve()) or not unpacked.is_dir():
        raise RuntimeError('Sandbox ACL target is outside this release output')
    run(['icacls.exe', unpacked, '/grant', '*S-1-15-2-1:(OI)(CI)(RX)', '/T', '/C'],
        ROOT, work / 'sandbox-acl.log')
    report.update(status='installer_built', output=str(output),
                  sandbox_acl_applied=True,
                  installer_hashes={p.name: digest(p) for p in output.iterdir() if p.is_file()})
    write_json(work / 'build-report.json', report)
    print(str(output), flush=True)
    return work


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--id')
    parser.add_argument('--version', required=True)
    parser.add_argument('--backend-only', action='store_true')
    parser.add_argument('--reuse-backend', metavar='BUILD_ID')
    options = parser.parse_args()
    build(options.id, options.version, options.backend_only, options.reuse_backend)
