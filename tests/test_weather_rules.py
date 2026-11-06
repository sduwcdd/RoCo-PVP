"""Regression evidence for weather identity, parameters, and provenance gates."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lab import weather_rules as wr


class WeatherRuleTests(unittest.TestCase):
    def test_reviewed_sources_and_all_weather_ids(self):
        rules = wr.get_weather_rules()
        self.assertEqual([], wr.verify_weather_sources())
        self.assertEqual({'rain':3, 'sandstorm':6, 'blizzard':5, 'thunder':14},
                         {k:v['weather_id'] for k,v in rules['weather'].items()})
        self.assertEqual({8}, {v['duration'] for v in rules['weather'].values()})
        global_config = json.loads((wr.ROOT / 'artifacts/unpack_probe_20261025/battle_analysis/tables/parsed/BATTLE_GLOBAL_CONFIG.json').read_text(encoding='utf-8'))
        self.assertEqual(8, global_config['weather_duration']['num'])

    def test_actual_weather_not_names_or_pokemon_assumptions(self):
        rules = wr.get_weather_rules()
        self.assertNotIn('7090110', rules['setters'])  # 暴风雪 is an attack.
        self.assertNotIn('7060240', rules['setters'])  # 放晴 is a power buff.
        self.assertEqual('blizzard', rules['setters']['7090370']['weather'])
        self.assertEqual(1.75, rules['weather']['rain']['effects'][0]['value'])
        sand = rules['weather']['sandstorm']['effects']
        self.assertEqual(['energy_multiplier'], [e['op'] for e in sand])
        self.assertEqual(.5, sand[0]['value'])
        self.assertEqual('地系', sand[0]['when']['skill_type'])

    def test_weather_chains_preserve_repeated_status_reference(self):
        deps = json.loads((wr.ROOT / 'artifacts/weather_rules_20261025/dependency_records.json').read_text(encoding='utf-8'))
        snow = deps['BUFFBASE_CONF']['2017123']
        self.assertEqual(7, snow['trigger_type'])
        self.assertEqual([20580010, 20580010], snow['buffbase_param'][0]['params'])
        thunder = deps['BUFFBASE_CONF']['2017342']
        self.assertEqual([20011586], thunder['buffbase_param'][0]['params'])
        rules = wr.get_weather_rules()
        self.assertEqual(2, rules['weather']['blizzard']['effects'][0]['value'])
        self.assertEqual(['冰系'], rules['weather']['blizzard']['effects'][0]['when']['exclude_target_types'])
        self.assertEqual(['电系'], rules['weather']['thunder']['effects'][0]['when']['exclude_target_types'])

    def test_current_description_and_historical_numeric_evidence_coexist(self):
        root = wr.ROOT/'artifacts/weather_rules_20261025/parsed'
        historical = json.loads((root/'pakchunk4-WindowsNoEditor_2_P/WEATHER_CONF.json').read_text(encoding='utf-8'))
        current = json.loads((root/'pakchunk4-WindowsNoEditor_3_P/WEATHER_CONF.json').read_text(encoding='utf-8'))
        for wid in ['3','5','6','14']:
            self.assertIn('weather_buff', historical[wid])
            self.assertNotIn('weather_buff', current[wid])
            self.assertEqual(historical[wid]['desc_for_battle']['text'], current[wid]['desc_for_battle']['text'])
        manifest=json.loads((wr.ROOT/'artifacts/weather_rules_20261025/manifest.json').read_text(encoding='utf-8'))
        self.assertTrue(all(r['stat_unchanged'] and r['source_ranges_unchanged'] for r in manifest))

    def test_all_catalog_weather_descriptions_have_configurations(self):
        rules = wr.get_weather_rules()
        self.assertEqual(9, len(rules['coverage']['skills']))
        self.assertEqual(5, len(rules['coverage']['traits']))
        self.assertEqual(14, len(rules['coverage']['forms']))
        self.assertTrue(all(x['configured'] for section in ['skills','traits'] for x in rules['coverage'][section]))
        self.assertEqual(-2, rules['skill_modifiers']['7050490'][0]['value'])
        self.assertEqual(8, rules['skill_modifiers']['7050530'][0]['response_success_value'])
        self.assertEqual(1, rules['skill_modifiers']['7080450'][0]['value'])
        self.assertEqual(50, rules['skill_modifiers']['7090460'][0]['value'])
        self.assertEqual(50, rules['trait_modifiers']['200298'][0]['value'])

    def test_unreviewed_rule_file_blocks_loading(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'rules.json'
            path.write_text('{}',encoding='utf-8')
            with patch.object(wr,'RULES_PATH',path):
                with self.assertRaisesRegex(wr.WeatherRulesError,'reviewed hash'):
                    wr.get_weather_rules()

    def test_changed_evidence_blocks_default_loading(self):
        with patch.object(wr,'verify_weather_sources',return_value=['changed-artifact.json']):
            with self.assertRaisesRegex(wr.WeatherRulesError,'changed-artifact'):
                wr.get_weather_rules()

    def test_static_validation_rejects_unknown_opcode_and_invalid_ratio(self):
        for key,value in [('op','unreviewed_damage'),('value',float('nan')),('value',-1)]:
            rules=wr.get_weather_rules()
            rules['weather']['rain']['effects'][0][key]=value
            with self.assertRaises(wr.WeatherRulesError):wr.validate_weather_rules(rules)

    def test_callers_do_not_share_mutable_state_or_hide_version_drift(self):
        rules=wr.get_weather_rules({'snapshot_id':'different'})
        self.assertIn('catalog_version_mismatch',[u['id'] for u in rules['uncertainties']])
        rules['weather']['rain']['duration']=99
        fresh=wr.get_weather_rules()
        self.assertEqual(8,fresh['weather']['rain']['duration'])
        self.assertFalse(fresh['formal_training_eligible'])
        self.assertFalse(fresh['server_semantics_verified'])
        self.assertTrue(fresh['uncertainties'])


if __name__=='__main__':unittest.main()
