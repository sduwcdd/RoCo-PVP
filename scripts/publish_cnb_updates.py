"""Publish immutable app assets to CNB, then atomically update public feed files."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote, urlsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.publish_mobile_update import apk_manifest


def credentials():
    token = os.environ.get('CNB_TOKEN', '').strip()
    for name in ('.env.cnb', 'cnb.txt'):
        if token:
            break
        path = ROOT / name
        if not path.is_file():
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('gb18030')
        match = re.search(r'(?im)^\s*(?:CNB_TOKEN\s*=|Token\s*[:：])\s*(\S+)', text)
        if match:
            token = match.group(1).strip('"\'')
    if not token or any(c.isspace() for c in token):
        raise ValueError('CNB_TOKEN missing; use an ignored local .env.cnb or cnb.txt')
    return token


def sha256(file):
    with Path(file).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class Publisher:
    def __init__(self, token):
        config = json.loads((ROOT / 'overlay/update_config.json').read_text(encoding='utf-8'))
        self.repo = config['cnbRepo']
        if not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+', self.repo):
            raise ValueError('Invalid CNB repository')
        self.token = token
        self.base = 'https://api.cnb.cool/' + self.repo
        self.site = 'https://cnb.cool/' + self.repo
        self.session = requests.Session()
        self.session.headers.update({'Authorization': 'Bearer ' + token,
                                     'Accept': 'application/vnd.cnb.api+json',
                                     'User-Agent': 'RoCo-PVP-release'})
        self.public = requests.Session()
        self.public.trust_env = False

    def api(self, method, path, payload=None, missing_ok=False):
        url = path if path.startswith('https://') else self.base + path
        if not url.startswith(self.base + '/') and url != self.base:
            raise ValueError('CNB API address outside configured repository')
        try:
            response = self.session.request(method, url, json=payload, timeout=(20, 60), allow_redirects=False)
        except requests.RequestException as error:
            raise RuntimeError('CNB API connection failed: ' + type(error).__name__) from None
        if missing_ok and response.status_code == 404:
            return None
        if not 200 <= response.status_code < 300:
            raise RuntimeError('CNB API ' + method + ' HTTP ' + str(response.status_code))
        return response.json() if response.content else None

    def git(self, folder, *arguments):
        import base64
        env = os.environ.copy()
        env.update(GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never', GIT_CONFIG_COUNT='1',
                   GIT_CONFIG_KEY_0='http.https://cnb.cool/.extraHeader',
                   GIT_CONFIG_VALUE_0='Authorization: Basic ' + base64.b64encode(('cnb:' + self.token).encode()).decode())
        result = subprocess.run(['git', '-c', 'credential.helper=', '-c', 'core.autocrlf=false', *arguments],
                                cwd=folder, env=env, capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise RuntimeError('CNB Git operation failed: ' + result.stderr.replace(self.token, '[hidden]')[-500:])
        return result.stdout.strip()

    def checkout(self, folder):
        self.git(folder.parent, 'clone', '--quiet', self.site + '.git', str(folder))
        branches = self.git(folder, 'branch', '-r')
        if 'origin/main' in branches:
            self.git(folder, 'switch', 'main')
        else:
            self.git(folder, 'switch', '-c', 'main')
        self.git(folder, 'config', 'user.name', 'RoCo PVP Publisher')
        self.git(folder, 'config', 'user.email', 'publisher@localhost')
        if not (folder / 'README.md').exists():
            (folder / 'README.md').write_bytes('# 洛克 PVP 国内下载\n'.encode())
            self.git(folder, 'add', 'README.md')
            self.git(folder, 'commit', '--quiet', '-m', 'Initialize app distribution repository')
            self.git(folder, 'push', '--quiet', '-u', 'origin', 'main')

    def download_url(self, tag, name):
        return self.site + '/-/releases/download/' + quote(tag, safe='') + '/' + quote(name, safe='')

    def upload(self, release, file):
        file = Path(file)
        wanted = sha256(file)
        existing = next((a for a in (release.get('assets') or []) if a['name'] == file.name), None)
        if existing:
            self.verify_asset(existing, file, wanted)
            return existing
        if not release['draft']:
            raise ValueError('Published release is missing an asset; use a new version')
        for attempt in range(3):
            try:
                upload = self.api('POST', '/-/releases/' + release['id'] + '/asset-upload-url',
                                  {'asset_name': file.name, 'size': file.stat().st_size, 'ttl': 0, 'overwrite': False})
                target = urlsplit(upload['upload_url'])
                if target.scheme != 'https' or target.username:
                    raise ValueError('Invalid signed upload address')
                print('上传 CNB ' + file.name + ' · ' + target.hostname, flush=True)
                with file.open('rb') as stream:
                    response = self.public.put(upload['upload_url'], data=stream,
                                               headers={'Content-Type': 'application/octet-stream',
                                                        'Content-Length': str(file.stat().st_size)},
                                               timeout=(20, 900), allow_redirects=False)
                if response.status_code != 200:
                    raise RuntimeError('CNB asset upload HTTP ' + str(response.status_code))
                self.api('POST', upload['verify_url'])
                refreshed = self.api('GET', '/-/releases/' + release['id'])
                asset = next(a for a in refreshed['assets'] if a['name'] == file.name)
                self.verify_asset(asset, file, wanted)
                release['assets'] = refreshed['assets']
                return asset
            except (requests.RequestException, RuntimeError) as error:
                if attempt == 2:
                    raise RuntimeError('CNB upload failed; draft retained: ' + type(error).__name__) from None
                time.sleep(1 + attempt)
                refreshed = self.api('GET', '/-/releases/' + release['id'])
                present = next((a for a in refreshed['assets'] if a['name'] == file.name), None)
                if present:
                    self.verify_asset(present, file, wanted)
                    release['assets'] = refreshed['assets']
                    return present

    @staticmethod
    def verify_asset(asset, file, wanted):
        algorithm = asset.get('hash_algo', '').lower().replace('-', '')
        value = asset.get('hash_value', '').lower().removeprefix('sha256:')
        if asset['size'] != Path(file).stat().st_size or algorithm != 'sha256' or value != wanted:
            raise ValueError('CNB asset size or SHA-256 mismatch: ' + Path(file).name)

    def release(self, tag, files, revision, prerelease):
        release = self.api('GET', '/-/releases/tags/' + quote(tag, safe=''), missing_ok=True)
        if release is None:
            release = self.api('POST', '/-/releases', {'tag_name': tag, 'target_commitish': revision,
                               'name': tag, 'body': '洛克 PVP 安装包及版本校验信息。',
                               'draft': True, 'prerelease': prerelease, 'make_latest': 'false'})
        for file in files:
            self.upload(release, file)
        if release['draft']:
            release = self.api('PATCH', '/-/releases/' + release['id'],
                               {'draft': False, 'prerelease': prerelease, 'make_latest': 'false' if prerelease else 'true'})
        return release


def windows_feed(text, version, address):
    name = 'RocoPVP-Setup-' + version + '.exe'
    if re.search(r'^version: [\'"]?' + re.escape(version) + r'[\'"]?$', text, re.M) is None:
        raise ValueError('Windows feed version differs from build')
    for field in ('url', 'path'):
        expression = r'(?m)^(\s*(?:- )?' + field + r': )' + re.escape(name) + r'\s*$'
        text, count = re.subn(expression, lambda m: m.group(1) + json.dumps(address), text)
        if count != 1:
            raise ValueError('Unexpected Windows feed asset layout')
    return text


def publish(desktop_build=None, apk=None):
    publisher = Publisher(credentials())
    repository = publisher.api('GET', '')
    if repository.get('visibility_level') != 'Public':
        raise ValueError('Anonymous updates require a public CNB repository')
    temporary_root = ROOT.parent / '.codex-tmp'
    temporary_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='roco-cnb-publish-', dir=temporary_root, ignore_cleanup_errors=True) as directory:
        work = Path(directory)
        checkout = work / 'repo'
        publisher.checkout(checkout)
        revision = publisher.git(checkout, 'rev-parse', 'HEAD')
        receipt = {'repository': publisher.site, 'releases': [], 'anonymousChecks': []}
        if desktop_build:
            if not re.fullmatch(r'[A-Za-z0-9_-]+', desktop_build):
                raise ValueError('Invalid desktop build ID')
            build = ROOT / 'artifacts/release_builds' / desktop_build
            report = json.loads((build / 'build-report.json').read_text(encoding='utf-8'))
            if report['status'] != 'installer_built' or not report.get('self_test_passed'):
                raise ValueError('Desktop build is incomplete')
            version = report['version']
            output = Path(report['output']).resolve()
            if not output.is_relative_to(ROOT / 'dist'):
                raise ValueError('Desktop output outside project dist')
            files = [output / ('RocoPVP-Setup-' + version + '.exe'),
                     output / ('RocoPVP-Setup-' + version + '.exe.blockmap'), output / 'latest.yml']
            for file in files:
                if sha256(file) != report['installer_hashes'][file.name]:
                    raise ValueError('Desktop artifact changed after build')
            tag = 'v' + version
            publisher.release(tag, files, revision, False)
            address = publisher.download_url(tag, files[0].name)
            pointer = checkout / 'updates/windows/latest.yml'
            pointer.parent.mkdir(parents=True, exist_ok=True)
            pointer.write_bytes(windows_feed(files[2].read_text(encoding='utf-8'), version, address).encode())
            receipt['releases'].append({'tag': tag, 'asset': files[0].name, 'url': address, 'sha256': sha256(files[0])})
        if apk:
            apk = Path(apk).resolve(strict=True)
            manifest = apk_manifest(apk)
            version = manifest['versionName'].removesuffix('-internal')
            tag = 'android-v' + version + ('.0' if version.count('.') == 1 else '') + '-internal'
            metadata = work / 'android-update.json'
            metadata.write_bytes((json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode())
            publisher.release(tag, [apk, metadata], revision, True)
            manifest['downloadUrl'] = publisher.download_url(tag, apk.name)
            pointer = checkout / 'updates/android/latest.json'
            pointer.parent.mkdir(parents=True, exist_ok=True)
            pointer.write_bytes((json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode())
            receipt['releases'].append({'tag': tag, 'asset': apk.name, 'url': manifest['downloadUrl'], 'sha256': manifest['sha256']})
        if not desktop_build and not apk:
            raise ValueError('At least one verified app build is required')
        links = []
        windows = checkout / 'updates/windows/latest.yml'
        if windows.is_file():
            text = windows.read_text(encoding='utf-8')
            version = re.search(r'^version: (.+)$', text, re.M).group(1)
            address = json.loads(re.search(r'^path: (.+)$', text, re.M).group(1))
            links.append('Windows ' + version + ' [下载安装包](' + address + ')')
        android = checkout / 'updates/android/latest.json'
        if android.is_file():
            current = json.loads(android.read_text(encoding='utf-8'))
            links.append('Android ' + current['versionName'] + ' [下载安装包](' + current['downloadUrl'] + ')')
        readme = checkout / 'README.md'
        content = readme.read_text(encoding='utf-8')
        start, end = '<!-- roco-downloads:start -->', '<!-- roco-downloads:end -->'
        block = start + '\n\n## 国内下载\n\n' + '\n\n'.join(links) + '\n\n' + end
        if start in content and end in content:
            previous = content[content.index(start):content.index(end) + len(end)]
            content = content.replace(previous, block)
        else:
            content = content.rstrip() + '\n\n' + block + '\n'
        readme.write_bytes(content.encode())
        publisher.git(checkout, 'add', 'README.md', 'updates')
        if publisher.git(checkout, 'diff', '--cached', '--name-only'):
            publisher.git(checkout, 'commit', '--quiet', '-m', 'Publish verified app update feeds')
            publisher.git(checkout, 'push', '--quiet', 'origin', 'main')
        for file in (checkout / 'updates').rglob('*'):
            if file.is_file():
                relative = file.relative_to(checkout).as_posix()
                url = publisher.site + '/-/git/raw/main/' + relative
                response = publisher.public.get(url, timeout=30)
                if response.status_code != 200 or hashlib.sha256(response.content).digest() != hashlib.sha256(file.read_bytes()).digest():
                    raise ValueError('Anonymous update pointer verification failed')
                receipt['anonymousChecks'].append(url)
        target = ROOT / 'artifacts/cnb-publish-report.json'
        target.write_bytes((json.dumps(receipt, ensure_ascii=False, indent=2) + '\n').encode())
        print(json.dumps(receipt, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop-build-id')
    parser.add_argument('--apk', type=Path)
    args = parser.parse_args()
    publish(args.desktop_build_id, args.apk)
