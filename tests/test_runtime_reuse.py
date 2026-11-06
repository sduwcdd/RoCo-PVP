"""Static reuse must not outlive its scope or hide source/configuration errors."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import unittest
from unittest.mock import Mock, patch

from lab import trait_runtime as traits
from lab.hud_damage_runtime import make_hud_damage_resolver
from lab.prepared_rules import PreparedRules


class SourceScopeTests(unittest.TestCase):
    def test_nested_scope_reuses_sources_and_next_operation_rechecks(self):
        source = Mock(return_value={'version': 1})

        @traits.cached_source_query
        def load():
            return source()

        with patch.object(traits, '_data', return_value={'skills': []}):
            with traits.query_scope():
                self.assertEqual(load(), {'version': 1})
                with traits.query_scope():
                    self.assertEqual(load(), {'version': 1})
                self.assertEqual(source.call_count, 1)
            source.side_effect = ValueError('changed source')
            with self.assertRaisesRegex(ValueError, 'changed source'):
                with traits.query_scope():
                    load()

    def test_failed_load_is_not_cached_and_scope_is_reset(self):
        calls = []

        @traits.cached_source_query
        def load():
            calls.append(True)
            if len(calls) == 1:
                raise ValueError('bad source')
            return len(calls)

        with patch.object(traits, '_data', return_value={'skills': []}):
            with self.assertRaises(ValueError):
                with traits.query_scope():
                    load()
            self.assertIsNone(traits._QUERY.get())
            with traits.query_scope():
                self.assertEqual(load(), 2)
                self.assertEqual(load(), 2)
            self.assertEqual(load(), 3)

    def test_concurrent_operations_do_not_share_query_cache(self):
        @traits.cached_source_query
        def load():
            return object()

        def operation(_):
            with traits.query_scope():
                first = load()
                self.assertIs(first, load())
                return first

        with patch.object(traits, '_data', return_value={'skills': []}):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first, second = list(pool.map(operation, range(2)))
        self.assertIsNot(first, second)

    def test_real_loss_source_is_verified_again_after_scope_exits(self):
        from lab import victory_rules as victory
        with patch.object(victory, '_loss_source_hash', wraps=victory._loss_source_hash) as verify:
            with traits.query_scope():
                first = victory._loss_data()
                count = verify.call_count
                self.assertGreater(count, 0)
                self.assertIs(first, victory._loss_data())
                self.assertEqual(verify.call_count, count)
        with patch.object(victory, '_loss_source_hash', return_value='changed'):
            with self.assertRaisesRegex(ValueError, 'source changed'):
                with traits.query_scope():
                    victory._loss_data()


class SnapshotReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from lab.server import load_catalog
        cls.catalog = load_catalog()[0]
        cls.prepared = PreparedRules(cls.catalog)

    def test_resolver_is_reused_but_metadata_is_detached_and_mismatch_rejected(self):
        first = make_hud_damage_resolver(self.prepared)
        self.assertIs(first, make_hud_damage_resolver(self.prepared))
        metadata = first.metadata
        metadata['limitations'].clear()
        self.assertTrue(first.metadata['limitations'])
        changed = deepcopy(self.catalog)
        changed['snapshot_id'] += '-invalid'
        with self.assertRaisesRegex(ValueError, 'catalog differs'):
            make_hud_damage_resolver(PreparedRules(changed))

    def test_defense_programs_are_detached_and_owned_source_drift_is_rejected(self):
        from lab import defense_runtime as defense
        first = defense.defense_programs(self.prepared)
        expected = deepcopy(first)
        first[next(iter(first))]['defense_components'].clear()
        self.assertEqual(defense.defense_programs(self.prepared), expected)
        changed = deepcopy(self.catalog)
        changed['moves']['7020780']['desc']['zh'] = 'changed'
        with self.assertRaises(ValueError):
            defense.defense_programs(PreparedRules(changed))


if __name__ == '__main__':
    unittest.main()
