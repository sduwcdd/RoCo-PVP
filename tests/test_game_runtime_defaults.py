from pathlib import Path

import unittest
from unittest.mock import patch

from lab import game_runtime_defaults as defaults


def test_pinned_recharge_chain_and_missing_energy_stay_distinct():
    bundle = defaults.load_game_runtime_defaults()
    assert bundle["source_hashes_verified"] is True
    assert bundle["version"] == "game-runtime-config-20261025-v2"
    assert bundle["runtime_version_verified"] is False
    recharge = bundle["recharge"]
    assert (recharge["skill_id"], recharge["effect_id"], recharge["amount"],
            recharge["energy_cost"], recharge["priority"]) == (7000010, 1019005, 5, 0, 5)
    assert recharge["skill_type_raw"] != recharge["skill_charge_is_distinct"]["value"]
    assert bundle["energy"]["maximum_raw"] == 9
    assert bundle["energy"]["maximum_raw_role"] == "character_config_only_not_pet_cap"
    assert bundle["energy"]["pet_maximum_fallback"] == 10
    source = bundle["energy"]["pet_maximum_fallback_source"]
    assert source["verified"] is True
    assert source["selection"] == "prefer_runtime_max_energy_otherwise_fallback"
    assert source["zero_is_preserved"] is True
    assert source["proves_initial_energy"] is False
    assert source["bytecode_check_raw"]["output_sha256"] == source["source_hashes"][source["disassembly_path"]]
    assert bundle["energy"]["initial_energy_raw"] is None
    assert bundle["energy"]["round_energy_numeric_present"] is False
    assert "num" not in bundle["energy"]["round_energy_raw"]


def test_status_sources_do_not_promote_semantics():
    bundle = defaults.load_game_runtime_defaults()
    burn = bundle["burn"]
    assert burn["raw"]["buff_group_reduce"] == [{"reduce_type": 6, "reduce_param": [1, 5000]}]
    assert burn["damage_basis_verified"] is False
    assert burn["rounding_verified"] is False
    assert all(not row["universal_regeneration"] for row in bundle["conditional_energy_statuses"])
    burn["raw"]["buff_group_reduce"][0]["reduce_param"][0] = 999
    assert defaults.load_game_runtime_defaults()["burn"]["raw"]["buff_group_reduce"][0]["reduce_param"][0] == 1


def test_changed_source_is_rejected_before_loading():
    original = Path.read_bytes
    target = defaults.ROOT / next(iter(defaults.SOURCE_HASHES))

    def changed(path):
        return original(path) + (b"\n" if path == target else b"")

    with patch.object(Path, "read_bytes", changed):
        with unittest.TestCase().assertRaisesRegex(ValueError, "source changed"):
            defaults.load_game_runtime_defaults()
        bundle = defaults.load_game_runtime_defaults(verify_sources=False)
        assert bundle["source_hashes_verified"] is False
        assert bundle["source_hashes"] != bundle["source_pinned_hashes"]


def test_pet_getter_evidence_drift_is_rejected():
    original = Path.read_bytes

    def changed(path):
        raw = original(path)
        return raw + (b"\n" if path.name == "GetMaxEnergy.disassembled.txt" else b"")

    with patch.object(Path, "read_bytes", changed):
        with unittest.TestCase().assertRaisesRegex(ValueError, "source changed"):
            defaults.load_game_runtime_defaults()
        bundle = defaults.load_game_runtime_defaults(verify_sources=False)
        assert bundle["energy"]["pet_maximum_fallback_source"]["verified"] is False


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(test) for test in [
        test_pinned_recharge_chain_and_missing_energy_stay_distinct,
        test_status_sources_do_not_promote_semantics,
        test_changed_source_is_rejected_before_loading,
        test_pet_getter_evidence_drift_is_rejected,
    ])
