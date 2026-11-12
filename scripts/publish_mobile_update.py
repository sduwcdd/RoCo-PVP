"""Publish a signed Android APK and its verified in-app update manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.publish_app_update import credentials, request


def apk_manifest(apk):
    apk = Path(apk).resolve(strict=True)
    sdk = os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT')
    if not sdk:
        properties = ROOT / 'mobile/android/local.properties'
        for line in properties.read_text(encoding='utf-8').splitlines():
            if line.startswith('sdk.dir='):
                sdk = line.split('=', 1)[1].replace('\\:', ':').replace('\\\\', '\\')
    tools = Path(sdk or '') / 'build-tools/35.0.0'
    aapt = tools / ('aapt.exe' if os.name == 'nt' else 'aapt')
    signer = tools / ('apksigner.bat' if os.name == 'nt' else 'apksigner')
    package = subprocess.check_output([str(aapt), 'dump', 'badging', str(apk)], encoding='utf-8')
    signing = subprocess.check_output([str(signer), 'verify', '--print-certs', str(apk)], encoding='utf-8')
    identity = re.search(r"^package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", package, re.M)
    minimum = re.search(r"^sdkVersion:'(\d+)'", package, re.M)
    certificates = re.findall(r'^Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]{64})$', signing, re.M)
    if not identity or not minimum or len(certificates) != 1:
        raise ValueError('APK identity, minimum SDK or single verified signer is missing')
    name, version, label = identity.groups()
    if name != 'cn.roco.mobile' or not re.fullmatch(r'\d+\.\d+(?:\.\d+)?-internal', label):
        raise ValueError('Expected an internal cn.roco.mobile APK')
    if not re.fullmatch(r'[A-Za-z0-9._-]+\.apk', apk.name):
        raise ValueError('Invalid APK asset filename')
    with apk.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'versionCode': int(version), 'versionName': label, 'packageName': name,
            'minSdk': int(minimum.group(1)), 'apk': apk.name, 'sha256': digest,
            'size': apk.stat().st_size, 'signerSha256': certificates[0].lower()}


def publish(apk, notes_file=None, dry_run=False):
    apk = Path(apk).resolve(strict=True)
    manifest = apk_manifest(apk)
    base_version = manifest['versionName'].removesuffix('-internal')
    if base_version.count('.') == 1:
        base_version += '.0'
    tag = 'android-v' + base_version + '-internal'
    metadata = apk.parent / 'android-update.json'
    metadata.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if dry_run:
        print(json.dumps({'tag': tag, 'manifest': manifest}, ensure_ascii=False))
        return
    config = json.loads((ROOT / 'overlay/update_config.json').read_text(encoding='utf-8'))
    token = credentials()
    base = 'https://api.github.com/repos/' + config['owner'] + '/' + config['repo']
    if request('GET', base, token)['private']:
        raise ValueError('Anonymous Android updates require the public release repository')
    releases = request('GET', base + '/releases?per_page=100', token)
    release = next((item for item in releases if item['tag_name'] == tag), None)
    if release is None:
        notes = Path(notes_file).read_text(encoding='utf-8') if notes_file else '安卓内部版，支持在 APP 内检查、下载和安装更新。'
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        release = request('POST', base + '/releases', token,
                          {'tag_name': tag, 'target_commitish': revision, 'name': tag,
                           'body': notes, 'draft': True, 'prerelease': True})
    assets = {item['name']: item for item in release['assets']}
    for file in (apk, metadata):
        with file.open('rb') as stream:
            wanted = 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()
        asset = assets.get(file.name)
        if asset and (asset.get('digest') != wanted or asset['size'] != file.stat().st_size):
            raise ValueError('Existing release asset differs; publish a new version: ' + file.name)
        if not asset:
            if not release['draft']:
                raise ValueError('Published release is incomplete; publish a new version')
            url = release['upload_url'].split('{')[0] + '?name=' + quote(file.name)
            print('上传 ' + file.name, flush=True)
            asset = request('POST', url, token, file=file)
        if asset.get('digest') != wanted or asset['size'] != file.stat().st_size:
            raise ValueError('GitHub asset verification failed: ' + file.name)
    if release['draft']:
        release = request('PATCH', base + '/releases/' + str(release['id']), token,
                          {'draft': False, 'prerelease': True, 'make_latest': 'false'})
    print(json.dumps({'published': release['html_url'], 'manifest': manifest}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--notes-file', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    publish(args.apk, args.notes_file, args.dry_run)
