"""Real model-change records and explicit evolution-edge regressions."""
import json
from copy import deepcopy
from pathlib import Path
import unittest

from lab import battle_data
from lab.live_battle import BattleTracker, _Pet
from lab.live_damage import _effective_base

FIXTURE = Path(__file__).resolve().parents[1] / "data/reference/live-boss-forms-20261029.json"


class LiveFormTests(unittest.TestCase):
    def test_real_boss_and_cute_records_update_both_sides_without_double_lowering(self):
        events = json.loads(FIXTURE.read_text(encoding="utf-8"))["events"]
        initial = {e["pet_info"]["battle_inside_pet_info"]["pet_id"]: e["pet_info"]
                   for e in events if e["phase"] == "initial"}
        tracker = BattleTracker()
        tracker.handle_event("0x1316", {"init_info": {"battle_id": 1,
            "player_team": [{"pets": [deepcopy(initial[4])]}],
            "enemy_team": [{"pets": [deepcopy(initial[401])]}]}})
        for event in events:
            if event["phase"] != "change_model":
                continue
            info = deepcopy(event["pet_info"])
            inside = info["battle_inside_pet_info"]
            pid = inside["pet_id"]
            tracker._apply_perform_item({"type": 24, "change_model": {
                "pet_id": pid, "old_base_id": event["old_base_id"], "pet_info": info}})
            pet = tracker._pet_by_id[str(pid)]
            payload = pet.to_payload(hide_unobserved=pet.side == 1, observed={})
            self.assertEqual(payload["petBaseId"], inside["base_conf_id"])
            self.assertEqual(_effective_base(payload), inside["base_conf_id"])
            if inside["base_conf_id"] == 5013:
                self.assertEqual(payload["name"], "雪影冰灵")
            if pid == 4 and inside["base_conf_id"] == 3123:
                self.assertEqual((payload["name"], payload["cuteStacks"], payload["effectiveTraitId"]),
                                 ("雪影娃娃", 1, 280012))
                tracker._on_round_start({"pet_infos": [info]})
                self.assertEqual(pet.display_name(), "雪影娃娃")
        self.assertEqual(len([e for e in tracker.timeline if e["kind"] == "form_change"]), 3)

    def test_all_65_published_bosses_follow_explicit_predecessors(self):
        rows = json.loads(FIXTURE.read_text(encoding="utf-8"))["published_boss_audit"]
        self.assertEqual(len(rows), 65)
        for row in rows:
            with self.subTest(boss=row["boss_id"]):
                self.assertEqual(battle_data.lower_stage_form(row["boss_id"], 1)["base_conf_id"], row["predecessor"])
                self.assertEqual(battle_data.lower_stage_form(row["boss_id"], 2)["base_conf_id"], row["second_predecessor"])
                pet = _Pet(side=0, roster_index=0, inside={"pet_id": 1, "base_conf_id": row["predecessor"]}, common={"level": 60})
                pet.refresh_stats({"base_conf_id": row["boss_id"], "cur_passive_skill": 0}, {})
                self.assertEqual(pet.display_name(), row["name"])
                pet.set_buff(21020040, 1)
                self.assertEqual(pet.lowered_form()["base_conf_id"], row["predecessor"])
                pet.refresh_stats({"base_conf_id": row["predecessor"], "buffs": [{"buff_id": 21020040, "stack": 1}]}, {})
                self.assertEqual(_effective_base(pet.to_payload(hide_unobserved=False, observed={})), row["predecessor"])

    def test_reported_cute_form_is_authoritative_and_normal_chain_avoids_sleep_branch(self):
        pet = _Pet(side=0, roster_index=0, inside={"pet_id": 4, "base_conf_id": 3123,
            "cur_passive_skill": 280012, "buffs": [{"buff_id": 21020040, "stack": 1}]}, common={"level": 60})
        self.assertEqual(pet.display_name(), "雪影娃娃")
        self.assertEqual(battle_data.lower_stage_form(3123, 1)["base_conf_id"], 3122)
        self.assertEqual(battle_data.lower_stage_form(3123, 2)["base_conf_id"], 3121)
        self.assertEqual(battle_data.lower_stage_form(3746, 1), {})

    def test_model_change_clears_old_panels_and_refreshes_slots_and_energy_cap(self):
        pet = _Pet(side=0, roster_index=0, inside={"pet_id": 4, "base_conf_id": 3123,
            "battle_attr": [0, 400, 100, 100, 100, 100, 100]}, common={"level": 60})
        pet.refresh_stats({"base_conf_id": 5013, "max_energy": 12, "battle_attr": [0, 500, 0, 0, 0, 0, 0],
            "skill_round_data": [{"pos": 1, "skill_id": 7700009}]}, {})
        self.assertEqual(pet.base_conf_id, 5013)
        self.assertNotIn("phyAtk", pet.revealed_base_stats)
        self.assertEqual(pet.attr_stats["phyAtk"], 0)
        self.assertEqual(pet.max_energy, 12)
        self.assertEqual(pet.skills[0]["skillId"], 7700009)

    def test_magic_burst_freezes_pre_payment_energy_for_actual_hit_context(self):
        def record(pid):
            return {"battle_inside_pet_info": {"pet_id": pid, "base_conf_id": 3001,
                "battle_attr": [0, 400, 200, 200, 100, 100, 100]}, "battle_common_pet_info": {"level": 60, "energy": 8}}
        tracker = BattleTracker()
        tracker.handle_event("0x1316", {"init_info": {"battle_id": 1,
            "player_team": [{"pets": [record(1)]}], "enemy_team": [{"pets": [record(401)]}]}})
        tracker._on_perform({"perform_cmd": {"round": 1, "perform_info": [
            {"type": 1, "exec_index": 1, "skill_cast": {"caster_id": 1, "skill_id": 702055000, "skill_name": "魔能爆"},
             "sync_data": {"pet_sync_info": [{"pet_id": 1, "energy_result": 0}]}},
            {"type": 4, "exec_index": 2, "damage_info": {"caster_id": 1, "target_id": 401, "source_id": 702055000},
             "sync_data": {"pet_sync_info": [{"pet_id": 401, "original_damage": 100, "damage_result": 100}]}}]}})
        attacker = tracker.damage_evidence["401"][0]["calculation"]["attacker"]
        self.assertEqual((attacker["energy"], attacker["energyBeforeCast"]), (0, 8))


if __name__ == "__main__":
    unittest.main()
