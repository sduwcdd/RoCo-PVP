"""Shared Windows capture/anti-cheat inventory and bounded OS event logs.

Run with .venv-rkpp/Scripts/python.exe scripts/check_npcap_environment.py.
The report describes observable components and errors. Detection policy remains
unknown even when all queries succeed and no matching events are returned.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
NPCAP = re.compile(r"\bnpcap(?:_wifi)?\b|\bnpf(?:_wifi)?\b|\bwpcap\.dll\b", re.I)
ANTI_CHEAT = re.compile(r"anti[- ]?cheat|sguard|ace[-_]|acebase|tenprotect|tensafe", re.I)
FAILURE = re.compile(r"block|denied|fail|invalid.*signature|拒绝|阻止|阻拦|失败|无法加载|不能加载", re.I)

COLLECT_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$report = [ordered]@{}
$namePattern = 'npcap|\bnpf\b|anti[- ]?cheat|sguard|ace[-_]|acebase|tenprotect|tensafe|^NRC-Win64-Shipping$'
function Read-Section([string]$name, [scriptblock]$read) {
    try {
        $rows = @(& $read)
        $report[$name] = @{ status = 'ok'; items = $rows }
    } catch {
        if ($_.FullyQualifiedErrorId -like 'NoMatchingEventsFound*') {
            $report[$name] = @{ status = 'ok'; items = @() }
        } else {
            $report[$name] = @{ status = 'error'; items = @(); error = $_.Exception.Message }
        }
    }
}
Read-Section 'services' {
    Get-CimInstance Win32_Service -OperationTimeoutSec 6 |
        Where-Object { ($_.Name + ' ' + $_.DisplayName) -match $namePattern } |
        Select-Object Name, DisplayName, State, StartMode
}
Read-Section 'drivers' {
    Add-Type -AssemblyName System.ServiceProcess
    [System.ServiceProcess.ServiceController]::GetDevices() |
        Where-Object { ($_.ServiceName + ' ' + $_.DisplayName) -match $namePattern } |
        Select-Object @{Name='Name';Expression={$_.ServiceName}}, DisplayName,
            @{Name='State';Expression={$_.Status.ToString()}}
}
Read-Section 'processes' {
    Get-Process | Where-Object { $_.ProcessName -match $namePattern } |
        Select-Object @{Name='Name';Expression={$_.ProcessName}}, Id
}
foreach ($channel in @('System', 'Microsoft-Windows-CodeIntegrity/Operational')) {
    Read-Section $channel {
        Get-WinEvent -FilterHashtable @{ LogName = $channel; StartTime = (Get-Date).AddDays(-7) } -MaxEvents 300 |
            Where-Object { $_.Message -match 'npcap|\bnpf\b|wpcap\.dll' } |
            Select-Object -First 30 @{Name='Time';Expression={$_.TimeCreated.ToUniversalTime().ToString('o')}},
                Id, ProviderName, LevelDisplayName, @{Name='Message';Expression={
                    $text = [string]$_.Message
                    $text.Substring(0, [Math]::Min($text.Length, 1600))
                }}
    }
}
$report | ConvertTo-Json -Depth 7 -Compress
"""


def collect_environment():
    if os.name != 'nt':
        raise OSError('此诊断工具仅支持 Windows')
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run(
        [str(powershell), '-NoProfile', '-NonInteractive', '-Command', COLLECT_SCRIPT],
        capture_output=True, encoding='utf-8', errors='strict', timeout=40,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise OSError('Windows 状态查询失败，退出码 ' + str(result.returncode))
    sections = json.loads(result.stdout.lstrip('\ufeff'))
    required = {'services', 'drivers', 'processes', 'System', 'Microsoft-Windows-CodeIntegrity/Operational'}
    if not isinstance(sections, dict) or set(sections) != required:
        raise ValueError('Windows 状态查询返回了不完整的结构')
    return sections


def assess(sections):
    components, npcaps, events, errors, games = [], [], [], [], []
    for section, data in sections.items():
        if data['status'] != 'ok':
            errors.append({'section': section, 'error': data.get('error', '查询未完成')})
        for item in data.get('items', []):
            if section in {'services', 'drivers', 'processes'}:
                name = str(item.get('Name', '')) + ' ' + str(item.get('DisplayName', ''))
                if NPCAP.search(name):
                    npcaps.append({'section': section, **item})
                if ANTI_CHEAT.search(name):
                    components.append({'section': section, **item})
                if section == 'processes' and str(item.get('Name', '')).lower() == 'nrc-win64-shipping':
                    games.append(item)
            else:
                text = str(item.get('Message', ''))
                if NPCAP.search(text):
                    events.append({'channel': section, 'failure_or_block_wording': bool(FAILURE.search(text)), **item})
    inventory_failed = any(x['section'] in {'services', 'drivers', 'collector'} for x in errors)
    if any(x['section'] == 'drivers' and x.get('State') == 'Running' for x in npcaps):
        npcap_state = 'running'
    elif npcaps:
        npcap_state = 'observed'
    elif inventory_failed:
        npcap_state = 'unknown'
    else:
        npcap_state = 'not_observed'
    return {
        'anti_npcap_detection': 'unknown',
        'conclusion': '无法确认游戏是否具备或启用了针对 Npcap 的检测。',
        'npcap_state': npcap_state,
        'npcap_components': npcaps,
        'anti_cheat_name_candidates': components,
        'game_processes': games,
        'npcap_related_events': events,
        'query_errors': errors,
        'limits': [
            '服务、驱动及进程按名称匹配，候选组件与当前游戏的关联尚未确认。',
            '日志范围为最近7天，每个通道最新300条，最多保留30条匹配记录。',
            '加载失败、访问拒绝或签名错误的来源需要结合事件核对，可能涉及系统策略或软件兼容。',
            '本机系统信息与日志不足以证明反作弊的私有检测能力，检测规则可能随版本变化。',
        ],
    }


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='只读查询 Npcap、反作弊名称线索及系统日志，检测能力结果保持待核实。')
    parser.add_argument('--output', type=Path, help='本地 JSON 报告保存位置')
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    output = args.output or ROOT / 'artifacts/app' / ('npcap-environment-' + now.strftime('%Y%m%d-%H%M%S-%f') + '.json')
    try:
        sections = collect_environment()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        sections = {'collector': {'status': 'error', 'items': [], 'error': str(error)}}
    report = {'schema': 'npcap-environment-1', 'collected_at': now.isoformat(), 'analysis': assess(sections), 'observations': sections}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    analysis = report['analysis']
    print(analysis['conclusion'])
    print('Npcap 状态 ' + analysis['npcap_state'])
    print('反作弊名称候选 ' + str(len(analysis['anti_cheat_name_candidates'])))
    for item in analysis['anti_cheat_name_candidates']:
        print('  ' + item['Name'] + ' / ' + str(item.get('State', '进程已观察到')))
    print('游戏进程 ' + str(len(analysis['game_processes'])))
    print('Npcap 相关系统记录 ' + str(len(analysis['npcap_related_events'])))
    print('查询未完成 ' + str(len(analysis['query_errors'])))
    print('本地报告 ' + str(output.resolve()))
    return 2 if analysis['query_errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
