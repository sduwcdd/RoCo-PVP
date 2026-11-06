"""Executable game-file components under an explicitly selected experiment.

Opcode/attribute identities are bound to extracted enum source. Parameter units,
target codes, timing and stacking are declared experiment policy, not claims that
the client contains the authoritative server implementation. No active rule is
installed here, and no skill ID or prose is used to select an effect.
"""
from copy import deepcopy
from collections import Counter
from pathlib import Path
import re

from lab.effect_runtime import HOOKS
from lab.game_layer_references import APPLICATION_FIELDS, validate_layer_references
from lab.game_rule_candidates import digest, file_hash, read_json
from lab.skill_execution import execute_skill

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "artifacts/game_layer_references_mirror_patch2_20261025/layer_references.json"
ENUM_PATH = ROOT / "artifacts/game_logic_followup_20261025/scripts/pakchunk4-WindowsNoEditor_27_P/Enum.luac.decompiled.lua"
ENUM_SHA256 = "292b8bedc43a930cb40e5f8f8e7bd8995c2ac7b433e5059fdd21c140627900a5"
VERSION = "game-file-components-experiment-1"
ATTRIBUTES = {"AT_PHY_ATKADD": ("patk", 1), "AT_SPE_ATKADD": ("matk", 1),
              "AT_PHY_DEFADD": ("pdef", 1), "AT_SPE_DEFADD": ("mdef", 1),
              "AT_PHY_ATKDEC": ("patk", -1), "AT_SPE_ATKDEC": ("matk", -1),
              "AT_PHY_DEFDEC": ("pdef", -1), "AT_SPE_DEFDEC": ("mdef", -1)}
# These presentation/ordinary-action fields occur in the supported pure-result
# layouts. A new action field requires review rather than being silently ignored.
PURE_RESULT_FIELDS = frozenset({"id", "name", "desc", "flavor_text", "icon", "res_id", "Skill_Type",
    "can_changed", "cd_round", "common_type", "common_type_number", "contact_type", "dam_para",
    "damage_type", "describe_type", "energy_cost", "hit_para", "monitor_data_version", "skill_dam_type",
    "skill_feature", "skill_priority", "skill_result", "target_blood_limit", "target_count", "target_type", "type"})


def _check_primary_action(row):
    if set(row) - PURE_RESULT_FIELDS:
        raise ValueError("Unadapted action fields: " + ",".join(sorted(set(row) - PURE_RESULT_FIELDS)))
    if digest(row.get("dam_para")) != digest([0]):
        raise ValueError("Primary damage is not adapted")
    cost = row.get("energy_cost")
    if not isinstance(cost, list) or len(cost) != 1 or type(cost[0]) is not int or cost[0] < 0:
        raise ValueError("Conditional or missing primary energy cost is not adapted")
    if digest(row.get("cd_round")) != digest([0, 0]):
        raise ValueError("Cooldown/charge action semantics are not adapted")
    if (type(row.get("hit_para")) is not int or row["hit_para"] != 10000 or
            type(row.get("target_count")) is not int or row["target_count"] != 1 or
            type(row.get("target_type")) is not int or row["target_type"] not in (1, 9) or
            ("target_blood_limit" in row and digest(row["target_blood_limit"]) != digest([0]))):
        raise ValueError("Conditional hit/target action semantics are not adapted")


def load_game_skill_sources(path=DEFAULT_SOURCE, *, verify_sources=True):
    bundle = read_json(path)
    errors = validate_layer_references(bundle, verify_sources=verify_sources)
    if errors:
        raise ValueError("Game-file sources invalid: " + "; ".join(errors))
    return bundle


def experimental_game_policy(source_id):
    """The caller explicitly selects this version; it is not a game default."""
    return {"version": VERSION, "source_id": source_id,
        "operation_order": "file_slot_order_experiment", "cast_moments": [11],
        "target_codes": {"1": "self", "2": "opponent"},
        "success_rate": "require_explicit_10000",
        "empty_slots": "preserve_as_noop", "absent_buff_level_rule": "literal_group_operand_experiment",
        "attribute_parameters": "attribute_zero_basis_points_per_layer_experiment",
        "attribute_denominator": 10000, "stat_stacking": "record_separate_signed_terms",
        "energy_parameters": "signed_delta_zero_zero_once_experiment",
        "energy_group_operand": "retained_not_a_multiplier", "runtime_version_verified": False}


def _enum_bindings():
    if file_hash(ENUM_PATH) != ENUM_SHA256:
        raise ValueError("Extracted enum source changed; binding review required")
    text = ENUM_PATH.read_text(encoding="utf-8")
    def namespace(name):
        match = re.search(r"Enum\." + name + r"\s*=\s*setmetatable\(\{(.*?)\}\s*,\s*EnumMeta\)", text, re.S)
        if not match:
            raise ValueError("Missing enum namespace: " + name)
        return {symbol: int(value) for symbol, value in re.findall(r"(\w+)\s*=\s*(-?\d+)", match[1])}
    attrs, effects, buffs = namespace("AttributeType"), namespace("EffectType"), namespace("BuffType")
    return {attrs[symbol]: {"symbol": symbol, "attribute": value[0], "sign": value[1]}
            for symbol, value in ATTRIBUTES.items()}, effects["ET_CHANGE_ENERGY"], buffs["BFT_ATTR_CHANGE"]


def _integer(value, label, minimum=None):
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ValueError("Unsupported integer operand: " + label)
    return value


def _triplet(row, field):
    groups = row.get(field)
    if (not isinstance(groups, list) or len(groups) != 3 or
            any(not isinstance(g, dict) or set(g) != {"params"} or
                not isinstance(g["params"], list) or len(g["params"]) != 1 for g in groups)):
        raise ValueError("Unsupported parameter structure: " + field)
    return [_integer(g["params"][0], field + ":" + str(i)) for i, g in enumerate(groups)]


def compile_game_skill(bundle, source_id, skill_id, policy):
    return _compile_game_skill(bundle, source_id, skill_id, policy, validate_bundle=True)


def _compile_game_skill(bundle, source_id, skill_id, policy, *, validate_bundle):
    """Return a source-bound program callable by the existing skill runtime.

    Unsupported references, parameter layouts, triggers, rules or probabilities
    reject the whole skill. Empty/zero slots stay in evidence as explicit noops.
    """
    if digest(policy) != digest(experimental_game_policy(source_id)):
        raise ValueError("Select the complete supported game-file experiment policy explicitly")
    if validate_bundle:
        errors = validate_layer_references(bundle)
        if errors:
            raise ValueError("Game-file graph invalid: " + "; ".join(errors))
    _integer(skill_id, "skill_id", 1)
    if source_id not in bundle["variants"]:
        raise ValueError("Unknown game-file source version")
    variant = bundle["variants"][source_id]
    if str(skill_id) not in variant["tables"]["SKILL_CONF"]:
        raise ValueError("Skill record absent from the explicitly selected source")
    row = variant["tables"]["SKILL_CONF"][str(skill_id)]
    _check_primary_action(row)
    attrs, energy_opcode, stat_opcode = _enum_bindings()
    operations, records, slots = [], {}, []

    def record(node_id):
        node = bundle["nodes"][node_id]
        records[node_id] = {"record_sha256": node["record_sha256"], "raw": deepcopy(node["raw"])}
        return node["raw"]

    record(f"{source_id}/SKILL_CONF:{skill_id}")
    for index, raw in enumerate(row.get("skill_result", [])):
        app = bundle["applications"][f"{source_id}/SKILL_CONF:{skill_id}/skill_result:{index}"]
        slot = {"application": deepcopy(app), "operation_indices": []}
        slots.append(slot)
        if set(raw) - set(APPLICATION_FIELDS):
            raise ValueError("Unadapted result-reference fields")
        if app["status"] in ("absent_id", "explicit_zero"):
            if raw not in ({}, {"effect_id": 0}):
                raise ValueError("An unresolved nonempty result slot cannot be silently skipped")
            continue
        if app["status"] != "resolved" or len(app["targets"]) != 1:
            raise ValueError("Unresolved game-file result reference")
        if (type(raw.get("cast_moment")) is not int or raw["cast_moment"] not in policy["cast_moments"] or
                type(raw.get("success_rate")) is not int or raw["success_rate"] != 10000 or
                type(raw.get("result_target_type")) is not int or str(raw["result_target_type"]) not in policy["target_codes"]):
            raise ValueError("Unbound trigger, target or probabilistic result")
        target = policy["target_codes"][str(raw["result_target_type"])]
        target_row = record(app["targets"][0])
        if app["kind"] == "state_application_reference":
            if "buff_level_rule" in raw:
                raise ValueError("Explicit buff_level_rule has no executable binding")
            layers = _integer(raw.get("buff_group_level"), "buff_group_level", 0)
            if not app["base_references"]:
                raise ValueError("Buff has no bound base component")
            for base_ref in app["base_references"]:
                if base_ref["status"] != "resolved" or len(base_ref["targets"]) != 1:
                    raise ValueError("Unresolved base-buff component")
                base = record(base_ref["targets"][0])
                if ("trigger_type" in base or ("client_trigger_type" in base and
                        digest(base["client_trigger_type"]) != digest([-1]))):
                    raise ValueError("Conditional base-buff trigger is not adapted")
                if type(base.get("buffbase_order")) is not int or base["buffbase_order"] != stat_opcode:
                    raise ValueError("Unsupported base-buff opcode")
                attribute, mode, amount = _triplet(base, "buffbase_param")
                if attribute not in attrs or mode != 0 or amount < 0:
                    raise ValueError("Unsupported attribute parameter mode")
                binding = attrs[attribute]
                slot["operation_indices"].append(len(operations))
                operations.append({"op": "stat.modify", "params": {"target": target,
                    "attributes": [binding["attribute"]], "percent": {
                        "numerator": binding["sign"] * amount * layers, "denominator": policy["attribute_denominator"]}}})
        elif type(target_row.get("effect_order")) is int and target_row["effect_order"] == energy_opcode:
            amount, mode, extra = _triplet(target_row, "effect_param")
            if mode != 0 or extra != 0 or amount == 0:
                raise ValueError("Unsupported energy parameter mode")
            slot["operation_indices"].append(len(operations))
            operations.append({"op": "energy.restore" if amount > 0 else "energy.reduce",
                               "params": {"target": target, "amount": abs(amount)}})
        else:
            raise ValueError("Unsupported game-file effect opcode")
    if not operations:
        raise ValueError("No executable file components")
    evidence = {"source_id": source_id, "archive": variant["archive"],
        "table_files": {name: deepcopy(s["files"]) for name, s in variant["table_sources"].items()},
        "records": records, "slots": slots, "policy": deepcopy(policy),
        "enum_source": {"path": str(ENUM_PATH), "sha256": ENUM_SHA256},
        "layer_adapter_sha256": variant["adapter_sha256"], "skill_adapter_sha256": file_hash(__file__)}
    name = row.get("name", {})
    description = row.get("desc", {})
    program = {"game_id": skill_id, "name": name.get("text") if isinstance(name, dict) else str(name),
        "category": "skill", "compiler_version": VERSION, "snapshot_id": "game-file:" + source_id,
        "source_hash": digest(evidence), "source_version": variant["archive"],
        "status": "compiled", "blockers": [], "dependency_ids": [], "operations": operations,
        "execution_blockers": [],
        "source_description": description.get("text") if isinstance(description, dict) else description,
        "source_details": {"source_id": source_id, "skill_node": f"{source_id}/SKILL_CONF:{skill_id}"},
        "source": {"kind": "extracted_game_file", "source_id": source_id, "archive": variant["archive"]},
        "skill_source": {"table": "SKILL_CONF", "record_sha256": digest(row)},
        "order_semantics": "file_slot_order_experiment_not_verified_battle_timing",
        "static_fields": {"energy_cost": deepcopy(row.get("energy_cost"))},
        "game_file_evidence": evidence, "executable": True, "real_game_verified": False,
        "scope": "isolated_game_file_skill_result_fragment", "whole_skill_verified": False,
        "research_skill_override_allowed": True,
        "structural_coverage": "all_result_components_no_primary_damage",
        "research_action_fields": {"base_energy_cost": row["energy_cost"][0],
            "priority_raw": deepcopy(row.get("skill_priority")), "cooldown_raw": deepcopy(row["cd_round"])},
        "training_eligible": False, "active_rules_modified": False,
        "execution_uncertainties": ["explicit_experiment_parameter_units_and_target_codes",
            "file_slot_order_is_not_verified_battle_timing", "stat_terms_are_not_an_effective_stat_formula",
            "duration_stacking_refresh_and_live_version_require_calibration"]}
    program["game_file_program_sha256"] = digest(program)
    return program


class GameSkillAdapter:
    """One verified private snapshot; per-skill compilation never rebuilds its graph."""
    def __init__(self, bundle, *, verify_sources=True):
        owned = deepcopy(bundle)
        if verify_sources:
            from lab.source_paths import validate_relocated_layer_sources
            errors = validate_relocated_layer_sources(owned)
        else:
            errors = validate_layer_references(owned, verify_sources=False)
        if errors:
            raise ValueError("Game-file sources invalid: " + "; ".join(errors))
        self._bundle, self._cache = owned, {}

    def sources(self):
        return {sid: {"archive": v["archive"], "skill_records": len(v["tables"]["SKILL_CONF"]),
                      "explicit_resource_group": "resource_group" in v}
                for sid, v in self._bundle["variants"].items()}

    def compile(self, source_id, skill_id, policy):
        _integer(skill_id, "skill_id", 1)
        key = (source_id, skill_id, digest(policy))
        if key not in self._cache:
            self._cache[key] = _compile_game_skill(self._bundle, source_id, skill_id, policy, validate_bundle=False)
        return deepcopy(self._cache[key])

    def coverage(self, source_id, policy):
        """One metadata pass followed by compilation only for eligible layouts."""
        if digest(policy) != digest(experimental_game_policy(source_id)):
            raise ValueError("Select the complete supported game-file experiment policy explicitly")
        rows = self._bundle["variants"][source_id]["tables"]["SKILL_CONF"]
        reasons, eligible, supported = Counter(), 0, []
        for key, row in rows.items():
            try:
                _check_primary_action(row)
            except ValueError as error:
                reasons[str(error)] += 1
                continue
            eligible += 1
            try:
                _compile_game_skill(self._bundle, source_id, int(key), policy, validate_bundle=False)
                supported.append(key)
            except (ValueError, KeyError) as error:
                reasons[str(error)] += 1
        return {"source_id": source_id, "source_records": len(rows), "metadata_eligible": eligible,
                "executable_result_fragments": len(supported), "supported_ids": supported,
                "blocked_reasons": dict(reasons), "training_eligible": False,
                "scope": "isolated_game_file_skill_result_fragment"}


def load_game_skill_adapter(path=DEFAULT_SOURCE, *, verify_sources=True):
    return GameSkillAdapter(read_json(path), verify_sources=verify_sources)


def game_skill_context(program, *, resolved_energy_cost):
    """Caller-resolved payment is mandatory, including an explicitly chosen zero."""
    _integer(resolved_energy_cost, "resolved_energy_cost", 0)
    return {"mode": "isolated_skill_experiment", "snapshot_id": program["snapshot_id"],
        "source_hash": program["source_hash"], "operation_order": "source_text_order_experiment",
        "game_file_policy": deepcopy(program["game_file_evidence"]["policy"]),
        "unresolved_dependencies": [], "excluded_hooks": sorted(HOOKS),
        "resolved_energy_cost": resolved_energy_cost, "stat_policy": "record_signed_percentage_terms",
        "energy_policy": "clamp_to_declared_max", "energy_reduction_policy": "clamp_to_zero_experiment"}


def execute_game_skill(program, state, context):
    """Source/policy-bound wrapper; execution uses the existing atomic runtime."""
    try:
        unsigned = {k: v for k, v in program.items() if k != "game_file_program_sha256"}
        if program["game_file_program_sha256"] != digest(unsigned):
            raise ValueError("Game-file compiled program changed")
        evidence = program["game_file_evidence"]
        if program["source_hash"] != digest(evidence):
            raise ValueError("Game-file source evidence changed")
        if (digest(context.get("game_file_policy")) != digest(evidence["policy"]) or
                "resolved_energy_cost" not in context):
            raise ValueError("Runtime must explicitly bind the game-file policy and payment")
        result = execute_skill(program, state, context)
        result["game_file_source_hash"] = program["source_hash"]
        result["game_file_program_sha256"] = program["game_file_program_sha256"]
        result["game_file_policy"] = deepcopy(evidence["policy"])
        result["game_file_component_observations"] = [{"slot": slot["application"]["slot"],
            "raw_reference": deepcopy(slot["application"]["raw_reference"]),
            "operand_byte_spans": deepcopy(slot["application"]["operand_byte_spans"]),
            "targets": deepcopy(slot["application"]["targets"]),
            "operation_indices": deepcopy(slot["operation_indices"])} for slot in evidence["slots"]]
        result["execution_source"] = "extracted_game_file_components_experiment"
        return result
    except (KeyError, TypeError, ValueError) as error:
        return {"status": "blocked", "state": deepcopy(state), "events": [], "blockers": [str(error)],
                "training_eligible": False, "calibrated": False, "full_turn_executed": False}
