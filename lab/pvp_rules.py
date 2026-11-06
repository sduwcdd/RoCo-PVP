"""The versioned rule entry point shared by HUD, web simulation and PVP RL."""
from copy import deepcopy
import json
import math
from pathlib import Path


RULES_PATH = Path(__file__).resolve().parents[1] / "data" / "rules" / "pvp-current.json"
def _validate_profile(profile):
    if not isinstance(profile, dict):
        raise ValueError("PVP profile must be an object")
    settings, battle, damage = (profile.get(key) for key in ("settings", "battle", "damage"))
    if any(not isinstance(value, dict) for value in (settings, battle, damage)):
        raise ValueError("PVP settings, battle and damage sections are required")
    if (not isinstance(profile.get("profile_id"), str) or not profile["profile_id"]
            or type(profile.get("version")) is not int or profile["version"] < 1
            or settings.get("profile_id") != profile["profile_id"]):
        raise ValueError("PVP profile version/identity is inconsistent")
    required = {"profile_id", "damage_candidate", "same_type_multiplier", "tie_break_side",
                "initial_energy", "source_mode", "multi_hit_power"}
    if (set(settings) != required or settings["damage_candidate"] != "hud_shared_current_v1"
            or settings["multi_hit_power"] != "source_power_per_hit"
            or settings["tie_break_side"] not in ("a", "b")
            or settings["source_mode"] != "patch2_components_then_bwiki"
            or type(settings["initial_energy"]) is not int or settings["initial_energy"] != 10):
        raise ValueError("Unsupported current PVP settings")
    for key in ("same_type_multiplier", "critical_multiplier"):
        value = damage.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError("Invalid PVP damage multiplier: " + key)
    if (damage.get("same_type_multiplier") != settings["same_type_multiplier"]
            or damage.get("power_basis") != settings["multi_hit_power"]
            or damage.get("runtime") != "lab.hud_damage_runtime"):
        raise ValueError("PVP damage and settings disagree")
    expected = {"team_size": 6, "initial_magic": 4, "max_round": 50,
                "pvp_id": 5001, "battle_config": 340005}
    if (battle.get("format") != "pvp6v6" or battle.get("victory_rule") != "pvp5001_four_magic"
            or any(type(battle.get(key)) is not int or battle[key] != value for key, value in expected.items())):
        raise ValueError("Unsupported PVP battle/source configuration")
    uncertainty = profile.get("uncertainty")
    if (not isinstance(uncertainty, dict) or uncertainty.get("unknown_mechanisms") != "fail_closed"
            or uncertainty.get("calibrated") is not False or uncertainty.get("real_game_verified") is not False):
        raise ValueError("PVP uncertainty policy must remain explicit and fail closed")
    return profile


_PROFILE = _validate_profile(json.loads(RULES_PATH.read_text(encoding="utf-8")))
PROFILE_ID = _PROFILE["profile_id"]
DEFAULT_SETTINGS = deepcopy(_PROFILE["settings"])
SAME_TYPE_MULTIPLIER = _PROFILE["damage"]["same_type_multiplier"]
CRITICAL_MULTIPLIER = _PROFILE["damage"]["critical_multiplier"]
TEAM_SIZE = _PROFILE["battle"]["team_size"]
INITIAL_MAGIC = _PROFILE["battle"]["initial_magic"]
MAX_ROUND = _PROFILE["battle"]["max_round"]
PVP_ID = _PROFILE["battle"]["pvp_id"]
BATTLE_CONFIG = _PROFILE["battle"]["battle_config"]


def load_pvp_rules():
    """Return an owned copy; callers cannot modify the active process profile."""
    return deepcopy(_PROFILE)
