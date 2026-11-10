import unittest
import os
import sys
import io
from unittest.mock import Mock, patch

from scripts.check_npcap_environment import assess


class NpcapEnvironmentTests(unittest.TestCase):
    def test_frozen_entry_outputs_utf8_even_when_initial_streams_use_gbk(self):
        from scripts import release_bootstrap
        from lab import npcap_environment
        out_bytes, err_bytes = io.BytesIO(), io.BytesIO()
        stdout = io.TextIOWrapper(out_bytes, encoding='gbk')
        stderr = io.TextIOWrapper(err_bytes, encoding='gbk')
        def emit():
            print('工作台：中文正常')
            print('错误日志正常', file=sys.stderr)
            return 0
        with patch.dict(os.environ), patch.object(sys, 'argv', ['backend.exe', 'environment-check']), \
                patch.object(sys, 'stdout', stdout), patch.object(sys, 'stderr', stderr), \
                patch.object(npcap_environment, 'main', side_effect=emit):
            self.assertEqual(release_bootstrap.main(Mock()), 0)
            stdout.flush(); stderr.flush()
            self.assertEqual(out_bytes.getvalue().decode('utf8').splitlines(), ['工作台：中文正常'])
            self.assertEqual(err_bytes.getvalue().decode('utf8').splitlines(), ['错误日志正常'])

    def test_release_dispatch_uses_shared_check_without_loading_battle_resources(self):
        from scripts import release_bootstrap
        from lab import npcap_environment
        mount = Mock()
        with patch.dict(os.environ), patch.object(sys, 'argv', ['backend.exe', 'environment-check', '--output', 'report.json']), \
                patch.object(npcap_environment, 'main', return_value=2) as check:
            self.assertEqual(release_bootstrap.main(mount), 2)
            self.assertEqual(sys.argv, [sys.executable, '--output', 'report.json'])
            check.assert_called_once_with()
            mount.assert_not_called()

    def test_running_npcap_and_anti_cheat_are_not_proof_of_detection(self):
        result = assess({
            'drivers': {'status': 'ok', 'items': [{'Name': 'npcap', 'State': 'Running'},
                                                {'Name': 'ACE-BASE', 'State': 'Running'}]},
            'System': {'status': 'ok', 'items': []},
        })
        self.assertEqual(result['npcap_state'], 'running')
        self.assertEqual(result['anti_npcap_detection'], 'unknown')
        self.assertEqual(len(result['anti_cheat_name_candidates']), 1)
        self.assertEqual(result['npcap_related_events'], [])

    def test_query_failure_preserves_unknown_instead_of_absence(self):
        for section in ['drivers', 'collector']:
            result = assess({section: {'status': 'error', 'items': [], 'error': 'Access denied'}})
            self.assertEqual(result['npcap_state'], 'unknown')
            self.assertEqual(result['anti_npcap_detection'], 'unknown')
            self.assertEqual(result['query_errors'][0]['error'], 'Access denied')

    def test_driver_policy_error_keeps_its_source_and_does_not_blame_anti_cheat(self):
        result = assess({'Microsoft-Windows-CodeIntegrity/Operational': {'status': 'ok', 'items': [
            {'Message': 'Npcap.sys failed signature validation', 'ProviderName': 'CodeIntegrity', 'Id': 1},
            {'Message': 'Unrelated driver failed', 'ProviderName': 'CodeIntegrity', 'Id': 2},
        ]}})
        self.assertEqual(len(result['npcap_related_events']), 1)
        self.assertTrue(result['npcap_related_events'][0]['failure_or_block_wording'])
        self.assertEqual(result['npcap_related_events'][0]['ProviderName'], 'CodeIntegrity')
        self.assertEqual(result['anti_npcap_detection'], 'unknown')

    def test_empty_successful_queries_do_not_claim_capture_is_safe(self):
        result = assess({'drivers': {'status': 'ok', 'items': []}})
        self.assertEqual(result['npcap_state'], 'not_observed')
        self.assertEqual(result['anti_npcap_detection'], 'unknown')

    def test_game_process_is_separate_from_anti_cheat_candidates(self):
        result = assess({'processes': {'status': 'ok', 'items': [
            {'Name': 'NRC-Win64-Shipping', 'Id': 1234}, {'Name': 'SGuard64', 'Id': 4321},
        ]}})
        self.assertEqual(result['game_processes'], [{'Name': 'NRC-Win64-Shipping', 'Id': 1234}])
        self.assertEqual(result['anti_cheat_name_candidates'][0]['Name'], 'SGuard64')
        self.assertEqual(len(result['anti_cheat_name_candidates']), 1)


if __name__ == '__main__':
    unittest.main()
