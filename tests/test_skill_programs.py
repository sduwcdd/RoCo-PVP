"""Declarative coverage is not real-game calibration or executable support."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from lab.skill_programs import COMPILER_VERSION, compile_skill, compile_catalog


def skill(desc="造成物伤，自己回复1能量。", kind="physical", **changes):
    result = {"id": 7020360, "name": {"zh": "测试"}, "desc": {"zh": desc}, "kind": kind,
              "energy": 0, "type": "普通系", "power": 35}
    result.update(changes)
    return result


class SkillProgramTests(unittest.TestCase):
    def test_plain_damage_and_energy_order_and_current_values(self):
        r = compile_skill(skill())
        self.assertEqual(r["status"], "compiled")
        self.assertEqual([op["op"] for op in r["operations"]], ["damage", "energy.restore"])
        self.assertEqual(r["operations"][0]["params"]["power"], 35)
        self.assertEqual(r["operations"][1]["params"]["amount"], 1)
        self.assertFalse(r["executable"])
        self.assertFalse(r["real_game_verified"])
        self.assertIn("not_validated_timing", r["order_semantics"])

    def test_full_physical_and_magical_names(self):
        for word, kind in (("物理", "physical"), ("魔法", "magical")):
            r = compile_skill(skill(f"对敌方精灵造成{word}伤害。", kind, power=110))
            self.assertEqual(r["status"], "compiled")
            self.assertEqual(r["operations"][0]["params"]["kind"], kind)

    def test_kind_conflict_cannot_emit_plausible_damage(self):
        r = compile_skill(skill("造成魔伤。", "physical"))
        self.assertIn("description_kind_conflict", r["blockers"])
        self.assertEqual(r["operations"], [])

    def test_extra_conditions_cannot_be_dropped(self):
        for description in ("造成物伤。每次使用后，本技能威力永久+45。", "造成物伤，自己回复1能量，应对防御：能量翻倍。", "造成物伤，3连击，若敌方换人则连击数+1。", "蓄力，对敌方精灵造成物理伤害。", "造成物伤。 ", "造成物伤。\n"):
            with self.subTest(description=description):
                r = compile_skill(skill(description))
                self.assertEqual(r["status"], "unsupported")
                self.assertEqual(r["operations"], [])

    def test_stat_percentage_is_fraction_and_does_not_assume_stacking(self):
        r = compile_skill(skill("自己获得物攻和魔攻+140%。", "status"))
        self.assertEqual(r["operations"][0]["params"], {"target": "self", "attributes": ["patk", "matk"], "percent": {"numerator": 140, "denominator": 100}})
        r = compile_skill(skill("敌方获得速度-10%。", "status"))
        self.assertEqual(r["operations"][0]["params"]["percent"]["numerator"], -10)
        self.assertEqual(compile_skill(skill("自己获得物攻和物攻+100%。", "status"))["status"], "unsupported")

    def test_status_stacks_do_not_invent_tick_or_rounding_rules(self):
        r = compile_skill(skill("敌方获得4层冻结。", "status"))
        self.assertEqual(r["operations"], [{"op": "status.add", "params": {"target": "opponent", "status": "freeze", "stacks": 4}}])
        self.assertFalse(r["executable"])
        self.assertNotIn("damage", str(r["operations"]))

    def test_defense_is_declarative_not_an_assumed_cooldown_or_order(self):
        r = compile_skill(skill("减伤70%，应对攻击。", "defense"))
        self.assertEqual(r["operations"][0]["params"]["reduction"], {"numerator": 70, "denominator": 100})
        self.assertFalse(r["executable"])
        self.assertEqual(compile_skill(skill("减伤101%，应对攻击。", "defense"))["operations"], [])

    def test_unknown_notes_and_details_block_even_recognizable_sentences(self):
        for extra in ({"desc_notes": [9999]}, {"desc_notes": [1015]}, {"desc_notes": "额外触发"}, {"effect_details": {"zh": "还有隐藏的触发"}}):
            r = compile_skill(skill("减伤70%，应对攻击。", "defense", **extra))
            self.assertEqual(r["status"], "unsupported")
            self.assertEqual(r["operations"], [])
            self.assertEqual(r["source_details"], extra)

    def test_recognized_notes_remain_explicit_unresolved_execution_dependencies(self):
        r = compile_skill(skill("减伤70%，应对攻击。", "defense", desc_notes=[1016]))
        self.assertEqual(r["status"], "compiled")
        self.assertEqual(r["dependency_ids"], [1016])
        self.assertEqual(r["source_details"]["desc_notes"], [1016])
        self.assertFalse(r["executable"])
        self.assertTrue(any("关联术语" in reason for reason in r["execution_blockers"]))
        r = compile_skill(skill("敌方获得4层冻结。", "status", desc_notes=[1002]))
        self.assertEqual(r["status"], "unsupported")
        self.assertEqual(r["operations"], [])

    def test_missing_fixed_numeric_data_never_uses_legacy_default(self):
        for changes in ({"power": None}, {"power": 0}, {"power": True}, {"energy": None}, {"energy": -1}, {"id": None}, {"type": ""}):
            self.assertEqual(compile_skill(skill(**changes))["status"], "unsupported")

    def test_source_identity_changes_on_any_added_detail_and_has_no_alias_mutation(self):
        original = skill(desc_notes=[1001])
        before = deepcopy(original)
        r = compile_skill(original)
        self.assertEqual(original, before)
        r["source_details"]["desc_notes"].append(1002)
        self.assertEqual(original, before)
        changed = deepcopy(original)
        changed["desc_notes"].append(1002)
        self.assertNotEqual(compile_skill(original)["source_hash"], compile_skill(changed)["source_hash"])

    def test_catalog_traits_are_explicitly_unimplemented_not_inferred_empty(self):
        catalog = {"snapshot_id": "synthetic", "moves": [skill()], "traits": [{"id": 123, "name": {"zh": "无事发生"}, "desc": {"zh": "无效果。"}}]}
        r = compile_catalog(catalog)
        self.assertEqual(r["counts"]["traits"]["unsupported"], 1)
        self.assertEqual(r["traits"]["123"]["operations"], [])
        self.assertFalse(r["training_allowed"])
        self.assertEqual(json.loads(json.dumps(r))["skills"]["7020360"]["status"], "compiled")
        with self.assertRaises(ValueError):
            compile_catalog({**catalog, "moves": [skill(), skill()]})

    def test_current_snapshot_every_game_id_is_accounted_for(self):
        from lab.server import load_catalog
        catalog = load_catalog()[0]
        r = compile_catalog(catalog)
        self.assertEqual(set(r["skills"]), {str(x["id"]) for x in catalog["moves"].values()})
        self.assertEqual(set(r["traits"]), {str(x["id"]) for x in catalog["traits"].values()})
        self.assertEqual(r["counts"]["skills"]["total"], 579)
        self.assertEqual(r["counts"]["traits"]["unsupported"], 246)
        self.assertEqual(r["skills"]["7020360"]["operations"][1]["params"]["amount"], 1)
        self.assertEqual(r["skills"]["7020440"]["operations"][0]["op"], "damage.conditional")
        self.assertEqual(r["skills"]["7020780"]["dependency_ids"], [1016])
        self.assertEqual(r["skills"]["7020780"]["snapshot_id"], catalog["snapshot_id"])
        self.assertEqual(r["skills"]["7020780"]["term_source"], catalog["provenance"]["Terms"])
        self.assertTrue(all(not v["executable"] and not v["real_game_verified"] for v in r["skills"].values()))


class CompoundSkillProgramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from lab.server import load_catalog
        cls.catalog = load_catalog()[0]
        cls.programs = compile_catalog(cls.catalog)

    def program(self, game_id):
        return self.programs["skills"][str(game_id)]

    def test_real_healing_preserves_percentage_without_inventing_its_basis(self):
        p = self.program(7020640)  # 休息回复
        self.assertEqual(p["operations"], [{"op": "hp.restore", "params": {
            "target": "self", "percent": {"numerator": 30, "denominator": 100}}}])
        self.assertEqual(p["source_description"], "自己回复30%生命。")
        self.assertTrue(any("百分比基数" in text for text in p["execution_blockers"]))
        self.assertNotIn("max_hp", str(p["operations"]))
        self.assertFalse(p["executable"])

    def test_real_recovery_and_stat_compounds_retain_every_operation_in_source_order(self):
        p = self.program(7030240)  # 根吸收
        self.assertEqual([o["op"] for o in p["operations"]], ["hp.restore", "energy.restore"])
        self.assertEqual(p["operations"][0]["params"]["percent"], {"numerator": 15, "denominator": 100})
        self.assertEqual(p["operations"][1]["params"]["amount"], 4)
        p = self.program(7030250)  # 氧输送
        self.assertEqual([o["op"] for o in p["operations"]], ["energy.restore", "stat.modify"])
        self.assertEqual(p["operations"][1]["params"], {
            "target": "self", "attributes": ["matk"], "percent": {"numerator": 70, "denominator": 100}})
        p = self.program(7030590)  # 丰收
        self.assertEqual([o["op"] for o in p["operations"]], ["damage", "hp.restore"])
        self.assertEqual(p["operations"][0]["params"]["power"], 85)
        self.assertEqual(p["operations"][1]["params"]["percent"]["numerator"], 20)

    def test_real_damage_status_compounds_preserve_dependencies_and_attack_kind(self):
        cases = [(7040400, "magical", "burn", 6, 1002),
                 (7040630, "physical", "burn", 4, 1002),
                 (7090110, "physical", "freeze", 1, 1004),
                 (7120060, "physical", "poison", 1, 1001),
                 (7120070, "magical", "poison", 2, 1001)]
        for game_id, kind, status, stacks, term in cases:
            with self.subTest(game_id=game_id):
                p = self.program(game_id)
                self.assertEqual(p["status"], "compiled")
                self.assertEqual(p["operations"][0]["params"]["kind"], kind)
                self.assertEqual(p["operations"][1], {"op": "status.add", "params": {
                    "target": "opponent", "status": status, "stacks": stacks}})
                self.assertEqual(p["dependency_ids"], [term])
                self.assertEqual(p["source_details"]["desc_notes"], [term])

    def test_real_damage_debuff_targets_and_signs_are_retained(self):
        for game_id, stat, percent in [(7090290, "mdef", -50), (7130300, "pdef", -30)]:
            p = self.program(game_id)
            self.assertEqual([o["op"] for o in p["operations"]], ["damage", "stat.modify"])
            self.assertEqual(p["operations"][1]["params"], {"target": "opponent", "attributes": [stat],
                             "percent": {"numerator": percent, "denominator": 100}})

    def test_multiple_explicit_clauses_are_atomic_and_kind_checked(self):
        desc = "造成物伤，敌方获得2层中毒，自己回复4能量，敌方获得物防-30%。"
        p = compile_skill(skill(desc, desc_notes=[1001]))
        self.assertEqual([o["op"] for o in p["operations"]], ["damage", "status.add", "energy.restore", "stat.modify"])
        self.assertEqual(p["dependency_ids"], [1001])
        for bad_kind in ("magical", "status", "defense"):
            rejected = compile_skill(skill(desc, bad_kind, desc_notes=[1001]))
            self.assertEqual(rejected["operations"], [])
            self.assertIn("description_kind_conflict", rejected["blockers"])
        for extra in ({"desc_notes": [1001, 9999]}, {"effect_details": {"zh": "隐藏效果"}}):
            self.assertEqual(compile_skill(skill(desc, **extra))["operations"], [])

    def test_conditions_unknown_clauses_and_unsupported_connectives_never_partial_compile(self):
        descriptions = ["造成物伤，敌方获得1层中毒，若敌方力竭则回复能量。",
                        "造成物伤，敌方获得1层中毒。额外造成伤害。",
                        "自己回复15%生命和4能量，随后脱离。",
                        "自己回复30%生命，应对防御：改为回复50%生命。",
                        "自己回复4能量，并获得魔攻+70%，但无法行动。",
                        "造成物伤，敌方获得1层中毒，，自己回复1能量。",
                        "造成物伤，敌方获得1层中毒；自己回复1能量。",
                        "造成物伤，敌方获得1层中毒。\n"]
        for desc in descriptions:
            with self.subTest(desc=desc):
                p = compile_skill(skill(desc))
                self.assertEqual(p["status"], "unsupported")
                self.assertEqual(p["operations"], [])

    def test_version_one_compiled_semantics_remain_unchanged(self):
        root = Path(__file__).resolve().parents[1]
        old_path = root / "data" / "rules" / self.catalog["snapshot_id"] / "bwiki-declarative-1.json"
        old = json.loads(old_path.read_text(encoding="utf-8"))
        unchanged = 0
        for game_id, previous in old["skills"].items():
            if previous["status"] != "compiled":
                continue
            current = deepcopy(self.program(game_id))
            previous = deepcopy(previous)
            current.pop("compiler_version")
            previous.pop("compiler_version")
            self.assertEqual(current, previous, game_id)
            unchanged += 1
        self.assertEqual(unchanged, 138)
        self.assertEqual(COMPILER_VERSION, "bwiki-declarative-6")
        self.assertEqual(self.programs["counts"]["skills"]["compiled"], 172)


class FixedHitSkillProgramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from lab.server import load_catalog
        cls.catalog = load_catalog()[0]
        cls.programs = compile_catalog(cls.catalog)

    def test_all_eighteen_source_sequences_keep_count_kind_and_unscaled_power(self):
        cases = [(7020480, 3, "physical", 35), (7020500, 5, "magical", 25),
                 (7020890, 1, "magical", 60), (7020920, 2, "magical", 50),
                 (7030190, 2, "physical", 45), (7030420, 2, "physical", 25),
                 (7040190, 2, "physical", 25), (7040350, 3, "magical", 15),
                 (7050350, 4, "magical", 20), (7060170, 3, "physical", 30),
                 (7080290, 1, "physical", 55), (7090260, 2, "magical", 45),
                 (7130250, 3, "magical", 15), (7140230, 2, "physical", 25),
                 (7150050, 2, "physical", 15), (7170210, 5, "magical", 20),
                 (7180260, 2, "magical", 45), (7190380, 3, "magical", 30)]
        for game_id, hits, kind, power in cases:
            with self.subTest(game_id=game_id):
                p = self.programs["skills"][str(game_id)]
                source = self.catalog["moves"][str(game_id)]
                self.assertEqual(p["status"], "compiled")
                self.assertEqual(p["operations"], [{"op": "damage.sequence", "params": {
                    "target": "opponent", "kind": kind, "power": power, "type": source["type"], "hits": hits}}])
                self.assertEqual(p["dependency_ids"], [3005])
                self.assertEqual(p["source_description"], source["desc"]["zh"])
                self.assertFalse(p["executable"])
                self.assertFalse(p["real_game_verified"])
                self.assertTrue(any("威力作用域" in text for text in p["execution_blockers"]))

    def test_one_hit_combo_is_not_collapsed_into_an_ordinary_attack(self):
        plain = compile_skill(skill("造成物伤。"))
        combo = compile_skill(skill("造成物伤，1连击。"))
        self.assertEqual(plain["operations"][0]["op"], "damage")
        self.assertEqual(combo["operations"][0]["op"], "damage.sequence")
        self.assertEqual(combo["operations"][0]["params"]["hits"], 1)
        self.assertEqual(combo["dependency_ids"], [3005])

    def test_conditional_repetition_and_extra_effects_remain_whole_skill_blockers(self):
        for desc in ("造成物伤，2连击，应对状态：本次技能连击数翻倍。",
                     "造成魔伤，1连击，应对状态：本技能变为3连击。",
                     "造成物伤，1连击，每次使用后，本技能连击数永久+1。",
                     "造成物伤，3连击。自己回复1能量。",
                     "造成物伤，3连击，自己回复1能量。",
                     "造成物伤，3连击。\n", "造成物伤，3连击；", "造成物伤，3连击。 "):
            with self.subTest(desc=desc):
                p = compile_skill(skill(desc))
                self.assertEqual(p["status"], "unsupported")
                self.assertEqual(p["operations"], [])
        for game_id in (7020460, 7020470, 7020510, 7021140):
            self.assertEqual(self.programs["skills"][str(game_id)]["status"], "unsupported")

    def test_sequence_rejects_invalid_count_kind_power_and_unrelated_notes(self):
        for desc in ("造成物伤，0连击。", "造成物伤，-1连击。", "造成物伤，1.5连击。", "造成物伤，03连击。"):
            self.assertEqual(compile_skill(skill(desc))["operations"], [])
        for changes in ({"kind": "status"}, {"kind": "magical"}, {"power": None},
                        {"power": 0}, {"power": True}, {"desc_notes": [3005, 9999]},
                        {"effect_details": {"zh": "额外触发"}}):
            p = compile_skill(skill("造成物伤，3连击。", **changes))
            self.assertEqual(p["status"], "unsupported")
            self.assertEqual(p["operations"], [])
        p = compile_skill(skill("造成物伤，3连击。", desc_notes=[3005]))
        self.assertEqual(p["status"], "compiled")
        self.assertEqual(p["source_details"]["desc_notes"], [3005])

    def test_sequence_source_and_output_are_detached(self):
        record = skill("造成物伤，3连击。", desc_notes=[3005])
        before = deepcopy(record)
        p = compile_skill(record)
        p["operations"][0]["params"]["hits"] = 100
        p["source_details"]["desc_notes"].clear()
        self.assertEqual(record, before)
        self.assertEqual(compile_skill(record)["operations"][0]["params"]["hits"], 3)

    def test_version_two_compiled_semantics_remain_unchanged(self):
        root = Path(__file__).resolve().parents[1]
        old = json.loads((root/"data"/"rules"/self.catalog["snapshot_id"]/"bwiki-declarative-2.json").read_text(encoding="utf-8"))
        unchanged = 0
        for game_id, previous in old["skills"].items():
            if previous["status"] != "compiled":
                continue
            previous, current = deepcopy(previous), deepcopy(self.programs["skills"][game_id])
            previous.pop("compiler_version")
            current.pop("compiler_version")
            self.assertEqual(previous, current, game_id)
            unchanged += 1
        self.assertEqual(unchanged, 149)
        self.assertEqual(self.programs["counts"]["skills"], {
            "total": 579, "compiled": 172, "unsupported": 407, "executable": 0, "real_game_verified": 0})


class EnergyConditionalSkillProgramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from lab.server import load_catalog
        cls.catalog = load_catalog()[0]
        cls.programs = compile_catalog(cls.catalog)

    def test_three_reviewed_source_conditions_keep_distinct_targets_and_modifiers(self):
        cases = [(7020440, "magical", 95, "self", "eq", 0, "after_use", "power_add", 120),
                 (7020530, "physical", 65, "opponent", "lte", 2, "unspecified", "damage_multiply", 5),
                 (7170110, "magical", 40, "opponent", "eq", 0, "unspecified", "damage_multiply", 20)]
        for game_id, kind, power, target, comparison, value, timing, modifier, amount in cases:
            with self.subTest(game_id=game_id):
                p = self.programs["skills"][str(game_id)]
                source = self.catalog["moves"][str(game_id)]
                self.assertEqual(p["operations"], [{"op": "damage.conditional", "params": {
                    "target": "opponent", "kind": kind, "power": power, "type": source["type"],
                    "condition": {"target": target, "attribute": "energy", "comparison": comparison,
                                  "value": value, "source_timing": timing},
                    "modifier": {"kind": modifier, "amount": amount}}}])
                self.assertEqual(p["source_description"], source["desc"]["zh"])
                self.assertEqual(p["static_fields"]["power"], power)
                self.assertFalse(p["executable"])
                self.assertFalse(p["real_game_verified"])

    def test_after_use_wording_does_not_become_assumed_payment_timing(self):
        p = self.programs["skills"]["7020440"]
        self.assertEqual(p["operations"][0]["params"]["condition"]["source_timing"], "after_use")
        self.assertTrue(any("使用后不等于已验证的支付费用后" in x for x in p["execution_blockers"]))
        self.assertTrue(any("实验时序" in x for x in p["execution_blockers"]))
        self.assertNotIn("after_payment", str(p["operations"]))
        self.assertEqual(p["dependency_ids"], [])

    def test_condition_kind_numeric_and_unreviewed_note_conflicts_are_atomic(self):
        original = self.catalog["moves"]["7020530"]
        for patch in ({"kind": "magical"}, {"kind": "status"}, {"power": None},
                      {"power": True}, {"power": 0}, {"desc_notes": [1020]},
                      {"effect_details": {"zh": "未核实的额外效果"}}):
            record = {**deepcopy(original), **patch}
            result = compile_skill(record)
            self.assertEqual(result["status"], "unsupported")
            self.assertEqual(result["operations"], [])

    def test_unknown_conditions_or_extra_clauses_never_fall_back_to_plain_damage(self):
        source = deepcopy(self.catalog["moves"]["7020530"])
        for desc in ("造成物伤，若敌方能量小于2，造成5倍伤害。",
                     "造成物伤，若敌方能量小于等于3，造成5倍伤害。",
                     "造成物伤，若敌方能量小于等于2，本次技能威力变为5倍。",
                     "造成物伤，若敌方能量小于等于2，造成5倍伤害，自己回复1能量。",
                     "造成物伤，若敌方能量小于等于2，造成5倍伤害。额外造成伤害。",
                     "造成物伤，若敌方能量小于等于2，造成5倍伤害。\n",
                     "造成魔伤，使用前若能量耗尽，本次技能威力+120。"):
            source["desc"]["zh"] = desc
            p = compile_skill(source)
            self.assertEqual(p["status"], "unsupported", desc)
            self.assertEqual(p["operations"], [])

    def test_mutating_conditional_program_does_not_change_source_or_future_compile(self):
        source = deepcopy(self.catalog["moves"]["7020530"])
        original = deepcopy(source)
        p = compile_skill(source)
        p["operations"][0]["params"]["condition"]["value"] = 999
        p["operations"][0]["params"]["modifier"]["kind"] = "power_add"
        self.assertEqual(source, original)
        again = compile_skill(source)
        self.assertEqual(again["operations"][0]["params"]["condition"]["value"], 2)
        self.assertEqual(again["operations"][0]["params"]["modifier"]["kind"], "damage_multiply")

    def test_all_version_three_compiled_programs_are_unchanged_except_version(self):
        root = Path(__file__).resolve().parents[1]
        old = json.loads((root/"data"/"rules"/self.catalog["snapshot_id"]/"bwiki-declarative-3.json").read_text(encoding="utf-8"))
        unchanged = 0
        for game_id, previous in old["skills"].items():
            if previous["status"] != "compiled":
                continue
            previous, current = deepcopy(previous), deepcopy(self.programs["skills"][game_id])
            previous.pop("compiler_version")
            current.pop("compiler_version")
            self.assertEqual(previous, current, game_id)
            unchanged += 1
        self.assertEqual(unchanged, 167)
        self.assertEqual(self.programs["counts"]["skills"], {
            "total": 579, "compiled": 172, "unsupported": 407, "executable": 0, "real_game_verified": 0})


class SwiftSkillProgramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from lab.server import load_catalog
        cls.catalog = load_catalog()[0]
        cls.programs = compile_catalog(cls.catalog)

    def test_wing_attack_keeps_swift_as_entry_metadata_not_duplicate_damage(self):
        p = self.programs["skills"]["7150080"]
        self.assertEqual(p["status"], "compiled")
        self.assertIs(p["intrinsic_swift"], True)
        self.assertEqual(p["entry_trigger"], {"kind": "voluntary_switch", "term_id": 1005})
        self.assertEqual(p["dependency_ids"], [1005])
        self.assertEqual(p["source_details"]["desc_notes"], [1005])
        self.assertEqual(p["operations"], [{"op": "damage", "params": {
            "target": "opponent", "kind": "magical", "power": 50, "type": "翼系"}}])
        self.assertEqual(p["swift_term"], next(t for t in self.catalog["glossary"] if t["key"] == 1005))
        self.assertEqual(p["term_source"], self.catalog["provenance"]["Terms"])
        self.assertFalse(p["executable"])
        self.assertFalse(p["real_game_verified"])

    def test_only_entire_simple_swift_attack_pattern_is_compiled(self):
        for desc in ("造成魔伤，迅捷，应对状态：本次技能威力变为1.5倍。",
                     "造成魔伤，若上回合使用幻系技能则获得迅捷。",
                     "造成魔伤，迅捷。然后自己回复1能量。", "迅捷，造成魔伤。",
                     "造成魔伤，迅捷。 ", "造成魔伤，2连击，迅捷。"):
            with self.subTest(desc=desc):
                p = compile_skill(skill(desc, "magical", desc_notes=[1005]))
                self.assertEqual(p["status"], "unsupported")
                self.assertEqual(p["operations"], [])
        for game_id in (7150110, 7150150, 7150260, 7150300, 7150320, 7150400, 7150410):
            self.assertEqual(self.programs["skills"][str(game_id)]["status"], "unsupported")

    def test_swift_invalid_power_kind_extra_notes_or_details_never_emit_operations(self):
        for changes in ({"power": None}, {"power": 0}, {"power": True}, {"kind": "physical"},
                        {"desc_notes": [1005, 9999]}, {"desc_notes": "1005"},
                        {"effect_details": {"zh": "额外条件"}}):
            source = deepcopy(self.catalog["moves"]["7150080"])
            source.update(changes)
            p = compile_skill(source)
            self.assertEqual(p["status"], "unsupported", changes)
            self.assertEqual(p["operations"], [], changes)

    def test_missing_changed_ambiguous_or_unreviewed_swift_term_blocks_catalog_program(self):
        for change in ("missing", "duplicate", "definition", "source"):
            catalog = deepcopy(self.catalog)
            term = next(t for t in catalog["glossary"] if t["key"] == 1005)
            if change == "missing":
                catalog["glossary"].remove(term)
            elif change == "duplicate":
                catalog["glossary"].append(deepcopy(term))
            elif change == "definition":
                term["definition"] += "变更"
            else:
                catalog["provenance"]["Terms"]["content_sha256"] = "changed"
            p = compile_catalog(catalog)["skills"]["7150080"]
            self.assertEqual(p["status"], "unsupported", change)
            self.assertEqual(p["operations"], [], change)
            self.assertIn("swift_term_missing_ambiguous_or_changed", p["blockers"])

    def test_swift_metadata_and_source_term_are_detached(self):
        p = deepcopy(self.programs["skills"]["7150080"])
        p["entry_trigger"]["kind"] = "faint"
        p["swift_term"]["definition"] = "changed"
        again = compile_catalog(self.catalog)["skills"]["7150080"]
        self.assertEqual(again["entry_trigger"]["kind"], "voluntary_switch")
        self.assertNotEqual(again["swift_term"]["definition"], "changed")

    def test_all_v4_programs_preserved_with_known_later_additions(self):
        root = Path(__file__).resolve().parents[1]
        old = json.loads((root/"data"/"rules"/self.catalog["snapshot_id"]/"bwiki-declarative-4.json").read_text(encoding="utf-8"))
        newly_compiled = []
        retained = 0
        for game_id, previous in old["skills"].items():
            current = deepcopy(self.programs["skills"][game_id])
            if previous["status"] == "compiled":
                previous = deepcopy(previous)
                previous.pop("compiler_version")
                current.pop("compiler_version")
                self.assertEqual(previous, current, game_id)
                retained += 1
            elif current["status"] == "compiled":
                newly_compiled.append(int(game_id))
        self.assertEqual(retained, 170)
        self.assertEqual(newly_compiled, [7150080, 7170280])
        self.assertEqual(self.programs["counts"]["skills"], {
            "total": 579, "compiled": 172, "unsupported": 407, "executable": 0, "real_game_verified": 0})


class EnergyReductionSkillProgramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from lab.server import load_catalog
        cls.catalog = load_catalog()[0]
        cls.programs = compile_catalog(cls.catalog)

    def test_mirror_keeps_both_opponent_effects_without_energy_transfer(self):
        p = self.programs["skills"]["7170280"]
        self.assertEqual(p["status"], "compiled")
        self.assertEqual(p["source_description"], "敌方获得魔防-50%，且失去3能量。")
        self.assertEqual(p["operations"], [
            {"op": "stat.modify", "params": {"target": "opponent", "attributes": ["mdef"],
                                                "percent": {"numerator": -50, "denominator": 100}}},
            {"op": "energy.reduce", "params": {"target": "opponent", "amount": 3}},
        ])
        self.assertEqual(p["dependency_ids"], [])
        self.assertEqual(p["static_fields"]["energy"], 2)
        self.assertEqual(p["source"]["source_url"], self.catalog["moves"]["7170280"]["source_url"])
        self.assertTrue(any("低能量边界" in reason for reason in p["execution_blockers"]))
        self.assertFalse(p["executable"])
        self.assertFalse(p["real_game_verified"])

    def test_energy_reduction_does_not_discard_missing_or_appended_clauses(self):
        for description in (
                "敌方获得魔防-50%，且失去能量。", "敌方获得魔防-50%，且失去0能量。",
                "敌方获得魔防-50%，且失去-3能量。", "敌方获得魔防-50%，且失去3.5能量。",
                "敌方获得魔防-50%，且失去3能量，应对攻击：改为6能量。",
                "敌方获得魔防-50%，且失去3能量。自己回复3能量。",
                "敌方获得魔防-50%，且失去3能量。 ", "敌方获得魔防-50%，且失去3能量。\n",
                "自己获得魔防-50%，且失去3能量。", "敌方获得魔防-50%，且偷取3能量。",
                "敌方队伍中所有精灵获得魔防-50%，且失去3能量。"):
            p = compile_skill(skill(description, "status"))
            self.assertEqual(p["status"], "unsupported", description)
            self.assertEqual(p["operations"], [], description)

    def test_kind_notes_details_and_energy_must_remain_valid_for_whole_mirror(self):
        for changes in ({"kind": "magical"}, {"kind": "defense"}, {"energy": None}, {"energy": True},
                        {"desc_notes": [1013]}, {"desc_notes": [1017]},
                        {"effect_details": {"zh": "仅应对时生效"}}):
            source = deepcopy(self.catalog["moves"]["7170280"])
            source.update(changes)
            p = compile_skill(source)
            self.assertEqual(p["status"], "unsupported", changes)
            self.assertEqual(p["operations"], [], changes)

    def test_reduction_does_not_admit_teamwide_response_or_energy_consumption_skills(self):
        for game_id in (7020550, 7170100, 7170130, 7170150, 7170330, 7170340, 7180300, 7180330):
            p = self.programs["skills"][str(game_id)]
            self.assertEqual(p["status"], "unsupported", game_id)
            self.assertEqual(p["operations"], [], game_id)

    def test_mirror_operations_and_source_are_detached(self):
        record = deepcopy(self.catalog["moves"]["7170280"])
        before = deepcopy(record)
        p = compile_skill(record)
        p["operations"][0]["params"]["attributes"].append("patk")
        p["operations"][1]["params"]["amount"] = 999
        again = compile_skill(record)
        self.assertEqual(record, before)
        self.assertEqual(again["operations"][0]["params"]["attributes"], ["mdef"])
        self.assertEqual(again["operations"][1]["params"]["amount"], 3)

    def test_v5_programs_remain_identical_and_only_mirror_is_new(self):
        root = Path(__file__).resolve().parents[1]
        old = json.loads((root/"data"/"rules"/self.catalog["snapshot_id"]/"bwiki-declarative-5.json").read_text(encoding="utf-8"))
        new, retained = [], 0
        for game_id, previous in old["skills"].items():
            current = deepcopy(self.programs["skills"][game_id])
            if previous["status"] == "compiled":
                previous = deepcopy(previous)
                previous.pop("compiler_version")
                current.pop("compiler_version")
                self.assertEqual(previous, current, game_id)
                retained += 1
            elif current["status"] == "compiled":
                new.append(int(game_id))
        self.assertEqual(retained, 171)
        self.assertEqual(new, [7170280])
        self.assertEqual(self.programs["counts"]["skills"], {
            "total": 579, "compiled": 172, "unsupported": 407, "executable": 0, "real_game_verified": 0})


if __name__ == "__main__":
    unittest.main()
