"""Native-compiled desktop backend entry, never distributed as Python source."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def _root():
    return Path(sys._MEIPASS)


def _state():
    root = Path(os.environ['LOCALAPPDATA']) / 'RocoPVP'
    root.mkdir(parents=True, exist_ok=True)
    return root


def _kernel():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.restype = wintypes.BOOL
    return kernel


def _process_exited(kernel, handle):
    status = kernel.WaitForSingleObject(handle, 0)
    if status == 0:
        return True
    if status == 258:
        return False
    raise ctypes.WinError(ctypes.get_last_error())


def _handle_identity(kernel, handle):
    # A terminated process object may survive while its image name is unavailable (WinError 31).
    if _process_exited(kernel, handle):
        return None
    try:
        created, exited, user, system = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(system), ctypes.byref(user)):
            raise ctypes.WinError(ctypes.get_last_error())
        length = wintypes.DWORD(32768)
        name = ctypes.create_unicode_buffer(length.value)
        if not kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(length)):
            raise ctypes.WinError(ctypes.get_last_error())
    except OSError:
        if _process_exited(kernel, handle):
            return None
        raise
    return (created.dwHighDateTime << 32 | created.dwLowDateTime, os.path.normcase(name.value))


def _process_identity(pid):
    kernel = _kernel()
    handle = kernel.OpenProcess(0x1000 | 0x00100000, False, int(pid))
    if not handle:
        if ctypes.get_last_error() == 87:
            return None
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return _handle_identity(kernel, handle)
    finally:
        kernel.CloseHandle(handle)


def _elevate(args):
    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG), ('hwnd', wintypes.HWND),
            ('lpVerb', wintypes.LPCWSTR), ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR),
            ('lpDirectory', wintypes.LPCWSTR), ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE),
            ('lpIDList', ctypes.c_void_p), ('lpClass', wintypes.LPCWSTR), ('hkeyClass', wintypes.HKEY),
            ('dwHotKey', wintypes.DWORD), ('hIcon', wintypes.HANDLE), ('hProcess', wintypes.HANDLE)]
    info = SHELLEXECUTEINFO()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40
    info.lpVerb = 'runas'
    info.lpFile = sys.executable
    info.lpParameters = subprocess.list2cmdline(['capture-control', *args, '--elevated'])
    info.lpDirectory = str(Path(sys.executable).parent)
    info.nShow = 0
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFO)]
    shell.ShellExecuteExW.restype = wintypes.BOOL
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == 1223:
            raise OSError('管理员授权被取消')
        raise OSError(error, 'Windows 管理员助手启动失败：' + ctypes.FormatError(error).strip())
    if not info.hProcess:
        raise RuntimeError('Windows 未返回管理员助手进程句柄，无法确认启动结果')
    kernel = _kernel()
    try:
        if kernel.WaitForSingleObject(info.hProcess, 0xFFFFFFFF) != 0:
            raise RuntimeError('无法确认管理员助手已退出')
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value
    finally:
        kernel.CloseHandle(info.hProcess)


def _capture_control(args):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['Start', 'Stop'], required=True)
    parser.add_argument('--iface', default='WLAN')
    parser.add_argument('--elevated', action='store_true')
    parsed = parser.parse_args(args)
    logs = _state() / 'artifacts/app'
    logs.mkdir(parents=True, exist_ok=True)
    result = logs / 'capture-result.json'
    receipt_path = logs / 'capture-owner.json'
    child = None
    def save(value):
        result.write_text(json.dumps(value, ensure_ascii=False), encoding='utf8')
    try:
        if not ctypes.windll.shell32.IsUserAnAdmin():
            if parsed.elevated:
                raise RuntimeError('管理员权限尚未授予')
            return _elevate(args)
        iface = parsed.iface
        if not iface.strip() or len(iface) > 128 or any(c in iface for c in '\r\n\0'):
            raise ValueError('网卡名称无效')
        if parsed.mode == 'Stop':
            receipt = json.loads(receipt_path.read_text(encoding='utf8'))
            identity = _process_identity(receipt['pid'])
            if identity is not None:
                expected = (int(receipt['start_ticks']), os.path.normcase(sys.executable))
                if identity != expected or receipt.get('kind') != 'roco-release-capture':
                    raise RuntimeError('进程归属已改变，拒绝停止')
                kernel = _kernel()
                handle = kernel.OpenProcess(0x0001 | 0x00100000 | 0x1000, False, int(receipt['pid']))
                if not handle:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    current = _handle_identity(kernel, handle)
                    if current is not None and current != expected:
                        raise RuntimeError('进程归属已改变，拒绝停止')
                    if current is not None and not kernel.TerminateProcess(handle, 0):
                        error = ctypes.get_last_error()
                        if not _process_exited(kernel, handle):
                            raise ctypes.WinError(error)
                    if kernel.WaitForSingleObject(handle, 5000) != 0:
                        raise RuntimeError('尚未确认采集进程退出，归属记录已保留，请重试停止')
                finally:
                    kernel.CloseHandle(handle)
            receipt_path.unlink()
            save({'ok': True, 'state': 'stopped'})
            return 0
        if receipt_path.exists():
            old = json.loads(receipt_path.read_text(encoding='utf8'))
            identity = _process_identity(old['pid'])
            if identity and str(identity[0]) == old.get('start_ticks'):
                raise RuntimeError('本APP的采集进程已在运行')
        output = _state() / 'rkpp' / ('rkpp_opencode_server_' + time.strftime('%Y%m%d_%H%M%S'))
        output.mkdir(parents=True, exist_ok=False)
        stdout, stderr = logs / ('capture-' + str(time.time_ns()) + '.stdout.log'), logs / ('capture-' + str(time.time_ns()) + '.stderr.log')
        with stdout.open('wb') as out, stderr.open('wb') as err:
            child = subprocess.Popen([sys.executable, 'capture', 'opencode-server', '--iface', iface,
                '--port', '8195', '--relay-host', '127.0.0.1', '--relay-port', '8765', '--out-dir', str(output)],
                cwd=str(_state()), stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
        identity = _process_identity(child.pid)
        if identity is None:
            raise RuntimeError('采集进程启动后意外退出，请查看日志')
        receipt_path.write_text(json.dumps({'pid': child.pid, 'start_ticks': str(identity[0]),
            'kind': 'roco-release-capture', 'script': sys.executable, 'stdout': str(stdout), 'stderr': str(stderr)}), encoding='utf8')
        save({'ok': True, 'state': 'starting', 'pid': child.pid})
        return 0
    except Exception as error:
        if child is not None and child.poll() is None:
            try:
                child.terminate()
                child.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired) as cleanup_error:
                error = RuntimeError(f'{error}；本次子进程{child.pid}清理失败：{cleanup_error}')
        save({'ok': False, 'error': str(error)})
        print(str(error), file=sys.stderr, flush=True)
        return 1


def _self_test():
    from lab.battle_data import physical_info
    from rkpp_proto_core import read_varint
    from rkpp_analysis import _read_varint_from
    from rkpp_analyzer import RkppAnalyzer
    from lab.live_damage import _rules, estimate_moves
    from lab.live_power import specification
    from lab.power_rule_runtime import stat_difference_candidate
    from lab.mark_runtime import mark_identity
    from lab.game_layer_references import _verified_reader
    from lab.release_paths import build_identity
    import Data
    # Verify parser boundaries and fresh analyzer state before shipping the backend.
    for payload, expected in ((b'\x08', 8), (b'\xac\x02', 300), (b'\xff' * 9 + b'\x01', 2**64 - 1)):
        assert read_varint(payload, 0) == (expected, len(payload))
        assert _read_varint_from(payload, 0) == (expected, len(payload))
    analyzer = RkppAnalyzer(port=8195, logger=None, writer=None, key_file=Path('unused.key'),
                            csv_sink=None, preset_key=None, stop_after_key=False)
    assert analyzer._total_errors == analyzer.failed_business_records == analyzer.listener_errors == 0
    physical = physical_info(3381, height=201, weight=645412, voice=48)
    assert physical['height']['text'] == '2.01米' and physical['weight']['text'] == '645.41千克'
    assert physical['medals'][0]['name'] == '小不点' and physical['voice']['text'] == '+48'
    catalog, _ = _rules()
    assert catalog['snapshot_id']
    assert specification(7060120)['components'][0]['op'] == 'distinct_type_history'
    assert stat_difference_candidate()['step'] == 30
    assert mark_identity(20490030)['mark_id']
    assert Data._connect_sqlite().execute('SELECT count(*) FROM sqlite_master').fetchone()[0] > 0
    assert _verified_reader(_root() / 'artifacts/unpack_probe_20261025')[0]
    pet = {'petBaseId': 3001, 'level': 60, 'effectiveTraitId': 0, 'energy': 10,
        'currentHp': 400, 'maxHp': 400, 'battleBuffs': [], 'entryActionCount': 1,
        'battleStats': {'phyAtk': 200, 'magAtk': 200, 'phyDef': 100, 'magDef': 100},
        'moves': [{'slot': 1, 'skillId': 7060120}], 'skillUseHistoryComplete': True,
        'carriedSkillIds': [7060120, 0, 0, 0], 'skillTypeUseCounts': {'7040370': {'火系': 1}}}
    quote = estimate_moves(pet, pet)[0]
    assert quote['normalMin'] > 0, quote.get('reason')
    print(json.dumps({'ok': True, 'identity': build_identity(), 'snapshot': catalog['snapshot_id'],
                      'damage': quote['normalMin']}, ensure_ascii=False), flush=True)
    return 0


def main(mount_resources):
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    os.environ['ROCO_RELEASE'] = '1'
    os.environ.pop('PYTHONPATH', None)
    if len(sys.argv) < 2:
        raise SystemExit('请从洛克PVP桌面入口启动')
    command, args = sys.argv[1], sys.argv[2:]
    if command == 'capture-control':
        return _capture_control(args)
    if command == 'environment-check':
        from lab.npcap_environment import main as check_environment
        sys.argv = [sys.executable, *args]
        return check_environment()
    mount_resources()
    if command == 'self-test':
        return _self_test()
    if command == 'server':
        from lab.server import main as serve
        sys.argv = [sys.executable, *args]
        serve()
        return 0
    if command == 'capture':
        import faulthandler
        faulthandler.enable(all_threads=True)
        import rkpp_live_tools
        sys.argv = [sys.executable, *args]
        return rkpp_live_tools.main()
    raise ValueError('不支持的启动模式')
