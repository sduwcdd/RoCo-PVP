from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from lab.charge_program_adapter import (load_charge_program_overrides,
                                        validate_charge_program_overrides)
from lab.prepared_rules import PreparedRules
from lab.research_phases import build_research_context_v2, execute_research_turn_v2
from tests import test_action_runtime as fixtures


class ChargeProgramAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.JointActionRuntimeTests.setUpClass()
        cls.catalog = fixtures.JointActionRuntimeTests.catalog
        cls.overlays = load_charge_program_overrides(cls.catalog)

    def test_reviewed_charge_programs_retain_raw_graph(self):
        self.assertEqual(set(self.overlays), {7100130, 7100140, 7100150, 7100170})
        program = self.overlays[7100150]
        self.assertEqual(program["static_fields"]["energy"], 3)
        self.assertEqual(program["operations"], [{"op": "damage", "params": {
            "target": "opponent", "kind": "magical", "power": 200, "type": "龙系"}}])
        self.assertEqual(program["dependency_ids"], [1007])
        evidence = program["charge_adapter_evidence"]
        self.assertEqual(evidence["game_charge_buff_raw"]["id"], 20880010)
        self.assertGreater(len(evidence["game_charge_bases_raw"]), 1)
        self.assertFalse(evidence["game_buff_graph_fully_interpreted"])
        self.assertTrue(validate_charge_program_overrides(self.catalog, self.overlays))

    def test_source_and_program_mutations_are_rejected(self):
        catalog = deepcopy(self.catalog)
        record = next(r for r in catalog["moves"].values() if r["id"] == 7100150)
        record["desc"]["zh"] += "并吸血50%。"
        with self.assertRaisesRegex(ValueError, "snapshot changed"):
            load_charge_program_overrides(catalog)
        programs = deepcopy(self.overlays)
        programs[7100150]["operations"][0]["params"]["power"] = 999
        with self.assertRaisesRegex(ValueError, "differs"):
            validate_charge_program_overrides(self.catalog, programs)

    def test_game_source_drift_rejected(self):
        original = Path.read_bytes

        def changed(path):
            raw = original(path)
            return raw + (b"\n" if path.name == "SKILL_CONF.json" else b"")

        with patch.object(Path, "read_bytes", changed):
            with self.assertRaisesRegex(ValueError, "game source changed"):
                load_charge_program_overrides(self.catalog)

    def test_actual_charge_then_release_uses_shared_runtime_and_pays_once(self):
        fixture = fixtures.JointActionRuntimeTests()
        fixture.setUp()
        state, actions = fixture.state, fixture.actions
        state["teams"]["a"]["members"][1]["skill_slots"][1] = 7100150
        actions["a"]["effective_cost"] = 0
        prepared = PreparedRules(self.catalog)
        seen = []

        def damage(params, *_):
            seen.append(deepcopy(params))
            return 17

        def turn(current):
            context = build_research_context_v2(prepared, current, actions, program_overrides=self.overlays)
            return execute_research_turn_v2(prepared, current, actions, context,
                program_overrides=self.overlays, damage_resolver=damage, status_damage_resolver=lambda *_: 0)

        setup = turn(state)
        self.assertEqual(setup["status"], "applied", setup["blockers"])
        actor = setup["state"]["teams"]["a"]["members"][1]
        self.assertEqual(actor["energy"], 10)
        self.assertIsNotNone(actor["charge"])
        self.assertFalse(any(p["power"] == 200 for p in seen))
        actions["a"]["effective_cost"] = 3
        released = turn(setup["state"])
        self.assertEqual(released["status"], "applied", released["blockers"])
        actor = released["state"]["teams"]["a"]["members"][1]
        self.assertEqual(actor["energy"], 7)
        self.assertIsNone(actor["charge"])
        self.assertEqual(sum(p["power"] == 200 for p in seen), 1)
        payments = [e["amount"] for e in released["events"]
                    if e["op"] == "energy.pay" and e["actor_side"] == "a"]
        self.assertEqual(payments, [3])
        self.assertFalse(released["training_eligible"])
