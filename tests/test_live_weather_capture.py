import unittest

from lab.live_battle import BattleTracker
from lab.live_damage import estimate_moves
from tests.test_live_battle import pet_record


class CapturedWeatherTests(unittest.TestCase):
    def tracker(self, **weather):
        tracker = BattleTracker()
        mine = pet_record(1, 3343)
        mine['battle_inside_pet_info'].update(pos=1, skill_round_data=[{'pos': 1, 'skill_id': 7090230}])
        mine['battle_inside_pet_info']['battle_attr'] = [0, 400, 200, 200, 100, 100, 200]
        enemy = pet_record(401, 3001, enemy=True)
        enemy['battle_inside_pet_info'].update(pos=1, battle_attr=[0, 400, 200, 200, 100, 100, 200])
        tracker.handle_event('0x1316', {'round': 7, **weather, 'init_info': {'battle_id': 8401,
            'observe_battle': {'is_observer': True},
            'player_team': [{'pets': [mine]}], 'enemy_team': [{'pets': [enemy]}]}})
        return tracker

    def power(self, tracker):
        a = tracker._pet_by_id['1'].to_payload(hide_unobserved=False, observed={})
        b = tracker._pet_by_id['401'].to_payload(hide_unobserved=True, observed={})
        a['liveContext'] = {'turn': tracker.round, 'weather': tracker.live_weather, 'weatherId': tracker.weather_id}
        return estimate_moves(a, b)[0]['effects'][0]['power_range']

    def test_midbattle_enter_reads_authoritative_weather_and_doubles_ice_only_once(self):
        tracker = self.tracker(weather_id=5, weather_expire_round=9)
        self.assertEqual(tracker.live_weather['remaining_rounds'], 3)
        self.assertEqual(self.power(tracker), [80, 80])
        tracker._pet_by_id['1'].set_buff(20231260, 1)
        self.assertEqual(self.power(tracker), [80, 80])
        tracker.handle_event('0x1324', {'perform_cmd': {'round': 7, 'perform_info': [
            {'weather_change': {'weather_id': 0}}]}})
        self.assertIsNone(tracker.live_weather)
        self.assertEqual(self.power(tracker), [40, 40])

    def test_same_weather_partial_refresh_preserves_the_reported_expiry(self):
        tracker = self.tracker(weather_id=5, weather_expire_round=9)
        tracker.handle_event('0x1324', {'perform_cmd': {'round': 8, 'perform_info': [
            {'weather_change': {'weather_id': 5}}]}})
        self.assertEqual(tracker.live_weather['remaining_rounds'], 2)
        tracker.handle_event('0x1324', {'perform_cmd': {'round': 10, 'perform_info': []}})
        self.assertIsNone(tracker.live_weather)
        self.assertEqual(self.power(tracker), [40, 40])

    def test_unknown_expiry_is_not_pretended_to_be_a_one_turn_weather(self):
        tracker = self.tracker(weather_id=5)
        tracker._pet_by_id['1'].set_buff(20231260, 1)
        self.assertIsNone(tracker.live_weather['source']['weather_expire_round'])
        tracker.handle_event('0x131A', {'state_info': {'round': 8}})
        self.assertIsNone(tracker.live_weather)
        self.assertIsNone(tracker.weather_id)
        self.assertEqual(self.power(tracker), [80, 80])


if __name__ == '__main__':
    unittest.main()
