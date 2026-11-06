"""Ownership and failure rollback without UAC or real packet capture."""
import json
import ctypes
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import release_bootstrap as runtime


class ReleaseCaptureControlTests(unittest.TestCase):
    def test_capture_parser_boundaries_and_analyzer_initial_counters(self):
        vendor = Path(__file__).resolve().parents[1] / 'vendor/rkpp'
        with patch.object(runtime.sys, 'path', [str(vendor), *runtime.sys.path]):
            from rkpp_proto_core import read_varint
            from rkpp_analysis import _read_varint_from
            from rkpp_analyzer import RkppAnalyzer
        for reader in (read_varint, _read_varint_from):
            for payload, expected in ((b'\x08', 8), (b'\xac\x02', 300), (b'\xff' * 9 + b'\x01', 2**64 - 1)):
                self.assertEqual(reader(payload, 0), (expected, len(payload)))
            for invalid in (b'', b'\x80', b'\xff' * 11):
                with self.assertRaises(ValueError):
                    reader(invalid, 0)
        with tempfile.TemporaryDirectory() as folder:
            analyzer = RkppAnalyzer(port=8195, logger=None, writer=None, key_file=Path(folder) / 'unused.key',
                                    csv_sink=None, preset_key=None, stop_after_key=False,
                                    key_store_dir=Path(folder))
            for field in ('failed_business_records', '_consecutive_errors', '_total_errors', 'listener_errors'):
                self.assertEqual(getattr(analyzer, field), 0)
            self.assertFalse(analyzer._error_alerted)

    def test_exited_process_is_not_queried_for_its_unavailable_image(self):
        kernel = Mock()
        kernel.OpenProcess.return_value = 123
        kernel.WaitForSingleObject.return_value = 0
        with patch.object(runtime, '_kernel', return_value=kernel):
            self.assertIsNone(runtime._process_identity(456))
        kernel.OpenProcess.assert_called_once_with(0x101000, False, 456)
        kernel.QueryFullProcessImageNameW.assert_not_called()
        kernel.GetProcessTimes.assert_not_called()
        kernel.CloseHandle.assert_called_once_with(123)

    def test_exit_during_identity_query_is_distinct_from_live_query_failure(self):
        for exited in (False, True):
            with self.subTest(exited=exited):
                kernel = Mock()
                kernel.GetProcessTimes.return_value = 1
                kernel.QueryFullProcessImageNameW.return_value = 0
                kernel.WaitForSingleObject.side_effect = [258, 0 if exited else 258]
                with patch.object(runtime.ctypes, 'get_last_error', return_value=31):
                    if exited:
                        self.assertIsNone(runtime._handle_identity(kernel, 123))
                    else:
                        with self.assertRaises(OSError) as error:
                            runtime._handle_identity(kernel, 123)
                        self.assertEqual(error.exception.winerror, 31)

    def test_unelevated_fresh_start_delegates_before_querying_capture_processes(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(runtime, '_state', return_value=Path(folder)), \
                 patch.object(runtime.ctypes.windll.shell32, 'IsUserAnAdmin', return_value=0), \
                 patch.object(runtime, '_elevate', return_value=0) as elevate, \
                 patch.object(runtime, '_process_identity') as identity, \
                 patch.object(runtime.subprocess, 'Popen') as spawn:
                self.assertEqual(runtime._capture_control(['--mode', 'Start', '--iface', 'WLAN']), 0)
            elevate.assert_called_once_with(['--mode', 'Start', '--iface', 'WLAN'])
            identity.assert_not_called()
            spawn.assert_not_called()

    def test_runas_uses_typed_unicode_structure_and_preserves_64bit_handle(self):
        handle = 0x100000123
        shell, kernel = Mock(), Mock()
        def launch(pointer):
            info = pointer._obj
            self.assertTrue(all(type(name) is str for name, _ in info._fields_))
            self.assertEqual(info.cbSize, ctypes.sizeof(info))
            self.assertEqual(info.lpVerb, 'runas')
            self.assertIn('capture-control --mode Start', info.lpParameters)
            self.assertTrue(info.lpParameters.endswith('--elevated'))
            info.hProcess = handle
            return 1
        shell.ShellExecuteExW.side_effect = launch
        kernel.WaitForSingleObject.return_value = 0
        def exit_code(process, pointer):
            self.assertEqual(process, handle)
            pointer._obj.value = 0
            return 1
        kernel.GetExitCodeProcess.side_effect = exit_code
        with patch.object(runtime.ctypes, 'WinDLL', return_value=shell), patch.object(runtime, '_kernel', return_value=kernel):
            self.assertEqual(runtime._elevate(['--mode', 'Start']), 0)
        self.assertIs(shell.ShellExecuteExW.restype, runtime.wintypes.BOOL)
        kernel.WaitForSingleObject.assert_called_once_with(handle, 0xFFFFFFFF)
        kernel.CloseHandle.assert_called_once_with(handle)

    def test_uac_cancellation_and_windows_launch_failure_are_distinguished(self):
        for error, text in ((1223, '管理员授权被取消'), (2, 'Windows 管理员助手启动失败')):
            with self.subTest(error=error):
                shell = Mock()
                shell.ShellExecuteExW.return_value = 0
                with patch.object(runtime.ctypes, 'WinDLL', return_value=shell), \
                     patch.object(runtime.ctypes, 'get_last_error', return_value=error), \
                     patch.object(runtime, '_kernel') as kernel:
                    with self.assertRaisesRegex(OSError, text):
                        runtime._elevate(['--mode', 'Start'])
                    kernel.assert_not_called()

    def test_start_failure_terminates_only_the_new_child(self):
        with tempfile.TemporaryDirectory() as folder:
            child = Mock(pid=123, poll=Mock(return_value=None))
            with patch.object(runtime, '_state', return_value=Path(folder)), \
                 patch.object(runtime.ctypes.windll.shell32, 'IsUserAnAdmin', return_value=1), \
                 patch.object(runtime.subprocess, 'Popen', return_value=child), \
                 patch.object(runtime, '_process_identity', return_value=None):
                self.assertEqual(runtime._capture_control(['--mode', 'Start']), 1)
            child.terminate.assert_called_once_with()
            child.wait.assert_called_once_with(timeout=5)
            self.assertFalse(json.loads((Path(folder) / 'artifacts/app/capture-result.json').read_text(encoding='utf8'))['ok'])

    def test_stop_wait_failure_preserves_receipt_and_changed_identity_is_never_killed(self):
        for changed in (False, True):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as folder:
                logs = Path(folder) / 'artifacts/app'
                logs.mkdir(parents=True)
                receipt = logs / 'capture-owner.json'
                receipt.write_text(json.dumps({'pid': 123, 'start_ticks': '456', 'kind': 'roco-release-capture'}), encoding='utf8')
                identity = (456, os.path.normcase(runtime.sys.executable))
                kernel = Mock()
                kernel.WaitForSingleObject.return_value = 258
                with patch.object(runtime, '_state', return_value=Path(folder)), \
                     patch.object(runtime.ctypes.windll.shell32, 'IsUserAnAdmin', return_value=1), \
                     patch.object(runtime, '_process_identity', return_value=identity), \
                     patch.object(runtime, '_handle_identity', return_value=(789, identity[1]) if changed else identity), \
                     patch.object(runtime, '_kernel', return_value=kernel):
                    self.assertEqual(runtime._capture_control(['--mode', 'Stop']), 1)
                self.assertTrue(receipt.exists())
                if changed:
                    kernel.TerminateProcess.assert_not_called()
                else:
                    kernel.TerminateProcess.assert_called_once()
