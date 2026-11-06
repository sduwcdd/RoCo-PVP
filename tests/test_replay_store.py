from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from lab.live_battle import BattleTracker, LiveBattleFeed
from lab.replay_store import ReplayStore
from tests.test_live_battle import pet_record


def entry(battle_id=1, round_no=1, observer=False):
    return {'round': round_no, 'init_info': {'battle_id': battle_id,
        'observe_battle': {'is_observer': observer},
        'player_team': [{'pets': [pet_record(1, 3001)]}],
        'enemy_team': [{'pets': [pet_record(401, 3002, enemy=True)]}]}}


class ReplayStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'human.sqlite3'
        self.identity = patch('lab.replay_store.rule_identity', return_value={'training_eligible': False, 'snapshot_id': 'test'})
        self.identity.start()

    def tearDown(self):
        self.identity.stop()
        self.temp.cleanup()

    def test_record_reload_dedup_and_replay_keep_partial_observation(self):
        store, tracker = ReplayStore(self.path), BattleTracker()
        start = entry(round_no=8, observer=True)
        tracker.handle_event('0x1316', start)
        self.assertIn('敌方 6 只', tracker.timeline[0]['text'])
        self.assertEqual(tracker.timeline[0]['observedRosterCounts']['enemy'], 1)
        recording = store.record(tracker, '0x1316', start, 1)
        cast = {'perform_cmd': {'round': 8, 'seq_num': 1, 'perform_info': [{'type': 1,
            'skill_cast': {'caster_id': 401, 'skill_id': 704020000, 'skill_name': '吹火'}}]}}
        tracker.handle_event('0x1324', cast)
        store.record(tracker, '0x1324', cast, 2)
        store.record(tracker, '0x1324', cast, 2)
        store.close()
        store = ReplayStore(self.path)
        saved = store.load(recording)
        self.assertEqual(len(saved['packets']), 2)
        self.assertEqual(saved['observer'], 1)
        self.assertFalse(json.loads(saved['quality_json'])['complete_from_start'])
        self.assertEqual(saved['training_eligible'], 0)
        self.assertTrue(any(e['kind'] == 'skill_cast' for e in saved['timeline']))
        replayed = BattleTracker()
        for packet in saved['packets']:
            replayed.handle_event(packet['opcode'], packet['content'])
        self.assertEqual(replayed.timeline, tracker.timeline)
        store.close()

    def test_feed_saves_each_battle_before_same_page_resets_tracker(self):
        store = ReplayStore(self.path)
        feed = LiveBattleFeed(archive=store)
        rows = [{'_relay_event_id': i, 'opencode': '0x1316', 'content': entry(i)} for i in (1, 2)]
        with patch.object(feed, '_get', return_value=rows), patch.object(feed.tracker, 'snapshot', return_value={'runtime': {}}):
            payload = feed.poll_once()
        self.assertTrue(payload['runtime']['replayArchive']['enabled'])
        self.assertEqual(store._db.execute('SELECT COUNT(*) FROM recordings').fetchone()[0], 2)
        self.assertEqual(store._db.execute('SELECT COUNT(*) FROM packets').fetchone()[0], 2)
        store.close()

    def test_archive_failure_is_reported_without_stopping_live_publication(self):
        store = ReplayStore(self.path)
        feed = LiveBattleFeed(archive=store)
        with patch.object(feed, '_get', return_value=[{'opencode': '0x1316', 'content': entry()}]), \
             patch.object(feed.tracker, 'snapshot', return_value={'runtime': {}}), \
             patch.object(store, 'record', side_effect=OSError('disk unavailable')):
            payload = feed.poll_once()
        self.assertIn('disk unavailable', payload['runtime']['replayArchive']['error'])
        self.assertEqual(payload['runtime']['replayArchive']['failedPackets'], 1)
        self.assertIsNotNone(feed.snapshot())
        store.close()

    def test_existing_hud_snapshot_is_preserved_as_unattested_not_training_truth(self):
        store = ReplayStore(self.path)
        payload = {'runtime': {'battleId': 5, 'battleHistory': [{'kind': 'skill_cast', 'round': 9}],
                               'damageEstimate': [{'normal': 999}]}}
        key = store.save_snapshot(payload, source='existing_hud')
        store.save_snapshot(payload, source='existing_hud')
        row = store._db.execute('SELECT payload_json,metadata_json,training_eligible FROM hud_snapshots WHERE snapshot_id=?', (key,)).fetchone()
        self.assertEqual(json.loads(row[0]), payload)
        self.assertTrue(json.loads(row[1])['estimates_are_not_game_truth'])
        self.assertEqual(row[2], 0)
        self.assertEqual(store._db.execute('SELECT COUNT(*) FROM hud_snapshots').fetchone()[0], 1)
        store.close()


class RuleIdentityTests(unittest.TestCase):
    def test_source_identity_is_available_without_training_modules(self):
        from lab.replay_store import rule_identity
        with patch('lab.release_paths.frozen', return_value=False), \
             patch('lab.live_damage._rules', return_value=({'snapshot_id': 'test'}, None)), \
             patch('lab.server._DESKTOP_SOURCE_HASH', 'loaded-helper-source'):
            result = rule_identity()
        self.assertNotIn('identity_error', result)
        identity = result['engine_identity']
        self.assertEqual(identity['source_hash'], 'loaded-helper-source')
        self.assertEqual(identity['ruleset_id'], 'roco-pvp-helper-source-v1')
        self.assertEqual(len(identity['engine_hash']), 64)

    def test_protected_release_keeps_its_own_identity(self):
        from lab.replay_store import rule_identity
        identity = {'release_id': 'protected', 'source_hash': 'compiled-source'}
        with patch('lab.replay_store.build_identity', return_value=identity), \
             patch('lab.live_damage._rules', return_value=({'snapshot_id': 'test'}, None)):
            result = rule_identity()
        self.assertEqual(result['engine_identity'], identity)


if __name__ == '__main__':
    unittest.main()
