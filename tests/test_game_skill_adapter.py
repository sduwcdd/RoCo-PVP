"""Real extracted components execute; source/policy failures remain atomic."""
from copy import deepcopy
import unittest

from lab.game_layer_references import build_layer_references
from lab.game_rule_candidates import digest
from lab.game_skill_adapter import (experimental_game_policy,
    compile_game_skill, game_skill_context, execute_game_skill, GameSkillAdapter, load_game_skill_adapter)


def state():
    actor = {"hp": 100, "max_hp": 100, "energy": 8, "max_energy": 12,
             "types": ["普通系"], "statuses": {}, "stat_modifiers": {}}
    return {"self": deepcopy(actor), "opponent": deepcopy(actor), "unrelated": {"kept": [1]}}


def synthetic():
    fields = ["effect_id", "cast_moment", "result_target_type", "success_rate", "buff_group_level", "buff_level_rule"]
    tables = {"SKILL_CONF": {"123": {"id": 123, "name": {"text": "arbitrary-name"},
        "dam_para": [0], "energy_cost": [1], "cd_round": [0, 0], "hit_para": 10000,
        "target_type": 1, "target_count": 1,
        "skill_result": [{"effect_id": 10, "cast_moment": 11, "result_target_type": 2,
            "success_rate": 10000, "buff_group_level": 3}, {}, {"effect_id": 0},
            {"effect_id": 40, "cast_moment": 11, "result_target_type": 1, "success_rate": 10000}]}},
        "BUFF_CONF": {"10": {"id": 10, "buff_base_ids": [20]}},
        "BUFFBASE_CONF": {"20": {"id": 20, "buffbase_order": 1,
            "buffbase_param": [{"params": [35]}, {"params": [0]}, {"params": [2000]}]}},
        "EFFECT_CONF": {"40": {"id": 40, "effect_order": 19,
            "effect_param": [{"params": [2]}, {"params": [0]}, {"params": [0]}]}}}
    sources = {name: {"rows_content_sha256": digest(rows), "files": {}, "schema": {
        "UniqueKey": "id", "Properties": []}} for name, rows in tables.items()}
    sources["SKILL_CONF"]["schema"]["Properties"] = [{"Name": "skill_result", "Type": "EStruct",
        "Struct": {"Properties": [{"Name": f, "Type": "EInt32"} for f in fields]}}]
    return {"source_id": "synthetic", "archive": "synthetic-not-game.pak", "tables": tables,
            "table_sources": sources, "result_field_spans": {}, "adapter_sha256": "synthetic"}


class GameSkillGenericTests(unittest.TestCase):
    def compile(self, variant=None, policy=None):
        bundle = build_layer_references({"synthetic": variant or synthetic()})
        return compile_game_skill(bundle, "synthetic", 123,
                                  policy or experimental_game_policy("synthetic"))

    def test_opcode_and_parameter_adapter_executes_unseen_id_without_name_rules(self):
        p = self.compile()
        self.assertEqual([x["op"] for x in p["operations"]], ["stat.modify", "energy.restore"])
        self.assertEqual(p["operations"][0]["params"], {"target": "opponent", "attributes": ["pdef"],
            "percent": {"numerator": -6000, "denominator": 10000}})
        self.assertEqual(len(p["game_file_evidence"]["slots"]), 4)
        self.assertEqual([s["operation_indices"] for s in p["game_file_evidence"]["slots"]], [[0], [], [], [1]])
        initial = state(); before = deepcopy((initial, p))
        r = execute_game_skill(p, initial, game_skill_context(p, resolved_energy_cost=1))
        self.assertEqual(r["status"], "applied", r["blockers"])
        self.assertEqual(r["state"]["self"]["energy"], 9)
        self.assertEqual(r["state"]["opponent"]["stat_modifiers"]["pdef"], [{"numerator": -6000, "denominator": 10000}])
        self.assertEqual((initial, p), before)
        self.assertFalse(r["training_eligible"])

    def test_unknown_rules_modes_missing_values_and_triggers_fail_instead_of_defaulting(self):
        mutations = [
            lambda v: v["tables"]["SKILL_CONF"]["123"].update(dam_para=[100]),
            lambda v: v["tables"]["SKILL_CONF"]["123"].update(damage_rule=0),
            lambda v: v["tables"]["SKILL_CONF"]["123"].update(energy_rule=0),
            lambda v: v["tables"]["SKILL_CONF"]["123"].update(cd_round=[0, 1]),
            lambda v: v["tables"]["SKILL_CONF"]["123"].update(charge_round=1),
            lambda v: v["tables"]["SKILL_CONF"]["123"]["skill_result"][0].update(buff_level_rule=0),
            lambda v: v["tables"]["SKILL_CONF"]["123"]["skill_result"][0].pop("buff_group_level"),
            lambda v: v["tables"]["SKILL_CONF"]["123"]["skill_result"][0].update(cast_moment=23),
            lambda v: v["tables"]["SKILL_CONF"]["123"]["skill_result"][0].update(success_rate=9999),
            lambda v: v["tables"]["SKILL_CONF"]["123"]["skill_result"][0].update(unbound_condition=1),
            lambda v: v["tables"]["BUFFBASE_CONF"]["20"].update(trigger_type=0),
            lambda v: v["tables"]["BUFFBASE_CONF"]["20"]["buffbase_param"][1].update(params=[1]),
            lambda v: v["tables"]["BUFFBASE_CONF"]["20"]["buffbase_param"].reverse(),
            lambda v: v["tables"]["EFFECT_CONF"]["40"].update(effect_order=2),
            lambda v: v["tables"]["EFFECT_CONF"]["40"]["effect_param"][2].update(params=[1]),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                v = synthetic(); mutate(v)
                for name, rows in v["tables"].items():
                    v["table_sources"][name]["rows_content_sha256"] = digest(rows)
                with self.assertRaises(ValueError): self.compile(v)

    def test_policy_and_source_are_explicit_and_outputs_are_isolated(self):
        for field in ("source_id", "operation_order", "absent_buff_level_rule"):
            policy = experimental_game_policy("synthetic"); policy[field] = "different"
            with self.assertRaises(ValueError): self.compile(policy=policy)
        v = synthetic(); before = deepcopy(v); a = self.compile(v); b = self.compile(v)
        a["game_file_evidence"]["records"]["synthetic/BUFFBASE_CONF:20"]["raw"]["buffbase_param"].clear()
        self.assertEqual(v, before)
        self.assertEqual(b, self.compile(v))

    def test_adapter_snapshot_cache_and_single_pass_coverage(self):
        bundle = build_layer_references({"synthetic": synthetic()})
        adapter = GameSkillAdapter(bundle, verify_sources=False)
        policy = experimental_game_policy("synthetic")
        first = adapter.compile("synthetic", 123, policy)
        first["operations"].clear()
        bundle["variants"]["synthetic"]["tables"]["SKILL_CONF"]["123"]["skill_result"].clear()
        second = adapter.compile("synthetic", 123, policy)
        self.assertEqual(len(second["operations"]), 2)
        self.assertTrue(second["research_skill_override_allowed"])
        self.assertFalse(second["whole_skill_verified"])
        self.assertEqual(second["execution_blockers"], [])
        self.assertEqual(second["skill_source"]["table"], "SKILL_CONF")
        summary = adapter.coverage("synthetic", policy)
        self.assertEqual((summary["source_records"], summary["metadata_eligible"], summary["supported_ids"]), (1, 1, ["123"]))

    def test_program_policy_and_payment_mutation_rejects_without_changes(self):
        p = self.compile(); initial = state(); ctx = game_skill_context(p, resolved_energy_cost=1)
        pairs = []
        changed = deepcopy(p); changed["operations"][0]["params"]["percent"]["numerator"] = 1
        pairs.append((changed, ctx))
        changed_context = deepcopy(ctx); changed_context.pop("game_file_policy")
        pairs.append((p, changed_context))
        changed_context = deepcopy(ctx); changed_context.pop("resolved_energy_cost")
        pairs.append((p, changed_context))
        changed_context = deepcopy(ctx); changed_context["resolved_energy_cost"] = 99
        pairs.append((p, changed_context))
        for program, context in pairs:
            result = execute_game_skill(program, initial, context)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["state"], initial)
            self.assertEqual(result["events"], [])


class ActualGameSkillAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = load_game_skill_adapter()
        sources = cls.adapter.sources()
        cls.base = next(s for s, v in sources.items() if v["archive"] == "pakchunk4-WindowsNoEditor.pak")
        cls.patch2 = next(s for s, v in sources.items() if v["explicit_resource_group"])
        cls.programs = {key: cls.adapter.compile(source, key, experimental_game_policy(source))
                        for source, key in ((cls.base, 7020620), (cls.base, 7020630), (cls.patch2, 7170280))}

    def test_strength_and_magic_execute_file_layer_operands(self):
        for key, stat, numerator, layers in ((7020620, "patk", 10000, 10), (7020630, "matk", 7000, 7)):
            with self.subTest(skill=key):
                p = self.programs[key]; r = execute_game_skill(p, state(), game_skill_context(p, resolved_energy_cost=0))
                self.assertEqual(r["status"], "applied", r["blockers"])
                self.assertEqual(r["state"]["self"]["stat_modifiers"][stat], [{"numerator": numerator, "denominator": 10000}])
                slot = p["game_file_evidence"]["slots"][0]["application"]
                self.assertEqual(slot["raw_reference"]["buff_group_level"], layers)
                self.assertTrue(next(s for s in slot["operand_byte_spans"] if s["field"] == "buff_group_level")["raw_hex"])

    def test_mirror_executes_five_layers_and_energy_effect_as_one_transaction(self):
        p = self.programs[7170280]; s = state()
        result = execute_game_skill(p, s, game_skill_context(p, resolved_energy_cost=2))
        self.assertEqual(result["status"], "applied", result["blockers"])
        self.assertEqual(result["state"]["self"]["energy"], 6)
        self.assertEqual(result["state"]["opponent"]["energy"], 5)
        self.assertEqual(result["state"]["opponent"]["stat_modifiers"]["mdef"], [{"numerator": -5000, "denominator": 10000}])
        self.assertEqual([o["raw_reference"]["buff_group_level"] for o in result["game_file_component_observations"]], [5, 1])
        self.assertEqual([e["op"] for e in result["events"]], ["energy.pay", "stat.modify", "energy.reduce"])
        self.assertEqual(p["game_file_evidence"]["records"][self.patch2 + "/EFFECT_CONF:1019013"]["raw"]["effect_param"],
                         [{"params": [-3]}, {"params": [0]}, {"params": [0]}])
        self.assertFalse(result["calibrated"])
        self.assertFalse(result["training_eligible"])


if __name__ == "__main__": unittest.main()
