"""Small, pinned game-file input bundle for explicitly selected research rules.

These are extracted configuration values, not a recovered server simulator.
In particular maximum energy does not establish opening energy, and absent
numeric fields are not converted to zero. This module installs no rules.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "game-runtime-config-20261025-v2"
_BASE = "artifacts/unpack_probe_20261025/battle_analysis/tables/parsed/"
_ENUM = "artifacts/game_logic_followup_20261025/scripts/pakchunk4-WindowsNoEditor_27_P/Enum.luac.decompiled.lua"
_ENERGY = "artifacts/strength_buff_probe_20261025/energy/"
_PET = _ENERGY + "utils/raw/pakchunk4-WindowsNoEditor_3_P/NRC/Content/ScriptC/NewRoco/Modules/Core/Battle/Entity/BattlePet"
SOURCE_HASHES = {
    _BASE + "BATTLE_GLOBAL_CONFIG.json": "0e43b58db5cc6cf04771c6e17af7c5a4564b3bee671da236706c3667dd9a527e",
    _BASE + "SKILL_CONF.json": "bc725ef6f611c12c5b62966cbbc6b4dd84aa95499906ef4394155289af063f1e",
    _BASE + "EFFECT_CONF.json": "7ad5dda4d787572f6591d662ec8c9a2f1cffb1caaf6de0474357eef9cba5c4b0",
    _BASE + "BUFF_CONF.json": "d80f8e2355ffd3d54f9caa27fc7d8034a8ae03720c4760af76664effc5b3e4b0",
    _BASE + "BUFFBASE_CONF.json": "44d6db038c7e4e830a0d518f502d828294d8f2eab5c6f66bf7b0c261369dedab",
    _ENUM: "292b8bedc43a930cb40e5f8f8e7bd8995c2ac7b433e5059fdd21c140627900a5",
    _ENERGY + "RESULT.md": "96b742cfc60b0faa30c66a0f36dec9252b4e0b8672e448b21d54f49bca36243f",
    _ENERGY + "bytecode_check.json": "76e27b3345cd0f153763d55d77cf6b5ebfc7af5f8099684c9dfd698ea3e493ab",
    _ENERGY + "GetMaxEnergy.disassembled.txt": "72df379e6d9f77a7a64916158e0d5e49c0d7bf1bf36de820c7134335ec0b7d21",
    _PET + ".decompiled.lua": "0e6ec78d5cf8500497a036ae238843c76dfe49c4c301fdc5a8bdf934aff7487c",
    _PET + ".luac": "6dc494ae4dd161479f707823e5c5f6e95eec06c3405687991ed6498a8dcf9d4f",
    _PET + ".standard.lua54": "7d5bb4f239bd704db9da8c1635bf2c901a7fc51341d6ea452314bc2860da0410",
}
# Selected compressed-data packages recorded by table_manifest.json and
# effect_table_manifest.json. Their precedence was not runtime verified.
SOURCE_PACKAGES = {
    "BATTLE_GLOBAL_CONFIG": "pakchunk4-WindowsNoEditor_10_P.pak",
    "SKILL_CONF": "pakchunk4-WindowsNoEditor_26_P.pak",
    "EFFECT_CONF": "pakchunk4-WindowsNoEditor_26_P.pak",
    "BUFF_CONF": "pakchunk4-WindowsNoEditor_27_P.pak",
    "BUFFBASE_CONF": "pakchunk4-WindowsNoEditor_26_P.pak",
    "BattlePet": "pakchunk4-WindowsNoEditor_3_P.pak",
}


def _params(row, field):
    return [deepcopy(group["params"]) for group in row[field]]


def load_game_runtime_defaults(*, verify_sources=True):
    """Return owned raw records plus narrowly justified numeric conveniences.

    The default fails on any changed source. Disabling verification is for
    inspection only: actual hashes and matching status remain explicit.
    Callers must choose their own documented experimental timing, clipping,
    opening energy, damage basis, stacking, rounding and regeneration policy.
    """
    documents, actual_hashes = {}, {}
    for relative, expected in SOURCE_HASHES.items():
        payload = (ROOT / relative).read_bytes()
        actual = hashlib.sha256(payload).hexdigest()
        actual_hashes[relative] = actual
        if verify_sources and actual != expected:
            raise ValueError("Game runtime source changed; review required: " + relative)
        if relative.endswith(".json"):
            documents[Path(relative).stem] = json.loads(payload)
    check = documents["bytecode_check"]
    if verify_sources and (check.get("source_sha256") != actual_hashes[_PET + ".standard.lua54"]
            or check.get("output_sha256") != actual_hashes[_ENERGY + "GetMaxEnergy.disassembled.txt"]):
        raise ValueError("Pet energy bytecode check does not bind the source and disassembly")
    globals_ = documents["BATTLE_GLOBAL_CONFIG"]
    skills, effects = documents["SKILL_CONF"], documents["EFFECT_CONF"]
    buffs, bases = documents["BUFF_CONF"], documents["BUFFBASE_CONF"]
    skill = skills[str(globals_["pet_common_globalskill"]["num"])]
    result = skill["skill_result"][0]
    effect = effects[str(result["effect_id"])]
    params = _params(effect, "effect_param")
    # This adapter deliberately supports only the reviewed recharge chain.
    if (skill["id"] != 7000010 or skill["type"] != 4 or
            len(skill["skill_result"]) != 1 or effect["id"] != 1019005 or
            effect["effect_order"] != 19 or params != [[5], [0], [0]] or
            skill["energy_cost"] != [0] or skill["cd_round"] != [0, 0]):
        raise ValueError("Unsupported common-skill recharge configuration")

    def status(buff_id):
        buff = buffs[str(buff_id)]
        return {"buff_id": buff_id, "raw": deepcopy(buff),
                "bases_raw": [deepcopy(bases[str(i)]) for i in buff["buff_base_ids"]],
                "damage_basis_verified": False, "rounding_verified": False,
                "execution_policy_required": True}

    return {
        "version": VERSION,
        "runtime_version_verified": False,
        "source_hashes": actual_hashes,
        "source_pinned_hashes": dict(SOURCE_HASHES),
        "source_hashes_verified": actual_hashes == SOURCE_HASHES,
        "source_packages": dict(SOURCE_PACKAGES),
        "source_selection": "highest numeric suffix candidate; runtime precedence unverified",
        "recharge": {
            "skill_id": skill["id"], "name": skill["name"]["text"],
            "description": skill["desc"]["text"], "amount": params[0][0],
            "energy_cost": skill["energy_cost"][0], "priority": skill["skill_priority"],
            "cast_moment": result["cast_moment"], "effect_id": effect["id"],
            "effect_opcode": effect["effect_order"], "effect_symbol": "ET_CHANGE_ENERGY",
            "effect_params": params, "cd_round_raw": deepcopy(skill["cd_round"]),
            "charge_rounds_raw": deepcopy(skill["cd_round"]),  # Compatibility key; no inferred charge semantics.
            "skill_type_raw": skill["type"], "skill_type_symbol": "SAT_GLOBAL",
            "skill_raw": deepcopy(skill), "effect_raw": deepcopy(effect),
            "timing_verified": False,
            "skill_charge_is_distinct": {"symbol": "SAT_CHARGE", "value": 10},
        },
        "energy": {
            "maximum_raw": globals_["character_max_energy"]["num"],
            "maximum_record_raw": deepcopy(globals_["character_max_energy"]),
            "maximum_pet_scope_verified": False,
            "maximum_raw_role": "character_config_only_not_pet_cap",
            "pet_maximum_fallback": 10,
            "pet_maximum_fallback_source": {
                "function": "BattlePet:GetMaxEnergy",
                "runtime_field": "card.petInfo.battle_inside_pet_info.max_energy",
                "expression": "insideInfo and insideInfo.max_energy or 10",
                "selection": "prefer_runtime_max_energy_otherwise_fallback",
                "zero_is_preserved": True,
                "decompiled_path": _PET + ".decompiled.lua", "line": 1859,
                "disassembly_path": _ENERGY + "GetMaxEnergy.disassembled.txt",
                "bytecode_check_path": _ENERGY + "bytecode_check.json",
                "bytecode_check_raw": deepcopy(check),
                "source_hashes": {key: value for key, value in actual_hashes.items()
                                  if key.startswith(_ENERGY)},
                "verified": all(actual_hashes[key] == expected for key, expected in SOURCE_HASHES.items()
                                if key.startswith(_ENERGY)),
                "proves_initial_energy": False,
            },
            "round_energy_raw": deepcopy(globals_["round_energy"]),
            "round_energy_numeric_present": "num" in globals_["round_energy"],
            "initial_energy_raw": None, "initial_energy_verified": False,
            "automatic_regeneration_verified": False,
        },
        "poison": status(20070010), "burn": status(20070020),
        "conditional_energy_statuses": [
            {"buff_raw": deepcopy(buffs[str(buff_id)]),
             "base_raw": deepcopy(bases[str(base_id)]),
             "effect_raw": deepcopy(effects[str(effect_id)]),
             "universal_regeneration": False}
            for buff_id, base_id, effect_id in
            [(20170170, 2017017, 1019010), (20350230, 2035023, 1019025)]
        ],
        "unresolved": [
            "character_max_energy is retained as raw 9 only; its consumer remains unknown and the pet getter does not read it.",
            "The pet getter uses runtime max_energy or fallback 10; server generation of that runtime value remains unverified.",
            "Opening energy and universal turn-end energy/magic regeneration are not established.",
            "Cast-moment and trigger-type integers do not establish authoritative event ordering.",
            "Poison/burn descriptions give 3%/2% life damage, but do not bind the HP basis or rounding.",
            "Burn describes half-stack decay; half-stack rounding and damage/decay order need a policy.",
            "Species/talent-to-panel conversion and arena/showdown damage formulas remain research profiles.",
        ],
    }
