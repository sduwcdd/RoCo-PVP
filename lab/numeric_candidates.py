"""Explicit community formula candidates for designing discriminating tests.

These functions reproduce named expressions, not the official game. They are
deliberately disconnected from battle execution, beliefs and training. Inputs
are already effective values; nothing derives nature, talents, traits, STAB,
type effectiveness, HP clipping or hidden state. All arithmetic uses binary64
in expression order, except the two source-prescribed Arena float32 casts.

The accepted numerical domain is intentionally narrower than JavaScript's:
positive integer base stats <= 10000, explicit integer IV encodings, damage
inputs <= 1e6, and nonnegative finite intermediates <= 2**53-1. Invalid inputs
raise ValueError rather than inheriting the source UI's clamping/coercion.
"""
from __future__ import annotations

from copy import deepcopy
import math
import struct


_SAFE_INTEGER = 2**53 - 1
_STATS = frozenset({"hp", "patk", "matk", "pdef", "mdef", "spd"})
_EVIDENCE_REF = "data/reference/mechanics-20261025/evidence.json"
_ARENA_STAT_SOURCE = {
    "url": "https://rocoarena.com/damage-ui-B2QaE2G3.js",
    "sha256": "c2bdfb350a714f4e06239847c45d4fa5c2fb7ed7953eac05badec9df009721f9",
    "evidence_ref": _EVIDENCE_REF,
    "recheck_ref": "data/reference/formula-followup-20261025/arena-source-recheck.json",
    "kind": "community_published_stat_expression",
    "recorded_on": "2026-10-25",
}
_ARENA_NOTES_SOURCE = {
    "url": "https://rocoarena.com/calculation-notes",
    "sha256": "e754f0e370b97dbe95d4222f75695960546c5428e7d3c00d41bdf040934f1f29",
    "evidence_ref": _EVIDENCE_REF,
    "kind": "community_documented_expression",
    "recorded_on": "2026-10-25",
    "implementation_parity_claimed": False,
}
_SHOWDOWN_SOURCE = {
    "url": "https://roco-showdown.com/battle-use-guide",
    "sha256": "73ae320c39401123709f5e704017c6808d789e443d5e720004478d522cb80e2e",
    "evidence_ref": _EVIDENCE_REF,
    "kind": "community_documented_expression",
    "recorded_on": "2026-10-25",
    "implementation_parity_claimed": False,
}


def _integer(value, name, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"{name} must be an integer in [{lower}, {upper}]; no coercion or clamping")
    return value


def _number(value, name, *, positive=False):
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be an explicit finite number")
    # Check integer magnitude before float conversion (huge Python ints may
    # overflow on conversion). Bool is already excluded by the type check.
    if not 0 <= value <= 1_000_000 or (positive and value == 0):
        raise ValueError(f"{name} is outside the candidate comparison domain")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _safe(value, name):
    if not math.isfinite(value) or not 0 <= value <= _SAFE_INTEGER:
        raise ValueError(f"{name} leaves the finite safe intermediate domain")
    return value


def _js_round_nonnegative(value):
    """Math.round on the accepted nonnegative domain, not Python round.

    Do not use floor(x + .5): near the safe integer boundary that addition can
    round up by itself before floor. Subtracting floor(x) preserves the fraction.
    """
    _safe(value, "rounding operand")
    integral = math.floor(value)
    return integral + int(value - integral >= 0.5)


def _f32(value):
    return struct.unpack("!f", struct.pack("!f", value))[0]


def _stat_inputs(base_stat, iv, nature_multiplier, stat, *, iv_name, max_iv, allow_hp):
    _integer(base_stat, "base_stat", 1, 10_000)
    _integer(iv, iv_name, 0, max_iv)
    if type(nature_multiplier) not in (int, float) or nature_multiplier not in (0.9, 1.0, 1.2):
        raise ValueError("nature_multiplier must explicitly be 0.9, 1 or 1.2")
    if not isinstance(stat, str) or stat not in _STATS or (stat == "hp" and not allow_hp):
        raise ValueError("Unsupported stat; this candidate must not extrapolate an HP formula")
    return {"base_stat": base_stat, iv_name: iv, "nature_multiplier": nature_multiplier, "stat": stat}


def _result(candidate_id, inputs, source, trace, *, scope, **prediction):
    return {"candidate_id": candidate_id, "inputs": deepcopy(inputs), "source": deepcopy(source),
            "trace": trace, "scope": scope, **prediction,
            "calibrated": False, "real_game_verified": False, "training_eligible": False,
            "uncertainties": ["Community expression, not verified current-game mechanics.",
                              "Agreement with another candidate is not game calibration."]}


def arena_stat60(base_stat, raw_iv, nature_multiplier, stat):
    """Arena published 60-level/five-star stat expression, user offset excluded."""
    inputs = _stat_inputs(base_stat, raw_iv, nature_multiplier, stat,
                          iv_name="raw_iv", max_iv=60, allow_hp=True)
    growth_factor, constant, bonus = (170, 70, 100) if stat == "hp" else (110, 10, 50)
    base_growth = base_stat * 0.01
    base_growth_f32 = _f32(base_growth)
    iv_growth = raw_iv * 0.005
    growth = base_growth_f32 + iv_growth
    scaled_growth = growth_factor * growth
    core_unrounded = scaled_growth + constant
    core_f32 = _f32(core_unrounded)
    core = _js_round_nonnegative(core_f32)
    nature_adjusted = core * float(nature_multiplier)
    before_final_round = nature_adjusted + bonus
    value = _js_round_nonnegative(before_final_round)
    trace = {"base_growth": base_growth, "base_growth_f32": base_growth_f32,
             "iv_growth": iv_growth, "growth": growth, "growth_factor": growth_factor,
             "scaled_growth": scaled_growth, "starting_constant": constant,
             "core_unrounded": core_unrounded, "core_f32": core_f32, "core": core,
             "nature_adjusted": nature_adjusted, "five_star_bonus": bonus,
             "before_final_round": before_final_round, "final": value,
             "float32_casts": ["base_growth", "core_unrounded"],
             "rounding": "Math.round_nonnegative_binary64", "user_offset_included": False}
    return _result("arena_stat60_v1", inputs, _ARENA_STAT_SOURCE, trace,
                   scope="level60_five_stars_no_user_offset", stat_value=value)


def captured_stat60(base_stat, raw_iv, nature_multiplier, stat):
    """Preserve both precision hypotheses at observed rounding boundaries.

    Keep arena_stat60 unchanged as the community expression: its extra f32
    core cast turns 180.4999937 into 180.5 for race131/raw48, adding one point.
    """
    result = arena_stat60(base_stat, raw_iv, nature_multiplier, stat)
    trace = result["trace"]
    core = _js_round_nonnegative(trace["core_unrounded"])
    alternate = _js_round_nonnegative(core * float(nature_multiplier) + trace["five_star_bonus"])
    result.update(candidate_id="captured_stat60_precision_bounds_v1", stat_values=sorted({result["stat_value"], alternate}),
                  source={"kind": "local_capture_precision_hypotheses", "evidence_ref": "data/reference/live-panel-20261029.json",
                          "scope": "preserved owned PVP sample; no universal calibration claim"})
    trace["single_f32_alternate"] = alternate
    result["uncertainties"] = ["Neither precision path alone fits every captured dimension; keep both where they differ."]
    return result


def showdown_non_hp_stat60(base_stat, display_iv, nature_multiplier, stat):
    """Showdown's displayed non-HP expression; no implicit raw-IV conversion."""
    inputs = _stat_inputs(base_stat, display_iv, nature_multiplier, stat,
                          iv_name="display_iv", max_iv=10, allow_hp=False)
    iv_contribution = 3 * display_iv
    combined_base = base_stat + iv_contribution
    scaled_base = 1.1 * combined_base
    rounded_scaled_base = _js_round_nonnegative(scaled_base)
    core = rounded_scaled_base + 10
    nature_adjusted = core * float(nature_multiplier)
    rounded_nature = _js_round_nonnegative(nature_adjusted)
    value = rounded_nature + 50
    trace = {"iv_contribution": iv_contribution, "combined_base": combined_base,
             "scaled_base": scaled_base, "rounded_scaled_base": rounded_scaled_base,
             "starting_constant": 10, "core": core, "nature_adjusted": nature_adjusted,
             "rounded_nature": rounded_nature, "five_star_bonus": 50, "final": value,
             "rounding": "Math.round_nonnegative_binary64", "float32_casts": []}
    return _result("showdown_non_hp_stat60_v1", inputs, _SHOWDOWN_SOURCE, trace,
                   scope="level60_five_stars_non_hp_documented_expression", stat_value=value)


def _damage_inputs(attack, defense, effective_power, multiplier):
    inputs = dict(attack=attack, defense=defense, effective_power=effective_power, multiplier=multiplier)
    values = {k: _number(v, k, positive=k in ("attack", "defense")) for k, v in inputs.items()}
    return inputs, values


def _documented_level_damage(attack, defense, effective_power, multiplier, level, coefficient, source):
    """Documented Arena expression; nominal single-hit damage, never HP loss.

    The expression is evaluated in binary64 as A*P*M*(37/41), then Math.round,
    division by D and floor. This is a stated expression candidate, not a claim
    to reproduce all code paths of Arena's current damage implementation.
    """
    inputs, v = _damage_inputs(attack, defense, effective_power, multiplier)
    attack_power = _safe(v["attack"] * v["effective_power"], "attack*power")
    weighted_attack_power = _safe(attack_power * v["multiplier"], "attack*power*multiplier")
    numerator_unrounded = _safe(weighted_attack_power * coefficient, "level-scaled numerator")
    numerator = _js_round_nonnegative(numerator_unrounded)
    quotient = _safe(numerator / v["defense"], "damage quotient")
    damage = math.floor(quotient)
    trace = {"attack_power": attack_power, "weighted_attack_power": weighted_attack_power,
             "level": level, "coefficient_fraction": {"numerator": 37, "denominator": 41} if level == 60 else None,
             "coefficient_binary64": coefficient, "numerator_unrounded": numerator_unrounded,
             "coefficient_evaluated_before_multiplication": True,
             "numerator_rounded": numerator, "quotient": quotient, "nominal_damage": damage,
             "intermediate_power_rounding": False, "hp_clipping_applied": False,
             "final_multiplier_applied": False, "minimum_damage_applied": False}
    return _result("arena_documented_damage60_v1" if level == 60 else "native_world_level_damage_candidate_v1", inputs, source, trace,
                   scope="level60_single_hit_documented_expression" if level == 60 else "world_level_single_hit_candidate", nominal_damage=damage)


def arena_documented_damage60(attack, defense, effective_power, multiplier):
    """Preserve the existing level-60 expression and arithmetic order."""
    return _documented_level_damage(attack, defense, effective_power, multiplier, 60, 37 / 41, _ARENA_NOTES_SOURCE)


def native_world_level_damage(attack, defense, effective_power, multiplier, level, parameters, source):
    """Native level parameters combined with the existing arithmetic candidate."""
    _integer(level, "world level", 1, 60)
    magnitude = _number(parameters["level_magnitude"], "level magnitude", positive=True)
    addition = _number(parameters["level_add"], "level addition", positive=True)
    denominator = _number(parameters["denominator"], "level denominator", positive=True)
    coefficient = (level * magnitude + addition) / denominator
    return _documented_level_damage(attack, defense, effective_power, multiplier, level, coefficient, source)


def showdown_documented_damage60(attack, defense, effective_power, multiplier):
    """Showdown documented expression, with no implicit final modifier.

    The displayed level coefficient (37/41) is evaluated first in binary64,
    then multiplied by A*Q. This does not rewrite it as sequential A*Q*37/41
    and claims no browser-code parity. Algebraic equivalence alone would not
    establish identical floating-point boundaries.
    """
    inputs, v = _damage_inputs(attack, defense, effective_power, multiplier)
    power_unrounded = _safe(v["effective_power"] * v["multiplier"], "display power")
    display_power = _js_round_nonnegative(power_unrounded)
    attack_power = _safe(v["attack"] * display_power, "attack*display power")
    coefficient = 37 / 41
    numerator_unrounded = _safe(attack_power * coefficient, "level-scaled numerator")
    numerator = _js_round_nonnegative(numerator_unrounded)
    quotient = _safe(numerator / v["defense"], "damage quotient")
    damage = math.floor(quotient)
    trace = {"display_power_unrounded": power_unrounded, "display_power": display_power,
             "attack_display_power": attack_power,
             "level": 60, "coefficient_fraction": {"numerator": 37, "denominator": 41},
             "coefficient_binary64": coefficient, "numerator_unrounded": numerator_unrounded,
             "coefficient_evaluated_before_multiplication": True,
             "numerator_rounded": numerator, "quotient": quotient, "nominal_damage": damage,
             "intermediate_power_rounding": True, "hp_clipping_applied": False,
             "final_multiplier_applied": False, "minimum_damage_applied": False}
    return _result("showdown_documented_damage60_v1", inputs, _SHOWDOWN_SOURCE, trace,
                   scope="level60_single_hit_documented_expression", nominal_damage=damage)


_CANDIDATES = {"arena_stat60_v1": arena_stat60, "showdown_non_hp_stat60_v1": showdown_non_hp_stat60,
               "arena_documented_damage60_v1": arena_documented_damage60,
               "showdown_documented_damage60_v1": showdown_documented_damage60}
CANDIDATE_IDS = tuple(_CANDIDATES)


def evaluate_candidate(candidate_id, inputs):
    """Require an explicit identity and complete inputs; never select a default."""
    if not isinstance(candidate_id, str) or candidate_id not in _CANDIDATES:
        raise ValueError("Unknown candidate; an explicit supported candidate ID is required")
    if not isinstance(inputs, dict):
        raise ValueError("Candidate inputs must be an object")
    try:
        return _CANDIDATES[candidate_id](**deepcopy(inputs))
    except TypeError as exc:
        raise ValueError("Candidate input fields are missing or unsupported") from exc
