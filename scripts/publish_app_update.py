"""Publish verified installers to the public binary-only update repository."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import socket
import time
from urllib.parse import quote, urlsplit
import requests

ROOT = Path(__file__).resolve().parents[1]


def request(method, url, token, payload=None, file=None):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in {'api.github.com', 'uploads.github.com'}:
        raise ValueError('Only GitHub API/upload endpoints are allowed')
    headers = {'Authorization': 'Bearer ' + token, 'User-Agent': 'RoCo-PVP-release',
               'Accept': 'application/vnd.github+json'}
    data = json.dumps(payload).encode() if payload is not None else None
    if data is not None:
        headers.update({'Content-Type': 'application/json', 'Content-Length': str(len(data))})
    if file is not None:
        headers.update({'Content-Type': 'application/octet-stream', 'Content-Length': str(file.stat().st_size)})
    try:
        if file:
            with file.open('rb') as stream:
                response = requests.request(method, url, data=stream, headers=headers, timeout=(30, 1800), allow_redirects=False)
        else:
            response = requests.request(method, url, data=data, headers=headers, timeout=(30, 45), allow_redirects=False)
        if response.status_code == 204:
            return {}
        if not 200 <= response.status_code < 300:
            # Never put headers, request bodies or tokens into release logs.
            raise RuntimeError(f'GitHub {method} failed: HTTP {response.status_code}')
        return response.json()
    except requests.RequestException:
        raise RuntimeError('GitHub 连接中断，草稿已保留；请重试发布') from None


def credentials():
    if os.environ.get('GH_TOKEN'):
        return os.environ['GH_TOKEN']
    result = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n',
                            text=True, capture_output=True, check=True, timeout=30)
    values = dict(row.split('=', 1) for row in result.stdout.splitlines() if '=' in row)
    if not values.get('password'):
        raise RuntimeError('请先使用 Git Credential Manager 登录 GitHub，或设置本次发布的 GH_TOKEN')
    return values['password']


def verify_desktop(work, output):
    """Cache one real desktop check per immutable build; never close a user's APP."""
    target = work / 'desktop-verification.json'
    if target.exists():
        return
    if os.name != 'nt':
        raise RuntimeError('请在 Windows 构建机验证桌面后发布')
    query = "@(Get-Process -Name '洛克PVP' -ErrorAction SilentlyContinue).Count"
    active = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', query],
                            capture_output=True, text=True, check=True, timeout=20)
    if active.stdout.strip() != '0':
        raise RuntimeError('请先从托盘退出正在运行的安装版 APP，再发布；发布器不会停止用户的应用')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = os.environ.copy(); env['ROCO_APP_PORT'] = str(port); env.pop('ELECTRON_RUN_AS_NODE', None)
    started = time.time()
    with (work / 'publish-desktop.stdout.log').open('wb') as out, (work / 'publish-desktop.stderr.log').open('wb') as err:
        child = subprocess.Popen([str(output / 'win-unpacked/洛克PVP.exe'), '--verify-desktop'],
                                 cwd=output, env=env, stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            code = child.wait(timeout=55)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill.exe', '/PID', str(child.pid), '/T', '/F'], capture_output=True, timeout=5)
            raise RuntimeError('桌面验证超时，未发布；请查看本构建验证日志') from None
    result = Path(os.environ['LOCALAPPDATA']) / 'RocoPVP/artifacts/app/desktop-verification.json'
    if code != 0 or not result.exists() or result.stat().st_mtime < started:
        raise RuntimeError('桌面验证没有生成本次有效结果，未发布')
    verified = json.loads(result.read_text('utf-8'))
    if verified.get('server', {}).get('port') != port:
        raise RuntimeError('桌面验证端口不匹配，未发布')
    target.write_text(json.dumps(verified, ensure_ascii=False, indent=2), encoding='utf-8')


def publish(build_id, notes_file=None, dry_run=False):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', build_id):
        raise ValueError('Invalid build ID')
    work = ROOT / 'artifacts/release_builds' / build_id
    report = json.loads((work / 'build-report.json').read_text('utf-8'))
    if report['status'] != 'installer_built':
        raise RuntimeError('安装包构建尚未完成')
    version = report['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Stable update versions must be major.minor.patch')
    output = Path(report['output']).resolve()
    if not output.is_relative_to((ROOT / 'dist').resolve()):
        raise ValueError('Installer output is outside project dist')
    if not dry_run:
        if report.get('packaging') not in ('python-bytecode-and-plain-zip', 'reused-native-cython-and-aes-resources'):
            raise RuntimeError('发布已阻止：安装包构建方式未识别')
        verify_desktop(work, output)
        verified = json.loads((work / 'desktop-verification.json').read_text('utf-8'))
        if not (verified.get('rendererIpc') and verified.get('workbenchReady') and verified.get('publicUpdateSettings')):
            raise RuntimeError('本次桌面或公开更新界面验证未通过，未发布')
    files = [output / f'RocoPVP-Setup-{version}.exe', output / f'RocoPVP-Setup-{version}.exe.blockmap', output / 'latest.yml']
    hashes = {}
    for p in files:
        with p.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if report['installer_hashes'].get(p.name) != digest:
            raise RuntimeError('安装包已在构建后发生变化：' + p.name)
        hashes[p.name] = digest
    config = json.loads((ROOT / 'overlay/update_config.json').read_text('utf-8'))
    repo = config['owner'] + '/' + config['repo']
    result = {'repository': repo, 'version': version, 'files': hashes}
    if dry_run:
        print(json.dumps(result, ensure_ascii=False, indent=2)); return result
    token = credentials()
    user = request('GET', 'https://api.github.com/user', token)
    if user['login'].lower() != config['owner'].lower():
        raise RuntimeError('请使用更新仓库所有者账号发布')
    base = 'https://api.github.com/repos/' + repo
    if request('GET', base, token)['private']:
        raise RuntimeError('发布已阻止：当前更新源仓库必须为公开仓库')
    tag = 'v' + version
    releases = request('GET', base + '/releases?per_page=100', token)
    release = next((r for r in releases if r['tag_name'] == tag), None)
    if release and '[WITHDRAWN_DO_NOT_PUBLISH]' in (release.get('body') or ''):
        raise RuntimeError('此候选已撤回，请使用新的修正版本号')
    if release is None:
        notes = Path(notes_file).read_text('utf-8') if notes_file else '洛克PVP 辅助工具更新。可在设置中下载、校验后安装并重启；使用当前辅助工具的统一游戏规则。'
        release = request('POST', base + '/releases', token,
                          {'tag_name': tag, 'name': '洛克PVP ' + version, 'body': notes, 'draft': True, 'prerelease': False})
    assets = {a['name']: a for a in release['assets']}
    receipts = []
    for p in files:
        asset = assets.get(p.name)
        if asset is not None and asset['state'] != 'uploaded' and release['draft']:
            request('DELETE', base + '/releases/assets/' + str(asset['id']), token)
            asset = None
        if asset is None:
            if not release['draft']:
                raise RuntimeError('已发布版本不完整，不覆盖旧版本；请发布新的版本号')
            url = release['upload_url'].split('{')[0] + '?name=' + quote(p.name)
            print('上传 ' + p.name, flush=True)
            asset = request('POST', url, token, file=p)
        if asset.get('digest') != 'sha256:' + hashes[p.name] or asset['size'] != p.stat().st_size:
            raise RuntimeError('GitHub 附件校验失败，不发布更新：' + p.name)
        receipts.append({'name': p.name, 'bytes': asset['size'], 'sha256': hashes[p.name], 'url': asset['browser_download_url']})
    if release['draft']:
        release = request('PATCH', base + '/releases/' + str(release['id']), token,
                          {'draft': False, 'prerelease': False, 'make_latest': 'true'})
    result.update(release=release['html_url'], assets=receipts, private=False)
    (work / 'publish-report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'published': result['release'], 'private': False}, ensure_ascii=False), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--build-id', required=True)
    parser.add_argument('--notes-file')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        publish(args.build_id, args.notes_file, args.dry_run)
    except (RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from None
