"""Local human observations, kept separate from simulator-generated training data."""
import hashlib
import json
from pathlib import Path
import sqlite3
from threading import RLock
import time

from .release_paths import user_root, build_identity
_USER_ROOT = user_root()
DEFAULT_PATH = (_USER_ROOT / 'replays/human-battles.sqlite3' if _USER_ROOT else
                Path(__file__).resolve().parents[1] / 'data/replays/human-battles.sqlite3')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode('utf8')).hexdigest()


def rule_identity():
    from .pvp_rules import load_pvp_rules
    profile = load_pvp_rules()
    result = {'pvp_profile': profile, 'pvp_profile_hash': _hash(profile),
              'origin': 'human_live_observation', 'training_eligible': False,
              'notice': 'Raw observations are not policy features. Hidden-field filtering and dataset admission are required before training.'}
    try:
        from .live_damage import _rules
        catalog, _ = _rules()
        identity = build_identity()
        if identity is None:
            from .server import _DESKTOP_SOURCE_HASH
            root = Path(__file__).resolve().parents[1]
            rules = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in sorted((root / 'data/rules').rglob('*.json'))}
            basis = {'snapshot_hash': _hash(catalog), 'source_hash': _DESKTOP_SOURCE_HASH,
                     'rules_hash': _hash(rules), 'settings_hash': _hash(profile['settings'])}
            identity = {**basis, 'engine_hash': _hash(basis),
                        'ruleset_id': 'roco-pvp-helper-source-v1'}
        result.update(snapshot_id=catalog['snapshot_id'], engine_identity=identity)
    except Exception as error:
        # Archival remains useful even when the running rules cannot be identified safely.
        result['identity_error'] = f'{type(error).__name__}: {error}'
    return result


class ReplayStore:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._recordings = {}
        self._timeline_cache = {}
        self._identity = None
        self._db = sqlite3.connect(str(self.path), timeout=5, check_same_thread=False)
        self._db.execute('PRAGMA journal_mode=WAL')
        self._db.execute('PRAGMA synchronous=NORMAL')
        self._db.executescript('''
          CREATE TABLE IF NOT EXISTS recordings (
            recording_id TEXT PRIMARY KEY, battle_id TEXT NOT NULL,
            first_seen REAL NOT NULL, last_seen REAL NOT NULL,
            observed_start_round INTEGER, observer INTEGER NOT NULL,
            mode TEXT NOT NULL, finished INTEGER NOT NULL, result_json TEXT,
            rules_json TEXT NOT NULL, quality_json TEXT NOT NULL,
            training_eligible INTEGER NOT NULL DEFAULT 0
          );
          CREATE TABLE IF NOT EXISTS packets (
            id INTEGER PRIMARY KEY, recording_id TEXT NOT NULL,
            packet_key TEXT NOT NULL, received_at REAL NOT NULL,
            relay_event_id TEXT, opcode TEXT NOT NULL, content_json TEXT NOT NULL,
            UNIQUE(recording_id, packet_key)
          );
          CREATE TABLE IF NOT EXISTS timeline (
            recording_id TEXT NOT NULL, event_index INTEGER NOT NULL,
            event_json TEXT NOT NULL, PRIMARY KEY(recording_id, event_index)
          );
          CREATE INDEX IF NOT EXISTS recordings_battle ON recordings(battle_id);
          CREATE TABLE IF NOT EXISTS hud_snapshots (
            snapshot_id TEXT PRIMARY KEY, battle_id TEXT NOT NULL, captured_at REAL NOT NULL,
            payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL,
            training_eligible INTEGER NOT NULL DEFAULT 0
          );
        ''')
        self._db.commit()

    def record(self, tracker, opcode, content, relay_event_id=None):
        from .live_battle import BATTLE_OPCODES, OP_BATTLE_ENTER
        code = f'0x{int(str(opcode), 16):04X}'
        if code not in BATTLE_OPCODES or tracker.battle_id is None:
            return
        reported = content.get('battle_id') or (content.get('init_info') or {}).get('battle_id') or (content.get('state_info') or {}).get('battle_id') or (content.get('settle_info') or {}).get('battle_id')
        if reported is not None and str(reported) != str(tracker.battle_id):
            return
        battle_id = str(tracker.battle_id)
        with self._lock:
            if code == OP_BATTLE_ENTER:
                self._recordings[battle_id] = _hash({'battle_id': battle_id, 'entry': content})
            recording = self._recordings.setdefault(battle_id, _hash({'battle_id': battle_id, 'partial_start': tracker.round}))
            if self._identity is None or code == OP_BATTLE_ENTER:
                self._identity = rule_identity()
            quality = {'schema': 'human-observation-replay-1', 'start_round': tracker.round,
                       'complete_from_start': code == OP_BATTLE_ENTER and tracker._entry_history_complete,
                       'roster_capacity': None if tracker.is_npc_battle else 6,
                       'initial_observed_roster_counts': {str(side): len(team) for side, team in tracker.teams.items()},
                       'raw_packets_may_contain_fields_not_visible_to_a_policy': True}
            now = time.time()
            timeline_updates = {}
            with self._db:
                self._db.execute('''INSERT INTO recordings VALUES (?,?,?,?,?,?,?,?,?,?,?,0)
                    ON CONFLICT(recording_id) DO UPDATE SET last_seen=excluded.last_seen,
                    finished=MAX(recordings.finished,excluded.finished),
                    result_json=COALESCE(excluded.result_json,recordings.result_json)''',
                    (recording, battle_id, now, now, tracker.round, int(tracker.is_observer),
                     'world' if tracker.is_npc_battle else 'pvp', int(tracker.finished),
                     _json(tracker.result) if tracker.result is not None else None,
                     _json(self._identity), _json(quality)))
                key = _hash({'opcode': code, 'event_id': relay_event_id, 'content': content})
                self._db.execute('''INSERT OR IGNORE INTO packets
                    (recording_id,packet_key,received_at,relay_event_id,opcode,content_json) VALUES (?,?,?,?,?,?)''',
                    (recording, key, now, str(relay_event_id) if relay_event_id is not None else None, code, _json(content)))
                for index, event in enumerate(tracker.timeline):
                    value = _json(event)
                    cache_key = (recording, index)
                    if self._timeline_cache.get(cache_key) == value:
                        continue
                    self._db.execute('''INSERT INTO timeline VALUES (?,?,?)
                        ON CONFLICT(recording_id,event_index) DO UPDATE SET event_json=excluded.event_json''',
                        (recording, index, value))
                    timeline_updates[cache_key] = value
            self._timeline_cache.update(timeline_updates)
            return recording

    def load(self, recording_id):
        with self._lock:
            self._db.row_factory = sqlite3.Row
            row = self._db.execute('SELECT * FROM recordings WHERE recording_id=?', (recording_id,)).fetchone()
            if row is None:
                raise ValueError('Replay recording not found')
            result = dict(row)
            result['packets'] = [{'opcode': p[0], 'content': json.loads(p[1])} for p in self._db.execute(
                'SELECT opcode,content_json FROM packets WHERE recording_id=? ORDER BY id', (recording_id,))]
            result['timeline'] = [json.loads(e[0]) for e in self._db.execute(
                'SELECT event_json FROM timeline WHERE recording_id=? ORDER BY event_index', (recording_id,))]
            return result

    def save_snapshot(self, payload, *, source):
        runtime = payload.get('runtime') or {}
        battle_id = runtime.get('battleId') or runtime.get('sessionId')
        history = runtime.get('battleHistory')
        if battle_id is None or not isinstance(history, list):
            raise ValueError('Snapshot has no observed battle history')
        metadata = {'schema': 'human-hud-snapshot-1', 'source': source,
                    'contains_model_estimates': True, 'estimates_are_not_game_truth': True,
                    'running_service_rules_identity': 'unattested', 'training_eligible': False}
        key = _hash(payload)
        with self._lock, self._db:
            self._db.execute('INSERT OR IGNORE INTO hud_snapshots VALUES (?,?,?,?,?,0)',
                             (key, str(battle_id), time.time(), _json(payload), _json(metadata)))
        return key

    def close(self):
        with self._lock:
            self._db.close()
