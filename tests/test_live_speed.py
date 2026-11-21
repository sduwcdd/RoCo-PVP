import copy
import unittest

from lab import battle_data
from lab.live_battle import BattleTracker
from lab.live_damage import _rules
from lab.live_inference import infer_configuration
from lab.live_speed import speed_values
from lab.live_stat_model import stat_candidates


def subject(nature=None):
    return {"petBaseId": 3080, "petId": 401, "level": 60, "nature": nature,
            "effectiveTraitId": 200151, "side": 1, "currentHp": 300, "maxHp": 350,
            "buffs": [], "naturePosOverride": 0, "natureNegOverride": 0,
            "natureOverrideKnown": {"up": True, "down": True}}


def order_event(pet, speed, *, first=True, turn=1):
    ally = {**subject(2), "side": 0, "petId": 1, "battleStats": {"spd": speed}}
    return {"kind": "speed_order", "turn": turn, "form_id": pet["petBaseId"], "subject_level": 60,
            "dimension": "spd", "role": "speed", "subject_first": first, "opponent_speed": [speed, speed],
            "snapshot_id": _rules()[0]["snapshot_id"], "skill_id": 7040370,
            "calculation": {"subject": copy.deepcopy(pet), "opponent": ally}}


def tracker_with_pair(speed=210):
    tracker = BattleTracker()
    race = _rules()[1].form(3080)["stats"]
    hp = stat_candidates(subject(2), race, "hp", 10, "patk", "matk", 5)[0]
    def record(pet_id, enemy):
        return {"battle_inside_pet_info": {"pet_id": pet_id, "base_conf_id": 3080,
                    "conf_id": 3080, "pos": 1, "is_player_enemy": enemy,
                    "battle_attr": [0, hp, 0, 0, 0, 0, 0 if enemy else speed],
                    "skill_round_data": ([{"pos": i+1, "skill_id": sid} for i, sid in enumerate(
                        (7040370, 7060200, 7090400, 7020780))] if enemy else [{"pos": 1, "skill_id": 7040370}])},
                "battle_common_pet_info": {"level": 60, "nature": 2, "energy": 10,
                    "changed_nature_pos_attr_type": 0, "changed_nature_neg_attr_type": 0}}
    tracker.handle_event("0x1316", {"init_info": {"battle_id": 7701,
        "player_team": [{"base": {"role_uin": 1}, "pets": [record(1, False)]}],
        "enemy_team": [{"base": {"role_uin": 2}, "pets": [record(401, True)]}]}})
    return tracker


def command(pet_id, seq, *, turn=1, skill=7040370):
    return {"perform_cmd": {"round": turn, "seq_num": seq, "perform_info": [{"exec_index": 0,
        "type": 1, "cast_moment": 0, "is_group_head": True, "group_ref": 0,
        "skill_cast": {"caster_id": pet_id, "skill_id": skill * 100,
            "skill_name": battle_data.skill_info(skill)["name"], "type": 1}}]}}


class LiveSpeedTests(unittest.TestCase):
    def test_order_can_identify_speed_investment_and_positive_nature(self):
        pet = subject()
        pet.pop("maxHp")
        original = copy.deepcopy(pet)
        result = infer_configuration(pet, [order_event(pet, 240)])
        self.assertEqual(result["status"], "conditional")
        self.assertGreaterEqual(result["panel_ranges"]["spd"][0], 240)
        self.assertTrue(result["known_talents"]["spd"]["selected"])
        self.assertNotIn(0, result["talent_value_options"]["spd"])
        self.assertEqual(result["known_nature"]["up"], "spd")
        self.assertEqual(result["used_speed_observations"], 1)
        self.assertEqual(pet, original)
        rewritten = {**pet, "nature": 2, "natureOverrideKnown": {"up": False, "down": False}}
        inferred = infer_configuration(rewritten, [order_event(rewritten, 240)])
        self.assertEqual(inferred["known_nature"]["up"], "spd")
        self.assertEqual(inferred["nature_source"], "protocol_original_public_order_inference")

    def test_known_neutral_speed_nature_can_identify_investment_alone(self):
        pet = subject(2)
        pet.pop("maxHp")
        result = infer_configuration(pet, [order_event(pet, 210)])
        self.assertEqual(result["panel_ranges"]["spd"], [212, 225])
        self.assertTrue(result["known_talents"]["spd"]["selected"])
        self.assertEqual(result["known_nature"]["up"], "patk")

    def test_same_speed_remains_possible_in_both_orders(self):
        pet = subject(2)
        pet.pop("maxHp")
        result = infer_configuration(pet, [order_event(pet, 209), order_event(pet, 209, first=False, turn=2)])
        self.assertEqual(result["panel_ranges"]["spd"], [209, 209])
        self.assertIn(5, result["talent_value_options"]["spd"])
        self.assertEqual(result["used_speed_observations"], 2)

    def test_conflicting_new_order_does_not_erase_prior_evidence(self):
        pet = subject(2)
        pet.pop("maxHp")
        first = order_event(pet, 210)
        before = infer_configuration(pet, [first])
        after = infer_configuration(pet, [first, order_event(pet, 9999, turn=2)])
        self.assertEqual(after["status"], "damage_conflict")
        self.assertEqual(after["panel_ranges"], before["panel_ranges"])
        self.assertEqual(after["used_speed_observations"], 1)
        self.assertEqual(after["damage_conflicts"][0]["kind"], "speed_order")

    def test_reported_speed_is_not_buffed_twice_and_flat_candidates_are_supported(self):
        pet, ally = subject(2), subject(2)
        buff = {"id": 20010011, "layers": 2}
        pet.update(battleStats={"spd": 311}, battleBuffs=[buff])
        self.assertEqual(speed_values(pet, ally), [311])
        pet["battleBuffs"] = [{"id": 20010100, "layers": 2}]
        self.assertEqual(speed_values(pet, ally, 200), [220])

    def test_cross_packet_order_updates_radar_and_survives_refresh(self):
        tracker = tracker_with_pair()
        tracker.handle_event("0x1324", command(401, 10))
        self.assertEqual(tracker.speed_order.evidence, {})
        tracker._pet_by_id["401"].nature_override_known["up"] = False
        self.assertTrue(tracker.speed_order.state["initial"][1]["natureOverrideKnown"]["up"])
        tracker._pet_by_id["401"].nature_override_known["up"] = True
        tracker.handle_event("0x1324", command(1, 11))
        self.assertNotIn("blocker", tracker.speed_order.state)
        evidence = tracker.speed_order.evidence["401"]
        self.assertEqual(len(evidence), 1)
        self.assertIsNone(evidence[0]["calculation"]["subject"]["carriedSkillIds"])
        self.assertEqual(evidence[0]["calculation"]["subject"]["moves"], [])
        first = tracker.snapshot()["runtime"]["enemyTeam"][0]
        self.assertEqual(first["configurationInference"]["used_speed_observations"], 1)
        self.assertEqual(first["panelStatRanges"]["spd"], [212, 225])
        tracker.handle_event("0x131A", {"state_info": {"round": 2}})
        later = tracker.snapshot()["runtime"]["enemyTeam"][0]
        self.assertEqual(later["panelStatRanges"]["spd"], first["panelStatRanges"]["spd"])
        tracker.handle_event("0x1316", {"init_info": {"battle_id": 7702}})
        self.assertEqual(tracker.speed_order.evidence, {})

    def test_unsafe_rounds_do_not_produce_speed_constraints(self):
        for case in ("indices", "seq", "counter", "passive", "priority", "switch", "unknown_buff", "percent",
                     "combo", "interrupted", "resonance"):
            with self.subTest(case=case):
                tracker = tracker_with_pair()
                first, second = command(401, 10), command(1, 11)
                item = first["perform_cmd"]["perform_info"][0]
                if case == "indices":
                    item.pop("exec_index")
                elif case == "seq":
                    second["perform_cmd"]["seq_num"] = 9
                elif case in ("counter", "passive"):
                    item["skill_cast"]["type"] = 3 if case == "counter" else 2
                elif case == "priority":
                    second = command(1, 11, skill=7020970)
                elif case == "switch":
                    item["change_pet"] = {"battle_pet_id": 1}
                elif case == "unknown_buff":
                    tracker._pet_by_id["401"].buffs = [{"id": 99999999, "layers": 1}]
                elif case == "percent":
                    tracker._pet_by_id["401"].buffs = [{"id": 20010011, "layers": 1}]
                elif case == "combo":
                    item["combo_skill_cast"] = {"skill_id": 704037000}
                elif case == "interrupted":
                    item["skill_cast"]["is_interupt"] = True
                else:
                    item["skill_cast"]["resonance_pet_id"] = 3
                tracker.handle_event("0x1324", first)
                tracker.handle_event("0x1324", second)
                self.assertEqual(tracker.speed_order.evidence, {})
                self.assertIn("blocker", tracker.speed_order.state)

    def test_environment_headers_without_main_actions_do_not_poison_order(self):
        tracker = tracker_with_pair()
        for pet in tracker._pet_by_id.values():
            pet.buffs = [{"id": 20170880, "layers": 1}]
        tracker.handle_event("0x131A", {"state_info": {"round": 1}, "perform_cmd": {
            "seq_num": 0, "perform_info": [{"exec_index": 0}, {"exec_index": 0}]}})
        tracker.handle_event("0x1324", command(401, 10))
        tracker.handle_event("0x1324", command(1, 11))
        self.assertEqual(len(tracker.speed_order.evidence["401"]), 1)

    def test_indexed_wire_groups_are_ordered_and_round_start_repeats_are_deduplicated(self):
        tracker = tracker_with_pair()
        enemy = command(401, 10)["perform_cmd"]["perform_info"][0]
        ally = command(1, 10)["perform_cmd"]["perform_info"][0]
        ally["exec_index"] = 1
        cmd = {"round": 1, "seq_num": 10, "perform_info": [ally, enemy]}
        tracker.handle_event("0x131A", {"state_info": {"round": 1}, "perform_cmd": copy.deepcopy(cmd)})
        tracker.handle_event("0x1324", {"perform_cmd": copy.deepcopy(cmd)})
        evidence = tracker.speed_order.evidence["401"]
        self.assertEqual(len(evidence), 1)
        self.assertTrue(evidence[0]["subject_first"])

    def test_repeated_identical_perform_packets_do_not_retract_a_valid_order(self):
        tracker = tracker_with_pair()
        for packet in (command(401, 10), command(401, 10), command(1, 11), command(1, 11)):
            tracker.handle_event("0x1324", packet)
        self.assertEqual(len(tracker.speed_order.evidence["401"]), 1)
        self.assertNotIn("blocker", tracker.speed_order.state)

    def test_midturn_speed_change_and_late_extra_cast_retract_only_current_round(self):
        tracker = tracker_with_pair()
        tracker.handle_event("0x1324", command(401, 10))
        tracker._pet_by_id["401"].buffs = [{"id": 20010100, "layers": 1}]
        tracker.handle_event("0x1324", command(1, 11))
        self.assertEqual(tracker.speed_order.evidence, {})
        tracker._pet_by_id["401"].buffs = []
        tracker.handle_event("0x1324", command(401, 20, turn=2))
        tracker.handle_event("0x1324", command(1, 21, turn=2))
        self.assertEqual(len(tracker.speed_order.evidence["401"]), 1)
        tracker.handle_event("0x1324", command(401, 22, turn=2))
        self.assertEqual(tracker.speed_order.evidence["401"], [])


if __name__ == "__main__":
    unittest.main()
