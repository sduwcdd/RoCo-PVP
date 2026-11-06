"""Audit labels cannot be confused with parsing or execution claims."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from lab.mechanism_audit import audit_catalog, inventory_record, markdown_report
from lab.server import load_catalog


class MechanismAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()[0]
        root = Path(__file__).resolve().parents[1]
        cls.baseline = json.loads((root / 'data' / 'rules' / cls.catalog['snapshot_id'] / 'bwiki-declarative-6.json').read_text(encoding='utf-8'))
        cls.report = audit_catalog(cls.catalog, cls.baseline)

    def inventory(self, text):
        return inventory_record({'id': 1, 'name': {'zh': '构造'}, 'desc': {'zh': text}})

    def test_all_records_accounted_and_originals_retained(self):
        self.assertEqual(self.report['total'], {'skill': 579, 'trait': 246})
        self.assertEqual(len(self.report['records']), 825)
        self.assertEqual(self.report['baseline_structured'], {'skill': 172, 'trait': 0})
        for row in self.report['records']:
            original = self.catalog['moves' if row['category'] == 'skill' else 'traits'][str(row['game_id'])]
            self.assertEqual(row['source_description'], original['desc']['zh'])
            self.assertEqual(row['source_evidence']['content_sha256'], self.catalog['provenance']['Skills']['content_sha256'])
            fragments = {x['field']: x['text'] for x in row['source_text_fragments']}
            for match in row['matches']:
                for span in match['spans']:
                    self.assertEqual(fragments[span['field']][span['start']:span['end']], span['text'])

    def test_priority_response_order_and_entry_are_distinct(self):
        row = self.inventory('先手度+1，先手时回复能量，后手时减伤，应对攻击，主动入场后迅捷。')
        names = {m['mechanism'] for m in row['matches']}
        self.assertTrue({'priority', 'condition_first', 'condition_last', 'response_success', 'trigger_entry', 'swift'} <= names)
        only_priority = {m['mechanism'] for m in self.inventory('先手度+1。')['matches']}
        self.assertIn('priority', only_priority)
        self.assertNotIn('condition_first', only_priority)
        shorthand = {m['mechanism'] for m in self.inventory('本技能先手-1。')['matches']}
        self.assertIn('priority', shorthand)
        self.assertNotIn('condition_first', shorthand)

    def test_negation_and_history_remain_candidates_not_rules(self):
        row = self.inventory('不能获得迅捷，重复释放此前的迅捷技能。未知后缀不可删。')
        self.assertFalse(row['description_completely_parsed_by_inventory'])
        self.assertTrue(row['unparsed_source_preserved'])
        self.assertTrue(row['source_description'].endswith('未知后缀不可删。'))
        self.assertTrue(all(m['classification'] == 'lexical_review_candidate' for m in row['matches']))

    def test_duplicate_mentions_count_once_and_overlaps_not_summed(self):
        row = self.inventory('迅捷，迅捷，先手度+1。')
        swift = next(m for m in row['matches'] if m['mechanism'] == 'swift')
        self.assertEqual(len(swift['spans']), 2)
        for metric in self.report['mechanisms']:
            for category, ids in metric['candidate_ids'].items():
                self.assertEqual(len(ids), len(set(ids)))
                self.assertEqual(metric['candidate_counts'][category], len(ids))
            self.assertIsNone(metric['exclusive_unlock_count'])

    def test_stale_or_duplicate_source_cannot_be_hidden(self):
        for mutate in (lambda c: c['moves']['7020360']['desc'].update(zh='changed'),
                       lambda c: c.update(snapshot_id='unknown'),
                       lambda c: c.update(moves=list(c['moves'].values()) + [c['moves']['7020360']])):
            c = deepcopy(self.catalog)
            mutate(c)
            with self.assertRaises(ValueError):
                audit_catalog(c, self.baseline)

    def test_deterministic_detached_output_and_no_executable_claims(self):
        again = audit_catalog(self.catalog, self.baseline)
        self.assertEqual(again, self.report)
        again['records'][0]['source_evidence']['content_sha256'] = 'mutated'
        self.assertNotEqual(again['records'][0], self.report['records'][0])
        self.assertFalse(self.report['full_battle_executable'])
        self.assertFalse(self.report['real_game_calibrated'])
        self.assertIn('不可直接求和', markdown_report(self.report))

    def test_all_named_terms_are_audited_without_invocation_inference(self):
        self.assertEqual(len(self.report['terms']), 54)
        replay = next(r for r in self.report['records'] if r['category'] == 'skill' and r['game_id'] == 7150320)
        swift = next(m for m in replay['term_mentions'] if m['term_id'] == 1005)
        self.assertFalse(swift['meaning_resolved'])
        self.assertTrue(swift['spans'])
        for row in self.report['terms']:
            self.assertEqual(row['source']['content_sha256'], self.catalog['provenance']['Terms']['content_sha256'])

    def test_detail_text_leaves_have_own_paths_and_are_not_joined_into_clauses(self):
        row = inventory_record({'id': 1, 'name': {'zh': '构造'}, 'desc': {'zh': '详情见表。'},
                                'effect_details': {'first': '敌方失去', 'second': '3能量', 'third': '冷却2回合'}})
        names = {m['mechanism'] for m in row['matches']}
        self.assertNotIn('energy_reduce', names)
        cooldown = next(m for m in row['matches'] if m['mechanism'] == 'cooldown')
        self.assertEqual(cooldown['spans'][0]['field'], 'effect_details/third')


if __name__ == '__main__':
    unittest.main()
